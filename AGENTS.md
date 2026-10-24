# AGENTS.md — Dark Ship Detector (c0mpiled-16, built Oct 24, 2026, 3:00–8:30 PM)

This file briefs any AI coding tool (Claude Code reads it via CLAUDE.md; Codex reads it directly).
Read PROGRESS.md first to see where things stand, and update it at the end of every session.

## Who I am
Nicholas, first-year Data Science student at UCSD, solo. I know basic Python, pandas, a little scikit-learn, basic git. I do NOT know async, WebSockets, databases, testing, or CI. Write the code, but explain every file and key line in plain English: I must explain the logic to judges. Define technical terms the first time. Push back on bad or risky ideas.

## Event
- Theme "Invisible Interfaces" (works without looking at a screen). Track: Dispatch.
- Judges: YC founders + a VC. They reward a clear real problem, a working demo, and a sharp explanation.
- Hard deadline 8:30 PM. **Feature freeze 7:30 PM.** Backup demo video at 8:00 PM.
- Commit every 20–30 minutes with clear messages.

## The product
Dark Ship Detector monitors live AIS ship traffic off San Diego, learns what normal looks like, and ranks ships that disappear by how suspicious the disappearance is. For the top alert it **calls a dispatcher's phone with a spoken alert** (no screen needed).

Framing: a **risk score with reasons**, not a yes/no claim. Example spoken alert (made-up ship): "Alert. Fishing vessel Sea Hawk went silent 12 minutes ago, 9 miles inside receiver coverage, moving 6 knots toward the Cabrillo marine reserve. Risk 85 percent." Lead the story with illegal fishing near marine reserves.

## Build order (do not skip ahead)
1. Replay mode: stream recorded CSVs from `data/` in time order (sped up). Build this FIRST.
2. Live mode: same pipeline from the aisstream WebSocket, switchable by a flag.
3. Per-ship state + silence detection.
4. Risk score with reasons.
5. Twilio phone alert (inline TwiML `<Say>`), with laptop-speaker fallback.
6. One-command demo + README.

Keep it simple: plain Python scripts, pandas, no database, no web UI unless everything else works.

## Data source: aisstream.io
- `wss://stream.aisstream.io/v0/stream`; send the subscription JSON within 3 seconds:
  `{"APIKey": <key>, "BoundingBoxes": [[[32.3, -118.0], [33.3, -117.0]]], "FilterMessageTypes": ["PositionReport", "ShipStaticData"]}`
- First message is a `SubscriptionConfirmation` (no MetaData): skip non-PositionReport/ShipStaticData messages.
- Messages may arrive as bytes; decode UTF-8, or zlib/gzip-decompress (`zlib.decompress(raw, wbits=47)`).
- A rejected API key shows up as the server silently closing the connection (no error message).
- `MetaData.time_utc` looks like `2026-10-11 23:38:05.87004921 +0000 UTC`; trailing zeros are trimmed, so split on `" +"` instead of slicing.
- Sentinels ("no data"): heading 511, course 360, speed 102.3. Treat speeds above ~50 kn as junk.
- Library: `websockets` (async). Reconnect with backoff; the free feed drops connections.

## Recorded data (for replay) in `data/`
- `ais_*.csv`: `time_utc, mmsi, ship_name, lat, lon, sog, cog, heading, nav_status`
- `ships_*.csv`: `time_utc, mmsi, ship_name, ship_type, length_m, width_m, draught_m, destination, call_sign, imo`
- Ship type codes: 30 fishing, 35 military, 36 sailing, 37 pleasure, 50–59 special (tug/pilot/law enforcement), 60–69 passenger, 70–79 cargo, 80–89 tanker.

## Facts from pre-event exploration (design from these)
- Free feed: median gap between one ship's reports ~2.7 min; 90% under 15 min; 4% over 1 hour. Whole-feed outages happen (no ship for 5+ min): those are feed problems, not ships.
- 134 disappearances (30+ min silent): **70% were inside San Diego Bay, mostly stopped boats** (harmless). Moving ships that vanished offshore were mostly cargo/tankers heading west/northwest, fading **10–20 nm before** the box edge: real coverage ends before the box, so learn the coverage edge from the data.
- Government/military vessels go quiet legitimately (Navy/Coast Guard); big false-alarm source in San Diego.
- nav_status (crew-set) is unreliable; use measured speed/position.
- 75% of reports are ships sitting still.
- Busiest area: San Diego Bay / Point Loma (32.6–32.75 N, -117.3 to -117.15 W).
- **Cabrillo State Marine Reserve** (no-take), tip of Point Loma, corners: (32.6767, -117.2470), (32.6767, -117.2500), (32.6617, -117.2500), (32.6617, -117.2383), (32.6667, -117.2383). It sits right next to the busy harbor entrance.

## Twilio
- Env vars: `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` (+16192795763), `MY_PHONE_NUMBER`.
- `client.calls.create(twiml="<Response><Say>...</Say></Response>", to=..., from_=...)` works (paid account, US geo permission enabled). About 3 s to ring.

## Machine
Surface Pro, Windows on ARM64, PowerShell. Python 3.12 ARM64 in `.venv` (`python -m venv .venv`). websockets, pandas, numpy, twilio all install natively. Prefer `[Environment]::GetEnvironmentVariable("AISSTREAM_API_KEY","User")` to load the saved AIS key.

## Secrets
Never hardcode keys or tokens. `.gitignore` must exclude `.venv/`, `.env`, `*.csv`, `__pycache__/`.
