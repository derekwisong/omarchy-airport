# Airport — an Omarchy shell plugin

Look up any of 19,411 US airports — and the rest of the world besides — without leaving your
desktop. One summoned panel: type an identifier, a city or a state, and get the field.

```
POU  KPOU  VFR  elev 164'
Hudson Valley Regional
Poughkeepsie, NY · 4 mi S · Airport diagram
Clear, 68°F, wind from the southeast (130°) at 3 kt.

Summary  Weather  Amenities  Runways  Procedures  Frequencies  Services  Notes
```

Built for someone who flies both seats: a private pilot who wants runway lengths, CTAF and
density altitude, and a frequent flier who wants to know if ATL is IFR before leaving for the
airport. Everything comes from public, unauthenticated sources — no API keys.

## Install

```bash
git clone <this-repo> && cd airport-info-plugin
./install.sh              # copies into ~/.config/omarchy/plugins/ and enables it
```

Or from a git URL, the normal Omarchy way:

```bash
omarchy plugin add https://github.com/<you>/airport-info-plugin.git --enable
```

Either way there is nothing else to run. The panel builds its data cache the first time you
open it, showing what it is doing while it works, and rebuilds it in the background when the
FAA cycle rolls over. To build it ahead of time instead:

```bash
python3 ~/.config/omarchy/plugins/derekwisong.airport/scripts/apt.py cache update
```

## The cache

Every FAA and OurAirports source is a bulk publication — a whole 28-day subscription file, a
national chart metafile — so there is no way to fetch one airport. Looking up KPOU means
holding the file that has all 19,411 of them. What the plugin can do is fetch only the
sources a given page needs, and only once per cycle:

| Tier | Download | What needs it | When |
|---|---|---|---|
| `core` | 22 MB | Search, ranking, IATA codes, every US page | First run |
| `charts` | 18 MB | Approach plates, SIDs, STARs, the airport diagram linked in every header | First run |
| `world` | 4 MB | Runway geometry for non-US fields | First time you look one up |

That comes to **about 9 seconds and 54 MB** in SQLite under `~/.cache/airport-info/`. Most
users never fetch the `world` tier at all.

The cache is rebuilt beside the live one and swapped in at the end, so a failed download
leaves the working cache alone and a refresh never blanks the panel mid-use. Staleness is the
FAA cycle rolling over, not the file getting old — a cache built on day 27 of a cycle is out
of date two days later, and one built on day 1 is current for four weeks.

```bash
python3 scripts/apt.py cache status            # cycle, size, which tiers are present
python3 scripts/apt.py cache status --json     # the same, for scripts
python3 scripts/apt.py cache update            # rebuild
python3 scripts/apt.py cache update --if-stale # rebuild only if the cycle rolled
python3 scripts/apt.py cache update --progress # one JSON line per step
```

## The panel

A single summoned panel — no bar item, nothing running in your face. Left rail is the
airports you've looked at recently, pinned ones first. Right side is the airport.

The header is what both audiences need before anything else: identifier, name, where it is,
flight category, field elevation, and one line of current conditions. Everything below is
split by task, so a traveler never scrolls past a runway table and a pilot never hunts for
the approach plates:

| Page | What's there |
|---|---|
| **Summary** | Location, elevation, conditions in plain English, **FAA delays and closures**, a forecast band, longest runway and surface, control tower and its hours, airspace class, fuel, attended hours, landing fee |
| **Weather** | Flight category spelled out, wind, visibility, sky, **ceiling**, temperature, dew point, altimeter, pressure and density altitude, civil twilight and sunrise/sunset, a **forecast timeline** read out of the TAF, then the raw METAR and TAF |
| **Amenities** | Food, shops and lounges as a table grouped by concourse, filterable, each name linking to its Google Maps listing |
| **Runways** | An aligned table: every runway per end — lengths, surface, lighting, alignment, ILS, VGSI, displaced thresholds, LDA and obstructions — plus pattern altitude and the diagram |
| **Procedures** | Approaches grouped by runway, SIDs, STARs, ODPs, minimums, hot spots, each opening in the panel's chart viewer |
| **Frequencies** | The ones you'd actually tune, with CTAF and tower weighted, then approach/departure, plus a LiveATC link |
| **Services** | Attended hours, parking, customs, manager and owner, FBOs with live fuel prices |
| **Notes** | Your notes rendered as markdown, with an Edit button that opens your editor, plus the raw FAA remarks |

