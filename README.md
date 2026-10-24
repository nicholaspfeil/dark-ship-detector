# Dark Ship Detector

**When a boat switches off its tracking transponder near a marine reserve, nobody notices. This does, and it phones a dispatcher about it.**

Built solo at c0mpiled-16 (Oct 24, 2026). Theme: *Invisible Interfaces*. Track: Dispatch.

## The problem

Ships broadcast their position over **AIS** (Automatic Identification System) every few seconds to minutes. Boats fishing illegally in no-take zones like the **Cabrillo State Marine Reserve** at the tip of Point Loma often just turn AIS off. Ships also go quiet for boring reasons, though: docked boats, Navy vessels on duty, or a ship sailing past the edge of the shore receivers' range. In our recordings, **70% of disappearances were boats sitting inside San Diego Bay.** An alarm on every silence would be ignored within a day.

## What it does

1. **Watches** live AIS traffic off San Diego (or replays a real recording).
2. **Learns normal**: each ship's own reporting rhythm, and where receiver coverage actually ends, measured from the data.
3. **Notices silences**: a ship quiet for more than 15 min *and* more than 4x its normal gap between reports.
4. **Scores each silence 0-100 with reasons** instead of a yes/no verdict.
5. **Calls the dispatcher's phone** and reads the top alert aloud. Nobody has to watch a screen. If the call fails, the laptop speaks it.

> "Alert. Underwater operations vessel Oceanus went silent 15 minutes ago, 2 miles west of Point Loma, 25 miles inside receiver coverage, moving 12 knots toward the Cabrillo marine reserve. If it held course, it passed within half a mile of the reserve about 11 minutes after going silent. Risk score 95 out of 100."

That alert is real: Oceanus went silent in our Oct 19 recording, out of 137 silences that day. The call then reads the top reasons and repeats the alert.

## Does it cut the noise? (`python backtest.py`)

Across all 4 recordings (13.9 hours of real coverage once feed outages are removed):

| | Per 24 h of coverage |
|---|---|
| Raw silences (what a naive alarm would ring for) | ~488 |
| Calls at risk 70+ (default) | ~17 |
| Calls at risk 80+ | ~5 |
| Calls at risk 90+ | ~2 |

77% of silences were inside a harbor and 27% were government or military vessels. That's a small sample, so treat the rates as rough.

## The live chart (`python demo.py --dashboard`)

