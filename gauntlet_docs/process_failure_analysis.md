# Process Failure Analysis — 2026-03-28

## What Happened

The rebuild pipeline ran successfully for ~7 hours, completing stories 1-1 through 2-7 (all of epics 1 and 2). The run was stopped when the Anthropic API credit balance ran out.

When attempting to restart, two separate runs occurred in quick succession:

### Run 1: Accidental non-resume start
- Command: `docker compose -f docker-compose.rebuild.yml up` (no `--resume` flag)
- The entrypoint in `Dockerfile.rebuild` is hardcoded to `python -m src.main --rebuild /app/workspace` — no `--resume`
- This started the pipeline from scratch at story 1-1
- Story 1-1 failed immediately: "Credit balance is too low" (API credits not yet reloaded)
- The pipeline recorded this as a failed story and wrote a checkpoint reflecting the failure
- The existing checkpoint from the successful 7-hour run was overwritten

### Run 2: Resume attempt
- Command: `docker compose run --entrypoint "python -m src.main --rebuild /app/workspace --resume" rebuild`
- Loaded the corrupted checkpoint from Run 1
- Log showed: "Resume state loaded: starting at epic 1, story 0, 0 stories already done"
- Then displayed: "Resuming from epic 2, story 1 (0 stories already done)"
- This inconsistency (epic 2 but 0 stories done) indicates the checkpoint is in a bad state
- Story 2-1 also failed with "Credit balance is too low"

## What Is Corrupted

### Checkpoint file: `shiprebuild/checkpoints/session.json`
The checkpoint was overwritten by Run 1's failure. It no longer reflects the progress from the 7-hour run (stories 1-1 through 2-7 complete). The current checkpoint data is unreliable.

### Git state in shiprebuild
The git repo itself is fine — all committed code from stories 1-1 through 2-7 is intact on the `master` branch. The code was not affected by the failed runs.

### Railway database
The failed runs sent log events to the Railway dashboard. These should be cleaned out before the next real run to avoid confusion.

## What Needs To Be Fixed Before Restarting

### 1. Delete the corrupted checkpoint
```bash
rm shiprebuild/checkpoints/session.json
```
This forces the pipeline to start fresh. Without this, `--resume` will load bad state.

### 2. Reload Anthropic API credits
The pipeline's Claude CLI agents need API credits to function. Resolve the billing issue before restarting.

### 3. Clean the Railway session database
Delete the failed test sessions so the public dashboard starts clean:
```bash
railway link -p 0f7bb362-3853-4e22-b0ab-f7f6f07312ae -s shiprebuild -e production
# Then switch back to clever-freedom and run:
railway ssh -s shipyard -- 'python -c "import os,psycopg2; conn=psycopg2.connect(os.environ[\"DATABASE_URL\"]); cur=conn.cursor(); cur.execute(\"DELETE FROM log_events\"); cur.execute(\"DELETE FROM sessions\"); conn.commit(); print(\"Cleaned\"); conn.close()"'
```

### 4. Decide on resume vs. fresh start
Since the code from stories 1-1 through 2-7 is already committed in the git repo, the pipeline will encounter those files when it re-runs those stories. The pipeline needs to handle this gracefully — either:
- **Fresh start (recommended):** Delete `session.json`, start without `--resume`. The pipeline will re-run stories 1-1 through 2-7, but the agents will find existing code and either skip or rebuild on top of it. This is the safest option since the checkpoint is corrupted.
- **Manual checkpoint repair:** Manually write a `session.json` that reflects the actual progress (epic 3, story 0, 12 stories completed). This skips re-running completed work but requires careful manual construction of the checkpoint.

### 5. Use the correct start command
Always use the `--resume` flag when restarting an interrupted run:
```bash
TARGET_DIR=c:/alcorn/gauntlet/6-shipyard/shiprebuild docker compose -f docker-compose.rebuild.yml run --entrypoint "python -m src.main --rebuild /app/workspace --resume" rebuild
```
The plain `docker compose up` will always start fresh because the Dockerfile entrypoint does not include `--resume`.

## Preventive Measures

### Consider adding `--resume` to the Dockerfile entrypoint
Change the entrypoint to always attempt resume — if no checkpoint exists, it starts fresh automatically:
```dockerfile
ENTRYPOINT ["python", "-m", "src.main", "--rebuild", "/app/workspace", "--resume"]
```
This would make `docker compose up` safe for both fresh starts and restarts.

### Protect checkpoints from non-resume overwrites
The pipeline should not overwrite an existing checkpoint with progress when starting a non-resume run. It could either:
- Refuse to start if a checkpoint with progress exists and `--resume` was not passed
- Back up the existing checkpoint before overwriting

## Timeline
- ~7 hours: Successful run, stories 1-1 through 2-7 complete
- API credits exhausted, pipeline stopped
- Accidental non-resume start overwrote checkpoint
- Resume attempt loaded corrupted checkpoint
- Both runs failed with "Credit balance is too low"
