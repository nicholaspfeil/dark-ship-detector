"""
briefing.py — a spoken shift briefing: one phone call that sums up a whole recording.

Like a dispatcher's start-of-shift handoff: how many ships went silent, how
many were routine, and the few worth checking, with the main reason for each.

    python briefing.py --print      # just print what would be said
    python briefing.py --speaker    # say it on the laptop
    python briefing.py              # phone it to MY_PHONE_NUMBER
    python briefing.py --session 20261023_184344
"""

import argparse

from alert import send_alert
from demo import DEMO_SESSION
from replay import load_session
from scoring import clean_name, knowledge, score_event
from tracker import ShipTracker

WORTH_CHECKING = 60   # risk at or above this gets named in the briefing
MAX_NAMED = 3


def build_briefing(tag):
    kb = knowledge()
    tracker = ShipTracker()
    messages = load_session(tag)
    best = {}  # mmsi -> (risk, event, result): each ship's most suspicious silence
    total = routine = 0
    for msg in messages:
        for e in tracker.update(msg):
            if e["event"] != "silent":
                continue
            total += 1
            r = score_event(e, kb)
            routine += r["risk"] < WORTH_CHECKING
            if e["mmsi"] not in best or r["risk"] > best[e["mmsi"]][0]:
                best[e["mmsi"]] = (r["risk"], e, r)

    flagged = sorted((b for b in best.values() if b[0] >= WORTH_CHECKING), key=lambda b: -b[0])
    hours = ((messages[-1]["time"] - messages[0]["time"]).total_seconds()
             - sum((b - a).total_seconds() for a, b in tracker.outages)) / 3600

    parts = [f"Shift briefing from the Dark Ship Detector. In {hours:.0f} hours of coverage off San Diego, "
             f"ships went silent {total} times. {routine} of those were routine, "
             f"mostly boats docked in the bay or government vessels."]
    if not flagged:
        parts.append("Nothing needs a closer look.")
    else:
        n = len(flagged)
        parts.append(f"{n} {'ship is' if n == 1 else 'ships are'} worth checking."
                     + (f" The top {MAX_NAMED}:" if n > MAX_NAMED else ""))
        for i, (risk, e, r) in enumerate(flagged[:MAX_NAMED]):
            name = clean_name(r["facts"]["name"])
            who = f"{r['facts']['type_word']} {name}" if name else f"an unidentified {r['facts']['type_word']}"
            when = e["time"].tz_convert("America/Los_Angeles").strftime("%I:%M %p").lstrip("0")
            # Two strongest reasons, e.g. "was moving 12 knots ... and 25 miles inside receiver coverage ..."
            reasons = " and ".join([t.split(",")[0] for p, t in r["reasons"] if p > 0][:2])
            ordinal = ["First", "Second", "Third"][i]
            parts.append(f"{ordinal}: {who}, risk {risk}, at {when}. It {reasons}.")
    parts.append("End of briefing.")
    return " ".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Phone a spoken summary of a recording.")
    parser.add_argument("--session", default=DEMO_SESSION)
    parser.add_argument("--print", action="store_true", help="only print the briefing text")
    parser.add_argument("--speaker", action="store_true", help="laptop voice instead of a phone call")
    args = parser.parse_args()

    text = build_briefing(args.session)
    print(text)
    if not args.print:
        print(f"[briefing] delivered by: {send_alert(text, use_phone=not args.speaker)}")


if __name__ == "__main__":
    main()
