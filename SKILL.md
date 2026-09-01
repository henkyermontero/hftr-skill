---
name: hftr
description: Ranked public replies from the last 30 days for a topic or @handle. Use when asked for the best replies, most-liked comments, what landed on a topic this month, or to look up a specific account's replies. Answers from live X search (your own credentials, or your host's X tool) with a dated snapshot as a fast local cache. Do NOT use for a multi-source research brief of what happened - that is last30days.
---

# HFTR — which replies landed

One question: **which public replies landed on this topic or this @handle in
the last 30 days.** Ranked by likes, one row per author, every row linking to
the original.

## When to use

- "best replies", "most-liked comments", "what landed on X this month"
- `/hftr <topic>` — `ufc`, `bitcoin`, `world cup`
- `/hftr @handle` — `@elonmusk`, `x:elonmusk`, `u/spez` — replies **by** them
- `/hftr to:@handle` — `to:@elonmusk`, `on:@elonmusk` — replies that landed
  **on** them

**This skill answers from live X search** - your own credentials, or your
host's X tool when the script prints `NO_CREDS`. That is the path that answers
a topic nobody has ever collected, which is most topics.

A static snapshot ships with the skill as a **fast local cache** of queries
collected earlier. It is tried first because it is free and always awake, not
because it is the product. It does not grow, it names its own freeze date, and
a row leaves it once that row ages out of `--days`. A snapshot miss is a fact
about the cache, never about the world - see **Empty results**.

## Two questions about a person

They are different, and the answer to one is often empty while the other is full:

| query | asks |
|---|---|
| `@elonmusk` | what **he** replied to other people |
| `to:@elonmusk` | what other people replied **to him** |
| `elonmusk` (no @) | replies that **mention** him anywhere in their text |

`to:`, `on:`, and "replies to @name" all mean the second one. The colon form
works bare (`to:elonmusk`); the spaced form needs the @ (`to @elonmusk`), so an
ordinary topic like "on fire" or "to be honest" is never mistaken for a person.

## When NOT to use

- "What happened with X across the internet" — that is a research brief; use
  **last30days**, not this.
- Essays, source tables, YouTube/TikTok/Hacker News sweeps.
- Posting replies, growth automation, or anything that writes.

These are different jobs. last30days tells you what happened; HFTR tells you
which replies landed. Do not substitute one for the other, and do not call
last30days to pad an empty HFTR result.

## Where the rows come from

The product is ranked public replies. Three sources can supply them, and the
script tries the cheap one first:

1. **Snapshot cache** - a dated file served from GitHub raw. Always awake,
   answers in well under a second, no account and no keys. Tried first for
   speed only. It does not grow, and a row leaves it once it falls outside
   `--days`. Rows served from here are labelled `snapshot`, under a line naming
   the freeze date and how much of the file is still in-window.
2. **Your own board** - only when `HFTR_BASE_URL` is set. There is no shared
   public board, so unset means this hop is skipped entirely. `to:` queries
   skip it either way.
3. **Live X and Reddit search** - the answer for anything the cache never
   collected, which is most queries. Read-only, same window, capped the same
   way, labelled `live` because those rows are not written into the cache.
   Reddit needs no key: its `.json` API is closed to anonymous clients, so the
   lane searches `search.rss` for posts and then reads each post's comments
   from the `svc/shreddit` partial, which still serves real scores. X needs
   your own cookies; Reddit does not.

Live runs on **your own** X credentials (`AUTH_TOKEN` / `CT0` in the
environment or in `~/.config/last30days/.env`). Most installs will not have
them, and that is a handled case, not a failure - see step 4, where your host
runs the search with whatever X tool it already has. Between the script's
cookies and the host's own X tool, the live path is what makes a brand-new
topic answerable at all.

There is no shared hosted board. The public one was retired on 2026-09-01:
answering live handle lookups for strangers meant putting one person's X
session behind a URL anyone could drive, which is somebody's account getting
rate-limited on everybody else's traffic. If you run your own board server,
set `HFTR_BASE_URL` and the script will use it as a middle hop.

### Step 4 — the host takes over (REQUIRED when you see `NO_CREDS`)

