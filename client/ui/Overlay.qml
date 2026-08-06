// Fullscreen lockout overlay.
//
// A translucent scrim over the primary display with a centred panel, rather
// than an opaque takeover — the README's stated intent is "the impression of a
// locked screen with a single dialog".
//
// The scrim covers the whole screen and swallows mouse events, so nothing
// underneath is clickable while this is up. Geometry comes from Python so the
// overlay is pinned to the primary display rather than guessing.

import QtQuick
import QtQuick.Window
import QtQuick.Layouts

Window {
    id: win

    flags: Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
    color: "transparent"
    visible: bridge.showWindows

    x: bridge.screenX
    y: bridge.screenY
    width: bridge.screenWidth
    height: bridge.screenHeight

    Theme { id: theme }

    // Scrim: covers everything and eats every mouse event.
    Rectangle {
        id: scrim

        anchors.fill: parent
        color: theme.scrim
        opacity: 0

        NumberAnimation on opacity {
            to: 1
            duration: 320
            easing.type: theme.easingType
        }

        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            acceptedButtons: Qt.AllButtons
            cursorShape: Qt.ForbiddenCursor
            onClicked: nudge.restart()
            onPressed: nudge.restart()
        }
    }

    Rectangle {
        id: panel

        anchors.centerIn: parent
        width: Math.min(560, win.width - 120)
        implicitHeight: content.implicitHeight + theme.panelPadding * 2
        height: implicitHeight
        radius: theme.radius
        color: theme.surface
        border.width: 1
        border.color: theme.surfaceEdge

        opacity: 0
        scale: 0.97

        ParallelAnimation {
            running: true
            NumberAnimation {
                target: panel; property: "opacity"; to: 1
                duration: 380; easing.type: theme.easingType
            }
            NumberAnimation {
                target: panel; property: "scale"; to: 1
                duration: 380; easing.type: theme.easingType
            }
        }

        // Clicking the scrim draws attention back to the panel rather than
        // doing nothing, so the machine does not read as simply frozen.
        SequentialAnimation {
            id: nudge
            NumberAnimation {
                target: panel; property: "scale"; to: 1.015
                duration: 110; easing.type: Easing.OutQuad
            }
            NumberAnimation {
                target: panel; property: "scale"; to: 1.0
                duration: 160; easing.type: Easing.OutQuad
            }
        }

        ColumnLayout {
            id: content

            anchors.fill: parent
            anchors.margins: theme.panelPadding
            spacing: 18

            RowLayout {
                Layout.fillWidth: true
                spacing: 14

                Rectangle {
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 40
                    radius: 20
                    color: theme.warningWash
                    border.width: 1
                    border.color: theme.warning

                    Text {
                        anchors.centerIn: parent
                        text: "!"
                        color: theme.warning
                        font.pixelSize: 20
                        font.family: "Segoe UI"
                        font.weight: Font.Bold
                    }
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 2

                    Text {
                        Layout.fillWidth: true
                        text: "Lab access is restricted"
                        color: theme.textPrimary
                        font.pixelSize: 21
                        font.family: "Segoe UI"
                        font.weight: Font.DemiBold
                        wrapMode: Text.Wrap
                    }

                    Text {
                        text: "Scheduled restriction period"
                        color: theme.textMuted
                        font.pixelSize: 12
                        font.family: "Segoe UI"
                    }
                }
            }

            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: theme.surfaceEdge
            }

            Text {
                Layout.fillWidth: true
                text: bridge.message
                color: theme.textSecondary
                font.pixelSize: 13
                font.family: "Segoe UI"
                lineHeight: 1.4
                wrapMode: Text.Wrap
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.topMargin: 4
                spacing: 8

                Text {
                    text: "Access returns in"
                    color: theme.textMuted
                    font.pixelSize: 11
                    font.family: "Segoe UI"
                }

                Text {
                    Layout.fillWidth: true
                    text: bridge.countdown
                    color: theme.accent
                    font.pixelSize: 40
                    font.family: "Consolas"
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 4
                    radius: 2
                    color: theme.raised

                    Rectangle {
                        height: parent.height
                        radius: parent.radius
                        color: theme.accent
                        width: parent.width * bridge.progress

                        Behavior on width {
                            NumberAnimation { duration: 950; easing.type: Easing.Linear }
                        }
                    }
                }
            }

            Text {
                Layout.fillWidth: true
                Layout.topMargin: 4
                text: "This screen clears automatically. Contact a lab supervisor "
                      + "if you believe this is an error."
                color: theme.textMuted
                font.pixelSize: 11
                font.family: "Segoe UI"
                wrapMode: Text.Wrap
            }
        }
    }
}
