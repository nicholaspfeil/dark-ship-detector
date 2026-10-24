"""
dashboard.py — an optional live chart that plays alongside the phone call.

The phone call is the real interface; this is for the room. It runs a tiny
web server on this laptop (Python's built-in http.server, nothing to install)
that serves web/dashboard.html. The detector writes its current picture of
the sea to web/state.json a few times per second, and the page re-reads that
file and redraws. No database, no WebSockets: just a file that keeps changing.

Used by demo.py:  python demo.py --dashboard
"""

import functools
import http.server
import json
import os
import threading
import time
import webbrowser
from collections import deque

from scoring import HARBORS, POINT_LOMA, RESERVE, clean_name, knowledge, move

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
STATE_FILE = os.path.join(WEB_DIR, "state.json")
TRAIL_POINTS = 12        # how many past positions to draw behind each ship
MAX_REACH_NM = 25        # cap on the "could be anywhere in here" circle
FEED_LENGTH = 14         # silences shown in the side log
PUBLISH_EVERY_S = 0.25   # write state.json at most 4 times per second
LOCAL_TZ = "America/Los_Angeles"


def _clock(t):
    return t.tz_convert(LOCAL_TZ).strftime("%I:%M %p").lstrip("0")


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files from web/ without printing a log line per request,
    and tells the browser never to cache (state.json changes constantly)."""

    def log_message(self, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


class Dashboard:
    def __init__(self, port=8765, speed=None):
        self.port = port
        self.speed = speed
        self.trails = {}        # mmsi -> recent [lat, lon] positions
        self.silences = {}      # mmsi -> (event, result) while that ship is silent
        self.feed = deque(maxlen=FEED_LENGTH)
        self.phase = "learning"
        self.alert = None
        self.top = None
        self.frozen = False     # after the alert, the chart stops moving
        self._ships = []
        self._ghosts = []
        self._now = None
        self._silence_total = 0
        self._last_write = 0.0
        self._lock = threading.Lock()
        kb = knowledge()
        self.static = {
            "center": list(POINT_LOMA),
            "reserve": [list(p) for p in RESERVE],
            "harbors": [[[s, w], [n, e]] for s, n, w, e in HARBORS.values()],
            "edge": kb.coverage_outline(),
        }

    # ---------- server ----------

    def start(self, open_browser=True):
        os.makedirs(WEB_DIR, exist_ok=True)
        self.publish(force=True)  # so the page has something to read immediately
        handler = functools.partial(_QuietHandler, directory=WEB_DIR)
        server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{self.port}/dashboard.html"
        print(f"Dashboard: {url}")
        if open_browser:
            webbrowser.open(url)
        return url

    # ---------- feeding it ----------

    def on_message(self, msg):
        if self.frozen or msg["type"] != "position" or msg["lat"] is None:
            return
        trail = self.trails.setdefault(msg["mmsi"], deque(maxlen=TRAIL_POINTS))
        trail.append([round(msg["lat"], 5), round(msg["lon"], 5)])

    def on_event(self, e, result=None):
        if self.frozen:
            return
        if e["event"] == "returned":
            self.silences.pop(e["mmsi"], None)
            return
        self.silences[e["mmsi"]] = (e, result)
        top = next((t for p, t in result["reasons"] if p), "")
        self.feed.appendleft({"time": _clock(e["time"]), "mmsi": e["mmsi"],
                              "name": clean_name(result["facts"]["name"]) or f"ID {e['mmsi']}",
                              "risk": result["risk"], "reason": top})

    def set_alert(self, e, result, text, status):
        self.alert = {"mmsi": e["mmsi"], "name": clean_name(result["facts"]["name"]) or f"ID {e['mmsi']}",
                      "type_word": result["facts"]["type_word"], "risk": result["risk"],
                      "text": text, "status": status, "lat": e["lat"], "lon": e["lon"],
                      "reasons": [[p, t] for p, t in result["reasons"] if p]}
        self.phase = "alert"

    def set_alert_status(self, status):
        if self.alert:
            self.alert["status"] = status
            self.publish(force=True)

    def set_top(self, rows):
        self.top = rows
        self.phase = "done"

    # ---------- writing state.json ----------

    def snapshot(self, tracker):
        """Rebuild the ships and ghosts lists from the tracker (skipped once frozen)."""
        if self.frozen or tracker.now is None:
            return
        now = tracker.now
        ships, ghosts = [], []
        for s in tracker.ships.values():
            if s["last_seen"] is None or s["lat"] is None:
                continue
            if s["silent"] and s["mmsi"] in self.silences:
                e, r = self.silences[s["mmsi"]]
                quiet = tracker.quiet_minutes(s["last_seen"], now)
                sog, cog = s["sog"], s["cog"]
                reach = min((sog or 0) * quiet / 60, MAX_REACH_NM)
                proj = list(move(s["lat"], s["lon"], cog, reach)) if cog is not None and (sog or 0) >= 1 else None
                ghosts.append({"mmsi": s["mmsi"], "name": clean_name(r["facts"]["name"]) or f"ID {s['mmsi']}",
                               "lat": s["lat"], "lon": s["lon"], "risk": r["risk"],
                               "quiet": round(quiet), "reach_nm": round(reach, 2), "proj": proj})
            elif not s["silent"]:
                ships.append({"mmsi": s["mmsi"], "lat": s["lat"], "lon": s["lon"],
                              "moving": (s["sog"] or 0) >= 1,
                              "trail": list(self.trails.get(s["mmsi"], []))})
        self._ships, self._ghosts, self._now = ships, ghosts, now
        self._silence_total = sum(s["silence_count"] for s in tracker.ships.values())

    def publish(self, tracker=None, force=False):
        now_s = time.time()
        if not force and now_s - self._last_write < PUBLISH_EVERY_S:
            return
        self._last_write = now_s
        if tracker is not None:
            self.snapshot(tracker)
        now = self._now
        state = {
            "phase": self.phase, "speed": self.speed,
            "clock": _clock(now) if now is not None else None,
            "date": f"{now.tz_convert(LOCAL_TZ):%B} {now.tz_convert(LOCAL_TZ).day}" if now is not None else None,
            "stats": {"ships": len(self._ships) + len(self._ghosts), "silent": len(self._ghosts),
                      "silences": self._silence_total},
            "ships": self._ships, "ghosts": self._ghosts, "feed": list(self.feed),
            "alert": self.alert, "top": self.top, "static": self.static,
        }
        with self._lock:  # write to a temp file, then swap, so the page never reads half a file
            tmp = STATE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(state, f)
            try:
                os.replace(tmp, STATE_FILE)
            except PermissionError:
                pass  # Windows: the server is reading the old file right now; next write will land
