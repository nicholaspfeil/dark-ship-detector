# PROGRESS.md

Updated by whichever tool is working (Claude Code or Codex) at the end of every session.

## Submission rules (fill in from the 2:45 overview)
- What to submit:
- Where:
- Deadline: 8:30 PM

## Milestones
- [x] 3:15 Repo set up, first commit pushed
- [x] 3:45 Replay mode streams recorded CSV
- [x] 4:15 Live mode works (or skipped: replay only)
- [x] 5:15 Per-ship tracking + silence detection
- [x] 6:15 Risk score with reasons
- [x] 6:45 Phone alert rings with a real alert
- [x] 7:15 One-command demo
- [x] 7:30 README written (FEATURE FREEZE still at 7:30)
- [ ] 8:00 Backup video recorded
- [ ] 8:30 Submitted

## Current state
- Replay mode works: `python replay.py` streams the biggest recorded session (ais_ + ships_ CSVs merged, sorted by time) at 600x. `--list`, `--session <tag>`, `--speed N` (0 = no waiting), `--limit N`.
- `messages.py` defines the shared message dict ("position" / "static") and cleans sentinels (heading 511, course 360, speed 102.3 or >50 kn -> None). Live mode must produce the same dicts.
- `replay(tag, speed)` is a generator; the detector will consume it with `for msg in replay(...)`.
- Live mode works: `live.py` connects to aisstream, converts messages with the same messages.py functions, reconnects with backoff (1 s doubling to 60 s), and reconnects if silent 120 s. Async WebSocket runs in a background thread feeding a queue, so `live()` is a plain generator like `replay()`. Tested: real San Diego traffic arrives within seconds; bad key prints a hint and retries.
- `feed.py`: `get_feed(mode)` + `add_feed_args(parser)` give any script `--mode replay|live --session --speed`. Milestone 3 reads from `get_feed`.
- Silence detection works: `tracker.py` (`ShipTracker.update(msg)` -> events "silent"/"returned", each with a snapshot: last position, speed, course, type, quiet minutes, silence_count). `python detect.py --speed 0` runs a whole recording in 1-5 s. Results: 137 / 48 / 38 / 59 silences across the 4 recordings.
- Risk scoring works: `scoring.py` `score_event(event)` -> risk 0-100 + reasons list (points, text); `alert_text(event, result)` builds the spoken sentence. `detect.py` prints each scored silence and a top-N ranking (one line per ship) with "why". Top alerts per recording are moving ships offshore (Oceanus 90, unidentified 367375550 80, Maersk Glacier 70); gov vessels and stopped bay boats score 1.
- Alerts: `alert.py` `send_alert(text)` phones MY_PHONE_NUMBER via Twilio (inline TwiML, Polly.Joanna voice, says alert twice), watches call status up to 45 s, and falls back to the laptop voice (Windows System.Speech) if Twilio isn't configured, errors, or the call is failed/busy/no-answer. `detect.py --alert` sends one alert (default `--max-alerts 1`) for the first silence with risk >= 70 (`--alert-threshold`); `--speaker` skips the phone. Calls run in a background thread so detection keeps going. `python alert.py` = test call; `python alert.py --speaker` = laptop only.
- One-command demo: `python demo.py` (~40 s). Replays the Oct 19 recording: fast-forwards to 1:30 PM local (learn normal), plays at 60x with a ticker + each silence's risk, calls the phone when Oceanus hits risk 90 at 2:02 PM, then fast-forwards the rest of the day and prints the top 5 + an example of a silence we did NOT alert on. Flags: `--speaker`, `--no-alert` (rehearsal), `--mode live`, `--speed`. Rehearsed with --no-alert; live mode smoke-tested.
- Extras (built after milestone 6):
  - Projected course (dead reckoning) in scoring.py: assumes same speed/heading during the silence; enters reserve +15, passes within 0.5 nm +5. Spoken: "If it held course, it passed within half a mile of the reserve about 11 minutes after going silent." Oceanus now 95.
  - Phone call reads the alert, then "Main reasons: ..." (top 3), then repeats only the alert (`call_text` + `twiml_for`).
  - `backtest.py`: 13.9 h real coverage across 4 recordings; ~488 silences/24 h -> ~17 calls at risk 70, ~5 at 80, ~2 at 90. 77% of silences in harbor, 27% government.
  - `make_map.py` -> map.html (gitignored): silences (gray/red), learned coverage edge, reserve, top-5 tracks + projected courses. Checked in browser.
  - PITCH.md: 2-minute script, demo choreography, numbers table, judge Q&A.
