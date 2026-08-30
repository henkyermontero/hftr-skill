# Refresh the snapshot

`data/board.json` is the static copy of the in-window board that `/hftr` reads
before it touches the live API. It is what makes a board query answer in ~0.3s
instead of waiting on a sleeping Render dyno.

## Automatic

`.github/workflows/rebuild-snapshot.yml` runs at **00:40 and 12:40 UTC** — 40
minutes after the Render ingest cron (`0 */12 * * *`), so it reads a board that
has just been refreshed. It commits `data/board.json` only when the content
actually changed, so quiet days add no commits.

Run it by hand any time: **GitHub → Actions → rebuild-snapshot → Run workflow**.

## Manual

```bash
cd ~/hftr-skill
python3 scripts/build_snapshot.py
git add data/board.json && git commit -m "chore: refresh snapshot" && git push
```

## Rules

- **Never wire this into `ops/ingest_cron.sh` or the ingest job.** A snapshot
  failure must never be able to change that job's exit code; the 14-day
  unattended clock depends on it. This workflow lives in the skill repo and
  cannot reach the ingest job at all.
- **An empty or unreachable API is safe.** `build_snapshot.py` refuses to write
  an empty snapshot and exits 1, so the workflow goes red *without committing*
  and the previous snapshot stays live. A red run here means "the refresh did
  not happen", never "the board is broken".
- **Check the row count** the builder prints. A gradual drop is normal as rows
  age out of the 30-day window. A sudden collapse usually means the API was
  throttling — it retries once on a 429.
