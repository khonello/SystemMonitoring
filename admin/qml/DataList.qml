// Three-column list used by every data view: label, sub-label, trailing value.
// The accessor properties are functions so each view can pull different keys
// out of its own model without duplicating this layout.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

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
            height: 44
            color: index % 2 === 0 ? "transparent" : Qt.rgba(0.5, 0.5, 0.5, 0.06)

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 10

                ColumnLayout {
                    spacing: 1
                    Layout.fillWidth: true

                    Label {
                        text: root.primary(model)
                        font.bold: true
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    Label {
                        text: root.secondary(model)
                        opacity: 0.6
                        font.pixelSize: 11
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }

                Label {
                    text: root.trailing(model)
                    font.family: "Consolas, monospace"
                    font.pixelSize: 11
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
            font.bold: true
            font.pixelSize: 14
            opacity: 0.75
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }

        Label {
            text: root.emptyText
            wrapMode: Text.Wrap
            opacity: 0.55
            horizontalAlignment: Text.AlignHCenter
            Layout.fillWidth: true
        }
    }
}
