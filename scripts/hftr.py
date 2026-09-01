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
import html as _html
import re
import urllib.request

# No default board. The hosted one was retired on 2026-09-01: serving live
# handle lookups meant putting one person's X session cookies behind a public
# URL anyone could drive. The skill answers from the snapshot and from YOUR OWN
# X credentials instead. Point HFTR_BASE_URL at your own board server to
# re-enable this hop.
DEFAULT_BASE = ""
SNAPSHOT_URL = ("https://raw.githubusercontent.com/henkyermontero/hftr-skill"
                "/main/data/board.json")
SNAPSHOT_TIMEOUT = 8
API_TIMEOUT = 20
# When the snapshot already answered "nothing here", the live board is only a
# second opinion - we do not make the user wait out a cold start for it.
API_TIMEOUT_AFTER_SNAPSHOT = 6
# Both live sources run in parallel, so this is the wall clock for the pair.
LIVE_TIMEOUT = 25
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
    """A query about a person's own replies. "to:@name" is a different mode."""
    q = (q or "").strip()
    if to_target(q):
        return False
    return q.startswith("@") or q.lower().startswith("u/") or (
        ":" in q and q.split(":", 1)[0].lower()
        in {"x", "twitter", "reddit", "bluesky", "youtube"})


# "to:@handle" asks what landed ON someone; "@handle" asks what they said.
# The colon form works bare ("to:elonmusk"); the spaced form needs the @, so an
# ordinary topic like "on fire" or "to be honest" is never mistaken for a person.
TO_PATTERN = re.compile(
    r"^(?:replies\s+to|to|on)\s*(?::\s*@?|\s+@)\s*([A-Za-z0-9_]{1,15})$",
    re.IGNORECASE)


def to_target(q: str) -> str | None:
    """The handle a "replies to X" query is about, or None."""
    m = TO_PATTERN.match((q or "").strip())
    return m.group(1).lower() if m else None


def identity_key(q: str) -> str:
    q = (q or "").strip().lstrip("@")
    if ":" in q:
        q = q.split(":", 1)[1]
    if q.lower().startswith("u/"):
        q = q[2:]
    return "@" + q.strip().lower()


def x_author_target(q: str) -> str | None:
    """The X handle whose OWN replies are being asked for, or None.

    Used to pick X's ``from:`` operator. Reddit identities have no X handle to
    ask about, so they stay out of it.
    """
    q = (q or "").strip()
    if not is_identity(q):
        return None
    low = q.lower().lstrip("@")
    if low.startswith("u/") or low.startswith("reddit:"):
        return None
    return identity_key(q).lstrip("@")


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


def clean_text(text: str) -> str:
    """Entities come off the wire raw: "&amp;" must read as "&"."""
    return _html.unescape(text or "")


def strip_leading_handles(text: str, parent: str) -> str:
    """Drop the @mentions a reply opens with when the card already shows them.

    "@Chime_Fave iPhone 11 ke" under "→ @Chime_Fave" says the handle twice.
    Only leading mentions go, and only while the first one is the parent.
    """
    body = (text or "").strip()
    parent = (parent or "").strip().lstrip("@").lower()
    if not body or not parent or not body.startswith("@"):
        return body
    # Only the parent's own handle goes. Other mentions are content: dropping
    # "@stripe" from "@cline @stripe ..." would hide why the row is here.
    while body.startswith("@"):
        parts = body[1:].split(None, 1)
        head = parts[0].rstrip(",:.!?").lower()
        if head != parent:
            break
        if len(parts) < 2:
            return (text or "").strip()      # nothing but the parent: keep it
        body = parts[1].strip()
    return body or (text or "").strip()


# How far apart the words of a multi-word query may sit and still be about the
# same thing, and whether they may sit either side of a full stop.
#
# Measured, not guessed. On a real "grok bot" result set, allowing any distance
# inside a 7-word window kept both wrong rows - "an AI bot account that has grok
# write fan fiction", and "a safe, corporate chat bot. Grok has become..." where
# the two words are adjacent but belong to different sentences. Confining the
# match to one sentence with at most 2 words between neighbours keeps all 10
# genuine rows and drops both wrong ones.
NEAR_GAP = 2


