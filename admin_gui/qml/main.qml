// Administrator GUI shell.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window

    width: 1200
    height: 780
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
                text: defaultHost
                placeholderText: "Engine host"
                enabled: !backend.connected
                Layout.preferredWidth: 150
            }

            TextField {
                id: portField
                text: defaultPort
                placeholderText: "Port"
                enabled: !backend.connected
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
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12

            Rectangle {
                width: 10
                height: 10
                radius: 5
                color: backend.connected ? "#2e9e4f" : "#9e2e2e"
            }

            Label {
                text: backend.status
                elide: Text.ElideRight
                Layout.fillWidth: true
            }
        }
    }

    SplitView {
        anchors.fill: parent
        orientation: Qt.Horizontal

        ClientList {
            SplitView.preferredWidth: 300
            SplitView.minimumWidth: 220
        }

        ColumnLayout {
            SplitView.fillWidth: true
            spacing: 0

            TabBar {
                id: tabs
                Layout.fillWidth: true

                TabButton { text: "Monitoring" }
                TabButton { text: "Reports" }
                TabButton { text: "Policy" }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: tabs.currentIndex

                MonitoringPanel {}
                ReportsPanel {}
                PolicyPanel {}
            }

            CommandPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: 260
            }
        }
    }

    Dialog {
        id: validationDialog

        property string detail: ""

        anchors.centerIn: parent
        width: Math.min(window.width - 80, 560)
        modal: true
        standardButtons: Dialog.Ok
        title: "Script not sent"

        ColumnLayout {
            anchors.fill: parent
            spacing: 8

            Label {
                text: "The script failed validation, so it was not sent to any client."
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            ScrollView {
                Layout.fillWidth: true
                Layout.preferredHeight: 140

                TextArea {
                    text: validationDialog.detail
                    readOnly: true
                    wrapMode: TextEdit.Wrap
                    font.family: "Consolas, monospace"
                }
            }
        }
    }

    Connections {
        target: backend

        function onValidationFailed(message) {
            validationDialog.detail = message
            validationDialog.open()
        }
    }
}
