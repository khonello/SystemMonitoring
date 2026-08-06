// Frameless warning dialog.
//
// Draggable by its own surface, since a frameless window has no title bar for
// the OS to move. Answers are reported to Python via `bridge`, which turns
// them into the exit code the agent reads.

import QtQuick
import QtQuick.Window
import QtQuick.Layouts

Window {
    id: win

    flags: Qt.Dialog | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"

    width: 480
    height: panel.implicitHeight + 32
    visible: bridge.showWindows

    Theme { id: theme }

    // Frameless windows are not placed by the window manager, so centre it —
    // slightly above centre, which reads better than dead centre.
    Component.onCompleted: {
        x = Screen.virtualX + (Screen.width - width) / 2
        y = Screen.virtualY + (Screen.height - height) / 2.4
        appear.start()
    }

    Rectangle {
        id: panel

        anchors.centerIn: parent
        width: parent.width - 32
        implicitHeight: content.implicitHeight + theme.panelPadding * 2
        height: implicitHeight
        radius: theme.radius
        color: theme.surface
        border.width: 1
        border.color: theme.surfaceEdge

        opacity: 0
        scale: 0.96

        // Entrance: fade and settle. Fast enough not to delay a warning.
        ParallelAnimation {
            id: appear
            NumberAnimation {
                target: panel; property: "opacity"; to: 1
                duration: theme.durationBase; easing.type: theme.easingType
            }
            NumberAnimation {
                target: panel; property: "scale"; to: 1
                duration: theme.durationBase; easing.type: theme.easingType
            }
        }

        // Frameless means dragging is ours to provide.
        MouseArea {
            anchors.fill: parent
            onPressed: win.startSystemMove()
        }

        ColumnLayout {
            id: content

            anchors.fill: parent
            anchors.margins: theme.panelPadding
            spacing: 14

            RowLayout {
                Layout.fillWidth: true
                spacing: 12

                Rectangle {
                    Layout.preferredWidth: 4
                    Layout.preferredHeight: title.implicitHeight
                    radius: 2
                    color: theme.warning
                }

                Text {
                    id: title
                    Layout.fillWidth: true
                    text: bridge.title
                    color: theme.textPrimary
                    font.pixelSize: 17
                    font.family: "Segoe UI"
                    font.weight: Font.DemiBold
                    wrapMode: Text.Wrap
                }
            }

            Text {
                Layout.fillWidth: true
                text: bridge.message
                color: theme.textSecondary
                font.pixelSize: 13
                font.family: "Segoe UI"
                lineHeight: 1.35
                wrapMode: Text.Wrap
            }

            // A shrinking bar reads as "time passing" without the user having
            // to parse a number.
            ColumnLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 6
                visible: bridge.totalSeconds > 0

                Text {
                    text: bridge.remainingSeconds > 0
                        ? "Closing automatically in " + bridge.remainingSeconds + "s"
                        : "Closing..."
                    color: theme.textMuted
                    font.pixelSize: 11
                    font.family: "Segoe UI"
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 3
                    radius: 2
                    color: theme.raised

                    Rectangle {
                        height: parent.height
                        radius: parent.radius
                        color: theme.warning
                        width: parent.width * (bridge.totalSeconds > 0
                            ? bridge.remainingSeconds / bridge.totalSeconds : 0)

                        Behavior on width {
                            NumberAnimation { duration: 900; easing.type: Easing.Linear }
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.topMargin: 6
                spacing: 10

                Item { Layout.fillWidth: true }

                ActionButton {
                    theme: theme
                    label: "Cancel"
                    visible: bridge.allowCancel
                    onClicked: bridge.cancel()
                }

                ActionButton {
                    theme: theme
                    label: "OK"
                    primary: true
                    onClicked: bridge.accept()
                }
            }
        }
    }

    // Enter accepts; Escape cancels only when cancelling is offered, so a
    // warning that must be acknowledged cannot be dismissed with a keypress.
    Shortcut {
        sequences: ["Return", "Enter"]
        onActivated: bridge.accept()
    }

    Shortcut {
        sequence: "Escape"
        enabled: bridge.allowCancel
        onActivated: bridge.cancel()
    }
}
