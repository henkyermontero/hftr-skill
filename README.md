# hftr

Ranked public replies from the last 30 days, by topic or `@handle`.

```
/hftr ufc
/hftr bitcoin
/hftr @elonmusk       # what he replied
/hftr to:@elonmusk    # what landed on him
```

```
HFTR · 30 days · world cup · snapshot · capped
cache frozen 2026-09-01T00:01:06+00:00 · 565 of 565 rows still in-window

 1  ▲1,234  @_I_am_Randy  x  → @theMadridZone
    But we need the intense investigation about the FIFA World Cup tournament…
    Parent https://x.com/i/web/status/2083518685403050428 · Reply https://x.com/…
```

One row per author, every row in-window, every row linked to the original.
It answers one question: **which replies landed.** For "what happened across
the internet", use [last30days](https://github.com/mvanhorn/last30days-skill) —
different job, don't bolt them together.

## Two modes

**Live — the one that scales.** Most topics nobody has ever collected, so the
real answer comes from searching X now. That needs either:

- `AUTH_TOKEN` / `CT0` in the environment or `~/.config/last30days/.env` on the
  machine running the skill, **or**
- an X search tool in your agent host. When the script has no cookies it exits
  0 with a `NO_CREDS` line naming the exact query to run, and `SKILL.md` tells
  the host how to format the results the same way.

So a Grok Bot with no cookies still answers a live topic - the host does the
search, the skill supplies the rules.

**Snapshot cache — free, instant, and dated.** A static file on GitHub raw
holds queries collected earlier. It is tried first because it costs nothing and
is always awake, not because it is the product: it does not grow, it names its
freeze date on every render, and a row leaves it once that row ages out of the
window. Aged rows stay in the file and are readable with `--archive`. A cache
miss is a fact about the cache, never about the world.

## Install

Agent Skills host (Claude Code, Codex, Cursor, Gemini CLI):

```bash
npx skills add henkyermontero/hftr-skill -g
```

Grok Build CLI:

```bash
grok plugin install henkyermontero/hftr-skill
```

Manual: copy this folder into your host's skills directory. No keys, no
dependencies — Python 3 standard library and one HTTP GET.

## Grok Bot recipe

1. Install the skill globally as above.
2. Register it so `/hftr` resolves in the chat.
3. Name the bot **here-for-the-replies**, described as: *ranked public replies
   from the last 30 days by topic or @handle. Not a research brief.*
4. Run `/hftr world cup` and confirm you get rows, or an honest empty result.
5. Do not install last30days inside this bot "to help". If the board has no
   in-window replies, the correct answer is that nobody landed one.

## Configuration

| variable | default | what it does |
|---|---|---|
| `HFTR_BASE_URL` | unset | Your own board server, used as a middle hop between the snapshot and live X search. There is no shared hosted board; unset is the normal case. |
| `HFTR_SNAPSHOT_URL` | this repo's `data/board.json` on GitHub raw | Where the static board is read from. |
| `AUTH_TOKEN` / `CT0` | unset | **Your own** X session cookies, for live search when the snapshot has nothing. Read from the environment or `~/.config/last30days/.env`. Without them the skill prints a `NO_CREDS` line naming the exact search for your host to run. |

## Direct use

```bash
python3 scripts/hftr.py --q "ufc"
python3 scripts/hftr.py --q "@elonmusk" --days 7
python3 scripts/hftr.py --q "world cup" --raw      # uncapped
python3 scripts/hftr.py --q "world cup" --json     # raw payload
python3 scripts/hftr.py --q "bitcoin" --archive    # cached rows that aged out
```

Exit codes: `0` success, including an honest empty result and the `NO_CREDS`
handoff. `2` only when nothing answered at all: the snapshot could not be
fetched, no board payload came back, and live search produced no rows.

## The cache, and its age

The script reads `data/board.json` from GitHub raw first, purely for speed.
Every render says where the rows came from and how old that source is:

```
HFTR · 30 days · bitcoin · snapshot · capped
cache frozen 2026-09-01T00:01:06+00:00 · 565 of 565 rows still in-window
```

Two counts, two meanings. `N of M still in-window` is the health of the whole
file. `0 in-window for this query` is about your query. When the cache holds
only aged rows for a query, it says so and points at `--archive` rather than
pretending nobody replied. Queries it never captured fall through to
`HFTR_BASE_URL` if you set one, then to live search.

Refresh the snapshot against a board you run (set `HFTR_BASE_URL` to it):

```bash
python3 scripts/build_snapshot.py     # writes data/board.json
git commit -am "snapshot" && git push
```

It is deliberately not wired into the ingest cron: nothing about this may ever
change that job's exit code.

## When the cache has never heard of it

If the snapshot and the optional board API both come up empty, the script runs
**one** read-only X and Reddit search for public replies in the window and
labels the header `live`. Those rows are shown, not stored: no ranking changes
and nothing is written to any database.

That step needs `AUTH_TOKEN` / `CT0` in the environment or in
`~/.config/last30days/.env`. Without them you get "looked, no credential for
live search" and an honest empty. Use `--no-live` to skip the step entirely.

## The optional board API

If you set `HFTR_BASE_URL` to a board server you run, the script asks it:

```
GET /api/board?q=&days=30&limit=12&cap_author=1
```

There is no shared public board and no default. Unset simply skips that hop.

MIT.
