"""
make_map.py — draw the day's silences on a map (map.html) for the pitch.

It replays a recording instantly, then writes an HTML page (using the Leaflet
map library) showing:
  - the Cabrillo marine reserve (green) and the harbors (gray)
  - the receiver coverage edge the system LEARNED from the data (blue dashed)
  - every silence: gray dots = low risk, red circles = high risk
  - for the top ships: the last hour of track, and the projected course
    after it went silent (red dashed)

    python make_map.py            # then open map.html in a browser
"""

import argparse
import json
import os

import pandas as pd

from demo import DEMO_SESSION
from replay import load_session
from scoring import HARBORS, POINT_LOMA, RESERVE, clean_name, knowledge, score_event
from tracker import ShipTracker

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "map.html")
TOP_N = 5
TRACK_MIN = 60  # minutes of track to draw before each top silence


def build(tag):
    kb = knowledge()
    tracker = ShipTracker()
    history = {}   # mmsi -> [(time, lat, lon)]
    silences = []
    for msg in load_session(tag):
        if msg["type"] == "position":
            history.setdefault(msg["mmsi"], []).append((msg["time"], msg["lat"], msg["lon"]))
        for e in tracker.update(msg):
            if e["event"] == "silent":
                silences.append((e, score_event(e, kb)))

    # Top ships: each ship's best silence, highest risk first.
    best = {}
    for e, r in silences:
        if e["mmsi"] not in best or r["risk"] > best[e["mmsi"]][1]["risk"]:
            best[e["mmsi"]] = (e, r)
    top = sorted(best.values(), key=lambda x: -x[1]["risk"])[:TOP_N]
    top_keys = {(e["mmsi"], e["time"]) for e, _ in top}

    points = []
    for e, r in silences:
        points.append({
            "lat": e["lat"], "lon": e["lon"], "risk": r["risk"],
            "name": clean_name(r["facts"]["name"]) or str(e["mmsi"]),
            "top": (e["mmsi"], e["time"]) in top_keys,
            "time": e["time"].tz_convert("America/Los_Angeles").strftime("%b %d %I:%M %p"),
            "reasons": [f"{p:+d} {t}" for p, t in r["reasons"] if p],
        })

    tracks = []
    for e, r in top:
        start = e["last_seen"] - pd.Timedelta(minutes=TRACK_MIN)
        pts = [[la, lo] for t, la, lo in history[e["mmsi"]] if start <= t <= e["last_seen"]]
        proj = r["facts"]["projection"]
        tracks.append({
            "name": clean_name(r["facts"]["name"]) or str(e["mmsi"]),
            "risk": r["risk"], "track": pts,
            "projection": [[e["lat"], e["lon"]], list(proj["now"])] if proj else None,
        })

    return {"points": points, "tracks": tracks, "edge": kb.coverage_outline(),
            "reserve": [list(p) for p in RESERVE],
            "harbors": [[[s, w], [n, e]] for s, n, w, e in HARBORS.values()],
            "center": list(POINT_LOMA), "n_silences": len(silences), "tag": tag}


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dark Ship Map</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<style>
  :root { --bg:#f7f7f5; --panel:#ffffff; --ink:#1d1d1b; --muted:#6b6b66; --high:#c8102e; }
  @media (prefers-color-scheme: dark) { :root { --bg:#151514; --panel:#22221f; --ink:#ededea; --muted:#a3a39c; } }
  html, body { margin:0; height:100%; background:var(--bg); color:var(--ink);
               font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
  #map { position:absolute; inset:0; }
  .panel { position:absolute; z-index:1000; top:12px; left:12px; max-width:340px;
           background:var(--panel); padding:12px 14px; border-radius:10px;
           box-shadow:0 2px 12px rgba(0,0,0,.18); }
  .panel summary { cursor:pointer; font-size:15px; }
  .panel p { margin:6px 0 4px; color:var(--muted); }
  .leaflet-tooltip.ship { font-weight:600; }
  .key { display:flex; align-items:center; gap:8px; margin:3px 0; }
  .sw { width:14px; height:14px; border-radius:50%; flex:none; }
  @media (max-width: 600px) { .panel { left:8px; right:8px; max-width:none; font-size:13px; } }
</style></head><body>
<div id="map"></div>
<details class="panel" id="panel" open>
  <summary><b>Dark Ship Detector: one day off San Diego</b></summary>
  <p id="summary"></p>
  <div class="key"><span class="sw" style="background:#c8102e"></span>High-risk silence (top ships)</div>
  <div class="key"><span class="sw" style="background:#9a9a94"></span>Low-risk silence (filtered out)</div>
  <div class="key"><span class="sw" style="background:#2e8b57"></span>Cabrillo marine reserve</div>
  <div class="key"><span class="sw" style="border:2px dashed #2563eb"></span>Coverage edge learned from data</div>
  <div class="key"><span class="sw" style="border:2px dashed #c8102e"></span>Projected course after going silent</div>
</details>
<script>
const D = __DATA__;
document.getElementById("summary").textContent =
  D.n_silences + " silences in one recording. Gray ones were filtered out (docked, government, near the coverage edge). Click a dot for its reasons.";
if (innerWidth < 600) document.getElementById("panel").open = false;  // keep the map visible on phones
const map = L.map("map").setView([32.68, -117.33], innerWidth < 600 ? 10 : 11);
L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
  {maxZoom: 18, attribution: "&copy; OpenStreetMap contributors"}).addTo(map);
L.polygon(D.edge, {color:"#2563eb", weight:2, dashArray:"6 6", fill:false})
  .bindTooltip("Receiver coverage edge (95% of reports heard inside)").addTo(map);
D.harbors.forEach(b => L.rectangle(b, {color:"#888", weight:1, fillOpacity:0.06}).addTo(map));
L.polygon(D.reserve, {color:"#2e8b57", weight:2, fillOpacity:0.35})
  .bindTooltip("Cabrillo State Marine Reserve (no-take)").addTo(map);
D.tracks.forEach(t => {
  L.polyline(t.track, {color:"#c8102e", weight:2, opacity:0.6}).addTo(map);
  if (t.projection) L.polyline(t.projection, {color:"#c8102e", weight:2, dashArray:"4 6"}).addTo(map);
});
const esc = s => String(s).replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
D.points.sort((a, b) => a.top - b.top).forEach(p => {
  const high = p.top;
  const m = L.circleMarker([p.lat, p.lon], {
    radius: high ? 6 + p.risk / 10 : 4, color: high ? "#c8102e" : "#9a9a94",
    fillColor: high ? "#c8102e" : "#9a9a94", fillOpacity: high ? 0.7 : 0.5, weight: 1
  }).bindPopup("<b>" + esc(p.name) + "</b> - risk " + p.risk + "<br>" + esc(p.time) +
               "<br><small>" + p.reasons.map(esc).join("<br>") + "</small>")
    .addTo(map);
  if (high) m.bindTooltip(esc(p.name) + " " + p.risk, {permanent: true, direction: "right", className: "ship"});
});
</script></body></html>
"""


def main():
    parser = argparse.ArgumentParser(description="Write map.html of a recording's silences.")
    parser.add_argument("--session", default=DEMO_SESSION)
    args = parser.parse_args()
    data = build(args.session)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(PAGE.replace("__DATA__", json.dumps(data)))
    print(f"Wrote {OUT}  ({data['n_silences']} silences, top {len(data['tracks'])} ships drawn)")


if __name__ == "__main__":
    main()
