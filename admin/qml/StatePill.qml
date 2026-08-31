// A small badge that says what state something is in right now.
//
// WHY THIS EXISTS. The console had several controls whose whole job was to
// report a state -- paused or not, applied or not, blocked or not -- and the
// only difference between the two states was a slightly different grey. On a
// near-black canvas that is a distinction an operator has to hunt for, and a
// state you have to hunt for is one that gets misread under pressure.
//
// A pill states the state in words, in its own colour, with a filled dot. It is
// not a control: it never accepts a click, so it can never be confused with the
// button that changes the thing it describes.

import QtQuick
import QtQuick.Controls
import "."

Rectangle {
    id: root

    property string text: ""
    property color tint: Theme.textFaint

    // Off states are drawn quietly: an unblocked machine is the normal case and
    // should not compete with the one that is blocked.
    property bool muted: false

    implicitWidth: row.implicitWidth + Theme.space3 * 2
    implicitHeight: 22
    radius: 11

    color: root.muted ? "transparent" : Qt.rgba(root.tint.r, root.tint.g, root.tint.b, 0.14)
    border.width: 1
    border.color: root.muted ? Theme.border
                             : Qt.rgba(root.tint.r, root.tint.g, root.tint.b, 0.55)

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6

        Rectangle {
            width: 6
            height: 6
            radius: 3
            anchors.verticalCenter: parent.verticalCenter
            color: root.muted ? Theme.textFaint : root.tint
        }

        Label {
            text: root.text
            color: root.muted ? Theme.textFaint : root.tint
            font.pixelSize: Theme.fontTiny
            font.bold: true
            font.letterSpacing: 0.6
            anchors.verticalCenter: parent.verticalCenter
        }
    }
}
