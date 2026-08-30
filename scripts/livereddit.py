#!/usr/bin/env python3
"""Best-effort live Reddit comments for a query the board has not collected.

Reddit's public JSON needs no key, but it aggressively blocks clients it does
not like: from some networks every endpoint answers 403 Blocked (it does from
the machine this was written on). That is not an error to shout about - the
skill simply gets nothing from Reddit there and still answers from X and the
board. Where Reddit does answer, these rows join the live result.

Standard library only, read-only, nothing is written to the HFTR database.
"""

from __future__ import annotations

import datetime as dt
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
TIMEOUT = 12
BLOCKED_CODES = (403, 429)


class Unavailable(RuntimeError):
    """Reddit refused us. Expected on many networks; never fatal."""


def _get(url: str, timeout: int = TIMEOUT) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        if exc.code in BLOCKED_CODES:
            raise Unavailable(f"reddit returned {exc.code}") from exc
        raise
    except Exception as exc:
        raise Unavailable(str(exc)[:60]) from exc


def _row(c: dict[str, Any]) -> dict[str, Any] | None:
    body = (c.get("body") or "").strip()
    author = (c.get("author") or "").strip()
    score = int(c.get("score") or 0)
    if not body or not author or author == "[deleted]" or score < 1:
        return None
    created = c.get("created_utc")
    when = (dt.datetime.fromtimestamp(created, dt.timezone.utc)
            if created else None)
    permalink = c.get("permalink") or ""
    return {
        "author": author, "source": "reddit", "like_count": score,
        "text": body, "topic": c.get("subreddit") or "",
        "created_at": when.isoformat() if when else None,
        "parent_handle": None,
        "parent_url": (f"https://www.reddit.com{c['link_permalink']}"
                       if c.get("link_permalink") else
                       (c.get("link_url") or None)),
        "reply_url": f"https://www.reddit.com{permalink}" if permalink else "",
        "permalink": None,
        "context": (c.get("link_title") or "")[:300],
    }


def search_comments(query: str, days: int = 30, limit: int = 25) -> list[dict[str, Any]]:
    """Top comments matching a query in the window. Raises Unavailable when
    Reddit refuses; returns [] when it answers with nothing."""
    window = "month" if days > 7 else "week"
    url = "https://www.reddit.com/search.json?" + urllib.parse.urlencode({
        "q": query, "type": "comment", "sort": "top", "t": window,
        "limit": min(max(limit * 2, 25), 100),
    })
    data = _get(url)
    children = (data.get("data") or {}).get("children") or []
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    for child in children:
        if child.get("kind") != "t1":          # t1 = comment
            continue
        row = _row(child.get("data") or {})
        if not row or not row["created_at"]:
            continue
        when = dt.datetime.fromisoformat(row["created_at"])
        if (now - when).total_seconds() > days * 86400:
            continue
        rows.append(row)
    rows.sort(key=lambda r: -r["like_count"])
    return rows[:limit]


if __name__ == "__main__":
    import sys
    try:
        for r in search_comments(" ".join(sys.argv[1:]) or "bitcoin"):
            print(f"▲{r['like_count']:<6} u/{r['author']:<18} {r['text'][:60]!r}")
    except Unavailable as exc:
        print(f"reddit unavailable: {exc}")
