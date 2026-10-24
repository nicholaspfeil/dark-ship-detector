"""
feed.py — one switch between recorded and live data.

    from feed import get_feed
    for msg in get_feed("replay"):   # or get_feed("live")
        ...

Both modes yield the same message dicts (see messages.py), so everything that
reads the feed works unchanged in either mode.

Run it:
    python feed.py --mode replay --speed 600
    python feed.py --mode live
"""

import argparse

from replay import format_message, list_sessions, replay


def get_feed(mode="replay", session=None, speed=600.0):
    """Return an iterator of messages from recorded CSVs ("replay") or aisstream ("live")."""
    if mode == "live":
        from live import live  # imported here so replay works even without a network/key
        return live()
    if mode == "replay":
        sessions = list_sessions()
        if not sessions:
            raise SystemExit("No recordings in data/.")
        tag = session or max(sessions, key=sessions.get)
        if tag not in sessions:
            raise SystemExit(f"Unknown session {tag}. Try: python replay.py --list")
        print(f"[replay] session {tag} at {speed:g}x")
        return replay(tag, speed)
    raise SystemExit(f"Unknown mode {mode!r}: use 'replay' or 'live'.")


def add_feed_args(parser):
    """Add the --mode/--session/--speed flags to any script's argument parser."""
    parser.add_argument("--mode", choices=["replay", "live"], default="replay",
                        help="replay recorded CSVs (default) or stream live from aisstream")
    parser.add_argument("--session", help="replay only: recording tag (default: biggest)")
    parser.add_argument("--speed", type=float, default=600.0,
                        help="replay only: speed-up factor (default 600; 0 = no waiting)")


def main():
    parser = argparse.ArgumentParser(description="Print the AIS feed in either mode.")
    add_feed_args(parser)
    parser.add_argument("--limit", type=int, default=None, help="stop after N messages")
    args = parser.parse_args()

    count = 0
    try:
        for msg in get_feed(args.mode, args.session, args.speed):
            print(format_message(msg))
            count += 1
            if args.limit and count >= args.limit:
                break
    except KeyboardInterrupt:
        pass
    print(f"Done: {count} messages.")


if __name__ == "__main__":
    main()
