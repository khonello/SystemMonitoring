// Live monitoring for the selected client.
//
// Reads top-down the way an operator asks questions: which machine, how is it
// doing at a glance, then the detail. The stat strip exists because "is this
// machine busy or idle?" should not require reading a table of 52 processes --
// and because the numbers changing every few seconds while it is watched is the
// clearest possible signal that the live subscription is working.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Item {
    id: root

    readonly property bool hasClient: backend.selectedClient !== ""

    // Derived from the live application rows rather than sent separately: the
    // client already reports per-process CPU and memory, and summing here keeps
    // the wire format unchanged.
    // Both mention `count` so the binding re-runs when rows change: total()
    // is a plain slot and carries no change signal of its own.
    readonly property real totalCpu:
        applicationModel.count >= 0 ? applicationModel.total("cpu_percent") : 0

    readonly property real totalMemory:
        applicationModel.count >= 0 ? applicationModel.total("memory_mb") : 0

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space3
        spacing: Theme.space3

        // --- who, and how it is doing --------------------------------------

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            ColumnLayout {
                spacing: 1

                Label {
                    text: root.hasClient ? backend.selectedClient : "No client selected"
                    color: Theme.text
                    font.pixelSize: Theme.fontLarge
                    font.bold: true
                }

                Label {
                    text: root.hasClient
                        ? "Live view - sampling every 3s while watched"
                        : "Choose a machine on the left"
                    color: Theme.textFaint
                    font.pixelSize: Theme.fontSmall
                }
            }

            Item { Layout.fillWidth: true }

            StatTile {
                label: "Processes"
                value: root.hasClient ? applicationModel.count.toString() : "--"
                tint: Theme.accent
            }

            StatTile {
                label: "CPU"
                value: root.hasClient ? root.totalCpu.toFixed(0) : "--"
                unit: "%"
                tint: root.totalCpu > 80 ? Theme.warn : Theme.ok
            }

            StatTile {
                label: "Memory"
                value: root.hasClient ? (root.totalMemory / 1024).toFixed(1) : "--"
                unit: "GB"
                tint: Theme.accent
            }

            StatTile {
                label: "USB events"
                value: root.hasClient ? usbModel.count.toString() : "--"
                tint: usbModel.count > 0 ? Theme.warn : Theme.textFaint
            }
        }

        // --- the detail ----------------------------------------------------

        SegmentedControl {
            id: view
            segments: [
                { text: "Applications", count: applicationModel.count },
                { text: "Network", count: networkModel.count },
                { text: "USB events", count: usbModel.count }
            ]
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: view.currentIndex

            DataList {
                model: applicationModel
                emptyTitle: root.hasClient ? "Waiting for the next report" : "No client selected"
                emptyText: root.hasClient
                    ? backend.selectedClient + " sends its application list every 30 seconds, " +
                      "or every 3 while you are watching it. This view is live only - " +
                      "use Reports for history."
                    : "Choose a machine in the list on the left to watch it."
                primary: function (m) { return m.process_name || "" }
                secondary: function (m) {
                    return "pid " + (m.pid || "?") + (m.window_title ? "   " + m.window_title : "")
                }
                trailing: function (m) {
                    return (m.cpu_percent || 0).toFixed(1) + "%   " +
                           (m.memory_mb || 0).toFixed(0) + " MB"
                }
            }

            DataList {
                model: networkModel
                emptyTitle: root.hasClient ? "Waiting for the next sample" : "No client selected"
                emptyText: root.hasClient
                    ? backend.selectedClient + " reports network counters every 60 seconds. " +
                      "Reports has the 24-hour and weekly summaries."
                    : "Choose a machine in the list on the left to watch it."
                primary: function (m) { return m.timestamp || "" }
                secondary: function (m) { return (m.active_connections || 0) + " active connections" }
                trailing: function (m) {
                    return "up " + (m.bytes_sent || 0) + "   down " + (m.bytes_received || 0)
                }
            }

            // USB is event-driven, so there is no interval to promise and no
            // "yet" to imply. Deliberately says nothing about virtual machines
            // not passing USB through: true of this lab, false of the product,
            // and a label that ships wrong everywhere is worse than a quiet one
            // (issues.md C18).
            DataList {
                model: usbModel
                emptyTitle: root.hasClient ? "No USB events recorded" : "No client selected"
                emptyText: root.hasClient
                    ? "Events appear here when a device is plugged into " +
                      backend.selectedClient + "."
                    : "Choose a machine in the list on the left to watch it."
                primary: function (m) { return m.device_name || "" }
                secondary: function (m) { return m.timestamp || "" }
                trailing: function (m) { return m.event || m.event_type || "" }
            }
        }
    }
}
