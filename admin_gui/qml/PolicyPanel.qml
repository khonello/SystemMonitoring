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

            RowLayout {
                anchors.fill: parent

                TextField {
                    id: blockedApp
                    Layout.fillWidth: true
                    enabled: root.ready
                    placeholderText: "Process to terminate on sight, e.g. steam.exe"
                }

                Button {
                    text: "Terminate now"
                    enabled: root.ready && blockedApp.text.trim().length > 0
                    onClicked: backend.terminateProcess(blockedApp.text.trim(), false)
                }
            }
        }

        Label {
            Layout.fillWidth: true
            wrapMode: Text.Wrap
            opacity: 0.6
            font.pixelSize: 11
            text: "Enforcement runs on the client and is a Phase 4 stub - commands " +
                  "are dispatched and audited, but the agent replies \"not implemented\"."
        }
    }
}
