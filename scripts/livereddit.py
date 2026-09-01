#!/usr/bin/env python3
"""Keyless live Reddit comments, for a query the cache has not collected.

Reddit's public JSON is closed. Measured 2026-09-01: every unauthenticated
`.json` endpoint answers 403 while reddit.com itself answers 200, and
old.reddit redirects a `.json` request to /login. That is an authentication
wall, not the network-reputation problem this file used to blame.

The technique below is cloned from the last30days skill (`reddit_rss.py`,
`reddit_shreddit.py`, `http.py`), which hit the same wall and mapped the way
around it. Two stages, both keyless:

  discovery   /search.rss?q=... returns POSTS (it ignores type=comment and
              carries no scores, so it cannot be the whole answer on its own).
  enrichment  /svc/shreddit/comments/r/{sub}/t3_{id} still serves 200 HTML with
              every comment as a <shreddit-comment> element whose start tag
              carries score / author / created / permalink, and whose body sits
              in a div keyed by the comment's thingId. Real scores, no key.

Requests are spaced by a token bucket, because the RSS endpoint 429s after a
single unthrottled burst.

Standard library only, read-only, nothing is written to the HFTR database.
"""

from __future__ import annotations

import datetime as dt
import html as _html
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# Reddit serves these surfaces to browsers. A library UA gets 403.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
SEARCH_URL = "https://www.reddit.com/search.rss"
SVC_URL = "https://www.reddit.com/svc/shreddit/comments/r/{sub}/t3_{pid}?sort=top"
FEED_TIMEOUT = 12
SVC_TIMEOUT = 9
# Each thread's HTML is several hundred KB, so this is the knob that decides
# whether the lane is fast or thorough. The live search as a whole has ~25s.
MAX_POSTS = 4
MAX_WORKERS = 4

_COMMENT_START = re.compile(r"<shreddit-comment(?=[\s>])[^>]*>")
_PARA = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_NEXT_RTJSON = re.compile(r'id="t1_[A-Za-z0-9]+-(?:comment|post)-rtjson-content"')
_POST_REF = re.compile(r"/r/([^/]+)/comments/([A-Za-z0-9]+)")


class Unavailable(RuntimeError):
    """Reddit refused us. Expected on some networks; never fatal."""


class _Bucket:
    """Token bucket, 5/sec with a burst of 5 - the spacing last30days settled
    on. One unthrottled burst is enough to get 429'd off the RSS endpoint."""

    def __init__(self, rate: float = 5.0, burst: int = 5) -> None:
        self.rate, self.burst = rate, float(burst)
        self.tokens, self.stamp = float(burst), time.monotonic()
        self.lock = threading.Lock()

    def take(self) -> None:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.burst, self.tokens + (now - self.stamp) * self.rate)
            self.stamp = now
            if self.tokens < 1.0:
                wait = (1.0 - self.tokens) / self.rate
            else:
                self.tokens -= 1.0
                return
        time.sleep(wait)
        with self.lock:
            self.tokens = max(0.0, self.tokens - 1.0)


_LIMITER = _Bucket()


def _get_text(url: str, timeout: int, accept: str) -> str:
    """Body as text, or "" on any failure. 429 is loud: it is the one error a
    caller can do something about (wait), and it must not read as "no results".
    """
    _LIMITER.take()
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise Unavailable("reddit rate-limited us (429)") from exc
        if exc.code == 403:
            raise Unavailable("reddit refused this client (403)") from exc
        return ""
    except Unavailable:
        raise
    except Exception:
        return ""


# --- stage 1: discovery ------------------------------------------------------

def find_posts(query: str, days: int = 30, limit: int = MAX_POSTS) -> list[tuple[str, str, str, str]]:
    """(subreddit, post_id, url, title) for posts matching the query.

    RSS is the only keyless search surface left. It returns posts, never
    comments, which is why stage 2 exists.
    """
    window = "month" if days > 7 else "week"
    url = (f"{SEARCH_URL}?" + urllib.parse.urlencode(
        {"q": query, "sort": "relevance", "t": window}))
    xml = _get_text(url, FEED_TIMEOUT, "application/atom+xml")
    if not xml:
        return []
    out, seen = [], set()
    for entry in re.findall(r"<entry>(.*?)</entry>", xml, re.S):
        m = re.search(r'<link href="([^"]+)"', entry)
        if not m:
            continue
        link = _html.unescape(m.group(1))
        ref = _POST_REF.search(link)
        if not ref or ref.group(2) in seen:
            continue
        seen.add(ref.group(2))
        title = re.search(r"<title>(.*?)</title>", entry, re.S)
        out.append((ref.group(1), ref.group(2), link,
                    _html.unescape(_TAG.sub("", title.group(1))).strip() if title else ""))
        if len(out) >= limit:
            break
    return out


