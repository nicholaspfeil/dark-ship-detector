"""
detect.py — run the feed through the ShipTracker and print silences as they happen.

    python detect.py                          # replay biggest recording at 600x
    python detect.py --speed 0                # whole recording instantly
    python detect.py --mode live              # live feed
    python detect.py --show-returns           # also print ships coming back
"""

import argparse

from feed import add_feed_args, get_feed
from tracker import ShipTracker


def format_event(e):
    t = e["time"].strftime("%Y-%m-%d %H:%M")
    name = e["name"] or "?"
    sog = f"{e['sog']:.1f}kn" if e["sog"] is not None else "--kn"
    cog = f"{e['cog']:.0f}deg" if e["cog"] is not None else "--deg"
    if e["event"] == "silent":
        return (f"{t}  SILENT   {e['mmsi']}  {name:<22.22} type={e['ship_type']}  "
                f"quiet {e['quiet_min']:.0f} min (limit {e['threshold_min']:.0f})  "
                f"last at {e['lat']:.4f},{e['lon']:.4f} {sog} {cog}  "
                f"[silence #{e['silence_count']}]")
    return f"{t}  RETURNED {e['mmsi']}  {name:<22.22} after {e['quiet_min']:.0f} min"


def main():
    parser = argparse.ArgumentParser(description="Detect ships that go silent.")
    add_feed_args(parser)
    parser.add_argument("--show-returns", action="store_true", help="also print 'returned' events")
    args = parser.parse_args()

    tracker = ShipTracker()
    n_msgs = n_silent = 0
    try:
        for msg in get_feed(args.mode, args.session, args.speed):
            n_msgs += 1
            for e in tracker.update(msg):
                if e["event"] == "silent":
                    n_silent += 1
                if e["event"] == "silent" or args.show_returns:
                    print(format_event(e))
    except KeyboardInterrupt:
        pass

    outage_h = sum((b - a).total_seconds() for a, b in tracker.outages) / 3600
    print(f"\nDone: {n_msgs} messages, {len(tracker.ships)} ships, {n_silent} silences, "
          f"{len(tracker.outages)} feed outages ({outage_h:.1f} h ignored).")


if __name__ == "__main__":
    main()
