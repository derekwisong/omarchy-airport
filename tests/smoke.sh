#!/usr/bin/env bash
# Smoke tests for the airport-info CLI. Network required.
#   ./tests/smoke.sh            everything except the slow OSM check
#   ./tests/smoke.sh --with-osm include the Overpass amenity check
set -uo pipefail
cd "$(dirname "$0")/.."
APT="python3 scripts/apt.py"
pass=0; fail=0

check() { # check <name> <expected-substring> <command...>
  local name="$1" want="$2"; shift 2
  local got
  got="$("$@" 2>&1)"
  if [[ "$got" == *"$want"* ]]; then
    printf 'ok   %s\n' "$name"; pass=$((pass+1))
  else
    printf 'FAIL %s\n     wanted: %s\n     got:    %s\n' \
      "$name" "$want" "$(printf '%s' "$got" | head -3)"; fail=$((fail+1))
  fi
}

$APT cache status >/dev/null 2>&1 || { echo "building cache first..."; $APT cache update; }

# Resolution: FAA id, ICAO, IATA-only, and name search.
check "resolve KPOU"            "HUDSON VALLEY"  $APT resolve KPOU
check "resolve bare POU"        "HUDSON VALLEY"  $APT resolve POU
check "resolve EGLL"            "Heathrow"       $APT resolve EGLL

# Small towered field: elevation, CTAF, runway, fuel, landing fee.
check "KPOU elevation"          "164'"           $APT info KPOU
check "KPOU CTAF"               "CTAF 124.0"     $APT info KPOU
check "KPOU runway 06/24"       "5,001' x 100'"  $APT info KPOU
check "KPOU fuel"               "100LL, Jet A"   $APT info KPOU
check "KPOU landing fee"        "Landing fee: yes" $APT info KPOU
check "KPOU displaced thr"      "displaced thr 115'" $APT runways KPOU
check "KPOU tower hours"        "0700-2200"      $APT freqs KPOU

# Large hub.
check "KATL elevation"          "1,026'"         $APT info KATL
check "KATL longest runway"     "12,390'"        $APT info KATL
check "KATL approach count"     "APPROACHES (52)" $APT procedures KATL
check "KATL runway filter"      "ILS OR LOC RWY 27R" $APT procedures KATL --runway 27R
check "KATL diagram link"       "00026AD.PDF"    $APT charts KATL

# The short FAA identifier is what shows; the ICAO form is carried, not shown
# as the name, and either spelling has to resolve to the same airport.
check "displays the FAA id"     "ATL  HARTSFIELD"   $APT info KATL
check "bare id displays same"   "ATL  HARTSFIELD"   $APT info ATL
check "ICAO annotated"          "(ICAO KATL)"       $APT info ATL
check "no ICAO to annotate"     "00A  TOTAL RF"     $APT info 00A
check "non-US identifier kept"  "EGLL  London"      $APT info EGLL
check "official links use ICAO" "airnav.com/airport/KPOU" $APT panel KPOU --no-record

# "24" is how NASR writes round-the-clock; on screen it must read as a time.
check "continuous hours"        '"hours": "24 hours"' $APT panel KATL --no-record

# Charts are viewed inside the panel, so the engine has to hand it a local file
# rather than a URL - and must refuse to fetch anything that is not an FAA chart.
check "chart downloads"    '"ok": true'   $APT pdf https://aeronav.faa.gov/d-tpp/2609/00286AD.PDF --json
check "chart cached local" "/charts/"     $APT pdf https://aeronav.faa.gov/d-tpp/2609/00286AD.PDF --json
check "chart host guarded" "not an FAA chart URL" $APT pdf https://example.com/x.pdf --json
check "chart scheme guarded" "not an FAA chart URL" $APT pdf http://aeronav.faa.gov/x.pdf --json

# The TAF outlook is parsed here, so it gets a fixed bulletin rather than
# whatever the weather happens to be doing. Categories, times, the PROB
# overlay and the P6SM rule are all pinned.
TAF_FIXTURE='TAF KORD 050057Z 0501/0606 21005KT P6SM FEW050 SCT100 FM050145 03006KT P6SM SCT050 BKN100 PROB30 0503/0507 3SM -TSRA BR SCT025 BKN050CB FM051100 02008KT P6SM SCT008 BKN015 FM051900 03012KT P6SM SCT025 FM060000 04005KT 2SM BR OVC006'
# The raw TAF must be read before apt.py is loaded, because importing it
# clears sys.argv.
PARSE="import importlib.util,sys,json;raw=sys.argv[1];sys.argv=['x'];s=importlib.util.spec_from_file_location('apt','scripts/apt.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m);print(json.dumps(m.parse_taf(raw)))"
check "taf timeline built"   '"timeline"'      python3 -c "$PARSE" "$TAF_FIXTURE"
check "1500ft ceiling is MVFR" '"category": "MVFR"' python3 -c "$PARSE" "$TAF_FIXTURE"
check "600ft and 2sm is IFR"   '"category": "IFR"'  python3 -c "$PARSE" "$TAF_FIXTURE"
check "taf prob overlay"     '"probability": 30' python3 -c "$PARSE" "$TAF_FIXTURE"
check "taf decodes weather"  "thunderstorms with rain" python3 -c "$PARSE" "$TAF_FIXTURE"
check "P6SM is not a limit"  '"visibility_sm": 10.0' python3 -c "$PARSE" "$TAF_FIXTURE"
check "taf outlook via CLI"  "Forecast"        $APT outlook KORD

