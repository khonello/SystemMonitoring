// Aggregated reports, queried from the Engine.
// Admins never read the database directly - every query goes through the
// Engine, which is what keeps the storage layer swappable.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    readonly property bool ready: backend.connected

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8

        RowLayout {
            Layout.fillWidth: true

            Label {
                text: "Reports"
                font.bold: true
                font.pixelSize: 14
            }

            Item { Layout.fillWidth: true }

            ComboBox {
                id: reportKind
                Layout.preferredWidth: 230
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
                enabled: root.ready
                onClicked: backend.requestReport(reportKind.currentValue)
            }
        }

        Label {
            visible: backend.selectedClient === "" &&
                     reportKind.currentValue !== "command_history"
            text: "Select a client - only command history is fleet-wide."
            opacity: 0.6
            font.pixelSize: 11
        }

        DataList {
            Layout.fillWidth: true
            Layout.fillHeight: true

            model: reportModel
            emptyText: root.ready
                ? "Choose a report and press Run."
                : "Connect to an Engine to run reports."

            primary: function (m) { return m.label || "" }
            secondary: function (m) { return m.detail || "" }
            trailing: function (m) { return m.value || "" }
        }
    }
}
