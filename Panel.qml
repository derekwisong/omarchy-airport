import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Summoned airport panel:  omarchy-shell shell toggle derekwisong.airport
//
// Left rail is recents (pinned first). Right side is the airport, with the
// header a traveler and a pilot both need, and the depth split across tabs so
// neither audience wades through the other's data.
Item {
  id: root

  property var shell: null
  property var manifest: null

  readonly property string pluginDir: Qt.resolvedUrl(".").toString().replace(/^file:\/\//, "")
  readonly property string engine: pluginDir + "scripts/apt.py"

  property bool opened: false
  property string query: ""
  property var results: []
  property var recents: []
  property var favourites: ({})
  property int tab: 0
  // NOT `data`: Item.data is the built-in default children list, so a
  // property of that name is shadowed and reads back as the child list.
  property var airportData: null
  property string loadingIdent: ""
  // What select() last asked for. A response is only allowed to touch the
  // highlight if the highlight is still sitting where that request left it.
  property string requestedIdent: ""
  // Which airport the slow lazy fetches were asked for. Overpass and AirNav
  // take seconds; without this, walking the rail lands one airport's FBOs on
  // the next airport's page.
  property string fboIdent: ""
  property string amenitiesIdent: ""
  property string trafficIdent: ""
  property int trafficRadius: 0   // the range the loaded payload was fetched at
  // The local record renders on its own; conditions and TFRs arrive after.
  property bool liveLoading: false
  onLiveLoadingChanged: {
    if (liveLoading) busyDelay.restart()
    else if (loadingIdent === "") { busyDelay.stop(); showBusy = false }
  }
  property bool showBusy: false
  property string currentIdent: ""   // what is loaded and displayed
  property string selectedIdent: ""  // what the highlight is on, may be ahead

  // Lazily fetched, because both are slow network calls.
  property var fbo: null
  property bool fboLoading: false
  property var amenities: null
  property bool amenitiesLoading: false
  property var traffic: null
  property bool trafficLoading: false
  // Table or scope, and how far out. One range for both views, so switching
  // between them never quietly changes what you are looking at.
  property bool trafficMap: false
  property int trafficRange: 25
  readonly property var trafficRanges: [10, 25, 50, 100]

  // Cache state. The engine keeps one 28-day FAA cycle in SQLite; the first
  // run has to fetch it, and every 28 days it has to fetch it again. Rather
  // than fail blank when it is missing, the panel builds it and says so.
  property bool cacheChecked: false
  property bool cacheReady: false
  property bool cacheBuilding: false
  property bool cacheRefreshing: false   // rebuilding under a usable cache
  property int buildStep: 0
  property int buildTotal: 0
  property string buildLabel: ""
  property string buildError: ""
  property string buildStderr: ""
  property string expectedCycle: ""

  // Chart viewing. Approach plates and airport diagrams are the reason a pilot
  // opens this panel, and handing them to an external viewer closed the panel
  // to show them - losing the airport, the tab and the search behind it.
  property bool chartOpen: false
  property bool chartLoading: false
  property string chartPath: ""
  property string chartUrl: ""
  property string chartTitle: ""
  property string chartError: ""
  property int chartPage: 0
  property real chartZoom: 1.0
  // Charts are ink on paper, so the page is drawn on its own white sheet
  // rather than on the panel's dark card. Inverting is offered because a white
  // sheet at night is its own problem; it stays off unless asked for, and
  // holds for the session once set.
  property bool chartInvert: false
  readonly property real buildFraction: buildTotal > 0 ? buildStep / buildTotal : 0
  property string amenityFilter: ""
  property string amenityTerminal: ""

  readonly property var header: airportData ? airportData.header : null
  readonly property var overview: airportData ? airportData.overview : null
  readonly property var ground: airportData ? airportData.ground : null
  readonly property bool searching: query.length >= 2
  readonly property var railItems: searching ? results : recents

  function open(payloadJson) {
    root.opened = true
    root.query = ""
    root.results = []
    root.tab = 0
    checkCache()
    Qt.callLater(function () { input.forceActiveFocus() })
  }

  function close() {
    root.opened = false
  }

  function toggle() { root.opened ? root.close() : root.open() }

  // ---- the cache ----------------------------------------------------------

  // Asking costs nothing: status is a meta read plus 28-day arithmetic, no
  // network, so it is safe on every open.
  function checkCache() {
    if (cacheStatusProcess.running) return
    cacheStatusProcess.running = true
  }

  function applyCacheStatus(text) {
    var state = null
    try { state = JSON.parse(String(text || "{}")) } catch (e) { state = null }
    root.cacheChecked = true
    if (!state) { root.cacheReady = false; startBuild(false); return }

    root.cacheReady = !!state.built
    root.expectedCycle = state.expected_cycle || ""
    if (!state.built) {
      startBuild(false)
    } else {
      loadRecents()
      // The cycle rolled. The cache still works, so refresh it underneath the
      // user rather than making them wait for data they already have.
      if (state.stale) startBuild(true)
    }
  }

  function startBuild(background) {
    if (root.cacheBuilding) return
    root.cacheBuilding = true
    root.cacheRefreshing = background
    root.buildStep = 0
    root.buildTotal = 0
    root.buildLabel = background ? "Checking for new FAA data" : "Starting"
    root.buildError = ""
    root.buildStderr = ""
    buildProcess.command = ["python3", root.engine, "cache", "update", "--progress"]
    buildProcess.running = true
  }

  function applyBuildEvent(line) {
    var e = null
    try { e = JSON.parse(String(line || "")) } catch (err) { return }
    if (e.event === "begin") {
      root.buildTotal = e.total || 0
      if (e.label) root.buildLabel = e.label
    } else if (e.event === "step") {
      root.buildStep = e.step || 0
      root.buildTotal = e.total || root.buildTotal
      root.buildLabel = e.label || root.buildLabel
    } else if (e.event === "error") {
      root.buildError = e.message || "the build failed"
    }
  }

  function finishBuild(code) {
    root.cacheBuilding = false
    if (code === 0) {
      root.buildStep = root.buildTotal
      root.cacheReady = true
      root.buildError = ""
      loadRecents()
      // A refresh replaced the data under a loaded airport - reload it so the
      // page reflects the new cycle rather than the one it was rendered from.
      if (root.cacheRefreshing && root.currentIdent) {
        var ident = root.currentIdent
        root.currentIdent = ""
        select(ident)
      }
      root.cacheRefreshing = false
    } else if (!root.cacheRefreshing) {
      root.buildError = root.buildError || root.buildStderr
        || "the data build failed - check the network and try again"
    } else {
      // A failed background refresh is not the user's problem: the cache they
      // already have still works, and the next open tries again.
      root.cacheRefreshing = false
    }
  }

  // ---- data plumbing ------------------------------------------------------

  function loadRecents() { recentsProcess.running = true }

  function applyRecents(text) {
    try {
      root.recents = (JSON.parse(String(text || "{}")).recents) || []
    } catch (e) {
      root.recents = []
    }
    var map = ({})
    for (var i = 0; i < root.recents.length; i++)
      if (root.recents[i].pinned) map[root.recents[i].ident] = true
    root.favourites = map
    if (!root.airportData && root.recents.length > 0) select(root.recents[0].ident)
  }

  // Arrow keys move the highlight immediately and load after a pause, so
  // holding a key does not spawn a subprocess per keystroke.
  function highlight(ident) {
    if (!ident) return
    root.selectedIdent = ident
    loadDebounce.restart()
  }

  function runSearch() {
    if (!root.searching) { root.results = []; return }
    if (searchProcess.running) searchProcess.running = false
    searchProcess.command = ["python3", root.engine, "search", root.query, "--limit", "25"]
    searchProcess.running = true
  }

  function applyResults(text) {
    try {
      root.results = (JSON.parse(String(text || "{}")).results) || []
    } catch (e) {
      root.results = []
    }
    // Move the highlight to the top hit. Ctrl+D and Enter then act on the row
    // the eye is on, not on whatever was loaded before the search started.
    if (root.results.length > 0)
      root.selectedIdent = root.results[0].ident || root.results[0].id
  }

  function loadLive(ident) {
    if (!ident) return
    root.liveLoading = true
    if (liveProcess.running) liveProcess.running = false
    liveProcess.command = ["python3", root.engine, "live", ident]
    liveProcess.running = true
  }

  function applyLive(text) {
    var live = null
    try { live = JSON.parse(String(text || "{}")) } catch (e) { live = null }
    root.liveLoading = false
    if (!root.airportData) return
    if (!live || !live.weather) {
      // The fetch produced nothing usable. Stop saying "fetching" forever, and
      // do not let the absent answer read as "this airport has no station".
      if (root.airportData.weather && root.airportData.weather.pending) {
        var stalled = {}
        for (var k in root.airportData) stalled[k] = root.airportData[k]
        stalled.weather = { "available": false, "unreachable": true }
        root.airportData = stalled
      }
      return
    }
    // Arrowing on while this was in flight means the answer is for an airport
    // that is no longer on screen. Drop it rather than showing ATL's weather
    // under POU's name.
    if (live.ident && live.ident !== root.currentIdent) return
    var next = {}
    for (var key in root.airportData) next[key] = root.airportData[key]
    if (live.tfr) next.tfr = live.tfr
    if (live.status) next.status = live.status
    if (live.weather) {
      next.weather = live.weather
      // The header and the Summary carry their own copies of the conditions
      // line and the flight category - the engine derives them when it builds
      // the payload, so merging the weather alone leaves both blank.
      var header = {}
      for (var h in next.header) header[h] = next.header[h]
      header.conditions = live.weather.summary || ""
      header.category = live.weather.category || ""
      next.header = header

      var summary = {}
      for (var s in next.summary) summary[s] = next.summary[s]
      summary.weather = live.weather.summary || ""
      next.summary = summary
    }
    root.airportData = next
  }

  function select(ident) {
    if (!ident || ident === root.loadingIdent) return
    loadDebounce.stop()
    root.selectedIdent = ident
    root.loadingIdent = ident
    root.requestedIdent = ident
    root.fbo = null
    root.amenities = null
    root.traffic = null
    if (fboProcess.running) fboProcess.running = false
    if (amenitiesProcess.running) amenitiesProcess.running = false
    if (trafficProcess.running) trafficProcess.running = false
    root.fboLoading = false
    root.amenitiesLoading = false
    root.trafficLoading = false
    root.fboIdent = ""
    root.amenitiesIdent = ""
    root.trafficIdent = ""
    root.trafficRadius = 0
    root.amenityFilter = ""
    root.amenityTerminal = ""
    if (panelProcess.running) panelProcess.running = false
    // Local data only. Weather is a network call that costs 300-1300ms on a
    // cold cache, and waiting for it made every step of an arrow-key walk
    // through the rail pause on aviationweather.gov.
    panelProcess.command = ["python3", root.engine, "panel", ident,
                            "--no-record", "--no-live"]
    panelProcess.running = true
  }

  function applyPanel(text) {
    try {
      var parsed = JSON.parse(String(text || "{}"))
      if (parsed && parsed.header) {
        root.airportData = parsed
        root.currentIdent = parsed.header.ident
        // Adopt the canonical spelling - "KPOU" was asked for, "POU" is what
        // the rail rows are keyed on - but only while the user is still on
        // that row. Walking the list with the arrows is faster than a load,
        // and a response that reasserts the highlight drags the cursor back
        // to an airport the user has already gone past.
        if (root.selectedIdent === root.requestedIdent)
          root.selectedIdent = parsed.header.ident
        loadLive(parsed.header.ident)
        if (root.tab === root.tabAmenities || root.tab === root.tabGround)
          ensureGroundData()
        if (root.tab === root.tabTraffic) ensureTraffic(false)
      }
    } catch (e) {
      // leave the previous airport on screen rather than blanking the panel
    }
    root.loadingIdent = ""
  }

  function ensureGroundData() {
    if (!root.currentIdent) return
    if (!root.fbo && !root.fboLoading) {
      root.fboLoading = true
      root.fboIdent = root.currentIdent
      fboProcess.command = ["python3", root.engine, "fbo", root.currentIdent, "--json"]
      fboProcess.running = true
    }
    if (!root.amenities && !root.amenitiesLoading) {
      root.amenitiesLoading = true
      root.amenitiesIdent = root.currentIdent
      amenitiesProcess.command = ["python3", root.engine, "amenities",
                                  root.currentIdent, "--json"]
      amenitiesProcess.running = true
    }
  }

  function stepTrafficRange(delta) {
    var ranges = root.trafficRanges
    var at = ranges.indexOf(root.trafficRange)
    if (at < 0) at = 1
    var next = Math.max(0, Math.min(ranges.length - 1, at + delta))
    if (ranges[next] === root.trafficRange) return
    root.trafficRange = ranges[next]
    root.ensureTraffic(true)
  }

  function ensureTraffic(force) {
    if (!root.currentIdent) return
    if (root.trafficLoading) return
    if (!force && root.traffic && root.trafficIdent === root.currentIdent
        && root.trafficRadius === root.trafficRange) return
    root.trafficRadius = root.trafficRange
    root.trafficLoading = true
    root.trafficIdent = root.currentIdent
    trafficProcess.command = ["python3", root.engine, "traffic",
                              root.currentIdent, "--radius",
                              String(root.trafficRange), "--json"]
    trafficProcess.running = true
  }

  function moveSelection(delta) {
    var list = root.railItems
    if (list.length === 0) return
    var index = -1
    for (var i = 0; i < list.length; i++) {
      if ((list[i].ident || list[i].id) === root.selectedIdent) { index = i; break }
    }
    var next = index < 0 ? 0 : index + delta
    if (next < 0) next = list.length - 1
    if (next >= list.length) next = 0
    highlight(list[next].ident || list[next].id)
  }

  function moveTab(delta) {
    var next = root.tab + delta
    if (next < 0) next = tabNames.length - 1
    if (next >= tabNames.length) next = 0
    root.tab = next
  }

  // FAA charts open here; everything else is somebody else's website and
  // belongs in a browser.
  function openLink(url) {
    if (!url) return
    var text = String(url)
    // Nothing but http(s) is ever handed to the desktop. The editor and
    // reload links are wired to their own handlers, not to this one.
    if (!/^https?:\/\//i.test(text)) return
    if (root.chartViewerAvailable
        && /^https:\/\/[a-z.]*faa\.gov\/.*\.pdf$/i.test(text)) openChart(text)
    else Qt.openUrlExternally(text)
  }

  // The panel already knows what each chart is called - the same name the row
  // was rendered with - so title the viewer with that rather than a filename.
  function chartTitleFor(url) {
    var procs = root.procedures
    if (procs) {
      for (var group in procs) {
        var list = procs[group]
        if (!list || !list.length) continue
        for (var i = 0; i < list.length; i++) {
          var item = list[i]
          if (!item || typeof item !== "object") continue
          if (item.url === url) return item.name || ""
          if (item.pages && item.pages.indexOf(url) >= 0) return item.name || ""
        }
      }
    }
    if (procs && procs.cs === url) return "Chart Supplement"
    return String(url).split("/").pop()
  }

  function openChart(url, title) {
    if (!url) return
    root.chartUrl = url
    root.chartTitle = title || chartTitleFor(url)
    root.chartError = ""
    root.chartPage = 0
    root.chartZoom = 1.0
    root.chartPath = ""
    root.chartLoading = true
    root.chartOpen = true
    if (pdfProcess.running) pdfProcess.running = false
    pdfProcess.command = ["python3", root.engine, "pdf", url, "--json"]
    pdfProcess.running = true
  }

  function applyChart(text) {
    var result = null
    try { result = JSON.parse(String(text || "{}")) } catch (e) { result = null }
    root.chartLoading = false
    if (result && result.ok && result.path) {
      // The viewer binds its own document to this path; the panel no longer
      // owns a PdfDocument, because that type may not exist here.
      root.chartPath = result.path
    } else {
      root.chartError = (result && result.error)
        ? result.error : "could not download this chart"
    }
  }

  function closeChart() {
    root.chartOpen = false
    root.chartPath = ""
    root.chartError = ""
  }

  // Whether this machine can show a chart inline at all. Set false the first
  // time the viewer fails to load, so later charts go straight to a browser
  // instead of flashing an empty card each time.
  property bool chartViewerAvailable: true

  // No PDF support on this machine. Hand this chart to a browser and stop
  // trying to draw later ones inline.
  function chartViewerFailed() {
    var pending = root.chartUrl
    root.chartViewerAvailable = false
    root.chartOpen = false
    if (pending) Qt.openUrlExternally(pending)
  }

  function chartStep(delta) { if (chartLoader.item) chartLoader.item.step(delta) }
  function chartZoomBy(factor) { if (chartLoader.item) chartLoader.item.zoomBy(factor) }

  // Chosen deliberately - record the visit and refresh the rail.
  function commit(ident) {
    if (!ident) return
    select(ident)
    touchProcess.command = ["python3", root.engine, "recents", "touch", ident]
    touchProcess.running = true
  }

  // Notes are the one part of the payload the user edits behind our back, in
  // a separate editor window. Rather than re-running the engine when the
  // editor exits - which omarchy-launch-editor cannot tell us, because it
  // spawns a terminal and returns immediately - the file itself is watched.
  // Saving updates the Summary and the Notes page at once, with no refresh.
  function applyNotes(text) {
    if (!root.airportData) return
    var incoming = String(text || "")
    if (root.airportData.notes === incoming) return
    // A new object, because mutating the existing one notifies nothing.
    var next = {}
    for (var key in root.airportData) next[key] = root.airportData[key]
    next.notes = incoming
    root.airportData = next
  }

  function editNotes() {
    if (!root.airportData || !root.airportData.notes_path) return
    editorProcess.command = ["omarchy-launch-editor", root.airportData.notes_path]
    editorProcess.running = true
    root.close()
  }

  // Amenity concourses were reachable only by clicking a chip. Tab walks them
  // instead: it is not a character the search field wants, and the filter is
  // the only thing on that page worth cycling.
  function cycleTerminal(delta) {
    var chips = Model.terminalChips(root.amenities)
    if (!chips.length) return
    var current = root.amenityTerminal === "" ? "All" : root.amenityTerminal
    var at = chips.indexOf(current)
    if (at < 0) at = 0
    var next = (at + delta + chips.length) % chips.length
    root.amenityTerminal = chips[next] === "All" ? "" : chips[next]
    // A new filter is a new list; start it at the top rather than wherever
    // the previous one happened to be scrolled to.
    bodyScroll.contentY = 0
  }

  function scrollBody(dy) {
    bodyScroll.contentY = Math.max(
      0, Math.min(bodyScroll.contentY + dy,
                  Math.max(0, bodyScroll.contentHeight - bodyScroll.height)))
  }

  function isFavourite(ident) {
    return root.favourites[ident] === true
  }

  // Flip the star immediately, persist in the background, and never reload the
  // rail: the list keeps its order and nothing redraws but the one glyph.
  // Looking an airport up puts it in the rail, and until now nothing took it
  // back out: a mistyped lookup sat there until twelve more pushed it off.
  // Shift+Delete is the browser-history idiom for "forget this row", and it
  // cannot be mistaken for editing the query.
  function forgetSelected() {
    if (root.searching || !root.selectedIdent) return
    var list = root.railItems
    var index = -1
    for (var i = 0; i < list.length; i++)
      if ((list[i].ident || list[i].id) === root.selectedIdent) { index = i; break }
    // Land on the row that takes its place, or the one above if it was last.
    var after = ""
    if (index >= 0 && list.length > 1) {
      var neighbour = index + 1 < list.length ? list[index + 1] : list[index - 1]
      after = neighbour.ident || neighbour.id
    }
    forgetProcess.command = ["python3", root.engine, "recents", "remove",
                             root.selectedIdent]
    forgetProcess.running = true
    root.selectedIdent = after
  }

  function toggleFavourite(ident) {
    if (!ident) return
    var now = !root.isFavourite(ident)
    var map = ({})
    for (var key in root.favourites) map[key] = root.favourites[key]
    if (now) map[ident] = true
    else delete map[ident]
    root.favourites = map
    pinProcess.command = ["python3", root.engine, "recents",
                          now ? "pin" : "unpin", ident]
    pinProcess.running = true
  }

  onQueryChanged: searchDebounce.restart()
  onTabChanged: {
    if (tab === tabAmenities || tab === tabGround) ensureGroundData()
    if (tab === tabTraffic) ensureTraffic(false)
  }

  // Traffic goes stale in seconds, so it refreshes itself while its tab is
  // the one on screen and stops the moment it is not. The engine holds a 15
  // second cache, so this cannot outrun the source however long it is open.
  Timer {
    interval: 20000
    repeat: true
    running: root.opened && root.tab === root.tabTraffic && !!root.currentIdent
    onTriggered: root.ensureTraffic(true)
  }

  Timer { id: searchDebounce; interval: 180; onTriggered: root.runSearch() }
  // Only reason this exists: Date.now() is not a property, so a binding that
  // depends on the current time has nothing to react to.
  property int clockTick: 0
  Timer {
    interval: 60000
    repeat: true
    running: root.opened && (!!root.outlook || !!root.localTime)
    onTriggered: root.clockTick++
  }

  Timer {
    id: loadDebounce
    interval: 220
    onTriggered: root.select(root.selectedIdent)
  }

  Timer {
    id: busyDelay
    interval: 250
    onTriggered: root.showBusy = root.loadingIdent !== "" || root.liveLoading
  }

  onLoadingIdentChanged: {
    if (loadingIdent === "") {
      busyDelay.stop()
      showBusy = root.liveLoading
    } else {
      busyDelay.restart()
    }
  }

  readonly property var tabNames: ["Summary", "Weather", "Traffic", "Amenities",
                                   "Runways", "Procedures", "Frequencies",
                                   "Services", "Notes"]
  readonly property int tabTraffic: 2
  readonly property int tabAmenities: 3
  readonly property int tabGround: 7
  readonly property var weather: airportData ? airportData.weather : null
  readonly property var summary: airportData ? airportData.summary : null
  readonly property var runwayData: airportData ? airportData.runways : null
  readonly property var procedures: airportData ? airportData.procedures : null
  readonly property var frequencies: airportData ? airportData.frequencies : null
  readonly property var tfr: airportData ? airportData.tfr : null
  readonly property var status: airportData ? airportData.status : null
  readonly property var localTime: airportData ? airportData.local : null
  readonly property var outlook: (airportData && airportData.weather)
    ? (airportData.weather.outlook || null) : null

  Process {
    id: cacheStatusProcess
    command: ["python3", root.engine, "cache", "status", "--json"]
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.applyCacheStatus(text) }
  }
  Process {
    id: buildProcess
    // Progress arrives a line at a time, so this cannot be a StdioCollector -
    // that waits for the process to end, which is exactly what we are waiting
    // through.
    stdout: SplitParser { onRead: function (line) { root.applyBuildEvent(line) } }
    stderr: SplitParser { onRead: function (line) { root.buildStderr = String(line) } }
    onExited: function (code, status) { root.finishBuild(code) }
  }
  Process {
    id: recentsProcess
    command: ["python3", root.engine, "recents", "list", "--json"]
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.applyRecents(text) }
  }
  Process {
    id: searchProcess
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.applyResults(text) }
  }
  Process {
    id: panelProcess
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.applyPanel(text) }
    onExited: root.loadingIdent = ""
  }
  Process {
    id: liveProcess
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.applyLive(text) }
    onExited: root.liveLoading = false
  }
  Process {
    id: fboProcess
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (root.fboIdent !== root.currentIdent) return
        try { root.fbo = JSON.parse(String(text || "{}")) } catch (e) { root.fbo = null }
      }
    }
    onExited: root.fboLoading = false
  }
  Process {
    id: amenitiesProcess
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (root.amenitiesIdent !== root.currentIdent) return
        try { root.amenities = JSON.parse(String(text || "{}")) } catch (e) { root.amenities = null }
      }
    }
    onExited: root.amenitiesLoading = false
  }
  Process {
    id: trafficProcess
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (root.trafficIdent !== root.currentIdent) return
        try { root.traffic = JSON.parse(String(text || "{}")) } catch (e) { root.traffic = null }
      }
    }
    onExited: root.trafficLoading = false
  }
  Process { id: pinProcess }
  Process {
    id: forgetProcess
    onExited: root.loadRecents()
  }
  Process { id: editorProcess }

  Process {
    id: pdfProcess
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.applyChart(text) }
  }


  FileView {
    id: notesFile
    path: root.airportData ? (root.airportData.notes_path || "") : ""
    watchChanges: true
    printErrors: false
    onLoaded: root.applyNotes(text())
    onFileChanged: reload()
    // No notes file yet is the normal state for most airports, not an error.
    onLoadFailed: root.applyNotes("")
  }
  Process { id: touchProcess }

  // ---- window -------------------------------------------------------------

  PanelWindow {
    visible: root.opened
    color: "transparent"
    WlrLayershell.namespace: "omarchy-airport"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: root.opened ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
    anchors { top: true; bottom: true; left: true; right: true }

    Rectangle {
      anchors.fill: parent
      color: Color.menu.scrim
      MouseArea { anchors.fill: parent; onClicked: root.close() }

      Rectangle {
        id: card
        anchors.centerIn: parent
        width: Math.min(parent.width - Style.space(80), Style.space(940))
        height: Math.min(parent.height - Style.space(80), Style.space(620))
        radius: Style.cornerRadius
        color: Color.menu.background
        border.color: Color.menu.border
        border.width: Style.normalBorderWidth
        MouseArea { anchors.fill: parent }

        Row {
          id: mainRow
          visible: root.cacheReady
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.margins: Style.space(18)
          // Stop above the footer so the rail divider never runs through it.
          anchors.bottom: footer.top
          anchors.bottomMargin: Style.space(10)
          spacing: Style.space(18)

          // ================= left rail =================
          Column {
            id: rail
            width: Style.space(210)
            height: parent.height
            spacing: Style.space(10)

            TextField {
              id: input
              width: parent.width
              placeholderText: "Search airport, city or state…"
              foreground: Color.menu.text
              accent: Color.accent
              font.family: Style.font.family
              font.pixelSize: Style.font.body
              text: root.query
              onTextChanged: root.query = text

              // While a chart is up it owns the keys: Esc backs out to the
              // airport rather than closing the panel, and the arrows page and
              // scroll the chart instead of moving the airport underneath it.
              Keys.onEscapePressed: root.chartOpen ? root.closeChart() : root.close()
              Keys.onDownPressed: function (event) {
                if (root.chartOpen) chartLoader.item ? chartLoader.item.scrollBy(120) : null
                else if (event.modifiers & Qt.ControlModifier) root.scrollBody(60)
                else root.moveSelection(1)
              }
              Keys.onUpPressed: function (event) {
                if (root.chartOpen) chartLoader.item ? chartLoader.item.scrollBy(-120) : null
                else if (event.modifiers & Qt.ControlModifier) root.scrollBody(-60)
                else root.moveSelection(-1)
              }
              Keys.onLeftPressed: root.chartOpen ? root.chartStep(-1) : root.moveTab(-1)
              Keys.onRightPressed: root.chartOpen ? root.chartStep(1) : root.moveTab(1)
              Keys.onPressed: function (event) {
                if (root.chartOpen && (event.key === Qt.Key_Plus
                    || event.key === Qt.Key_Equal)) {
                  root.chartZoomBy(1.25); event.accepted = true; return
                }
                if (root.chartOpen && event.key === Qt.Key_Minus) {
                  root.chartZoomBy(0.8); event.accepted = true; return
                }
                if (root.chartOpen && event.key === Qt.Key_I) {
                  if (chartLoader.item) chartLoader.item.toggleInvert(); event.accepted = true; return
                }
                if (root.chartOpen && event.key === Qt.Key_0) {
                  if (chartLoader.item) chartLoader.item.resetZoom(); event.accepted = true; return
                }
                if (root.chartOpen && (event.key === Qt.Key_PageDown
                    || event.key === Qt.Key_PageUp)) {
                  if (chartLoader.item)
                    chartLoader.item.scrollBy(event.key === Qt.Key_PageDown
                                              ? chartLoader.height * 0.9
                                              : -chartLoader.height * 0.9)
                  event.accepted = true; return
                }
                // Tab walks the concourse filter on the Amenities page. The
                // arrows are already spoken for by the airport list, so the
                // page's own filter needs a key of its own.
                if (root.tab === root.tabAmenities
                    && (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab)) {
                  root.cycleTerminal(event.key === Qt.Key_Backtab ? -1 : 1)
                  event.accepted = true
                  // Same key on Traffic, same reason: the page has a view of
                  // its own to switch and the arrows are already spoken for.
                } else if (root.tab === root.tabTraffic
                           && (event.key === Qt.Key_Tab || event.key === Qt.Key_Backtab)) {
                  root.trafficMap = !root.trafficMap
                  event.accepted = true
                } else if (root.tab === root.tabTraffic
                           && (event.key === Qt.Key_BracketLeft
                               || event.key === Qt.Key_BracketRight)) {
                  root.stepTrafficRange(event.key === Qt.Key_BracketRight ? 1 : -1)
                  event.accepted = true
                } else if (event.key === Qt.Key_Delete
                           && (event.modifiers & Qt.ShiftModifier)) {
                  root.forgetSelected()
                  event.accepted = true
                } else if (event.key === Qt.Key_D && (event.modifiers & Qt.ControlModifier)) {
                  root.toggleFavourite(root.selectedIdent)
                  event.accepted = true
                } else if (event.key === Qt.Key_PageDown) {
                  root.scrollBody(bodyScroll.height * 0.9)
                  event.accepted = true
                } else if (event.key === Qt.Key_PageUp) {
                  root.scrollBody(-bodyScroll.height * 0.9)
                  event.accepted = true
                  // Ctrl+arrows scroll the page a line at a time, and
                  // Ctrl+Home/End jump to its ends. Plain Home/End are left
                  // to the search field, which needs them for editing.
                } else if ((event.modifiers & Qt.ControlModifier)
                           && event.key === Qt.Key_Home) {
                  bodyScroll.contentY = 0
                  event.accepted = true
                } else if ((event.modifiers & Qt.ControlModifier)
                           && event.key === Qt.Key_End) {
                  root.scrollBody(bodyScroll.contentHeight)
                  event.accepted = true
                }
              }
              Keys.onReturnPressed: {
                if (root.selectedIdent) root.commit(root.selectedIdent)
                else if (root.railItems.length > 0)
                  root.commit(root.railItems[0].ident || root.railItems[0].id)
              }
            }

            PanelSectionHeader {
              text: root.searching ? "RESULTS" : "RECENT"
              foreground: Color.menu.text
            }

            Flickable {
              id: railScroll
              width: parent.width
              height: rail.height - y
              contentWidth: width
              contentHeight: railColumn.implicitHeight
              clip: true
              boundsBehavior: Flickable.StopAtBounds
              interactive: contentHeight > height

              Column {
                id: railColumn
                width: railScroll.width
                spacing: Style.space(1)

                Text {
                  visible: root.railItems.length === 0
                  width: parent.width
                  wrapMode: Text.WordWrap
                  text: root.searching ? "No match."
                    : "Nothing yet — search for an airport to get started."
                  color: Color.muted
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                }

                Repeater {
                  model: root.railItems

                  delegate: Rectangle {
                    required property var modelData
                    readonly property string rowIdent: modelData.ident || modelData.id

                    width: railColumn.width
                    implicitHeight: rowCol.implicitHeight + Style.space(10)
                    radius: Style.cornerRadius
                    color: rowIdent === root.selectedIdent ? Style.selectedFill
                      : (rowMouse.containsMouse ? Style.hoverFill : "transparent")

                    Column {
                      id: rowCol
                      anchors.verticalCenter: parent.verticalCenter
                      anchors.left: parent.left
                      anchors.leftMargin: Style.space(8)
                      anchors.right: pinBtn.left
                      anchors.rightMargin: Style.space(4)
                      spacing: 0

                      Text {
                        textFormat: Text.PlainText
                        text: rowIdent
                        color: Color.menu.text
                        font.family: "monospace"
                        font.pixelSize: Style.font.bodySmall
                        font.bold: true
                      }
                      Text {
                        width: parent.width
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                        text: modelData.name || ""
                        color: Color.muted
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                      }
                    }

                    Text {
                      id: pinBtn
                      anchors.verticalCenter: parent.verticalCenter
                      anchors.right: parent.right
                      anchors.rightMargin: Style.space(6)
                      text: root.isFavourite(rowIdent) ? "★" : "☆"
                      color: root.isFavourite(rowIdent) ? Color.accent : Color.muted
                      opacity: root.isFavourite(rowIdent) ? 1.0
                        : (rowMouse.containsMouse ? 0.9 : 0.35)
                      font.pixelSize: Style.font.body

                      MouseArea {
                        anchors.fill: parent
                        anchors.margins: -Style.space(4)
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.toggleFavourite(rowIdent)
                      }
                    }

                    MouseArea {
                      id: rowMouse
                      anchors.fill: parent
                      anchors.rightMargin: Style.space(22)
                      hoverEnabled: true
                      cursorShape: Qt.PointingHandCursor
                      onClicked: root.commit(rowIdent)
                    }
                  }
                }
              }
            }
          }

          Rectangle { width: 1; height: parent.height; color: Color.menu.border }

          // ================= detail =================
          Column {
            width: parent.width - rail.width - Style.space(37)
            height: parent.height
            spacing: Style.space(12)

            // ---- header (same for every audience) ----
            Column {
              width: parent.width
              spacing: Style.space(3)
              visible: !!root.header

              // The header sits above every page, so every line it takes is a
              // line the page below loses. Six stacked rows became three: the
              // name reads across from the identifier, the clock uses the
              // right-hand space that was empty, and the facts that each had a
              // row - ICAO, place, elevation - share one muted line.
              Item {
                width: parent.width
                height: Math.max(identText.implicitHeight, clockCol.implicitHeight)

                Text {
                  id: identText
                  anchors.left: parent.left
                  anchors.verticalCenter: parent.verticalCenter
                  textFormat: Text.PlainText
                  text: (root.header && root.header.ident) || ""
                  color: Color.menu.text
                  font.family: Style.font.family
                  font.pixelSize: Style.font.displayLarge
                  font.bold: true
                }

                // Reads across from the identifier rather than under it, and
                // gives way to the clock rather than sliding beneath it.
                Text {
                  anchors.left: identText.right
                  anchors.leftMargin: Style.space(10)
                  anchors.right: clockCol.left
                  anchors.rightMargin: Style.space(12)
                  anchors.baseline: identText.baseline
                  elide: Text.ElideRight
                  textFormat: Text.PlainText
                  text: (root.header && root.header.name) || ""
                  color: Color.menu.text
                  font.family: Style.font.family
                  font.pixelSize: Style.font.title
                }

                // What time it is where you are going. Absent entirely when
                // the zone was never established - a wrong hour is worse than
                // no hour - and the name simply takes the space back.
                Column {
                  id: clockCol
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: 0
                  visible: !!Model.localClock(root.localTime, root.clockTick)

                  Text {
                    anchors.right: parent.right
                    textFormat: Text.PlainText
                    text: Model.localClock(root.localTime, root.clockTick)
                    color: Color.menu.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                    font.bold: true
                  }
                  Text {
                    anchors.right: parent.right
                    textFormat: Text.PlainText
                    text: Model.localDate(root.localTime, root.clockTick)
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                  }
                }
              }

              Row {
                width: parent.width
                spacing: Style.space(8)

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  textFormat: Text.PlainText
                  text: Model.headerFacts(root.header)
                  color: Color.muted
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                }

                // The flight category was a filled pill, which made the one
                // thing on the page that is only ever a hint shout louder than
                // the airport's own name. A dot carries the same colour and
                // asks for none of the attention.
                Rectangle {
                  anchors.verticalCenter: parent.verticalCenter
                  visible: !!(root.header && root.header.category)
                  width: Style.space(8)
                  height: width
                  radius: width / 2
                  color: Model.categoryColor(
                    (root.header && root.header.category) || "", Color.muted)
                }

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  visible: !!(root.header && root.header.category)
                  textFormat: Text.PlainText
                  text: root.header ? (root.header.category || "") : ""
                  color: Color.muted
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                  font.bold: true
                }
              }

              Text {
                width: parent.width
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                textFormat: Text.PlainText
                visible: !!(root.header && root.header.conditions)
                text: (root.header && root.header.conditions) || ""
                color: Color.menu.text
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
              }

              // Where the airport goes when you leave. In the header because
              // every page has the same answer, and Flow so a narrow panel
              // wraps them instead of clipping.
              Flow {
                visible: !!root.header
                width: parent.width
                spacing: Style.space(12)

                Repeater {
                  model: Model.linkRows(root.airportData)
                  delegate: Text {
                    required property var modelData
                    textFormat: Text.RichText
                    text: "<a href='" + Model.safeUrl(modelData.url) + "' style='color:"
                      + Color.accent + ";text-decoration:none'>"
                      + Model.escapeHtml(modelData.label) + "</a>"
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    onLinkActivated: function (link) { root.openLink(link) }
                    MouseArea {
                      anchors.fill: parent
                      acceptedButtons: Qt.NoButton
                      cursorShape: Qt.PointingHandCursor
                    }
                  }
                }
              }
            }

            Text {
              visible: !root.header
              width: parent.width
              wrapMode: Text.WordWrap
              text: root.loadingIdent !== "" ? "Loading " + root.loadingIdent + "…"
                : "Search for an airport, or pick one from the list."
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }

            // ---- tabs ----
            // Nine of them at twenty units of padding each spent a quarter of
            // the bar on empty space, which pushed the row onto a second line.
            // Every name is doing work and none abbreviates without losing
            // something, so the padding gives way rather than the words.
            Flow {
              visible: !!root.header
              width: parent.width
              spacing: Style.space(3)

              Repeater {
                model: root.tabNames
                delegate: Rectangle {
                  required property string modelData
                  required property int index
                  radius: Style.cornerRadius
                  implicitWidth: tabLabel.implicitWidth + Style.space(12)
                  implicitHeight: tabLabel.implicitHeight + Style.space(8)
                  color: index === root.tab ? Style.selectedFill
                    : (tabMouse.containsMouse ? Style.hoverFill : "transparent")

                  Text {
                    id: tabLabel
                    anchors.centerIn: parent
                    text: modelData
                    color: index === root.tab ? Color.menu.selectedText : Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: index === root.tab
                  }
                  MouseArea {
                    id: tabMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.tab = index
                  }
                }
              }
            }

            Rectangle {
              visible: !!root.header
              width: parent.width
              height: 1
              color: Color.menu.border

              Rectangle {
                height: 1
                width: parent.width * 0.35
                color: Color.accent
                opacity: root.showBusy ? 0.9 : 0
                Behavior on opacity { NumberAnimation { duration: 160 } }
                SequentialAnimation on x {
                  running: root.showBusy
                  loops: Animation.Infinite
                  NumberAnimation { from: 0; to: parent.width * 0.65; duration: 700
                                    easing.type: Easing.InOutQuad }
                  NumberAnimation { from: parent.width * 0.65; to: 0; duration: 700
                                    easing.type: Easing.InOutQuad }
                }
              }
            }

            // ---- tab content ----
            Item {
              width: parent.width
              height: parent.height - y

            Flickable {
              id: bodyScroll
              anchors.fill: parent
              contentWidth: width
              contentHeight: body.implicitHeight
              clip: true
              boundsBehavior: Flickable.StopAtBounds
              interactive: contentHeight > height

              Column {
                id: body
                width: bodyScroll.width
                spacing: Style.space(8)

                // ============ 0 SUMMARY ============
                Column {
                  visible: root.tab === 0
                  width: parent.width
                  spacing: Style.space(5)

                  Repeater {
                    model: Model.summaryRows(root.summary, root.header)
                    delegate: Row {
                      required property var modelData
                      visible: !!modelData.v
                      width: body.width
                      spacing: Style.space(10)
                      Text {
                        width: Style.space(126)
                        textFormat: Text.PlainText
                        text: modelData.k
                        color: Color.muted
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                      }
                      Text {
                        width: parent.width - Style.space(136)
                        wrapMode: Text.WordWrap
                        textFormat: Text.PlainText
                        text: modelData.v
                        color: modelData.pending ? Color.muted : Color.menu.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        font.italic: modelData.pending === true
                        font.bold: modelData.accent === true
                      }
                    }
                  }

                  Item { width: 1; height: Style.space(6) }

                  Row {
                    spacing: Style.space(14)
                  }

                  Item { width: 1; height: Style.space(4) }

                  // The Summary is the one page with no section headers, which
                  // was fine when it was a single table. It is not fine now
                  // that a coloured bar sits under it with nothing saying what
                  // the colours are about.
                  PanelSectionHeader {
                    visible: Model.outlookSegments(root.outlook).length > 0
                    text: "WEATHER"
                    foreground: Color.menu.text
                  }

                  // ---- forecast at a glance ----
                  // The same band as the Weather page, captioned so it reads
                  // without a licence: what the sky is doing now, when that
                  // changes, and what the colours stand for.
                  Item {
                    visible: Model.outlookSegments(root.outlook).length > 0
                    width: parent.width
                    height: glanceCol.implicitHeight

                    Column {
                      id: glanceCol
                      width: parent.width
                      spacing: Style.space(5)

                      Text {
                        width: parent.width
                        wrapMode: Text.WordWrap
                        textFormat: Text.PlainText
                        text: Model.outlookHeadline(root.outlook, root.clockTick)
                        color: Color.menu.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                      }

                      Item {
                        width: parent.width
                        height: Style.space(19)

                        readonly property real nowFraction:
                          Model.outlookNow(root.outlook, root.clockTick)

                        Rectangle {
                          id: glanceBand
                          width: parent.width
                          height: Style.space(8)
                          radius: Style.space(2)
                          color: Color.menu.border
                          clip: true

                          Repeater {
                            model: Model.outlookSegments(root.outlook)
                            delegate: Rectangle {
                              required property var modelData
                              x: glanceBand.width * modelData.offset
                              width: Math.max(1, glanceBand.width * modelData.fraction)
                              height: glanceBand.height
                              color: Model.categoryColor(modelData.category, Color.muted)
                            }
                          }
                        }

                        Rectangle {
                          visible: parent.nowFraction >= 0
                          x: glanceBand.width * parent.nowFraction - width / 2
                          y: -Style.space(2)
                          width: Style.space(2)
                          height: glanceBand.height + Style.space(4)
                          radius: width / 2
                          color: Color.menu.text
                          border.color: Color.menu.background
                          border.width: 1
                          Behavior on x { NumberAnimation { duration: 400 } }
                        }

                        Text {
                          visible: parent.nowFraction >= 0
                          x: Math.min(glanceBand.width - implicitWidth,
                                      Math.max(0, glanceBand.width * parent.nowFraction
                                                  - implicitWidth / 2))
                          y: glanceBand.height + Style.space(3)
                          textFormat: Text.PlainText
                          text: "now"
                          color: Color.muted
                          font.family: Style.font.family
                          font.pixelSize: Style.font.caption
                        }

                        Repeater {
                          model: Model.outlookTicks(root.outlook, root.clockTick)
                          delegate: Text {
                            required property var modelData
                            visible: modelData.relative !== ""
                            x: Math.min(glanceBand.width - implicitWidth,
                                        Math.max(0, glanceBand.width * modelData.offset
                                                    - implicitWidth / 2))
                            y: glanceBand.height + Style.space(3)
                            textFormat: Text.PlainText
                            text: modelData.relative
                            color: Color.muted
                            font.family: "monospace"
                            font.pixelSize: Style.font.caption
                          }
                        }
                      }

                      // What the colours stand for - only the ones this
                      // forecast actually uses.
                      Row {
                        width: parent.width
                        spacing: Style.space(12)

                        Repeater {
                          model: Model.outlookLegend(root.outlook)
                          delegate: Row {
                            required property var modelData
                            spacing: Style.space(5)

                            Rectangle {
                              anchors.verticalCenter: parent.verticalCenter
                              width: Style.space(8)
                              height: Style.space(8)
                              radius: Style.space(2)
                              color: Model.categoryColor(modelData.category, Color.muted)
                            }
                            Text {
                              anchors.verticalCenter: parent.verticalCenter
                              textFormat: Text.PlainText
                              text: modelData.text
                              color: Color.muted
                              font.family: Style.font.family
                              font.pixelSize: Style.font.caption
                            }
                          }
                        }
                      }
                    }
                  }

                  Item {
                    width: 1
                    height: Style.space(6)
                    visible: Model.outlookSegments(root.outlook).length > 0
                  }

                  // Advisories are not weather. Without a header of their own
                  // they read as the tail of the block above. One heading over
                  // both because a ground stop, a NOTAM and a TFR are the same
                  // question to whoever is reading: is anything in my way?
                  PanelSectionHeader {
                    visible: !!(root.status && root.status.available)
                      || !!Model.tfrNote(root.tfr, root.header ? root.header.us : true)
                      || !!(root.weather && root.weather.pending)
                    text: "ADVISORIES"
                    foreground: Color.menu.text
                  }

                  // The delay and TFR lines below arrive with the live fetch.
                  // Without this the bottom of the page is simply blank and
                  // then is not, with nothing to say which it was.
                  Text {
                    visible: !!(root.weather && root.weather.pending)
                    width: parent.width
                    textFormat: Text.PlainText
                    text: "Checking conditions, delays and TFRs…"
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    font.italic: true
                  }

                  // ---- what the FAA is reporting right now ----
                  // Above the TFR line because a ground stop is the thing that
                  // changes your day, and it is the reason a traveller opened
                  // this page at all.
                  Repeater {
                    model: Model.statusLines(root.status, String(Color.accent))
                    delegate: Text {
                      required property var modelData
                      width: parent.width
                      wrapMode: Text.WordWrap
                      // Rich text for the advisory link only; every part of it
                      // is escaped in Model.statusLines.
                      textFormat: Text.RichText
                      text: modelData.html
                      color: modelData.alert ? Color.menu.text : Color.muted
                      font.family: Style.font.family
                      font.pixelSize: modelData.alert ? Style.font.body
                                                      : Style.font.caption
                      font.bold: modelData.alert === true

                      // Text.onLinkActivated never fires for these rows: they
                      // sit inside the body Flickable, which takes the press
                      // first. So the click is handled here, and the press is
                      // only accepted when the pointer is actually on a link -
                      // anywhere else it falls through and still scrolls.
                      MouseArea {
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: parent.linkAt(mouseX, mouseY)
                          ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onPressed: function (mouse) {
                          mouse.accepted = !!parent.linkAt(mouse.x, mouse.y)
                        }
                        onClicked: function (mouse) {
                          var link = parent.linkAt(mouse.x, mouse.y)
                          if (link) root.openLink(link)
                        }
                      }
                    }
                  }

                  Item {
                    width: 1
                    height: Style.space(4)
                    visible: Model.statusLines(root.status, '').length > 0
                  }

                  // Its own heading under the one above: a delay program and
                  // a flight restriction are both advisories, but they are not
                  // the same kind of thing and the list below needs saying
                  // what it is. Muted, so it reads as a part of ADVISORIES
                  // rather than a section beside it.
                  PanelSectionHeader {
                    visible: !!Model.tfrNote(root.tfr, root.header ? root.header.us : true)
                    text: "TEMPORARY FLIGHT RESTRICTIONS"
                    foreground: Color.muted
                  }

                  // Nearest first, in columns. Only the distance is emphasised
                  // - it is the column anyone actually scans - and everything
                  // else sits back, so nine restrictions at once read as a
                  // list rather than a wall.
                  Repeater {
                    model: Model.tfrRows(root.tfr, root.header ? root.header.us : true,
                                         String(Color.accent))
                    delegate: Row {
                      required property var modelData
                      width: parent.width
                      spacing: Style.space(8)

                      Text {
                        width: Style.space(54)
                        horizontalAlignment: Text.AlignRight
                        textFormat: Text.PlainText
                        text: modelData.near
                        // Inside a presidential restriction is the one thing
                        // on this page worth a colour of its own.
                        color: modelData.inside ? Color.urgent : Color.menu.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        font.bold: true
                      }

                      Text {
                        width: Style.space(66)
                        elide: Text.ElideRight
                        textFormat: Text.PlainText
                        text: modelData.kind
                        color: Color.muted
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                      }

                      Text {
                        width: parent.width - Style.space(54 + 66 + 16)
                        wrapMode: Text.WordWrap
                        // Escaped in Model.tfrRows; rich text is for the link
                        // and the italic date.
                        textFormat: Text.RichText
                        text: modelData.html
                        color: Color.menu.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall

                        // Text.onLinkActivated never fires for these rows: they
                        // sit inside the body Flickable, which takes the press
                        // first. So the click is handled here, and the press is
                        // only accepted when the pointer is actually on a link -
                        // anywhere else it falls through and still scrolls.
                        MouseArea {
                          anchors.fill: parent
                          hoverEnabled: true
                          cursorShape: parent.linkAt(mouseX, mouseY)
                            ? Qt.PointingHandCursor : Qt.ArrowCursor
                          onPressed: function (mouse) {
                            mouse.accepted = !!parent.linkAt(mouse.x, mouse.y)
                          }
                          onClicked: function (mouse) {
                            var link = parent.linkAt(mouse.x, mouse.y)
                            if (link) root.openLink(link)
                          }
                        }
                      }
                    }
                  }

                  // Always shown, including when there is nothing near, since
                  // "none within 50 nm" is the answer the heading just asked for.
                  Text {
                    visible: !!Model.tfrNote(root.tfr, root.header ? root.header.us : true)
                    width: parent.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.RichText
                    text: Model.tfrNote(root.tfr, root.header ? root.header.us : true,
                                        String(Color.accent))
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption

                    // Text.onLinkActivated never fires for these rows: they
                    // sit inside the body Flickable, which takes the press
                    // first. So the click is handled here, and the press is
                    // only accepted when the pointer is actually on a link -
                    // anywhere else it falls through and still scrolls.
                    MouseArea {
                      anchors.fill: parent
                      hoverEnabled: true
                      cursorShape: parent.linkAt(mouseX, mouseY)
                        ? Qt.PointingHandCursor : Qt.ArrowCursor
                      onPressed: function (mouse) {
                        mouse.accepted = !!parent.linkAt(mouse.x, mouse.y)
                      }
                      onClicked: function (mouse) {
                        var link = parent.linkAt(mouse.x, mouse.y)
                        if (link) root.openLink(link)
                      }
                    }
                  }

                  Item { width: 1; height: Style.space(4) }

                  Text {
                    visible: !!(root.airportData && root.airportData.notes)
                    width: parent.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.MarkdownText
                    text: (root.airportData && root.airportData.notes)
                      ? root.airportData.notes.replace(/^#.*\n/, "").trim() : ""
                    color: Color.menu.text
                    linkColor: Color.accent
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                  }
                }

                // ============ 1 WEATHER ============
                Column {
                  visible: root.tab === 1
                  width: parent.width
                  spacing: Style.space(5)

                  Text {
                    visible: !!(root.weather && root.weather.unreachable)
                    width: parent.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    text: "Could not reach the weather service. This says nothing "
                      + "about the airport - only that the report did not arrive."
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                  }

                  Text {
                    visible: !!(root.weather && root.weather.pending)
                    width: parent.width
                    textFormat: Text.PlainText
                    text: "Fetching current conditions…"
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                  }

                  Text {
                    // Only once the fetch has actually come back - an absent
                    // report and one still in flight are not the same claim.
                    visible: !!(root.weather && !root.weather.available
                                && !root.weather.pending && !root.weather.unreachable)
                    width: parent.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    text: "No weather station reports for this airport."
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                  }

                  Repeater {
                    model: Model.weatherRows(root.weather, root.header)
                    delegate: Row {
                      required property var modelData
                      visible: !!modelData.v
                      width: body.width
                      spacing: Style.space(10)
                      Text {
                        width: Style.space(126)
                        textFormat: Text.PlainText
                        text: modelData.k
                        color: Color.muted
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                      }
                      Text {
                        width: parent.width - Style.space(136)
                        wrapMode: Text.WordWrap
                        textFormat: Text.PlainText
                        text: modelData.v
                        color: modelData.accent ? Model.categoryColor((root.weather && root.weather.category) || "", Color.menu.text) : Color.menu.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        font.bold: modelData.accent === true
                      }
                    }
                  }

                  Item { width: 1; height: Style.space(6) }
                  PanelSeparator { width: parent.width; foreground: Color.menu.text }
                  Item { width: 1; height: Style.space(6) }

                  PanelSectionHeader {
                    text: "RAW OBSERVATION"
                    foreground: Color.menu.text
                  }
                  Text {
                    visible: !!(root.weather && root.weather.raw)
                    width: parent.width
                    wrapMode: Text.WrapAnywhere
                    textFormat: Text.PlainText
                    text: (root.weather && root.weather.raw) || ""
                    color: Color.muted
                    font.family: "monospace"
                    font.pixelSize: Style.font.bodySmall
                  }
                  Item { width: 1; height: Style.space(8) }

                  // ---- forecast timeline ----
                  // The TAF was already being downloaded and shown only as its
                  // raw bulletin. Laid out as a band, it answers the question
                  // both audiences actually have: when does this change.
                  PanelSectionHeader {
                    visible: Model.outlookSegments(root.outlook).length > 0
                    text: "FORECAST TIMELINE"
                    foreground: Color.menu.text
                  }

                  Item {
                    visible: Model.outlookSegments(root.outlook).length > 0
                    width: parent.width
                    height: Style.space(62)

                    readonly property real nowFraction:
                      Model.outlookNow(root.outlook, root.clockTick)

                    Rectangle {
                      id: outlookBand
                      y: Style.space(14)
                      width: parent.width
                      height: Style.space(14)
                      radius: Style.space(3)
                      color: Color.menu.border
                      clip: true

                      Repeater {
                        model: Model.outlookSegments(root.outlook)
                        delegate: Rectangle {
                          required property var modelData
                          x: outlookBand.width * modelData.offset
                          width: Math.max(1, outlookBand.width * modelData.fraction)
                          height: outlookBand.height
                          color: Model.categoryColor(modelData.category, Color.muted)

                          PanelToolTip {
                            visible: segHover.hovered
                            text: modelData.from + "-" + modelData.to
                              + "  " + modelData.category
                          }
                          HoverHandler { id: segHover }
                        }
                      }
                    }

                    // ---- now ----
                    // Sits over the band rather than inside it, so it is not
                    // clipped and reads against whatever category it lands on.
                    Rectangle {
                      visible: parent.nowFraction >= 0
                      x: outlookBand.width * parent.nowFraction - width / 2
                      y: outlookBand.y - Style.space(3)
                      width: Style.space(2)
                      height: outlookBand.height + Style.space(6)
                      radius: width / 2
                      color: Color.menu.text
                      border.color: Color.menu.background
                      border.width: 1
                      Behavior on x { NumberAnimation { duration: 400 } }
                    }

                    Text {
                      id: nowLabel
                      visible: parent.nowFraction >= 0
                      x: Math.min(outlookBand.width - implicitWidth,
                                  Math.max(0, outlookBand.width * parent.nowFraction
                                              - implicitWidth / 2))
                      y: 0
                      textFormat: Text.PlainText
                      text: "now"
                      color: Color.menu.text
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      Behavior on x { NumberAnimation { duration: 400 } }
                    }

                    Repeater {
                      model: Model.outlookTicks(root.outlook, root.clockTick)
                      delegate: Column {
                        required property var modelData
                        x: Math.min(outlookBand.width - width,
                                    Math.max(0, outlookBand.width * modelData.offset
                                                - width / 2))
                        y: outlookBand.y + outlookBand.height + Style.space(3)
                        spacing: 0

                        Text {
                          anchors.horizontalCenter: parent.horizontalCenter
                          textFormat: Text.PlainText
                          text: modelData.label
                          color: Color.muted
                          font.family: "monospace"
                          font.pixelSize: Style.font.caption
                        }
                        Text {
                          anchors.horizontalCenter: parent.horizontalCenter
                          visible: modelData.relative !== ""
                          textFormat: Text.PlainText
                          text: modelData.relative
                          color: Color.muted
                          opacity: 0.7
                          font.family: "monospace"
                          font.pixelSize: Style.font.caption
                        }
                      }
                    }
                  }

                  Repeater {
                    model: Model.outlookRows(root.outlook)
                    delegate: Row {
                      required property var modelData
                      width: parent.width
                      spacing: Style.space(10)

                      Text {
                        width: Style.space(104)
                        textFormat: Text.PlainText
                        text: modelData.time
                        color: Color.muted
                        font.family: "monospace"
                        font.pixelSize: Style.font.bodySmall
                      }
                      Text {
                        width: Style.space(46)
                        textFormat: Text.PlainText
                        text: modelData.category
                        color: Model.categoryColor(modelData.category, Color.menu.text)
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        font.bold: true
                      }
                      Text {
                        width: parent.width - Style.space(180)
                        wrapMode: Text.WordWrap
                        textFormat: Text.PlainText
                        text: (modelData.tag ? modelData.tag + " — " : "") + modelData.text
                        color: Color.menu.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                      }
                    }
                  }

                  Item {
                    width: 1
                    height: Style.space(8)
                    visible: Model.outlookSegments(root.outlook).length > 0
                  }

                  PanelSectionHeader {
                    text: "FORECAST"
                    foreground: Color.menu.text
                  }
                  Text {
                    visible: !!(root.weather && root.weather.taf)
                    width: parent.width
                    wrapMode: Text.WrapAnywhere
                    textFormat: Text.PlainText
                    text: root.weather ? Model.tafLines(root.weather.taf) : ""
                    color: Color.muted
                    font.family: "monospace"
                    font.pixelSize: Style.font.bodySmall
                  }

                  Item { width: 1; height: Style.space(10) }
                }

                // ============ 2 TRAFFIC ============
                Column {
                  visible: root.tab === 2
                  width: parent.width
                  spacing: Style.space(4)

                  // View switch and range, clickable as well as keyed, so
                  // neither is a secret. Tab flips the view, [ and ] step the
                  // range - both said out loud in the row itself.
                  Row {
                    width: parent.width
                    spacing: Style.space(6)

                    Repeater {
                      model: [{ label: "Table", map: false }, { label: "Map", map: true }]
                      delegate: Rectangle {
                        required property var modelData
                        radius: Style.cornerRadius
                        implicitWidth: viewLabel.implicitWidth + Style.space(16)
                        implicitHeight: viewLabel.implicitHeight + Style.space(6)
                        color: modelData.map === root.trafficMap ? Style.selectedFill
                          : (viewMouse.containsMouse ? Style.hoverFill : "transparent")
                        Text {
                          id: viewLabel
                          anchors.centerIn: parent
                          text: modelData.label
                          color: modelData.map === root.trafficMap
                            ? Color.menu.selectedText : Color.muted
                          font.family: Style.font.family
                          font.pixelSize: Style.font.caption
                          font.bold: modelData.map === root.trafficMap
                        }
                        MouseArea {
                          id: viewMouse
                          anchors.fill: parent
                          hoverEnabled: true
                          cursorShape: Qt.PointingHandCursor
                          onClicked: root.trafficMap = modelData.map
                        }
                      }
                    }

                    Item { width: Style.space(10); height: 1 }

                    Repeater {
                      model: root.trafficRanges
                      delegate: Rectangle {
                        required property int modelData
                        radius: Style.cornerRadius
                        implicitWidth: rangeLabel.implicitWidth + Style.space(14)
                        implicitHeight: rangeLabel.implicitHeight + Style.space(6)
                        color: modelData === root.trafficRange ? Style.selectedFill
                          : (rangeMouse.containsMouse ? Style.hoverFill : "transparent")
                        Text {
                          id: rangeLabel
                          anchors.centerIn: parent
                          text: modelData + " nm"
                          color: modelData === root.trafficRange
                            ? Color.menu.selectedText : Color.muted
                          font.family: Style.font.family
                          font.pixelSize: Style.font.caption
                          font.bold: modelData === root.trafficRange
                        }
                        MouseArea {
                          id: rangeMouse
                          anchors.fill: parent
                          hoverEnabled: true
                          cursorShape: Qt.PointingHandCursor
                          onClicked: {
                            if (modelData === root.trafficRange) return
                            root.trafficRange = modelData
                            root.ensureTraffic(true)
                          }
                        }
                      }
                    }
                  }

                  Text {
                    width: parent.width
                    textFormat: Text.PlainText
                    text: "Tab switches view · [ and ] step the range"
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                  }

                  Item { width: 1; height: Style.space(4) }

                  Text {
                    visible: root.trafficLoading && !root.traffic
                    text: "Listening…"
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                    font.italic: true
                  }

                  // ---- the scope ----
                  // A plan view centred on the field, not a globe: 25 nm is
                  // 0.4 degrees of latitude, which on a globe drawn from any
                  // ordinary country outline is a single dot. Rings, the real
                  // runway layout from the cache, and a chevron per aircraft
                  // turned to its own track.
                  Canvas {
                    id: scope
                    visible: root.trafficMap
                    width: parent.width
                    height: visible ? Math.min(parent.width, Style.space(430)) : 0
                    renderStrategy: Canvas.Cooperative

                    property var payload: root.traffic
                    property int range: root.trafficRange
                    property var strips: (root.runwayData && root.runwayData.runways)
                      ? root.runwayData.runways : []
                    onPayloadChanged: requestPaint()
                    onRangeChanged: requestPaint()
                    onStripsChanged: requestPaint()
                    onWidthChanged: requestPaint()

                    // The drawing itself lives in Model.js so it can be
                    // rendered and checked outside a running shell.
                    onPaint: Model.paintScope(getContext("2d"), {
                      width: width, height: height,
                      payload: payload, range: range, strips: strips,
                      rings: Model.scopeRings(range),
                      pad: Style.space(16),
                      runwayWidth: Math.max(2, Style.space(3)),
                      font: Math.round(Style.font.caption) + "px " + Style.font.family,
                      muted: String(Color.muted),
                      ink: String(Color.menu.text),
                      accent: String(Color.accent)
                    })
                  }

                  Repeater {
                    model: root.trafficMap ? [] : Model.trafficGroups(root.traffic)
                    delegate: Column {
                      required property var modelData
                      width: parent.width
                      spacing: Style.space(2)

                      PanelSectionHeader {
                        text: modelData.title.toUpperCase() + "  ("
                          + modelData.count + ")"
                        foreground: Color.menu.text
                      }

                      Repeater {
                        model: modelData.rows
                        delegate: Row {
                          required property var modelData
                          width: parent.width
                          spacing: Style.space(8)

                          Text {
                            width: Style.space(80)
                            elide: Text.ElideRight
                            textFormat: Text.PlainText
                            text: modelData.call
                            color: modelData.emergency ? Color.urgent : Color.menu.text
                            font.family: Style.font.family
                            font.pixelSize: Style.font.body
                            font.bold: true
                          }
                          Text {
                            width: Style.space(40)
                            textFormat: Text.PlainText
                            text: modelData.type
                            color: Color.muted
                            font.family: Style.font.family
                            font.pixelSize: Style.font.body
                          }
                          Text {
                            textFormat: Text.PlainText
                            text: modelData.detail
                            color: Color.muted
                            font.family: Style.font.family
                            font.pixelSize: Style.font.body
                          }
                        }
                      }

                      Item { width: 1; height: Style.space(6) }
                    }
                  }

                  // Always shown, including when the list is empty, because
                  // "nothing was heard" is the part that needs explaining.
                  Text {
                    visible: !!Model.trafficNote(root.traffic)
                    width: parent.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    text: Model.trafficNote(root.traffic)
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                  }

                  Item { width: 1; height: Style.space(10) }
                }

                // ============ 3 AMENITIES ============
                Column {
                  visible: root.tab === 3
                  width: parent.width
                  spacing: Style.space(4)

                  Text {
                    visible: root.amenitiesLoading
                    text: "reading OpenStreetMap… (first look can take a minute)"
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                  }
                  Text {
                    visible: !root.amenitiesLoading && !!root.amenities
                      && (!root.amenities.pois || root.amenities.pois.length === 0)
                    width: parent.width
                    wrapMode: Text.WordWrap
                    // "Unknown", not "none": OpenStreetMap simply may not
                    // cover this field, which is not the same as an empty one.
                    text: "Unknown"
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                  }

                  // Flow, not Row: ATL has eight concourses plus the domestic
                  // terminal, which overruns a single line.
                  Flow {
                    visible: !!root.amenities && (root.amenities.pois || []).length > 0
                    width: body.width
                    spacing: Style.space(4)
                    bottomPadding: Style.space(4)
                    Repeater {
                      model: Model.terminalChips(root.amenities)
                      delegate: Rectangle {
                        required property string modelData
                        radius: Style.cornerRadius
                        implicitWidth: chipText.implicitWidth + Style.space(14)
                        implicitHeight: chipText.implicitHeight + Style.space(6)
                        color: (modelData === "All" ? root.amenityTerminal === ""
                                                    : root.amenityTerminal === modelData)
                          ? Style.selectedFill
                          : (chipMouse.containsMouse ? Style.hoverFill : "transparent")
                        border.color: Color.menu.border
                        border.width: Style.normalBorderWidth
                        Text {
                          id: chipText
                          anchors.centerIn: parent
                          text: modelData
                          color: Color.menu.text
                          font.family: Style.font.family
                          font.pixelSize: Style.font.caption
                        }
                        MouseArea {
                          id: chipMouse
                          anchors.fill: parent
                          hoverEnabled: true
                          cursorShape: Qt.PointingHandCursor
                          onClicked: root.amenityTerminal = (modelData === "All" ? "" : modelData)
                        }
                      }
                    }
                  }

                  // Column header, so the table reads as a table.
                  Row {
                    visible: !!root.amenities && (root.amenities.pois || []).length > 0
                    width: body.width
                    spacing: Style.space(10)
                    topPadding: Style.space(6)
                    PanelSectionHeader {
                      width: body.width * 0.42
                      text: "PLACE"
                      foreground: Color.menu.text
                    }
                    PanelSectionHeader {
                      width: body.width * 0.24
                      text: "TYPE"
                      foreground: Color.menu.text
                    }
                    PanelSectionHeader {
                      text: "HOURS"
                      foreground: Color.menu.text
                    }
                  }

                  Repeater {
                    model: Model.amenityRows(root.amenities, root.amenityTerminal)

                    delegate: Item {
                      required property var modelData
                      width: body.width
                      implicitHeight: modelData.heading
                        ? groupHead.implicitHeight + Style.space(14)
                        : Math.max(placeName.implicitHeight, Style.space(19))

                      // ---- concourse heading ----
                      Text {
                        id: groupHead
                        visible: modelData.heading === true
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: Style.space(2)
                        textFormat: Text.PlainText
                        text: modelData.name + "   " + modelData.count
                        color: Color.menu.selectedText
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                        font.bold: true
                        font.letterSpacing: 1.2
                      }

                      // ---- one place ----
                      Rectangle {
                        visible: !modelData.heading
                        anchors.fill: parent
                        color: rowHover.hovered ? Style.hoverFill : "transparent"
                        radius: Style.cornerRadius

                        HoverHandler { id: rowHover }

                        Row {
                          anchors.verticalCenter: parent.verticalCenter
                          anchors.left: parent.left
                          anchors.right: parent.right
                          spacing: Style.space(10)

                          Text {
                            id: placeName
                            width: body.width * 0.42
                            elide: Text.ElideRight
                            textFormat: modelData.url ? Text.RichText : Text.PlainText
                            text: Model.safeUrl(modelData.url)
                              ? ("<a href='" + Model.safeUrl(modelData.url)
                                 + "' style='color:"
                                 + (modelData.kind === "lounge" ? Color.accent : Color.menu.text)
                                 + ";text-decoration:"
                                 + (rowHover.hovered ? "underline" : "none") + "'>"
                                 + Model.escapeHtml(modelData.name) + "</a>")
                              : Model.escapeHtml(modelData.name)
                            color: Color.menu.text
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                            font.bold: modelData.kind === "lounge"
                            onLinkActivated: function (link) { root.openLink(link) }
                          }
                          Text {
                            width: body.width * 0.24
                            elide: Text.ElideRight
                            textFormat: Text.PlainText
                            text: modelData.type
                            color: Color.muted
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                          }
                          Text {
                            elide: Text.ElideRight
                            textFormat: Text.PlainText
                            text: modelData.hours
                            color: Color.muted
                            font.family: "monospace"
                            font.pixelSize: Style.font.caption
                          }
                          // Guaranteed-exact fallback for when Google guesses
                          // wrong: the OSM object this row was built from.
                          Text {
                            visible: rowHover.hovered && !!modelData.osm
                            textFormat: Text.RichText
                            text: "<a href='" + Model.safeUrl(modelData.osm)
                              + "' style='color:" + Color.muted + "'>osm</a>"
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                            onLinkActivated: function (link) { root.openLink(link) }
                          }
                        }
                      }
                    }
                  }

                  Item { width: 1; height: Style.space(6) }
                  Text {
                    visible: !!root.amenities && (root.amenities.pois || []).length > 0
                    width: body.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    text: "Amenities © OpenStreetMap contributors (ODbL). Hours go stale — "
                      + "confirm before relying on them."
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                  }
                }

                // ============ 3 RUNWAYS ============
                Column {
                  visible: root.tab === 4
                  width: parent.width
                  spacing: Style.space(1)

                  // Which way the wind is blowing, in the one form that
                  // matters on this page: which end to use.
                  Text {
                    visible: Model.favouredLine(root.runwayData, root.weather) !== ""
                    width: parent.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    text: Model.favouredLine(root.runwayData, root.weather)
                    color: Color.menu.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }

                  Item {
                    width: 1
                    height: Style.space(8)
                    visible: Model.favouredLine(root.runwayData, root.weather) !== ""
                  }

                  // The table had no labels at all: "6,549' × 150'" and "150°T"
                  // are obvious to a pilot and opaque to everyone else.
                  Row {
                    width: parent.width
                    spacing: Style.space(10)
                    visible: !!(root.runwayData
                                && (root.runwayData.runways || []).length)

                    Text {
                      width: Style.space(74)
                      text: "RUNWAY"
                      color: Color.muted
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      font.letterSpacing: 1.2
                    }
                    Text {
                      width: Style.space(120)
                      text: "SIZE"
                      color: Color.muted
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      font.letterSpacing: 1.2
                    }
                    Text {
                      width: parent.width - Style.space(214)
                      text: "SURFACE, LIGHTING AND APPROACH AIDS"
                      color: Color.muted
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                      font.bold: true
                      font.letterSpacing: 1.2
                    }
                  }

                  Repeater {
                    model: Model.runwayRows(root.runwayData)
                    delegate: Column {
                      required property var modelData
                      width: body.width
                      topPadding: modelData.runway ? Style.space(10) : 0

                      Row {
                        width: parent.width
                        spacing: Style.space(10)
                        Text {
                          width: Style.space(74)
                          horizontalAlignment: modelData.runway ? Text.AlignLeft
                                                                : Text.AlignRight
                          textFormat: Text.PlainText
                          text: modelData.id
                          color: Model.isFavouredEnd(modelData, root.runwayData,
                                                     root.weather)
                            ? Color.accent
                            : (modelData.runway ? Color.menu.text : Color.muted)
                          font.family: "monospace"
                          font.pixelSize: Style.font.bodySmall
                          font.bold: modelData.runway === true
                            || Model.isFavouredEnd(modelData, root.runwayData,
                                                   root.weather)
                        }
                        Text {
                          width: Style.space(120)
                          textFormat: Text.PlainText
                          text: modelData.dims
                          color: Color.menu.text
                          font.family: "monospace"
                          font.pixelSize: Style.font.bodySmall
                        }
                        Text {
                          width: parent.width - Style.space(214)
                          wrapMode: Text.WordWrap
                          textFormat: Text.PlainText
                          text: modelData.spec
                          color: modelData.runway ? Color.menu.text : Color.muted
                          font.family: Style.font.family
                          font.pixelSize: Style.font.bodySmall
                        }
                      }

                      Text {
                        visible: !!modelData.obstruction
                        x: Style.space(84)
                        width: parent.width - Style.space(84)
                        wrapMode: Text.WordWrap
                        textFormat: Text.PlainText
                        text: "obstruction: " + (modelData.obstruction || "")
                        color: Color.muted
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                      }
                    }
                  }

                  Text {
                    visible: !root.runwayData
                      || (root.runwayData.runways || []).length === 0
                    width: parent.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    text: "No runway data published for this airport."
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                  }

                  Item { width: 1; height: Style.space(12) }
                  PanelSeparator { width: parent.width; foreground: Color.menu.text }
                  Item { width: 1; height: Style.space(8) }

                  // Published if the FAA prints one; otherwise the standard
                  // 1,000 ft above the field, labelled as the convention it is
                  // rather than passed off as data for this airport.
                  Text {
                    visible: !!(root.runwayData
                                && (root.runwayData.pattern_altitude
                                    || root.runwayData.pattern_altitude_standard))
                    width: parent.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    text: !root.runwayData ? ""
                      : (root.runwayData.pattern_altitude
                         ? "Pattern altitude   " + root.runwayData.pattern_altitude
                         : "Pattern altitude   "
                           + root.runwayData.pattern_altitude_standard
                           + "   (standard 1,000 ft above the field; none published "
                           + "for this airport)")
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                  }
                }

                // ============ 4 PROCEDURES ============
                Column {
                  visible: root.tab === 5
                  width: parent.width
                  spacing: Style.space(2)

                  Repeater {
                    model: Model.procedureRows(root.procedures, root.header ? root.header.us : true)
                    delegate: Text {
                      required property var modelData
                      width: body.width
                      elide: Text.ElideRight
                      topPadding: modelData.heading ? Style.space(12)
                        : (modelData.sub ? Style.space(6) : 0)
                      // Indent with padding, never leading spaces: RichText
                      // collapses whitespace, so a linked row would lose its
                      // indent while the plain-text heading above kept its own.
                      leftPadding: modelData.heading ? 0
                        : (modelData.sub ? Style.space(10) : Style.space(24))
                      textFormat: modelData.url ? Text.RichText : Text.PlainText
                      text: Model.safeUrl(modelData.url)
                        ? (Model.escapeHtml(modelData.label) + "   <a href='"
                           + Model.safeUrl(modelData.url)
                           + "' style='color:" + Color.accent + "'>PDF</a>")
                        : modelData.label
                      color: modelData.heading ? Color.menu.selectedText
                        : (modelData.sub || modelData.note ? Color.muted : Color.menu.text)
                      font.family: modelData.heading || modelData.note
                        ? Style.font.family : "monospace"
                      font.pixelSize: modelData.heading || modelData.note
                        ? Style.font.caption : Style.font.bodySmall
                      font.bold: modelData.heading === true
                      font.letterSpacing: modelData.heading ? 1.2 : 0
                      onLinkActivated: function (link) { root.openLink(link) }
                    }
                  }
                }

                // ============ 5 FREQUENCIES ============
                Column {
                  visible: root.tab === 6
                  width: parent.width
                  spacing: Style.space(1)

                  Repeater {
                    model: Model.frequencyRows(root.frequencies)
                    delegate: Item {
                      required property var modelData
                      width: body.width
                      implicitHeight: modelData.heading
                        ? freqHead.implicitHeight + Style.space(14)
                        : freqRow.implicitHeight + Style.space(3)

                      PanelSectionHeader {
                        id: freqHead
                        visible: modelData.heading === true
                        anchors.left: parent.left
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: Style.space(2)
                        text: modelData.label || ""
                        foreground: Color.menu.text
                      }

                      Row {
                        id: freqRow
                        visible: !modelData.heading
                        anchors.verticalCenter: parent.verticalCenter
                        width: parent.width
                        spacing: Style.space(10)
                        Text {
                          width: Style.space(96)
                          textFormat: Text.PlainText
                          text: modelData.label || ""
                          color: Color.muted
                          font.family: Style.font.family
                          font.pixelSize: Style.font.bodySmall
                        }
                        Text {
                          width: Style.space(80)
                          textFormat: Text.PlainText
                          text: modelData.freq || ""
                          color: Color.menu.text
                          font.family: "monospace"
                          font.pixelSize: Style.font.bodySmall
                          font.bold: modelData.primary === true
                        }
                        Text {
                          width: parent.width - Style.space(196)
                          elide: Text.ElideRight
                          textFormat: Text.PlainText
                          text: modelData.note || ""
                          color: Color.muted
                          font.family: Style.font.family
                          font.pixelSize: Style.font.caption
                        }
                      }
                    }
                  }

                  Text {
                    visible: !root.frequencies || (root.frequencies.field || []).length === 0
                    width: parent.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    text: root.header && root.header.us
                      ? "No frequencies published for this airport."
                      : "Frequencies come from FAA data and are not available outside the US."
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                  }

                  Item { width: 1; height: Style.space(14) }
                }

                // ============ 6 GROUND SERVICES ============
                Column {
                  visible: root.tab === 7
                  width: parent.width
                  spacing: Style.space(4)

                  Repeater {
                    model: Model.groundRows(root.ground)
                    delegate: Row {
                      required property var modelData
                      visible: !!modelData.v
                      width: body.width
                      spacing: Style.space(10)
                      Text {
                        width: Style.space(126)
                        textFormat: Text.PlainText
                        text: modelData.k
                        color: Color.muted
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                      }
                      Text {
                        width: parent.width - Style.space(136)
                        wrapMode: Text.WordWrap
                        textFormat: Text.PlainText
                        text: modelData.v
                        color: Color.menu.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        font.bold: modelData.accent === true
                      }
                    }
                  }

                  Item { width: 1; height: Style.space(8) }
                  PanelSectionHeader {
                    // PanelSectionHeader is PlainText, so this is an
                    // ampersand, not an HTML entity.
                    text: "FBOs & FUEL"
                    foreground: Color.menu.text
                  }
                  Text {
                    visible: root.fboLoading
                    text: "  checking AirNav…"
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                  }
                  Text {
                    visible: !root.fboLoading && !!root.fbo
                      && (!root.fbo.fbos || root.fbo.fbos.length === 0)
                    text: "  none listed"
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                  }
                  Repeater {
                    model: root.fbo ? (root.fbo.fbos || []) : []
                    delegate: Column {
                      required property var modelData
                      width: body.width
                      spacing: 0
                      Text {
                        textFormat: Text.PlainText
                        text: "  " + modelData.name
                          + (modelData.phone ? "   " + modelData.phone : "")
                        color: Color.menu.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        font.bold: true
                      }
                      Text {
                        visible: (modelData.prices || []).length > 0
                        textFormat: Text.PlainText
                        text: "    " + Model.fuelPrices(modelData)
                        color: Color.menu.text
                        font.family: "monospace"
                        font.pixelSize: Style.font.bodySmall
                      }
                    }
                  }
                  Item { width: 1; height: Style.space(6) }
                  Text {
                    width: body.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    text: "FBOs and fuel prices from AirNav, cached for a day. "
                      + "Ramp fees are not published anywhere."
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                  }
                }

                // ============ 7 NOTES ============
                Column {
                  visible: root.tab === 8
                  width: parent.width
                  spacing: Style.space(6)

                  Row {
                    spacing: Style.space(16)
                    Text {
                      textFormat: Text.RichText
                      text: "<a href='edit' style='color:" + Color.accent + "'>"
                        + ((root.airportData && root.airportData.notes
                            && root.airportData.notes.trim()) ? "Edit notes" : "Write a note")
                        + "</a>"
                      font.family: Style.font.family
                      font.pixelSize: Style.font.bodySmall
                      onLinkActivated: root.editNotes()
                      MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.NoButton
                        cursorShape: Qt.PointingHandCursor
                      }
                    }
                    Text {
                      textFormat: Text.RichText
                      text: "<a href='reload' style='color:" + Color.accent + "'>Reload</a>"
                      font.family: Style.font.family
                      font.pixelSize: Style.font.bodySmall
                      onLinkActivated: root.select(root.currentIdent)
                      MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.NoButton
                        cursorShape: Qt.PointingHandCursor
                      }
                    }
                  }

                  Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    // Notes are markdown on disk, so render them as markdown.
                    textFormat: (root.airportData && root.airportData.notes
                                 && root.airportData.notes.trim())
                      ? Text.MarkdownText : Text.PlainText
                    text: (root.airportData && root.airportData.notes
                           && root.airportData.notes.trim())
                      ? root.airportData.notes.trim()
                      : "No notes for this airport yet."
                    color: Color.menu.text
                    linkColor: Color.accent
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    onLinkActivated: function (link) { root.openLink(link) }
                  }

                  Text {
                    textFormat: Text.PlainText
                    text: root.airportData ? (root.airportData.notes_path || "") : ""
                    color: Color.muted
                    font.family: "monospace"
                    font.pixelSize: Style.font.caption
                  }

                  Item { width: 1; height: Style.space(8) }
                  PanelSectionHeader {
                    text: "FAA REMARKS"
                    foreground: Color.menu.text
                  }
                  Repeater {
                    model: root.airportData ? (root.airportData.remarks || []) : []
                    delegate: Text {
                      required property string modelData
                      width: body.width
                      wrapMode: Text.WordWrap
                      textFormat: Text.PlainText
                      text: "• " + modelData
                      color: Color.muted
                      font.family: Style.font.family
                      font.pixelSize: Style.font.caption
                    }
                  }
                }
              }
            }

            Rectangle {
              anchors.right: parent.right
              width: 3
              radius: 1.5
              color: Color.muted
              opacity: 0.45
              visible: bodyScroll.contentHeight > bodyScroll.height
              height: Math.max(24, bodyScroll.height
                * (bodyScroll.height / bodyScroll.contentHeight))
              y: bodyScroll.contentHeight > bodyScroll.height
                ? (bodyScroll.contentY / (bodyScroll.contentHeight - bodyScroll.height))
                  * (bodyScroll.height - height)
                : 0
            }
            }
          }
        }


        // ---- first run -------------------------------------------------
        // The FAA publishes airports, runways and charts as whole 28-day
        // files; there is no per-airport endpoint, so the first open of a
        // cycle has a download in it. Better to show it happening than to
        // present an empty panel while a subprocess works.
        Item {
          id: buildPane
          visible: !root.cacheReady
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.top: parent.top
          anchors.margins: Style.space(18)
          anchors.bottom: footer.top
          anchors.bottomMargin: Style.space(10)

          Column {
            anchors.centerIn: parent
            width: Math.min(parent.width * 0.7, Style.space(420))
            spacing: Style.space(14)

            Text {
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
              textFormat: Text.PlainText
              text: root.buildError !== "" ? "Could not build the airport data"
                                           : "Setting up airport data"
              color: Color.menu.text
              font.family: Style.font.family
              font.pixelSize: Style.font.title
              font.bold: true
            }

            Text {
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
              wrapMode: Text.WordWrap
              textFormat: Text.PlainText
              text: root.buildError !== ""
                ? root.buildError
                : "The FAA publishes one file per 28-day cycle, so this "
                  + "downloads about 40 MB once. It takes a few seconds, and "
                  + "happens again only when the cycle rolls over."
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.body
            }

            // Determinate: the engine knows how many steps there are and says
            // which one it is on, so there is no reason to show a guess.
            Rectangle {
              visible: root.buildError === ""
              anchors.horizontalCenter: parent.horizontalCenter
              width: parent.width
              height: Style.space(4)
              radius: height / 2
              color: Color.menu.border

              Rectangle {
                width: parent.width * root.buildFraction
                height: parent.height
                radius: parent.radius
                color: Color.accent
                Behavior on width {
                  NumberAnimation { duration: 320; easing.type: Easing.OutCubic }
                }
                // A step can take seconds; the pulse says the wait is alive
                // without pretending to know progress within it.
                SequentialAnimation on opacity {
                  running: root.cacheBuilding
                  loops: Animation.Infinite
                  NumberAnimation { from: 1.0; to: 0.55; duration: 750
                                    easing.type: Easing.InOutQuad }
                  NumberAnimation { from: 0.55; to: 1.0; duration: 750
                                    easing.type: Easing.InOutQuad }
                }
              }
            }

            Text {
              visible: root.buildError === ""
              width: parent.width
              horizontalAlignment: Text.AlignHCenter
              textFormat: Text.PlainText
              elide: Text.ElideRight
              text: root.buildTotal > 0
                ? root.buildLabel + " — step " + Math.max(1, root.buildStep)
                  + " of " + root.buildTotal
                : root.buildLabel
              color: Color.muted
              font.family: Style.font.family
              font.pixelSize: Style.font.caption
            }

            Rectangle {
              visible: root.buildError !== "" && !root.cacheBuilding
              anchors.horizontalCenter: parent.horizontalCenter
              implicitWidth: retryLabel.implicitWidth + Style.space(24)
              implicitHeight: retryLabel.implicitHeight + Style.space(12)
              radius: Style.cornerRadius
              color: retryArea.containsMouse ? Color.accent : "transparent"
              border.color: Color.accent
              border.width: Style.normalBorderWidth

              Text {
                id: retryLabel
                anchors.centerIn: parent
                textFormat: Text.PlainText
                text: "Try again"
                color: retryArea.containsMouse ? Color.menu.background : Color.accent
                font.family: Style.font.family
                font.pixelSize: Style.font.body
                font.bold: true
              }
              MouseArea {
                id: retryArea
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.startBuild(false)
              }
            }
          }
        }


        // ---- chart viewer ----------------------------------------------
        // Isolated in ChartView.qml: its Qt PDF and GraphicalEffects imports
        // are not present on a stock Omarchy install, and a failed import
        // takes down the file it sits in. Through a Loader, losing them costs
        // the inline viewer and nothing else.
        Loader {
          id: chartLoader
          anchors.fill: parent
          anchors.margins: Style.normalBorderWidth
          active: root.chartOpen && root.chartViewerAvailable
          visible: active && status === Loader.Ready
          source: "ChartView.qml"

          // Deferred: this handler closes the chart, and `active` is bound to
          // that, so acting inline is a binding loop.
          onStatusChanged: if (status === Loader.Error)
            Qt.callLater(root.chartViewerFailed)

          onLoaded: {
            item.path = Qt.binding(function () { return root.chartPath })
            item.title = Qt.binding(function () { return root.chartTitle })
            item.url = Qt.binding(function () { return root.chartUrl })
            item.loading = Qt.binding(function () { return root.chartLoading })
            item.error = Qt.binding(function () { return root.chartError })
            item.closeRequested.connect(root.closeChart)
            item.externalRequested.connect(function () {
              Qt.openUrlExternally(root.chartUrl)
            })
          }
        }


        // ---- footer ----
        Text {
          id: footer
          // The chart viewer covers the card and brings its own footer.
          visible: !root.chartOpen
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          anchors.margins: Style.space(18)
          textFormat: Text.PlainText
          text: root.cacheRefreshing
            ? "Updating to FAA cycle " + root.expectedCycle + " in the background — "
              + root.buildLabel.toLowerCase()
            : "↑↓ airport · ←→ page · Ctrl+D pin · "
              + (root.searching ? "" : "Shift+Del forget · ")
              + (root.tab === root.tabAmenities
                 && Model.terminalChips(root.amenities).length ? "Tab concourse · " : "")
              + "PgUp/PgDn or Ctrl+↑↓ scroll · Esc close   —   not for navigation"
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}
