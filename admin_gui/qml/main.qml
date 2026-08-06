// Administrator GUI shell.
// PHASE 1 SCAFFOLD - layout only, no live data.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window

    width: 1100
    height: 700
    visible: true
    title: "Lab Monitor - Administrator"

    header: ToolBar {
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12

            Label {
                text: "Lab Monitor"
                font.bold: true
                font.pixelSize: 16
            }

            Item { Layout.fillWidth: true }

            TextField {
                id: hostField
                text: "127.0.0.1"
                placeholderText: "Engine host"
                Layout.preferredWidth: 140
            }

            TextField {
                id: portField
                text: "5000"
                placeholderText: "Port"
                Layout.preferredWidth: 70
                validator: IntValidator { bottom: 1; top: 65535 }
            }

            Button {
                text: backend.connected ? "Disconnect" : "Connect"
                onClicked: backend.connected
                    ? backend.disconnectFromEngine()
                    : backend.connectToEngine(hostField.text, parseInt(portField.text))
            }
        }
    }

    footer: ToolBar {
        Label {
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            text: backend.status
        }
    }

    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal

        ClientList {
            id: clientList
            SplitView.preferredWidth: 280
            SplitView.minimumWidth: 200
        }

        ColumnLayout {
            SplitView.fillWidth: true
            spacing: 0

            MonitoringPanel {
                Layout.fillWidth: true
                Layout.fillHeight: true
                selectedClient: clientList.selectedClient
            }

            CommandPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: 220
                selectedClient: clientList.selectedClient
            }
        }
    }
}
