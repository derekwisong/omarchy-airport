# Airport — an Omarchy shell plugin

Flight conditions for the airports you watch, in your bar. Full-screen lookup for the other
19,410.

```
… ● KPOU VFR  🔊 📶 🔋 14:32
  └─ green dot = VFR, blue = MVFR, red = IFR, magenta = LIFR
```

Click the pill for the detail popup. Right-click to cycle to the next watched airport.
Middle-click to force a refresh. Hit the full-screen lookup for anything not on your list.

Built for someone who flies both seats: a private pilot who wants runway lengths, CTAF and
density altitude, and a frequent flier who wants to know if ATL is IFR before leaving for the
airport. Everything comes from public, unauthenticated sources — no API keys.

## Install

```bash
git clone <this-repo> && cd airport-info-plugin
./install.sh              # copies into ~/.config/omarchy/plugins/, enables, builds the cache
```

Or from a git URL, the normal Omarchy way:

```bash
omarchy plugin add https://github.com/<you>/airport-info-plugin.git --enable
python3 ~/.config/omarchy/plugins/derekwisong.airport/scripts/apt.py cache update
```

The cache is one 28-day FAA cycle in SQLite under `~/.cache/airport-info/` — about 8 seconds
and 40 MB. Re-run `cache update` when `cache status` says the cycle has rolled over.

## The panel

A single summoned panel — no bar item, nothing running in your face. Left rail is the
airports you've looked at recently, pinned ones first. Right side is the airport.

The header is what both audiences need before anything else: identifier, name, where it is,
flight category, field elevation, and one line of current conditions. Everything below is
split by task, so a traveler never scrolls past a runway table and a pilot never hunts for
the approach plates:

| Page | What's there |
|---|---|
| **Summary** | Location, elevation, conditions in plain English, longest runway and surface, control tower and its hours, airspace class, fuel, attended hours, landing fee, and links out — AirNav, driving directions, SkyVector, FAA record, NOTAM search |
| **Weather** | Flight category spelled out, wind, visibility, sky, **ceiling**, temperature, dew point, altimeter, pressure and density altitude, civil twilight and sunrise/sunset, then the raw METAR and TAF |
| **Amenities** | Food, shops and lounges as a table grouped by concourse, filterable, each name linking to its Google Maps listing |
| **Runways** | An aligned table: every runway per end — lengths, surface, lighting, alignment, ILS, VGSI, displaced thresholds, LDA and obstructions — plus pattern altitude and the diagram |
| **Procedures** | Approaches grouped by runway, SIDs, STARs, ODPs, minimums, hot spots, each linked to its PDF |
| **Frequencies** | The ones you'd actually tune, with CTAF and tower weighted, then approach/departure, plus a LiveATC link |
| **Services** | Attended hours, parking, customs, manager and owner, FBOs with live fuel prices |
| **Notes** | Your notes rendered as markdown, with an Edit button that opens your editor, plus the raw FAA remarks |

The **Summary** is written for a traveller and a pilot at once — no CTAF, no density
altitude, no pattern altitude. Those live on the pages that are about flying the aeroplane.
The **airport diagram** is linked in the header, so it is reachable from every page.

**Weather is written for people first.** The header says *"Scattered clouds at 7,000 ft, 83°F,
wind from the west-northwest (300°) at 5 kt"*, not `30005KT 10SM SCT070 28/16 A2984`.
Temperatures use one unit, chosen from your locale — override with
`AIRPORT_INFO_UNITS=metric`.

**Frequencies are the ones you'd actually tune.** ATL publishes 101; the page shows the 13
field frequencies (ATIS, tower, ground, clearance, CTAF, UNICOM), files 74 approach and
departure frequencies under their own heading, and counts the rest.

## Activating it

**This plugin configures nothing on your system.** Omarchy manifests cannot declare
keybindings — the schema accepts only `schemaVersion`, `id`, `name`, `version`, `author`,
`description`, `kinds`, `keepLoaded`, `entryPoints`, a `barWidget` block and an `omarchy`
block (clone bookkeeping). Bindings live in Hyprland config, which is yours. `install.sh`
copies, enables and builds the cache; it never writes to your config.

Three ways in, in the order Omarchy itself uses them:

**1. The bar widget** — already there once enabled, no setup. Click the pill for the detail
popup, right-click to cycle watched airports, middle-click to refresh. A plugin that ships a
bar widget is its own entry point, which is why this one needs no keybinding to be useful.

**2. The Omarchy menu** — `SUPER + SPACE`, then type "airport". Copy the entry from
[`menu-extension.jsonc`](menu-extension.jsonc) into
`~/.config/omarchy/extensions/omarchy-menu.jsonc` (hot-reloads on save). This is how the
built-in overlays are reachable too — Emoji is `trigger.emoji` in the stock menu, with
`aliases` making it searchable. Aliases also give you CLI routes:

```bash
omarchy menu summon trigger.airports
```

**3. A keybinding** — optional, and only worth it for something you open constantly. Nothing
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

**4. Directly**, from a script or terminal:

```bash
omarchy-shell shell toggle derekwisong.airport
```

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
  clients and `external-api.faa.gov` returns 401 — so the plugin does not pretend to have them.
  The Summary links out to the official NOTAM search instead.
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
and `omarchy-shell shell rescanPlugins` returns success, but **neither re-instantiates an
already-mounted bar widget** — the old component keeps running and your edit appears to do
nothing. `omarchy restart shell` is the only thing that reliably reloads plugin QML.

### Two traps worth knowing

**Never name a QML property `data`.** `Item.data` is the built-in default children list, so
`property var data: null` is shadowed and reads back as the child list — every `if (!data)`
silently inverts. This cost an hour: recents rendered, the airport never loaded, and no error
was logged anywhere. `airportData` is the name now.

**Set `Process.command` imperatively** right before `running = true`. A declarative binding
on `command` may not have propagated when you start the process in the same block, so it runs
the previous (or empty) argument list.

```bash
./tests/smoke.sh              # 31 checks against the engine, network required
./tests/smoke.sh --with-osm   # adds the Overpass concourse check
omarchy plugin validate .     # manifest and entry points
```

## Data sources

FAA NASR 28-day subscription · FAA d-TPP · FAA Chart Supplement · aviationweather.gov ·
tfr.faa.gov · OurAirports · OpenStreetMap contributors (ODbL) · sunrise-sunset.org

FAA data is public domain. OpenStreetMap data is © OpenStreetMap contributors under ODbL, and
that attribution appears in the CLI output and on every generated page.
