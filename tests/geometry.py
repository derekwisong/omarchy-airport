#!/usr/bin/env python3
"""TFR distance maths, offline.

A TFR is one or more closed rings, and the case that matters most is the one a
bag-of-vertices distance gets wrong: a field inside the ring is nought miles
from the TFR, not the ring's radius away from it.
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
sys.argv = ["apt.py"]
import apt  # noqa: E402

failed = 0


def check(name, got, want, tol=0.15):
    global failed
    ok = (got is None and want is None) or (
        got is not None and want is not None and abs(got - want) <= tol)
    if not ok:
        failed += 1
        print("FAIL %s\n     wanted: %s\n     got:    %s" % (name, want, got))


# A one-degree square, so every expected distance is arithmetic.
SQUARE = [(40.0, -75.0), (40.0, -74.0), (41.0, -74.0), (41.0, -75.0)]
EAST_NM = 60.0 * math.cos(math.radians(40.5))

check("inside is zero", apt.tfr_distance_nm(40.5, -74.5, [SQUARE]), 0.0)
check("on the edge is zero", apt.tfr_distance_nm(40.0, -74.5, [SQUARE]), 0.0)
check("a degree of longitude east", apt.tfr_distance_nm(40.5, -73.0, [SQUARE]), EAST_NM)
check("a degree of latitude north", apt.tfr_distance_nm(42.0, -74.5, [SQUARE]), 60.0)
check("nearest edge, not nearest corner",
      apt.tfr_distance_nm(40.5, -75.5, [SQUARE]), EAST_NM / 2)
check("no geometry is unknown, not far", apt.tfr_distance_nm(40.0, -74.0, []), None)
check("two points are not a ring",
      apt.tfr_distance_nm(40.0, -74.0, [[(1, 2), (3, 4)]]), None)

# A VIP TFR is a 30 nm ring with a 10 nm ring inside it. Between the two is
# still inside the TFR, and the rings must not be flattened together.
OUTER = [(39.0, -76.0), (39.0, -73.0), (42.0, -73.0), (42.0, -76.0)]
check("inside the outer ring counts as inside",
      apt.tfr_distance_nm(39.5, -75.5, [OUTER, SQUARE]), 0.0)
check("outside every ring measures to the nearest",
      apt.tfr_distance_nm(38.0, -74.5, [OUTER, SQUARE]), 60.0)

# The detail file writes a hemisphere suffix rather than a sign.
rings = apt._tfr_rings(
    "<abdMergedArea>"
    "<Avx><geoLat>32.5N</geoLat><geoLong>083.75W</geoLong></Avx>"
    "<Avx><geoLat>32.5N</geoLat><geoLong>083.25W</geoLong></Avx>"
    "<Avx><geoLat>33.0N</geoLat><geoLong>083.25W</geoLong></Avx>"
    "</abdMergedArea>")
if len(rings) != 1 or rings[0][0] != (32.5, -83.75):
    failed += 1
    print("FAIL west longitude is negative\n     got:    %s" % (rings,))

if failed:
    sys.exit(1)
print("geometry ok")
