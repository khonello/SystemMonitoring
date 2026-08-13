// Access-control policy editor.
//
// The asymmetry here is deliberate, not an oversight: website filtering offers
// both blacklist and whitelist, applications are blacklist-only. Whitelisting
// applications cannot reliably enumerate OS and helper processes, so unlisted
// applications are allowed by design (README "Access Control").
//
// LAYOUT. Four stacked GroupBoxes gave every control the same weight, so
// "terminate one process" looked exactly as consequential as "block every
// machine in the room". It is now two columns of sections, ordered by blast
// radius: standing policy for one machine on the left, immediate and
// fleet-wide actions on the right, with the destructive ones carrying a red
// edge and their own confirmation. An operator should be able to tell what a
// control will do to how many people before reading its label.

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "."

Item {
    id: root

    readonly property bool ready: backend.connected && backend.selectedClient !== ""

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space3
        spacing: Theme.space3

        // --- context -------------------------------------------------------

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            ColumnLayout {
                spacing: 1

                Label {
                    text: root.ready ? "Policy for " + backend.selectedClient
                                     : "No client selected"
                    color: Theme.text
                    font.pixelSize: Theme.fontLarge
                    font.bold: true
                }

                Label {
                    text: root.ready
                        ? "Standing policy is re-enforced every collection cycle"
                        : "Select a machine on the left to edit its policy"
                    color: Theme.textFaint
                    font.pixelSize: Theme.fontSmall
                }
            }

            Item { Layout.fillWidth: true }

            // A standing reminder of what "all clients" means right now. The
            // number is the difference between an abstract warning and an
            // informed decision.
            Rectangle {
                visible: backend.connected
                implicitWidth: fleetLabel.implicitWidth + Theme.space3 * 2
                implicitHeight: 26
                radius: Theme.radius
                color: Theme.surfaceHigh
                border.width: 1
                border.color: Theme.border

                Label {
                    id: fleetLabel
                    anchors.centerIn: parent
                    text: clientModel.count + " machine" + (clientModel.count === 1 ? "" : "s") + " known"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
            }
        }

        // --- the two columns -----------------------------------------------

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.space3

            // Left: standing policy, scoped to the selected machine.
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                spacing: Theme.space3

                Section {
                    title: "Website filtering"
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        SegmentedControl {
                            id: policyMode
                            segments: [{ text: "Blacklist" }, { text: "Whitelist" }]
                        }

                        Item { Layout.fillWidth: true }

                        ComboBox {
                            id: policyAction
                            model: ["block", "unblock", "replace"]
                            Layout.preferredWidth: 116
                            Layout.preferredHeight: Theme.controlHeight
                            font.pixelSize: Theme.fontBody
                        }
                    }

                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        font.pixelSize: Theme.fontSmall
                        color: policyMode.currentIndex === 1 ? Theme.warn : Theme.textFaint
                        text: policyMode.currentIndex === 1
                            ? "Only these domains will load. Expect pages to break unless their " +
                              "CDN, font and SSO domains are listed too - accepted for locked-down " +
                              "sessions such as exams."
                            : "These domains are blocked; everything else loads. The right default " +
                              "for general lab use."
                    }

                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        TextArea {
                            id: urlList
                            enabled: root.ready
                            wrapMode: TextEdit.NoWrap
                            font.family: Theme.mono
                            font.pixelSize: Theme.fontBody
                            placeholderText: "One domain per line\nfacebook.com\nyoutube.com"
                        }
                    }

                    Button {
                        text: "Apply website policy"
                        highlighted: true
                        Layout.alignment: Qt.AlignRight
                        Layout.preferredHeight: Theme.controlHeight
                        font.pixelSize: Theme.fontBody
                        enabled: root.ready && urlList.text.trim().length > 0
                        onClicked: backend.setWebsitePolicy(
                            policyMode.currentIndex === 1 ? "whitelist" : "blacklist",
                            urlList.text, policyAction.currentText)
                    }
                }

                Section {
                    title: "Application blacklist"
                    hint: "Blacklist only, by design: whitelisting cannot enumerate OS and " +
                          "helper processes. Re-enforced every cycle, so blocking a launch " +
                          "means terminating shortly after it starts. An empty list clears it."
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    ScrollView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true

                        TextArea {
                            id: appList
                            enabled: root.ready
                            wrapMode: TextEdit.NoWrap
                            font.family: Theme.mono
                            font.pixelSize: Theme.fontBody
                            placeholderText: "One process per line\nsteam.exe\ndiscord.exe"
                        }
                    }

                    Button {
                        text: "Apply blacklist"
                        highlighted: true
                        Layout.alignment: Qt.AlignRight
                        Layout.preferredHeight: Theme.controlHeight
                        font.pixelSize: Theme.fontBody
                        enabled: root.ready
                        onClicked: backend.setAppBlacklist(appList.text)
                    }
                }
            }

            // Right: things that happen now, and things that reach everyone.
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                spacing: Theme.space3

                Section {
                    title: "Terminate a process now"
                    hint: "One-off, on the selected machine. Unrelated to the standing blacklist."
                    Layout.fillWidth: true

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        TextField {
                            id: blockedApp
                            Layout.fillWidth: true
                            Layout.preferredHeight: Theme.controlHeight
                            enabled: root.ready
                            font.family: Theme.mono
                            font.pixelSize: Theme.fontBody
                            placeholderText: "steam.exe"
                        }

                        Button {
                            text: "Terminate"
                            Layout.preferredHeight: Theme.controlHeight
                            font.pixelSize: Theme.fontBody
                            Material.accent: Theme.danger
                            highlighted: true
                            enabled: root.ready && blockedApp.text.trim().length > 0
                            onClicked: backend.terminateProcess(blockedApp.text.trim(), false)
                        }
                    }
                }

                Section {
                    title: "Scheduled block"
                    accent: Theme.warn
                    hint: "The student sees a countdown to the end of the window. A pause, by " +
                          "contrast, shows none. Enforcement is local, so it survives losing " +
                          "the network and a reboot."
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    GridLayout {
                        columns: 3
                        columnSpacing: Theme.space2
                        rowSpacing: Theme.space2
                        Layout.fillWidth: true

                        Label {
                            text: "Block for"
                            color: Theme.textDim
                            font.pixelSize: Theme.fontBody
                        }

                        SpinBox {
                            id: blockDuration
                            from: 1; to: 24 * 60; stepSize: 15; value: 60
                            editable: true
                            enabled: backend.connected
                            Layout.preferredWidth: 150
                            Layout.preferredHeight: Theme.controlHeight
                        }

                        Label {
                            text: "minutes"
                            color: Theme.textFaint
                            font.pixelSize: Theme.fontBody
                            Layout.fillWidth: true
                        }

                        Label {
                            text: "Starting in"
                            color: Theme.textDim
                            font.pixelSize: Theme.fontBody
                        }

                        SpinBox {
                            id: blockDelay
                            from: 0; to: 24 * 60; stepSize: 5; value: 0
                            editable: true
                            enabled: backend.connected
                            Layout.preferredWidth: 150
                            Layout.preferredHeight: Theme.controlHeight
                        }

                        Label {
                            text: blockDelay.value === 0 ? "minutes (immediately)" : "minutes"
                            color: Theme.textFaint
                            font.pixelSize: Theme.fontBody
                            Layout.fillWidth: true
                        }
                    }

                    // Only appears when it applies. A warning that is always on
                    // screen is furniture; one that appears when you cross a
                    // line is information.
                    Rectangle {
                        visible: blockDuration.value > backend.maxBlockHours * 60
                        Layout.fillWidth: true
                        implicitHeight: capLabel.implicitHeight + Theme.space2 * 2
                        radius: Theme.radius
                        color: Qt.rgba(0.82, 0.6, 0.13, 0.12)
                        border.width: 1
                        border.color: Theme.warn

                        Label {
                            id: capLabel
                            anchors.fill: parent
                            anchors.margins: Theme.space2
                            wrapMode: Text.Wrap
                            color: Theme.warn
                            font.pixelSize: Theme.fontSmall
                            text: "The client caps a single block at " + backend.maxBlockHours +
                                  "h and will shorten this. The cap is a safety timeout against " +
                                  "the overlay hanging, not a policy - re-apply for longer."
                        }
                    }

                    Item { Layout.fillHeight: true }

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        Button {
                            text: "Block this machine"
                            highlighted: true
                            Layout.preferredHeight: Theme.controlHeight
                            font.pixelSize: Theme.fontBody
                            enabled: root.ready
                            onClicked: backend.setTimeRestriction(
                                blockDuration.value, blockDelay.value, false)
                        }

                        Button {
                            text: "Clear"
                            flat: true
                            Layout.preferredHeight: Theme.controlHeight
                            font.pixelSize: Theme.fontBody
                            enabled: root.ready
                            onClicked: backend.clearTimeRestriction(false)
                        }

                        Item { Layout.fillWidth: true }
                    }
                }

                // Everything that reaches every machine lives in one place,
                // marked, at the bottom. Blocking one machine is recoverable by
                // walking to it; blocking the room is not.
                Section {
                    title: "Every connected machine"
                    accent: Theme.danger
                    hint: "These reach the whole lab at once."
                    Layout.fillWidth: true

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        Button {
                            text: "Block all"
                            Layout.preferredHeight: Theme.controlHeight
                            font.pixelSize: Theme.fontBody
                            Material.accent: Theme.danger
                            highlighted: true
                            enabled: backend.connected
                            onClicked: confirmBlockAll.open()
                        }

                        Button {
                            text: "Clear all blocks"
                            flat: true
                            Layout.preferredHeight: Theme.controlHeight
                            font.pixelSize: Theme.fontBody
                            enabled: backend.connected
                            onClicked: backend.clearTimeRestriction(true)
                        }

                        Item { Layout.fillWidth: true }
                    }
                }
            }
        }
    }

    // Blocking one machine is recoverable by walking to it. Blocking the room
    // is not, so that one asks first.
    Dialog {
        id: confirmBlockAll
        anchors.centerIn: Overlay.overlay
        modal: true
        title: "Block every connected machine?"
        standardButtons: Dialog.Ok | Dialog.Cancel

        Label {
            width: 380
            wrapMode: Text.Wrap
            color: Theme.text
            font.pixelSize: Theme.fontBody
            text: "All " + clientModel.count + " known machines will be locked for " +
                  blockDuration.value + " minutes" +
                  (blockDelay.value > 0
                      ? ", starting in " + blockDelay.value + " minutes." : ".") +
                  "\n\nEnforcement is local: clearing it needs the clients to be " +
                  "reachable again, though each block lapses on its own regardless."
        }

        onAccepted: backend.setTimeRestriction(
            blockDuration.value, blockDelay.value, true)
    }
}
