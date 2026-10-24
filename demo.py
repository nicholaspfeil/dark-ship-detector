"""
demo.py — Milestone 6: the whole system in one command.

    python demo.py                  # replay demo; phones MY_PHONE_NUMBER (laptop voice if Twilio fails)
    python demo.py --speaker        # same, laptop voice only
    python demo.py --no-alert       # rehearsal: no call, no voice
    python demo.py --mode live      # watch the live feed instead

The replay demo runs in three phases on a real recording (Oct 19, 2026):
  1. Fast-forward: the first 30 minutes of the recording are fed in instantly
     so the tracker learns each ship's normal reporting rhythm.
  2. Watch: the next part plays at 60x (1 recorded minute per second) while
     the screen shows a ticker. When a silence scores 70+, we phone the dispatcher.
  3. Fast-forward the rest of the day, then print the day's top risks with reasons.
Nothing is staged: phase 2 starts at a fixed time, and whatever the detector
finds is what gets called in.
"""

import argparse
import time

import pandas as pd

from alert import send_alert_async
from feed import get_feed
from replay import MAX_WAIT_S, load_session
from scoring import alert_text, call_text, clean_name, knowledge, score_event
from tracker import ShipTracker

DEMO_SESSION = "20261019_195808"       # biggest recording: Oct 19-20, 2026
DEMO_WATCH_FROM = "2026-10-19 20:30"   # UTC; phase 2 starts here (1:30 PM San Diego time)
DEMO_SPEED = 60
TICKER_EVERY_MIN = 2                   # print a status line every 2 recorded minutes
ALERT_THRESHOLD = 70
LOCAL_TZ = "America/Los_Angeles"


def local(t, with_date=False):
    """UTC timestamp -> San Diego clock time, e.g. '1:30 PM' (or 'Oct 19 1:30 PM')."""
    t = t.tz_convert(LOCAL_TZ)
    clock = t.strftime("%I:%M %p").lstrip("0")
    return f"{t.strftime('%b')} {t.day} {clock}" if with_date else clock


def paced(messages, watch_from, speed, state):
    """Yield messages: instantly before watch_from, at `speed`x after it,
    and instantly again once state["fast"] is set (after the alert)."""
    prev = None
    for msg in messages:
        if not state["fast"] and msg["time"] >= watch_from:
            if not state["watching"]:
                state["watching"] = True
                prev = msg["time"]
            wait = min((msg["time"] - prev).total_seconds() / speed, MAX_WAIT_S)
            if wait > 0:
                time.sleep(wait)
            prev = msg["time"]
        yield msg


def main():
    parser = argparse.ArgumentParser(description="Dark Ship Detector demo.")
    parser.add_argument("--mode", choices=["replay", "live"], default="replay")
    parser.add_argument("--speaker", action="store_true", help="laptop voice instead of a phone call")
    parser.add_argument("--no-alert", action="store_true", help="don't call or speak (rehearsal)")
    parser.add_argument("--speed", type=float, default=DEMO_SPEED, help="replay speed during the watch phase")
    args = parser.parse_args()

    print("=" * 72)
    print(" DARK SHIP DETECTOR  -  waters off San Diego")
    print(" Learns what normal AIS traffic looks like, ranks ships that go silent,")
    print(" and phones a dispatcher about the most suspicious one.")
    print("=" * 72)
    knowledge()  # learn coverage edge + ship registry from data/

    state = {"fast": False, "watching": args.mode == "live"}
    if args.mode == "live":
        stream = get_feed("live")
        print("Watching the live feed. Silences need 15+ minutes to appear. Ctrl+C to stop.\n")
    else:
        watch_from = pd.Timestamp(DEMO_WATCH_FROM, tz="UTC")
        print(f"Recording of {local(watch_from)} Oct 19 onward. "
              f"Fast-forwarding 30 min of history to learn normal traffic...")
        stream = paced(load_session(DEMO_SESSION), watch_from, args.speed, state)

    tracker = ShipTracker()
    scored = []
    alert_thread = None
    next_tick = None
    announced_watch = False
    try:
        for msg in stream:
            events = tracker.update(msg)

            if state["watching"] and not state["fast"]:
                if not announced_watch and args.mode == "replay":
                    announced_watch = True
                    print(f"Learned {len(tracker.ships)} ships. Now playing at {args.speed:g}x "
                          f"(1 recorded minute per {60 / args.speed:g} s).\n")
                if next_tick is None or msg["time"] >= next_tick:
                    silent = sum(s["silent"] for s in tracker.ships.values())
                    print(f"  {local(msg['time'])}  tracking {len(tracker.ships):>3} ships   "
                          f"{silent} currently silent")
                    next_tick = msg["time"] + pd.Timedelta(minutes=TICKER_EVERY_MIN)

            for e in events:
                if e["event"] != "silent":
                    continue
                result = score_event(e)
                scored.append((result["risk"], e, result))
                if not state["watching"] or state["fast"]:
                    continue  # silences during fast-forward are ranked at the end, not shown live
                name = clean_name(result["facts"]["name"]) or f"ID {e['mmsi']}"
                top = result["reasons"][0][1] if result["reasons"] else ""
                print(f"  {local(e['time'])}  SILENT  {name:<20.20} risk {result['risk']:>2}  ({top})")

                if result["risk"] >= ALERT_THRESHOLD and alert_thread is None:
                    text = alert_text(e, result)
                    print("\n" + "!" * 72)
                    print(f" HIGH RISK: {text}")
                    print(" Why: " + "; ".join(f"{p:+d} {t}" for p, t in result["reasons"] if p))
                    print("!" * 72 + "\n")
                    if args.no_alert:
                        alert_thread = True
                    else:
                        print(" Calling the dispatcher...\n")
                        alert_thread = send_alert_async(call_text(e, result), use_phone=not args.speaker)
                    if args.mode == "replay":
                        state["fast"] = True  # skip ahead through the rest of the day
    except KeyboardInterrupt:
        pass

    if hasattr(alert_thread, "join"):
        alert_thread.join()

    print(f"\nProcessed the full recording: {len(tracker.ships)} ships, {len(scored)} silences. "
          f"Most were harmless. Top 5:")
    shown = set()
    for risk, e, result in sorted(scored, key=lambda s: -s[0]):
        if e["mmsi"] in shown:
            continue
        shown.add(e["mmsi"])
        name = clean_name(result["facts"]["name"]) or f"ID {e['mmsi']}"
        why = "; ".join(t for p, t in result["reasons"] if p > 0) or "-"
        print(f"  {risk:>2}  {name:<20.20} {local(e['time'], with_date=True):<16} {why}")
        if len(shown) >= 5:
            break
    lowest = sorted(scored, key=lambda s: s[0])[:1]
    if lowest:
        r = lowest[0][2]
        print(f"\nExample of a silence we did NOT alert on: "
              f"{clean_name(r['facts']['name']) or lowest[0][1]['mmsi']}, risk {r['risk']} "
              f"({'; '.join(t for p, t in r['reasons'] if p < 0)})")


if __name__ == "__main__":
    main()
