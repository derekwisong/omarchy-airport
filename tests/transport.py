#!/usr/bin/env python3
"""Ways out of an airport: which kind a mapped object is, and which line it is.

Offline. The classification rules are argued with here rather than by staring
at Overpass output for a hub that is mapped differently next month.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import apt  # noqa: E402

fail = 0


def check(name, got, want):
    global fail
    if got == want:
        return
    fail += 1
    print("FAIL %s\n     wanted: %r\n     got:    %r" % (name, want, got))


def poi(**kw):
    row = {"amenity": "", "railway": "", "station": "", "network": "",
           "name": "", "on_field": True}
    row.update(kw)
    return row


kind = apt._transport_kind

# The city's railway, at the airport: rail, whatever else is on the field.
check("a subway station is rail",
      kind(poi(railway="station", station="subway", network="MARTA",
               name="Airport")), "rail")
check("a commuter station is rail",
      kind(poi(railway="station", network="Metra", name="O'Hare Transfer")), "rail")

# The airport's own train, by network name, on the field or just off it.
check("an airtrain is a people mover",
      kind(poi(railway="station", station="light_rail", network="AirTrain JFK",
               name="Terminal 4")), "people_mover")
check("a skytrain outside the fence is still the airport's",
      kind(poi(railway="station", station="monorail", network="ATL SkyTrain",
               name="Airport", on_field=False)), "people_mover")
# ...and by the only other thing that distinguishes it: what it is named for.
check("a stop named for a concourse is a people mover",
      kind(poi(railway="halt", station="monorail", name="A Gates")), "people_mover")
check("an unnetworked stop on the field is a people mover",
      kind(poi(railway="station", name="Jeppesen Terminal")), "people_mover")
# A station off the field with no network is nobody's shuttle - do not claim it.
check("an unnetworked stop off the field is only rail",
      kind(poi(railway="station", name="Somewhere", on_field=False)), "rail")

check("a station entrance is not a second station",
      kind(poi(railway="subway_entrance", name="Exit 2")), "")
check("a taxi rank is a taxi rank",
      kind(poi(amenity="taxi", name="Terminal 4 Pick-Up A")), "taxi")
check("car rental is car rental", kind(poi(amenity="car_rental", name="Hertz")),
      "car_rental")
check("a ferry terminal is a ferry",
      kind(poi(amenity="ferry_terminal", name="Logan Airport Ferry Terminal")),
      "ferry")
check("a bike dock is not a train",
      kind(poi(amenity="bicycle_rental", name="Bluebikes")), "bike")
check("a restaurant is not a way out",
      kind(poi(amenity="restaurant", name="Asian Chao")), "")

# Staff shuttles and staging lots are mapped, and are not for passengers.
check("an employee shuttle is not offered",
      kind(poi(amenity="bus_station", name="B Concourse Shuttle - Employees only")),
      "")
check("a rideshare staging lot is not a pickup point",
      kind(poi(amenity="parking", name="TNC Staging Lot")), "")

# One row per line, not one per direction, and the shuttle is not a line.
routes = [
    {"name": "RTD A Line: Union Station → Denver Airport", "kind": "train",
     "network": "RTD", "operator": "", "between": "Union Station → Denver Airport"},
    {"name": "RTD A Line: Denver Airport → Union Station", "kind": "train",
     "network": "RTD", "operator": "", "between": "Denver Airport → Union Station"},
    {"name": "Denver International Airport Automated Guideway Transit System",
     "kind": "monorail", "network": "DEN", "operator": "", "between": ""},
]
lines = apt.route_lines(routes)
check("both directions are one line", len(lines), 1)
check("the line keeps its name", lines[0]["name"], "RTD A Line")
check("the line says where it runs", lines[0]["between"],
      "Denver Airport ↔ Union Station")

# Rail before bus, because that is the order they are wanted in.
mixed = apt.route_lines([
    {"name": "Route 5", "kind": "bus", "network": "X", "operator": "", "between": ""},
    {"name": "Blue Line", "kind": "subway", "network": "X", "operator": "", "between": ""},
])
check("rail is listed before bus", [r["name"] for r in mixed],
      ["Blue Line", "Route 5"])

# Distance is measured from the terminal a passenger is standing in, not from
# the middle of a field that can be four kilometres across.
terminals = [{"name": "Jeppesen Terminal",
              "ring": [(-104.673, 39.856), (-104.671, 39.856),
                       (-104.671, 39.858), (-104.673, 39.858)]}]
rows = apt.transport_rows(
    [poi(amenity="car_rental", name="Hertz", lat=39.8905, lon=-104.6737)],
    [], terminals, (39.8617, -104.6732))
check("distance is from the terminal",
      3500 < rows["car_rental"][0]["distance_m"] < 3900, True)
check("and says which terminal it was measured from",
      rows["car_rental"][0]["from_terminal"], "Jeppesen Terminal")

# A people mover is one train, and its stops belong in the order it calls at
# them - rebuilt from loose points, because that is how they are mapped.
def stop(name, lat, lon):
    return {"name": name, "lat": lat, "lon": lon, "railway": "station",
            "network": "", "station": "monorail", "on_field": True,
            "amenity": "", "distance_m": 0}


line = [stop("C Gates", 33.6405, -84.4290), stop("A Gates", 33.6405, -84.4340),
        stop("Domestic Terminal", 33.6405, -84.4380), stop("T Gates", 33.6405, -84.4360),
        stop("B Gates", 33.6405, -84.4315)]
check("the train calls at its stops in order",
      apt._chain_stops(line),
      ["Domestic Terminal", "T Gates", "A Gates", "B Gates", "C Gates"])
# With no stop named for a terminal, start at an end of the line, not the middle.
check("an unnamed line still starts at an end",
      apt._chain_stops([stop("North", 33.70, -84.43), stop("Middle", 33.66, -84.43),
                        stop("South", 33.62, -84.43)])[0] in ("North", "South"), True)

# The wiki asks for amenity=car_rental; the map answers in three other tags,
# and at a small field the rental cars are a parking area named for them.
check("shop=car_rental is car rental",
      kind(poi(amenity="", name="Hertz", **{"shop": "car_rental"})), "car_rental")
check("office=car_rental is car rental",
      kind(poi(amenity="", name="Avis", **{"office": "car_rental"})), "car_rental")
check("a lot named for the rental cars is car rental",
      kind(poi(amenity="parking", name="Rental Car Lot")), "car_rental")
check("an ordinary car park is not",
      kind(poi(amenity="parking", name="Long Term Parking")), "")

systems = [{"name": "ATL SkyTrain", "between": "Airport ↔ Rental Car Center"}]
summary = apt.rental_summary(
    [{"name": "Hertz", "brand": "", "distance_m": 2500},
     {"name": "Avis - ATL", "brand": "", "distance_m": 2600},
     {"name": "Hertz", "brand": "", "distance_m": 2700}], systems)
check("desks are counted, not listed twice", summary["count"], 3)
check("brands are deduplicated and trimmed", summary["brands"], ["Hertz", "Avis"])
check("the rental centre is named", summary["centre"], "Rental Car Center")
# A desk whose operator nobody has mapped is still a desk, and is not a brand.
anon = apt.rental_summary([{"name": "(unnamed)", "brand": "", "distance_m": 120}], [])
check("an unnamed desk counts", anon["count"], 1)
check("but is not listed as a brand", anon["brands"], [])
check("and does not pretend to be a list", anon["brands_worth_listing"], False)
check("and how you get to it", summary["via"], "ATL SkyTrain")


# --- which railway is whose -------------------------------------------------
# The rule that matters most: a network running a service that ends somewhere
# other than this airport is the city's, however airport-shaped its stations
# are named. DART calls its DFW station "DFW Airport Terminal A" and it is
# still the city's railway.
class Rec(dict):
    def __getitem__(self, key):
        return self.get(key)


field = Rec(name="DALLAS/FORT WORTH INTL", id="DFW", icao="KDFW", city="DALLAS")

city_line = {"name": "DART Orange Line: Parker Road => DFW Airport", "kind": "light_rail",
             "network": "DART", "between": "Parker Road → DFW Airport", "operator": ""}
mover_line = {"name": "Skylink: Terminal A => Terminal D", "kind": "monorail",
              "network": "Skylink", "between": "Terminal A → Terminal D", "operator": ""}
ctx = apt.network_context([city_line, mover_line], field)
check("a line that leaves belongs to the city", "DART" in ctx["city_networks"], True)
check("a line that never leaves is the airport's",
      "Skylink" in ctx["own_networks"], True)
check("a city station named for a terminal is still city rail",
      apt._transport_kind(poi(railway="station", station="light_rail",
                              network="DART", name="DFW Airport Terminal A"), ctx),
      "rail")
check("the airport's own train is a people mover",
      apt._transport_kind(poi(railway="station", station="monorail",
                              network="Skylink", name="Terminal A"), ctx),
      "people_mover")
# The airport carries its city's name, and so does the city's transit agency.
bwi = Rec(name="BALTIMORE/WASHINGTON INTL THURGOOD MARSHALL", id="BWI", icao="KBWI",
          city="BALTIMORE")
light_rail = {"name": "Baltimore Light RailLink: BWI Airport to Hunt Valley",
              "kind": "light_rail", "network": "Baltimore Light RailLink",
              "between": "BWI Airport → Hunt Valley", "operator": ""}
ctx2 = apt.network_context([light_rail], bwi)
check("sharing the city's name does not make it the airport's",
      "Baltimore Light RailLink" in ctx2["city_networks"], True)
# Loosely spelled networks are one system.
check("station and route spellings are matched loosely",
      apt._network_in("Orlando International Airport",
                      {"Orlando International Airport People Movers"}), True)

# --- which station is this airport's ---------------------------------------
def station(name, metres, network=""):
    return {"name": name, "network": network, "railway": "station",
            "distance_m": metres, "lat": 0.0, "lon": 0.0}


near = station("BWI Airport", 220, "Baltimore Light RailLink")
far = station("BWI Business District", 1119, "Baltimore Light RailLink")
further = station("Ferndale", 2105, "Baltimore Light RailLink")
amtrak = station("BWI Thurgood Marshall Airport", 2391, "Amtrak;MARC")
pois = [near, far, further, amtrak]
check("the airport's own station is kept",
      apt._serves_this_field(near, pois, bwi), True)
check("the next stop down the line is not",
      apt._serves_this_field(far, pois, bwi), False)
check("nor the one after that",
      apt._serves_this_field(further, pois, bwi), False)
check("a station a mile out that names the airport is kept",
      apt._serves_this_field(amtrak, pois, bwi), True)
lax = Rec(name="LOS ANGELES INTL", id="LAX", icao="KLAX", city="LOS ANGELES")
check("the airport's code plus a transit word keeps it",
      apt._serves_this_field(station("LAX/Metro Transit Center", 1674, "Metro Rail"),
                             [], lax), True)

# --- semicolons are for databases ------------------------------------------
check("two networks on one platform read as two",
      apt.tag_list("Amtrak;MARC"), "Amtrak and MARC")
check("three read as a list", apt.tag_list("A;B;C"), "A, B and C")
check("one is left alone", apt.tag_list("MARTA"), "MARTA")
check("none is nothing", apt.tag_list(""), "")

# --- a rental centre is a place, not a brand -------------------------------
for name, want in [("Rental Car Center", True), ("Rental Car Lot", True),
                   ("Consolidated Rental Car Facility", True),
                   ("Dollar Car Rental", False), ("Thrifty car rentals", False),
                   ("National/Alamo/Enterprise Car Rental", False)]:
    check("rental centre: %s" % name, bool(apt.RENTAL_CENTRE.search(name)), want)

if fail:
    sys.exit(1)
print("ground transport ok")
