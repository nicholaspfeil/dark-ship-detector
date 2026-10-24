# PROGRESS.md

Updated by whichever tool is working (Claude Code or Codex) at the end of every session.

## Submission rules (fill in from the 2:45 overview)
- What to submit:
- Where:
- Deadline: 8:30 PM

## Milestones
- [ ] 3:15 Repo set up, first commit pushed
- [x] 3:45 Replay mode streams recorded CSV
- [ ] 4:15 Live mode works (or skipped: replay only)
- [ ] 5:15 Per-ship tracking + silence detection
- [ ] 6:15 Risk score with reasons
- [ ] 6:45 Phone alert rings with a real alert
- [ ] 7:15 One-command demo
- [ ] 7:30 README; FEATURE FREEZE
- [ ] 8:00 Backup video recorded
- [ ] 8:30 Submitted

## Current state
- Replay mode works: `python replay.py` streams the biggest recorded session (ais_ + ships_ CSVs merged, sorted by time) at 600x. `--list`, `--session <tag>`, `--speed N` (0 = no waiting), `--limit N`.
- `messages.py` defines the shared message dict ("position" / "static") and cleans sentinels (heading 511, course 360, speed 102.3 or >50 kn -> None). Live mode must produce the same dicts.
- `replay(tag, speed)` is a generator; the detector will consume it with `for msg in replay(...)`.

## Decisions made
- Replay default speed 600x: a ~25 h recording plays in ~2.5 min.
- Replay never waits more than 2 real seconds between rows (skips dead air during feed outages). Detection must use message timestamps, never the wall clock, so this changes no results.
- Sessions are replayed one at a time (recordings are days apart; merging them would create fake day-long silences).

## Known issues / next step
- No git remote configured yet: commits are local only. Create a GitHub repo and `git remote add origin ...` then push.
- Next: milestone 2 (live mode from aisstream, producing the same dicts via messages.py), or skip to milestone 3 if short on time.