Links out live in the **header**, not on a page: the airport diagram, driving directions,
AirNav, SkyVector, the FAA record, aviationweather.gov and LiveATC all describe the airport
rather than any one view of it, and on the Runways page you are no less likely to want AirNav
than on the Summary. Links that belong to a single row — a plate's PDF, a restaurant's map
pin, the TFR list — stay with their row.

The **Summary** is written for a traveller and a pilot at once — no CTAF, no density
altitude, no pattern altitude. Those live on the pages that are about flying the aeroplane.


**Weather is written for people first.** The header says *"Scattered clouds at 7,000 ft, 83°F,
wind from the west-northwest (300°) at 5 kt"*, not `30005KT 10SM SCT070 28/16 A2984`.
Temperatures use one unit, chosen from your locale — override with
`AIRPORT_INFO_UNITS=metric`.

**Frequencies are the ones you'd actually tune.** ATL publishes 101; the page shows the 13
field frequencies (ATIS, tower, ground, clearance, CTAF, UNICOM), files 74 approach and
departure frequencies under their own heading, and counts the rest.

## Activating it

**This plugin configures nothing on your system.** Omarchy manifests cannot declare
keybindings, so bindings live in Hyprland config, which is yours. `install.sh` copies and
enables; it never writes to your config and never builds anything behind your back.

Three ways in:

**1. The Omarchy menu** — `SUPER + SPACE`, then type "airport". Copy the entry from
[`menu-extension.jsonc`](menu-extension.jsonc) into
`~/.config/omarchy/extensions/omarchy-menu.jsonc` (hot-reloads on save). This is how the
built-in overlays are reachable too — Emoji is `trigger.emoji` in the stock menu, with
`aliases` making it searchable. Aliases also give you CLI routes:

```bash
omarchy menu summon trigger.airports
```

**2. A keybinding** — optional, and only worth it for something you open constantly. Nothing
is suggested here by default: on a stock install the natural candidates are taken
(`SUPER+CTRL+A` is Audio), and overriding a stock binding to install a third-party plugin is
a bad trade. If you want one, check what is free first and pick from there:

```bash
omarchy menu keybindings --print | grep -E "^SUPER"
```

```lua
-- ~/.config/hypr/bindings.lua
o.bind("SUPER + <key>", "Airports", "omarchy-shell shell toggle derekwisong.airport")
```

**3. Directly**, from a script or terminal:

```bash
omarchy-shell shell toggle derekwisong.airport
```

## Requirements

Python 3 (standard library only — no pip install) and the Omarchy shell. Nothing else is
required.

**Optional:** in-panel chart viewing needs `qt6-webengine`, which supplies `QtQuick.Pdf`, and
`qt6-5compat` for the invert effect. Neither is a dependency of Omarchy or Quickshell, so
neither is present by default, and `qt6-webengine` is a 282 MB install. Without them the
plugin works normally and charts open in your browser instead. Install them only if you want
plates and diagrams inside the panel:

```bash
sudo pacman -S --needed qt6-webengine qt6-5compat
```

## Charts

Approach plates and airport diagrams open **inside the panel**, not in an external viewer —
handing a plate to a browser meant the panel closed to show it, losing the airport, the page
and the search behind it. Esc backs out to exactly where you were.

`←→` pages a multi-page plate, `+`/`−` and `Ctrl`+wheel zoom, `0` fits the page again, and
`↑↓`/`PgUp`/`PgDn` scroll. "Open externally" is still there for when you want it in a browser.

Charts are drawn on their own white sheet rather than on the panel's card — the FAA renders
these pages with a transparent background, so black linework on a dark theme is invisible,
which is not a thing to discover on the ramp. **`i` inverts** for night use: white linework on
black, alpha left alone so the page stays a page. The setting holds for the session.

If `QtQuick.Pdf` is missing the viewer is simply never loaded — its imports live in
`ChartView.qml` rather than `Panel.qml` precisely so that a missing module costs the viewer
and not the whole plugin — and charts open externally as before.

