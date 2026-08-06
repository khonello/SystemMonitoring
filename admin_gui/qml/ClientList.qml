// Connected Client Agents.
// PHASE 1 SCAFFOLD - bound to clientModel, which stays empty until Phase 3.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    property string selectedClient: ""

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

        ListView {
            id: listView

            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: clientModel

            delegate: ItemDelegate {
                width: listView.width
                highlighted: root.selectedClient === model.client_id
                onClicked: root.selectedClient = model.client_id

                contentItem: ColumnLayout {
                    spacing: 2

                    Label {
                        text: model.client_id || ""
                        font.bold: true
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    Label {
                        text: (model.address || "") + "  -  " + (model.status || "")
                        opacity: 0.6
                        font.pixelSize: 11
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }
            }

            Label {
                anchors.centerIn: parent
                visible: listView.count === 0
                text: backend.connected ? "No clients connected" : "Not connected"
                opacity: 0.5
            }
        }
    }
}
