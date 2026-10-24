"""
scoring.py — Milestone 4: turn a "silent" event into a risk score with reasons.

The score is NOT a yes/no verdict and NOT a calibrated probability. It's a
0-100 ranking: start at a base of 30, then each factor adds or subtracts
points, and every factor that fires leaves a plain-English reason. The
dispatcher hears the top ship and *why* it ranked high.

Factors (all based on the pre-event data exploration):
  1. Movement      moving ships vanishing is odd; stopped boats go quiet all the time
  2. Harbor        boats in San Diego / Mission Bay often switch off at the dock
  3. Coverage      vanishing deep inside receiver range is odd; near the edge, signals
                   fade naturally. The edge is LEARNED from the recordings.
  4. Reserve       inside, near, or heading toward the Cabrillo marine reserve
  5. Ship type     fishing up (illegal fishing story); government/military down
                   (Navy and Coast Guard go quiet legitimately)
  6. History       a ship that has already gone quiet and come back is less alarming
"""

import glob
import math
import os
import re
from collections import Counter

import pandas as pd

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
BASE_SCORE = 30

# Reference point for "receiver coverage": Point Loma, roughly where the
# shore receivers are. Coverage is measured as distance from here.
POINT_LOMA = (32.70, -117.24)
SECTOR_DEG = 30          # split the compass into 12 slices of 30 degrees
COVERAGE_PERCENTILE = 0.95

# Cabrillo State Marine Reserve (no-take zone), tip of Point Loma.
RESERVE_NAME = "the Cabrillo marine reserve"
RESERVE = [(32.6767, -117.2470), (32.6767, -117.2500), (32.6617, -117.2500),
           (32.6617, -117.2383), (32.6667, -117.2383)]
RESERVE_CENTER = (sum(p[0] for p in RESERVE) / len(RESERVE),
                  sum(p[1] for p in RESERVE) / len(RESERVE))

# Harbors as simple lat/lon boxes: (south, north, west, east).
HARBORS = {
    "San Diego Bay": (32.60, 32.735, -117.235, -117.10),
    "Mission Bay": (32.755, 32.80, -117.26, -117.19),
}

SHIP_TYPE_WORDS = {30: "fishing vessel", 31: "tug", 32: "tug", 33: "underwater operations vessel",
                   34: "dive boat", 35: "military vessel",
                   36: "sailboat", 37: "pleasure boat", 50: "pilot boat", 51: "rescue vessel",
                   52: "tug", 53: "port tender", 55: "law enforcement vessel", 58: "medical vessel"}
GOV_NAME = re.compile(r"US ?GOV|USNS|USCG|NOAA|WARSHIP|NAVY|CUTTER|^CG ?\d|^\d*PB\b|^PB\b")


# ---------- geometry ----------

def distance_nm(a, b):
    """Great-circle distance in nautical miles between (lat, lon) points (haversine formula)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 3440.065 * math.asin(math.sqrt(h))  # 3440 nm = Earth's radius


def bearing_deg(a, b):
    """Compass direction from point a to point b (0 = north, 90 = east)."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    x = math.sin(lon2 - lon1) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return math.degrees(math.atan2(x, y)) % 360


def angle_diff(a, b):
    """Smallest difference between two compass directions (0-180)."""
    return abs((a - b + 180) % 360 - 180)


