"""
detect.py — run the feed through the ShipTracker, score each silence, and rank them.

    python detect.py                          # replay biggest recording at 600x
    python detect.py --speed 0                # whole recording instantly
    python detect.py --mode live              # live feed
    python detect.py --min-risk 50            # only print silences scoring 50+
    python detect.py --show-returns           # also print ships coming back
    python detect.py --alert                  # phone the dispatcher for the first risk-70+ ship
    python detect.py --alert --speaker        # same, but speak on the laptop instead of calling
"""

import argparse

from alert import send_alert_async
from feed import add_feed_args, get_feed
from scoring import alert_text, call_text, gap_text, knowledge, review_gap, score_event
from tracker import ShipTracker


def format_event(e, result=None):
    t = e["time"].strftime("%Y-%m-%d %H:%M")
    if e["event"] == "returned":
        return f"{t}  RETURNED {e['mmsi']}  {e['name'] or '?':<22.22} after {e['quiet_min']:.0f} min"
    name = result["facts"]["name"] or "?"
    reasons = "; ".join(f"{p:+d} {text}" for p, text in result["reasons"] if p)
    return f"{t}  RISK {result['risk']:>2}  {e['mmsi']}  {name:<22.22} {reasons}"


def main():
    parser = argparse.ArgumentParser(description="Detect ships that go silent and rank them by risk.")
    add_feed_args(parser)
    parser.add_argument("--min-risk", type=int, default=0, help="only print silences at or above this risk")
    parser.add_argument("--show-returns", action="store_true", help="also print 'returned' events")
    parser.add_argument("--top", type=int, default=5, help="how many to list in the final ranking")
    parser.add_argument("--alert", action="store_true", help="send a spoken alert for high-risk silences")
    parser.add_argument("--speaker", action="store_true", help="with --alert: laptop speaker instead of phone")
    parser.add_argument("--alert-threshold", type=int, default=70, help="minimum risk that triggers an alert")
    parser.add_argument("--max-alerts", type=int, default=1,
                        help="most alerts to send per run (default 1, so a demo can't spam your phone)")
    args = parser.parse_args()

    knowledge()  # learn coverage edge + ship registry from data/ before streaming
    tracker = ShipTracker()
    scored = []  # (risk, event, result) for every silence
    alerts_sent = []  # background alert threads
    n_msgs = 0
    try:
        for msg in get_feed(args.mode, args.session, args.speed):
            n_msgs += 1
            for e in tracker.update(msg):
                if e["event"] == "returned":
                    findings = review_gap(e)
                    if findings:
                        print(f"{e['time']:%Y-%m-%d %H:%M}  GAP      {gap_text(e, findings)}")
                    elif args.show_returns:
                        print(format_event(e))
                    continue
                result = score_event(e)
                scored.append((result["risk"], e, result))
                if result["risk"] >= args.min_risk:
                    print(format_event(e, result))
                if (args.alert and result["risk"] >= args.alert_threshold
                        and len(alerts_sent) < args.max_alerts):
                    text = call_text(e, result)
                    print(f"\n>>> ALERT: {text}\n")
                    alerts_sent.append(send_alert_async(text, use_phone=not args.speaker))
    except KeyboardInterrupt:
        pass

    outage_h = sum((b - a).total_seconds() for a, b in tracker.outages) / 3600
    print(f"\nDone: {n_msgs} messages, {len(tracker.ships)} ships, {len(scored)} silences, "
          f"{len(tracker.outages)} feed outages ({outage_h:.1f} h ignored).")
    print(f"\nTop {args.top} by risk:")
    shown = set()  # one line per ship: its highest-scoring silence
    for risk, e, result in sorted(scored, key=lambda s: -s[0]):
        if e["mmsi"] in shown:
            continue
        shown.add(e["mmsi"])
        print(f"  {alert_text(e, result)}")
        print("      why: " + "; ".join(f"{p:+d} {t}" for p, t in result["reasons"] if p))
        if len(shown) >= args.top:
            break


if __name__ == "__main__":
    main()