Charts are downloaded once into `~/.cache/airport-info/charts/` and reused; the 28-day cycle
is part of the URL, so a file that exists is a file that is current. The engine only fetches
from the FAA chart hosts, over https — the URLs come from the plugin's own tables, but it
refuses anything else rather than downloading whatever it is handed.

```bash
python3 scripts/apt.py pdf <chart-url>          # download, print the local path
python3 scripts/apt.py pdf <chart-url> --json
```

## Forecast timeline

The TAF was already being downloaded for every airport and shown only as its raw bulletin.
It is parsed now into a band of time — one segment per forecast period, width proportional to
how long it lasts, coloured by flight category — with the periods listed underneath in plain
English and `TEMPO`/`PROB` groups kept separate as the overlays they are.

```
     now
      │
06Z   ▼    12Z        18Z        00Z        06Z
▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓
01:00Z-11:00Z  VFR   scattered clouds at 5,000 ft, wind north-northeast (30°) at 6 kt
11:00Z-19:00Z  MVFR  scattered clouds at 800 ft, broken clouds at 1,500 ft
03:00Z-07:00Z  MVFR  PROB30 — light thunderstorms with rain, mist, visibility 3 miles
```

Marks along the band carry both readings: Zulu, which is what a TAF is written in and what a
pilot briefs against, and an offset from now — `+4h`, `+10h` — which is what anyone else can
act on without doing timezone arithmetic. The Summary shows only the offsets; the Weather page
shows both. A mark already in the past gets no offset rather than a negative one.

**Now** is marked on the band and creeps along while the panel is open, so "when does this
change" is a glance rather than arithmetic against a Zulu clock. On a forecast whose valid
period has already passed the marker is absent rather than pinned to an edge, since a stale
TAF should not look current.

This is the one genuinely predictive thing here, and it needed no new source: the forecast was
already in hand. Categories are computed with the standard FAA ceiling and visibility
thresholds, so they mean the same thing as the category on the current conditions.

```bash
python3 scripts/apt.py outlook KORD
```

### At a glance, on the Summary

The same band appears on the Summary, captioned so it reads without a licence:

```
Clear now, turning to some cloud or haze in about 9 hours · thunderstorms possible
in about 2 hours (30% chance)
▓▓▓▓▓▓▓▓▓░░░░░░░░░░░▓▓▓▓▓▓▓▓▓▓▓▓
now      +4h        +10h      +16h
■ clear   ■ some cloud or haze
```

The colours are flight categories, which mean nothing to someone who does not fly, so the
line above says what the sky is doing and when that changes, and the key below names only the
categories this particular forecast contains — a clear day carries no four-colour legend
explaining weather it is not having.

It deliberately says nothing about delays. Low cloud correlates with them, but a forecast
knows nothing about traffic, crews or the rest of the system, and a plugin that refuses to
invent a NOTAM should not guess at that either.

## FAA status

Ground delay programs, ground stops, arrival and departure delays, and field closures, from
`nasstatus.faa.gov` — public, key-free, and the whole national picture in under 2 KB. One
fetch covers every airport, so it is cached nationally rather than requested per airport.

```bash
python3 scripts/apt.py status          # everywhere the FAA reports a problem
python3 scripts/apt.py status DCA      # one airport
```

The Summary says *"No delays or closures reported by the FAA"* only when the feed actually
answered. If it could not be reached the line is absent, because an unreachable feed is not
evidence that an airport is running normally. This is delays and closures — still not NOTAMs.

## Keyboard

The panel is usable without the mouse. Everything is typed at the search field, so the keys
that act on the page carry a modifier rather than stealing characters from it.

| Key | Does |
|---|---|
| `↑` `↓` | Move through the airport list |
| `←` `→` | Change page |
| `Enter` | Pick the highlighted airport (this is what records a recent) |
| `Ctrl+D` | Favourite / unfavourite |
| `PgUp` `PgDn` | Scroll the page |
| `Ctrl+↑` `Ctrl+↓` | Scroll a line at a time |
| `Ctrl+Home` `Ctrl+End` | Jump to the top or bottom of the page |
| `Tab` `Shift+Tab` | On **Amenities**, walk the concourse filter |
| `Esc` | Back out of a chart, then close the panel |

