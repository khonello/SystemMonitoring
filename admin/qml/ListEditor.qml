// A one-entry-per-line list, with a count, per-line validation and an honest
// account of whether what is on screen has actually been sent.
//
// WHY THIS EXISTS. Both policy lists were a bare TextArea in a ScrollView with
// a placeholder, and everything an operator needed to know was missing:
//
//   - how many entries are in the box (you counted lines yourself)
//   - whether any of them are malformed (you found out when they silently did
//     nothing on the machine -- `https://facebook.com/` is not a domain, and
//     the client matches hosts, so a pasted URL blocks nothing)
//   - whether the text on screen is what was sent, or an unsent edit
//
// That last one is the important one. A policy editor that looks identical
// before and after Apply, and identical again after you type into it, gives an
// operator no way to answer "did I actually push this?" -- so they push it
// again, which is harmless here and would not be everywhere.
//
// "Sent", never "in force". Nothing in the protocol reports a client's current
// policy back, so this can only honestly describe what this console pushed and
// when. Claiming more would be worse than claiming nothing.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "."

ColumnLayout {
    id: root

    property alias text: editor.text
    property string placeholder: ""
    property string unit: "entry"
    property string unitPlural: "entries"

    // What was last pushed for this machine, and when. Empty `sentAt` means
    // nothing has been sent from this console during this session.
    property string sentText: ""
    property string sentAt: ""

    // A line is checked against this before it counts as valid. The default
    // accepts anything; the website list narrows it to hostnames.
    property var validate: function (line) { return true }

    // Why the flagged lines will not work, in the caller's own terms. Stated by
    // the caller because "malformed" alone sends an operator hunting for the
    // rule they broke.
    property string invalidNote: "The client cannot match these"

    readonly property var lines: editor.text.split("\n")
        .map(function (l) { return l.trim() })
        .filter(function (l) { return l.length > 0 })

    readonly property var invalid: lines.filter(function (l) { return !root.validate(l) })

    readonly property int count: lines.length

    // Compared on the normalised list rather than the raw text, so trailing
    // whitespace or a reordered blank line does not read as an unsent change.
    readonly property bool modified: lines.join("\n") !== root.sentText
    readonly property bool everSent: root.sentAt !== ""

    spacing: Theme.space2

    // --- count, state, clear -------------------------------------------------

    RowLayout {
        Layout.fillWidth: true
        spacing: Theme.space2

        Label {
            text: root.count + " " + (root.count === 1 ? root.unit : root.unitPlural)
            color: root.count > 0 ? Theme.text : Theme.textFaint
            font.pixelSize: Theme.fontSmall
            font.bold: root.count > 0
        }

        StatePill {
            visible: root.invalid.length > 0
            text: root.invalid.length + " MALFORMED"
            tint: Theme.warn
        }

        Item { Layout.fillWidth: true }

        StatePill {
            visible: root.everSent && !root.modified
            text: "SENT " + root.sentAt
            tint: Theme.ok
        }

        StatePill {
            visible: root.modified && root.everSent
            text: "EDITED - NOT SENT"
            tint: Theme.warn
        }

        StatePill {
            visible: !root.everSent
            text: "NOT SENT"
            muted: true
        }

        ToolButton {
            text: "Clear"
            flat: true
            visible: root.count > 0
            implicitHeight: 22
            font.pixelSize: Theme.fontSmall
            onClicked: editor.clear()
        }
    }

    // --- the list itself ------------------------------------------------------

    Rectangle {
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.minimumHeight: 96
        radius: Theme.radius
        color: Theme.canvas
        border.width: 1
        border.color: editor.activeFocus ? Theme.accent
                    : (root.invalid.length > 0 ? Theme.warn : Theme.border)

        Behavior on border.color { ColorAnimation { duration: 110 } }

        ScrollView {
            anchors.fill: parent
            anchors.margins: 1
            clip: true

            TextArea {
                id: editor
                wrapMode: TextEdit.NoWrap
                font.family: Theme.mono
                font.pixelSize: Theme.fontBody
                color: Theme.text
                selectByMouse: true
                leftPadding: Theme.space2
                rightPadding: Theme.space2
                topPadding: Theme.space2
                bottomPadding: Theme.space2

                // An empty Item, not null: the field draws its own frame above
                // and the control must not draw a second one inside it, but the
                // Material style positions its own decorations against the
                // background and loses them when there is nothing there.
                background: Item {}
            }
        }

        // Our own hint, not `placeholderText`. Material treats a placeholder as
        // a floating label: once the field has content the hint shrinks and
        // moves up rather than disappearing, so a pre-filled list was drawn on
        // top of its own ghost. This one is simply absent when there is text.
        Label {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.leftMargin: Theme.space2 + 1
            anchors.topMargin: Theme.space2 + 1
            visible: editor.length === 0
            text: root.placeholder
            color: Theme.textFaint
            font.family: Theme.mono
            font.pixelSize: Theme.fontBody
        }
    }

    // Named, not just counted, and with the reason attached: the offending line
    // is usually obvious once it is quoted back, and the rule it broke is not.
    Label {
        visible: root.invalid.length > 0
        Layout.fillWidth: true
        wrapMode: Text.Wrap
        color: Theme.warn
        font.pixelSize: Theme.fontSmall
        text: root.invalidNote + ": " + root.invalid.slice(0, 3).join(", ") +
              (root.invalid.length > 3 ? " and " + (root.invalid.length - 3) + " more" : "")
    }
}
