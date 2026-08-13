// Administrator GUI shell.

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: window

    // One theme, stated once. The console previously inherited the platform
    // default and arrived as two half-finished themes at once: light title bar
    // and toolbar, dark body, light grey text areas. The style itself is
    // selected in admin/style.py, which both this app and --check-qml call.
    Material.theme: Material.Dark
    Material.background: "#12161c"
    Material.primary: "#1b2430"
    Material.accent: "#4c8dff"

    // MAXIMIZED, ALWAYS. issues.md C17.
    //
    // This used to lock height to 30% of width and re-apply that ratio on every
    // resize, which made the window a 1600x480 letterbox that fought anyone who
    // tried to change it. That single binding was most of why the Admin read as
    // scaffolding rather than a tool: an operator console is a full-screen
    // thing, and there is no shape a supervisor's dashboard wants less than a
    // strip with no vertical room for the lists that are the entire point.
    //
    // Maximized rather than Window.FullScreen: the title bar and taskbar stay,
    // so the operator can minimise, alt-tab and see a clock. FullScreen reads
    // as a kiosk, which is wrong for the machine doing the supervising and
    // awkward to escape from mid-demonstration.
    visibility: Window.Maximized

    // Only used when someone restores the window down. The minimums matter more
    // than these do: the lab is demonstrated on projectors and second machines,
    // so the layout has to hold at 1024x768 as well as at full HD. Everything
    // below is anchored and proportional for that reason -- maximized is not a
    // licence for fixed coordinates.
    width: 1400
    height: 900

    minimumWidth: 1024
    minimumHeight: 700

    visible: true
    title: "Lab Monitor - Administrator"

    header: ToolBar {
        // Tall enough for Material's floating field labels. At the default
        // height "Engine host" and "Port" were clipped off the top edge, which
        // reads as a rendering fault rather than a spacing one.
        height: 76

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 10

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

            // Tabs sized to their labels, not stretched across the window.
            // A TabBar distributes its width equally among its buttons unless
            // they set one, so three tabs across a maximized window became
            // three 640px slabs -- which is most of what "the dimensions look
            // distorted" meant (issues.md C17).
            TabBar {
                id: tabs
                Layout.fillWidth: true

                TabButton { text: "Monitoring"; width: implicitWidth + 24 }
                TabButton { text: "Reports"; width: implicitWidth + 24 }
                TabButton { text: "Policy"; width: implicitWidth + 24 }
            }

            StackLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: tabs.currentIndex

                MonitoringPanel {}
                ReportsPanel {}
                PolicyPanel {}
            }

            // Proportional AND capped. The proportion was added when the window
            // was a 480px strip, where a fixed 260 panel swallowed the tab above
            // it; maximized, the same expression just pins to 260 and the data
            // views get the rest, which is the right split for a console whose
            // job is showing lists.
            CommandPanel {
                Layout.fillWidth: true
                Layout.preferredHeight: Math.min(300, Math.round(window.height * 0.34))
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
