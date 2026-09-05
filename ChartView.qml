import QtQuick
import Quickshell.Io
import QtQuick.Pdf
import Qt5Compat.GraphicalEffects
import qs.Commons
import qs.Ui

// The chart viewer lives in its own file because of these two imports.
//
// QtQuick.Pdf ships in qt6-webengine and Qt5Compat.GraphicalEffects in
// qt6-5compat. A stock Omarchy install has both, though only by accident:
// kdenlive is in omarchy-base.packages and drags them in through purpose and
// kwallet. Nothing declares them, so nothing keeps them - drop kdenlive and
// they go too. A failed import takes down the whole file it appears in, so if
// these sat in Panel.qml that day would take the entire plugin with it.
// Behind a Loader it costs the inline viewer and nothing else, and charts open
// in a browser instead.

// ---- chart viewer ----------------------------------------------
// Sits over the card rather than replacing it, so backing out with Esc
// returns to exactly the airport and page you left.
Item {
  id: chartRoot

  property string path: ""
  property string title: ""
  property string url: ""
  property bool loading: false
  property string error: ""
  property int page: 0
  property real zoom: 1.0
  property bool invert: false
  readonly property int pageCount: chartDoc.pageCount

  signal closeRequested()
  signal externalRequested()

  function step(delta) {
    if (chartDoc.pageCount <= 0) return
    page = Math.max(0, Math.min(chartDoc.pageCount - 1, page + delta))
  }

  function zoomBy(factor) { zoom = Math.max(0.25, Math.min(6.0, zoom * factor)) }
  function toggleInvert() { invert = !invert }
  function resetZoom() { zoom = 1.0 }

  PdfDocument { id: chartDoc }
  onPathChanged: if (path) chartDoc.source = Qt.resolvedUrl("file://" + path)

  anchors.fill: parent

  function scrollBy(dy) {
    chartFlick.contentY = Math.max(
      0, Math.min(chartFlick.contentY + dy,
                  Math.max(0, chartFlick.contentHeight - chartFlick.height)))
  }

  Rectangle {
    anchors.fill: parent
    radius: Style.cornerRadius
    color: Color.menu.background
    // Swallow clicks so they never reach the airport underneath.
    MouseArea { anchors.fill: parent }
  }

  // ---- toolbar ----
  Item {
    id: chartBar
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: Style.space(18)
    height: chartTitleText.implicitHeight + Style.space(10)

    Text {
      id: chartTitleText
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
      width: parent.width - chartTools.width - Style.space(16)
      elide: Text.ElideRight
      textFormat: Text.PlainText
      text: chartRoot.title
      color: Color.menu.text
      font.family: Style.font.family
      font.pixelSize: Style.font.title
      font.bold: true
    }

    Row {
      id: chartTools
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(14)

      Text {
        anchors.verticalCenter: parent.verticalCenter
        visible: chartDoc.pageCount > 1
        textFormat: Text.PlainText
        text: "page " + (chartRoot.page + 1) + " of " + chartDoc.pageCount
        color: Color.muted
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
      }

      Repeater {
        model: [
          { label: "−", action: "out" },
          { label: "reset", action: "reset" },
          { label: "+", action: "in" },
          { label: "invert", action: "invert" },
          { label: "open externally", action: "external" },
          { label: "close", action: "close" }
        ]
        delegate: Text {
          required property var modelData
          anchors.verticalCenter: parent.verticalCenter
          textFormat: Text.PlainText
          text: modelData.label
          color: (modelData.action === "invert" && chartRoot.invert)
            ? Color.accent
            : (toolArea.containsMouse ? Color.accent : Color.muted)
          font.family: Style.font.family
          font.pixelSize: Style.font.caption
          font.bold: true
          MouseArea {
            id: toolArea
            anchors.fill: parent
            anchors.margins: -Style.space(4)
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: {
              if (modelData.action === "in") chartRoot.zoomBy(1.25)
              else if (modelData.action === "out") chartRoot.zoomBy(0.8)
              else if (modelData.action === "reset") chartRoot.zoom = 1.0
              else if (modelData.action === "invert")
                chartRoot.invert = !chartRoot.invert
              else if (modelData.action === "external")
                chartRoot.externalRequested()
              else chartRoot.closeRequested()
            }
          }
        }
      }
    }
  }

  // ---- the page ----
  Flickable {
    id: chartFlick
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: chartBar.bottom
    anchors.bottom: chartFoot.top
    anchors.margins: Style.space(18)
    anchors.topMargin: Style.space(8)
    clip: true
    contentWidth: Math.max(width, chartPage.width)
    contentHeight: Math.max(height, chartPage.height)
    boundsBehavior: Flickable.StopAtBounds
    visible: !chartRoot.loading && chartRoot.error === "" && !!chartRoot.path

    // Charts are line art on white. Rendering at the displayed pixel
    // size rather than scaling a smaller bitmap is what keeps the
    // minimums text and the taxiway labels readable.
    // Geometry lives on a plain Item, so the page has a size before
    // any PDF exists. PdfPageImage warns 'Protocol "" is unknown' on
    // every frame if it is alive with no document loaded, so it is
    // only created once a chart has actually been fetched.
    Item {
      id: chartPage
      x: Math.max(0, (chartFlick.width - width) / 2)
      y: Math.max(0, (chartFlick.height - height) / 2)

      // Page size comes from the document, never from implicitWidth:
      // sourceSize feeds back into an image's implicit size, so sizing
      // off that is a binding loop.
      property size pageSize: chartDoc.status === PdfDocument.Ready
        && chartDoc.pageCount > 0
        ? chartDoc.pagePointSize(chartRoot.page)
        : Qt.size(612, 792)
      property real fitScale: (pageSize.width > 0 && pageSize.height > 0
                               && chartFlick.width > 0 && chartFlick.height > 0)
        ? Math.min(chartFlick.width / pageSize.width,
                   chartFlick.height / pageSize.height)
        : 1
      width: pageSize.width * fitScale * chartRoot.zoom
      height: pageSize.height * fitScale * chartRoot.zoom
      Behavior on width { NumberAnimation { duration: 90 } }
      Behavior on height { NumberAnimation { duration: 90 } }

      // The sheet. Without it a chart that renders its background
      // transparent puts black linework on a near-black card, which is
      // exactly as readable as it sounds.
      Rectangle {
        anchors.fill: parent
        color: chartRoot.invert ? "#000000" : "#ffffff"
      }

      Loader {
        anchors.fill: parent
        active: !!chartRoot.path
        sourceComponent: PdfPageImage {
          document: chartDoc
          currentFrame: chartRoot.page
          layer.enabled: chartRoot.invert
          // RGB is swapped end for end; alpha keeps its identity
          // mapping (0 -> 0, 1 -> 1). Inverting alpha as well turns
          // the page's transparent background opaque white and
          // swallows the ink with it.
          layer.effect: LevelAdjust {
            minimumOutput: Qt.rgba(1, 1, 1, 0)
            maximumOutput: Qt.rgba(0, 0, 0, 1)
          }
          // Render at the size actually shown, so the minimums table
          // and the taxiway labels stay readable, not upscaled.
          sourceSize.width: Math.max(1, Math.round(width))
          sourceSize.height: Math.max(1, Math.round(height))
        }
      }
    }

    // Ctrl+wheel zooms, plain wheel scrolls, as in every other viewer.
    WheelHandler {
      acceptedModifiers: Qt.ControlModifier
      onWheel: function (event) {
        chartRoot.zoomBy(event.angleDelta.y > 0 ? 1.15 : 0.87)
      }
    }
  }

  Text {
    anchors.centerIn: chartFlick
    width: chartFlick.width * 0.7
    horizontalAlignment: Text.AlignHCenter
    wrapMode: Text.WordWrap
    textFormat: Text.PlainText
    visible: chartRoot.loading || chartRoot.error !== ""
    text: chartRoot.error !== ""
      ? chartRoot.error + "\n\nUse \u201copen externally\u201d to view it in a browser."
      : "Fetching the chart…"
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.body
  }

  Text {
    id: chartFoot
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    anchors.margins: Style.space(18)
    textFormat: Text.PlainText
    text: (chartDoc.pageCount > 1 ? "←→ page · " : "")
      + "+/− zoom · 0 reset · i invert · ↑↓ PgUp/PgDn scroll · Esc back"
      + "   —   not for navigation"
    color: Color.muted
    font.family: Style.font.family
    font.pixelSize: Style.font.caption
  }
}