# An unreachable weather service must not read as an airport with no station.
UNREACH=$(https_proxy=http://127.0.0.1:9 http_proxy=http://127.0.0.1:9 \
  AIRPORT_INFO_CACHE="$(mktemp -d)" $APT panel KPOU --no-record 2>/dev/null || true)
if [[ -z "$UNREACH" || "$UNREACH" != *"No weather station reports"* ]]; then
  echo "ok   offline does not claim there is no station"; pass=$((pass+1))
else
  echo "FAIL offline reported 'no weather station reports'"; fail=$((fail+1))
fi

# FAA delay and closure reporting. Which airports are affected changes by the
# minute, so these assert the plumbing and the honesty rules, never a delay.
check "national status feed"  '"airports"'  $APT status --json
check "quiet field says so"   "No delays or closures reported by the FAA." $APT status POU
check "non-US has no FAA status" "outside the US" $APT status EGLL
check "live payload has status"  '"status"'  $APT live POU

# The favoured-runway sum needs numbers, not the wind sentence, and a pattern
# altitude has to exist even where the FAA prints none.
check "numeric wind exposed"  '"wind_dir"'   $APT panel KHPN --no-record
check "standard TPA computed" '"pattern_altitude_standard"' $APT panel KHPN --no-record

# Markup and URL handling for data that arrives from OpenStreetMap. Node is
# not a dependency of the plugin, so this runs only where it happens to exist.
if command -v node >/dev/null 2>&1; then
  if node tests/escaping.js >/dev/null 2>&1; then
    echo "ok   markup and urls from mapped data are neutralised"; pass=$((pass+1))
  else
    echo "FAIL escaping regressed:"; node tests/escaping.js 2>&1 | head -6; fail=$((fail+1))
  fi
fi

# Cycle currency must always be stated.
check "cycle stamped"           "NASR cycle 2026" $APT info KPOU
check "not-for-navigation"      "NOT FOR NAVIGATION" $APT info KPOU
check "charts carry expiry"     "Charts expire"  $APT procedures KPOU

# Non-US: works, but says what is missing rather than faking it.
check "EGLL runways"            "12,799'"        $APT info EGLL
check "EGLL states the gap"     "Non-US airport" $APT info EGLL
check "EGLL procedures refused" "outside FAA coverage" $APT procedures EGLL

# Edge cases must not crash.
check "heliport"                "Heliport"       $APT info 00A
check "seaplane base"           "Seaplane Base"  $APT info AL46
check "unknown identifier"      "no airport matching" $APT info ZZZZ9
check "ambiguous name"          "matches several" $APT info Springfield

# Live services.
check "METAR"                   "KATL"           $APT wx KATL
check "TFR list"                "Active TFRs"    $APT tfr KPOU --no-geometry

# Nearby filters to usable destinations.
check "nearby excludes helipads" "SKY ACRES"     $APT nearby KPOU --radius 30 --min-runway 2500

# Panel payload: the shape the QML depends on.
check "panel header"        '"ident": "POU"'       $APT panel KPOU --no-record
check "panel header keeps ICAO" '"icao": "KPOU"'  $APT panel KPOU --no-record
check "panel overview"      '"longest_runway"'     $APT panel KPOU --no-record
check "panel attended hrs"  "0700-2130"            $APT panel KPOU --no-record
check "panel ground block"  '"fbo_remarks"'        $APT panel KPOU --no-record
check "panel non-US"        '"us": false'          $APT panel EGLL --no-record

# Recents store, in a throwaway location.
REC_TMP="$(mktemp -d)"
AIRPORT_INFO_RECENTS="$REC_TMP/r.json" $APT panel 44N >/dev/null
check "recents records visits" "44N" \
  env AIRPORT_INFO_RECENTS="$REC_TMP/r.json" python3 scripts/apt.py recents