When the script cannot reach X itself it exits **0** and prints a line starting
with `NO_CREDS`, followed by the exact search to run. The `since:` date is
computed as today minus `--days`; the script fills in the real date, shown here
as a placeholder:

```
NO_CREDS · search with your own X tool: filter:replies "iphone 18" since:<today minus --days> min_faves:1
```

For a `to:` query the line names X's own operator instead:

```
NO_CREDS · search with your own X tool: filter:replies to:iampapito since:<today minus --days> min_faves:1
```

For an `@handle` query it names `from:` instead, because a bare `@handle` is a
MENTION search on X and would answer the opposite question:

```
NO_CREDS · search with your own X tool: filter:replies from:iampapito since:<today minus --days> min_faves:1
```

**Do not stop there and apologise.** If you have any X search tool - Grok's
`x_keyword_search`, an X/Twitter search action, a browser you can search with -
run that query now, then present the results yourself:

1. Keep **replies only**. Drop root posts, and drop a reply whose author is the
   same account it is replying to (a self-thread is not a reply to anyone).
2. Keep rows whose **own text** contains the query. A reply that only shares a
   thread with the topic is not an answer. For a multi-word query, the words
   must sit together **in one sentence**, in any order, with at most two words
   between them: "Grok Bot messes up" and "@bot The Grok app" both count,
   "corporate chat bot. Grok has become..." does not - that is two thoughts.
   If the query contains a number, require the exact phrase: "iphone 18" is
   never "iPhone 11".
3. For a `to:` query, keep only rows whose parent really is that handle - X's
   `to:` operator returns whole conversations, including that account's own
   replies to other people. Drop those.
4. For an `@handle` query, mirror it: keep only rows that account **wrote**.
   A search around a handle returns everyone replying *to* them too, and
   keeping those answers the `to:` question instead.
5. Keep **one row per author**, the highest-liked one - except in `@handle`
   mode, which is one person by definition and is never capped.
6. Sort by likes (`@handle` mode: newest first), at most 12 rows, and unescape
   HTML (`&amp;` is `&`).
7. Print the same cards, with the header labelled `live` instead of `board`:

```
HFTR · 30 days · iphone 18 · live · capped

 1  @author → @parent
    the reply text, without repeating @parent at the start
    ▲likes · https://x.com/author/status/…
```

Never call last30days to fill this in, and never write a row you did not get
back from a real search. If your search returns nothing, say the snapshot had
nothing in-window and X had nothing that passed the filters - that is a true
answer, and the only wording that earns the phrase "nobody landed a reply".

## How to run it

1. Parse the user's request into a single query `Q`: a topic string, or an
   identity (`@handle`, `x:name`, `u/name`).
2. Run, from this skill's directory:

   ```bash
   python3 scripts/hftr.py --q "$Q" --days 30 --limit 12
   ```

3. **Print the script's stdout as-is.** No preamble, no summary, no essay
   before or after. The output is already the answer.
4. If the script reports no replies in-window, read the note lines under the
   header before you answer. A `NO_CREDS` line means it could **not** search X,
   and step 4 above is now your job. A note naming X and Reddit means it did
   search and found nothing. The two are different answers - see **Empty
   results**. Either way: do not backfill from an earlier month, do not call
   last30days to pad the answer, and do not invent rows.
5. Never print secrets or tokens. This skill has none and needs none.
6. Prefer this script over inventing rows. There is no public website holding
   this data to browse instead.

## Options

