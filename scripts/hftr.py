#!/usr/bin/env python3
"""Fetch ranked public replies from the Here for the Replies board.

Standard library only, one HTTP GET, no keys. It reads the same API the website
reads, so the skill and the site can never disagree about what landed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BASE = "https://here-for-the-replies.onrender.com"
TIMEOUT = 20
MAX_ROWS = 12


def base_url() -> str:
    return (os.getenv("HFTR_BASE_URL") or DEFAULT_BASE).rstrip("/")


def fetch(q: str, days: int, limit: int, cap_author: int) -> dict:
    params = urllib.parse.urlencode({
        "q": q, "days": days, "limit": limit, "cap_author": cap_author,
    })
    url = f"{base_url()}/api/board?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "hftr-skill/0.1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def one_line(text: str, width: int = 160) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= width else t[:width].rstrip() + "…"


def render(payload: dict) -> str:
    q = payload.get("query") or ""
    days = payload.get("window_days", 30)
    rows = payload.get("rows") or []
    head = f"HFTR · last {days} days · {q}"
    if payload.get("mode") == "author":
        head += " · author"
    elif payload.get("capped"):
        head += " · capped"

    if not rows:
        return (f"{head}\nNo replies in-window. Not last month's leftovers.")

    out = [head]
    updated = payload.get("updated_at")
    if updated:
        out.append(f"updated {updated}")
    out.append("")
    for i, r in enumerate(rows[:MAX_ROWS], start=1):
        parent = r.get("parent_handle") or "—"
        likes = int(r.get("like_count") or 0)
        out.append(f"{i:>2}  ▲{likes:,}  @{r.get('author','')}  "
                   f"{r.get('source','')}  → @{parent}")
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
    args = ap.parse_args(argv)

    try:
        payload = fetch(args.q, args.days, min(args.limit, 25),
                        0 if args.raw else 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            print("HFTR: rate limited (60 requests/minute). Try again shortly.",
                  file=sys.stderr)
        else:
            print(f"HFTR: board unreachable (HTTP {exc.code}; it may be waking).",
                  file=sys.stderr)
        return 2
    except Exception:
        # Free hosting sleeps; say so in one line rather than dumping a trace.
        print("HFTR: board unreachable (it may be waking). Try again in a minute.",
              file=sys.stderr)
        return 2

    print(json.dumps(payload, indent=2) if args.json else render(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
