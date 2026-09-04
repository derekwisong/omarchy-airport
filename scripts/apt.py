#!/usr/bin/env python3
"""
apt.py - airport data CLI for the airport-info Claude Code plugin.

Standard library only. Data comes from:
  FAA NASR 28-day subscription   airport / runway / frequency records
  FAA d-TPP                      airport diagrams and approach plates
  FAA Chart Supplement           per-airport CS page
  aviationweather.gov            METAR / TAF
  tfr.faa.gov                    active TFRs
  OurAirports                    worldwide fallback
  OpenStreetMap (Overpass)       terminal / concourse polygons and amenities

NOT FOR NAVIGATION. Verify against official sources and current NOTAMs.
"""

import argparse
import csv
import io
import json
import math
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

VERSION = "1.0.0"
UA = "airport-info-plugin/%s (Claude Code plugin; contact: local user)" % VERSION

CACHE_DIR = Path(os.environ.get("AIRPORT_INFO_CACHE") or (Path.home() / ".cache" / "airport-info"))
NOTES_DIR = Path(os.environ.get("AIRPORT_INFO_NOTES") or (Path.home() / ".airport-info" / "notes"))
DB_PATH = CACHE_DIR / "airports.db"
OSM_DIR = CACHE_DIR / "osm"

AERONAV = "https://aeronav.faa.gov"
NFDC_EXTRA = "https://nfdc.faa.gov/webContent/28DaySub/extra"
AWC = "https://aviationweather.gov/api/data"
TFR_LIST_URL = "https://tfr.faa.gov/tfrapi/exportTfrList"
TFR_DETAIL_URL = "https://tfr.faa.gov/save_pages/detail_%s.xml"
OURAIRPORTS = "https://davidmegginson.github.io/ourairports-data"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
SUNRISE_URL = "https://api.sunrise-sunset.org/json"

# NASR subscriptions step 28 days from this verified effective date.
NASR_ANCHOR = date(2026, 9, 3)
OSM_TTL_DAYS = 7

FT_PER_NM = 6076.115
NM_PER_DEG = 60.0


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

