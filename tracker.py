"""
tracker.py — Milestone 3: remember every ship, and notice when one goes silent.

ShipTracker keeps one record ("state") per ship, keyed by MMSI: where it was
last seen, how fast it was going, what type of ship it is, and how often it
normally reports. Feed it messages one at a time with `tracker.update(msg)`;
it returns a list of *events*:

    {"event": "silent",   ...}  a ship has been quiet much longer than normal
    {"event": "returned", ...}  a silent ship started reporting again

Two rules keep this honest:
1. The clock is the feed's own timestamps, never the laptop clock. In replay
   mode time is sped up, so the laptop clock would be meaningless.
2. Feed outages don't count. If NO ship reports for 5+ minutes, the problem
   is the feed (or our connection), not the ships. That time is subtracted
   from every ship's silence. The recordings have outages of up to 20 hours.
"""

import statistics
from collections import deque

# A ship is "silent" once it has been quiet for longer than BOTH of these:
MIN_SILENCE_MIN = 15  # 90% of normal gaps are under 15 min (pre-event data)
GAP_MULTIPLIER = 4    # ...and 4x this ship's own typical gap between reports
# A ship needs a few reports before we trust its "typical gap" (and before we
# think it was really being tracked rather than glimpsed once at the edge).
MIN_REPORTS = 3
# If no ship at all reports for this long, it's a feed outage.
FEED_OUTAGE_MIN = 5
# Only keep the last N gaps per ship (enough for a stable median).
GAP_HISTORY = 30


class ShipTracker:
    def __init__(self):
        self.ships = {}        # mmsi -> state dict
        self.now = None        # latest timestamp seen in the feed
        self.outages = []      # list of (start, end) timestamps when the feed was down

    # ---------- public ----------

    def update(self, msg):
        """Take one message, update state, and return any new events."""
        events = []
        t = msg["time"]
        if self.now is not None and t < self.now:
            t = self.now  # out-of-order message: don't let the clock go backwards

        # 1. Did the whole feed just come back from an outage?
        if self.now is not None and (t - self.now).total_seconds() > FEED_OUTAGE_MIN * 60:
            self.outages.append((self.now, t))
        self.now = t

        # 2. Update this ship's record.
        ship = self._get_ship(msg["mmsi"])
        if msg["ship_name"]:
            ship["name"] = msg["ship_name"]
        if msg["type"] == "static":
            for k in ("ship_type", "length_m", "destination"):
                if msg[k] is not None:
                    ship[k] = msg[k]
        else:
            if ship["last_seen"] is not None:
                gap_min = self.quiet_minutes(ship["last_seen"], t)
                ship["gaps_min"] = (ship["gaps_min"] + [gap_min])[-GAP_HISTORY:]
            if ship["silent"]:
                ship["silent"] = False
                ev = self._event("returned", ship)  # lat/lon = where it went dark
                ev["back_lat"], ev["back_lon"] = msg["lat"], msg["lon"]  # where it came back
                events.append(ev)
            ship.update(last_seen=t, lat=msg["lat"], lon=msg["lon"],
                        sog=msg["sog"], cog=msg["cog"])
            ship["reports"] += 1
            ship["recent"].append((msg["sog"], msg["cog"]))  # for movement patterns
            if ship["first_seen"] is None:
                ship["first_seen"] = t

        # 3. Has any other ship now been quiet for too long?
        events += self.check_silences()
        return events

    def check_silences(self):
        """Mark ships that just crossed their silence threshold. Each silence is reported once."""
        events = []
        for ship in self.ships.values():
            if ship["silent"] or ship["last_seen"] is None or ship["reports"] < MIN_REPORTS:
                continue
            if self.quiet_minutes(ship["last_seen"], self.now) > self.threshold_min(ship):
                ship["silent"] = True
                ship["silence_count"] += 1
                events.append(self._event("silent", ship))
        return events

    def threshold_min(self, ship):
        """How long this particular ship must be quiet before it counts as silent."""
        typical = statistics.median(ship["gaps_min"]) if ship["gaps_min"] else 0
        return max(MIN_SILENCE_MIN, GAP_MULTIPLIER * typical)

    def quiet_minutes(self, since, until):
        """Minutes between two times, NOT counting any feed outage in between."""
        total = (until - since).total_seconds()
        for start, end in self.outages:
            overlap = (min(end, until) - max(start, since)).total_seconds()
            if overlap > 0:
                total -= overlap
        return max(total, 0) / 60

    # ---------- internal ----------

    def _get_ship(self, mmsi):
        if mmsi not in self.ships:
            self.ships[mmsi] = {
                "mmsi": mmsi, "name": None, "ship_type": None, "length_m": None,
                "destination": None, "first_seen": None, "last_seen": None,
                "lat": None, "lon": None, "sog": None, "cog": None,
                "reports": 0, "gaps_min": [], "silent": False, "silence_count": 0,
                "recent": deque(maxlen=10),  # last 10 (speed, course) readings
            }
        return self.ships[mmsi]

    def _event(self, kind, ship):
        """A snapshot of the ship at the moment of the event (milestone 4 scores these)."""
        return {
            "event": kind,
            "time": self.now,
            "mmsi": ship["mmsi"],
            "name": ship["name"],
            "ship_type": ship["ship_type"],
            "length_m": ship["length_m"],
            "destination": ship["destination"],
            "last_seen": ship["last_seen"],
            "quiet_min": self.quiet_minutes(ship["last_seen"], self.now),
            "threshold_min": self.threshold_min(ship),
            "lat": ship["lat"], "lon": ship["lon"],
            "sog": ship["sog"], "cog": ship["cog"],
            "reports": ship["reports"],
            "silence_count": ship["silence_count"],  # how many times it has gone silent so far
            "recent": list(ship["recent"]),
        }