## Speed

An airport is drawn in two passes. Everything local — runways, frequencies, procedures,
services — comes from SQLite and renders in about **75 ms**. Conditions and TFRs are a
network call that costs 300–1300 ms on a cold cache, so they arrive separately and fold in
when they land. Walking the list with the arrow keys never waits on aviationweather.gov.

Until the conditions arrive the panel says nothing about them, rather than showing "no
weather station reports" — an answer that has not come back yet is not the same claim as an
airport that has no station.

It does say that it is waiting, though. The Conditions row holds its place as *checking…*
instead of appearing from nowhere, a line stands in for the delay and TFR lines that arrive
last, and the accent sliver under the tabs runs until the fetch lands. Silence about the
weather and silence about whether anything is happening are different things.

## Recents

There is no list to curate. Picking an airport — clicking it or pressing Enter — puts it at
the top of recents, deduped and capped at 12. Merely arrowing past one does not, so browsing
never pollutes the list. Every row carries a star, in search results too: click it, or press
**Ctrl+D**, to make an airport a favourite so it stays put and never rolls off.

```bash
apt=~/.config/omarchy/plugins/derekwisong.airport/scripts/apt.py
python3 $apt recents            # list, pinned first
python3 $apt recents pin KPOU
python3 $apt recents unpin KPOU
python3 $apt recents clear      # drops everything except pins
```

Stored in `~/.airport-info/recents.json`.

## The engine

`scripts/apt.py` is stdlib-only Python 3 and works standalone — the QML just shells out to it.

```bash
python3 scripts/apt.py info KPOU                     # full summary
python3 scripts/apt.py runways KPOU --svg            # to-scale SVG diagram
python3 scripts/apt.py procedures KATL --runway 27R  # approaches, SIDs, STARs
python3 scripts/apt.py amenities ATL --concourse B --type food
python3 scripts/apt.py nearby KPOU --radius 50 --min-runway 3000 --fuel
python3 scripts/apt.py wx KPOU                       # METAR, TAF, density altitude, twilight
python3 scripts/apt.py tfr KPOU --radius 100
python3 scripts/apt.py notes ATL add "Sky Club F is the good one"
python3 scripts/apt.py fbo KPOU                      # FBOs and live fuel prices
python3 scripts/apt.py search pough                  # type-ahead, JSON
python3 scripts/apt.py panel KPOU                    # the panel's payload, JSON
python3 scripts/apt.py brief KATL --amenities        # everything, JSON
```

Add `--json` to any subcommand. `scripts/render_page.py <ident> --amenities --out page.html`
writes a standalone browsable page — runway diagram, procedures, and a searchable
food/shops/lounges browser you can filter by concourse.

## What it knows

**Pilot side**, from the FAA NASR 28-day subscription and d-TPP:

- Field elevation, pattern altitude (including the 286 fields that publish it only in
  remarks), magnetic variation, ARP coordinates
- Runways longest-first: dimensions, surface, lighting, weight bearing, PCN
- Per runway end: true alignment, LDA/TORA/TODA/ASDA, displaced thresholds, ILS, approach
  lighting, VGSI, right-hand traffic, and the tree on short final with its slope
- CTAF, UNICOM, tower/ground/clearance, ATIS, ASOS, approach — with tower hours
- Fuel types, landing fee, transient hangar and tiedown, customs, ARFF, services
- Airport manager and owner with phone numbers
- Every published procedure: airport diagram, approaches grouped by runway, SIDs, STARs,
  ODPs, minimums, hot spots, LAHSO — each linked to its PDF, with the cycle expiry stated
- METAR, TAF, flight category, density altitude, civil twilight
- Active TFRs, filtered by state and refined by distance where the FAA publishes geometry

**Traveler side**, from OpenStreetMap: restaurants, bars, cafes, shops and airline lounges,
assigned to the terminal or concourse polygon that contains them. At ATL that places all 193
mapped POIs into Concourses A–F, T and the Domestic Terminal with none left over.

**Your side**: plain markdown in `~/.airport-info/notes/<IDENT>.md`, one file per airport.

## What it deliberately does not do