def compass_word(deg):
    return ["north", "northeast", "east", "southeast",
            "south", "southwest", "west", "northwest"][int((deg + 22.5) // 45) % 8]


def in_polygon(lat, lon, poly):
    """Ray-casting test: count how many polygon edges a line going east crosses."""
    inside = False
    for (la1, lo1), (la2, lo2) in zip(poly, poly[1:] + poly[:1]):
        if (la1 > lat) != (la2 > lat):
            cross_lon = lo1 + (lat - la1) / (la2 - la1) * (lo2 - lo1)
            if lon < cross_lon:
                inside = not inside
    return inside


def move(lat, lon, course_deg, dist_nm):
    """Where you end up going dist_nm along course_deg. Flat-earth math is fine
    over a few miles: 1 minute of latitude = 1 nautical mile."""
    c = math.radians(course_deg)
    dlat = dist_nm * math.cos(c) / 60
    dlon = dist_nm * math.sin(c) / (60 * math.cos(math.radians(lat)))
    return lat + dlat, lon + dlon


def project_course(lat, lon, sog, cog, minutes):
    """
    Dead reckoning: assume the ship kept the same speed and course after it went
    silent. Walk along that path in 20-second steps for `minutes` and report
    the closest it gets to the reserve, and when.
    Returns {"now": (lat, lon), "enters_reserve": bool,
             "closest_nm": float, "minutes_to_closest": float} or None.
    """
    if sog is None or cog is None or sog < 1 or minutes <= 0:
        return None
    best = (distance_nm((lat, lon), RESERVE_CENTER), 0.0)
    enters = False
    steps = int(minutes * 3)  # 3 steps per minute = every 20 s
    for i in range(1, steps + 1):
        m = i / 3
        p = move(lat, lon, cog, sog * m / 60)
        if in_polygon(*p, RESERVE):
            enters = True
            best = (0.0, m)
            break
        d = distance_nm(p, RESERVE_CENTER)
        if d < best[0]:
            best = (d, m)
    return {"now": move(lat, lon, cog, sog * minutes / 60), "enters_reserve": enters,
            "closest_nm": best[0], "minutes_to_closest": best[1]}


def harbor_at(lat, lon):
    for name, (s, n, w, e) in HARBORS.items():
        if s <= lat <= n and w <= lon <= e:
            return name
    return None


# ---------- things learned from the recordings ----------

class Knowledge:
    """Facts learned once from data/: receiver coverage edge, and a ship registry."""

    def __init__(self, data_dir=DATA_DIR):
        self.coverage_nm = {}   # sector start degree -> coverage edge distance (nm)
        self.registry = {}      # mmsi -> {"ship_type", "name", "length_m"}
        self._learn_coverage(glob.glob(os.path.join(data_dir, "ais_*.csv")))
        self._learn_registry(glob.glob(os.path.join(data_dir, "ships_*.csv")))

    def _learn_coverage(self, files):
        """For each compass slice around Point Loma, the distance within which 95% of
        all reports were heard = where coverage effectively ends in that direction."""
        if not files:
            return
        df = pd.concat([pd.read_csv(f, usecols=["lat", "lon"]) for f in files])
        dists = {}
        for lat, lon in zip(df["lat"], df["lon"]):
            p = (lat, lon)
            sector = int(bearing_deg(POINT_LOMA, p) // SECTOR_DEG) * SECTOR_DEG
            dists.setdefault(sector, []).append(distance_nm(POINT_LOMA, p))
        for sector, ds in dists.items():
            if len(ds) >= 50:  # too few reports = not enough to learn from
                self.coverage_nm[sector] = float(pd.Series(ds).quantile(COVERAGE_PERCENTILE))

    def _learn_registry(self, files):
        """mmsi -> most common non-zero ship type seen in any recording."""
        if not files:
            return
        df = pd.concat([pd.read_csv(f) for f in files])
        for mmsi, g in df.groupby("mmsi"):
            types = [int(t) for t in g["ship_type"].dropna() if t != 0]
            self.registry[int(mmsi)] = {
                "ship_type": Counter(types).most_common(1)[0][0] if types else None,
                "name": g["ship_name"].dropna().iloc[-1] if g["ship_name"].notna().any() else None,
                "length_m": g["length_m"].max(),
            }

    def coverage_outline(self):
        """The learned coverage edge as a closed ring of [lat, lon] points (for maps):
        one point per compass slice, at that slice's edge distance."""
        ring = [list(move(*POINT_LOMA, sector + SECTOR_DEG / 2, dist))
                for sector, dist in sorted(self.coverage_nm.items())]
        return ring + ring[:1]

    def coverage_edge(self, lat, lon):
        sector = int(bearing_deg(POINT_LOMA, (lat, lon)) // SECTOR_DEG) * SECTOR_DEG
        return self.coverage_nm.get(sector)


_knowledge = None


def knowledge():
    """Load Knowledge once and reuse it (reading the CSVs takes a moment)."""
    global _knowledge
    if _knowledge is None:
        _knowledge = Knowledge()
    return _knowledge


# ---------- the score ----------

def is_government(mmsi, name, ship_type):
    # MMSIs starting 3669 are assigned to US federal vessels (Navy, Coast Guard, NOAA...).
    return (str(mmsi).startswith("3669") or ship_type in (35, 55)
            or bool(name and GOV_NAME.search(name.upper())))


def score_event(e, kb=None):
    """
    Score one "silent" event. Returns a dict:
      risk     0-100 (higher = more suspicious)
      reasons  list of (points, text), biggest effect first
      facts    numbers the spoken alert uses (distances, type word...)
    """
    kb = kb or knowledge()
    reg = kb.registry.get(e["mmsi"], {})
    ship_type = e["ship_type"] or reg.get("ship_type")
    name = e["name"] or reg.get("name")
    lat, lon, sog, cog = e["lat"], e["lon"], e["sog"], e["cog"]
    reasons = []

    def add(points, text):
        reasons.append((points, text))

    # 1. Movement
    if sog is None:
        add(0, "speed unknown")
    elif sog >= 2:
        add(20, f"was moving {sog:.0f} knots when it went silent")
    elif sog >= 1:
        add(5, f"was drifting at {sog:.1f} knots")
    else:
        add(-20, "was stopped when it went silent")

    # 2. Harbor / 3. Coverage
    harbor = harbor_at(lat, lon)
    inside_nm = None
    if harbor:
        stopped = sog is not None and sog < 1
        add(-30 if stopped else -10,
            f"inside {harbor}, where boats often switch off at the dock")
    else:
        edge = kb.coverage_edge(lat, lon)
        if edge is not None:
            inside_nm = edge - distance_nm(POINT_LOMA, (lat, lon))
            if inside_nm >= 10:
                add(20, f"{inside_nm:.0f} miles inside receiver coverage, where signals are normally strong")
            elif inside_nm >= 3:
                add(5, f"{inside_nm:.0f} miles inside receiver coverage")
            else:
                add(-25, "near the edge of receiver range, where signals normally fade")

    # 4. Marine reserve
    reserve_nm = distance_nm((lat, lon), RESERVE_CENTER)
    # Not counted inside a harbor: the harbor exit channel runs right past the
    # reserve, so every boat leaving the bay would look like it's "heading there".
    toward_reserve = (not harbor and cog is not None and sog is not None and sog >= 1
                      and reserve_nm < 10
                      and angle_diff(cog, bearing_deg((lat, lon), RESERVE_CENTER)) < 45)
    if in_polygon(lat, lon, RESERVE):
        add(35, f"last seen inside {RESERVE_NAME}")
    elif reserve_nm < 1:
        add(25, f"last seen within a mile of {RESERVE_NAME}")
    elif toward_reserve:
        add(20 if reserve_nm < 5 else 10, f"heading toward {RESERVE_NAME}, {reserve_nm:.0f} miles away")
    elif reserve_nm < 3:
        add(10, f"{reserve_nm:.0f} miles from {RESERVE_NAME}")

    # 4b. Projected course: if it kept going the same way during the silence,
    # would it be in (or right next to) the reserve by now?
    projection = None if harbor else project_course(lat, lon, sog, cog, e["quiet_min"])
    if projection and projection["minutes_to_closest"] > 0:
        if projection["enters_reserve"]:
            add(15, f"on its last course it would have entered {RESERVE_NAME} "
                    f"{projection['minutes_to_closest']:.0f} minutes after going silent")
        elif projection["closest_nm"] < 0.5:
            add(5, f"on its last course it would have passed within half a mile of {RESERVE_NAME}")

    # 5. Ship type (and whether it MOVES like a fishing boat, whatever its label says)
    gov = is_government(e["mmsi"], name, ship_type)
    if not gov and not harbor and ship_type != 30 and fishing_like(e.get("recent", [])):
        add(15, "was moving like a fishing boat before it went dark: slow, with frequent turns")
    if gov:
        add(-40, "government or military vessel, which often go quiet on duty")
    elif ship_type == 30:
        add(20, "fishing vessel")
    elif ship_type in (31, 32, 50, 52, 53):
        add(-10, "harbor work boat")
    elif ship_type is not None and 60 <= ship_type <= 69:
        add(-10, "passenger or tour boat on a regular route")
    elif ship_type is None:
        add(0, "ship type unknown")

    # 6. History
    prior = e["silence_count"] - 1
    if prior > 0:
        add(-10 * min(prior, 2), f"has gone quiet {prior} time{'s' if prior > 1 else ''} before and come back")

    risk = max(1, min(99, BASE_SCORE + sum(p for p, _ in reasons)))
    reasons.sort(key=lambda r: -abs(r[0]))  # biggest effect first
    return {
        "risk": risk,
        "reasons": reasons,
        "facts": {
            "name": name, "ship_type": ship_type, "government": gov,
            "type_word": "government vessel" if gov else SHIP_TYPE_WORDS.get(ship_type, _type_family(ship_type)),
            "harbor": harbor, "inside_coverage_nm": inside_nm,
            "reserve_nm": reserve_nm, "toward_reserve": toward_reserve,
            "projection": projection,
            "from_point_loma_nm": distance_nm(POINT_LOMA, (lat, lon)),
            "bearing_from_point_loma": bearing_deg(POINT_LOMA, (lat, lon)),
        },
    }


def fishing_like(recent):
    """
    Fishing boats trawl or work lines slowly (about 1-5 knots) and keep turning.
    Transiting boats go faster in a straight line; moored boats sit at 0.
    True if the last readings look like fishing: median speed 1-5 kn and
    an average course change of more than 30 degrees between reports.
    """
    pts = [(s, c) for s, c in recent if s is not None and c is not None]
    if len(pts) < 5:
        return False
    speeds = sorted(s for s, _ in pts)
    median = speeds[len(speeds) // 2]
    turns = [angle_diff(a[1], b[1]) for a, b in zip(pts, pts[1:])]
    return 1 <= median <= 5 and sum(turns) / len(turns) > 30


def review_gap(e):
    """
    When a silent ship reappears, reconstruct the dark gap: it went dark at A and
    came back at B, so it must have traveled from A to B in the meantime. The
    straightest possible route is the line A->B (the real path can only be longer).
    Returns a list of plain-English findings (empty = nothing notable).
    """
    a, b = (e["lat"], e["lon"]), (e["back_lat"], e["back_lon"])
    dist = distance_nm(a, b)
    findings = []
    # Walk the straight line A->B in 40 steps and check it against the reserve.
    closest = min(distance_nm((a[0] + (b[0] - a[0]) * i / 40, a[1] + (b[1] - a[1]) * i / 40),
                              RESERVE_CENTER) for i in range(41))
    crossed = any(in_polygon(a[0] + (b[0] - a[0]) * i / 40, a[1] + (b[1] - a[1]) * i / 40, RESERVE)
                  for i in range(41))
    if crossed:
        findings.append(f"its shortest path while dark ran through {RESERVE_NAME}")
    elif closest < 0.5 and dist > 0.3:
        findings.append(f"its shortest path while dark passed within half a mile of {RESERVE_NAME}")
    # Speed check uses real elapsed time: ships keep moving during feed outages.
    real_hours = (e["time"] - e["last_seen"]).total_seconds() / 3600
    if real_hours > 0 and dist / real_hours > 40:
        findings.append(f"it would have needed {dist / real_hours:.0f} knots to get there, "
                        "faster than almost any boat here; the position data may be spoofed")
    near_a, near_b = distance_nm(a, RESERVE_CENTER), distance_nm(b, RESERVE_CENTER)
    if e["quiet_min"] >= 30 and near_a < 2 and near_b < 2:
        findings.append(f"it stayed near {RESERVE_NAME} for {e['quiet_min']:.0f} minutes while dark")
    return findings


def gap_text(e, findings):
    """Spoken follow-up when a flagged ship reappears."""
    name = clean_name(e["name"]) or f"ID {e['mmsi']}"
    dist = distance_nm((e["lat"], e["lon"]), (e["back_lat"], e["back_lon"]))
    return (f"Update. {name} is transmitting again after {e['quiet_min']:.0f} minutes dark, "
            f"{dist:.1f} miles from where it went silent. " + " ".join(f[0].upper() + f[1:] + "." for f in findings))


def _type_family(t):
    if t is None:
        return "vessel"
    if 60 <= t <= 69:
        return "passenger ship"
    if 70 <= t <= 79:
        return "cargo ship"
    if 80 <= t <= 89:
        return "tanker"
    return "vessel"


def clean_name(name):
    """'LEGACY        ?' -> 'Legacy'. AIS names are typed by crews and often have junk."""
    name = re.sub(r"[^A-Za-z0-9 '\-]", " ", name or "")
    return " ".join(w if re.search(r"\d|^(US|USNS|USCG|NOAAS?|CG|PB|RV)$", w) else w.title()
                    for w in name.upper().split())


def alert_text(e, result):
    """The sentence a dispatcher hears on the phone (milestone 5 speaks this)."""
    f = result["facts"]
    minutes = e["quiet_min"]  # silence time with feed outages already removed
    name = clean_name(f["name"])
    who = f"{f['type_word'].capitalize()} {name}" if name else f"Unidentified {f['type_word']}, ID {e['mmsi']},"
    parts = [f"Alert. {who} went silent {minutes:.0f} minutes ago"]

    if in_polygon(e["lat"], e["lon"], RESERVE):
        parts.append(f"inside {RESERVE_NAME}")
    elif f["harbor"]:
        parts.append(f"inside {f['harbor']}")
    else:
        if f["from_point_loma_nm"] < 1:
            where = "just off Point Loma"
        else:
            where = (f"{f['from_point_loma_nm']:.0f} miles "
                     f"{compass_word(f['bearing_from_point_loma'])} of Point Loma")
        if f["inside_coverage_nm"] is not None and f["inside_coverage_nm"] >= 3:
            where += f", {f['inside_coverage_nm']:.0f} miles inside receiver coverage"
        parts.append(where)

    sog, cog = e["sog"], e["cog"]
    if sog is not None and sog >= 1:
        if f["toward_reserve"]:
            parts.append(f"moving {sog:.0f} knots toward {RESERVE_NAME}")
        elif cog is not None:
            parts.append(f"moving {sog:.0f} knots heading {compass_word(cog)}")
        else:
            parts.append(f"moving {sog:.0f} knots")
    elif sog is not None:
        parts.append("stopped")

    text = ", ".join(parts) + "."
    p = f["projection"]
    if p and p["minutes_to_closest"] > 0 and (p["enters_reserve"] or p["closest_nm"] < 0.5):
        verb = "entered" if p["enters_reserve"] else "passed within half a mile of"
        text += (f" If it held course, it {verb} the reserve about "
                 f"{p['minutes_to_closest']:.0f} minutes after going silent.")
    return text + f" Risk score {result['risk']} out of 100."


def call_text(e, result):
    """What the phone says: the alert, then the main reasons it ranked high."""
    reasons = [t for p, t in result["reasons"] if p > 0][:3]
    text = alert_text(e, result)
    if reasons:
        text += " Main reasons: " + "; ".join(reasons) + "."
    return text
