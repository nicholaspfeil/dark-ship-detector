"""
replay.py — Milestone 1: stream recorded AIS data as if it were live.

Each recording "session" in data/ is a pair of files with the same timestamp tag:
    data/ais_<tag>.csv    position reports
    data/ships_<tag>.csv  static ship info
We merge both files, sort every row by time, and hand them out one at a time,
waiting between rows so it feels like a live feed, just sped up.

Run it:
    python replay.py                      # biggest session, 600x speed
    python replay.py --list               # show available sessions
    python replay.py --session 20261023_184344 --speed 60
    python replay.py --speed 0            # no waiting, as fast as possible
"""

import argparse
import glob
import os
import time

import pandas as pd

from messages import make_position, make_static

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# If the recording has a long gap (e.g. a feed outage), don't make the viewer
# stare at nothing: never wait more than this many real seconds between rows.
# Downstream code uses the message timestamps, not the wall clock, so this
# doesn't change any results; it only skips dead air.
MAX_WAIT_S = 2.0


def list_sessions():
    """Return {tag: row_count} for every recording that has an ais_ file."""
    sessions = {}
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "ais_*.csv"))):
        tag = os.path.basename(path)[len("ais_"):-len(".csv")]
        with open(path, encoding="utf-8") as f:
            sessions[tag] = sum(1 for _ in f) - 1  # minus header line
    return sessions


def load_session(tag):
    """Load one session's CSVs into a single list of message dicts, sorted by time."""
    ais = pd.read_csv(os.path.join(DATA_DIR, f"ais_{tag}.csv"))
    ais["time_utc"] = pd.to_datetime(ais["time_utc"], format="ISO8601", utc=True)

    messages = [
        make_position(r.time_utc, r.mmsi, r.ship_name, r.lat, r.lon,
                      r.sog, r.cog, r.heading, r.nav_status)
        for r in ais.itertuples(index=False)
    ]

    ships_path = os.path.join(DATA_DIR, f"ships_{tag}.csv")
    if os.path.exists(ships_path):  # static info is nice to have, not required
        ships = pd.read_csv(ships_path)
        ships["time_utc"] = pd.to_datetime(ships["time_utc"], format="ISO8601", utc=True)
        messages += [
            make_static(r.time_utc, r.mmsi, r.ship_name, r.ship_type, r.length_m,
                        r.width_m, r.draught_m, r.destination, r.call_sign, r.imo)
            for r in ships.itertuples(index=False)
        ]

    # sorted() is "stable": rows with identical times keep their file order.
    messages.sort(key=lambda m: m["time"])
    return messages


def replay(tag, speed=600.0):
    """
    Yield messages one at a time in time order, waiting between them.

    This is a *generator* (note `yield` instead of `return`): the caller loops
    over it with `for msg in replay(...)` and gets each message as it "arrives".
    speed=600 means 1 recorded minute plays in 0.1 real seconds (10 min -> 1 s).
    speed=0 means don't wait at all.
    """
    messages = load_session(tag)
    prev_time = None
    for msg in messages:
        if speed > 0 and prev_time is not None:
            gap_s = (msg["time"] - prev_time).total_seconds()
            wait = min(gap_s / speed, MAX_WAIT_S)
            if wait > 0:
                time.sleep(wait)
        prev_time = msg["time"]
        yield msg


def format_message(msg):
    """One readable line per message, for watching the stream scroll by."""
    t = msg["time"].strftime("%Y-%m-%d %H:%M:%S")
    name = msg["ship_name"] or "?"
    if msg["type"] == "position":
        sog = f"{msg['sog']:.1f}kn" if msg["sog"] is not None else "--kn"
        cog = f"{msg['cog']:.0f}deg" if msg["cog"] is not None else "--deg"
        return (f"{t}  POS  {msg['mmsi']}  {name:<22.22} "
                f"{msg['lat']:.4f},{msg['lon']:.4f}  {sog:>7} {cog:>6}")
    return (f"{t}  INFO {msg['mmsi']}  {name:<22.22} "
            f"type={msg['ship_type']} len={msg['length_m']} dest={msg['destination']}")


def main():
    parser = argparse.ArgumentParser(description="Replay recorded AIS data in time order.")
    parser.add_argument("--session", help="timestamp tag, e.g. 20261023_184344 (default: biggest)")
    parser.add_argument("--speed", type=float, default=600.0,
                        help="speed-up factor (default 600; 0 = no waiting)")
    parser.add_argument("--limit", type=int, default=None, help="stop after N messages")
    parser.add_argument("--list", action="store_true", help="list sessions and exit")
    args = parser.parse_args()

    sessions = list_sessions()
    if not sessions:
        raise SystemExit(f"No ais_*.csv files found in {DATA_DIR}")
    if args.list:
        for tag, n in sessions.items():
            print(f"{tag}  {n} position reports")
        return

    tag = args.session or max(sessions, key=sessions.get)
    if tag not in sessions:
        raise SystemExit(f"Unknown session {tag}. Try --list.")
    print(f"Replaying session {tag} at {args.speed:g}x  (Ctrl+C to stop)")

    count = 0
    try:
        for msg in replay(tag, args.speed):
            print(format_message(msg))
            count += 1
            if args.limit and count >= args.limit:
                break
    except KeyboardInterrupt:
        pass
    print(f"Done: {count} messages.")


if __name__ == "__main__":
    main()
