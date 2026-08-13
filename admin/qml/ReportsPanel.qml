// Aggregated reports, queried from the Engine.
// Admins never read the database directly - every query goes through the
// Engine, which is what keeps the storage layer swappable.
//
// This is the counterpart to Monitoring: that view is live and keeps nothing,
// this one is history and computes nothing locally. Saying so on the page is
// worth a line, because "why is Applications empty when Reports has data?" is
// otherwise a reasonable thing to wonder (issues.md C18).

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Item {
    id: root

    readonly property bool ready: backend.connected
    readonly property bool needsClient:
        backend.selectedClient === "" && reportKind.currentValue !== "command_history"

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space3
        spacing: Theme.space3

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            ColumnLayout {
                spacing: 1

                Label {
                    text: "Reports"
                    color: Theme.text
                    font.pixelSize: Theme.fontLarge
                    font.bold: true
                }

                Label {
                    text: "History from the Engine's database, not this window's memory"
                    color: Theme.textFaint
                    font.pixelSize: Theme.fontSmall
                }
            }

            Item { Layout.fillWidth: true }

            ComboBox {
                id: reportKind
                Layout.preferredWidth: 240
                Layout.preferredHeight: Theme.controlHeight
                font.pixelSize: Theme.fontBody
                textRole: "label"
                valueRole: "key"

                model: [
                    { key: "network_24h",     label: "Network - last 24 hours" },
                    { key: "network_weekly",  label: "Network - per day, 7 days" },
                    { key: "app_usage",       label: "Application usage - 24 hours" },
                    { key: "usb_events",      label: "USB events" },
                    { key: "command_history", label: "Command history" }
                ]
            }

            Button {
                text: "Run"
                highlighted: true
                Layout.preferredHeight: Theme.controlHeight
                Layout.preferredWidth: 84
                font.pixelSize: Theme.fontBody
                enabled: root.ready && !root.needsClient
                onClicked: backend.requestReport(reportKind.currentValue)
            }
        }

        // Appears only when the chosen report needs a machine and none is
        // selected — which is also exactly when Run is disabled, so the notice
        // explains the disabled button rather than leaving it unexplained.
        Rectangle {
            visible: root.needsClient
            Layout.fillWidth: true
            implicitHeight: 32
            radius: Theme.radius
            color: Qt.rgba(0.82, 0.6, 0.13, 0.10)
            border.width: 1
            border.color: Theme.warn

            Label {
                anchors.fill: parent
                anchors.leftMargin: Theme.space3
                verticalAlignment: Text.AlignVCenter
                color: Theme.warn
                font.pixelSize: Theme.fontSmall
                text: "This report is per-machine. Select one on the left - only command " +
                      "history is fleet-wide."
            }
        }

        DataList {
            Layout.fillWidth: true
            Layout.fillHeight: true

            model: reportModel
            emptyTitle: root.ready ? "No report run yet" : "Not connected"
            emptyText: root.ready
                ? "Choose a report above and press Run. Results come from the Engine, so " +
                  "they cover history this console never saw."
                : "Connect to an Engine to run reports."

            primary: function (m) { return m.label || "" }
            secondary: function (m) { return m.detail || "" }
            trailing: function (m) { return m.value || "" }
        }
    }
}
