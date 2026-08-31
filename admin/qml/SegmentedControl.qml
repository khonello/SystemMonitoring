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
//
// THE ACTIVE SEGMENT USED TO BE ALMOST INVISIBLE. It was one surface step
// lighter than the track -- #1b212a against #0d1014 -- plus bold text, which is
// fine for "which list am I looking at?" and badly wrong for "am I about to put
// this machine in whitelist mode?". The same control was carrying a view switch
// and a consequential mode switch with the same near-zero contrast.
//
// So the active segment is now tinted with its own colour and underlined in it,
// and a segment may declare that colour: the view switches stay accent-blue,
// while whitelist -- the mode that breaks pages if you get it wrong -- comes up
// amber and says so. Colour is doing the same job here as everywhere else in
// this console: accent means selected, warn means be careful.

import QtQuick
import QtQuick.Controls
import "."

Item {
    id: root

    // [{ text: "Applications", count: 52 }, { text: "Whitelist", tint: Theme.warn }]
    property var segments: []
    property int currentIndex: 0

    // Colour for a segment that does not name its own.
    property color tint: Theme.accent

    function tintOf(index) {
        var segment = root.segments[index]
        return (segment && segment.tint !== undefined) ? segment.tint : root.tint
    }

    readonly property color activeTint: tintOf(root.currentIndex)

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
                    readonly property color tint: root.tintOf(index)

                    height: root.height - 4
                    width: label.implicitWidth + 26
                    radius: Theme.radius - 1
                    color: active ? Qt.rgba(tint.r, tint.g, tint.b, 0.18)
                                  : (hover.hovered ? Qt.rgba(1, 1, 1, 0.05) : "transparent")

                    border.width: active ? 1 : 0
                    border.color: Qt.rgba(tint.r, tint.g, tint.b, 0.5)

                    Behavior on color { ColorAnimation { duration: 90 } }

                    // A solid bar along the bottom of the active segment. The
                    // tint alone reads at a glance; the bar is what makes it
                    // unambiguous on a projector, where subtle fills wash out.
                    Rectangle {
                        visible: active
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        anchors.leftMargin: 5
                        anchors.rightMargin: 5
                        height: 2
                        radius: 1
                        color: tint
                    }

                    Row {
                        id: label
                        anchors.centerIn: parent
                        spacing: 6

                        Label {
                            text: modelData.text
                            color: active ? tint : Theme.textDim
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
                            color: active ? Qt.rgba(tint.r, tint.g, tint.b, 0.3)
                                          : Qt.rgba(1, 1, 1, 0.06)

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
