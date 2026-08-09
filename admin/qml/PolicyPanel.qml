// Access-control policy editor.
//
// The asymmetry here is deliberate, not an oversight: website filtering offers
// both blacklist and whitelist, applications are blacklist-only. Whitelisting
// applications cannot reliably enumerate OS and helper processes, so unlisted
// applications are allowed by design (README "Access Control").

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    readonly property bool ready: backend.connected && backend.selectedClient !== ""

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 10

        Label {
            text: root.ready
                ? "Policy for " + backend.selectedClient
                : "Select a client to edit its policy"
            font.bold: true
            font.pixelSize: 14
        }

        GroupBox {
            title: "Website filtering"
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true

                    Label { text: "Mode" }

                    ComboBox {
                        id: policyMode
                        Layout.preferredWidth: 140
                        model: ["blacklist", "whitelist"]
                    }

                    Label {
                        Layout.fillWidth: true
                        wrapMode: Text.Wrap
                        opacity: 0.65
                        font.pixelSize: 11
                        text: policyMode.currentText === "whitelist"
                            ? "Only these domains will load. Expect pages to break unless " +
                              "their CDN, font and SSO domains are listed too - that is " +
                              "accepted for locked-down sessions such as exams."
                            : "These domains are blocked; everything else loads. This is " +
                              "the right default for general lab use."
                    }
                }

                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    TextArea {
                        id: urlList
                        enabled: root.ready
                        wrapMode: TextEdit.NoWrap
                        font.family: "Consolas, monospace"
                        placeholderText: "One domain per line, e.g.\nfacebook.com\nyoutube.com"
                    }
                }

                RowLayout {
                    Layout.fillWidth: true

                    ComboBox {
                        id: policyAction
                        Layout.preferredWidth: 140
                        model: ["block", "unblock", "replace"]
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: "Apply policy"
                        enabled: root.ready && urlList.text.trim().length > 0
                        onClicked: backend.setWebsitePolicy(
                            policyMode.currentText, urlList.text, policyAction.currentText)
                    }
                }
            }
        }

        GroupBox {
            title: "Applications (blacklist only, by design)"
            Layout.fillWidth: true
            Layout.fillHeight: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 6

                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    opacity: 0.65
                    font.pixelSize: 11
                    text: "The standing list, re-enforced every collection cycle. " +
                          "Blocking a launch means terminating shortly after it " +
                          "starts - there is no pre-launch hook without a kernel " +
                          "driver. Applying an empty list clears the blacklist."
                }

                ScrollView {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    TextArea {
                        id: appList
                        enabled: root.ready
                        wrapMode: TextEdit.NoWrap
                        font.family: "Consolas, monospace"
                        placeholderText: "One process per line, e.g.\nsteam.exe\ndiscord.exe"
                    }
                }

                Button {
                    text: "Apply blacklist"
                    enabled: root.ready
                    onClicked: backend.setAppBlacklist(appList.text)
                }
            }
        }

        GroupBox {
            title: "Terminate one process now"
            Layout.fillWidth: true

            RowLayout {
                anchors.fill: parent

                TextField {
                    id: blockedApp
                    Layout.fillWidth: true
                    enabled: root.ready
                    placeholderText: "Process to kill once, e.g. steam.exe"
                }

                Button {
                    text: "Terminate now"
                    enabled: root.ready && blockedApp.text.trim().length > 0
                    onClicked: backend.terminateProcess(blockedApp.text.trim(), false)
                }
            }
        }

        GroupBox {
            title: "Time restriction (scheduled block)"
            Layout.fillWidth: true

            ColumnLayout {
                anchors.fill: parent
                spacing: 6

                RowLayout {
                    Layout.fillWidth: true

                    Label { text: "Block for" }

                    SpinBox {
                        id: blockDuration
                        from: 1
                        to: 24 * 60
                        stepSize: 15
                        value: 60
                        editable: true
                        enabled: backend.connected
                    }

                    Label { text: "min, starting in" }

                    SpinBox {
                        id: blockDelay
                        from: 0
                        to: 24 * 60
                        stepSize: 5
                        value: 0
                        editable: true
                        enabled: backend.connected
                    }

                    Label { text: "min" }

                    Item { Layout.fillWidth: true }
                }

                Label {
                    Layout.fillWidth: true
                    wrapMode: Text.Wrap
                    font.pixelSize: 11
                    opacity: blockDuration.value > backend.maxBlockHours * 60 ? 1.0 : 0.65
                    color: blockDuration.value > backend.maxBlockHours * 60
                        ? "#b34700" : palette.text
                    text: blockDuration.value > backend.maxBlockHours * 60
                        ? "The client caps a single block at " + backend.maxBlockHours +
                          "h and will shorten this. The cap is a safety timeout against " +
                          "the overlay hanging, not a policy - re-apply for a longer session."
                        : "The student sees a countdown to the end of this window. A pause, " +
                          "by contrast, shows none. Enforcement is local, so it survives " +
                          "losing the network and a reboot."
                }

                RowLayout {
                    Layout.fillWidth: true

                    Button {
                        text: "Block selected"
                        enabled: root.ready
                        onClicked: backend.setTimeRestriction(
                            blockDuration.value, blockDelay.value, false)
                    }

                    Button {
                        text: "Block all clients"
                        enabled: backend.connected
                        onClicked: confirmBlockAll.open()
                    }

                    Item { Layout.fillWidth: true }

                    Button {
                        text: "Clear selected"
                        enabled: root.ready
                        onClicked: backend.clearTimeRestriction(false)
                    }

                    Button {
                        text: "Clear all"
                        enabled: backend.connected
                        onClicked: backend.clearTimeRestriction(true)
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
        title: "Block every connected client?"
        standardButtons: Dialog.Ok | Dialog.Cancel

        Label {
            width: 360
            wrapMode: Text.Wrap
            text: "Every connected machine will be locked for " +
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
