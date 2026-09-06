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


# to_field is the bearing from the aircraft to the airport. Hold it due north
# for every case, so an aircraft tracking 000 is flying at the field and one
# tracking 180 is flying away from it.
TO_FIELD = 0.0
TOWARD, AWAY = 0.0, 180.0


def phase(ac, dist=6.0):
    return apt._traffic_phase(ac, TO_FIELD, dist)[0]


check("on the ground", phase({"alt_baro": "ground"}), "ground")
check("descending toward the field is arriving",
      phase({"alt_baro": 3000, "baro_rate": -900, "track": TOWARD}), "arriving")
check("climbing away from the field is departing",
      phase({"alt_baro": 3000, "baro_rate": 1200, "track": AWAY}), "departing")
check("level is neither",
      phase({"alt_baro": 3000, "baro_rate": 0, "track": TOWARD}), "over")

# The error this rule exists for: Teterboro is 20 nm from Westchester, so
# without a direction test every jet climbing out of one was reported as
# departing the other. Climbing *at* the field is somebody else's departure.
check("climbing toward the field is not our departure",
      phase({"alt_baro": 3000, "baro_rate": 2000, "track": TOWARD}), "over")
check("descending away from the field is not our arrival",
      phase({"alt_baro": 3000, "baro_rate": -900, "track": AWAY}), "over")
check("crossing the area is neither",
      phase({"alt_baro": 3000, "baro_rate": -900, "track": 90.0}), "over")
check("no track means no claim",
      phase({"alt_baro": 3000, "baro_rate": -900}), "over")

# The cone: too high for how close, or too low for how far, is not ours.
check("too high for three miles out",
      phase({"alt_baro": 9000, "baro_rate": -900, "track": TOWARD}, 3.0), "over")
check("right height for three miles out",
      phase({"alt_baro": 2500, "baro_rate": -900, "track": TOWARD}, 3.0),
      "arriving")
# 400 ft at 22 nm is on somebody else's final, not ours.
check("too low for twenty-two miles out",
      phase({"alt_baro": 400, "baro_rate": -900, "track": TOWARD}, 22.0), "over")
check("beyond the cone nothing is claimed",
      phase({"alt_baro": 6000, "baro_rate": -900, "track": TOWARD}, 20.0), "over")

check("cruising is passing over",
      phase({"alt_baro": 35000, "baro_rate": 0, "track": TOWARD}), "over")
check("no altitude is not a guess",
      phase({"baro_rate": -900, "track": TOWARD}), "over")
# A drifting altimeter is not a descent.
check("a trickle is not a descent",
      phase({"alt_baro": 5000, "baro_rate": -60, "track": TOWARD}), "over")
check("geometric rate is used when barometric is missing",
      phase({"alt_baro": 3000, "geom_rate": -900, "track": TOWARD}), "arriving")
check("junk does not crash",
      phase({"alt_baro": "?", "baro_rate": "?", "track": "?"}), "over")

# Bearings, which the direction test rests on.
check("due north", round(apt.bearing_deg(40.0, -74.0, 41.0, -74.0)), 0)
check("due east", round(apt.bearing_deg(40.0, -74.0, 40.0, -73.0)), 90)
check("due south", round(apt.bearing_deg(41.0, -74.0, 40.0, -74.0)), 180)
check("due west", round(apt.bearing_deg(40.0, -73.0, 40.0, -74.0)), 270)

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
