import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// protas bar widget + popup panel. Polling uses `protas list --all --json`,
// a pure query that never creates or rolls a day. Clicking an entry runs
// `protas done|undone <id>`; project mentions are left to the TUI, because
// completing one completes the whole project.
Panel {
  id: root
  moduleName: "german-ds.protas"
  ipcTarget: "german-ds.protas"

  readonly property string cli: Quickshell.env("HOME") + "/.local/bin/protas"

  readonly property string glyphList: String.fromCodePoint(0xF065F) // nf-md-format_list_checks
  readonly property string glyphOpen: String.fromCodePoint(0xF003A) // nf-md-checkbox_blank_outline
  readonly property string glyphDone: String.fromCodePoint(0xF04E9) // nf-md-check_circle
  readonly property string glyphPlay: String.fromCodePoint(0xF0313) // nf-md-play

  // ---------- Agenda ----------
  property var agenda: null
  property bool loaded: false
  property string errorText: ""
  property bool refreshQueued: false
  // Id of the entry being written, or -1. One write at a time.
  property int markingId: -1
  // Kept apart from errorText: the refresh that follows a failed write
  // would clear it before it could be read.
  property string markError: ""

  readonly property var counts: agenda && agenda.counts ? agenda.counts : null
  readonly property var entries: agenda && agenda.entries ? agenda.entries : []
  readonly property string note: agenda && agenda.note ? String(agenda.note) : ""
  readonly property int pending: counts && counts.open !== undefined ? counts.open : 0
  readonly property int total: counts && counts.total !== undefined ? counts.total : 0
  readonly property int done: counts && counts.done !== undefined ? counts.done : 0
  readonly property string dayTitle: agenda && agenda.workspace && agenda.workspace.title
    ? String(agenda.workspace.title) : ""

  readonly property int refreshIntervalSec: {
    var n = parseInt(String(setting("refreshIntervalSec", 60)), 10)
    if (!isFinite(n)) n = 60
    return Math.max(10, Math.min(3600, n))
  }

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.5)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  readonly property string summary: {
    if (!loaded) return "Leyendo la agenda…"
    if (pending === 0 && total === 0) return "Nada pendiente para hoy"
    if (pending === 0) return "Todo hecho: " + done + " entradas"
    return pending + " pendiente" + (pending === 1 ? "" : "s") + " de " + total
  }

  readonly property string tooltip: !loaded ? "protas"
    : (pending === 0 ? "protas · nada pendiente"
    : "protas · " + pending + " pendiente" + (pending === 1 ? "" : "s"))

  function refresh() {
    if (dataProc.running) {
      refreshQueued = true
      return
    }
    dataProc.running = true
  }

  function applyAgenda(raw) {
    var body = String(raw || "").trim()
    if (body === "") {
      loaded = true
      return
    }
    var parsed = null
    try { parsed = JSON.parse(body) } catch (e) { parsed = null }
    if (parsed && typeof parsed === "object" && parsed.counts) {
      agenda = parsed
      errorText = ""
    } else {
      errorText = "No pude leer la agenda de protas."
    }
    loaded = true
  }

  function canMark(entry) {
    return entry !== null && entry !== undefined
      && entry.id !== undefined && entry.id !== null
      && (entry.project_id === null || entry.project_id === undefined)
  }

  function toggleEntry(entry) {
    if (!canMark(entry) || markingId !== -1 || markProc.running) return
    markingId = entry.id
    markError = ""
    markProc.command = [root.cli, entry.done === true ? "undone" : "done", String(entry.id)]
    markProc.running = true
  }

  function openTui() {
    root.close()
    if (root.bar && typeof root.bar.run === "function") {
      root.bar.run("omarchy-launch-or-focus-tui " + root.cli)
    }
  }

  onOpenedChanged: if (opened) refresh()
  Component.onCompleted: refresh()

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Process {
    id: dataProc
    command: [root.cli, "list", "--all", "--json"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: root.applyAgenda(text)
    }
    onExited: {
      if (root.refreshQueued) {
        root.refreshQueued = false
        Qt.callLater(root.refresh)
      }
    }
  }

  Process {
    id: markProc
    onExited: function(exitCode, exitStatus) {
      root.markingId = -1
      if (exitCode !== 0) root.markError = "No pude marcar la entrada."
      root.refresh()
    }
  }

  // Poll faster while the panel is open; refresh() queues instead of overlapping.
  Timer {
    interval: root.opened ? 5000 : root.refreshIntervalSec * 1000
    running: true
    repeat: true
    onTriggered: root.refresh()
  }

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.glyphList
    labelText: root.loaded && root.pending > 0 ? String(root.pending) : ""
    opacity: !root.loaded ? 0.5 : (root.pending === 0 ? 0.45 : 1)
    tooltipText: root.tooltip
    onPressed: function(b) { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: panel.loadedContent
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(panel.loadedContentHeight)

    content: PanelKeyCatcher {
      id: keyCatcher
      implicitHeight: column.implicitHeight
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Flickable {
        id: scroll
        anchors.fill: parent
        contentWidth: width
        contentHeight: column.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: column
          width: scroll.width
          spacing: Style.space(14)

          // ---------- Hero ----------
          Item {
            width: parent.width
            implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight)

            Text {
              id: heroIcon
              textFormat: Text.PlainText
              text: root.glyphList
              color: root.pending > 0 ? root.foreground : root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.display
              anchors.left: parent.left
              anchors.verticalCenter: parent.verticalCenter
            }

            Column {
              id: heroLabels
              anchors.left: heroIcon.right
              anchors.leftMargin: Style.space(14)
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)

              Text {
                textFormat: Text.PlainText
                text: "protas"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                font.bold: true
                elide: Text.ElideRight
                width: parent.width
              }

              Text {
                textFormat: Text.PlainText
                text: root.summary
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
                width: parent.width
              }

              Text {
                visible: text !== ""
                textFormat: Text.PlainText
                text: root.dayTitle
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                elide: Text.ElideRight
                width: parent.width
              }
            }
          }

          // ---------- Errors ----------
          Text {
            visible: text !== ""
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            text: root.markError !== "" ? root.markError : root.errorText
            color: root.urgent
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          // ---------- Note of the day ----------
          Text {
            visible: root.note.trim() !== ""
            width: parent.width
            textFormat: Text.PlainText
            wrapMode: Text.WordWrap
            maximumLineCount: 6
            elide: Text.ElideRight
            text: root.note
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.bodySmall
          }

          PanelSeparator { foreground: root.foreground }

          // ---------- Entries ----------
          Section {
            title: "HOY"

            Text {
              visible: root.entries.length === 0
              width: parent.width
              textFormat: Text.PlainText
              wrapMode: Text.WordWrap
              text: root.loaded ? "Sin entradas." : "Leyendo…"
              color: root.dim
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
            }

            Column {
              width: parent.width
              spacing: Style.space(6)

              Repeater {
                model: root.entries
                EntryRow {
                  required property var modelData
                  entry: modelData
                }
              }
            }
          }

          Button {
            width: parent.width
            iconText: root.glyphPlay
            iconSize: Style.font.title
            text: "Abrir protas"
            fontSize: Style.font.bodySmall
            foreground: root.foreground
            fontFamily: root.fontFamily
            verticalPadding: Style.spacing.controlPaddingY + Style.space(2)
            bordered: true
            onClicked: root.openTui()
          }
        }
      }
    }
  }

  component Section: Column {
    property string title: ""
    width: parent ? parent.width : 0
    spacing: Style.space(10)

    PanelSectionHeader {
      text: parent.title
      foreground: root.foreground
      fontFamily: root.fontFamily
    }
  }

  // One entry: a marker, its text, and the progress when it is a project
  // mention. Done entries stay visible but recede. A click completes or
  // reopens it; mentions do not react.
  component EntryRow: Item {
    id: row
    property var entry: null
    readonly property bool finished: entry !== null && entry.done === true
    readonly property int depth: entry !== null && entry.depth ? entry.depth : 0
    readonly property var progress: entry !== null && entry.progress ? entry.progress : null
    readonly property bool markable: root.canMark(entry)
    readonly property bool marking: entry !== null && root.markingId === entry.id

    width: parent ? parent.width : 0
    implicitHeight: Math.max(marker.implicitHeight, label.implicitHeight)
    height: implicitHeight
    opacity: marking ? 0.5 : 1

    Rectangle {
      anchors.fill: parent
      anchors.margins: -Style.space(2)
      radius: Style.space(4)
      color: root.foreground
      opacity: rowMouse.containsMouse ? 0.08 : 0
    }

    MouseArea {
      id: rowMouse
      anchors.fill: parent
      enabled: row.markable
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: root.toggleEntry(row.entry)
    }

    Text {
      id: marker
      textFormat: Text.PlainText
      text: row.finished ? root.glyphDone : root.glyphOpen
      color: row.finished ? root.dim : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      anchors.left: parent.left
      anchors.leftMargin: Style.space(4) + Style.space(12) * row.depth
      anchors.verticalCenter: parent.verticalCenter
    }

    Text {
      id: progressLabel
      visible: row.progress !== null
      textFormat: Text.PlainText
      text: row.progress !== null ? (row.progress.done + "/" + row.progress.total) : ""
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
    }

    Text {
      id: label
      textFormat: Text.PlainText
      text: row.entry !== null ? String(row.entry.text) : ""
      color: row.finished ? root.dim : root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      font.strikeout: row.finished
      elide: Text.ElideRight
      anchors.left: marker.right
      anchors.leftMargin: Style.space(8)
      anchors.right: progressLabel.visible ? progressLabel.left : parent.right
      anchors.rightMargin: Style.space(8)
      anchors.verticalCenter: parent.verticalCenter
    }
  }
}

