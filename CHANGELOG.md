# Changelog

## Unreleased

### Fixed

- **A ground stop no longer reads as a closed airport.** The line said
  `Ground stop — thunderstorms — until 6:45 pm EDT` and sat next to a row
  labelled `Airport closure`, which is how a program holding ZDC and ZNY
  departures out of Atlanta came to look like Atlanta being shut. It now names
  the centres actually included, and says the field is open and that inbound
  flights are waiting at their departure airport.
- **A NOTAM is no longer reported as a closure.** The FAA's XML files free-form
  NOTAMs under `Airport_Closure_List`, so `LAX AD AP CLSD TO NON SKED TRANSIENT
  GA ACFT EXC 24HR PPR` was shown as LAX being closed. Genuine closures and
  free-form notices are now told apart and labelled for what they are.
- **Both TFR detail URLs were 404s**, which is a failure with no symptom: the
  geometry fetch silently returned nothing, so no TFR was ever measured, and
  every per-TFR link was dead. Fixed to the endpoints the FAA actually serves.

### Added

- **A Traffic page.** What ADS-B hears within 25 nm right now, grouped into
  arriving, departing, on the ground and passing over, with type, altitude,
  speed and distance. It refreshes itself while its tab is open and stops the
  moment it is not. From [adsb.lol](https://adsb.lol/), which is volunteer
  receivers pooling what they hear — so every line says *seen*, and an empty
  list says the receivers are quiet rather than that the sky is. Arriving and
  departing are read off altitude and vertical rate, because ADS-B carries no
  origin or destination, and the page says so.
- **Local time in the header.** The first thing anyone asks about an airport
  they are flying to, and nothing in the panel could answer it. No FAA product
  publishes a timezone in structured form — not any of the eight NASR airport
  files, not the Chart Supplement index, and the Chart Supplement PDF prints it
  with subset fonts that contain no extractable text. So the IANA zone is
  looked up once per airport and kept; only the name is stored, and the offset
  is recomputed from the system tzdata on every read, so a cached airport still
  reads correctly the morning the clocks go back. Nearest-city guessing was
  tried and rejected — it put Pensacola in Eastern and Portland in Mountain,
  and a wrong hour is worse than no hour, so a failed lookup shows nothing.
- `amenities --open-now` uses the real zone when it is known, instead of the
  longitude-derived offset that ignored DST and every timezone boundary.
- **Delays and TFRs are one `ADVISORIES` section**, because a ground stop, a
  NOTAM and a TFR are the same question to whoever is reading.
- **A field inside a TFR is reported as inside it.** A TFR is one or more
  closed rings — a VIP one is a 30 nm ring with a 10 nm ring inside — and
  distance is measured to the ring edge, or nought if the field is within it.
  Measured against a bag of vertices instead, the airport most affected would
  have read as the one least affected: Morristown sitting in its own 30 nm VIP
  ring, reported as 30 nm away from it.
- **TFRs are located rather than counted.** "3 active TFRs in Georgia" answered
  a question nobody asked. Every active TFR on the national list is now placed
  from its published geometry and the ones within 50 nm are listed nearest
  first, each linked to its FAA page. Geometry is cached per NOTAM, so the
  first lookup costs about three seconds and later ones cost nothing.
- **Delay programs link to the FAA advisory** they summarise.
- Ground stops and ground delay programs carry their scope, real start and end
  times, a live countdown, and how likely the FAA thinks an extension is —
  read from `nasstatus.faa.gov/api/airport-events`, the JSON the FAA's own
  dashboard uses. The older XML feed stays as a fallback and, having no scope
  to report, claims none.

### Changed

- `apt.py tfr` defaults to a 50 nm radius, sorts by distance and drops
  `--no-geometry`; geometry is the point of it and is now cached.

## 3.0.0

A major version because the identifiers on screen, the JSON payload and the
cache schema all changed shape. Nothing about how you install or update it
changes; `omarchy plugin update derekwisong.airport` is enough.

### Breaking

- Your notes and recents move out of `~/.airport-info` to the XDG directories:
  notes to `~/.local/share/airport-info/notes`, recents to
  `~/.local/state/airport-info/recents.json`. Moved automatically on the next
  run, which says what it moved; the cache was already in `~/.cache`.

- Airports display as `ATL`, not `KATL`. The ICAO form sits beside it, and
  either spelling still resolves. Services that publish under the ICAO
  identifier — AirNav, LiveATC, the FAA record — still use it.
- `panel` payload: `header.faa_id` is gone, replaced by `header.icao`.
- `links.notams` is gone. The plugin has no NOTAM data and will not link to a
  search that implies otherwise.
- NASR rows are stored as positional arrays over explicit column allowlists.
  Any cache from an earlier version is read correctly but should be rebuilt.

### Added

- A forecast timeline parsed from the TAF, on the Weather page as a band of
  flight categories and on the Summary as a captioned one-liner. Marks carry
  both Zulu and an offset from now, and now itself is marked.
- FAA delays and closures from `nasstatus.faa.gov` — ground delay programs,
  ground stops, arrival and departure delays, field closures.
- Approach plates and airport diagrams open inside the panel, with `i` to
  invert for night use, and in a browser where Qt's PDF module is absent.
  Nothing to install either way.
- Keyboard reaches the whole panel: `Ctrl`+arrows and `Ctrl+Home`/`End`
  scroll, `Tab` walks the concourse filter, `Shift+Del` forgets a recent.
- `apt.py outlook`, `apt.py status`, `apt.py live` and `apt.py pdf`.

### Changed

- First run takes about 9 seconds and leaves 54 MB, down from 100 seconds and
  114 MB. Most of that was one unindexed query in the search ranking.
- An airport draws in two passes: everything local in about 75 ms, then
  conditions and delays when they arrive. Walking the rail no longer waits on
  the network.
- Airport-level links moved to the header, where they are reachable from every
  page rather than only the Summary.
- Notes are watched on disk, so saving one updates the page immediately.
- Frequency hours read as hours: NASR writes continuous operation as `24`.

### Fixed

- An unreachable weather service no longer reads as an airport with no weather
  station.
- A finished load no longer drags the selection backwards while you are
  arrowing through the list, and a slow amenity or FBO fetch can no longer
  land on the wrong airport.
- The cache rebuilds beside the live one and swaps in, so a failed download
  leaves the working cache alone.
- `cache status` exits non-zero when there is no cache.

## 2.0.0

Initial public shape: the summoned panel, eight pages, and the stdlib-only
engine behind it.
