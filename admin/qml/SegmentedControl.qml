// A compact segmented switch: one recessed track, the active segment raised.
//
// WHY THIS EXISTS. The console had a TabBar directly beneath another TabBar --
// same shape, same weight, two different meanings -- and it read as a mistake
// because visually it *is* one. Nesting is fine; nesting a control inside an
// identical control is not. Top-level navigation stays underlined tabs; a
// choice *within* a page is this instead, so the two levels never look alike.
//
// Counts are supported because "Applications (52)" is a fact worth carrying in
// the control rather than in a label beside it.

import QtQuick
import QtQuick.Controls
import "."

Item {
    id: root

    // [{ text: "Applications", count: 52 }, { text: "Network" }]
    property var segments: []
    property int currentIndex: 0

    implicitHeight: 28
    implicitWidth: track.implicitWidth

    Rectangle {
        id: track
        anchors.fill: parent
        radius: Theme.radius
        color: Theme.canvas
        border.width: 1
        border.color: Theme.border
        implicitWidth: row.implicitWidth + 4

        Row {
            id: row
            anchors.verticalCenter: parent.verticalCenter
            anchors.left: parent.left
            anchors.leftMargin: 2
            spacing: 2

            Repeater {
                model: root.segments

                delegate: Rectangle {
                    required property int index
                    required property var modelData

                    readonly property bool active: root.currentIndex === index

                    height: root.height - 4
                    width: label.implicitWidth + 26
                    radius: Theme.radius - 1
                    color: active ? Theme.surfaceHigh
                                  : (hover.hovered ? Qt.rgba(1, 1, 1, 0.04) : "transparent")

                    Behavior on color { ColorAnimation { duration: 90 } }

                    Row {
                        id: label
                        anchors.centerIn: parent
                        spacing: 6

                        Label {
                            text: modelData.text
                            color: active ? Theme.text : Theme.textDim
                            font.pixelSize: Theme.fontBody
                            font.bold: active
                            anchors.verticalCenter: parent.verticalCenter
                        }

                        // The count sits in its own chip so a changing number
                        // never shifts the label beside it.
                        Rectangle {
                            visible: modelData.count !== undefined
                            anchors.verticalCenter: parent.verticalCenter
                            width: countLabel.implicitWidth + 10
                            height: 16
                            radius: 8
                            color: active ? Theme.accentDim : Qt.rgba(1, 1, 1, 0.06)

                            Label {
                                id: countLabel
                                anchors.centerIn: parent
                                text: modelData.count !== undefined ? modelData.count : ""
                                color: active ? Theme.text : Theme.textFaint
                                font.pixelSize: Theme.fontTiny
                                font.bold: true
                            }
                        }
                    }

                    HoverHandler { id: hover }
                    TapHandler { onTapped: root.currentIndex = index }
                }
            }
        }
    }
}