class Http:
    """Small retrying HTTP client. Overpass and the FAA both throttle."""

    @staticmethod
    def get(url, data=None, timeout=90, retries=3, backoff=3.0, binary=False, headers=None):
        hdrs = {"User-Agent": UA}
        if headers:
            hdrs.update(headers)
        last = None
        for attempt in range(retries):
            try:
                req = urllib.request.Request(url, data=data, headers=hdrs)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                return raw if binary else raw.decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                last = exc
                if exc.code in (403, 408, 429, 500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(backoff * (attempt + 1))
                    continue
                raise
            except Exception as exc:  # timeouts, DNS, resets
                last = exc
                if attempt < retries - 1:
                    time.sleep(backoff * (attempt + 1))
                    continue
                raise
        raise last

    @staticmethod
    def json(url, **kw):
        text = Http.get(url, **kw)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            raise RuntimeError("expected JSON from %s, got %r" % (url, text[:200]))

    @staticmethod
    def peek(url, n=1024, timeout=30):
        """Read only the first n bytes. Used to read cycle headers off huge XML."""
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read(n).decode("utf-8", "replace")

    @staticmethod
    def exists(url, timeout=30):
        """Probe with a ranged GET - nfdc.faa.gov answers HEAD with 503."""
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Range": "bytes=0-63"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False


def log(msg):
    print(msg, file=sys.stderr)


# --------------------------------------------------------------------------
# Cycle discovery
# --------------------------------------------------------------------------

def nasr_cycle_date(today=None):
    """Current NASR 28-day effective date, verified against the live server."""
    today = today or date.today()
    steps = (today - NASR_ANCHOR).days // 28
    candidate = NASR_ANCHOR + timedelta(days=28 * steps)
    for back in range(3):
        d = candidate - timedelta(days=28 * back)
        if Http.exists("%s/%s_APT_CSV.zip" % (NFDC_EXTRA, nasr_stamp(d))):
            return d
    raise RuntimeError("could not find a published NASR cycle near %s" % candidate)


def nasr_stamp(d):
    return "%02d_%s_%d" % (d.day, d.strftime("%b"), d.year)


def _dir_links(url, pattern):
    html = Http.get(url, timeout=60)
    return sorted(set(m.upper() for m in re.findall(pattern, html, re.I)))


def _parse_edate(text):
    """'0901Z  09/03/26' -> date(2026, 9, 3)"""
    m = re.search(r"(\d{2})/(\d{2})/(\d{2})", text)
    if not m:
        return None
    mm, dd, yy = (int(x) for x in m.groups())
    return date(2000 + yy, mm, dd)


def dtpp_cycle(today=None):
    """Newest d-TPP cycle whose metafile is published and already effective."""
    today = today or date.today()
    cycles = _dir_links(AERONAV + "/d-tpp/", r'href="/d-tpp/(\d{4})/"')
    for cycle in sorted(cycles, reverse=True):
        url = "%s/d-tpp/%s/xml_data/d-TPP_Metafile.xml" % (AERONAV, cycle)
        try:
            head = Http.peek(url)
        except Exception:
            continue
        if "digital_tpp" not in head:
            continue
        m = re.search(r'from_edate="([^"]+)"', head)
        start = _parse_edate(m.group(1)) if m else None
        if start and start <= today:
            return cycle, start
    raise RuntimeError("no effective d-TPP cycle found")


def cs_cycle(today=None):
    """Newest already-effective Chart Supplement edition directory, e.g. 03SEP2026."""
    today = today or date.today()
    dirs = _dir_links(AERONAV + "/afd/", r'href="/afd/(\d{2}[A-Z]{3}\d{4})/"')
    dated = []
    for name in dirs:
        try:
            dated.append((datetime.strptime(name, "%d%b%Y").date(), name))
        except ValueError:
            continue
    effective = [x for x in sorted(dated, reverse=True) if x[0] <= today]
    if not effective:
        raise RuntimeError("no effective Chart Supplement edition found")
    return effective[0][1], effective[0][0]


# --------------------------------------------------------------------------
# Database
# --------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);

CREATE TABLE IF NOT EXISTS apt (
  arpt_id TEXT, icao_id TEXT, site_no TEXT, name TEXT, city TEXT, state TEXT,
  state_name TEXT, county TEXT, lat REAL, lon REAL, elev REAL, site_type TEXT,
  rank INTEGER DEFAULT 0, data TEXT);
CREATE INDEX IF NOT EXISTS apt_rank_ix ON apt(rank DESC);
CREATE INDEX IF NOT EXISTS apt_id_ix ON apt(arpt_id);
CREATE INDEX IF NOT EXISTS apt_icao_ix ON apt(icao_id);
CREATE INDEX IF NOT EXISTS apt_name_ix ON apt(name);
CREATE INDEX IF NOT EXISTS apt_city_ix ON apt(city);

CREATE TABLE IF NOT EXISTS rwy (arpt_id TEXT, rwy_id TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS rwy_ix ON rwy(arpt_id);

CREATE TABLE IF NOT EXISTS rwy_end (arpt_id TEXT, rwy_id TEXT, end_id TEXT, data TEXT);
CREATE INDEX IF NOT EXISTS rwy_end_ix ON rwy_end(arpt_id);

CREATE TABLE IF NOT EXISTS rmk (arpt_id TEXT, element TEXT, ref_col TEXT, remark TEXT);
CREATE INDEX IF NOT EXISTS rmk_ix ON rmk(arpt_id);

CREATE TABLE IF NOT EXISTS airspace (
  arpt_id TEXT, class_b TEXT, class_c TEXT, class_d TEXT, class_e TEXT,
  hours TEXT, remark TEXT);
CREATE INDEX IF NOT EXISTS airspace_ix ON airspace(arpt_id);

CREATE TABLE IF NOT EXISTS att (arpt_id TEXT, month TEXT, day TEXT, hour TEXT);
CREATE INDEX IF NOT EXISTS att_ix ON att(arpt_id);

CREATE TABLE IF NOT EXISTS con (arpt_id TEXT, title TEXT, name TEXT, phone TEXT, addr TEXT);
CREATE INDEX IF NOT EXISTS con_ix ON con(arpt_id);

CREATE TABLE IF NOT EXISTS frq (
  arpt_id TEXT, facility TEXT, fac_name TEXT, fac_type TEXT, freq TEXT,
  freq_use TEXT, twr_hrs TEXT, remark TEXT);
CREATE INDEX IF NOT EXISTS frq_ix ON frq(arpt_id);

CREATE TABLE IF NOT EXISTS chart (
  arpt_id TEXT, icao_id TEXT, code TEXT, name TEXT, pdf TEXT, seq TEXT);
CREATE INDEX IF NOT EXISTS chart_ix ON chart(arpt_id);
CREATE INDEX IF NOT EXISTS chart_icao_ix ON chart(icao_id);

CREATE TABLE IF NOT EXISTS cs (arpt_id TEXT, name TEXT, city TEXT, pdf TEXT);
CREATE INDEX IF NOT EXISTS cs_ix ON cs(arpt_id);

CREATE TABLE IF NOT EXISTS oa_apt (
  ident TEXT, type TEXT, name TEXT, lat REAL, lon REAL, elev REAL,
  country TEXT, region TEXT, municipality TEXT, icao TEXT, iata TEXT,
  local_code TEXT, wikipedia TEXT);
CREATE INDEX IF NOT EXISTS oa_ident_ix ON oa_apt(ident);
CREATE INDEX IF NOT EXISTS oa_icao_ix ON oa_apt(icao);
CREATE INDEX IF NOT EXISTS oa_iata_ix ON oa_apt(iata);

CREATE TABLE IF NOT EXISTS oa_rwy (
  ident TEXT, length_ft TEXT, width_ft TEXT, surface TEXT, lighted TEXT,
  closed TEXT, le_ident TEXT, he_ident TEXT, le_lat TEXT, le_lon TEXT,
  he_lat TEXT, he_lon TEXT);
CREATE INDEX IF NOT EXISTS oa_rwy_ix ON oa_rwy(ident);
"""


def db_connect(readonly=True):
    if readonly and not DB_PATH.exists():
        die("no cache yet - run:  apt.py cache update")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def meta_get(conn, key, default=None):
    row = conn.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default


def meta_set(conn, key, value):
    conn.execute("INSERT OR REPLACE INTO meta (k, v) VALUES (?, ?)", (key, str(value)))


def die(msg, code=1):
    print("error: " + msg, file=sys.stderr)
    sys.exit(code)


# --------------------------------------------------------------------------
# Cache building
# --------------------------------------------------------------------------

def _read_csv_from_zip(zf, filename):
    with zf.open(filename) as fh:
        text = io.TextIOWrapper(fh, encoding="utf-8", errors="replace")
        for row in csv.DictReader(text):
            yield row


def _fnum(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_nasr(conn, cycle_date):
    stamp = nasr_stamp(cycle_date)
    log("  downloading NASR %s airport records..." % stamp)
    apt_zip = Http.get("%s/%s_APT_CSV.zip" % (NFDC_EXTRA, stamp), binary=True, timeout=300)
    log("  downloading NASR %s frequencies..." % stamp)
    frq_zip = Http.get("%s/%s_FRQ_CSV.zip" % (NFDC_EXTRA, stamp), binary=True, timeout=300)

    for table in ("apt", "rwy", "rwy_end", "rmk", "con", "frq", "att", "airspace"):
        conn.execute("DELETE FROM %s" % table)

    counts = {}
    with zipfile.ZipFile(io.BytesIO(apt_zip)) as zf:
        names = {n.upper(): n for n in zf.namelist()}

        rows = []
        for r in _read_csv_from_zip(zf, names["APT_BASE.CSV"]):
            rows.append((
                r.get("ARPT_ID", ""), r.get("ICAO_ID", ""), r.get("SITE_NO", ""),
                r.get("ARPT_NAME", ""), r.get("CITY", ""), r.get("STATE_CODE", ""),
                r.get("STATE_NAME", ""), r.get("COUNTY_NAME", ""),
                _fnum(r.get("LAT_DECIMAL")), _fnum(r.get("LONG_DECIMAL")),
                _fnum(r.get("ELEV")), r.get("SITE_TYPE_CODE", ""),
                json.dumps({k: v for k, v in r.items() if v}),
            ))
        conn.executemany("INSERT INTO apt VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?)", rows)
        counts["airports"] = len(rows)

        rows = [(r.get("ARPT_ID", ""), r.get("RWY_ID", ""),
                 json.dumps({k: v for k, v in r.items() if v}))
                for r in _read_csv_from_zip(zf, names["APT_RWY.CSV"])]
        conn.executemany("INSERT INTO rwy VALUES (?,?,?)", rows)
        counts["runways"] = len(rows)

        rows = [(r.get("ARPT_ID", ""), r.get("RWY_ID", ""), r.get("RWY_END_ID", ""),
                 json.dumps({k: v for k, v in r.items() if v}))
                for r in _read_csv_from_zip(zf, names["APT_RWY_END.CSV"])]
        conn.executemany("INSERT INTO rwy_end VALUES (?,?,?,?)", rows)
        counts["runway_ends"] = len(rows)

        rows = [(r.get("ARPT_ID", ""), r.get("ELEMENT", ""), r.get("REF_COL_NAME", ""),
                 r.get("REMARK", ""))
                for r in _read_csv_from_zip(zf, names["APT_RMK.CSV"])]
        conn.executemany("INSERT INTO rmk VALUES (?,?,?,?)", rows)
        counts["remarks"] = len(rows)

        rows = [(r.get("ARPT_ID", ""), r.get("MONTH", ""), r.get("DAY", ""),
                 r.get("HOUR", ""))
                for r in _read_csv_from_zip(zf, names["APT_ATT.CSV"])]
        conn.executemany("INSERT INTO att VALUES (?,?,?,?)", rows)
        counts["attendance"] = len(rows)

        rows = []
        for r in _read_csv_from_zip(zf, names["APT_CON.CSV"]):
            addr = " ".join(x for x in (r.get("ADDRESS1"), r.get("TITLE_CITY"),
                                        r.get("STATE"), r.get("ZIP_CODE")) if x)
            rows.append((r.get("ARPT_ID", ""), r.get("TITLE", ""), r.get("NAME", ""),
                         r.get("PHONE_NO", ""), addr))
        conn.executemany("INSERT INTO con VALUES (?,?,?,?,?)", rows)
        counts["contacts"] = len(rows)

    log("  downloading NASR %s class airspace..." % stamp)
    cls_zip = Http.get("%s/%s_CLS_ARSP_CSV.zip" % (NFDC_EXTRA, stamp), binary=True, timeout=300)
    with zipfile.ZipFile(io.BytesIO(cls_zip)) as zf:
        names = {n.upper(): n for n in zf.namelist()}
        rows = [(r.get("ARPT_ID", ""), r.get("CLASS_B_AIRSPACE", ""),
                 r.get("CLASS_C_AIRSPACE", ""), r.get("CLASS_D_AIRSPACE", ""),
                 r.get("CLASS_E_AIRSPACE", ""), r.get("AIRSPACE_HRS", ""),
                 r.get("REMARK", ""))
                for r in _read_csv_from_zip(zf, names["CLS_ARSP.CSV"])]
        conn.executemany("INSERT INTO airspace VALUES (?,?,?,?,?,?,?)", rows)
        counts["class_airspace"] = len(rows)

    with zipfile.ZipFile(io.BytesIO(frq_zip)) as zf:
        names = {n.upper(): n for n in zf.namelist()}
        rows = [(r.get("SERVICED_FACILITY", ""), r.get("FACILITY", ""),
                 r.get("FAC_NAME", ""), r.get("FACILITY_TYPE", ""), r.get("FREQ", ""),
                 r.get("FREQ_USE", ""), r.get("TOWER_HRS", ""), r.get("REMARK", ""))
                for r in _read_csv_from_zip(zf, names["FRQ.CSV"])]
        conn.executemany("INSERT INTO frq VALUES (?,?,?,?,?,?,?,?)", rows)
        counts["frequencies"] = len(rows)

    meta_set(conn, "nasr_cycle", cycle_date.isoformat())
    return counts


def build_dtpp(conn):
    cycle, effective = dtpp_cycle()
    log("  downloading d-TPP cycle %s (effective %s)..." % (cycle, effective))
    xml = Http.get("%s/d-tpp/%s/xml_data/d-TPP_Metafile.xml" % (AERONAV, cycle), timeout=300)
    root = ET.fromstring(xml)
    conn.execute("DELETE FROM chart")
    rows = []
    for state in root:
        for city in state:
            for apt in city:
                fid = apt.get("apt_ident") or ""
                icao = apt.get("icao_ident") or ""
                for rec in apt:
                    rows.append((fid, icao, rec.findtext("chart_code") or "",
                                 rec.findtext("chart_name") or "",
                                 rec.findtext("pdf_name") or "",
                                 rec.findtext("chartseq") or ""))
    conn.executemany("INSERT INTO chart VALUES (?,?,?,?,?,?)", rows)
    meta_set(conn, "dtpp_cycle", cycle)
    meta_set(conn, "dtpp_effective", effective.isoformat())
    return {"charts": len(rows)}


def build_cs(conn):
    edition, effective = cs_cycle()
    log("  downloading Chart Supplement index %s..." % edition)
    xml = Http.get("%s/afd/%s/afd_%s.xml" % (AERONAV, edition, edition), timeout=180)
    root = ET.fromstring(xml)
    conn.execute("DELETE FROM cs")
    rows = []
    for location in root:
        for apt in location.findall("airport"):
            fid = (apt.findtext("aptid") or "").strip()
            if not fid:
                continue
            pdfs = [p.text for p in apt.iter("pdf") if p.text]
            if pdfs:
                rows.append((fid, (apt.findtext("aptname") or "").strip(),
                             (apt.findtext("aptcity") or "").strip(), pdfs[0]))
    conn.executemany("INSERT INTO cs VALUES (?,?,?,?)", rows)
    meta_set(conn, "cs_edition", edition)
    meta_set(conn, "cs_effective", effective.isoformat())
    return {"chart_supplement_pages": len(rows)}


def build_ourairports(conn):
    log("  downloading OurAirports worldwide data...")
    airports = Http.get(OURAIRPORTS + "/airports.csv", timeout=180)
    runways = Http.get(OURAIRPORTS + "/runways.csv", timeout=180)
    conn.execute("DELETE FROM oa_apt")
    conn.execute("DELETE FROM oa_rwy")

    rows = [(r.get("ident", ""), r.get("type", ""), r.get("name", ""),
             _fnum(r.get("latitude_deg")), _fnum(r.get("longitude_deg")),
             _fnum(r.get("elevation_ft")), r.get("iso_country", ""),
             r.get("iso_region", ""), r.get("municipality", ""),
             r.get("icao_code", ""), r.get("iata_code", ""),
             r.get("local_code", ""), r.get("wikipedia_link", ""))
            for r in csv.DictReader(io.StringIO(airports))]
    conn.executemany("INSERT INTO oa_apt VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    count = {"world_airports": len(rows)}

    rows = [(r.get("airport_ident", ""), r.get("length_ft", ""), r.get("width_ft", ""),
             r.get("surface", ""), r.get("lighted", ""), r.get("closed", ""),
             r.get("le_ident", ""), r.get("he_ident", ""),
             r.get("le_latitude_deg", ""), r.get("le_longitude_deg", ""),
             r.get("he_latitude_deg", ""), r.get("he_longitude_deg", ""))
            for r in csv.DictReader(io.StringIO(runways))]
    conn.executemany("INSERT INTO oa_rwy VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    count["world_runways"] = len(rows)
    return count


def cmd_cache(args):
    if args.action == "status":
        if not DB_PATH.exists():
            print("cache: not built. run:  apt.py cache update")
            return
        conn = db_connect()
        print("cache:            %s" % DB_PATH)
        print("NASR cycle:       %s" % meta_get(conn, "nasr_cycle", "?"))
        print("d-TPP cycle:      %s (effective %s)" % (meta_get(conn, "dtpp_cycle", "?"),
                                                       meta_get(conn, "dtpp_effective", "?")))
        print("Chart Supplement: %s" % meta_get(conn, "cs_edition", "?"))
        print("built:            %s" % meta_get(conn, "built_at", "?"))
        for table, label in (("apt", "US airports"), ("rwy", "runways"),
                             ("frq", "frequencies"), ("chart", "charts"),
                             ("oa_apt", "world airports")):
            n = conn.execute("SELECT COUNT(*) c FROM %s" % table).fetchone()["c"]
            print("  %-16s %d" % (label + ":", n))
        stale = cache_age_days(conn)
        if stale is not None and stale > 28:
            print("\nNOTE: cache is %d days old - run 'apt.py cache update'" % stale)
        return

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # The database is derived data - rebuild it rather than migrate schemas.
    if DB_PATH.exists():
        DB_PATH.unlink()
    conn = db_connect(readonly=False)
    conn.executescript(SCHEMA)
    log("building airport cache (first run downloads ~40 MB)...")
    counts = {}
    cycle = nasr_cycle_date()
    counts.update(build_nasr(conn, cycle))
    counts.update(build_dtpp(conn))
    counts.update(build_cs(conn))
    counts.update(build_ourairports(conn))
    log("  ranking airports for search...")
    compute_ranks(conn)
    meta_set(conn, "built_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    conn.commit()
    print("cache built:")
    print("  NASR cycle %s" % cycle.isoformat())
    for key, value in counts.items():
        print("  %-24s %d" % (key + ":", value))


def compute_ranks(conn):
    """Score airports so a search for a city surfaces the airport people mean.

    Without this, "atlanta" returns a private Illinois strip before
    Hartsfield-Jackson, because nothing distinguishes them but the alphabet.
    """
    conn.execute("UPDATE apt SET rank = 0")
    # Longest runway is the honest baseline for how significant a field is.
    conn.execute("""
        UPDATE apt SET rank = COALESCE((
            SELECT MAX(CAST(json_extract(rwy.data, '$.RWY_LEN') AS INTEGER))
            FROM rwy WHERE rwy.arpt_id = apt.arpt_id), 0)
    """)
    # Airline hubs and public-use fields outrank private strips and helipads.
    conn.execute("""
        UPDATE apt SET rank = rank + CASE
            WHEN (SELECT type FROM oa_apt WHERE oa_apt.local_code = apt.arpt_id
                  OR oa_apt.ident = apt.icao_id) = 'large_airport'  THEN 60000
            WHEN (SELECT type FROM oa_apt WHERE oa_apt.local_code = apt.arpt_id
                  OR oa_apt.ident = apt.icao_id) = 'medium_airport' THEN 25000
            ELSE 0 END
    """)
    conn.execute("UPDATE apt SET rank = rank + 4000 WHERE icao_id != ''")
    conn.execute("UPDATE apt SET rank = rank + 3000 "
                 "WHERE json_extract(data, '$.FACILITY_USE_CODE') = 'PU'")
    conn.execute("UPDATE apt SET rank = rank - 15000 WHERE site_type != 'A'")


def state_lookup(conn):
    """code -> name and name -> code, straight from the data."""
    codes, names = {}, {}
    for row in conn.execute("SELECT DISTINCT state, state_name FROM apt "
                            "WHERE state != '' AND state_name != ''"):
        codes[row["state"].upper()] = row["state_name"].upper()
        names[row["state_name"].upper()] = row["state"].upper()
    return codes, names


def split_state(conn, query):
    """Pull a trailing or standalone state out of the query.

    Handles "atlanta ga", "Millbrook, NY", "new york" and bare "vermont".
    """
    codes, names = state_lookup(conn)
    q = query.replace(",", " ").strip()
    upper = q.upper()

    if upper in codes:            # bare state code
        return "", upper
    if upper in names:            # bare state name
        return "", names[upper]

    words = upper.split()
    if len(words) >= 2:
        if words[-1] in codes:    # "atlanta ga"
            return " ".join(words[:-1]), words[-1]
        for take in (3, 2):       # "boston massachusetts", "atlanta new york"
            if len(words) > take and " ".join(words[-take:]) in names:
                return " ".join(words[:-take]), names[" ".join(words[-take:])]
        if len(words) > 1 and words[-1] in names:
            return " ".join(words[:-1]), names[words[-1]]
    return q, ""


def cache_age_days(conn):
    built = meta_get(conn, "built_at")
    if not built:
        return None
    try:
        when = datetime.fromisoformat(built)
    except ValueError:
        return None
    return (datetime.now(timezone.utc) - when).days


def cycle_note(conn):
    return "FAA NASR cycle %s / d-TPP %s (cached %s)" % (
        meta_get(conn, "nasr_cycle", "?"),
        meta_get(conn, "dtpp_cycle", "?"),
        (meta_get(conn, "built_at", "?") or "?")[:10],
    )


# --------------------------------------------------------------------------
# Resolution
# --------------------------------------------------------------------------

def resolve(conn, query):
    """Return a dict describing the airport, US-first then worldwide."""
    q = (query or "").strip().upper()
    if not q:
        die("no airport given")

    candidates = [q]
    if len(q) == 4 and q[0] == "K":
        candidates.append(q[1:])
    if len(q) == 3:
        candidates.append("K" + q)

    for cand in candidates:
        row = conn.execute("SELECT * FROM apt WHERE arpt_id=?", (cand,)).fetchone()
        if row:
            return us_record(conn, row)
    for cand in candidates:
        row = conn.execute("SELECT * FROM apt WHERE icao_id=?", (cand,)).fetchone()
        if row:
            return us_record(conn, row)

    for cand in candidates:
        row = conn.execute(
            "SELECT * FROM oa_apt WHERE ident=? OR icao=? OR iata=? OR local_code=?",
            (cand, cand, cand, cand)).fetchone()
        if row:
            # An OurAirports hit may still be a US field under a different key.
            local = (row["local_code"] or "").upper()
            if local:
                us = conn.execute("SELECT * FROM apt WHERE arpt_id=?", (local,)).fetchone()
                if us:
                    return us_record(conn, us)
            return world_record(conn, row)

    like = "%" + q + "%"
    rows = conn.execute(
        "SELECT * FROM apt WHERE name LIKE ? OR city LIKE ? ORDER BY name LIMIT 25",
        (like, like)).fetchall()
    if len(rows) == 1:
        return us_record(conn, rows[0])
    if rows:
        return {"ambiguous": [
            {"id": r["arpt_id"], "icao": r["icao_id"], "name": r["name"],
             "city": r["city"], "state": r["state"]} for r in rows]}

    rows = conn.execute(
        "SELECT * FROM oa_apt WHERE name LIKE ? OR municipality LIKE ? "
        "ORDER BY name LIMIT 25", (like, like)).fetchall()
    if len(rows) == 1:
        return world_record(conn, rows[0])
    if rows:
        return {"ambiguous": [
            {"id": r["ident"], "icao": r["icao"], "iata": r["iata"], "name": r["name"],
             "city": r["municipality"], "state": r["region"]} for r in rows]}

    return {"error": "no airport matching %r" % query}


def us_record(conn, row):
    data = json.loads(row["data"])
    fid = row["arpt_id"]
    oa = conn.execute("SELECT * FROM oa_apt WHERE local_code=? OR ident=? OR icao=?",
                      (fid, row["icao_id"] or fid, row["icao_id"] or fid)).fetchone()
    return {
        "source": "faa",
        "id": fid,
        "icao": row["icao_id"] or "",
        "iata": (oa["iata"] if oa else "") or "",
        "name": row["name"],
        "city": row["city"],
        "state": row["state"],
        "state_name": row["state_name"],
        "county": row["county"],
        "lat": row["lat"],
        "lon": row["lon"],
        "elev": row["elev"],
        "site_type": row["site_type"],
        "faa": data,
        "wikipedia": (oa["wikipedia"] if oa else "") or "",
    }


def world_record(conn, row):
    return {
        "source": "ourairports",
        "id": row["ident"],
        "icao": row["icao"] or row["ident"],
        "iata": row["iata"] or "",
        "name": row["name"],
        "city": row["municipality"],
        "state": row["region"],
        "state_name": row["region"],
        "county": "",
        "lat": row["lat"],
        "lon": row["lon"],
        "elev": row["elev"],
        "site_type": row["type"],
        "faa": None,
        "wikipedia": row["wikipedia"] or "",
    }


def need_airport(conn, query):
    rec = resolve(conn, query)
    if "error" in rec:
        die(rec["error"])
    if "ambiguous" in rec:
        lines = ["%r matches several airports:" % query]
        for c in rec["ambiguous"][:15]:
            lines.append("  %-5s %-5s %s, %s" % (c.get("id", ""), c.get("icao", "") or "",
                                                 c["name"], c.get("city", "")))
        die("\n".join(lines))
    return rec


# --------------------------------------------------------------------------
# NASR field decoding
# --------------------------------------------------------------------------

SITE_TYPES = {"A": "Airport", "B": "Balloonport", "C": "Seaplane Base",
              "G": "Gliderport", "H": "Heliport", "U": "Ultralight"}
OWNERSHIP = {"PU": "Public", "PR": "Private", "MA": "Air Force", "MN": "Navy",
             "MR": "Army", "CG": "Coast Guard"}
USE = {"PU": "Public use", "PR": "Private use"}
FUEL = {"100": "100", "100LL": "100LL", "A": "Jet A", "A1": "Jet A-1",
        "A1+": "Jet A-1+", "A+": "Jet A+", "B": "Jet B", "B+": "Jet B+",
        "MOGAS": "MOGAS", "UL91": "UL91", "UL94": "UL94", "SAF": "SAF",
        "J": "Jet fuel", "80": "80 octane", "115": "115 octane"}
SURFACE = {"ASPH": "asphalt", "CONC": "concrete", "TURF": "turf", "GRVL": "gravel",
           "DIRT": "dirt", "WATER": "water", "MATS": "mats", "TREATED": "treated",
           "GRASS": "grass", "SAND": "sand", "SNOW": "snow", "ICE": "ice",
           "ROOF-TOP": "rooftop", "ALUM": "aluminum", "STEEL": "steel",
           "PEM": "porous friction", "PFC": "porous friction", "GRVD": "grooved"}
SURFACE_COND = {"E": "excellent", "G": "good", "F": "fair", "P": "poor", "L": "failed"}
LIGHTING = {"HIGH": "HIRL", "MED": "MIRL", "LOW": "LIRL", "NSTD": "non-standard",
            "PERI": "perimeter", "NONE": "none", "": ""}
OTHER_SERVICES = {"AFRT": "air freight", "AGRI": "agricultural", "AMB": "air ambulance",
                  "AVNCS": "avionics", "BCHR": "beaching gear", "CARGO": "cargo",
                  "CHTR": "charter", "GLD": "glider", "INSTR": "flight instruction",
                  "PAJA": "parachute jump", "RNTL": "aircraft rental",
                  "SALES": "aircraft sales", "SURV": "survey", "TOW": "glider tow"}


def decode_fuel(value):
    if not value:
        return []
    return [FUEL.get(v.strip(), v.strip()) for v in value.split(",") if v.strip()]


def decode_surface(code):
    if not code:
        return ""
    parts = code.split("-")
    base = SURFACE.get(parts[0], parts[0].lower())
    if len(parts) > 1 and parts[-1] in SURFACE_COND:
        return "%s (%s)" % (base, SURFACE_COND[parts[-1]])
    return base


def decode_vgsi(code):
    if not code:
        return ""
    if code.startswith("P"):
        kind = "PAPI"
    elif code.startswith("V"):
        kind = "VASI"
    elif code.startswith("S"):
        kind = "SAVASI"
    elif code.startswith("N"):
        return "none"
    else:
        return code
    side = {"L": "left", "R": "right"}.get(code[-1], "")
    boxes = "".join(c for c in code if c.isdigit())
    return " ".join(x for x in (kind, boxes and "(%s box)" % boxes, side) if x)


SMALL_WORDS = {"of", "the", "at", "in", "on", "and", "for"}
KEEP_UPPER = {"US", "USA", "AFB", "ANGB", "AAF", "NAS", "ANG", "II", "III", "IV",
              "JR", "SR", "STOL", "VA", "FAA", "USAF", "USMC"}
# NASR abbreviations, spelled out so a desktop widget reads like English.
EXPAND = {
    "RGNL": "Regional", "INTL": "International", "MUNI": "Municipal",
    "FLD": "Field", "CO": "County", "MEM": "Memorial", "MEML": "Memorial",
    "ARPT": "Airport", "NATL": "National", "CNTY": "County", "MTN": "Mountain",
    "VLY": "Valley", "SPB": "Seaplane Base", "HELIPORT": "Heliport",
    "EXEC": "Executive", "IND": "Industrial", "AIRPARK": "Airpark",
    "MED": "Medical", "CNTR": "Center", "HOSP": "Hospital", "UNIV": "University",
    "ST": "St", "MT": "Mt", "FT": "Ft", "PT": "Pt", "JCT": "Junction",
    "SVC": "Service", "TWP": "Township", "VET": "Veterans",
}


def title_case(text):
    """NASR ships SHOUTING ABBREVIATED NAMES; soften them for a UI."""
    if not text:
        return ""

    def fix(part):
        upper = part.upper()
        if upper in KEEP_UPPER:
            return upper
        if upper in EXPAND:
            return EXPAND[upper]
        return part.capitalize()

    words = []
    for i, word in enumerate(str(text).split()):
        if word.lower() in SMALL_WORDS and i:
            words.append(word.lower())
            continue
        pieces = re.split(r"([-/'.])", word)
        rebuilt = []
        for j, piece in enumerate(pieces):
            if piece in "-/'.":
                rebuilt.append(piece)
            elif j and pieces[j - 1] == "'":
                rebuilt.append(piece.lower())  # St Luke's, not St Luke'S
            else:
                rebuilt.append(fix(piece))
        words.append("".join(rebuilt))
    return " ".join(words)


def fmt_ft(value):
    n = _fnum(value)
    return "%s'" % ("{:,}".format(int(round(n))) if n is not None else value)


# --------------------------------------------------------------------------
# Airport data assembly
# --------------------------------------------------------------------------

def get_runways(conn, rec):
    if rec["source"] != "faa":
        rows = conn.execute("SELECT * FROM oa_rwy WHERE ident=?", (rec["id"],)).fetchall()
        out = []
        for r in rows:
            if r["closed"] == "1":
                continue
            oa_surface = {"asp": "asphalt", "con": "concrete", "grs": "grass",
                          "gvl": "gravel", "tur": "turf", "wat": "water",
                          "dirt": "dirt", "san": "sand", "pem": "asphalt",
                          "psp": "steel matting", "bit": "bitumen"}
            raw_surface = (r["surface"] or "").strip().lower()
            out.append({
                "id": "%s/%s" % (r["le_ident"] or "?", r["he_ident"] or "?"),
                "length": r["length_ft"], "width": r["width_ft"],
                "surface": oa_surface.get(raw_surface, raw_surface),
                "lighted": r["lighted"] == "1", "ends": [],
            })
        return out

    fid = rec["id"]
    ends_by_rwy = {}
    for r in conn.execute("SELECT * FROM rwy_end WHERE arpt_id=?", (fid,)).fetchall():
        ends_by_rwy.setdefault(r["rwy_id"], []).append(json.loads(r["data"]))

    out = []
    for r in conn.execute("SELECT * FROM rwy WHERE arpt_id=?", (fid,)).fetchall():
        d = json.loads(r["data"])
        ends = []
        for e in ends_by_rwy.get(r["rwy_id"], []):
            ends.append({
                "id": e.get("RWY_END_ID", ""),
                "true_align": e.get("TRUE_ALIGNMENT", ""),
                "ils": e.get("ILS_TYPE", ""),
                "vgsi": decode_vgsi(e.get("VGSI_CODE", "")),
                "approach_lights": e.get("APCH_LGT_SYSTEM_CODE", ""),
                "reil": e.get("RWY_END_LGTS_FLAG", ""),
                "cl_lights": e.get("CNTRLN_LGTS_AVBL_FLAG", ""),
                "tdz_lights": e.get("TDZ_LGT_AVBL_FLAG", ""),
                "displaced_thr": e.get("DISPLACED_THR_LEN", ""),
                "lat": _fnum(e.get("LAT_DECIMAL")),
                "lon": _fnum(e.get("LONG_DECIMAL")),
                "elev": e.get("RWY_END_ELEV", ""),
                "tora": e.get("TKOF_RUN_AVBL", ""),
                "toda": e.get("TKOF_DIST_AVBL", ""),
                "asda": e.get("ACLT_STOP_DIST_AVBL", ""),
                "lda": e.get("LNDG_DIST_AVBL", ""),
                "right_traffic": e.get("RIGHT_HAND_TRAFFIC_PAT_FLAG", ""),
                "obstruction": e.get("OBSTN_TYPE", ""),
                "obst_slope": e.get("OBSTN_CLNC_SLOPE", ""),
                "obst_height": e.get("OBSTN_HGT", ""),
                "obst_dist": e.get("DIST_FROM_THR", ""),
                "markings": e.get("RWY_MARKING_TYPE_CODE", ""),
            })
        ends.sort(key=lambda e: e["id"])
        out.append({
            "id": r["rwy_id"],
            "length": d.get("RWY_LEN", ""),
            "width": d.get("RWY_WIDTH", ""),
            "surface": decode_surface(d.get("SURFACE_TYPE_CODE", "")),
            "lighting": LIGHTING.get(d.get("RWY_LGT_CODE", ""), d.get("RWY_LGT_CODE", "")),
            "weight_sw": d.get("GROSS_WT_SW", ""),
            "weight_dw": d.get("GROSS_WT_DW", ""),
            "pcn": d.get("PCN_PCR_NUMBER", ""),
            "ends": ends,
        })
    out.sort(key=lambda r: -(_fnum(r["length"]) or 0))
    return out


FREQ_ORDER = ["ATIS", "AWOS", "ASOS", "CTAF", "UNICOM", "LCL", "GND", "CD", "APCH", "DEP"]


def get_freqs(conn, rec):
    if rec["source"] != "faa":
        return []
    rows = conn.execute("SELECT * FROM frq WHERE arpt_id=?", (rec["id"],)).fetchall()
    out = []
    for r in rows:
        use = (r["freq_use"] or "").strip()
        freq = (r["freq"] or "").strip()
        if not freq:
            continue
        # Skip UHF military frequencies in the default view.
        n = _fnum(freq)
        out.append({
            "freq": freq,
            "use": use,
            "facility": r["facility"],
            "fac_type": r["fac_type"],
            "tower_hours": (r["twr_hrs"] or "").strip(),
            "remark": (r["remark"] or "").strip(),
            "uhf": bool(n and n > 200),
        })
    return out


def pick_freq(freqs, *keys):
    for key in keys:
        for f in freqs:
            if f["uhf"]:
                continue
            if key in f["use"].upper():
                return f
    return None


def get_charts(conn, rec):
    if rec["source"] != "faa":
        return {"cycle": None, "charts": [], "cs": None}
    cycle = meta_get(conn, "dtpp_cycle", "")
    rows = conn.execute(
        "SELECT * FROM chart WHERE arpt_id=? OR icao_id=?",
        (rec["id"], rec["icao"] or rec["id"])).fetchall()
    order = {"APD": 0, "HOT": 1, "IAP": 2, "DP": 3, "STR": 4, "ODP": 5, "MIN": 6, "LAH": 7}
    charts = [{
        "code": r["code"], "name": r["name"], "pdf": r["pdf"],
        "url": "%s/d-tpp/%s/%s" % (AERONAV, cycle, r["pdf"]),
    } for r in rows]
    charts.sort(key=lambda c: (order.get(c["code"], 9), c["name"]))

    cs = conn.execute("SELECT * FROM cs WHERE arpt_id=?", (rec["id"],)).fetchone()
    cs_url = None
    if cs:
        edition = meta_get(conn, "cs_edition", "")
        cs_url = "%s/afd/%s/%s" % (AERONAV, edition, cs["pdf"])
    return {"cycle": cycle, "charts": charts, "cs": cs_url}


PROC_KINDS = {
    "IAP": "approaches",
    "DP": "departures",
    "ODP": "obstacle_departures",
    "STR": "arrivals",
    "DAU": "diverse_vector",
    "MIN": "minimums",
    "HOT": "hot_spots",
    "LAH": "lahso",
    "APD": "airport_diagram",
}

APPROACH_TYPES = [
    ("ILS", r"\bILS\b"), ("LOC", r"\bLOC\b"), ("LDA", r"\bLDA\b"),
    ("SDF", r"\bSDF\b"), ("RNAV (RNP)", r"RNAV\s*\(RNP\)"),
    ("RNAV (GPS)", r"RNAV\s*\(GPS\)"), ("GPS", r"\bGPS\b"),
    ("VOR", r"\bVOR\b"), ("NDB", r"\bNDB\b"), ("TACAN", r"\bTACAN\b"),
    ("ASR", r"\bASR\b"), ("COPTER", r"\bCOPTER\b"),
]


def parse_procedure(name):
    """Split a d-TPP chart name into procedure, continuation page, runway and type."""
    base = re.sub(r",\s*CONT\.?\s*\d*$", "", name, flags=re.I).strip()
    cont = base != name.strip()
    m = re.search(r"\bRWY\s+(\d{1,2}[LRC]?)", base, re.I)
    runway = m.group(1).upper() if m else ""
    circling = ""
    if not runway:
        c = re.search(r"[-\s]([A-Z])$", base)
        circling = c.group(1) if c else ""
    kinds = [label for label, pat in APPROACH_TYPES if re.search(pat, base, re.I)]
    return {"base": base, "continuation": cont, "runway": runway,
            "circling": circling, "types": kinds}


def get_procedures(conn, rec, runway=None, kind=None):
    """Terminal procedures grouped the way a pilot briefs them."""
    charts = get_charts(conn, rec)
    groups = {v: {} for v in PROC_KINDS.values()}
    groups["other"] = {}
    for chart in charts["charts"]:
        bucket = PROC_KINDS.get(chart["code"], "other")
        info = parse_procedure(chart["name"])
        entry = groups[bucket].setdefault(info["base"], {
            "name": info["base"], "runway": info["runway"],
            "circling": info["circling"], "types": info["types"],
            "code": chart["code"], "url": None, "pages": [],
        })
        if info["continuation"]:
            entry["pages"].append(chart["url"])
        else:
            entry["url"] = chart["url"]
        if entry["url"] is None and entry["pages"]:
            entry["url"] = entry["pages"][0]

    def sort_key(item):
        rwy = item["runway"]
        num = int(re.sub(r"[^0-9]", "", rwy) or 99)
        return (num, rwy, item["name"])

    out = {}
    for bucket, items in groups.items():
        listed = sorted(items.values(), key=sort_key)
        if runway:
            want = runway.upper().lstrip("0")
            listed = [i for i in listed
                      if i["runway"].lstrip("0") == want or not i["runway"]] \
                if bucket == "approaches" else listed
        out[bucket] = listed
    out["cycle"] = charts["cycle"]
    out["cs"] = charts["cs"]
    out["effective"] = meta_get(conn, "dtpp_effective", "")
    if out["effective"]:
        try:
            out["expires"] = (date.fromisoformat(out["effective"])
                              + timedelta(days=28)).isoformat()
        except ValueError:
            out["expires"] = ""
    if kind:
        keep = {k.strip().lower() for k in kind.split(",")}
        for bucket in list(out):
            if bucket in PROC_KINDS.values() or bucket == "other":
                if bucket not in keep:
                    out[bucket] = []
    return out


def get_remarks(conn, rec, limit=None):
    if rec["source"] != "faa":
        return []
    rows = conn.execute("SELECT remark FROM rmk WHERE arpt_id=?", (rec["id"],)).fetchall()
    out = [r["remark"] for r in rows if r["remark"]]
    return out[:limit] if limit else out


def pattern_altitude(conn, rec):
    """TPA from the NASR field, falling back to the remark that carries it."""
    faa = rec["faa"] or {}
    if faa.get("TPA"):
        return fmt_ft(faa["TPA"]) + " MSL"
    for remark in get_remarks(conn, rec):
        if "TPA" in remark.upper():
            return re.sub(r"^TPA\s+", "", remark.strip().rstrip("."), flags=re.I)
    return ""


def get_attendance(conn, rec):
    """When the field is actually attended - the thing that decides a GA trip."""
    if rec["source"] != "faa":
        return []
    rows = conn.execute("SELECT month, day, hour FROM att WHERE arpt_id=?",
                        (rec["id"],)).fetchall()
    out = []
    for r in rows:
        month, day, hour = (r["month"] or "").strip(), (r["day"] or "").strip(), (r["hour"] or "").strip()
        if month.upper() == "ALL" and day.upper() == "ALL":
            label = hour if hour.upper() != "ALL" else "24 hours"
        else:
            label = " ".join(x for x in (month if month.upper() != "ALL" else "",
                                         day if day.upper() != "ALL" else "", hour) if x)
        if label:
            out.append(label)
    return out


RECENTS_PATH = Path(os.environ.get("AIRPORT_INFO_RECENTS")
                    or (NOTES_DIR.parent / "recents.json"))
RECENTS_MAX = 12


def read_recents():
    try:
        data = json.loads(RECENTS_PATH.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def write_recents(entries):
    RECENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RECENTS_PATH.write_text(json.dumps(entries, indent=2))


def touch_recent(rec):
    """Record a visit. Pinned entries always sort first and never roll off."""
    entries = [e for e in read_recents() if e.get("id") != rec["id"]]
    pinned_before = next((e for e in read_recents() if e.get("id") == rec["id"]), {})
    entries.insert(0, {"id": rec["id"], "ident": rec["icao"] or rec["id"],
                       "pinned": bool(pinned_before.get("pinned")),
                       "last": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    pinned = [e for e in entries if e.get("pinned")]
    rest = [e for e in entries if not e.get("pinned")][:RECENTS_MAX]
    write_recents(pinned + rest)


def get_contacts(conn, rec):
    if rec["source"] != "faa":
        return []
    return [dict(r) for r in
            conn.execute("SELECT * FROM con WHERE arpt_id=?", (rec["id"],)).fetchall()]


# --------------------------------------------------------------------------
# Live data
# --------------------------------------------------------------------------

def _awc(product, ident):
    """Fetch one AWC product.

    An unknown station answers with an empty body, which is not an error - it
    means "this field publishes nothing". Returning None for that lets the
    caller cache the miss instead of retrying on every keystroke.
    """
    try:
        text = Http.get("%s/%s?ids=%s&format=json"
                        % (AWC, product, urllib.parse.quote(ident)),
                        timeout=45, retries=2)
    except Exception as exc:
        return {"error": str(exc)}
    text = (text or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data[0] if data else None


def fetch_metar(ident):
    return _awc("metar", ident)


METAR_CACHE = CACHE_DIR / "metar"
METAR_TTL_SECONDS = 300
METAR_MISS_TTL_SECONDS = 1800


TFR_CACHE = CACHE_DIR / "tfr.json"
TFR_TTL_SECONDS = 900


def tfrs_for_state(state):
    """Active TFRs in one state. The national list is small, so cache it whole
    rather than hammering the FAA once per airport."""
    if not state:
        return {"available": True, "tfrs": []}
    data = None
    if TFR_CACHE.exists() and (time.time() - TFR_CACHE.stat().st_mtime) < TFR_TTL_SECONDS:
        try:
            data = json.loads(TFR_CACHE.read_text())
        except Exception:
            data = None
    if data is None:
        fetched = fetch_tfrs()
        if isinstance(fetched, dict) and "error" in fetched:
            return {"available": False, "tfrs": [], "error": fetched["error"]}
        data = fetched or []
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        TFR_CACHE.write_text(json.dumps(data))
    hits = [{"id": t.get("notam_id", ""), "type": t.get("type", ""),
             "description": t.get("description", ""),
             "url": "https://tfr.faa.gov/save_pages/detail_%s.html"
                    % t.get("notam_id", "").replace("/", "_")}
            for t in data if (t.get("state") or "").upper() == state.upper()]
    return {"available": True, "tfrs": hits, "state": state}


def _wx_cached(kind, ident, fetch):
    """Cache weather on disk, negatives included.

    Without caching the miss, a field with no weather station (most small
    airports) re-queries the network on every arrow keypress.
    """
    METAR_CACHE.mkdir(parents=True, exist_ok=True)
    path = METAR_CACHE / ("%s_%s.json" % (kind, re.sub(r"[^A-Z0-9]", "_", ident.upper())))
    if path.exists():
        age = time.time() - path.stat().st_mtime
        try:
            cached = json.loads(path.read_text())
        except Exception:
            cached = None
        ttl = METAR_TTL_SECONDS if cached else METAR_MISS_TTL_SECONDS
        if cached is not None and age < ttl:
            return cached or None
        if cached is None and age < METAR_MISS_TTL_SECONDS:
            return None

    data = fetch(ident)
    if isinstance(data, dict) and "error" not in data and data:
        path.write_text(json.dumps(data))
        return data
    if isinstance(data, dict) and "error" in data:
        # A transient failure should not poison the cache; serve stale if we have it.
        if path.exists():
            try:
                return json.loads(path.read_text()) or None
            except Exception:
                return None
        return None
    path.write_text("null")  # station genuinely publishes nothing
    return None


def fetch_metar_cached(ident):
    return _wx_cached("metar", ident, lambda i: fetch_metar(i))


def fetch_taf_cached(ident):
    return _wx_cached("taf", ident, lambda i: fetch_taf(i))


COMPASS = ["north", "north-northeast", "northeast", "east-northeast", "east",
           "east-southeast", "southeast", "south-southeast", "south",
           "south-southwest", "southwest", "west-southwest", "west",
           "west-northwest", "northwest", "north-northwest"]

COVER_TEXT = {"SKC": "clear", "CLR": "clear", "CAVOK": "clear", "NCD": "clear",
              "FEW": "a few clouds", "SCT": "scattered clouds",
              "BKN": "broken clouds", "OVC": "overcast", "OVX": "obscured"}

CATEGORY_TEXT = {
    "VFR": "Visual Flight Rules",
    "MVFR": "Marginal Visual Flight Rules",
    "IFR": "Instrument Flight Rules",
    "LIFR": "Low Instrument Flight Rules",
}


def compass(degrees):
    try:
        return COMPASS[int((float(degrees) % 360) / 22.5 + 0.5) % 16]
    except (TypeError, ValueError):
        return ""


def use_fahrenheit():
    """Show one temperature unit, the one this machine expects."""
    override = os.environ.get("AIRPORT_INFO_UNITS", "").strip().lower()
    if override in ("imperial", "us", "f", "fahrenheit"):
        return True
    if override in ("metric", "si", "c", "celsius"):
        return False
    for var in ("LC_MEASUREMENT", "LC_ALL", "LANG"):
        value = os.environ.get(var, "").upper()
        if value:
            return any(value.startswith(p) or "_" + p in value
                       for p in ("EN_US", "US", "EN_LR", "EN_MM"))
    return True  # FAA data is American; default to the local convention


def temp_text(celsius):
    if celsius is None:
        return ""
    if use_fahrenheit():
        return "%.0f°F" % (celsius * 9 / 5 + 32)
    return "%.0f°C" % celsius


CEILING_COVERS = ("BKN", "OVC", "OVX", "VV")


def ceiling_of(metar):
    """Ceiling is the lowest broken/overcast layer - the number that decides
    whether an approach is flyable."""
    lowest = None
    for layer in (metar.get("clouds") or []):
        if layer.get("cover") in CEILING_COVERS and layer.get("base") is not None:
            if lowest is None or layer["base"] < lowest:
                lowest = layer["base"]
    return lowest


def get_airspace(conn, rec):
    """Class B/C/D/E surface area, with the hours it is active."""
    if rec["source"] != "faa":
        return {}
    row = conn.execute("SELECT * FROM airspace WHERE arpt_id=?", (rec["id"],)).fetchone()
    if not row:
        return {}
    classes = [name for name, flag in (("B", row["class_b"]), ("C", row["class_c"]),
                                       ("D", row["class_d"]), ("E", row["class_e"]))
               if (flag or "").upper() == "Y"]
    if not classes:
        return {}
    return {"classes": classes,
            "label": "Class " + "/".join(classes),
            "hours": re.sub(r"\s+", " ", row["hours"] or ""),
            "remark": row["remark"] or ""}


def humanize_weather(metar, taf, elev):
    """Turn a METAR into something a non-pilot can read, without throwing away
    the numbers a pilot needs."""
    if not isinstance(metar, dict) or not metar.get("rawOb"):
        return {"available": False,
                "summary": "No weather station reports for this airport."}

    wind = "calm"
    speed = metar.get("wspd")
    direction = metar.get("wdir")
    if speed:
        if direction in (None, 0) or str(direction).upper() == "VRB":
            wind = "variable at %s kt" % speed
        else:
            wind = "from the %s (%s°) at %s kt" % (compass(direction), direction, speed)
        if metar.get("wgst"):
            wind += ", gusting %s kt" % metar["wgst"]

    layers = metar.get("clouds") or []
    described = []
    for layer in layers:
        text = COVER_TEXT.get(layer.get("cover", ""), layer.get("cover", "").lower())
        if layer.get("base") is not None and text not in ("clear", ""):
            described.append("%s at %s ft" % (text, "{:,}".format(int(layer["base"]))))
        elif text:
            described.append(text)
    sky = ", ".join(described) if described else \
        COVER_TEXT.get(metar.get("cover", ""), "no cloud report")

    visibility = metar.get("visib")
    if visibility is None:
        vis_text = ""
    elif str(visibility).endswith("+"):
        vis_text = "%s miles or more" % str(visibility).rstrip("+")
    else:
        vis_text = "%s miles" % visibility

    temp = metar.get("temp")
    dewp = metar.get("dewp")
    temperature = temp_text(temp)
    dewpoint = temp_text(dewp)

    ceiling = ceiling_of(metar)
    ceiling_text = ("{:,} ft".format(int(ceiling)) if ceiling is not None
                    else "unlimited")

    altim_text = ""
    density = None
    pressure = None
    if metar.get("altim"):
        inhg = metar["altim"] / 33.8639
        altim_text = "%.2f inHg (%.0f hPa)" % (inhg, metar["altim"])
        if elev is not None:
            pressure = round(elev + (29.92 - inhg) * 1000)
            if temp is not None:
                isa = 15 - 2 * (elev / 1000.0)
                density = round(pressure + 120 * (temp - isa))

    summary_bits = []
    if sky:
        summary_bits.append(sky[0].upper() + sky[1:])
    if temperature:
        summary_bits.append(temperature)
    if wind:
        summary_bits.append("wind " + wind)
    summary = ", ".join(summary_bits) + "." if summary_bits else ""

    observed = ""
    if metar.get("reportTime"):
        observed = str(metar["reportTime"])[11:16] + "Z"

    return {
        "available": True,
        "summary": summary,
        "category": metar.get("fltCat", ""),
        "category_text": CATEGORY_TEXT.get(metar.get("fltCat", ""), ""),
        "wind": wind,
        "sky": sky,
        "ceiling": ceiling_text,
        "ceiling_ft": ceiling,
        "visibility": vis_text,
        "temp": temperature,
        "dewpoint": dewpoint,
        "altimeter": altim_text,
        "pressure_alt": pressure,
        "density_alt": density,
        "observed": observed,
        "raw": metar.get("rawOb", ""),
        "taf": (taf or {}).get("rawTAF", "") if isinstance(taf, dict) else "",
    }


# Frequencies worth showing on a field page, in the order a pilot reads them.
FIELD_FREQS = [
    ("ATIS", ("D-ATIS", "ATIS")),
    ("Weather", ("ASOS", "AWOS")),
    ("CTAF", ("CTAF",)),
    ("UNICOM", ("UNICOM",)),
    ("Tower", ("LCL",)),
    ("Ground", ("GND",)),
    ("Clearance", ("CD",)),
]
APPROACH_USES = ("APCH", "DEP", "FINAL", "PRM", "ARR")


def split_frequencies(freqs):
    """A big airport publishes a hundred frequencies. Only a handful belong on
    a field page; approach/departure ones belong with the procedures."""
    field, approach, other = [], [], []
    seen = set()
    for label, keys in FIELD_FREQS:
        for f in freqs:
            if f["uhf"]:
                continue
            use = f["use"].upper()
            if not any(use.startswith(k) or use == k for k in keys):
                continue
            key = (label, f["freq"])
            if key in seen:
                continue
            seen.add(key)
            field.append({"label": label, "freq": f["freq"],
                          "hours": re.sub(r"\s+", " ", f["tower_hours"] or ""),
                          "remark": f["remark"]})
    for f in freqs:
        if f["uhf"]:
            continue
        use = f["use"].upper()
        if any(use.startswith(k) for k in APPROACH_USES) or " DP" in use or " STAR" in use:
            key = (use, f["freq"])
            if key in seen:
                continue
            seen.add(key)
            approach.append({"label": f["use"], "freq": f["freq"]})
        elif not any((label, f["freq"]) in seen for label, _ in FIELD_FREQS):
            other.append({"label": f["use"], "freq": f["freq"]})
    return field, approach, other


def fetch_taf(ident):
    return _awc("taf", ident)


def wx_ident(rec):
    """Weather stations are keyed by ICAO; fall back to K+id for US fields."""
    if rec["icao"]:
        return rec["icao"]
    if rec["source"] == "faa" and len(rec["id"]) == 3 and rec["id"].isalpha():
        return "K" + rec["id"]
    return rec["id"]


def fetch_twilight(lat, lon, when=None):
    try:
        url = "%s?lat=%.5f&lng=%.5f&formatted=0" % (SUNRISE_URL, lat, lon)
        if when:
            url += "&date=" + when
        return Http.json(url, timeout=30, retries=2).get("results")
    except Exception:
        return None


def haversine_nm(lat1, lon1, lat2, lon2):
    r = 3440.065  # nautical miles
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def fetch_tfrs():
    try:
        return Http.json(TFR_LIST_URL, timeout=60, retries=2)
    except Exception as exc:
        return {"error": str(exc)}


def tfr_geometry(notam_id):
    """Best effort: pull lat/lon out of a TFR detail page."""
    safe = notam_id.replace("/", "_")
    try:
        xml = Http.get(TFR_DETAIL_URL % safe, timeout=45, retries=1)
    except Exception:
        return None
    lats = re.findall(r"<latitude>([\d.\-]+)</latitude>", xml, re.I)
    lons = re.findall(r"<longitude>([\d.\-]+)</longitude>", xml, re.I)
    pts = []
    for a, b in zip(lats, lons):
        try:
            pts.append((float(a), float(b)))
        except ValueError:
            continue
    return pts or None


# --------------------------------------------------------------------------
# OpenStreetMap amenities
# --------------------------------------------------------------------------

POI_FILTER = (
    '["amenity"~"^(restaurant|cafe|fast_food|bar|pub|food_court|ice_cream|'
    'bureau_de_change|pharmacy|atm|bank|car_rental|charging_station|'
    'lounge|nursery|clinic|doctors)$"]'
)

LOUNGE_BRANDS = re.compile(
    r"sky\s*club|skyclub|admirals?\s*club|united\s*club|polaris|centurion|"
    r"escape\s*lounge|priority\s*pass|amex|american\s*express|chase\s*sapphire|"
    r"sapphire\s*lounge|capital\s*one|the\s*club\s*(at|mco|bos|phx)|plaza\s*premium|"
    r"clubhouse|flagship\s*lounge|delta\s*one|alaska\s*lounge|aspire\s*lounge|"
    r"maple\s*leaf\s*lounge|air\s*france\s*lounge|lufthansa\s*(senator|business)",
    re.I)


def overpass_query(query, timeout=90):
    """POST to Overpass, rotating mirrors. 429/504 here means throttled, not broken."""
    last = None
    for attempt in range(2):
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                data = urllib.parse.urlencode({"data": query}).encode()
                text = Http.get(
                    endpoint, data=data, timeout=timeout, retries=1,
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
                if not text.lstrip().startswith("{"):
                    raise RuntimeError("non-JSON response from %s" % endpoint)
                return json.loads(text)
            except Exception as exc:
                last = exc
        if attempt == 0:
            time.sleep(6)
    raise RuntimeError("all Overpass mirrors failed (last: %s)" % last)


def q_aerodrome(lat, lon, radius=9000):
    """Outline of the aerodrome(s) near a point. Small, fast, works on every mirror."""
    return f"""[out:json][timeout:80];
(
  way["aeroway"="aerodrome"](around:{radius},{lat:.6f},{lon:.6f});
  relation["aeroway"="aerodrome"](around:{radius},{lat:.6f},{lon:.6f});
);
out geom;
"""


def q_pois(bbox):
    """Everything interesting inside the aerodrome bounding box."""
    s_, w_, n_, e_ = bbox
    box = f"{s_:.6f},{w_:.6f},{n_:.6f},{e_:.6f}"
    return f"""[out:json][timeout:120];
(
  nwr{POI_FILTER}({box});
  nwr["shop"]({box});
  nwr["aeroway"="lounge"]({box});
)->.pois;
.pois out tags center;
(
  way["aeroway"="terminal"]({box});
  relation["aeroway"="terminal"]({box});
  way["building"="terminal"]({box});
)->.terms;
.terms out geom;
"""


def _ring(element):
    geom = element.get("geometry")
    if geom:
        return [(p["lon"], p["lat"]) for p in geom]
    rings = []
    for member in element.get("members", []):
        if member.get("role") in ("outer", None) and member.get("geometry"):
            rings.extend((p["lon"], p["lat"]) for p in member["geometry"])
    return rings


def point_in_ring(x, y, ring):
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def in_any(x, y, rings):
    return any(point_in_ring(x, y, r) for r in rings)


def classify(tags):
    name = tags.get("name", "")
    operator = tags.get("operator", "")
    amenity = tags.get("amenity", "")
    if amenity == "lounge" or tags.get("aeroway") == "lounge":
        return "lounge"
    # A named airline/card lounge wins; a bare "lounge" in the name of a shop
    # ("The Beauty Lounge") or a bar ("Cigar and Smoke Lounge") does not.
    if LOUNGE_BRANDS.search(name) or LOUNGE_BRANDS.search(operator):
        return "lounge"
    if tags.get("shop"):
        return "shop"
    if re.search(r"\blounge\b", name, re.I) and amenity not in ("bar", "pub", "restaurant"):
        return "lounge"
    if amenity in ("restaurant", "cafe", "fast_food", "bar", "pub", "food_court", "ice_cream"):
        return "food"
    if tags.get("shop"):
        return "shop"
    return "service"


def fetch_amenities(rec, refresh=False):
    """Two steps: outline the aerodrome, then read everything inside its bbox.

    Bounding box then point-in-polygon beats a fixed radius: it excludes the city
    around an urban field like LGA and still covers a sprawling one like DFW.
    """
    OSM_DIR.mkdir(parents=True, exist_ok=True)
    key = (rec["icao"] or rec["id"]).upper()
    path = OSM_DIR / ("%s.json" % re.sub(r"[^A-Z0-9]", "_", key))
    if path.exists() and not refresh:
        age = (time.time() - path.stat().st_mtime) / 86400
        if age < OSM_TTL_DAYS:
            return json.loads(path.read_text())

    lat, lon = rec["lat"], rec["lon"]
    if lat is None or lon is None:
        return {"error": "no coordinates for %s" % rec["id"], "pois": [], "terminals": []}

    def cached_or_error(exc):
        if path.exists():  # stale beats nothing when Overpass is throttled
            stale = json.loads(path.read_text())
            stale["stale"] = True
            return stale
        return {"error": str(exc), "pois": [], "terminals": []}

    try:
        field = overpass_query(q_aerodrome(lat, lon))
    except Exception as exc:
        return cached_or_error(exc)

    rings = []
    for el in field.get("elements", []):
        ring = _ring(el)
        if len(ring) >= 4 and in_any(lon, lat, [ring]):
            rings.append(ring)
    if not rings:  # unmapped aerodrome - fall back to a plain radius
        rings = []
        bbox = (lat - 0.025, lon - 0.030, lat + 0.025, lon + 0.030)
    else:
        xs = [p[0] for r in rings for p in r]
        ys = [p[1] for r in rings for p in r]
        bbox = (min(ys), min(xs), max(ys), max(xs))

    try:
        data = overpass_query(q_pois(bbox))
    except Exception as exc:
        return cached_or_error(exc)

    terminals = []
    pois = []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        if tags.get("aeroway") == "terminal" or tags.get("building") == "terminal":
            ring = _ring(el)
            if len(ring) >= 4 and tags.get("name"):
                terminals.append({"name": tags["name"], "ring": ring})
            continue
        if "amenity" not in tags and "shop" not in tags and tags.get("aeroway") != "lounge":
            continue
        plat = el.get("lat") or (el.get("center") or {}).get("lat")
        plon = el.get("lon") or (el.get("center") or {}).get("lon")
        if plat is None or plon is None:
            continue
        if rings and not in_any(plon, plat, rings):
            continue  # inside the bbox but off the airport
        pois.append({
            "id": "%s/%s" % (el["type"], el["id"]),
            "name": tags.get("name") or tags.get("operator") or "(unnamed)",
            "kind": classify(tags),
            "amenity": tags.get("amenity", ""),
            "shop": tags.get("shop", ""),
            "cuisine": tags.get("cuisine", ""),
            "operator": tags.get("operator", ""),
            "brand": tags.get("brand", ""),
            "hours": tags.get("opening_hours", ""),
            "level": tags.get("level", ""),
            "website": tags.get("website", "") or tags.get("contact:website", ""),
            "phone": tags.get("phone", ""),
            "lat": plat, "lon": plon,
            "terminal": "",
        })

    # Smallest containing polygon wins, so a concourse beats the terminal it sits in.
    terminals.sort(key=lambda t: len(t["ring"]), reverse=True)
    for poi in pois:
        for term in terminals:
            if point_in_ring(poi["lon"], poi["lat"], term["ring"]):
                poi["terminal"] = term["name"]
    result = {
        "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "pois": pois,
        "terminals": sorted({t["name"] for t in terminals}),
        "aerodrome_mapped": bool(rings),
        "attribution": "OpenStreetMap contributors (ODbL)",
    }
    path.write_text(json.dumps(result))
    return result


# --------------------------------------------------------------------------
# FBOs and fuel prices (AirNav)
#
# No free aviation feed carries FBO names, hours or fuel prices - NASR has
# fuel *types* only. AirNav publishes them, and its robots.txt disallows only
# /cgi-bin/, so /airport/<id> is fetchable. Be a good citizen anyway: one
# airport at a time, on demand, identified honestly, cached for a day. Never
# crawl this in bulk.
# --------------------------------------------------------------------------

AIRNAV_URL = "https://www.airnav.com/airport/%s"
AIRNAV_TTL_HOURS = 24
AIRNAV_DIR = CACHE_DIR / "airnav"


class TableWalker(HTMLParser):
    """Collect table rows as lists of raw cell HTML, nesting-aware.

    Regex cannot do this and a naive parser cannot either: AirNav nests the
    fuel-price table inside a cell of the FBO row, so a nested </td> must not
    close the outer cell and a nested <tr> must not close the outer row. Each
    open row and cell therefore remembers the table depth it belongs to.
    """

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.depth = 0
        self.rows = []
        self._row = None
        self._row_depth = -1
        self._cell = None
        self._cell_depth = -1

    def _emit(self, chunk):
        if self._cell is not None:
            self._cell.append(chunk)

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "table":
            self.depth += 1
            self._emit("<table>")
            return
        if tag == "tr":
            if self._cell is not None:
                self._emit("<tr>")
            else:
                self._row = []
                self._row_depth = self.depth
            return
        if tag == "td":
            if self._cell is not None:
                self._emit("<td>")
            elif self._row is not None:
                self._cell = []
                self._cell_depth = self.depth
            return
        self._emit("<%s %s>" % (tag, " ".join(
            '%s="%s"' % (k, v or "") for k, v in attrs)))

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "table":
            self._emit("</table>")
            self.depth -= 1
            return
        if tag == "td":
            if self._cell is not None and self.depth == self._cell_depth:
                self._row.append("".join(self._cell))
                self._cell = None
            else:
                self._emit("</td>")
            return
        if tag == "tr":
            if self._cell is None and self._row is not None and self.depth == self._row_depth:
                self.rows.append(self._row)
                self._row = None
            else:
                self._emit("</tr>")
            return
        self._emit("</%s>" % tag)

    def handle_data(self, data):
        self._emit(data)

    def handle_entityref(self, name):
        self._emit({"nbsp": " ", "amp": "&", "quot": '"', "lt": "<",
                    "gt": ">", "reg": ""}.get(name, " "))

    def handle_charref(self, name):
        self._emit(" ")


def _text(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def _price_table(cell_html):
    """Fuel prices: a header row of fuel names, then one row per service type."""
    walker = TableWalker()
    walker.feed(cell_html)
    fuels, rows, updated = [], [], ""
    for row in walker.rows:
        texts = [_text(c) for c in row]
        joined = " ".join(texts)
        if "Updated" in joined:
            m = re.search(r"Updated\s+([\w-]+)", joined)
            if m:
                updated = m.group(1)
            continue
        labels = [t for t in texts if re.match(r"^(100LL|Jet A\+?|Jet-A\+?|MOGAS|UL94|UL91|SAF|80)$", t, re.I)]
        if labels and not fuels:
            fuels = labels
            continue
        money = re.findall(r"\$\s*([\d]+\.[\d]{2})", joined)
        service = texts[0].strip() if texts else ""
        if money and service in ("FS", "SS", "Full", "Self"):
            rows.append({"service": {"FS": "full serve", "SS": "self serve"}.get(service, service),
                         "prices": money})
    out = []
    for row in rows:
        for i, price in enumerate(row["prices"]):
            out.append({"fuel": fuels[i] if i < len(fuels) else "?",
                        "service": row["service"], "price": price})
    return out, updated


def parse_airnav(html, ident):
    if html.find("FBO, Fuel Providers") < 0:
        return []
    walker = TableWalker()
    walker.feed(html)
    out = []
    for cells in walker.rows:
        # An FBO row carries the "More info and photos of <name>" link. Price
        # sub-rows also have five cells, so cell count alone is not enough.
        if len(cells) < 5 or "More info and" not in " ".join(cells):
            continue
        name = ""
        m = re.search(r'alt="([^"]+)"', cells[0])
        if m and m.group(1).strip() and "aff/" not in cells[0][:200]:
            name = m.group(1).strip()
        if not name:
            m = re.search(r"More info and\s*photos\s*of\s+(.+)$", _text(cells[-1]))
            if m:
                name = m.group(1).strip()
        if not name:
            name = _text(cells[0])
        if not name or name.lower() in ("independent", ""):
            continue
        # Cell positions shift between listings, so classify by content.
        contact = ""
        price_cell = ""
        services = ""
        for cell in cells[1:]:
            text = _text(cell)
            if not contact and re.search(r"\d{3}[ .-]?\d{3}-\d{4}|UNICOM", text, re.I):
                contact = text
                contact_html = cell
            elif not price_cell and re.search(r"100LL|Jet A", text, re.I) and "$" in text:
                price_cell = cell
            else:
                # The services blurb shares its cell with the "More info and
                # photos of X" link; keep the blurb, drop the tail.
                candidate = text.split("More info")[0].strip(" .,")
                if len(candidate) > len(services):
                    services = candidate
        contact_html = locals().get("contact_html", "")
        phone = ""
        m = re.search(r"(\(?\d{3}\)?[ .-]?\d{3}-\d{4})", contact)
        if m:
            phone = m.group(1)
        unicom = ""
        m = re.search(r"UNICOM\s*([\d.]+)", contact, re.I)
        if m:
            unicom = m.group(1)
        website = ""
        m = re.search(r"window\.status='([^']+)'", contact_html or "")
        if m:
            website = m.group(1)
        prices, updated = _price_table(price_cell) if price_cell else ([], "")
        out.append({"name": name, "phone": phone, "unicom": unicom,
                    "website": website, "prices": prices,
                    "prices_updated": updated, "services": services[:300]})
    return out


def fetch_fbos(ident, refresh=False):
    AIRNAV_DIR.mkdir(parents=True, exist_ok=True)
    key = re.sub(r"[^A-Z0-9]", "_", ident.upper())
    path = AIRNAV_DIR / ("%s.json" % key)
    if path.exists() and not refresh:
        age = (time.time() - path.stat().st_mtime) / 3600
        if age < AIRNAV_TTL_HOURS:
            return json.loads(path.read_text())
    try:
        html = Http.get(AIRNAV_URL % urllib.parse.quote(ident), timeout=40, retries=2)
    except Exception as exc:
        if path.exists():
            stale = json.loads(path.read_text())
            stale["stale"] = True
            return stale
        return {"error": str(exc), "fbos": []}
    result = {"fbos": parse_airnav(html, ident),
              "source": AIRNAV_URL % ident,
              "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path.write_text(json.dumps(result))
    return result


def approx_local_time(lon):
    """Longitude-derived local time. Approximate: ignores DST and tz boundaries."""
    offset = round(lon / 15.0)
    return datetime.now(timezone.utc) + timedelta(hours=offset), offset


DAY_INDEX = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def open_at(hours, when):
    """Best-effort opening_hours check. Returns True / False / None (unknown)."""
    if not hours:
        return None
    text = hours.strip()
    if text in ("24/7", "Mo-Su 00:00-24:00"):
        return True
    minutes = when.hour * 60 + when.minute
    weekday = when.weekday()
    matched_any = False
    for rule in text.split(";"):
        rule = rule.strip()
        if not rule or "off" in rule.lower():
            continue
        days = range(7)
        m = re.match(r"^((?:[A-Za-z]{2}(?:-[A-Za-z]{2})?)(?:,[A-Za-z]{2}(?:-[A-Za-z]{2})?)*)\s+(.*)$", rule)
        if m:
            spec, rule = m.group(1), m.group(2)
            days = set()
            for part in spec.split(","):
                if "-" in part:
                    a, b = part.split("-", 1)
                    ai, bi = DAY_INDEX.get(a[:2].upper()), DAY_INDEX.get(b[:2].upper())
                    if ai is None or bi is None:
                        return None
                    i = ai
                    while True:
                        days.add(i)
                        if i == bi:
                            break
                        i = (i + 1) % 7
                else:
                    di = DAY_INDEX.get(part[:2].upper())
                    if di is None:
                        return None
                    days.add(di)
        spans = re.findall(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", rule)
        if not spans:
            continue
        matched_any = True
        if weekday not in days:
            continue
        for h1, m1, h2, m2 in spans:
            start = int(h1) * 60 + int(m1)
            end = int(h2) * 60 + int(m2)
            if end <= start:  # crosses midnight
                if minutes >= start or minutes < end:
                    return True
            elif start <= minutes < end:
                return True
    return False if matched_any else None


# --------------------------------------------------------------------------
# Notes
# --------------------------------------------------------------------------

def notes_path(ident):
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    return NOTES_DIR / ("%s.md" % re.sub(r"[^A-Za-z0-9]", "", ident.upper()))


def read_notes(ident):
    path = notes_path(ident)
    return path.read_text() if path.exists() else ""


def append_note(ident, text):
    path = notes_path(ident)
    stamp = date.today().isoformat()
    if not path.exists():
        path.write_text("# %s - personal notes\n\n- %s - %s\n" % (ident.upper(), stamp, text))
    else:
        body = path.read_text().rstrip("\n")
        path.write_text("%s\n- %s - %s\n" % (body, stamp, text))
    return path


# --------------------------------------------------------------------------
# Runway diagram
# --------------------------------------------------------------------------

def runway_svg(rec, runways, width=760, height=560, pad=54):
    """To-scale, true-north-up runway diagram from runway end coordinates."""
    segs = []
    for rwy in runways:
        ends = [e for e in rwy.get("ends", []) if e.get("lat") and e.get("lon")]
        if len(ends) == 2:
            segs.append((rwy, ends[0], ends[1]))
    if not segs:
        return None

    lat0 = sum((e["lat"] + f["lat"]) / 2 for _, e, f in segs) / len(segs)
    lon0 = sum((e["lon"] + f["lon"]) / 2 for _, e, f in segs) / len(segs)
    coslat = math.cos(math.radians(lat0))

    def project(lat, lon):
        return ((lon - lon0) * NM_PER_DEG * coslat, (lat - lat0) * NM_PER_DEG)

    pts = []
    for _, a, b in segs:
        pts.append(project(a["lat"], a["lon"]))
        pts.append(project(b["lat"], b["lon"]))
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    spanx = max(max(xs) - min(xs), 0.05)
    spany = max(max(ys) - min(ys), 0.05)
    scale = min((width - 2 * pad) / spanx, (height - 2 * pad) / spany)
    cx = (max(xs) + min(xs)) / 2
    cy = (max(ys) + min(ys)) / 2

    def screen(lat, lon):
        x, y = project(lat, lon)
        return (width / 2 + (x - cx) * scale, height / 2 - (y - cy) * scale)

    out = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %d %d" '
        'role="img" aria-label="Runway diagram for %s">' % (width, height, rec["id"]),
        '<style>'
        '.rwy{stroke:var(--rwy,#3d4450);stroke-linecap:butt}'
        '.lbl{fill:var(--ink,#1b1f27);font:600 13px ui-monospace,SFMono-Regular,Menlo,monospace}'
        '.sub{fill:var(--muted,#6b7280);font:11px ui-monospace,Menlo,monospace}'
        '</style>',
    ]
    for rwy, a, b in segs:
        x1, y1 = screen(a["lat"], a["lon"])
        x2, y2 = screen(b["lat"], b["lon"])
        w = _fnum(rwy.get("width")) or 100
        thickness = max(4.0, min(18.0, (w / FT_PER_NM) * scale))
        out.append('<line class="rwy" x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                   'stroke-width="%.1f"/>' % (x1, y1, x2, y2, thickness))
        out.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" stroke="var(--cl,#fff)" '
                   'stroke-width="1" stroke-dasharray="7 9" opacity=".65"/>' % (x1, y1, x2, y2))
        for (px, py), end, other in ((screen(a["lat"], a["lon"]), a, b),
                                     (screen(b["lat"], b["lon"]), b, a)):
            ox, oy = screen(other["lat"], other["lon"])
            dx, dy = px - ox, py - oy
            norm = math.hypot(dx, dy) or 1
            lx = px + dx / norm * 20
            ly = py + dy / norm * 20
            out.append('<text class="lbl" x="%.1f" y="%.1f" text-anchor="middle" '
                       'dominant-baseline="middle">%s</text>' % (lx, ly, end["id"]))
    lengths = ", ".join("%s %s x %s" % (r["id"], fmt_ft(r["length"]), fmt_ft(r["width"]))
                        for r, _, _ in segs)
    out.append('<text class="sub" x="%d" y="%d">N up, to scale &#183; %s</text>'
               % (pad // 2, height - 14, lengths[:110]))
    out.append("</svg>")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def cmd_resolve(args):
    conn = db_connect()
    rec = resolve(conn, args.query)
    if args.json:
        print(json.dumps(rec, indent=2, default=str))
        return
    if "error" in rec:
        die(rec["error"])
    if "ambiguous" in rec:
        for c in rec["ambiguous"]:
            print("%-5s %-5s %s, %s" % (c.get("id", ""), c.get("icao") or "",
                                        c["name"], c.get("city", "")))
        return
    print("%s  %s  %s, %s" % (rec["icao"] or rec["id"], rec["name"], rec["city"], rec["state"]))


def cmd_info(args):
    conn = db_connect()
    rec = need_airport(conn, args.airport)
    runways = get_runways(conn, rec)
    freqs = get_freqs(conn, rec)
    charts = get_charts(conn, rec)
    payload = {
        "airport": rec, "runways": runways, "frequencies": freqs, "charts": charts,
        "remarks": get_remarks(conn, rec), "contacts": get_contacts(conn, rec),
        "notes": read_notes(rec["id"]), "cycle": cycle_note(conn),
    }
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return

    faa = rec["faa"] or {}
    ident = rec["icao"] or rec["id"]
    head = "%s  %s" % (ident, rec["name"])
    if rec["id"] != ident:
        head += "  (FAA %s)" % rec["id"]
    print(head)
    print("%s, %s%s" % (rec["city"], rec["state_name"] or rec["state"],
                        "  |  " + SITE_TYPES.get(rec["site_type"], rec["site_type"] or "")
                        if rec["site_type"] else ""))
    print()

    bits = []
    if rec["elev"] is not None:
        bits.append("Elev %s" % fmt_ft(rec["elev"]))
    tpa = pattern_altitude(conn, rec)
    if tpa:
        bits.append("TPA %s" % tpa)
    if faa.get("MAG_VARN"):
        bits.append("Var %s%s" % (faa["MAG_VARN"], faa.get("MAG_HEMIS", "")))
    if rec["lat"] is not None:
        bits.append("%.5f, %.5f" % (rec["lat"], rec["lon"]))
    print(" · ".join(bits))

    ctaf = pick_freq(freqs, "CTAF")
    twr = pick_freq(freqs, "LCL")
    gnd = pick_freq(freqs, "GND")
    atis = pick_freq(freqs, "ATIS", "ASOS", "AWOS")
    line = []
    if ctaf:
        line.append("CTAF %s" % ctaf["freq"])
    if twr:
        label = "Twr %s" % twr["freq"]
        if twr["tower_hours"]:
            label += " (%s)" % re.sub(r"\s+", " ", twr["tower_hours"])
        line.append(label)
    if gnd:
        line.append("Gnd %s" % gnd["freq"])
    if atis:
        line.append("%s %s" % (atis["use"].split("/")[0] or "ATIS", atis["freq"]))
    if line:
        print(" · ".join(line))

    if runways:
        print()
        for rwy in runways:
            desc = "Rwy %-8s %s x %s  %s" % (
                rwy["id"], fmt_ft(rwy["length"]), fmt_ft(rwy["width"]),
                rwy.get("surface", ""))
            extras = []
            if rwy.get("lighting") and rwy["lighting"] not in ("none", ""):
                extras.append(rwy["lighting"])
            for end in rwy.get("ends", []):
                tags = []
                if end.get("ils"):
                    tags.append(end["ils"])
                if end.get("approach_lights"):
                    tags.append(end["approach_lights"])
                if end.get("vgsi") and end["vgsi"] != "none":
                    tags.append(end["vgsi"].split(" (")[0])
                if tags:
                    extras.append("%s: %s" % (end["id"], "/".join(tags)))
            print(desc + ("  [%s]" % "; ".join(extras) if extras else ""))

    print()
    svc = []
    fuels = decode_fuel(faa.get("FUEL_TYPES", ""))
    svc.append("Fuel: %s" % (", ".join(fuels) if fuels else "none listed"))
    if faa.get("LNDG_FEE_FLAG"):
        svc.append("Landing fee: %s" % ("yes" if faa["LNDG_FEE_FLAG"] == "Y" else "no"))
    if faa.get("OWNERSHIP_TYPE_CODE"):
        svc.append(OWNERSHIP.get(faa["OWNERSHIP_TYPE_CODE"], faa["OWNERSHIP_TYPE_CODE"]))
    if faa.get("FACILITY_USE_CODE"):
        svc.append(USE.get(faa["FACILITY_USE_CODE"], faa["FACILITY_USE_CODE"]))
    print(" · ".join(svc))

    extras = []
    if faa.get("OTHER_SERVICES"):
        extras.append("Services: " + ", ".join(
            OTHER_SERVICES.get(s, s.lower()) for s in faa["OTHER_SERVICES"].split(",")))
    stg = []
    if faa.get("TRNS_STRG_HGR_FLAG") == "Y":
        stg.append("hangar")
    if faa.get("TRNS_STRG_TIE_FLAG") == "Y":
        stg.append("tiedown")
    if stg:
        extras.append("Transient parking: " + ", ".join(stg))
    if faa.get("LGT_SKED"):
        extras.append("Field lighting: %s" % faa["LGT_SKED"])
    if faa.get("CUST_FLAG") == "Y":
        extras.append("Customs available")
    for line in extras:
        print(line)

    contacts = payload["contacts"]
    if contacts:
        print()
        for c in contacts[:3]:
            print("%-8s %s  %s" % (c["title"].title() + ":", c["name"], c["phone"] or ""))

    if charts["charts"] or charts["cs"]:
        print()
        apd = [c for c in charts["charts"] if c["code"] == "APD"]
        if apd:
            print("Airport diagram: %s" % apd[0]["url"])
        elif charts["cs"]:
            print("No FAA airport diagram published; Chart Supplement: %s" % charts["cs"])
        iaps = [c for c in charts["charts"] if c["code"] == "IAP"]
        if iaps:
            print("Approaches (%d): %s" % (len(iaps), ", ".join(c["name"] for c in iaps[:6])))
        print("All charts: apt.py charts %s" % rec["id"])

    notes = payload["notes"]
    if notes:
        print("\nYour notes:")
        for line in notes.strip().splitlines():
            print("  " + line)

    if rec["source"] != "faa":
        print("\nNon-US airport: FAA runway detail, frequencies, charts and TFRs are "
              "not available. Data from OurAirports.")
    print("\n%s · NOT FOR NAVIGATION - verify with official sources and NOTAMs."
          % cycle_note(conn))


def cmd_runways(args):
    conn = db_connect()
    rec = need_airport(conn, args.airport)
    runways = get_runways(conn, rec)
    if args.svg:
        svg = runway_svg(rec, runways)
        if not svg:
            die("no runway end coordinates available for %s" % rec["id"])
        print(svg)
        return
    if args.json:
        print(json.dumps({"airport": rec, "runways": runways}, indent=2, default=str))
        return
    if not runways:
        die("no runway data for %s" % rec["id"])
    print("%s  %s\n" % (rec["icao"] or rec["id"], rec["name"]))
    for rwy in runways:
        print("Runway %s   %s x %s   %s%s" % (
            rwy["id"], fmt_ft(rwy["length"]), fmt_ft(rwy["width"]),
            rwy.get("surface", ""),
            "   " + rwy["lighting"] if rwy.get("lighting") not in (None, "", "none") else ""))
        if rwy.get("weight_sw"):
            print("   Weight bearing: %s lbs single wheel%s" % (
                "{:,}".format(int(_fnum(rwy["weight_sw"]) or 0) * 1000)
                if _fnum(rwy["weight_sw"]) else rwy["weight_sw"],
                ", PCN %s" % rwy["pcn"] if rwy.get("pcn") else ""))
        for end in rwy.get("ends", []):
            parts = []
            if end.get("true_align"):
                parts.append("%s°T" % end["true_align"])
            if end.get("lda"):
                parts.append("LDA %s" % fmt_ft(end["lda"]))
            if end.get("tora"):
                parts.append("TORA %s" % fmt_ft(end["tora"]))
            if end.get("displaced_thr"):
                parts.append("displaced thr %s" % fmt_ft(end["displaced_thr"]))
            if end.get("ils"):
                parts.append(end["ils"])
            if end.get("approach_lights"):
                parts.append(end["approach_lights"])
            if end.get("vgsi") and end["vgsi"] != "none":
                parts.append(end["vgsi"])
            if end.get("right_traffic") == "Y":
                parts.append("RIGHT traffic")
            print("   %-4s %s" % (end["id"], "  ·  ".join(parts)))
            if end.get("obstruction"):
                print("        obstruction: %s%s%s" % (
                    end["obstruction"].lower(),
                    " %s' high" % end["obst_height"] if end.get("obst_height") else "",
                    " at %s' / %s:1 slope" % (end["obst_dist"], end["obst_slope"])
                    if end.get("obst_dist") else ""))
        print()
    print("%s · NOT FOR NAVIGATION." % cycle_note(conn))


def cmd_freqs(args):
    conn = db_connect()
    rec = need_airport(conn, args.airport)
    freqs = get_freqs(conn, rec)
    if args.json:
        print(json.dumps({"airport": rec, "frequencies": freqs}, indent=2, default=str))
        return
    if not freqs:
        die("no FAA frequency data for %s" % rec["id"])
    print("%s  %s\n" % (rec["icao"] or rec["id"], rec["name"]))
    seen = set()
    for f in freqs:
        if f["uhf"] and not args.all:
            continue
        key = (f["freq"], f["use"])
        if key in seen:
            continue
        seen.add(key)
        line = "%-9s %-22s %s" % (f["freq"], f["use"], f["fac_type"])
        print(line.rstrip())
        if f["tower_hours"]:
            print("          hours: %s" % re.sub(r"\s+", " ", f["tower_hours"]))
        if f["remark"]:
            print("          %s" % f["remark"])
    print("\n%s · NOT FOR NAVIGATION." % cycle_note(conn))


def cmd_charts(args):
    conn = db_connect()
    rec = need_airport(conn, args.airport)
    charts = get_charts(conn, rec)
    if args.json:
        print(json.dumps({"airport": rec, **charts}, indent=2, default=str))
        return
    if not charts["charts"]:
        msg = "no FAA terminal procedures published for %s" % rec["id"]
        if charts["cs"]:
            msg += "\nChart Supplement: %s" % charts["cs"]
        print(msg)
        return
    print("%s  %s   d-TPP cycle %s\n" % (rec["icao"] or rec["id"], rec["name"], charts["cycle"]))
    labels = {"APD": "Airport diagram", "HOT": "Hot spots", "IAP": "Approach",
              "DP": "Departure", "STR": "Arrival", "ODP": "Obstacle departure",
              "MIN": "Takeoff/alternate minimums", "LAH": "LAHSO", "DAU": "Diverse vector"}
    current = None
    for c in charts["charts"]:
        if args.type and c["code"] != args.type.upper():
            continue
        if c["code"] != current:
            current = c["code"]
            print("%s:" % labels.get(current, current))
        print("  %-42s %s" % (c["name"], c["url"]))
    if charts["cs"]:
        print("\nChart Supplement: %s" % charts["cs"])
    print("\nCharts expire with the cycle. NOT FOR NAVIGATION without verifying currency.")


def cmd_procedures(args):
    conn = db_connect()
    rec = need_airport(conn, args.airport)
    kind = args.kind
    if args.runway and not kind:
        kind = "approaches,airport_diagram"
    procs = get_procedures(conn, rec, runway=args.runway, kind=kind)

    if args.json:
        print(json.dumps({"airport": rec, "procedures": procs}, indent=2, default=str))
        return

    if rec["source"] != "faa":
        die("terminal procedures are FAA products; %s is outside FAA coverage. "
            "Try the national AIP for that country." % (rec["icao"] or rec["id"]))

    total = sum(len(procs[b]) for b in PROC_KINDS.values() if b in procs)
    if not total:
        print("%s  %s\n" % (rec["icao"] or rec["id"], rec["name"]))
        print("No FAA terminal procedures published - this is a VFR-only field.")
        if procs.get("cs"):
            print("Chart Supplement: %s" % procs["cs"])
        return

    print("%s  %s" % (rec["icao"] or rec["id"], rec["name"]))
    print("d-TPP cycle %s, effective %s through %s\n"
          % (procs["cycle"], procs.get("effective", "?"), procs.get("expires", "?")))

    diagram = procs.get("airport_diagram") or []
    if diagram:
        print("AIRPORT DIAGRAM")
        for d in diagram:
            print("  %s" % d["url"])
        print()

    approaches = procs.get("approaches") or []
    if approaches:
        print("APPROACHES (%d)" % len(approaches))
        by_runway = {}
        for a in approaches:
            key = a["runway"] or ("circling" if a["circling"] else "no runway")
            by_runway.setdefault(key, []).append(a)
        def rwy_order(r):
            return (r in ("circling", "no runway"),
                    int(re.sub(r"[^0-9]", "", r) or 99), r)
        for rwy in sorted(by_runway, key=rwy_order):
            label = {"circling": "Circling", "no runway": "All rwys"}.get(rwy, "Rwy %s" % rwy)
            for i, a in enumerate(by_runway[rwy]):
                print("  %-10s %-38s %s" % (label if i == 0 else "", a["name"], a["url"]))
                for extra in a["pages"]:
                    print("  %-10s   (cont.) %s" % ("", extra))
        print()

    for bucket, title in (("departures", "DEPARTURES (SIDs)"),
                          ("obstacle_departures", "OBSTACLE DEPARTURES"),
                          ("arrivals", "ARRIVALS (STARs)"),
                          ("diverse_vector", "DIVERSE VECTOR AREA")):
        items = procs.get(bucket) or []
        if not items:
            continue
        print("%s (%d)" % (title, len(items)))
        for item in items:
            print("  %-49s %s" % (item["name"], item["url"]))
            for extra in item["pages"]:
                print("    (cont.) %s" % extra)
        print()

    misc = (procs.get("minimums") or []) + (procs.get("hot_spots") or []) \
        + (procs.get("lahso") or []) + (procs.get("other") or [])
    if misc:
        print("ALSO PUBLISHED")
        for item in misc:
            print("  %-49s %s" % (item["name"], item["url"]))
        print()

    if procs.get("cs"):
        print("Chart Supplement: %s" % procs["cs"])
    print("\nCharts expire %s. NOT FOR NAVIGATION - verify currency against the FAA "
          "d-TPP before use." % procs.get("expires", "with the cycle"))


def cmd_wx(args):
    conn = db_connect()
    rec = need_airport(conn, args.airport)
    station = wx_ident(rec)
    metar = fetch_metar(station)
    taf = fetch_taf(station) if not args.no_taf else None
    twilight = fetch_twilight(rec["lat"], rec["lon"]) if rec["lat"] else None

    if args.json:
        print(json.dumps({"airport": rec, "station": station, "metar": metar,
                          "taf": taf, "twilight": twilight}, indent=2, default=str))
        return

    print("%s  %s\n" % (rec["icao"] or rec["id"], rec["name"]))
    if not metar:
        print("No METAR published for %s (many small fields have no weather station)." % station)
    elif "error" in metar:
        print("METAR unavailable: %s" % metar["error"])
    else:
        print(metar.get("rawOb", ""))
        cat = metar.get("fltCat", "")
        parts = []
        if cat:
            parts.append(cat)
        if metar.get("temp") is not None:
            parts.append("%.0fC/%.0fC" % (metar["temp"], metar.get("dewp") or 0))
        if metar.get("wdir") is not None:
            parts.append("wind %s@%s" % (metar["wdir"], metar.get("wspd")))
        if metar.get("altim"):
            parts.append("altimeter %.2f inHg" % (metar["altim"] / 33.8639))
        if metar.get("reportTime"):
            parts.append("obs %sZ" % str(metar["reportTime"])[11:16])
        print("  " + "  ·  ".join(parts))
        # Density altitude matters for GA performance planning.
        if metar.get("temp") is not None and metar.get("altim") and rec["elev"] is not None:
            pa = rec["elev"] + (29.92 - metar["altim"] / 33.8639) * 1000
            isa = 15 - 2 * (rec["elev"] / 1000.0)
            da = pa + 120 * (metar["temp"] - isa)
            print("  Density altitude ~%s (pressure alt ~%s)" % (fmt_ft(da), fmt_ft(pa)))

    if taf and "error" not in taf and taf.get("rawTAF"):
        print("\nTAF")
        raw = taf["rawTAF"]
        for chunk in re.split(r"\s+(?=FM\d|TEMPO|BECMG|PROB)", raw):
            print("  " + chunk.strip())

    if twilight:
        def hhmm(iso):
            return iso[11:16] + "Z"
        print("\nCivil twilight %s - %s  ·  sunrise %s  sunset %s (UTC)" % (
            hhmm(twilight["civil_twilight_begin"]), hhmm(twilight["civil_twilight_end"]),
            hhmm(twilight["sunrise"]), hhmm(twilight["sunset"])))

    print("\nNOT FOR NAVIGATION - obtain an official briefing before flight.")


def cmd_tfr(args):
    conn = db_connect()
    rec = need_airport(conn, args.airport) if args.airport else None
    data = fetch_tfrs()
    if isinstance(data, dict) and "error" in data:
        die("TFR list unavailable: %s" % data["error"])

    results = []
    state = None
    if rec and rec["source"] == "faa":
        state = rec["state"]
    for tfr in data:
        if state and tfr.get("state") and tfr["state"].upper() != state.upper():
            continue
        results.append(tfr)

    if rec and not args.no_geometry:
        refined = []
        for tfr in results[:12]:  # each detail page is a separate fetch
            pts = tfr_geometry(tfr.get("notam_id", ""))
            if pts:
                dist = min(haversine_nm(rec["lat"], rec["lon"], a, b) for a, b in pts)
                tfr["distance_nm"] = round(dist, 1)
                if dist > args.radius:
                    continue
            refined.append(tfr)
        results = refined

    if args.json:
        print(json.dumps({"airport": rec, "radius_nm": args.radius,
                          "tfrs": results}, indent=2, default=str))
        return

    if rec:
        print("Active TFRs near %s (%s, within %s nm where geometry is published)\n"
              % (rec["icao"] or rec["id"], state or "?", args.radius))
    if not results:
        print("None found.")
    for tfr in results:
        dist = "  ~%.0f nm" % tfr["distance_nm"] if "distance_nm" in tfr else ""
        print("%-9s %-18s %s%s" % (tfr.get("notam_id", ""), tfr.get("type", ""),
                                   tfr.get("description", ""), dist))
        print("          https://tfr.faa.gov/save_pages/detail_%s.html"
              % tfr.get("notam_id", "").replace("/", "_"))
    print("\nThis is a filtered view of the FAA TFR list and is NOT a substitute for an "
          "official preflight briefing. Check https://tfr.faa.gov and NOTAMs.")


def cmd_amenities(args):
    conn = db_connect()
    rec = need_airport(conn, args.airport)
    data = fetch_amenities(rec, refresh=args.refresh)
    pois = data.get("pois", [])

    if args.type:
        wanted = {t.strip().lower() for t in args.type.split(",")}
        pois = [p for p in pois if p["kind"] in wanted]
    if args.concourse:
        needle = args.concourse.lower()
        pois = [p for p in pois if needle in (p["terminal"] or "").lower()]
    if args.search:
        needle = args.search.lower()
        pois = [p for p in pois
                if needle in p["name"].lower() or needle in p["cuisine"].lower()
                or needle in (p["shop"] or "").lower() or needle in (p["amenity"] or "").lower()]

    warn = None
    if args.open_now:
        when, offset = approx_local_time(rec["lon"])
        warn = ("open-now uses UTC%+d derived from longitude; it ignores DST and "
                "timezone boundaries" % offset)
        pois = [p for p in pois if open_at(p["hours"], when)]

    pois.sort(key=lambda p: ((p["terminal"] or "~"), p["kind"], p["name"]))

    if args.json:
        print(json.dumps({"airport": rec, "terminals": data.get("terminals", []),
                          "pois": pois, "warning": warn,
                          "attribution": data.get("attribution")}, indent=2, default=str))
        return

    if data.get("error"):
        die("OpenStreetMap lookup failed: %s" % data["error"])
    print("%s  %s\n" % (rec["icao"] or rec["id"], rec["name"]))
    if data.get("stale"):
        print("(serving cached data; Overpass was unreachable)\n")
    if warn:
        print("note: %s\n" % warn)
    if not pois:
        print("Nothing matching in OpenStreetMap. Small fields are often unmapped - "
              "check the airport's own site, or ask me to search the web.")
        return

    current = object()
    for poi in pois:
        term = poi["terminal"] or "(location not mapped)"
        if term != current:
            current = term
            print("\n%s" % term)
            print("-" * len(term))
        label = poi["name"]
        detail = []
        if poi["kind"] == "lounge":
            detail.append("LOUNGE")
        if poi["cuisine"]:
            detail.append(poi["cuisine"].replace(";", ", "))
        elif poi["shop"]:
            detail.append(poi["shop"].replace("_", " "))
        elif poi["amenity"]:
            detail.append(poi["amenity"].replace("_", " "))
        if poi["level"]:
            detail.append("level %s" % poi["level"])
        if poi["hours"]:
            detail.append(poi["hours"])
        print("  %-34s %s" % (label[:34], "  ·  ".join(detail)))

    counts = {}
    for poi in data.get("pois", []):
        counts[poi["terminal"] or "(unmapped)"] = counts.get(poi["terminal"] or "(unmapped)", 0) + 1
    print("\n%d shown of %d mapped. By area: %s" % (
        len(pois), len(data.get("pois", [])),
        ", ".join("%s %d" % (k, v) for k, v in sorted(counts.items()))))

    notes = read_notes(rec["id"])
    if notes:
        print("\nYour notes:")
        for line in notes.strip().splitlines():
            print("  " + line)
    print("\nAmenity data (c) OpenStreetMap contributors, ODbL. Coverage varies and "
          "hours are often stale - confirm before relying on it.")


def cmd_notes(args):
    conn = db_connect()
    wants_list = args.action == "list" or (args.airport or "").lower() == "list"
    rec = need_airport(conn, args.airport) if (args.airport and not wants_list) else None
    ident = rec["id"] if rec else (args.airport or "").upper()

    if args.action == "list" or (args.airport or "").lower() == "list":
        args.action = "list"
    if args.action == "add":
        if not args.text:
            die("nothing to add")
        path = append_note(ident, " ".join(args.text))
        print("saved to %s" % path)
        return
    if args.action == "path":
        print(notes_path(ident))
        return
    if args.action == "list":
        NOTES_DIR.mkdir(parents=True, exist_ok=True)
        files = sorted(NOTES_DIR.glob("*.md"))
        if not files:
            print("no notes yet. add one:  apt.py notes ATL add \"Sky Club F is the good one\"")
        for f in files:
            first = ""
            for line in f.read_text().splitlines():
                if line.startswith("- "):
                    first = line[2:]
                    break
            print("%-6s %s" % (f.stem, first[:90]))
        return

    text = read_notes(ident)
    if args.json:
        print(json.dumps({"airport": ident, "notes": text}))
        return
    print(text if text else "no notes for %s" % ident)


def longest_runway(conn, arpt_id):
    row = conn.execute(
        "SELECT data FROM rwy WHERE arpt_id=?", (arpt_id,)).fetchall()
    best = 0
    surface = ""
    for r in row:
        d = json.loads(r["data"])
        n = _fnum(d.get("RWY_LEN")) or 0
        if n > best:
            best = n
            surface = decode_surface(d.get("SURFACE_TYPE_CODE", ""))
    return int(best), surface


def cmd_nearby(args):
    conn = db_connect()
    rec = need_airport(conn, args.airport)
    rows = conn.execute(
        "SELECT arpt_id, icao_id, name, city, state, lat, lon, elev, site_type, data "
        "FROM apt WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?",
        (rec["lat"] - args.radius / 60.0, rec["lat"] + args.radius / 60.0,
         rec["lon"] - args.radius / 45.0, rec["lon"] + args.radius / 45.0)).fetchall()
    out = []
    for r in rows:
        if r["arpt_id"] == rec["id"] or r["lat"] is None:
            continue
        if not args.all and r["site_type"] != "A":
            continue  # heliports and hospital pads crowd out real destinations
        faa = json.loads(r["data"])
        if not args.all and faa.get("FACILITY_USE_CODE") == "PR":
            continue
        dist = haversine_nm(rec["lat"], rec["lon"], r["lat"], r["lon"])
        if dist > args.radius:
            continue
        length, surface = longest_runway(conn, r["arpt_id"])
        if args.min_runway and length < args.min_runway:
            continue
        fuels = decode_fuel(faa.get("FUEL_TYPES", ""))
        if args.fuel and not fuels:
            continue
        out.append({"id": r["arpt_id"], "icao": r["icao_id"], "name": r["name"],
                    "city": r["city"], "state": r["state"], "elev": r["elev"],
                    "site_type": r["site_type"], "distance_nm": round(dist, 1),
                    "bearing": round(bearing(rec["lat"], rec["lon"], r["lat"], r["lon"])),
                    "longest_runway_ft": length, "surface": surface, "fuel": fuels})
    out.sort(key=lambda a: a["distance_nm"])
    out = out[:args.limit]
    if args.json:
        print(json.dumps({"from": rec, "airports": out}, indent=2, default=str))
        return
    print("Airports within %g nm of %s%s\n" % (
        args.radius, rec["icao"] or rec["id"],
        "  (public-use airports only; --all to include heliports and private fields)"
        if not args.all else ""))
    for a in out:
        print("%-5s %5.1f nm %03d°  %-28s %-18s %7s %-9s %s" % (
            a["id"], a["distance_nm"], a["bearing"], a["name"][:28],
            (a["city"] or "")[:18],
            "{:,}'".format(a["longest_runway_ft"]) if a["longest_runway_ft"] else "-",
            (a["surface"] or "").split(" (")[0][:9],
            ", ".join(a["fuel"]) or "no fuel"))
    if not out:
        print("Nothing matched. Loosen --radius, --min-runway, or pass --all.")


def bearing(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def cmd_fbo(args):
    conn = db_connect()
    rec = need_airport(conn, args.airport)
    data = fetch_fbos(rec["icao"] or rec["id"], refresh=args.refresh)
    if args.json:
        print(json.dumps({"airport": rec, **data}, indent=2, default=str))
        return
    if data.get("error"):
        die("AirNav unavailable: %s" % data["error"])
    fbos = data.get("fbos", [])
    print("%s  %s\n" % (rec["icao"] or rec["id"], title_case(rec["name"])))
    if not fbos:
        print("No FBOs listed on AirNav for this field.")
    for f in fbos:
        head = f["name"]
        if f["phone"]:
            head += "   " + f["phone"]
        print(head)
        if f["unicom"]:
            print("   UNICOM %s" % f["unicom"])
        for p in f["prices"]:
            print("   %-7s %-11s $%s%s" % (p["fuel"], p["service"], p["price"],
                                           "  (%s)" % f["prices_updated"]
                                           if f["prices_updated"] else ""))
        if f["services"]:
            print("   %s" % f["services"][:100])
        print()
    print("Source: %s  ·  cached 24h" % data.get("source", "airnav.com"))


def cmd_search(args):
    """Type-ahead over identifier, name, city and state, ranked by significance."""
    conn = db_connect()
    raw = (args.query or "").strip()
    if not raw:
        print(json.dumps({"results": []}))
        return

    text, state = split_state(conn, raw)
    q = text.upper()
    like = q + "%"
    contains = "%" + q + "%"
    seen = set()
    results = []

    def push(row, source):
        if source == "faa":
            keys = {row["arpt_id"], row["icao_id"] or row["arpt_id"]}
        else:
            keys = {row["ident"], row["icao"] or "", row["local_code"] or ""}
        if keys & seen:
            return
        seen.update(k for k in keys if k)
        if source == "faa":
            results.append({
                "id": row["arpt_id"], "icao": row["icao_id"] or "",
                "ident": row["icao_id"] or row["arpt_id"],
                "name": title_case(row["name"]), "city": title_case(row["city"]),
                "state": row["state"], "elev": row["elev"],
                "site_type": SITE_TYPES.get(row["site_type"], ""), "us": True})
        else:
            results.append({
                "id": row["ident"], "icao": row["icao"] or row["ident"],
                "ident": row["icao"] or row["ident"],
                "iata": row["iata"] or "", "name": row["name"],
                "city": row["municipality"], "state": row["region"],
                "elev": row["elev"], "site_type": row["type"], "us": False})

    state_clause = " AND state = ?" if state else ""
    state_arg = (state,) if state else ()

    # A bare state ("vermont", "VT") means "show me that state's airports".
    if state and not q:
        for row in conn.execute(
                "SELECT * FROM apt WHERE state = ? ORDER BY rank DESC, name LIMIT ?",
                (state, args.limit)):
            push(row, "faa")
        print(json.dumps({"results": results[:args.limit], "state": state}, default=str))
        return

    passes = [
        ("SELECT * FROM apt WHERE (arpt_id=? OR icao_id=?)" + state_clause
         + " ORDER BY rank DESC", (q, q) + state_arg),
        ("SELECT * FROM apt WHERE (arpt_id LIKE ? OR icao_id LIKE ?)" + state_clause
         + " ORDER BY rank DESC, arpt_id LIMIT 40", (like, like) + state_arg),
        ("SELECT * FROM apt WHERE (city LIKE ? OR name LIKE ?)" + state_clause
         + " ORDER BY rank DESC, name LIMIT 60", (like, like) + state_arg),
        ("SELECT * FROM apt WHERE (city LIKE ? OR name LIKE ?)" + state_clause
         + " ORDER BY rank DESC, name LIMIT 60", (contains, contains) + state_arg),
    ]
    for sql, params in passes:
        for row in conn.execute(sql, params):
            push(row, "faa")
        if len(results) >= args.limit:
            break

    if len(results) < args.limit and not state:
        for sql, params in (
                ("SELECT * FROM oa_apt WHERE ident=? OR icao=? OR iata=?", (q, q, q)),
                ("SELECT * FROM oa_apt WHERE (ident LIKE ? OR icao LIKE ? OR iata LIKE ?) "
                 "AND type != 'closed' ORDER BY ident LIMIT 30", (like, like, like)),
                ("SELECT * FROM oa_apt WHERE (name LIKE ? OR municipality LIKE ?) "
                 "AND type != 'closed' ORDER BY name LIMIT 30", (contains, contains))):
            for row in conn.execute(sql, params):
                push(row, "oa")

    print(json.dumps({"results": results[:args.limit],
                      "state": state, "text": text}, default=str))


def cmd_recents(args):
    conn = db_connect()
    entries = read_recents()

    def decorate(items):
        out = []
        for e in items:
            rec = resolve(conn, e["id"])
            if "name" not in rec:
                continue
            out.append({**e, "name": title_case(rec["name"]),
                        "city": title_case(rec["city"]), "state": rec["state"]})
        return out

    if args.action == "touch":
        rec = need_airport(conn, args.airport)
        touch_recent(rec)
        entries = read_recents()

    if args.action in ("pin", "unpin", "remove"):
        rec = need_airport(conn, args.airport)
        if args.action == "remove":
            entries = [e for e in entries if e["id"] != rec["id"]]
        else:
            found = False
            for e in entries:
                if e["id"] == rec["id"]:
                    e["pinned"] = args.action == "pin"
                    found = True
            if not found and args.action == "pin":
                entries.insert(0, {"id": rec["id"], "ident": rec["icao"] or rec["id"],
                                   "pinned": True,
                                   "last": datetime.now(timezone.utc).isoformat(
                                       timespec="seconds")})
        entries = [e for e in entries if e.get("pinned")] + \
                  [e for e in entries if not e.get("pinned")]
        write_recents(entries)

    if args.action == "clear":
        write_recents([e for e in entries if e.get("pinned")])
        entries = read_recents()

    listed = decorate(entries)
    if args.json:
        print(json.dumps({"recents": listed}))
        return
    if not listed:
        print("no recent airports yet - open one with:  apt.py panel KPOU")
    for e in listed:
        print("%s %-5s %-32s %s" % ("*" if e.get("pinned") else " ", e["ident"],
                                    e["name"][:32], e.get("last", "")[:10]))


def cmd_panel(args):
    """One payload for the desktop panel. Everything local plus weather;
    amenities and FBO stay out because they are slow network calls the panel
    fetches lazily when their tab is opened."""
    conn = db_connect()
    rec = need_airport(conn, args.airport)
    if not args.no_record:
        touch_recent(rec)

    runways = get_runways(conn, rec)
    freqs = get_freqs(conn, rec)
    faa = rec["faa"] or {}
    station = wx_ident(rec)
    metar = None if args.no_live else fetch_metar_cached(station)
    taf = None if args.no_live else fetch_taf_cached(station)
    weather = humanize_weather(metar, taf, rec["elev"])
    if not args.no_live and rec["lat"] is not None:
        twilight = fetch_twilight(rec["lat"], rec["lon"])
        if twilight:
            weather["twilight"] = "%sZ - %sZ" % (twilight["civil_twilight_begin"][11:16],
                                                 twilight["civil_twilight_end"][11:16])
            weather["sunrise"] = twilight["sunrise"][11:16] + "Z"
            weather["sunset"] = twilight["sunset"][11:16] + "Z"
    field_freqs, approach_freqs, other_freqs = split_frequencies(freqs)

    longest = runways[0] if runways else None
    ctaf = pick_freq(freqs, "CTAF")
    twr = pick_freq(freqs, "LCL")
    atis = pick_freq(freqs, "ATIS", "ASOS", "AWOS")
    attended = get_attendance(conn, rec)
    remarks = get_remarks(conn, rec)

    density = weather.get("density_alt")

    where = ", ".join(x for x in (title_case(rec["city"]), rec["state"]) if x)
    if faa.get("DIST_CITY_TO_AIRPORT") and faa.get("DIRECTION_CODE"):
        where += "  ·  %s mi %s" % (faa["DIST_CITY_TO_AIRPORT"], faa["DIRECTION_CODE"])

    procedures = get_procedures(conn, rec)
    diagram = (procedures.get("airport_diagram") or [{}])[0].get("url", "")
    airspace = get_airspace(conn, rec)
    towered = bool(twr) or (faa.get("TWR_TYPE_CODE", "").startswith("ATCT"))
    tower_hours = re.sub(r"\s+", " ", twr["tower_hours"]) if twr and twr["tower_hours"] else ""
    if re.fullmatch(r"24|24 HR|CONTINUOUS", tower_hours.strip(), re.I):
        tower_hours = "24 hours"

    payload = {
        "header": {
            "ident": rec["icao"] or rec["id"],
            "faa_id": rec["id"],
            "name": title_case(rec["name"]),
            "where": where,
            "elev": rec["elev"],
            "site_type": SITE_TYPES.get(rec["site_type"], rec["site_type"] or ""),
            "category": weather.get("category", ""),
            "conditions": weather.get("summary", ""),
            "diagram": diagram,
            "us": rec["source"] == "faa",
        },
        # The front page answers "what is this airport and can I use it",
        # for a traveler and a pilot alike. No jargon, no performance numbers.
        "summary": {
            "longest_runway": ("%s  %s × %s" % (
                longest["id"], fmt_ft(longest["length"]), fmt_ft(longest["width"]))
            ) if longest else "",
            "surface": (longest.get("surface", "") if longest else ""),
            "runway_count": len(runways),
            "airspace": airspace.get("label", ""),
            "airspace_hours": airspace.get("hours", ""),
            "towered": towered,
            "tower_hours": tower_hours,
            "fuel": decode_fuel(faa.get("FUEL_TYPES", "")),
            "landing_fee": faa.get("LNDG_FEE_FLAG", ""),
            "attended": attended,
            "weather": weather.get("summary", ""),
        },
        "weather": weather,
        "tfr": (tfrs_for_state(rec["state"]) if not args.no_live
                else {"available": False, "tfrs": []}),
        "runways": {
            "runways": runways,
            "pattern_altitude": pattern_altitude(conn, rec),
            "diagram": diagram,
        },
        "procedures": procedures,
        "frequencies": {
            "field": field_freqs,
            "approach": approach_freqs,
            "other_count": len(other_freqs),
        },
        "ground": {
            "attended": attended,
            "fuel": decode_fuel(faa.get("FUEL_TYPES", "")),
            "landing_fee": faa.get("LNDG_FEE_FLAG", ""),
            "hangar": faa.get("TRNS_STRG_HGR_FLAG", "") == "Y",
            "tiedown": faa.get("TRNS_STRG_TIE_FLAG", "") == "Y",
            "customs": faa.get("CUST_FLAG", "") == "Y",
            "services": [OTHER_SERVICES.get(x, x.lower())
                         for x in (faa.get("OTHER_SERVICES") or "").split(",") if x],
            "contacts": [{**c, "name": title_case(c["name"]),
                          "title": title_case(c["title"])}
                         for c in get_contacts(conn, rec)],
            "fbo_remarks": [r for r in remarks if "FBO" in r.upper()],
        },
        "remarks": remarks,
        "notes": read_notes(rec["id"]),
        "notes_path": str(notes_path(rec["id"])),
        "links": official_links(rec, diagram),
        "cycle": cycle_note(conn),
    }
    print(json.dumps(payload, default=str))


def cmd_brief(args):
    """Everything a pilot or traveler needs, in one JSON blob for the skill to format."""
    conn = db_connect()
    rec = need_airport(conn, args.airport)
    payload = {
        "airport": rec,
        "cycle": cycle_note(conn),
        "runways": get_runways(conn, rec),
        "frequencies": get_freqs(conn, rec),
        "pattern_altitude": pattern_altitude(conn, rec),
        "charts": get_charts(conn, rec),
        "procedures": get_procedures(conn, rec),
        "remarks": get_remarks(conn, rec),
        "contacts": get_contacts(conn, rec),
        "notes": read_notes(rec["id"]),
        "links": official_links(rec),
    }
    if not args.no_live:
        station = wx_ident(rec)
        payload["metar"] = fetch_metar(station)
        payload["taf"] = fetch_taf(station)
        if rec["lat"] is not None:
            payload["twilight"] = fetch_twilight(rec["lat"], rec["lon"])
    if args.amenities:
        payload["amenities"] = fetch_amenities(rec)
    print(json.dumps(payload, indent=2, default=str))


def official_links(rec, diagram_url=""):
    ident = rec["icao"] or rec["id"]
    links = {
        "airnav": "https://www.airnav.com/airport/%s" % ident,
        "faa_nfdc": "https://nfdc.faa.gov/nfdcApps/services/ajv5/airportDisplay.jsp"
                    "?airportId=%s" % rec["id"],
        "notams": "https://notams.aim.faa.gov/notamSearch/nsapp.html#/",
        "tfr": "https://tfr.faa.gov/tfr3/?page=list",
        "weather": "https://aviationweather.gov/data/metar/?ids=%s" % ident,
        "skyvector": "https://skyvector.com/airport/%s" % rec["id"],
        "liveatc": "https://www.liveatc.net/search/?icao=%s" % ident,
    }
    if rec["lat"] is not None and rec["lon"] is not None:
        links["directions"] = ("https://www.google.com/maps/dir/?api=1&destination=%.5f,%.5f"
                               % (rec["lat"], rec["lon"]))
        links["map"] = ("https://www.openstreetmap.org/?mlat=%.5f&mlon=%.5f#map=14/%.5f/%.5f"
                        % (rec["lat"], rec["lon"], rec["lat"], rec["lon"]))
    if diagram_url:
        links["diagram"] = diagram_url
    if rec["source"] != "faa":
        for key in ("faa_nfdc", "notams", "tfr"):
            links.pop(key, None)
    return links


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(
        prog="apt.py", description="Airport data for pilots and travelers. NOT FOR NAVIGATION.")
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("cache", help="build or inspect the local data cache")
    sp.add_argument("action", choices=["update", "status"])
    sp.set_defaults(func=cmd_cache)

    sp = sub.add_parser("resolve", help="resolve an identifier or name")
    sp.add_argument("query")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_resolve)

    sp = sub.add_parser("info", help="airport summary")
    sp.add_argument("airport")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("runways", help="runway detail")
    sp.add_argument("airport")
    sp.add_argument("--svg", action="store_true", help="emit a to-scale SVG diagram")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_runways)

    sp = sub.add_parser("freqs", help="frequencies")
    sp.add_argument("airport")
    sp.add_argument("--all", action="store_true", help="include UHF/military")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_freqs)

    sp = sub.add_parser("charts", help="FAA terminal procedures and Chart Supplement")
    sp.add_argument("airport")
    sp.add_argument("--type", help="filter by code: APD, IAP, DP, STR, HOT, MIN")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_charts)

    sp = sub.add_parser("procedures", aliases=["procs"],
                        help="instrument procedures: approaches, SIDs, STARs, ODPs")
    sp.add_argument("airport")
    sp.add_argument("--runway", help="only approaches serving this runway, e.g. 24 or 08L")
    sp.add_argument("--kind", help="approaches,departures,arrivals,obstacle_departures")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_procedures)

    sp = sub.add_parser("wx", help="METAR, TAF, density altitude, twilight")
    sp.add_argument("airport")
    sp.add_argument("--no-taf", action="store_true")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_wx)

    sp = sub.add_parser("tfr", help="active TFRs near an airport")
    sp.add_argument("airport", nargs="?")
    sp.add_argument("--radius", type=float, default=100.0, help="nautical miles")
    sp.add_argument("--no-geometry", action="store_true",
                    help="skip per-TFR detail fetches (faster, state filter only)")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_tfr)

    sp = sub.add_parser("amenities", help="food, shops and lounges by terminal/concourse")
    sp.add_argument("airport")
    sp.add_argument("--type", help="food,lounge,shop,service")
    sp.add_argument("--concourse", help="filter by terminal or concourse name")
    sp.add_argument("--search", help="name or cuisine substring")
    sp.add_argument("--open-now", action="store_true", help="approximate local time filter")
    sp.add_argument("--refresh", action="store_true", help="bypass the 7-day cache")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_amenities)

    sp = sub.add_parser("notes", help="your personal notes on an airport")
    sp.add_argument("airport", nargs="?")
    sp.add_argument("action", nargs="?", default="show",
                    choices=["show", "add", "path", "list"])
    sp.add_argument("text", nargs="*")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_notes)

    sp = sub.add_parser("nearby", help="nearby airports")
    sp.add_argument("airport")
    sp.add_argument("--radius", type=float, default=50.0)
    sp.add_argument("--limit", type=int, default=25)
    sp.add_argument("--min-runway", type=int, default=0, help="minimum runway length, ft")
    sp.add_argument("--fuel", action="store_true", help="only fields that sell fuel")
    sp.add_argument("--all", action="store_true",
                    help="include heliports, seaplane bases and private fields")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_nearby)

    sp = sub.add_parser("panel", help="one JSON payload for the desktop panel")
    sp.add_argument("airport")
    sp.add_argument("--no-live", action="store_true")
    sp.add_argument("--no-record", action="store_true",
                    help="do not add this airport to recents")
    sp.set_defaults(func=cmd_panel)

    sp = sub.add_parser("recents", help="recently viewed airports, with pinning")
    sp.add_argument("action", nargs="?", default="list",
                    choices=["list", "touch", "pin", "unpin", "remove", "clear"])
    sp.add_argument("airport", nargs="?")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_recents)

    sp = sub.add_parser("fbo", help="FBOs and fuel prices from AirNav")
    sp.add_argument("airport")
    sp.add_argument("--refresh", action="store_true", help="bypass the 24h cache")
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_fbo)

    sp = sub.add_parser("search", help="type-ahead airport search, JSON out")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=20)
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("brief", help="everything as JSON, for the skill to format")
    sp.add_argument("airport")
    sp.add_argument("--amenities", action="store_true")
    sp.add_argument("--no-live", action="store_true")
    sp.set_defaults(func=cmd_brief)

    args = p.parse_args(argv)
    try:
        args.func(args)
    except BrokenPipeError:
        pass
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
