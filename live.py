"""
live.py — Milestone 2: the same message stream, but from the live aisstream feed.

aisstream.io pushes ship reports to us over a *WebSocket*: a connection that
stays open so the server can send us messages whenever they happen (instead of
us asking over and over). We convert each one into the same dicts that
replay.py produces (see messages.py), so the rest of the program can't tell
live data from recorded data.

The `websockets` library is *async* (it uses Python's asyncio, a way to wait on
network traffic without freezing the program). To keep the rest of our code
plain and simple, we run the async part in a background *thread* (a second
line of execution running at the same time) and pass messages back through a
*queue* (a thread-safe line that one side puts things into and the other takes
out of). The result: `for msg in live(): ...` works exactly like replay().

Run it:
    python live.py              # print live messages until Ctrl+C
    python live.py --limit 20
"""

import argparse
import asyncio
import json
import os
import queue
import subprocess
import threading
import time
import zlib

import pandas as pd
from websockets.asyncio.client import connect

from messages import make_position, make_static

URL = "wss://stream.aisstream.io/v0/stream"
# [[south-west corner], [north-east corner]] as [lat, lon]: the waters off San Diego.
BOUNDING_BOX = [[32.3, -118.0], [33.3, -117.0]]

# Reconnect backoff: wait 1 s after the first drop, then 2, 4, 8 ... up to 60 s.
# "Backoff" = waiting longer after each failure so we don't hammer the server.
BACKOFF_START_S = 1
BACKOFF_MAX_S = 60
# The free feed sometimes goes quiet without closing. If nothing arrives for
# this long, assume the connection is dead and reconnect.
SILENT_TIMEOUT_S = 120


def get_api_key():
    """Read the AIS key from the environment, or from the saved Windows user variable."""
    key = os.environ.get("AISSTREAM_API_KEY")
    if key:
        return key
    if os.name == "nt":
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             '[Environment]::GetEnvironmentVariable("AISSTREAM_API_KEY","User")'],
            capture_output=True, text=True)
        key = out.stdout.strip()
    if not key:
        raise SystemExit("AISSTREAM_API_KEY is not set.")
    return key


def parse_time(time_utc):
    """'2026-10-11 23:38:05.87004921 +0000 UTC' -> pandas UTC timestamp.
    Trailing zeros get trimmed by the feed, so split on ' +' rather than slicing."""
    return pd.Timestamp(time_utc.split(" +")[0], tz="UTC")


def decode(raw):
    """Messages arrive as bytes: plain UTF-8 JSON, or sometimes gzip/zlib-compressed."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            raw = zlib.decompress(raw, wbits=47).decode("utf-8")  # 47 = auto-detect gzip/zlib
    return json.loads(raw)


def to_message(data):
    """Turn one aisstream JSON message into our message dict, or None to skip it."""
    kind = data.get("MessageType")
    meta = data.get("MetaData")
    if kind not in ("PositionReport", "ShipStaticData") or not meta:
        return None  # e.g. the SubscriptionConfirmation sent first
    t = parse_time(meta["time_utc"])
    body = data["Message"][kind]

    if kind == "PositionReport":
        lat, lon = body.get("Latitude"), body.get("Longitude")
        if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
            return None  # AIS uses lat 91 / lon 181 for "no position"
        return make_position(t, meta["MMSI"], meta.get("ShipName"), lat, lon,
                             body.get("Sog"), body.get("Cog"), body.get("TrueHeading"),
                             body.get("NavigationalStatus"))

    # ShipStaticData: size is given as distances from the GPS antenna to the
    # bow (A), stern (B), port side (C) and starboard side (D).
    dim = body.get("Dimension") or {}
    return make_static(t, meta["MMSI"], body.get("Name") or meta.get("ShipName"),
                       body.get("Type"),
                       dim.get("A", 0) + dim.get("B", 0),
                       dim.get("C", 0) + dim.get("D", 0),
                       body.get("MaximumStaticDraught"), body.get("Destination"),
                       body.get("CallSign"), body.get("ImoNumber"))


async def _stream_forever(api_key, out_queue):
    """Connect, subscribe, push messages into out_queue; reconnect whenever it drops."""
    subscription = json.dumps({
        "APIKey": api_key,
        "BoundingBoxes": [BOUNDING_BOX],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    })
    backoff = BACKOFF_START_S
    while True:
        received = 0
        try:
            async with connect(URL) as ws:
                await ws.send(subscription)  # must be sent within 3 s of connecting
                print("[live] connected to aisstream")
                while True:
                    raw = await asyncio.wait_for(ws.recv(), timeout=SILENT_TIMEOUT_S)
                    msg = to_message(decode(raw))
                    received += 1
                    backoff = BACKOFF_START_S  # healthy again: reset the backoff
                    if msg is not None:
                        out_queue.put(msg)
        except asyncio.TimeoutError:
            print(f"[live] no data for {SILENT_TIMEOUT_S}s, reconnecting")
        except Exception as e:  # dropped connection, network error, bad message...
            print(f"[live] connection lost ({type(e).__name__}: {e})")
        if received == 0:
            # The server rejects a bad API key by just closing the connection.
            print("[live] server closed before sending anything: check AISSTREAM_API_KEY")
        print(f"[live] reconnecting in {backoff}s")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, BACKOFF_MAX_S)


def live():
    """
    Yield live messages forever, one at a time, just like replay() does.
    The WebSocket runs in a background thread; we just read from the queue.
    """
    api_key = get_api_key()
    q = queue.Queue()
    # daemon=True: the thread dies automatically when the main program exits.
    threading.Thread(target=lambda: asyncio.run(_stream_forever(api_key, q)),
                     daemon=True).start()
    while True:
        try:
            # A short timeout keeps Ctrl+C working on Windows while we wait.
            yield q.get(timeout=1)
        except queue.Empty:
            continue


def main():
    from replay import format_message

    parser = argparse.ArgumentParser(description="Stream live AIS data from aisstream.io.")
    parser.add_argument("--limit", type=int, default=None, help="stop after N messages")
    args = parser.parse_args()

    print("Streaming live AIS off San Diego  (Ctrl+C to stop)")
    count = 0
    start = time.time()
    try:
        for msg in live():
            print(format_message(msg))
            count += 1
            if args.limit and count >= args.limit:
                break
    except KeyboardInterrupt:
        pass
    print(f"Done: {count} messages in {time.time() - start:.0f}s.")


if __name__ == "__main__":
    main()