def words_are_near(text: str, tokens: list[str]) -> bool:
    """Do the query's words sit together, in one sentence, in any order?

    "Grok Bot messes up" and "@bot The Grok app" both qualify - order does not
    matter, closeness does. A sentence boundary ends the match, because
    "corporate chat bot. Grok has become..." is two thoughts, not one topic.
    """
    for sentence in re.split(r"[.!?\n]+", text or ""):
        words = re.findall(r"[a-z0-9]+", sentence.lower())
        if not words:
            continue
        hits = []
        for i, w in enumerate(words):
            for t in tokens:
                if t == w or (len(t) >= 4 and t in w):
                    hits.append((i, t))
                    break
        if len({t for _, t in hits}) < len(set(tokens)):
            continue
        # Slide the smallest span that covers every token and check the gaps.
        need = len(set(tokens))
        left = 0
        seen: dict[str, int] = {}
        for right, (idx, tok) in enumerate(hits):
            seen[tok] = seen.get(tok, 0) + 1
            while len(seen) == need:
                span = [hits[i][0] for i in range(left, right + 1)]
                if all(b - a - 1 <= NEAR_GAP for a, b in zip(span, span[1:])):
                    return True
                out = hits[left][1]
                seen[out] -= 1
                if not seen[out]:
                    del seen[out]
                left += 1
    return False


def needs_exact_phrase(q: str) -> bool:
    """A query with a number means the number: "iphone 18" is not "iPhone 11".

    Loose all-words matching is fine for "grok bot"; it is wrong the moment a
    model number, year or version is involved.
    """
    q = (q or "").strip()
    if q.startswith('"') and q.endswith('"') and len(q) > 2:
        return True
    return any(ch.isdigit() for ch in q)


def matches_query(row: dict, q: str, *, text_only: bool = False) -> bool:
    """Does this row actually answer the query, not just share a thread with it?

    X search returns thread siblings, so a reply about broadband pricing can
    come back for "lg tv" because the CONVERSATION mentioned an LG TV. The card
    shows only the reply, so the reply itself has to carry the query - a reader
    cannot verify a row whose text never mentions what they asked for.
    """
    needle = normalize(q).strip('"')
    if not needle:
        return True
    text = str(row.get("text") or "").lower()
    if not text_only:
        hay = " ".join(str(row.get(f) or "") for f in
                       ("text", "topic", "parent_handle", "author")).lower()
        return needle in hay
    if needle in text:
        return True
    if needs_exact_phrase(q):
        return False                      # a numbered query means that number
    tokens = [t for t in needle.split() if len(t) > 1]
    if not tokens:
        return False
    if len(tokens) == 1:
        return tokens[0] in text
    return words_are_near(text, tokens)


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
    if hits or needs_exact_phrase(q):
        # A numbered query means that number. "iphone 18" must never fall back
        # to rows that merely say iphone and 18 somewhere.
        return hits
    # "grok bot" should still find a reply that says grok and bot, in any order.
    words = [w for w in needle.split() if len(w) > 2]
    if len(words) < 2:
        return []
    return [r for r, hay in stacks if all(w in hay for w in words)]


def rank_relevance(rows: list[dict], q: str) -> list[dict]:
    """Put rows that actually say the thing above rows that merely sit under it.

    Board rows carry the topic ingest filed them under, so a reply can be on the
    "World Cup 2026" board while its own text is about an edited video. Those
    are still replies that landed in that conversation - the parent link proves
    it - so they are demoted, not dropped. A brand query keeps its own stronger
    rule.
    """
    if brand_for(q):
        return rank_brand(rows, q)
    if is_identity(q) or not normalize(q):
        return rows
    scored = [(0 if matches_query(r, q, text_only=True) else 1,
               -(r.get("like_count") or 0), i, r) for i, r in enumerate(rows)]
    scored.sort(key=lambda t: (t[0], t[1], t[2]))
    return [t[3] for t in scored]


def from_snapshot(q: str, days: int) -> tuple[list[dict], dict | None]:
    try:
        snap = _get(snapshot_url(), SNAPSHOT_TIMEOUT)
    except Exception:
        return [], None
    now = dt.datetime.now(dt.timezone.utc)
    target = to_target(q)
    if target:
        # What landed ON this account: rows whose parent is that handle. Never
        # their own replies to themselves.
        rows = [r for r in (snap.get("rows") or [])
                if (r.get("parent_handle") or "").strip().lower() == target
                and (r.get("author") or "").strip().lower() != target]
        rows = [r for r in rows if in_window(r, days, now)]
        return cap_by_author(rows), snap
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
        rows = rank_relevance(rows, q)
    if is_identity(q):
        # Author mode is one person by definition: one row per author would
        # collapse their whole month into a single reply. Rows already arrive
        # newest-first, which is what this mode promises.
        return rows, snap
    return cap_by_author(rows, preserve_order=True), snap


