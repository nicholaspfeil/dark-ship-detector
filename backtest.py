"""
backtest.py — how many phone calls would a dispatcher actually get?

Runs every recording through the tracker and scorer (no waiting, no calls)
and compares raw silences with alerts that cross the threshold. Time is
counted only while the feed was actually up (outages are subtracted), so
"per day" means per 24 hours of real coverage.

    python backtest.py
    python backtest.py --threshold 60
"""

import argparse

from replay import list_sessions, load_session
from scoring import knowledge, score_event
from tracker import ShipTracker


def run_session(tag, threshold):
    tracker = ShipTracker()
    messages = load_session(tag)
    silences, alerts, harbor, gov = 0, [], 0, 0
    for msg in messages:
        for e in tracker.update(msg):
            if e["event"] != "silent":
                continue
            silences += 1
            r = score_event(e)
            harbor += bool(r["facts"]["harbor"])
            gov += r["facts"]["government"]
            if r["risk"] >= threshold:
                alerts.append((r["risk"], r["facts"]["name"]))
    span_h = (messages[-1]["time"] - messages[0]["time"]).total_seconds() / 3600
    outage_h = sum((b - a).total_seconds() for a, b in tracker.outages) / 3600
    return {"tag": tag, "covered_h": span_h - outage_h, "silences": silences,
            "alerts": alerts, "harbor": harbor, "gov": gov}


def main():
    parser = argparse.ArgumentParser(description="Alert volume across all recordings.")
    parser.add_argument("--threshold", type=int, default=70)
    args = parser.parse_args()

    knowledge()
    rows = [run_session(tag, args.threshold) for tag in list_sessions()]

    print(f"{'recording':<17}{'hours of data':>14}{'silences':>10}{'alerts':>8}   alerted ships")
    for r in rows:
        names = ", ".join(f"{(n or '?').strip()} ({k})" for k, n in r["alerts"]) or "-"
        print(f"{r['tag']:<17}{r['covered_h']:>14.1f}{r['silences']:>10}{len(r['alerts']):>8}   {names}")

    hours = sum(r["covered_h"] for r in rows)
    sil = sum(r["silences"] for r in rows)
    al = sum(len(r["alerts"]) for r in rows)
    print(f"{'TOTAL':<17}{hours:>14.1f}{sil:>10}{al:>8}")
    print(f"\nPer 24 hours of coverage: {sil / hours * 24:.0f} raw silences -> "
          f"{al / hours * 24:.1f} phone calls (risk >= {args.threshold}).")
    print(f"Filtered out: {sum(r['harbor'] for r in rows) / sil:.0%} were inside a harbor, "
          f"{sum(r['gov'] for r in rows) / sil:.0%} were government/military vessels.")


if __name__ == "__main__":
    main()
