// Administrator GUI shell.

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import QtQuick.Window
import "."

ApplicationWindow {
    id: window

    // One theme, stated once, and the values live in Theme.qml so nothing here
    // invents its own. The console previously inherited the platform default
    // and arrived as two half-finished themes at once: light title bar and
    // toolbar, dark body, light grey text areas. The style itself is selected
    // in admin/style.py, which both this app and --check-qml call.
    Material.theme: Material.Dark
    Material.background: Theme.canvas
    Material.primary: Theme.surface
    Material.accent: Theme.accent
    Material.foreground: Theme.text

    // ROUNDING, TURNED DOWN. Material's default radii are phone-sized -- pill
    // buttons and heavily rounded fields -- which is most of why the console
    // read as an app rather than an instrument. SmallScale gives a 4px corner
    // that matches Theme.radius, and it is inherited by every control below.
    Material.roundedScale: Material.SmallScale

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

    // The header carries identity on the left, primary navigation in the
    // middle and the connection on the right. Navigation lives up here rather
    // than above the content because it then never sits directly on top of a
    // second row of tabs -- the thing that made the old layout read as a
    // mistake. Within a page, choices use SegmentedControl instead, so the two
    // levels are never the same shape.
    header: Rectangle {
        implicitHeight: 52
        color: Theme.surface

        Rectangle {
            anchors.bottom: parent.bottom
            width: parent.width
            height: 1
            color: Theme.border
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.space4
            anchors.rightMargin: Theme.space4
            spacing: Theme.space4

            RowLayout {
                spacing: Theme.space2

                Rectangle {
                    width: 8; height: 18; radius: 2
                    color: Theme.accent
                }

                Label {
                    text: "LAB MONITOR"
                    color: Theme.text
                    font.pixelSize: Theme.fontMedium
                    font.bold: true
                    font.letterSpacing: 1.4
                }
            }

            Rectangle { width: 1; height: 22; color: Theme.border }

            TabBar {
                id: tabs
                Layout.preferredWidth: contentWidth
                background: null

                TabButton { text: "Monitoring"; width: implicitWidth + 20 }
                TabButton { text: "Reports"; width: implicitWidth + 20 }
                TabButton { text: "Policy"; width: implicitWidth + 20 }
            }

            Item { Layout.fillWidth: true }

            // Connection details collapse to a single line once connected --
            // an address you cannot change is reference information, not a
            // control, and giving it two editable boxes overstates it.
            RowLayout {
                spacing: Theme.space2
                visible: !backend.connected

                TextField {
                    id: hostField
                    text: defaultHost
                    placeholderText: "Engine host"
                    Layout.preferredWidth: 140
                    Layout.preferredHeight: Theme.controlHeight
                    font.pixelSize: Theme.fontBody
                }

                TextField {
                    id: portField
                    text: defaultPort
                    placeholderText: "Port"
                    Layout.preferredWidth: 64
                    Layout.preferredHeight: Theme.controlHeight
                    font.pixelSize: Theme.fontBody
                    validator: IntValidator { bottom: 1; top: 65535 }
                }
            }

            Label {
                visible: backend.connected
                text: hostField.text + ":" + portField.text
                color: Theme.textDim
                font.family: Theme.mono
                font.pixelSize: Theme.fontBody
            }

            Button {
                text: backend.connected ? "Disconnect" : "Connect"
                Layout.preferredHeight: Theme.controlHeight
                highlighted: !backend.connected
                font.pixelSize: Theme.fontBody
                onClicked: backend.connected
                    ? backend.disconnectFromEngine()
                    : backend.connectToEngine(hostField.text, parseInt(portField.text))
            }
        }
    }

    footer: Rectangle {
        implicitHeight: 26
        color: Theme.surface

        Rectangle {
            width: parent.width
            height: 1
            color: Theme.border
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.space4
            anchors.rightMargin: Theme.space4
            spacing: Theme.space2

            Rectangle {
                width: 7; height: 7; radius: 4
                color: backend.connected ? Theme.ok : Theme.danger

                // A slow pulse while connected. The only animation in the
                // console, and it earns its place: it is the difference between
                // "the link is up" and "this window froze ten minutes ago".
                SequentialAnimation on opacity {
                    running: backend.connected
                    loops: Animation.Infinite
                    NumberAnimation { to: 0.35; duration: 1400; easing.type: Easing.InOutQuad }
                    NumberAnimation { to: 1.0;  duration: 1400; easing.type: Easing.InOutQuad }
                }
            }

            Label {
                text: backend.status
                color: Theme.textDim
                font.pixelSize: Theme.fontSmall
                elide: Text.ElideRight
                Layout.fillWidth: true
            }

            Label {
                visible: backend.selectedClient !== ""
                text: "watching " + backend.selectedClient
                color: Theme.accent
                font.pixelSize: Theme.fontSmall
                font.family: Theme.mono
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

            // Navigation moved into the header, so a page's own controls are
            // never a second row of tabs under the first.
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

    // A screen capture used to arrive, be reported as "Captured 1920x1080", and
    // then go nowhere at all — the operator was told it worked and given
    // nothing to look at. It is now written to disk and shown here.
    Dialog {
        id: captureDialog

        property string path: ""
        property string client: ""

        anchors.centerIn: parent
        width: Math.min(window.width - 120, 1100)
        height: Math.min(window.height - 120, 800)
        modal: true
        standardButtons: Dialog.Close
        title: "Screen capture - " + captureDialog.client

        ColumnLayout {
            anchors.fill: parent
            spacing: 8

            Image {
                source: captureDialog.path ? "file:///" + captureDialog.path : ""
                fillMode: Image.PreserveAspectFit
                // Decoded at display size rather than full resolution: a 4K
                // screenshot held at native size is a lot of memory for a
                // preview nobody zooms into.
                sourceSize.width: 1600
                Layout.fillWidth: true
                Layout.fillHeight: true
            }

            // The path is selectable because the useful thing to do with a
            // capture is usually to attach it to something else.
            TextField {
                text: captureDialog.path
                readOnly: true
                Layout.fillWidth: true
                font.pixelSize: 11
            }
        }
    }

    Connections {
        target: backend

        function onCaptureReady(path, clientId) {
            captureDialog.path = path
            captureDialog.client = clientId
            captureDialog.open()
        }

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
