// Live monitoring for the selected client.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8

        Label {
            text: backend.selectedClient !== ""
                ? "Live data: " + backend.selectedClient
                : "Select a client"
            font.bold: true
            font.pixelSize: 14
        }

        // Sized to their labels — see the note on the outer TabBar in main.qml.
        TabBar {
            id: innerTabs
            Layout.fillWidth: true

            TabButton {
                text: "Applications (" + applicationModel.rowCount() + ")"
                width: implicitWidth + 24
            }
            TabButton { text: "Network"; width: implicitWidth + 24 }
            TabButton { text: "USB Events"; width: implicitWidth + 24 }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: innerTabs.currentIndex

            DataList {
                model: applicationModel
                emptyTitle: backend.selectedClient === ""
                    ? "No client selected"
                    : "Waiting for the next report"
                emptyText: backend.selectedClient === ""
                    ? "Choose a machine in the list on the left to watch it."
                    : backend.selectedClient + " sends its application list every " +
                      "30 seconds. This view is live only — use Reports for history."
                primary: function (m) { return m.process_name || "" }
                secondary: function (m) {
                    return "pid " + (m.pid || "?") + "   " + (m.window_title || "")
                }
                trailing: function (m) {
                    return (m.cpu_percent || 0).toFixed(1) + "% CPU   " +
                           (m.memory_mb || 0).toFixed(0) + " MB"
                }
            }

            DataList {
                model: networkModel
                emptyTitle: backend.selectedClient === ""
                    ? "No client selected"
                    : "Waiting for the next sample"
                emptyText: backend.selectedClient === ""
                    ? "Choose a machine in the list on the left to watch it."
                    : backend.selectedClient + " reports network counters every " +
                      "60 seconds. This view is live only — use Reports for 24-hour " +
                      "and weekly summaries."
                primary: function (m) { return m.timestamp || "" }
                secondary: function (m) {
                    return (m.active_connections || 0) + " active connections"
                }
                trailing: function (m) {
                    return "sent " + (m.bytes_sent || 0) + "   recv " + (m.bytes_received || 0)
                }
            }

            // USB is event-driven, so there is no interval to promise and no
            // "yet" to imply. Deliberately says nothing about virtual machines
            // not passing USB through: true of this lab, false of the product,
            // and a label that ships wrong everywhere is worse than a quiet one
            // (issues.md C18).
            DataList {
                model: usbModel
                emptyTitle: backend.selectedClient === ""
                    ? "No client selected"
                    : "No USB events recorded"
                emptyText: backend.selectedClient === ""
                    ? "Choose a machine in the list on the left to watch it."
                    : "Events appear here when a device is plugged into " +
                      backend.selectedClient + ". Nothing has been reported since this " +
                      "session connected."
                primary: function (m) { return m.device_name || "" }
                secondary: function (m) { return m.timestamp || "" }
                trailing: function (m) { return m.event || m.event_type || "" }
            }
        }
    }
}
