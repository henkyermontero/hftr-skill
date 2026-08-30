#!/usr/bin/env python3
"""Last resort: ask X directly for replies the board has never collected.

Only runs when the snapshot and the live API both come back empty. Standard
library only, read-only, and it never writes to the HFTR database - a live hit
is shown once and labelled, not silently promoted to a board row.

Credentials: AUTH_TOKEN / CT0 from the environment, or from
~/.config/last30days/.env if that file already exists on this machine. With
neither, this module says so and returns nothing. It never opens a login page
and never asks for a password.

The request shape (endpoint, headers, feature flags) follows the public
web client, the same protocol the MIT-licensed @steipete/bird client documents.
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

BEARER = ("AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
          "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA")
API = "https://x.com/i/api/graphql"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126 Safari/537.36")
TIMEOUT = 25
# Known-good SearchTimeline ids, tried if discovery fails.
FALLBACK_QUERY_IDS = ("M1jEez78PEfVfbQLvlWMvQ", "5h0kNbk3ii97rmfY6CdgAA",
                      "Tp1sewRU1AsZpBWhqCZicQ")

FEATURES = {
    "rweb_video_screen_enabled": False,
    "profile_label_improvements_pcf_label_in_post_enabled": True,
    "rweb_tipjar_consumption_enabled": True,
    "verified_phone_label_enabled": False,
    "creator_subscriptions_tweet_preview_api_enabled": True,
    "responsive_web_graphql_timeline_navigation_enabled": True,
    "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
    "premium_content_api_read_enabled": False,
    "communities_web_enable_tweet_community_results_fetch": True,
    "c9s_tweet_anatomy_moderator_badge_enabled": True,
    "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
    "responsive_web_grok_analyze_post_followups_enabled": True,
    "responsive_web_jetfuel_frame": False,
    "responsive_web_grok_share_attachment_enabled": True,
    "articles_preview_enabled": True,
    "responsive_web_edit_tweet_api_enabled": True,
    "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
    "view_counts_everywhere_api_enabled": True,
    "longform_notetweets_consumption_enabled": True,
    "responsive_web_twitter_article_tweet_consumption_enabled": True,
    "tweet_awards_web_tipping_enabled": False,
    "responsive_web_grok_show_grok_translated_post": False,
    "responsive_web_grok_analysis_button_from_backend": True,
    "creator_subscriptions_quote_tweet_preview_enabled": False,
    "freedom_of_speech_not_reach_fetch_enabled": True,
    "standardized_nudges_misinfo": True,
    "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
    "longform_notetweets_rich_text_read_enabled": True,
    "longform_notetweets_inline_media_enabled": True,
    "responsive_web_grok_image_annotation_enabled": True,
    "responsive_web_enhance_cards_enabled": False,
}


class NoCredentials(RuntimeError):
    """No cookies on this machine. Not an error: just nothing we can do."""


def credentials() -> dict[str, str]:
    creds = {k: os.getenv(k, "").strip() for k in ("AUTH_TOKEN", "CT0")}
    if all(creds.values()):
        return creds
    env = Path.home() / ".config/last30days/.env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                if k.strip() in ("AUTH_TOKEN", "CT0") and not creds.get(k.strip()):
                    creds[k.strip()] = v.strip()
    if not all(creds.get(k) for k in ("AUTH_TOKEN", "CT0")):
        raise NoCredentials
    return creds


def _fetch(url: str, headers: dict | None = None, data: bytes | None = None,
           timeout: int = TIMEOUT) -> str:
    req = urllib.request.Request(
        url, data=data, method="POST" if data else "GET",
        headers=headers or {"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return raw.decode("utf-8", "replace")


def query_ids() -> list[str]:
    """The SearchTimeline id, read from the public web bundle, then fallbacks."""
    ids: list[str] = []
    try:
        html = _fetch("https://x.com/explore", timeout=12)
        bundles = dict.fromkeys(re.findall(
            r"https://abs\.twimg\.com/responsive-web/client-web[^\"']+\.js", html))
        for b in list(bundles)[:12]:
            try:
                js = _fetch(b, timeout=10)
            except Exception:
                continue
            m = re.search(r'queryId:"([^"]+)",operationName:"SearchTimeline"', js)
            if m:
                ids.append(m.group(1))
                break
    except Exception:
        pass
    return ids + [q for q in FALLBACK_QUERY_IDS if q not in ids]


def _headers(creds: dict[str, str]) -> dict[str, str]:
    return {
        "accept": "*/*", "accept-language": "en-US,en;q=0.9",
        "authorization": f"Bearer {BEARER}",
        "x-csrf-token": creds["CT0"],
        "x-twitter-auth-type": "OAuth2Session",
        "x-twitter-active-user": "yes",
        "x-twitter-client-language": "en",
        "x-client-uuid": str(uuid.uuid4()),
        "x-client-transaction-id": os.urandom(16).hex(),
        "cookie": f"auth_token={creds['AUTH_TOKEN']}; ct0={creds['CT0']}",
        "user-agent": UA, "content-type": "application/json",
        "Accept-Encoding": "gzip",
    }


def _tweets(instructions: list[dict]):
    """Search returns bare items and conversation modules; walk both."""
    for ins in instructions:
        for entry in ins.get("entries") or []:
            content = entry.get("content") or {}
            r = (content.get("itemContent") or {}).get("tweet_results", {}).get("result")
            if r:
                yield r
            for item in content.get("items") or []:
                r = ((item.get("item") or {}).get("itemContent") or {}) \
                    .get("tweet_results", {}).get("result")
                if r:
                    yield r


def _row(result: dict) -> dict[str, Any] | None:
    result = result.get("tweet") or result
    legacy = result.get("legacy") or {}
    if not legacy.get("in_reply_to_status_id_str"):
        return None                     # replies only, same as the board
    core = ((result.get("core") or {}).get("user_results") or {}).get("result") or {}
    author = ((core.get("core") or {}).get("screen_name")
              or (core.get("legacy") or {}).get("screen_name") or "")
    text = (legacy.get("full_text") or "").strip()
    likes = int(legacy.get("favorite_count") or 0)
    if not author or not text or likes < 1:
        return None                     # a row needs a voice and some signal
    created = legacy.get("created_at") or ""
    try:
        when = dt.datetime.strptime(created, "%a %b %d %H:%M:%S %z %Y")
    except ValueError:
        return None
    parent_id = legacy.get("in_reply_to_status_id_str")
    parent = legacy.get("in_reply_to_screen_name") or ""
    if not parent and text.startswith("@"):
        parent = text[1:].split()[0].rstrip(",:.!?") if len(text) > 1 else ""
    tid = result.get("rest_id") or legacy.get("id_str") or ""
    return {
        "author": author, "source": "x", "like_count": likes, "text": text,
        "topic": "", "created_at": when.isoformat(),
        "parent_handle": parent or None,
        "parent_url": f"https://x.com/i/web/status/{parent_id}" if parent_id else None,
        "reply_url": f"https://x.com/{author}/status/{tid}" if tid else "",
        "permalink": None,
    }


def search_replies(query: str, days: int = 30, limit: int = 25) -> list[dict[str, Any]]:
    """In-window public replies matching a query. Raises NoCredentials if we
    have no cookies; returns [] when X simply has nothing."""
    creds = credentials()
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    variables = {
        "rawQuery": f"{query} filter:replies since:{since}",
        "count": min(max(limit * 2, 20), 50),
        "querySource": "typed_query", "product": "Top",
    }
    params = urllib.parse.urlencode({"variables": json.dumps(variables)})
    body = None
    for qid in query_ids():
        url = f"{API}/{qid}/SearchTimeline?{params}"
        payload = json.dumps({"features": FEATURES, "queryId": qid}).encode()
        try:
            body = _fetch(url, _headers(creds), payload)
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 404):     # stale query id, try the next one
                continue
            raise
    if body is None:
        return []
    data = json.loads(body)
    if data.get("errors"):
        return []
    instructions = (data.get("data", {}).get("search_by_raw_query", {})
                    .get("search_timeline", {}).get("timeline", {})
                    .get("instructions", []))
    now = dt.datetime.now(dt.timezone.utc)
    rows = []
    for result in _tweets(instructions):
        row = _row(result)
        if not row:
            continue
        when = dt.datetime.fromisoformat(row["created_at"])
        if (now - when).total_seconds() > days * 86400:
            continue
        rows.append(row)
    rows.sort(key=lambda r: -r["like_count"])
    return rows[:limit]
