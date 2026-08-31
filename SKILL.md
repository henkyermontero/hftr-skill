---
name: hftr
description: Ranked public replies from the last 30 days for a topic or @handle. Use when asked for the best replies, most-liked comments, what landed on a topic this month, or to look up a specific account's replies. Do NOT use for a multi-source research brief of what happened - that is last30days.
---

# HFTR — which replies landed

One question, answered from one board: **which public replies landed on this
topic or this @handle in the last 30 days.** Ranked by likes, one row per
author, every row linking to the original.

## When to use

- "best replies", "most-liked comments", "what landed on X this month"
- `/hftr <topic>` — `ufc`, `bitcoin`, `world cup`
- `/hftr @handle` — `@elonmusk`, `x:elonmusk`, `u/spez` — replies **by** them
- `/hftr to:@handle` — `to:@elonmusk`, `on:@elonmusk` — replies that landed
  **on** them

The board answers for what it has already collected. The catalog grows when the
ingest job runs, so a brand-new topic can be empty today and answer next week -
an empty result is an honest "nobody landed a reply on that", never a guess.

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

Three hops, fastest first. The script does all of this for you:

1. **Snapshot** - a static copy of the in-window board on GitHub raw. Always
   awake, answers in well under a second.
2. **Live API** - fresher, but the board runs on free hosting that sleeps, so a
   first call can wait on a cold start.
3. **Live X search** - only when the first two find nothing. One read-only
   search for public replies in the window, capped the same way, labelled
   `live · not on board` because those rows are not part of the ranked board
   and are not written into it.

Step 3 needs X cookies (`AUTH_TOKEN` / `CT0`) in the environment or in
`~/.config/last30days/.env`. Most installs will not have them, and that is a
handled case, not a failure.

### Step 4 — the host takes over (REQUIRED when you see `NO_CREDS`)

When the script cannot reach X itself it exits **0** and prints a line starting
with `NO_CREDS`, followed by the exact search to run:

```
NO_CREDS · search with your own X tool: filter:replies "iphone 18" since:2026-07-31 min_faves:1
```

For a `to:` query the line names X's own operator instead:

```
NO_CREDS · search with your own X tool: filter:replies to:iampapito since:2026-07-31 min_faves:1
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
4. Keep **one row per author**, the highest-liked one.
5. Sort by likes, at most 12 rows, and unescape HTML (`&amp;` is `&`).
6. Print the same cards, with the header labelled `live` instead of `board`:

```
HFTR · 30 days · iphone 18 · live · capped

 1  @author → @parent
    the reply text, without repeating @parent at the start
    ▲likes · https://x.com/author/status/…
```

Never call last30days to fill this in, and never write a row you did not get
back from a real search. If your search returns nothing, say the board and X
both had nothing - that is a true answer.

## How to run it

1. Parse the user's request into a single query `Q`: a topic string, or an
   identity (`@handle`, `x:name`, `u/name`).
2. Run, from this skill's directory:

   ```bash
   python3 scripts/hftr.py --q "$Q" --days 30 --limit 12
   ```

3. **Print the script's stdout as-is.** No preamble, no summary, no essay
   before or after. The output is already the answer.
4. If the script reports no replies in-window, it has already looked at the
   board AND at X. Say exactly that. Do not backfill from an earlier month, do
   not call last30days to pad the answer, and do not invent rows.
5. Never print secrets or tokens. This skill has none and needs none.
6. Prefer this script over browsing the website; it reads the same data.

## Options

| flag | meaning |
|---|---|
| `--q` | topic or identity (required) |
| `--days` | 7 or 30 (default 30) |
| `--limit` | rows, max 25 (default 12) |
| `--raw` | uncapped: allow several rows from the same account |
| `--json` | print the raw API payload instead of the readable list |
| `--no-snapshot` | skip the snapshot and ask the live board directly |
| `--no-live` | do not fall back to a live X search when the board is empty |
| `--links` | also print the parent post URL on each row |

`HFTR_BASE_URL` overrides the board's address; the default is the public site.

## What the numbers mean

- **▲ count** is likes (X) or score (Reddit) on that reply.
- **Capped** means one row per author. The most-liked reply of the month still
  ranks first; one prolific account just cannot own the whole page. `--raw`
  shows the uncapped list.
- **Author mode** (`@handle`) shows everything that person said in the window,
  newest first, and is never capped.
- The window is real: an empty result means nobody landed a reply on that topic
  this month, not that the tool failed.

## Failure

If the snapshot and the live board are both unreachable, the script prints one
line saying the board may be waking and exits 2. Run it again a minute later.
It never falls back to live scraping, and it never pads an empty result with
another tool.
