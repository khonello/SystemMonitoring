// Flat button with hover and press states.
// Hand-rolled rather than QtQuick.Controls' Button so the frameless windows
// keep one look regardless of the platform style Qt picks up.
//
// Note it does NOT redeclare `enabled` — Item already provides it, and
// shadowing a base member is both a QML warning and a genuine trap.

import QtQuick

Item {
    id: root

    property Theme theme
    property string label: ""
    property bool primary: false

    signal clicked()

    implicitWidth: Math.max(112, text.implicitWidth + 40)
    implicitHeight: 38
    opacity: enabled ? 1.0 : 0.4

    Behavior on opacity {
        NumberAnimation { duration: root.theme.durationFast }
    }

    Rectangle {
        anchors.fill: parent
        radius: 8
        color: root.primary
            ? (mouse.containsMouse && !mouse.pressed ? root.theme.accentHover
                                                     : root.theme.accent)
            : (mouse.containsMouse ? root.theme.raised : "transparent")
        border.width: root.primary ? 0 : 1
        border.color: root.theme.surfaceEdge

        scale: mouse.pressed && root.enabled ? 0.97 : 1.0

        Behavior on color {
            ColorAnimation { duration: root.theme.durationFast }
        }
        Behavior on scale {
            NumberAnimation {
                duration: root.theme.durationFast
                easing.type: root.theme.easingType
            }
        }
    }

    Text {
        id: text

        anchors.centerIn: parent
        text: root.label
        color: root.primary ? "#0b0f14" : root.theme.textPrimary
        font.pixelSize: 13
        font.family: "Segoe UI"
        font.weight: root.primary ? Font.DemiBold : Font.Normal
    }

    MouseArea {
        id: mouse

        anchors.fill: parent
        hoverEnabled: true
        enabled: root.enabled
        cursorShape: root.enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: root.clicked()
    }
}
