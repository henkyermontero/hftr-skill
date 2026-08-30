# hftr

Ranked public replies from the last 30 days, by topic or `@handle`.

```
/hftr ufc
/hftr bitcoin
/hftr @elonmusk
```

```
HFTR · last 30 days · world cup · capped
updated 2026-08-30T04:46:00+00:00

 1  ▲1,234  @_I_am_Randy  x  → @theMadridZone
    But we need the intense investigation about the FIFA World Cup tournament…
    Parent https://x.com/i/web/status/2083518685403050428 · Reply https://x.com/…
```

One row per author, every row in-window, every row linked to the original.
It answers one question: **which replies landed.** For "what happened across
the internet", use [last30days](https://github.com/mvanhorn/last30days-skill) —
different job, don't bolt them together.

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

| variable | default |
|---|---|
| `HFTR_BASE_URL` | `https://here-for-the-replies.onrender.com` |

## Direct use

```bash
python3 scripts/hftr.py --q "ufc"
python3 scripts/hftr.py --q "@elonmusk" --days 7
python3 scripts/hftr.py --q "world cup" --raw      # uncapped
python3 scripts/hftr.py --q "world cup" --json     # raw payload
```

Exit codes: `0` success (including an honest empty result), `2` board
unreachable. The board runs on free hosting that sleeps, so a first request
after idle can take a moment; the script says so in one line instead of
crashing.

## The API behind it

```
GET /api/board?q=&days=30&limit=12&cap_author=1
```

No auth, 60 requests/minute per IP. Same queries the website runs, so the site
and the skill cannot disagree. Full contract: `HFTR.md` in the main repo.

MIT.
