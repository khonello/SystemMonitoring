// Three-column list used by every data view: label, sub-label, trailing value.
// The accessor properties are functions so each view can pull different keys
// out of its own model without duplicating this layout.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Item {
    id: root

    property alias model: listView.model
    property string emptyTitle: "No data"
    property string emptyText: ""

    property var primary: function (m) { return "" }
    property var secondary: function (m) { return "" }
    property var trailing: function (m) { return "" }

    ListView {
        id: listView

        anchors.fill: parent
        clip: true
        spacing: 1

        delegate: Rectangle {
            width: listView.width
            height: Theme.rowHeight
            // Hover instead of zebra striping. Alternating fills add a second
            // visual rhythm competing with the data; a row that lights under
            // the cursor tells you where you are without patterning the panel.
            color: rowHover.hovered ? Qt.rgba(1, 1, 1, 0.04) : "transparent"

            HoverHandler { id: rowHover }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.space3
                anchors.rightMargin: Theme.space3
                spacing: Theme.space3

                ColumnLayout {
                    spacing: 1
                    Layout.fillWidth: true

                    Label {
                        text: root.primary(model)
                        color: Theme.text
                        font.pixelSize: Theme.fontBody
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    Label {
                        text: root.secondary(model)
                        color: Theme.textFaint
                        font.pixelSize: Theme.fontTiny
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }

                // Monospaced and right-aligned: figures that change on every
                // sample must line up, or the eye re-reads the column each time.
                Label {
                    text: root.trailing(model)
                    color: Theme.textDim
                    font.family: Theme.mono
                    font.pixelSize: Theme.fontSmall
                    horizontalAlignment: Text.AlignRight
                }
            }
        }
    }

    // EMPTY STATE. issues.md C18: an empty table is indistinguishable from a
    // broken feature, and this used to be one faint centred line at opacity
    // 0.5 -- present, but quiet enough to read as "nothing here". It now states
    // the reason plainly and, where there is one, when to expect data.
    //
    // Three different situations reach this label and they are not the same
    // thing: nothing has arrived YET, this client genuinely HAS none, and no
    // client is selected at all. The caller supplies the wording; this only
    // makes sure it is actually read.
    ColumnLayout {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 420)
        spacing: 6
        visible: listView.count === 0

        Label {
            text: root.emptyTitle
            color: Theme.textDim
            font.bold: true
            font.pixelSize: Theme.fontMedium
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }

        Label {
            text: root.emptyText
            color: Theme.textFaint
            font.pixelSize: Theme.fontSmall
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }
    }
}
