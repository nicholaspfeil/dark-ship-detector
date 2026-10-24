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

    # 5. Ship type
    gov = is_government(e["mmsi"], name, ship_type)
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
            "from_point_loma_nm": distance_nm(POINT_LOMA, (lat, lon)),
            "bearing_from_point_loma": bearing_deg(POINT_LOMA, (lat, lon)),
        },
    }


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

    return ", ".join(parts) + f". Risk score {result['risk']} out of 100."
