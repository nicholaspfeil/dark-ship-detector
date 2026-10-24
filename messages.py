"""
messages.py — the one common shape every ship message takes.

Replay mode (reading CSVs) and live mode (the aisstream WebSocket) both turn
their raw data into the SAME kind of Python dict, defined here. Everything
downstream (tracking, silence detection, scoring) only ever sees these dicts,
so it doesn't care whether the data is recorded or live.

Two message types:
  "position": where a ship is right now (lat, lon, speed, course, heading).
  "static":   what a ship is (type code, size, destination).
"""

import math

# AIS uses special "sentinel" values to mean "no data". We turn them into None
# so later code can't mistake them for real readings (e.g. heading 511 degrees).
HEADING_UNKNOWN = 511
COURSE_UNKNOWN = 360
SPEED_UNKNOWN = 102.3
MAX_REAL_SPEED_KN = 50  # nothing in this area goes faster; higher = junk


def _num(value):
    """Turn a value into a float, or None if it's missing (NaN/empty)."""
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else x


def _text(value):
    """Turn a value into a clean string, or None if missing."""
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    s = str(value).strip()
    return s or None


def make_position(time, mmsi, ship_name, lat, lon, sog, cog, heading, nav_status):
    """Build a cleaned "position" message. `time` is a pandas/datetime timestamp (UTC)."""
    sog = _num(sog)
    if sog is not None and (sog >= SPEED_UNKNOWN or sog > MAX_REAL_SPEED_KN):
        sog = None
    cog = _num(cog)
    if cog is not None and cog >= COURSE_UNKNOWN:
        cog = None
    heading = _num(heading)
    if heading is not None and heading == HEADING_UNKNOWN:
        heading = None
    return {
        "type": "position",
        "time": time,
        "mmsi": int(mmsi),        # MMSI = the ship's unique 9-digit radio ID
        "ship_name": _text(ship_name),
        "lat": _num(lat),
        "lon": _num(lon),
        "sog": sog,               # speed over ground, knots
        "cog": cog,               # course over ground, degrees (direction of travel)
        "heading": heading,       # direction the bow points, degrees
        "nav_status": _num(nav_status),  # crew-set, unreliable; kept for reference only
    }


def make_static(time, mmsi, ship_name, ship_type, length_m, width_m, draught_m,
                destination, call_sign, imo):
    """Build a cleaned "static" message (ship identity/type info)."""
    ship_type = _num(ship_type)
    return {
        "type": "static",
        "time": time,
        "mmsi": int(mmsi),
        "ship_name": _text(ship_name),
        "ship_type": int(ship_type) if ship_type is not None else None,
        "length_m": _num(length_m),
        "width_m": _num(width_m),
        "draught_m": _num(draught_m),
        "destination": _text(destination),
        "call_sign": _text(call_sign),
        "imo": _num(imo),
    }
