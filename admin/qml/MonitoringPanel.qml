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

        TabBar {
            id: innerTabs
            Layout.fillWidth: true

            TabButton { text: "Applications (" + applicationModel.rowCount() + ")" }
            TabButton { text: "Network" }
            TabButton { text: "USB Events" }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: innerTabs.currentIndex

            DataList {
                model: applicationModel
                emptyText: "No application data received yet.\n" +
                           "Clients send a batch every 30 seconds once connected."
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
                emptyText: "No network samples received yet."
                primary: function (m) { return m.timestamp || "" }
                secondary: function (m) {
                    return (m.active_connections || 0) + " active connections"
                }
                trailing: function (m) {
                    return "sent " + (m.bytes_sent || 0) + "   recv " + (m.bytes_received || 0)
                }
            }

            DataList {
                model: usbModel
                emptyText: "No USB events received yet."
                primary: function (m) { return m.device_name || "" }
                secondary: function (m) { return m.timestamp || "" }
                trailing: function (m) { return m.event || m.event_type || "" }
            }
        }
    }
}
