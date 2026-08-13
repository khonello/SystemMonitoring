// One number, its label, and an optional unit. Used in the strip across the top
// of the monitoring view.
//
// The point of a stat strip on an operator console is that the answers to "is
// this machine alive, busy, or quiet?" should be readable from across a room,
// without reading a table. So the value is large and monospaced -- monospaced
// specifically because a number that changes every three seconds must not make
// the layout twitch as digits change width.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Rectangle {
    id: root

    property string label: ""
    property string value: "--"
    property string unit: ""
    property color tint: Theme.accent

    implicitWidth: 128
    implicitHeight: 56
    radius: Theme.radius
    color: Theme.surface
    border.width: 1
    border.color: Theme.border

    Rectangle {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.margins: 1
        width: 2
        radius: 1
        color: root.tint
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.space3
        anchors.rightMargin: Theme.space2
        anchors.topMargin: Theme.space2
        anchors.bottomMargin: Theme.space2
        spacing: 2

        Label {
            text: root.label.toUpperCase()
            color: Theme.textDim
            font.pixelSize: Theme.fontTiny
            font.letterSpacing: 1.0
            elide: Text.ElideRight
            Layout.fillWidth: true
        }

        RowLayout {
            spacing: 4
            Layout.fillWidth: true

            Label {
                text: root.value
                color: Theme.text
                font.pixelSize: Theme.fontHuge
                font.family: Theme.mono
                elide: Text.ElideRight
            }

            Label {
                visible: root.unit !== ""
                text: root.unit
                color: Theme.textFaint
                font.pixelSize: Theme.fontSmall
                Layout.alignment: Qt.AlignBottom
                Layout.bottomMargin: 3
            }

            Item { Layout.fillWidth: true }
        }
    }
}
