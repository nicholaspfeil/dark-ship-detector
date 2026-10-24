"""
evaluate.py — how often does the detector catch a dark ship? Measured, not guessed.

There's no list of confirmed real dark ships, so we make labeled test cases:
SIMULATED boats (radio IDs 999xxxxxx, never real) are mixed into a real
recording. Each reports normally for 30-45 minutes, then goes dark near the
Cabrillo reserve. Two scenarios:
  transit: heads straight for the reserve at 6-12 knots, then goes dark
  fishing: works slowly (2-4 knots, constant turns) 1-3 miles from the reserve,
           labeled as a pleasure boat, then goes dark
We count how many get an alert (risk >= 70). False alarms come from the real
traffic, which backtest.py already measures (~17 calls per 24 h).

    python evaluate.py
"""

import argparse
import random

import pandas as pd

from messages import make_position, make_static
from replay import list_sessions, load_session
from scoring import RESERVE_CENTER, bearing_deg, knowledge, move, score_event
from tracker import ShipTracker

THRESHOLD = 70


def quiet_window(times, t0, minutes=80):
    """True if the real feed has no 5+ minute outage in [t0, t0 + minutes]:
    test ships should go dark while the feed is up, or the outage rule hides them."""
    window = [t for t in times if t0 <= t <= t0 + pd.Timedelta(minutes=minutes)]
    return len(window) > 10 and all((b - a).total_seconds() < 300 for a, b in zip(window, window[1:]))


def fake_ship(rng, mmsi, t0, scenario):
    """Messages for one simulated boat: normal reports, then silence."""
    msgs = [make_static(t0, mmsi, f"TEST {mmsi % 1000}", 37, 12, 4, 1, None, None, 0)]
    if scenario == "transit":
        lat, lon = move(*RESERVE_CENTER, rng.uniform(200, 300), rng.uniform(5, 9))
    else:
        lat, lon = move(*RESERVE_CENTER, rng.uniform(200, 300), rng.uniform(1, 3))
    course = rng.uniform(0, 360)
    t, end = t0, t0 + pd.Timedelta(minutes=rng.uniform(30, 45))
    while t < end:
        if scenario == "transit":
            sog, course = rng.uniform(6, 12), bearing_deg((lat, lon), RESERVE_CENTER) + rng.uniform(-8, 8)
        else:
            sog, course = rng.uniform(2, 4), (course + rng.choice([-1, 1]) * rng.uniform(35, 90)) % 360
        msgs.append(make_position(t, mmsi, f"TEST {mmsi % 1000}", lat, lon, sog, course, None, 0))
        step = rng.uniform(1.5, 3.5)  # minutes until the next report
        lat, lon = move(lat, lon, course, sog * step / 60)
        t += pd.Timedelta(minutes=step)
    return msgs  # ...and then nothing: it went dark


def main():
    parser = argparse.ArgumentParser(description="Detection rate on simulated dark ships.")
    parser.add_argument("--per-session", type=int, default=10, help="test ships per scenario per recording")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    kb = knowledge()
    rng = random.Random(args.seed)
    results = {"transit": [0, 0], "fishing": [0, 0]}  # caught, total
    mmsi = 999000000
    for tag in list_sessions():
        real = load_session(tag)
        times = [m["time"] for m in real]
        fakes = {}
        for scenario in results:
            placed = 0
            while placed < args.per_session:
                t0 = rng.choice(times[: int(len(times) * 0.9)])
                if not quiet_window(times, t0):
                    continue
                mmsi += 1
                fakes[mmsi] = scenario
                real += fake_ship(rng, mmsi, t0, scenario)
                placed += 1
        real.sort(key=lambda m: m["time"])

        tracker, caught = ShipTracker(), set()
        for msg in real:
            for e in tracker.update(msg):
                if e["event"] == "silent" and e["mmsi"] in fakes and score_event(e, kb)["risk"] >= THRESHOLD:
                    caught.add(e["mmsi"])
        for m, scenario in fakes.items():
            results[scenario][0] += m in caught
            results[scenario][1] += 1

    print(f"Simulated dark ships mixed into {len(list_sessions())} real recordings (alert = risk >= {THRESHOLD}):")
    for scenario, (c, n) in results.items():
        print(f"  {scenario:<8} caught {c}/{n}  ({c / n:.0%})")
    c = sum(v[0] for v in results.values()); n = sum(v[1] for v in results.values())
    print(f"  overall  caught {c}/{n}  ({c / n:.0%})")
    print("False alarms come from real traffic: see backtest.py (~17 calls per 24 h at risk 70).")


if __name__ == "__main__":
    main()