- README.md written for judges: problem, what it does, run instructions, scoring table, design choices, limitations.
- `secrets_env.get_secret(name)` reads env vars or saved Windows user vars (live.py uses it too).
- Tested: TwiML escaping, laptop fallback (spoke the Oceanus alert aloud), speech with apostrophes. Real Twilio test call (`python alert.py`, test text) placed 2026-10-24, answered, and Nicholas confirmed the spoken text was correct. Real detector alert call (`detect.py --speed 0 --alert`, Oceanus risk 90) placed 2026-10-24 and answered.

## Decisions made
- Replay default speed 600x: a ~25 h recording plays in ~2.5 min.
- Replay never waits more than 2 real seconds between rows (skips dead air during feed outages). Detection must use message timestamps, never the wall clock, so this changes no results.
- Silence threshold = max(15 min, 4x the ship's own median gap); needs 3+ reports first. 15 min because 90% of normal gaps are under that.
- Clock = feed timestamps. Feed outage = no ship reports for 5+ min; outage time is subtracted from every ship's silence. Recordings have 14-20 h recorder gaps, so this is essential.
- Each silence reported once; "returned" clears it. silence_count lets scoring discount ships that go quiet often.
- Risk = 30 base + points, clamped 1-99. It's a ranking, not a probability: alert says "risk score N out of 100", not "percent". Points: moving >=2 kn +20 / stopped -20; in harbor -30 stopped, -10 moving; offshore coverage: >=10 nm inside edge +20, 3-10 +5, <3 -25; reserve: inside +35, <1 nm +25, heading toward (outside harbor, <5 nm +20, 5-10 nm +10), <3 nm +10; fishing +20; government -40; harbor work boat -10; passenger -10; each prior silence -10 (max -20).
- Coverage edge is learned: 95th percentile of report distance from Point Loma in each 30-degree compass slice (offshore 22-44 nm). Land-side slices are tiny, so the coverage factor is skipped inside harbors.
- Ship type registry built from all ships_*.csv (99% of MMSIs covered). Government = MMSI prefix 3669 (US federal), type 35/55, or name match (US GOV, USNS, USCG, NOAA, CUTTER, PB, CG...).
- "Toward the reserve" not counted inside the harbor: the exit channel passes the reserve, so every departing boat would match.
- Sessions are replayed one at a time (recordings are days apart; merging them would create fake day-long silences).

## Known issues / next step
- Repo: https://github.com/nicholaspfeil/dark-ship-detector (origin/main). Push after every commit.
- Live messages have no recorder yet (can't save live data for later replay). Add only if time allows.
- Live detection only smoke-tested (connects, no crash); a live silence takes 15+ min to appear.
- No fishing vessel in the recordings scores high (only 2, mostly docked). Demo decision: lead with the REAL top alert (Oceanus, type 33 underwater operations, 12 m, heading toward the reserve at 12 kn). Pitch illegal fishing as the motivating problem; no simulated ships.
- Weights are hand-set from the exploration facts, not fitted (no labeled "real dark ship" data exists). Be upfront about that with judges.
- Twilio secrets are saved as Windows user env vars.
- `--alert` fires on the FIRST silence with risk >= threshold as it happens (needed for live mode, which never "ends"), not the overall top of the run. In the biggest recording these are the same ship (Oceanus 90).
- Not yet done: `python demo.py` with a real phone call (only rehearsed with --no-alert; last rehearsal 39 s). The call is now longer (reasons added) and hasn't been heard yet. Do one full run before recording the 8:00 backup video.
- Next: rehearse pitch, record backup video at 8:00, fill in submission rules at the top of this file.
