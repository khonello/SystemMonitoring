// Holding and interrupting machines: the things that act now.
//
// Split out of the Policy page, along the line the protocol already draws.
// Policy carries the two DURABLE_COMMANDS that declare state a machine should
// converge to, and which the Engine queues and replays for a machine that was
// offline. What is here is different in kind: a pause, a termination and a
// clear happen to a machine that is connected, or they do not happen at all and
// are recorded as undeliverable. Putting the two on one page made those two
// very different promises look like the same button.
//
// Ordered down the page by blast radius, which is the order an operator's
// caution should increase in: one process on one machine, then one machine's
// screen, then every machine in the room behind a confirmation.
//
// Every control that reports a state carries a pill rather than relying on a
// colour change: "is this machine paused?" was previously answerable only by
// looking at the roster on the far side of the window.

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "."

Item {
    id: root

    readonly property bool ready: backend.connected && backend.selectedClient !== ""
    readonly property bool paused: root.ready && backend.selectedPaused

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space3
        spacing: Theme.space3

        // --- context -----------------------------------------------------------

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            ColumnLayout {
                spacing: 1
                Layout.fillWidth: true
                Layout.minimumWidth: 0

                Label {
                    text: root.ready ? "Restrictions on " + backend.selectedClient
                                     : "No machine selected"
                    color: Theme.text
                    font.pixelSize: Theme.fontLarge
                    font.bold: true
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                Label {
                    text: root.ready
                        ? "These act on a connected machine now. A machine that is offline " +
                          "records them as undeliverable rather than queuing them."
                        : "Choose a machine on the left"
                    color: Theme.textFaint
                    font.pixelSize: Theme.fontSmall
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }

            StatePill {
                visible: root.ready
                text: root.paused ? "SCREEN HELD" : "NOT HELD"
                tint: Theme.warn
                muted: !root.paused
            }

            StatePill {
                visible: root.ready
                text: backend.idleSeconds < 0 ? "IDLE UNKNOWN"
                    : "IDLE " + backend.idleText
                tint: backend.idleSeconds >= 900 ? Theme.warn : Theme.ok
                muted: backend.idleSeconds < 0
            }

            Rectangle {
                visible: backend.connected
                implicitWidth: fleetLabel.implicitWidth + Theme.space3 * 2
                implicitHeight: 22
                radius: Theme.radius
                color: Theme.surfaceHigh
                border.width: 1
                border.color: Theme.border

                Label {
                    id: fleetLabel
                    anchors.centerIn: parent
                    text: clientModel.count + " machine" +
                          (clientModel.count === 1 ? "" : "s") + " known"
                    color: Theme.textDim
                    font.pixelSize: Theme.fontSmall
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.space3

            // Left: this machine.
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                spacing: Theme.space3

                // A pause has no stated end and shows the student no countdown.
                // The cap is an admin fail-safe, so it is surfaced here and
                // deliberately never on the client (README "Access Control").
                Section {
                    title: "Hold this screen"
                    hint: "A pause has no end time and the student sees no countdown, just " +
                          "\"paused\" - it is held until you resume it. It lapses on its own " +
                          "after " + backend.pauseCapMinutes + " minutes, which is a safety " +
                          "net against an operator who forgets rather than a promise to the " +
                          "student, and is why the client never shows it. A pause outranks a " +
                          "scheduled block: dropping it while the window is still open falls " +
                          "back to the countdown rather than releasing the machine."
                    Layout.fillWidth: true

                    RowLayout {
                        Layout.fillWidth: true
                        spacing: Theme.space2

                        StatePill {
                            text: root.paused ? "HELD NOW" : "NOT HELD"
                            tint: Theme.warn
                            muted: !root.paused
                        }

                        Item { Layout.fillWidth: true }

                        // Two buttons rather than one toggle: which one is
                        // available says what state the machine is in, and
                        // neither can be pressed into a no-op by accident.
                        Button {
                            text: "Pause"
                            Layout.preferredHeight: Theme.controlHeight
                            font.pixelSize: Theme.fontBody
                            Material.accent: Theme.warn
                            highlighted: !root.paused
                            flat: root.paused
                            enabled: root.ready && !root.paused
                            onClicked: backend.pauseSelected()
                        }

                        Button {
                            text: "Resume"
                            Layout.preferredHeight: Theme.controlHeight
                            font.pixelSize: Theme.fontBody
                            highlighted: root.paused
                            flat: !root.paused
                            enabled: root.ready && root.paused
                            onClicked: backend.resumeSelected()
                        }
                    }
                }

                Section {
                    title: "Terminate a process now"
                    hint: "One-off, on the selected machine. Unrelated to the standing " +
                          "blacklist on the Policy page, which keeps re-enforcing."
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

                        CheckBox {
                            id: forceKill
                            text: "Force"
                            enabled: root.ready
                            font.pixelSize: Theme.fontBody
                        }

                        Button {
                            text: "Terminate"
                            Layout.preferredHeight: Theme.controlHeight
                            font.pixelSize: Theme.fontBody
                            Material.accent: Theme.danger
                            highlighted: true
                            enabled: root.ready && blockedApp.text.trim().length > 0
                            onClicked: backend.terminateProcess(
                                blockedApp.text.trim(), forceKill.checked)
                        }
                    }
                }

                Item { Layout.fillHeight: true }
            }

            // Right: scheduled, then everyone.
            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1
                spacing: Theme.space3

                Section {
                    title: "Scheduled block"
                    accent: Theme.warn
                    hint: "The student sees a countdown to the end of the window - which is " +
                          "what makes this different from a pause. Enforcement is local, so " +
                          "it survives losing the network and a reboot."
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

                    // A plain-English restatement of the two spin boxes. Two
                    // numbers and a unit are easy to read individually and easy
                    // to get wrong together.
                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        color: Theme.textDim
                        font.pixelSize: Theme.fontSmall
                        text: blockDelay.value === 0
                            ? "Locks the screen now, for " + blockDuration.value +
                              " minutes."
                            : "Locks the screen in " + blockDelay.value + " minutes, for " +
                              blockDuration.value + " minutes after that."
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
                            Material.accent: Theme.warn
                            enabled: root.ready
                            onClicked: backend.setTimeRestriction(
                                blockDuration.value, blockDelay.value, false)
                        }

                        Button {
                            text: "Clear block"
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
                // Two mechanisms, not four buttons. Grouped and captioned
                // because side by side and unlabelled, "Block all" and "Pause
                // all" read as the same action twice -- and the difference
                // between them is the difference between a lab that unlocks
                // itself and one that waits for you.
                Section {
                    title: "Every connected machine"
                    accent: Theme.danger
                    hint: "These reach the whole lab at once."
                    Layout.fillWidth: true

                    GridLayout {
                        Layout.fillWidth: true
                        columns: 2
                        columnSpacing: Theme.space3
                        rowSpacing: Theme.space2

                        Label {
                            text: "Pause"
                            color: Theme.text
                            font.pixelSize: Theme.fontBody
                            font.bold: true
                            Layout.alignment: Qt.AlignTop
                            Layout.preferredWidth: 104
                        }

                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                            text: "No end time, and the student sees no countdown - just " +
                                  "\"paused\". Held until you resume it, and it lapses on its " +
                                  "own after " + backend.pauseCapMinutes + " minutes so an " +
                                  "unattended console cannot hold the lab. Machines that are " +
                                  "off are not paused when they return."
                        }

                        Item { width: 1; height: 1 }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.space2

                            Button {
                                text: "Pause all"
                                Layout.preferredHeight: Theme.controlHeight
                                font.pixelSize: Theme.fontBody
                                Material.accent: Theme.warn
                                highlighted: true
                                enabled: backend.connected
                                onClicked: backend.pauseAll()
                            }

                            Button {
                                text: "Resume all"
                                flat: true
                                Layout.preferredHeight: Theme.controlHeight
                                font.pixelSize: Theme.fontBody
                                enabled: backend.connected
                                onClicked: backend.resumeAll()
                            }

                            Item { Layout.fillWidth: true }
                        }

                        Rectangle {
                            Layout.columnSpan: 2
                            Layout.fillWidth: true
                            Layout.topMargin: Theme.space1
                            Layout.bottomMargin: Theme.space1
                            height: 1
                            color: Theme.border
                        }

                        Label {
                            text: "Scheduled block"
                            color: Theme.text
                            font.pixelSize: Theme.fontBody
                            font.bold: true
                            Layout.alignment: Qt.AlignTop
                            Layout.preferredWidth: 104
                        }

                        Label {
                            Layout.fillWidth: true
                            wrapMode: Text.Wrap
                            color: Theme.textDim
                            font.pixelSize: Theme.fontSmall
                            text: "Ends by itself after the " + blockDuration.value +
                                  " minutes set above, and the student sees it counting " +
                                  "down. Stored on each machine, so it survives a reboot and " +
                                  "losing the network - and a machine that is off is blocked " +
                                  "when it next connects."
                        }

                        Item { width: 1; height: 1 }

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
