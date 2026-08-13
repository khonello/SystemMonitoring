// The fleet: every machine known to the Engine, connected or not.
//
// A left rail rather than a page of its own, so selection can never become a
// hidden mode — the operator can always see which machine every other panel is
// talking about (issues.md C17). Selection also drives the live subscription,
// so this list is what makes a machine stream at three seconds.
//
// Rows are dense and quiet. Colour appears only where it means something: a
// state dot per machine, and an accent edge on the selected row.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Rectangle {
    id: root

    color: Theme.surface

    Rectangle {
        anchors.right: parent.right
        width: 1
        height: parent.height
        color: Theme.border
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // --- header --------------------------------------------------------

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 40
            color: "transparent"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.space3
                anchors.rightMargin: Theme.space2
                spacing: Theme.space2

                Label {
                    text: "MACHINES"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontTiny
                    font.letterSpacing: 1.1
                    font.bold: true
                }

                Rectangle {
                    implicitWidth: countLabel.implicitWidth + 12
                    implicitHeight: 16
                    radius: 8
                    color: Theme.surfaceHigh

                    Label {
                        id: countLabel
                        anchors.centerIn: parent
                        text: clientModel.count
                        color: Theme.textDim
                        font.pixelSize: Theme.fontTiny
                        font.bold: true
                    }
                }

                Item { Layout.fillWidth: true }

                ToolButton {
                    text: "Refresh"
                    enabled: backend.connected
                    font.pixelSize: Theme.fontSmall
                    implicitHeight: 26
                    onClicked: backend.refreshClients()
                }
            }

            Rectangle {
                anchors.bottom: parent.bottom
                width: parent.width
                height: 1
                color: Theme.border
            }
        }

        // --- the machines ---------------------------------------------------

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: clientModel

            delegate: Rectangle {
                required property int index
                required property string client_id
                required property string hostname
                required property bool connected
                required property bool paused

                readonly property bool selected: backend.selectedClient === client_id

                width: list.width
                height: 52
                color: selected ? Qt.rgba(0.30, 0.55, 1.0, 0.10)
                                : (hover.hovered ? Qt.rgba(1, 1, 1, 0.03) : "transparent")

                Behavior on color { ColorAnimation { duration: 90 } }

                // The selected machine gets an edge, not a fill: at a glance you
                // want to find it, not have it shout.
                Rectangle {
                    width: 2
                    height: parent.height
                    color: parent.selected ? Theme.accent : "transparent"
                }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.space3
                    anchors.rightMargin: Theme.space2
                    spacing: Theme.space2

                    // One dot, three states. Paused outranks connected because
                    // a paused machine is the one an operator needs to notice.
                    Rectangle {
                        width: 8; height: 8; radius: 4
                        Layout.alignment: Qt.AlignVCenter
                        color: !parent.parent.connected ? Theme.textFaint
                             : parent.parent.paused ? Theme.warn
                             : Theme.ok
                    }

                    ColumnLayout {
                        spacing: 0
                        Layout.fillWidth: true

                        Label {
                            text: hostname || client_id
                            color: Theme.text
                            font.pixelSize: Theme.fontBody
                            font.bold: selected
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }

                        Label {
                            text: client_id
                            color: Theme.textFaint
                            font.pixelSize: Theme.fontTiny
                            font.family: Theme.mono
                            elide: Text.ElideMiddle
                            Layout.fillWidth: true
                        }
                    }

                    Label {
                        visible: paused
                        text: "PAUSED"
                        color: Theme.warn
                        font.pixelSize: Theme.fontTiny
                        font.bold: true
                        font.letterSpacing: 0.8
                    }

                    // Only the watched machine says so, and only in the rail —
                    // the footer repeats it for the operator who is looking at
                    // the far side of the window.
                    Label {
                        visible: selected
                        text: "LIVE"
                        color: Theme.accent
                        font.pixelSize: Theme.fontTiny
                        font.bold: true
                        font.letterSpacing: 0.8
                    }
                }

                HoverHandler { id: hover }
                TapHandler { onTapped: backend.selectedClient = client_id }
            }

            ScrollBar.vertical: ScrollBar {}
        }

        // --- empty state -----------------------------------------------------

        Label {
            visible: clientModel.count === 0
            Layout.fillWidth: true
            Layout.margins: Theme.space4
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            color: Theme.textFaint
            font.pixelSize: Theme.fontSmall
            text: backend.connected
                ? "No machines have registered with this Engine yet."
                : "Not connected to an Engine."
        }

        // --- fleet actions ---------------------------------------------------

        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 44
            color: Theme.canvas

            Rectangle {
                width: parent.width
                height: 1
                color: Theme.border
            }

            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.space2
                spacing: Theme.space2

                Button {
                    text: "Pause all"
                    flat: true
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.controlHeight
                    font.pixelSize: Theme.fontSmall
                    enabled: backend.connected
                    onClicked: backend.pauseAll()
                }

                Button {
                    text: "Resume all"
                    flat: true
                    Layout.fillWidth: true
                    Layout.preferredHeight: Theme.controlHeight
                    font.pixelSize: Theme.fontSmall
                    enabled: backend.connected
                    onClicked: backend.resumeAll()
                }
            }
        }
    }
}