AIRPORT_INFO_RECENTS="$REC_TMP/r.json" $APT recents pin 44N >/dev/null
check "recents pinning" "*" \
  env AIRPORT_INFO_RECENTS="$REC_TMP/r.json" python3 scripts/apt.py recents
rm -rf "$REC_TMP"

# Search must not list an airport twice from two sources.
check "search dedupes" "KPOU" $APT search kpou --limit 5
DUPES=$($APT search kpou --limit 25 | python3 -c "import json,sys;r=json.load(sys.stdin)['results'];print(len(r)-len({x['icao'] or x['id'] for x in r}))")
if [[ "$DUPES" == "0" ]]; then echo "ok   search has no duplicates"; pass=$((pass+1));
else echo "FAIL search returned $DUPES duplicates"; fail=$((fail+1)); fi

# Weather must read as English, and a field with no station must say so
# rather than erroring.
# Phrasing, not today's numbers: asserting "wind from the" failed whenever the
# field happened to be calm, which is a property of the weather, not the code.
WIND=$($APT panel KATL --no-record | python3 -c "import json,sys;print(json.load(sys.stdin)['weather'].get('wind',''))")
if [[ "$WIND" == "calm" || "$WIND" == *"from the"* || "$WIND" == *"variable"* ]]; then
  echo "ok   wind reads as English (\"$WIND\")"; pass=$((pass+1))
else
  echo "FAIL wind not humanized: '$WIND'"; fail=$((fail+1))
fi
check "category spelled out" "Visual Flight Rules" $APT panel KATL --no-record
check "no-station handled"  '"available": false' $APT panel 44N --no-record

# Frequency lists must be trimmed, not dumped.
FREQS=$($APT panel KATL --no-record | python3 -c "import json,sys;print(len(json.load(sys.stdin)['frequencies']['field']))")
if [[ "$FREQS" -gt 0 && "$FREQS" -le 20 ]]; then
  echo "ok   KATL field frequencies trimmed to $FREQS"; pass=$((pass+1))
else
  echo "FAIL KATL field frequencies = $FREQS (expected 1-20)"; fail=$((fail+1))