# --- stage 2: comments, with real scores -------------------------------------

def _attr(tag: str, name: str) -> str:
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return _html.unescape(m.group(1)) if m else ""


def _body_for(html_text: str, thing_id: str) -> str:
    """A comment's own text, anchored on its thingId so nested replies do not
    get attributed to their parent, and bounded by the next comment's anchor so
    a parent does not swallow its children's text."""
    if not thing_id:
        return ""
    anchor = f'id="{thing_id}-post-rtjson-content"'
    idx = html_text.find(anchor)
    if idx == -1:
        return ""
    window = html_text[idx + len(anchor): idx + len(anchor) + 8000]
    nxt = _NEXT_RTJSON.search(window)
    if nxt:
        window = window[:nxt.start()]
    paras = _PARA.findall(window)
    if not paras:
        return ""
    return _WS.sub(" ", _html.unescape(_TAG.sub("", " ".join(paras)))).strip()


def parse_comments(html_text: str, sub: str, post_url: str, title: str) -> list[dict[str, Any]]:
    rows = []
    for m in _COMMENT_START.finditer(html_text or ""):
        tag = m.group(0)
        author = _attr(tag, "author") or "[deleted]"
        if author in ("[deleted]", "[removed]"):
            continue
        body = _body_for(html_text, _attr(tag, "thingId"))
        if not body or body in ("[deleted]", "[removed]"):
            continue
        try:
            score = int(_attr(tag, "score") or 0)
        except ValueError:
            score = 0
        if score < 1:
            continue
        created = _attr(tag, "created")
        try:
            when = dt.datetime.fromisoformat(created) if created else None
        except ValueError:
            when = None
        if when and when.tzinfo is None:
            when = when.replace(tzinfo=dt.timezone.utc)
        permalink = _attr(tag, "permalink")
        rows.append({
            "author": author, "source": "reddit", "like_count": score,
            "text": body, "topic": sub,
            "created_at": when.isoformat() if when else None,
            "parent_handle": None,
            "parent_url": post_url,
            "reply_url": f"https://www.reddit.com{permalink}" if permalink else "",
            "permalink": None,
            "context": title[:300],
        })
    return rows


def search_comments(query: str, days: int = 30, limit: int = 25) -> list[dict[str, Any]]:
    """Top in-window Reddit comments for a query. Raises Unavailable when
    Reddit refuses; returns [] when it answers with nothing."""
    posts = find_posts(query, days)
    if not posts:
        return []
    now = dt.datetime.now(dt.timezone.utc)
    rows: list[dict[str, Any]] = []
    blocked: list[Unavailable] = []

    def one(post):
        sub, pid, url, title = post
        try:
            html_text = _get_text(SVC_URL.format(sub=sub, pid=pid), SVC_TIMEOUT, "text/html")
        except Unavailable as exc:
            blocked.append(exc)
            return []
        return parse_comments(html_text, sub, url, title)

    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(posts))) as pool:
        for fut in as_completed([pool.submit(one, p) for p in posts]):
            try:
                rows += fut.result()
            except Exception:
                pass

    if not rows and blocked:
        raise blocked[0]
    seen, kept = set(), []
    for r in rows:
        if not r["created_at"] or r["reply_url"] in seen:
            continue
        when = dt.datetime.fromisoformat(r["created_at"])
        if (now - when).total_seconds() > days * 86400:
            continue
        seen.add(r["reply_url"])
        kept.append(r)
    kept.sort(key=lambda r: -r["like_count"])
    return kept[:limit]


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]) or "bitcoin"
    try:
        found = search_comments(q)
        print(f"{len(found)} comments for {q!r}")
        for r in found[:8]:
            print(f"  ▲{r['like_count']:<6} u/{r['author']:<20} r/{r['topic']:<18} {r['text'][:60]!r}")
    except Unavailable as exc:
        print(f"reddit unavailable: {exc}")