| flag | meaning |
|---|---|
| `--q` | topic or identity (required) |
| `--days` | 7 or 30 (default 30) |
| `--limit` | rows, max 25 (default 12). Honoured by the readable list, not only by `--json` |
| `--raw` | uncapped: allow several rows from the same account. Also **skips the snapshot**, so the answer comes from `HFTR_BASE_URL` or live search |
| `--json` | print the raw payload instead of the readable list (`source` is `snapshot`, `live-x`, or your board's own payload) |
| `--no-snapshot` | skip the GitHub raw snapshot. The next hop is `HFTR_BASE_URL` if set, otherwise live search / `NO_CREDS` |
| `--no-live` | do not fall back to live X and Reddit search when nothing above answered. No `NO_CREDS` handoff either |
| `--links` | also print the parent post URL on each row |
| `--archive` | list cached rows for this query that have aged out of `--days`, newest first. Cache only - never searches live, because live is always the last `--days`. Still capped unless `--raw` |

`HFTR_BASE_URL` is optional and **unset by default**. There is no shared public
board to fall back on, so unset simply means hop 2 is skipped. Set it to your
own board server to use it as a middle hop. `HFTR_SNAPSHOT_URL` overrides where
the snapshot is read from.

## What the numbers mean

- **▲ count** is likes (X) or score (Reddit) on that reply.
- **Capped** means one row per author. The most-liked reply of the month still
  ranks first; one prolific account just cannot own the whole page. `--raw`
  shows the uncapped list.
- **Author mode** (`@handle`) shows everything that person said in the window,
  newest first, and is never capped.
- The window is real: rows outside `--days` are dropped, including from the
  snapshot. What an empty result means depends on how far the run got - see
  below.
- **The header names its source and its age.** `snapshot` means the cache
  answered, and the line under it reads `cache frozen DATE · N of M rows still
  in-window`. `live` means X or Reddit answered just now. `archive` means the
  window was deliberately ignored.
- **Two counts, two meanings.** `N of M still in-window` is the health of the
  whole cache file. `0 in-window for this query` is about your query. A full
  file can still miss your topic, and a file with nothing left in-window
  answers nothing at all. Never report one as the other.
- **An X reply must name the query itself; a Reddit comment may be qualified
  by its thread.** They reach us differently. X search returns thread
  siblings, so the reply has to carry the query or a reader cannot check it.
  A Reddit comment is found by matching a *post* and then reading it, so the
  thread is the evidence - and the card prints it (`u/name → r/sub · thread
  title`) rather than asking you to take it on trust. Requiring the comment to
  repeat the topic word silenced the lane completely: 0 of 25 real r/Bitcoin
  comments contained "bitcoin halving".

## Empty results

Four different empties. Do not report one as another. The script tells you
which one you are looking at on the line under the header - read it.

1. **Cache miss, no credentials.** The cache held no in-window row for the
   query and the script could not search X itself, so it printed `NO_CREDS`.
   The header names the freeze date and both counts. This says nothing about
   the world. Run that query with your own X tool (step 4), then answer from
   what you find. Exit 0.
2. **Cache miss, searched, nothing survived.** A live search ran - by the
   script with its cookies, or by you after `NO_CREDS` - and nothing passed the
   seven filters. Only now may you say the cache had nothing in-window and X
   had nothing either. Exit 0.

   On a multi-word topic the script adds one more line, counted from the rows
   the search actually returned: how many of them mention every word but never
   close enough together to be about it, how often each word appeared on its
   own, and a narrower query that would match. Pass that on. "No reply put
   *hot*, *ios* and *apps* together, though 23 mentioned ios" is a different
   and far more useful answer than silence, and it is the one case where an
   empty can point somewhere.
3. **Cache aged out.** The cache holds rows for this query but every one of
   them is older than `--days`. The header says `0 in-window for this query`
   and the note says how many older rows exist and that `--archive` lists them.
   This is a fact about a frozen file, not about the world. Live / `NO_CREDS`
   still follows. Exit 0.
4. **Nothing answered at all.** Snapshot not read, no board payload, no live
   rows. One line on stderr, empty stdout, exit 2.

Only case 2 earns the phrase "nobody landed a reply". Cases 1 and 3 mean "not
in this cache" and "not searched yet", and case 4 means the run could not
look.

## Failure

- **A source is unreachable** (GitHub raw down, or a `HFTR_BASE_URL` you set
  that is not answering): say that source was unreachable. Do not invent rows
  to cover for it. The run continues to live search unless `--no-live`.
- **Exit 2** is the one hard failure: nothing answered at all - the snapshot
  could not be fetched, no board payload came back, and live search produced no
  rows. One line on stderr, exit code 2.
- **Exit 0** is everything else, including an empty render and including the
  `NO_CREDS` handoff. "I cannot reach X" is an answer, not a crash.

Never invent a row, and never pad an empty result with last30days. Live X and
Reddit search - by the script with your own cookies, or by your host with its
own X tool - is the intended fallback, not a workaround.