The phone call is the interface; the chart is for the room. A tiny built-in web server (Python's `http.server`, nothing to install) serves `web/dashboard.html`, and the detector rewrites `web/state.json` a few times a second.

- A nautical chart at night: navy sea, ship contacts in chart-paper buff, the reserve in chart magenta (the color real charts use for restricted areas), range rings every 10 nm, and the learned coverage edge.
- When a ship goes dark it becomes a **ghost**: its last position, a circle showing everywhere it could have reached at its last speed (growing every minute it stays silent), and its projected course.
- When the alert fires, the chart flies to the ship and a card shows the risk gauge, the reasons and the exact words the dispatcher hears, plus whether the call was answered.
- **Sound:** click "Turn on sound" to hear each new silence as a tone, a soft low tick for harmless ones and a brighter chime for risky ones. You can follow the sea without watching it.

## Does it catch dark ships? (`python evaluate.py`)

There's no list of confirmed real dark ships, so we made labeled test cases: simulated boats (fake IDs 999xxxxxx) mixed into all 4 real recordings. Each reports normally, then goes dark near the reserve, either heading straight for it at 6-12 knots or working slowly with constant turns (fishing-style) under a pleasure-boat label.

| Scenario | Caught (risk 70+) |
|---|---|
| Transit toward the reserve | 36 / 40 (90%) |
| Fishing-style near the reserve | 38 / 40 (95%) |
| Overall | 74 / 80 (92%) |

Caveat: these scenarios match what the rules were designed to catch, so this checks that the system works end to end on realistic traffic; it isn't proof against every evasion. False alarms come from real traffic (~17 calls per 24 h at risk 70, from `backtest.py`).

## Reconstructing the dark gap

When a silent ship starts transmitting again, it went dark at A and came back at B, so it must have traveled between them, and the straight line A to B is the shortest route it could have taken. The system checks whether that route crosses the reserve, whether the ship stayed near the reserve while dark, and whether the trip would need an impossible speed (a sign of spoofed positions; the check uses real elapsed time, because ships keep moving during feed outages). In the demo recording, **Oceanus reappeared 2.9 miles away and its shortest path while dark ran through the Cabrillo reserve**, so the projected course was right.

## Shift briefing (`python briefing.py`)

One phone call that sums up a whole recording, like a start-of-shift handoff: how many silences, how many were routine, and the top ships worth checking with their two strongest reasons. `--print` shows the text, and `--speaker` says it on the laptop.

## See it on a map (`python make_map.py`)

Writes `map.html`: every silence in a recording (gray = filtered out, red = top ships), the learned coverage edge, the Cabrillo reserve, each top ship's last hour of track, and its projected course after it went silent.

## Run the demo

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python demo.py --dashboard  # phone call + live night chart in the browser
.venv\Scripts\python demo.py              # phone call (laptop voice if Twilio isn't set up)
.venv\Scripts\python demo.py --speaker    # laptop voice only
.venv\Scripts\python demo.py --no-alert   # silent rehearsal
.venv\Scripts\python demo.py --mode live  # live feed
```

The replay demo takes about 40 seconds. It fast-forwards 30 minutes of history so the tracker learns normal traffic, plays the next 35 minutes at 60x, calls when a silence scores 70+, then ranks the rest of the day.

Secrets are read from environment variables (or saved Windows user variables), never from code:
`AISSTREAM_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER`, `MY_PHONE_NUMBER`.

Recordings go in `data/` as `ais_<tag>.csv` + `ships_<tag>.csv`. They're git-ignored, so they aren't in this repo.

## How the risk score works

Start at 30. Each factor adds or subtracts points and leaves a reason the dispatcher hears. The result is clamped to 1-99.

| Factor | Points | Why |
|---|---|---|
| Moving 2+ knots when it went silent / stopped | +20 / -20 | 75% of reports are ships sitting still, and they go quiet constantly |
| Inside San Diego or Mission Bay | -30 stopped, -10 moving | Boats switch off at the dock |
| 10+ nm inside receiver coverage / near its edge | +20 / -25 | Deep inside coverage, signals don't just fade |
| Inside / within 1 nm of / heading toward the Cabrillo reserve | +35 / +25 / +10 to +20 | The no-take zone we protect |
| Projected course (same speed and heading during the silence) enters / passes within 0.5 nm of the reserve | +15 / +5 | Dead reckoning: where it probably went after it went dark |
| Fishing vessel | +20 | Illegal fishing is the core case |
| Government or military vessel | -40 | Navy and Coast Guard go quiet legitimately |
| Has gone silent before and come back | -10 each (max -20) | It does this often |

**Receiver coverage is learned, not assumed.** For each 30-degree slice of the compass around Point Loma, coverage ends at the distance within which 95% of all recorded reports were heard (22-44 nm offshore). Ships fade before the edge of the area we subscribe to, so a fixed map would be wrong.

**Government vessels** are recognized by MMSI prefix 3669 (US federal), military/law-enforcement type codes, or names like USNS, USCG, NOAA.

**It's a ranking, not a probability.** There is no labeled dataset of confirmed dark ships, so the weights are set by hand from what the data shows. That's why the alert says "risk score 90 out of 100", not "90 percent".

## Design choices that matter

- **Same pipeline for recorded and live data.** Both are converted to one message format (`messages.py`), so detection can't tell them apart. `--mode replay|live` switches between them.
- **The clock is the data's timestamps,** never the laptop's. Replay runs 60-600x faster.
- **Feed outages aren't ship silences.** If *no* ship reports for 5+ minutes, the feed is down, and that time is subtracted from every ship's silence. Our recordings contain 14-20 hour recorder gaps; without this rule every ship would look dark.
- **Junk values are dropped:** AIS uses heading 511, course 360, and speed 102.3 to mean "no data", and speeds over 50 knots are treated as errors.
- **One call per run by default,** so a demo can't flood a phone.

## Files

| File | What it does |
|---|---|
| `demo.py` | One-command demo |
| `detect.py` | Full pipeline with all flags (`--alert`, `--min-risk`, `--speed 0`...) |
| `feed.py` | Picks replay or live |
| `replay.py` / `live.py` | Recorded CSVs / aisstream WebSocket (auto-reconnect with backoff) |
| `messages.py` | The shared message format + junk-value cleaning |
| `tracker.py` | Per-ship state, silence detection, outage handling |
| `scoring.py` | Learned coverage, ship registry, risk score, spoken alert text |
| `alert.py` | Twilio phone call (inline TwiML `<Say>`), laptop-voice fallback |
| `dashboard.py` + `web/dashboard.html` | Live night-chart dashboard (local server + state file) |
| `backtest.py` | Alert volume across all recordings |
| `make_map.py` | Writes `map.html` of a recording's silences |
| `PITCH.md` | 2-minute pitch script and judge Q&A |

## Limitations / next steps

- Weights are hand-set; with confirmed cases they could be fit properly.
- Only one marine reserve is mapped. Adding more is a list of corners.
- Some boats legitimately power off AIS at sea (it's not required for small recreational boats), so every alert is a lead to check, not an accusation.
- A dispatcher could reply by voice ("acknowledge", "next alert") to make the interface two-way.

Data: [aisstream.io](https://aisstream.io). Calls: Twilio.
