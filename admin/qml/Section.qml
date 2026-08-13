// A titled panel: hairline border, small radius, an uppercase label and an
// optional one-line explanation under it.
//
// Replaces GroupBox, whose framed-title look belongs to a desktop idiom from
// twenty years ago and which gave every group the same visual weight. Here the
// title is quiet (letterspaced, dim, small) and the content is loud, which is
// the right way round for a console: the operator is looking for a value, not
// for the name of the box it lives in.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

Rectangle {
    id: root

    property string title: ""
    property string hint: ""
    property color accent: "transparent"
    default property alias content: body.data

    color: Theme.surface
    radius: Theme.radius
    border.width: 1
    border.color: Theme.border

    implicitHeight: layout.implicitHeight + Theme.space3 * 2

    // A colour strip along the top edge, used only where a section carries a
    // consequence worth flagging (anything that acts on every machine).
    Rectangle {
        visible: root.accent !== "transparent"
        anchors.top: parent.top
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.margins: 1
        height: 2
        radius: 1
        color: root.accent
    }

    ColumnLayout {
        id: layout
        anchors.fill: parent
        anchors.margins: Theme.space3
        spacing: Theme.space2

        Label {
            visible: root.title !== ""
            text: root.title.toUpperCase()
            color: Theme.textDim
            font.pixelSize: Theme.fontTiny
            font.letterSpacing: 1.1
            font.bold: true
            Layout.fillWidth: true
        }

        Label {
            visible: root.hint !== ""
            text: root.hint
            color: Theme.textFaint
            font.pixelSize: Theme.fontSmall
            wrapMode: Text.Wrap
            Layout.fillWidth: true
            Layout.bottomMargin: Theme.space1
        }

        ColumnLayout {
            id: body
            spacing: Theme.space2
            Layout.fillWidth: true
            Layout.fillHeight: true
        }
    }
}
