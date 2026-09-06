#!/usr/bin/env python3
"""Traffic phase and local time, offline.

Phase is a reading of altitude and vertical rate, not something ADS-B states,
so the reading is worth pinning. Local time is pinned against a fixed instant,
because the whole point of it is being right about an offset nobody can check
by eye.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.argv = ["apt.py"]
import apt  # noqa: E402

failed = 0


def check(name, got, want):
    global failed
    if got != want:
        failed += 1
        print("FAIL %s\n     wanted: %r\n     got:    %r" % (name, want, got))


phase = lambda ac: apt._traffic_phase(ac)[0]

check("on the ground", phase({"alt_baro": "ground"}), "ground")
check("descending low is arriving",
      phase({"alt_baro": 3000, "baro_rate": -900}), "arriving")
check("climbing low is departing",
      phase({"alt_baro": 3000, "baro_rate": 1200}), "departing")
check("level low is neither",
      phase({"alt_baro": 3000, "baro_rate": 0}), "over")
# A jet descending through the twenties is going somewhere else's runway.
check("descending high is passing over",
      phase({"alt_baro": 24000, "baro_rate": -1800}), "over")
check("cruising is passing over",
      phase({"alt_baro": 35000, "baro_rate": 0}), "over")
check("no altitude is not a guess",
      phase({"baro_rate": -900}), "over")
# A drifting altimeter is not a descent.
check("a trickle is not a descent",
      phase({"alt_baro": 5000, "baro_rate": -60}), "over")
check("geometric rate is used when barometric is missing",
      phase({"alt_baro": 3000, "geom_rate": -900}), "arriving")
check("junk does not crash", phase({"alt_baro": "?", "baro_rate": "?"}), "over")

# Local time against a fixed instant: 2026-09-05T22:12Z.
WHEN = datetime(2026, 9, 5, 22, 12, tzinfo=timezone.utc)


class Rec(dict):
    def __getitem__(self, k):
        return self.get(k)


def at(zone):
    saved = apt.airport_timezone
    apt.airport_timezone = lambda rec, offline=False: zone
    try:
        return apt.local_time(Rec(lat=1, lon=1, id="TEST"), now=WHEN)
    finally:
        apt.airport_timezone = saved


check("eastern daylight", at("America/New_York")["time"], "18:12")
check("eastern names itself", at("America/New_York")["abbrev"], "EDT")
# Arizona keeps standard time all year, which is the case a fixed offset or a
# nearest-city guess gets wrong.
check("arizona ignores daylight saving", at("America/Phoenix")["time"], "15:12")
check("arizona offset", at("America/Phoenix")["utc_offset"], "UTC-07:00")
check("across the date line", at("Pacific/Auckland")["date"], "Sun 06 Sep")
check("half-hour offset", at("Asia/Kolkata")["time"], "03:42")
check("unknown zone shows nothing", at("Mars/Olympus"), {})
check("no zone shows nothing", at(""), {})

if failed:
    sys.exit(1)
print("traffic and clock ok")