- **No NOTAMs.** There is no key-free source — `notams.aim.faa.gov` returns 403 to non-browser
  clients and `external-api.faa.gov` returns 401 — so the plugin does not pretend to have them,
  and does not link to a search that would imply it had checked. Every pilot-facing output
  says to get an official briefing.
- **FBO names and fuel prices come from AirNav**, scraped on demand for one airport at a
  time and cached for 24 hours. Their robots.txt disallows only `/cgi-bin/`, so `/airport/`
  is fair game, but this is still someone else's site: don't bulk-crawl it, and expect the
  parser to need repair when their HTML changes. Ramp fees are not published anywhere.
- **No ratings or reviews.** OpenStreetMap has no rating field at all, and the only public
  sources charge for it, so the plugin shows none rather than a made-up number. Names link to
  Google Maps, where the ratings live.
- **Non-US airports** fall back to OurAirports and OSM: identifier, runways, elevation, METAR
  and amenities work; FAA charts, frequencies, procedures and TFRs don't exist and it says so.
- **TFRs are counted, not located.** The FAA publishes geometry only per-NOTAM, so the panel
  says how many are active in the state and links to the list. It never implies one is near
  your airport, because it does not know.
- **It never asserts a negative from missing data.** Outside FAA coverage an airport is not
  described as having no tower or no fuel; the Summary says the data does not reach there.

## Not for navigation

A reference tool built on a 28-day snapshot. Every pilot-facing output names its cycle and
carries a not-for-navigation note. Verify against current FAA publications and get an official
preflight briefing, including NOTAMs and TFRs, before any flight.

## Development

The panel is built from Omarchy's own shell components — `PanelSectionHeader`,
`PanelSeparator`, `TextField` — so it inherits the theme, focus and hover treatment every
other panel uses, rather than reimplementing them.

`~/.config/omarchy/plugins/` hot-reloads on save, so `./install.sh` re-applies edits without a
restart. If a change doesn't take:

```bash
omarchy restart shell                                     # REQUIRED to pick up QML changes
journalctl --user --since "2 minutes ago" | grep -i qml   # QML errors land here
```

Note: saving a file under `~/.config/omarchy/plugins/` logs `Local plugin changed, reloading`
and `omarchy-shell shell rescanPlugins` returns success, but **neither re-instantiates a
component the shell has already mounted** — the old one keeps running and your edit appears to
do nothing. `omarchy restart shell` is the only thing that reliably reloads plugin QML.

### Adding a NASR column

Rows are stored as positional JSON arrays over the allowlists at the top of `apt.py`
(`APT_KEEP`, `RWY_KEEP`, `RWY_END_KEEP`), because NASR ships ~90 columns per airport and
carrying all of them cost 61 MB and most of the build. A column that is not on its list reads
back as absent, exactly as an empty NASR field always has — so if a new feature needs one, add
it to the list and rebuild the cache. The list in force at build time is written to `meta`,
so an existing cache stays readable when the lists change.

### Two traps worth knowing

**Never name a QML property `data`.** `Item.data` is the built-in default children list, so
`property var data: null` is shadowed and reads back as the child list — every `if (!data)`
silently inverts. This cost an hour: recents rendered, the airport never loaded, and no error
was logged anywhere. `airportData` is the name now.

**Set `Process.command` imperatively** right before `running = true`. A declarative binding
on `command` may not have propagated when you start the process in the same block, so it runs
the previous (or empty) argument list.

```bash
./tests/smoke.sh              # 69 checks against the engine, network required
./tests/smoke.sh --with-osm   # adds the Overpass concourse check
omarchy plugin validate .     # manifest and entry points
```

## License

MIT — see [LICENSE](LICENSE). The code is mine to license; the data is not, and the sources
below carry their own terms. FAA material is public domain. OpenStreetMap data is
© OpenStreetMap contributors under the ODbL, and that attribution appears in the CLI output
and on every generated page.

## Data sources

FAA NASR 28-day subscription · FAA d-TPP · FAA Chart Supplement · aviationweather.gov ·
tfr.faa.gov · OurAirports · OpenStreetMap contributors (ODbL) · sunrise-sunset.org

FAA data is public domain. OpenStreetMap data is © OpenStreetMap contributors under ODbL, and
that attribution appears in the CLI output and on every generated page.
