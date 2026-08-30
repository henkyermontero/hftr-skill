#!/usr/bin/env python3
"""Fetch ranked public replies from the Here for the Replies board.

Two hops, fastest first:

  1. the snapshot on GitHub raw - always awake, answers in well under a second
  2. the live API - fresher, but on free hosting that sleeps

Standard library only, no keys. Rows are only ever a copy of what the board
already stored: nothing here scrapes, and nothing here invents a row.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import re
import urllib.request

DEFAULT_BASE = "https://here-for-the-replies.onrender.com"
SNAPSHOT_URL = ("https://raw.githubusercontent.com/henkyermontero/hftr-skill"
                "/main/data/board.json")
SNAPSHOT_TIMEOUT = 8
API_TIMEOUT = 20
# When the snapshot already answered "nothing here", the live board is only a
# second opinion - we do not make the user wait out a cold start for it.
API_TIMEOUT_AFTER_SNAPSHOT = 6
MAX_ROWS = 12


def base_url() -> str:
    return (os.getenv("HFTR_BASE_URL") or DEFAULT_BASE).rstrip("/")


def snapshot_url() -> str:
    return os.getenv("HFTR_SNAPSHOT_URL") or SNAPSHOT_URL


def _get(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "hftr-skill/0.2"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


# --- brand queries -----------------------------------------------------------
# A short brand name is also an ordinary word: "stripe" matched "a black stripe
# on the side" of some shorts and outranked a reply to @stripe. Evidence about
# who the reply addresses beats raw likes. Mirrors backend/app/relevance.py.

BRAND_ALIASES = {
    "stripe": {"stripe", "stripehq"},
    "openai": {"openai"},
    "grok": {"grok", "xai"},
    "tesla": {"tesla", "teslamotors"},
    "spacex": {"spacex"},
    "xai": {"xai", "grok"},
}
TIER_HANDLE, TIER_MENTION, TIER_WORD, TIER_SUBSTRING = 0, 1, 2, 3


def brand_for(query: str):
    q = normalize(query)
    return (q, BRAND_ALIASES[q]) if q in BRAND_ALIASES else None


def tier_of(row: dict, aliases: set) -> int:
    author = (row.get("author") or "").strip().lower()
    parent = (row.get("parent_handle") or "").strip().lower()
    if author in aliases or parent in aliases:
        return TIER_HANDLE
    text = (row.get("text") or "").lower()
    if any(f"@{a}" in text for a in aliases):
        return TIER_MENTION
    if any(re.search(rf"\b{re.escape(a)}\b", text) for a in aliases):
        return TIER_WORD
    return TIER_SUBSTRING


def rank_brand(rows: list[dict], query: str) -> list[dict]:
    found = brand_for(query)
    if not found:
        return rows
    _, aliases = found
    tiered = [(tier_of(r, aliases), -int(r.get("like_count") or 0), i, r)
              for i, r in enumerate(rows)]
    strong = [t for t in tiered if t[0] <= TIER_MENTION]
    keep = strong or tiered
    keep.sort(key=lambda t: (t[0], t[1], t[2]))
    return [t[3] for t in keep]


# --- matching ----------------------------------------------------------------

def normalize(q: str) -> str:
    return " ".join((q or "").strip().lower().split())


def is_identity(q: str) -> bool:
    q = (q or "").strip()
    return q.startswith("@") or q.lower().startswith("u/") or (
        ":" in q and q.split(":", 1)[0].lower()
        in {"x", "twitter", "reddit", "bluesky", "youtube"})


def identity_key(q: str) -> str:
    q = (q or "").strip().lstrip("@")
    if ":" in q:
        q = q.split(":", 1)[1]
    if q.lower().startswith("u/"):
        q = q[2:]
    return "@" + q.strip().lower()


def in_window(row: dict, days: int, now: dt.datetime) -> bool:
    """A snapshot ages. Never serve a row that has fallen out of the window."""
    created = row.get("created_at")
    if not created:
        return False
    try:
        when = dt.datetime.fromisoformat(created)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return (now - when).total_seconds() <= days * 86400


def cap_by_author(rows: list[dict], preserve_order: bool = False) -> list[dict]:
    """One row per (source, author) - same rule as the site.

    ``preserve_order`` keeps a brand ranking intact instead of re-sorting by
    likes, which would put the ambiguous word back on top.
    """
    out, seen = [], set()
    ordered = rows if preserve_order else sorted(
        rows, key=lambda r: -(r.get("like_count") or 0))
    for r in ordered:
        key = ((r.get("source") or "").lower(), (r.get("author") or "").lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def search_rows(rows: list[dict], q: str) -> list[dict]:
    """Substring match over what a person would actually search: the reply text,
    the topic it was filed under, who it answered, and who wrote it.

    This is why `grok` can find rows stored under another topic - the word is in
    the reply. It never reaches outside the board.
    """
    needle = normalize(q)
    if not needle:
        return []
    fields = ("text", "topic", "parent_handle", "author")
    stacks = [(r, " ".join(str(r.get(f) or "") for f in fields).lower()) for r in rows]
    hits = [r for r, hay in stacks if needle in hay]
    if hits:
        return hits
    # "grok bot" should still find a reply that says grok and bot, in any order.
    words = [w for w in needle.split() if len(w) > 2]
    if len(words) < 2:
        return []
    return [r for r, hay in stacks if all(w in hay for w in words)]


def from_snapshot(q: str, days: int) -> tuple[list[dict], dict | None]:
    try:
        snap = _get(snapshot_url(), SNAPSHOT_TIMEOUT)
    except Exception:
        return [], None
    now = dt.datetime.now(dt.timezone.utc)
    if is_identity(q):
        key = identity_key(q)
        rows = snap.get("queries", {}).get(key) or []
        if not rows:
            # "@handle" means replies BY that person. Falling back to a text
            # match would answer with everyone who mentioned them instead.
            handle = key.lstrip("@")
            rows = [r for r in (snap.get("rows") or [])
                    if (r.get("author") or "").lower() == handle]
    else:
        rows = snap.get("queries", {}).get(normalize(q)) or []
        if not rows:
            rows = search_rows(snap.get("rows") or [], q)
    rows = [r for r in rows if in_window(r, days, now)]
    if not is_identity(q):
        rows = rank_brand(rows, q)
    return cap_by_author(rows, preserve_order=bool(brand_for(q))), snap


def from_api(q: str, days: int, limit: int, cap: int,
             timeout: int = API_TIMEOUT) -> dict | None:
    params = urllib.parse.urlencode({"q": q, "days": days, "limit": limit,
                                     "cap_author": cap})
    try:
        return _get(f"{base_url()}/api/board?{params}", timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            print("HFTR: rate limited (60 requests/minute). Try again shortly.",
                  file=sys.stderr)
        return None
    except Exception:
        return None


# --- output ------------------------------------------------------------------

def one_line(text: str, width: int = 160) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= width else t[:width].rstrip() + "…"


def render(q: str, rows: list[dict], *, days: int, capped: bool, source: str,
           updated_at: str | None, mode: str) -> str:
    head = f"HFTR · last {days} days · {q}"
    head += " · author" if mode == "author" else (" · capped" if capped else " · raw")
    head += f" · {source}"
    if not rows:
        return f"{head}\nNo replies in-window. Not last month's leftovers."

    out = [head]
    if updated_at:
        out.append(f"board updated {updated_at}")
    out.append("")
    for i, r in enumerate(rows[:MAX_ROWS], start=1):
        parent = r.get("parent_handle") or "—"
        out.append(f"{i:>2}  ▲{int(r.get('like_count') or 0):,}  @{r.get('author','')}"
                   f"  {r.get('source','')}  → @{parent}")
        out.append(f"    {one_line(r.get('text', ''))}")
        links = []
        if r.get("parent_url"):
            links.append(f"Parent {r['parent_url']}")
        if r.get("reply_url"):
            links.append(f"Reply {r['reply_url']}")
        if links:
            out.append("    " + " · ".join(links))
        out.append("")
    return "\n".join(out).rstrip()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="hftr",
        description="Ranked public replies from the last 30 days, by topic or @handle.")
    ap.add_argument("--q", required=True, help="topic, or @handle / x:name / u/name")
    ap.add_argument("--days", type=int, default=30, choices=[7, 30])
    ap.add_argument("--limit", type=int, default=MAX_ROWS)
    ap.add_argument("--raw", action="store_true",
                    help="uncapped: allow several rows from the same account")
    ap.add_argument("--json", action="store_true", help="print the raw payload")
    ap.add_argument("--no-snapshot", action="store_true",
                    help="skip the snapshot and ask the live board")
    args = ap.parse_args(argv)

    limit = min(args.limit, 25)
    mode = "author" if is_identity(args.q) else "topic"
    snap_rows: list[dict] = []
    snap = None

    # 1. snapshot: always awake, sub-second
    if not args.raw and not args.no_snapshot:
        snap_rows, snap = from_snapshot(args.q, args.days)
        if snap_rows:
            if args.json:
                print(json.dumps({"query": args.q, "mode": mode, "source": "snapshot",
                                  "window_days": args.days, "capped": True,
                                  "updated_at": (snap or {}).get("updated_at"),
                                  "count": len(snap_rows[:limit]),
                                  "rows": snap_rows[:limit]}, indent=2))
            else:
                print(render(args.q, snap_rows[:limit], days=args.days, capped=True,
                             source="snapshot", mode=mode,
                             updated_at=(snap or {}).get("updated_at")))
            return 0

    # 2. the live board: fresher, may need to wake up. If the snapshot already
    # loaded and simply had no match, we have a truthful answer in hand, so we
    # give the sleeping board a short window rather than a long one.
    payload = from_api(args.q, args.days, limit, 0 if args.raw else 1,
                       timeout=API_TIMEOUT_AFTER_SNAPSHOT if snap else API_TIMEOUT)
    if payload is None:
        if snap is None:
            print("HFTR: board unreachable (it may be waking). Try again in a minute.",
                  file=sys.stderr)
            return 2
        # snapshot answered, it simply had nothing for this query
        print(render(args.q, [], days=args.days, capped=not args.raw,
                     source="snapshot", mode=mode,
                     updated_at=(snap or {}).get("updated_at")))
        return 0

    rows = payload.get("rows") or []
    if args.json:
        payload["source"] = "live"
        print(json.dumps(payload, indent=2))
        return 0
    print(render(args.q, rows, days=payload.get("window_days", args.days),
                 capped=bool(payload.get("capped")), source="live",
                 mode=payload.get("mode", mode),
                 updated_at=payload.get("updated_at")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
