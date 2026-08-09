// Administrator GUI shell.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ApplicationWindow {
    id: window

    // A wide rectangle: height tracks width at 30%. Widening the window keeps
    // the shape; dragging the height directly overrides it, which is the normal
    // QML behaviour of a binding replaced by the window manager.
    //
    // The shape suits the layout below — a horizontal split with the roster
    // beside the panels — but it leaves little vertical room, which is why the
    // command panel's height is proportional rather than fixed.
    readonly property real aspectRatio: 0.30

    width: 1600
    height: Math.round(width * aspectRatio)

    minimumWidth: 1100
    minimumHeight: Math.round(minimumWidth * aspectRatio)

    // Re-applied rather than left to the binding alone. Dragging a window edge
    // makes the window manager write height directly, which replaces the
    // binding above and would strand the ratio wherever it happened to be.
    // The offscreen platform cannot exercise a real user resize, so this is
    // belt-and-braces for the case the automated check cannot reach.
    onWidthChanged: height = Math.round(width * aspectRatio)

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

    // A pause lapses on its own if nobody extends it. That is deliberate — it
    // stops an unattended pause holding the lab indefinitely — but it must
    // never happen silently, so it is announced here rather than in the status
    // line where it could scroll past unnoticed.
    Rectangle {
        id: pauseBanner

        property string clientId: ""
        property int secondsLeft: 0

        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        height: visible ? 44 : 0
        visible: clientId !== ""
        color: "#3a2d10"
        z: 10

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            spacing: 12

            Label {
                Layout.fillWidth: true
                color: "#f0d58c"
                elide: Text.ElideRight
                text: "Pause on " + pauseBanner.clientId + " lapses in " +
                      Math.ceil(pauseBanner.secondsLeft / 60) +
                      " min. Extend it, or the machine resumes on its own."
            }

            Button {
                text: "Extend"
                onClicked: {
                    backend.extendPause(pauseBanner.clientId)
                    pauseBanner.clientId = ""
                }
            }

            Button {
                text: "Dismiss"
                onClicked: pauseBanner.clientId = ""
            }
        }
    }

    SplitView {
        anchors.top: pauseBanner.bottom
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
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

            // Proportional, not the fixed 260 it used to be. In a window this
            // wide and short a fixed panel would claim most of the height and
            // leave the tab above it unusable.
            CommandPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(260, Math.round(window.height * 0.34))
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

        function onPauseExpiring(clientId, secondsLeft) {
            pauseBanner.clientId = clientId
            pauseBanner.secondsLeft = secondsLeft
        }
    }
}
