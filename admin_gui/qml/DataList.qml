// Three-column list used by every data view: label, sub-label, trailing value.
// The accessor properties are functions so each view can pull different keys
// out of its own model without duplicating this layout.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    property alias model: listView.model
    property string emptyText: "No data"

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

    Label {
        anchors.centerIn: parent
        width: parent.width - 40
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        visible: listView.count === 0
        opacity: 0.5
        text: root.emptyText
    }
}