def from_api(q: str, days: int, limit: int, cap: int,
             timeout: int = API_TIMEOUT) -> dict | None:
    """The live board, when one is configured. Skipped entirely otherwise -
    an unset HFTR_BASE_URL is the normal case, not a failure."""
    if not base_url():
        return None
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

def one_line(text: str, width: int = 240) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= width else t[:width].rstrip() + "…"


def who(row: dict) -> str:
    prefix = "u/" if (row.get("source") or "").lower() == "reddit" else "@"
    return f"{prefix}{row.get('author', '')}"


def render(q: str, rows: list[dict], *, days: int, capped: bool, source: str,
           updated_at: str | None, mode: str, links: bool = False) -> str:
    """A card per reply: who answered whom, what they said, what it earned.

    Deliberately quiet - no source column, no parent URL unless asked. The
    reply is the content; everything else is a label.
    """
    kind = ("to" if mode == "to" else
            "author" if mode == "author" else
            "capped" if capped else "raw")
    head = f"HFTR · {days} days · {q} · {source} · {kind}"
    if not rows:
        return f"{head}\nNo replies in-window. Not last month's leftovers."

    out = [head, ""]
    for i, r in enumerate(rows[:MAX_ROWS], start=1):
        parent = (r.get("parent_handle") or "").strip()
        author = (r.get("author") or "").strip()
        line = f"{i:>2}  {who(r)}"
        if parent and parent.lower() != author.lower():
            line += f" → @{parent}"
        out.append(line)
        body = strip_leading_handles(clean_text(r.get("text", "")), parent)
        out.append(f"    {one_line(body)}")
        tail = f"    ▲{int(r.get('like_count') or 0):,}"
        if r.get("reply_url"):
            tail += f" · {r['reply_url']}"
        if links and r.get("parent_url"):
            tail += f" · parent {r['parent_url']}"
        out.append(tail)
        out.append("")
    if updated_at:
        out.append(f"board updated {updated_at}")
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
                    help="skip the GitHub raw snapshot (next hop: HFTR_BASE_URL if set, else live search)")
    ap.add_argument("--links", action="store_true",
                    help="also print the parent post URL on each row")
    ap.add_argument("--no-live", action="store_true",
                    help="do not fall back to live X/Reddit search when nothing above answered")
    args = ap.parse_args(argv)

    limit = min(args.limit, 25)
    target = to_target(args.q)
    mode = "to" if target else ("author" if is_identity(args.q) else "topic")
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
                             source="board", mode=mode, links=args.links,
                             updated_at=(snap or {}).get("updated_at")))
            return 0

    def live_search(reason_out: list) -> list:
        """3. Ask the networks directly for a query the board never collected.

        X and Reddit run at the same time, so the slower one costs nothing. A
        source that has no credential, or that refuses us, drops out quietly -
        one working source still answers.
        """
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from concurrent.futures import ThreadPoolExecutor

        # Fetch a pool, not a page. Reply/phrase filtering removes most of what
        # a search returns, so asking for exactly `limit` rows leaves one card.
        pool_size = max(limit * 4, 25)
        notes, rows = [], []
        no_creds = []
        author_handle = x_author_target(args.q)

        def from_x():
            try:
                import livex
            except ImportError:
                return []
            try:
                return livex.search_replies(args.q, args.days, pool_size,
                                            to_handle=target,
                                            from_handle=author_handle)
            except livex.NoCredentials:
                no_creds.append(True)
                notes.append("X: no credential on this machine")
                return []
            except Exception:
                notes.append("X: unavailable")
                return []

        def from_reddit():
            try:
                import livereddit
            except ImportError:
                return []
            try:
                return livereddit.search_comments(args.q, args.days, pool_size)
            except Exception as exc:
                notes.append(f"Reddit: {exc}" if str(exc) else "Reddit: unavailable")
                return []

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(from_x), pool.submit(from_reddit)]
            for f in futures:
                try:
                    rows += f.result(timeout=LIVE_TIMEOUT)
                except Exception:
                    pass

        # The board rejects root posts and self-threads: a reply answers
        # SOMEONE ELSE. Live must apply the same rule, or a thread opener with
        # no parent handle - or one replying to itself - leads the card list.
        def is_real_reply(r: dict) -> bool:
            parent = (r.get("parent_handle") or "").strip().lower()
            if (r.get("source") or "") != "x":
                return bool(r.get("parent_url"))
            return bool(parent) and parent != (r.get("author") or "").strip().lower()

        rows = [r for r in rows if is_real_reply(r)]
        # The reply itself must carry the query. Search hands back thread
        # siblings, and a card showing a reply that never mentions what was
        # asked is unverifiable to whoever reads it.
        if target:
            rows = [r for r in rows
                    if (r.get("parent_handle") or "").strip().lower() == target]
        elif is_identity(args.q):
            # "@handle" asks what THEY replied. Search hands back the whole
            # conversation around a handle, so without this the author lane
            # answers the to: question instead - the exact opposite result.
            who = identity_key(args.q).lstrip("@")
            rows = [r for r in rows
                    if (r.get("author") or "").strip().lstrip("@").lower() == who]
        else:
            rows = [r for r in rows if matches_query(r, args.q, text_only=True)]

        if not rows:
            # Name every source we consulted, not only the ones that errored -
            # "Reddit: 403" alone reads as if X was never asked.
            detail = ("; ".join(notes)) if notes else "nothing matched"
            reason_out.append(f"looked at X and Reddit: {detail}")
            if no_creds:
                # A machine-readable handoff: this install cannot search X
                # itself, but the agent running it may be able to. Exit 0 -
                # "I cannot reach X" is an answer, not a crash.
                since = (dt.date.today() - dt.timedelta(days=args.days)).isoformat()
                if target:
                    subject = f"to:{target}"
                elif author_handle:
                    subject = f"from:{author_handle}"
                else:
                    subject = f'"{args.q}"'
                reason_out.append(
                    f'NO_CREDS · search with your own X tool: '
                    f'filter:replies {subject} since:{since} min_faves:1')
        if not target and not is_identity(args.q):
            rows = rank_brand(rows, args.q)
        if is_identity(args.q):
            return rows[:limit]
        return cap_by_author(rows, preserve_order=bool(brand_for(args.q)))[:limit]

    # 2. the live board: fresher, may need to wake up. If the snapshot already
    # loaded and simply had no match, we have a truthful answer in hand, so we
    # give the sleeping board a short window rather than a long one.
    payload = None if target else from_api(
        args.q, args.days, limit,
        0 if (args.raw or is_identity(args.q)) else 1,
        timeout=API_TIMEOUT_AFTER_SNAPSHOT if snap else API_TIMEOUT)
    if payload is None and snap is None:
        # Nothing answered at all: no snapshot, no board. Live search still gets
        # its turn below; only a total failure is worth an error exit.
        payload = None

    # An unreachable board is not the end of the answer - a sleeping Render
    # used to stop the run here, before live search ever got a turn.
    rows = (payload or {}).get("rows") or []
    if rows and not is_identity(args.q):
        # Same rule as the snapshot: a reply that names the topic outranks one
        # that was merely filed under it.
        rows = cap_by_author(rank_relevance(rows, args.q), preserve_order=True)

    # 3. Nothing on the board: look at X itself before saying no.
    note: list[str] = []
    if not rows and not args.no_live:
        fresh = live_search(note)
        if fresh:
            if args.json:
                print(json.dumps({"query": args.q, "mode": mode, "source": "live-x",
                                  "window_days": args.days, "capped": True,
                                  "on_board": False, "count": len(fresh),
                                  "rows": fresh}, indent=2))
            else:
                print(render(args.q, fresh, days=args.days, capped=True,
                             source="live", mode=mode,
                             updated_at=None, links=args.links))
            return 0

    if payload is None and snap is None and not rows:
        print("HFTR: board unreachable (it may be waking). Try again in a minute.",
              file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload or {"query": args.q, "count": 0, "rows": []},
                         indent=2))
        return 0
    out = render(args.q, rows, days=(payload or {}).get("window_days", args.days),
                 capped=bool((payload or {}).get("capped", not args.raw)),
                 source="board", mode=(payload or {}).get("mode", mode),
                 links=args.links,
                 updated_at=(payload or (snap or {})).get("updated_at"))
    if not rows and note:
        # Every note matters: the second one is the NO_CREDS handoff a host
        # needs in order to take over the search itself.
        out += "\n" + "\n".join(note)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
