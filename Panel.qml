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
  property bool showBusy: false
  property string currentIdent: ""   // what is loaded and displayed
  property string selectedIdent: ""  // what the highlight is on, may be ahead

  // Lazily fetched, because both are slow network calls.
  property var fbo: null
  property bool fboLoading: false
  property var amenities: null
  property bool amenitiesLoading: false
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
    loadRecents()
    Qt.callLater(function () { input.forceActiveFocus() })
  }

  function close() {
    root.opened = false
  }

  function toggle() { root.opened ? root.close() : root.open() }

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

  function select(ident) {
    if (!ident || ident === root.loadingIdent) return
    loadDebounce.stop()
    root.selectedIdent = ident
    root.loadingIdent = ident
    root.fbo = null
    root.amenities = null
    root.amenityFilter = ""
    root.amenityTerminal = ""
    if (panelProcess.running) panelProcess.running = false
    panelProcess.command = ["python3", root.engine, "panel", ident, "--no-record"]
    panelProcess.running = true
  }

  function applyPanel(text) {
    try {
      var parsed = JSON.parse(String(text || "{}"))
      if (parsed && parsed.header) {
        root.airportData = parsed
        root.currentIdent = parsed.header.ident
        root.selectedIdent = parsed.header.ident
        if (root.tab === root.tabAmenities || root.tab === root.tabGround)
          ensureGroundData()
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
      fboProcess.command = ["python3", root.engine, "fbo", root.currentIdent, "--json"]
      fboProcess.running = true
    }
    if (!root.amenities && !root.amenitiesLoading) {
      root.amenitiesLoading = true
      amenitiesProcess.command = ["python3", root.engine, "amenities",
                                  root.currentIdent, "--json"]
      amenitiesProcess.running = true
    }
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

  function openLink(url) { if (url) Qt.openUrlExternally(url) }

  // Chosen deliberately - record the visit and refresh the rail.
  function commit(ident) {
    if (!ident) return
    select(ident)
    touchProcess.command = ["python3", root.engine, "recents", "touch", ident]
    touchProcess.running = true
  }

  function editNotes() {
    if (!root.airportData || !root.airportData.notes_path) return
    editorProcess.command = ["omarchy-launch-editor", root.airportData.notes_path]
    editorProcess.running = true
    root.close()
  }

  function isFavourite(ident) {
    return root.favourites[ident] === true
  }

  // Flip the star immediately, persist in the background, and never reload the
  // rail: the list keeps its order and nothing redraws but the one glyph.
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
  onTabChanged: if (tab === tabAmenities || tab === tabGround) ensureGroundData()

  Timer { id: searchDebounce; interval: 180; onTriggered: root.runSearch() }
  Timer {
    id: loadDebounce
    interval: 220
    onTriggered: root.select(root.selectedIdent)
  }

  Timer {
    id: busyDelay
    interval: 250
    onTriggered: root.showBusy = root.loadingIdent !== ""
  }

  onLoadingIdentChanged: {
    if (loadingIdent === "") {
      busyDelay.stop()
      showBusy = false
    } else {
      busyDelay.restart()
    }
  }

  readonly property var tabNames: ["Summary", "Weather", "Amenities", "Runways",
                                   "Procedures", "Frequencies", "Services", "Notes"]
  readonly property int tabAmenities: 2
  readonly property int tabGround: 6
  readonly property var weather: airportData ? airportData.weather : null
  readonly property var summary: airportData ? airportData.summary : null
  readonly property var runwayData: airportData ? airportData.runways : null
  readonly property var procedures: airportData ? airportData.procedures : null
  readonly property var frequencies: airportData ? airportData.frequencies : null
  readonly property var tfr: airportData ? airportData.tfr : null

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
    id: fboProcess
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
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
        try { root.amenities = JSON.parse(String(text || "{}")) } catch (e) { root.amenities = null }
      }
    }
    onExited: root.amenitiesLoading = false
  }
  Process { id: pinProcess }
  Process { id: editorProcess }
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

              Keys.onEscapePressed: root.close()
              Keys.onDownPressed: root.moveSelection(1)
              Keys.onUpPressed: root.moveSelection(-1)
              Keys.onLeftPressed: root.moveTab(-1)
              Keys.onRightPressed: root.moveTab(1)
              Keys.onPressed: function (event) {
                if (event.key === Qt.Key_D && (event.modifiers & Qt.ControlModifier)) {
                  root.toggleFavourite(root.selectedIdent)
                  event.accepted = true
                } else if (event.key === Qt.Key_PageDown) {
                  bodyScroll.contentY = Math.min(
                    bodyScroll.contentY + bodyScroll.height * 0.9,
                    Math.max(0, bodyScroll.contentHeight - bodyScroll.height))
                  event.accepted = true
                } else if (event.key === Qt.Key_PageUp) {
                  bodyScroll.contentY = Math.max(0, bodyScroll.contentY - bodyScroll.height * 0.9)
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

              Row {
                spacing: Style.space(10)

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  textFormat: Text.PlainText
                  text: root.header ? root.header.ident : ""
                  color: Color.menu.text
                  font.family: Style.font.family
                  font.pixelSize: Style.font.displayLarge
                  font.bold: true
                }

                Rectangle {
                  anchors.verticalCenter: parent.verticalCenter
                  visible: !!(root.header && root.header.category)
                  radius: Style.cornerRadius
                  color: Model.categoryColor(root.header ? root.header.category : "", Color.muted)
                  implicitWidth: catText.implicitWidth + Style.space(14)
                  implicitHeight: catText.implicitHeight + Style.space(6)
                  Text {
                    id: catText
                    anchors.centerIn: parent
                    textFormat: Text.PlainText
                    text: root.header ? (root.header.category || "") : ""
                    color: Color.background
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                  }
                }

                Text {
                  anchors.verticalCenter: parent.verticalCenter
                  textFormat: Text.PlainText
                  text: root.header && root.header.elev !== null
                    ? "elev " + Model.feet(root.header.elev) : ""
                  color: Color.muted
                  font.family: Style.font.family
                  font.pixelSize: Style.font.body
                }
              }

              Text {
                width: parent.width
                elide: Text.ElideRight
                textFormat: Text.PlainText
                text: root.header ? root.header.name : ""
                color: Color.menu.text
                font.family: Style.font.family
                font.pixelSize: Style.font.title
              }

              Row {
                spacing: Style.space(12)
                Text {
                  textFormat: Text.PlainText
                  text: root.header ? root.header.where : ""
                  color: Color.muted
                  font.family: Style.font.family
                  font.pixelSize: Style.font.bodySmall
                }
                Text {
                  visible: !!(root.header && root.header.diagram)
                  textFormat: Text.RichText
                  text: "<a href='" + (root.header ? root.header.diagram : "")
                    + "' style='color:" + Color.accent + "'>Airport diagram</a>"
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

              Text {
                width: parent.width
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                textFormat: Text.PlainText
                visible: !!(root.header && root.header.conditions)
                text: root.header ? root.header.conditions : ""
                color: Color.menu.text
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
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
            Flow {
              visible: !!root.header
              width: parent.width
              spacing: Style.space(4)

              Repeater {
                model: root.tabNames
                delegate: Rectangle {
                  required property string modelData
                  required property int index
                  radius: Style.cornerRadius
                  implicitWidth: tabLabel.implicitWidth + Style.space(20)
                  implicitHeight: tabLabel.implicitHeight + Style.space(10)
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
                        color: Color.menu.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        font.bold: modelData.accent === true
                      }
                    }
                  }

                  Item { width: 1; height: Style.space(6) }

                  Row {
                    spacing: Style.space(14)
                    Repeater {
                      model: Model.linkRows(root.airportData)
                      delegate: Text {
                        required property var modelData
                        textFormat: Text.RichText
                        text: "<a href='" + modelData.url + "' style='color:"
                          + Color.accent + "'>" + modelData.label + "</a>"
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

                  Item { width: 1; height: Style.space(4) }

                  Text {
                    visible: !!Model.tfrLine(root.tfr, root.header ? root.header.us : true)
                    width: parent.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.RichText
                    text: Model.tfrLine(root.tfr, root.header ? root.header.us : true)
                      + "   <a href='https://tfr.faa.gov/tfr3/?page=list' style='color:"
                      + Color.accent + "'>TFR list</a>"
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    onLinkActivated: function (link) { root.openLink(link) }
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
                    visible: !!(root.weather && !root.weather.available)
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
                        color: modelData.accent ? Model.categoryColor(root.weather ? root.weather.category : "", Color.menu.text) : Color.menu.text
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
                    text: root.weather ? root.weather.raw : ""
                    color: Color.muted
                    font.family: "monospace"
                    font.pixelSize: Style.font.bodySmall
                  }
                  Item { width: 1; height: Style.space(8) }
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
                  Text {
                    visible: !!(root.airportData && root.airportData.links
                                && root.airportData.links.weather)
                    textFormat: Text.RichText
                    text: "<a href='" + (root.airportData && root.airportData.links
                            ? root.airportData.links.weather : "")
                      + "' style='color:" + Color.accent
                      + "'>Live weather on aviationweather.gov</a>"
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

                // ============ 2 AMENITIES ============
                Column {
                  visible: root.tab === 2
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
                    text: "Nothing mapped here. Small fields usually have no OpenStreetMap "
                      + "coverage — that does not mean there is nothing on the field."
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
                            text: modelData.url
                              ? ("<a href='" + modelData.url + "' style='color:"
                                 + (modelData.kind === "lounge" ? Color.accent : Color.menu.text)
                                 + ";text-decoration:"
                                 + (rowHover.hovered ? "underline" : "none") + "'>"
                                 + modelData.name + "</a>")
                              : modelData.name
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
                            text: "<a href='" + modelData.osm + "' style='color:"
                              + Color.muted + "'>osm</a>"
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
                  visible: root.tab === 3
                  width: parent.width
                  spacing: Style.space(1)

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
                          color: modelData.runway ? Color.menu.text : Color.muted
                          font.family: "monospace"
                          font.pixelSize: Style.font.bodySmall
                          font.bold: modelData.runway === true
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

                  Text {
                    visible: !!(root.runwayData && root.runwayData.pattern_altitude)
                    width: parent.width
                    wrapMode: Text.WordWrap
                    textFormat: Text.PlainText
                    text: root.runwayData
                      ? "Pattern altitude   " + root.runwayData.pattern_altitude : ""
                    color: Color.muted
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                  }
                  Text {
                    visible: !!(root.runwayData && root.runwayData.diagram)
                    textFormat: Text.RichText
                    text: "<a href='" + (root.runwayData ? root.runwayData.diagram : "")
                      + "' style='color:" + Color.accent + "'>Airport diagram (PDF)</a>"
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

                // ============ 4 PROCEDURES ============
                Column {
                  visible: root.tab === 4
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
                      text: modelData.url
                        ? (modelData.label + "   <a href='" + modelData.url
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
                  visible: root.tab === 5
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
                  Text {
                    visible: !!(root.airportData && root.airportData.links
                                && root.airportData.links.liveatc)
                    textFormat: Text.RichText
                    text: "<a href='" + (root.airportData && root.airportData.links
                            ? root.airportData.links.liveatc : "")
                      + "' style='color:" + Color.accent + "'>Listen on LiveATC</a>"
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

                // ============ 6 GROUND SERVICES ============
                Column {
                  visible: root.tab === 6
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
                    text: "FBOs &amp; FUEL"
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
                  visible: root.tab === 7
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

        // ---- footer ----
        Text {
          id: footer
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          anchors.margins: Style.space(18)
          textFormat: Text.PlainText
          text: "↑↓ airport · ←→ page · PgUp/PgDn scroll · Esc close   —   not for navigation"
          color: Color.muted
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
        }
      }
    }
  }
}
