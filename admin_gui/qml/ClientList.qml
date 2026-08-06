// Known Client Agents, connected or not.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: 8

            Label {
                text: "Clients (" + listView.count + ")"
                font.bold: true
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "Refresh"
                enabled: backend.connected
                onClicked: backend.refreshClients()
            }
        }

        // Pausing the whole room is the common case, so it gets its own row
        // rather than being buried in the per-client command panel.
        RowLayout {
            Layout.fillWidth: true
            Layout.leftMargin: 8
            Layout.rightMargin: 8
            Layout.bottomMargin: 6
            spacing: 6

            Button {
                text: "Pause all"
                enabled: backend.connected
                Layout.fillWidth: true
                onClicked: backend.pauseAll()
            }

            Button {
                text: "Resume all"
                enabled: backend.connected
                Layout.fillWidth: true
                onClicked: backend.resumeAll()
            }
        }

        ListView {
            id: listView

            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: clientModel

            delegate: ItemDelegate {
                width: listView.width
                highlighted: backend.selectedClient === model.client_id
                onClicked: backend.selectedClient = model.client_id

                contentItem: RowLayout {
                    spacing: 8

                    Rectangle {
                        width: 8
                        height: 8
                        radius: 4
                        color: model.connected ? "#2e9e4f" : "#8a8a8a"
                    }

                    ColumnLayout {
                        spacing: 2
                        Layout.fillWidth: true

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 6

                            Label {
                                text: model.client_id || ""
                                font.bold: true
                                elide: Text.ElideRight
                                Layout.fillWidth: true
                            }

                            Rectangle {
                                visible: model.paused === true
                                radius: 3
                                color: "#3a2d10"
                                border.width: 1
                                border.color: "#d29922"
                                implicitWidth: pausedTag.implicitWidth + 10
                                implicitHeight: pausedTag.implicitHeight + 4

                                Label {
                                    id: pausedTag
                                    anchors.centerIn: parent
                                    text: "paused"
                                    color: "#d29922"
                                    font.pixelSize: 9
                                }
                            }
                        }

                        Label {
                            text: (model.hostname || "") +
                                  (model.os_type ? "  -  " + model.os_type : "")
                            opacity: 0.6
                            font.pixelSize: 11
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                }
            }

            Label {
                anchors.centerIn: parent
                width: parent.width - 32
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                visible: listView.count === 0
                opacity: 0.5
                text: backend.connected
                    ? "No clients have registered yet"
                    : "Not connected to an Engine"
            }
        }
    }
}
