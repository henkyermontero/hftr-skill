# Refresh the snapshot

Run after a green ingest, while the site is awake:

```bash
cd ~/hftr-skill && python3 scripts/build_snapshot.py \
  && git commit -am "chore: refresh snapshot" && git push
```

That pulls the current in-window board (the All view, every stored topic, and
the authors actually on the board) into `data/board.json`, which the skill reads
before it touches the live API.

Notes:

- It refuses to write an empty snapshot, so a failed pull cannot blank the file.
- Check the row count it prints. A large drop usually means a topic aged out of
  the 30-day window, which is normal, or that the API was throttling, which is
  not - it retries once on a 429.
- **Never wire this into `ops/ingest_cron.sh` or the ingest job.** A snapshot
  failure must never be able to change that job's exit code; the 14-day
  unattended clock depends on it.
