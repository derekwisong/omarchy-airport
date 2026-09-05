# Changelog

## 3.0.0

A major version because the identifiers on screen, the JSON payload and the
cache schema all changed shape. Nothing about how you install or update it
changes; `omarchy plugin update derekwisong.airport` is enough.

### Breaking

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
  invert for night use. Falls back to a browser where Qt's PDF module is
  absent.
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