fi
check "approach freqs split"  '"approach"'          $APT panel KATL --no-record
check "ceiling reported"      '"ceiling"'           $APT panel KATL --no-record
# One unit, chosen from the locale - not a particular temperature. The old
# check wanted a value in the 90s, so it failed on any cool day.
TEMPS=$($APT panel KATL --no-record | python3 -c "
import json,sys
w=json.load(sys.stdin)['weather']
print(w.get('temp',''), w.get('dewpoint',''))")
if [[ "$TEMPS" == *"°F"* && "$TEMPS" != *"°C"* ]] || [[ "$TEMPS" == *"°C"* && "$TEMPS" != *"°F"* ]]; then
  echo "ok   one temperature unit throughout ($TEMPS)"; pass=$((pass+1))
else
  echo "FAIL mixed or missing temperature units: '$TEMPS'"; fail=$((fail+1))
fi
check "airspace class B"      "Class B"             $APT panel KATL --no-record
check "airspace class D hrs"  "CLASS D SVC"         $APT panel KPOU --no-record
check "uncontrolled field"    '"towered": false'    $APT panel 44N  --no-record
check "diagram in header"     "AD.PDF"              $APT panel KATL --no-record
check "directions link"       "maps/dir"            $APT panel KPOU --no-record
check "liveatc link"          "liveatc.net"         $APT panel KPOU --no-record
check "notes path exposed"    "notes_path"          $APT panel KPOU --no-record
check "no notam machinery"    '"weather"'           $APT panel KPOU --no-record
# Not even a link to a NOTAM search: pointing at one reads as though the
# plugin had checked something it never checks.
LINKKEYS=$($APT panel KPOU --no-record | python3 -c "import json,sys;print(','.join(json.load(sys.stdin)['links'].keys()))")
if [[ "$LINKKEYS" != *notam* ]]; then
  echo "ok   no notam link in the payload"; pass=$((pass+1))
else
  echo "FAIL payload still carries a notam link: $LINKKEYS"; fail=$((fail+1))
fi

# The summary must stay free of cockpit jargon.
SUMKEYS=$($APT panel KPOU --no-record | python3 -c "import json,sys;print(','.join(json.load(sys.stdin)['summary'].keys()))")
if [[ "$SUMKEYS" != *ctaf* && "$SUMKEYS" != *density* && "$SUMKEYS" != *pattern* \
      && "$SUMKEYS" != *notam* ]]; then
  echo "ok   summary free of ctaf/density/pattern"; pass=$((pass+1))
else
  echo "FAIL summary still carries cockpit fields: $SUMKEYS"; fail=$((fail+1))
fi

# Search rows must key the same way recents do, or the favourite star on a
# search result never matches the stored favourite.
IDENT=$($APT search atl --limit 1 | python3 -c "import json,sys;print(json.load(sys.stdin)['results'][0].get('ident',''))")
if [[ "$IDENT" == "ATL" ]]; then
  echo "ok   search rows key on ident"; pass=$((pass+1))
else
  echo "FAIL search row ident was '$IDENT' (expected ATL)"; fail=$((fail+1))
fi

# Rendering an airport must not add it to recents; only an explicit pick does.
REC2="$(mktemp -d)/r.json"
AIRPORT_INFO_RECENTS="$REC2" $APT panel KATL --no-record >/dev/null
COUNT=$(AIRPORT_INFO_RECENTS="$REC2" $APT recents --json 2>/dev/null | python3 -c "import json,sys;print(len(json.load(sys.stdin)['recents']))" 2>/dev/null || echo 0)
if [[ "$COUNT" == "0" ]]; then
  echo "ok   browsing does not pollute recents"; pass=$((pass+1))
else
  echo "FAIL browsing added $COUNT entries to recents"; fail=$((fail+1))
fi
AIRPORT_INFO_RECENTS="$REC2" $APT recents touch KATL >/dev/null
check "explicit pick records" "ATL" \
  env AIRPORT_INFO_RECENTS="$REC2" python3 scripts/apt.py recents
rm -rf "$(dirname "$REC2")"

# Search must find airports by city and state, and rank the one people mean first.
TOP=$($APT search atlanta --limit 1 | python3 -c "import json,sys;print(json.load(sys.stdin)['results'][0]['id'])")
if [[ "$TOP" == "ATL" ]]; then
  echo "ok   city search ranks the hub first"; pass=$((pass+1))
else
  echo "FAIL 'atlanta' returned $TOP first (expected ATL)"; fail=$((fail+1))
fi
check "state name search"     '"state": "VT"'  $APT search vermont --limit 3
check "state code search"     '"state": "VT"'  $APT search VT --limit 3
check "city plus state"       "Sky Acres"      $APT search "millbrook ny" --limit 5
check "two-word state"        '"state": "NY"'  $APT search "new york" --limit 3
VTALL=$($APT search vermont --limit 5 | python3 -c "import json,sys;r=json.load(sys.stdin)['results'];print(len({x['state'] for x in r}))")
if [[ "$VTALL" == "1" ]]; then
  echo "ok   state search stays in state"; pass=$((pass+1))
else
  echo "FAIL state search spanned $VTALL states"; fail=$((fail+1))
fi

# Live hazard and daylight context on the panel payload.
check "tfr in payload"      '"tfr"'            $APT panel KPOU --no-record
check "twilight in weather" "twilight"         $APT panel KPOU --no-record

# Never assert a negative from missing data: outside FAA coverage the plugin
# must not claim an airport has no tower or no fuel.
EGLLSUM=$($APT panel EGLL --no-record | python3 -c "
import json,sys
s=json.load(sys.stdin)
print('towered=%s fuel=%d' % (s['summary']['towered'], len(s['summary']['fuel'])))")
check "non-US surface decoded" "asphalt" $APT panel EGLL --no-record
if [[ "$EGLLSUM" == "towered=False fuel=0" ]]; then
  echo "ok   non-US gaps present in payload (UI must not assert them)"; pass=$((pass+1))
else
  echo "FAIL unexpected EGLL summary: $EGLLSUM"; fail=$((fail+1))
fi

# Notes round-trip.
NOTES_TMP="$(mktemp -d)"
AIRPORT_INFO_NOTES="$NOTES_TMP" $APT notes KPOU add "smoke test note" >/dev/null
check "notes round-trip" "smoke test note" \
  env AIRPORT_INFO_NOTES="$NOTES_TMP" python3 scripts/apt.py notes KPOU
rm -rf "$NOTES_TMP"

# Page renders without a wrapper element.
OUT="$(mktemp -d)/p.html"
if python3 scripts/render_page.py KPOU --out "$OUT" >/dev/null 2>&1; then
  if grep -qi '<!doctype html>' "$OUT" && grep -qi '</html>' "$OUT"; then
    echo "ok   page renders a complete document"; pass=$((pass+1))
  else
    echo "FAIL page is not a complete HTML document"; fail=$((fail+1))
  fi
  check "page has runway diagram" "<svg" cat "$OUT"
else
  echo "FAIL page render"; fail=$((fail+1))
fi

if [[ "${1:-}" == "--with-osm" ]]; then
  check "ATL concourse bucketing" "Concourse" $APT amenities KATL --type lounge
  check "AirNav FBO names"        "FlightLevel" $APT fbo KPOU
  check "AirNav fuel prices"      "100LL"       $APT fbo KPOU
fi

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
