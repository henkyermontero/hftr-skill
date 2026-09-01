#!/usr/bin/env python3
"""Build data/board.json: a static copy of the in-window board.

Why: the board runs on free hosting that sleeps, so a stranger's first `/hftr`
call can otherwise wait ~50s on a cold start. The snapshot is served from
GitHub raw, which is always awake, and the live API stays the second hop.

Run it by hand (or from any job that is allowed to fail) while the site is
awake. It is deliberately NOT wired into the ingest cron: nothing here may ever
change that job's exit code.

    python3 scripts/build_snapshot.py            # write data/board.json
    python3 scripts/build_snapshot.py --dry-run  # show what it would fetch
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# The board to copy. There is no shared public board any more, so this only
# does anything when HFTR_BASE_URL names one you run.
BASE = (os.getenv("HFTR_BASE_URL") or "").rstrip("/")
OUT = Path(__file__).resolve().parents[1] / "data" / "board.json"
TIMEOUT = 60
PER_QUERY = 25

# Every chip the site shows, plus the catch-all board. Authors come from
# whoever is actually on the board, so the list stays true as it changes.
FALLBACK_TOPICS = [
    "world cup", "champions league", "premier league", "super bowl",
    "nfl mahomes", "nba finals", "mlb world series", "ufc", "f1 grand prix",
    "max verstappen", "taylor swift", "kardashian", "elonmusk", "bitcoin",
]
TOP_AUTHORS = 12


def get(path: str) -> dict | list:
    url = f"{BASE}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "hftr-snapshot/0.1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def board(q: str, limit: int = PER_QUERY) -> dict:
    return get("/api/board?" + urllib.parse.urlencode(
        {"q": q, "days": 30, "limit": limit, "cap_author": 1}))


def topics() -> list[str]:
    """The topic strings the board actually stores.

    Chip LABELS ("soccer") are keyword categories, not stored topics, so they
    match nothing through ?q=. The real topics come from /stats.
    """
    try:
        stats = get("/stats")
        live = [t["topic"].lower() for t in stats.get("trending_topics", [])
                if t.get("topic")]
        return live or FALLBACK_TOPICS
    except Exception:
        return FALLBACK_TOPICS


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--base", default=None)
    args = ap.parse_args(argv)
    global BASE
    if args.base:
        BASE = args.base.rstrip("/")

    if not BASE:
        # Refusing beats writing an empty file over a good archive.
        print("build_snapshot: no board to copy. Set HFTR_BASE_URL to a board "
              "server you run. The existing snapshot is left untouched.",
              file=sys.stderr)
        return 1

    queries = ["", *topics()]
    if args.dry_run:
        print("would fetch:", ", ".join(repr(q) for q in queries))
        return 0

    # NOTE: no "generated_at" field. It changed on every run, so the committed
    # file differed even when the board did not, and the workflow's
    # commit-only-if-changed guard could never fire. Build time is reported
    # below and recorded by the commit itself; `updated_at` (when the board was
    # last ingested) is the timestamp that actually means something.
    built_at = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    snapshot: dict = {
        "updated_at": None,
        "window_days": 30,
        "capped": True,
        "source": BASE,
        "queries": {},
        "rows": [],
    }
    seen: set[str] = set()

    def absorb(key: str, payload: dict) -> None:
        rows = payload.get("rows") or []
        snapshot["queries"][key] = rows
        snapshot["updated_at"] = snapshot["updated_at"] or payload.get("updated_at")
        for r in rows:
            u = r.get("reply_url") or ""
            if u and u not in seen:
                seen.add(u)
                snapshot["rows"].append(r)

    for q in queries:
        for attempt in range(3):
            try:
                payload = board(q or "")
                absorb(q.strip().lower(), payload)
                print(f"  {q or '(all)':<22} {len(payload.get('rows') or [])} rows")
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 2:
                    # The API allows 60/min and a full snapshot brushes that.
                    # Without this a throttled run silently drops topics, and
                    # the file differs from the last one for no real reason.
                    print(f"  {q!r}: rate limited, waiting", file=sys.stderr)
                    time.sleep(20)
                    continue
                print(f"  skip {q!r}: HTTP {exc.code}", file=sys.stderr)
                break
            except Exception as exc:
                print(f"  skip {q!r}: {type(exc).__name__}", file=sys.stderr)
                break

    # A handful of author pages, chosen from who is actually on the board.
    authors: list[tuple[str, str]] = []
    for r in snapshot["rows"]:
        pair = (r.get("source") or "", r.get("author") or "")
        if all(pair) and pair not in authors:
            authors.append(pair)
        if len(authors) >= TOP_AUTHORS:
            break
    for source, name in authors:
        q = f"@{name}" if source == "x" else f"{source}:{name}"
        for attempt in range(3):
            try:
                payload = board(q)
                absorb(f"@{name.lower()}", payload)
                print(f"  {q:<22} {len(payload.get('rows') or [])} rows")
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt < 2:
                    # The API allows 60/min; a full snapshot brushes that.
                    print(f"  {q}: rate limited, waiting", file=sys.stderr)
                    time.sleep(20)
                    continue
                print(f"  skip {q}: HTTP {exc.code}", file=sys.stderr)
                break
            except Exception as exc:
                print(f"  skip {q}: {type(exc).__name__}", file=sys.stderr)
                break

    # The All view: if the deployed API cannot answer a blank query yet, build
    # it from the rows we already have, with the same cap rule the site uses.
    # Same rows, same ordering - just assembled here instead of there.
    if not snapshot["queries"].get(""):
        pool = sorted(snapshot["rows"], key=lambda r: -(r.get("like_count") or 0))
        allrows, seen_authors = [], set()
        for r in pool:
            key = ((r.get("source") or "").lower(), (r.get("author") or "").lower())
            if key in seen_authors:
                continue
            seen_authors.add(key)
            allrows.append(r)
            if len(allrows) >= PER_QUERY:
                break
        snapshot["queries"][""] = allrows
        print(f"  (all) assembled locally: {len(allrows)} rows")

    if not snapshot["rows"]:
        print("refusing to write an empty snapshot", file=sys.stderr)
        return 1

    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text())
        except Exception:
            previous = {}
        was, now_ = len(previous.get("rows") or []), len(snapshot["rows"])
        if was and now_ < was * 0.8:
            # A run degraded by rate limits or a half-awake board must not
            # replace a good snapshot with a thinner one. Rows aging out of the
            # window is gradual; a 20% collapse in one run is a failure.
            print(f"refusing to shrink the snapshot: {was} -> {now_} rows",
                  file=sys.stderr)
            return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    # Sorted keys so an identical board always produces an identical file -
    # the workflow's commit-only-if-changed guard depends on it.
    OUT.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1,
                              sort_keys=True))
    kb = OUT.stat().st_size / 1024
    print(f"\nwrote {OUT} · {len(snapshot['rows'])} unique rows · "
          f"{len(snapshot['queries'])} queries · {kb:.0f} KB")
    print(f"board updated_at: {snapshot['updated_at']}")
    print(f"built at:         {built_at}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
