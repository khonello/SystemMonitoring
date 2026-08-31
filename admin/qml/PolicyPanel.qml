// Standing policy for the selected machine: the rules the agent re-enforces on
// every collection cycle.
//
// WHAT MOVED OUT, AND WHY. This page used to carry standing policy *and* every
// immediate and fleet-wide action -- terminate a process, schedule a block,
// block the whole room -- in two columns ordered by blast radius. Ordering them
// was an improvement on stacking them, but it did not fix the underlying
// problem: two different kinds of thing were sharing one page, so the two lists
// that are the actual policy were squeezed into a half-width column with room
// for about four visible lines each.
//
// The split is along a line the protocol already draws. These two commands are
// in DURABLE_COMMANDS: they declare state the machine should converge to, so
// the Engine queues them for a machine that is offline and replays them on its
// next registration. Everything on the Restrictions page is a point-in-time
// action that is recorded as undeliverable instead. "Will be applied whenever
// this machine next appears" and "happens now or not at all" are different
// promises, and they should not be made by adjacent buttons.
//
// The asymmetry between the two lists is deliberate, not an oversight: website
// filtering offers blacklist and whitelist, applications are blacklist-only,
// because whitelisting applications cannot reliably enumerate the OS and helper
// processes a machine needs (README "Access Control").

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "."

Item {
    id: root

    readonly property bool ready: backend.connected && backend.selectedClient !== ""
    readonly property bool whitelist: policyMode.currentIndex === 1

    // Mirrors `_normalise` in client/policy.py: the agent strips the scheme,
    // the path and the port before writing a hosts entry, so a pasted URL is
    // fine and must not be reported as an error. What is checked is what the
    // line reduces to.
    function normaliseDomain(line) {
        var host = line.trim().toLowerCase().replace(/^https?:\/\//, "")
        return host.split("/")[0].split("?")[0].split(":")[0].trim()
    }

    // No wildcards. A hosts file has no `*.example.com`; the agent would write
    // the asterisk literally and the entry would match nothing, which is the
    // silent failure this check exists to prevent. (The agent does add the
    // `www.` form of every domain by itself.)
    function isDomain(line) {
        return /^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$/.test(
            root.normaliseDomain(line))
    }

    // A Windows image name. Anything with a path separator is a mistake: the
    // client compares process names, not paths.
    function isProcess(line) {
        return /^[^\\/:*?"<>|]+$/.test(line) && line.length <= 260
    }

    // Load each machine's last-sent policy into the editors when the selection
    // changes. Without this the boxes keep whatever was typed for the previous
    // machine while the state pills describe the new one -- an empty editor
    // reading "edited, not sent" against a policy that was in fact sent. The
    // editors are per-machine views, so they have to follow the selection.
    Connections {
        target: backend

        function onSelectedClientChanged() {
            urlList.text = backend.appliedWebsites
            appList.text = backend.appliedApps
            policyMode.currentIndex = backend.appliedWebsiteMode === "whitelist" ? 1 : 0
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space3
        spacing: Theme.space3

        // --- context ---------------------------------------------------------

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            ColumnLayout {
                spacing: 1
                Layout.fillWidth: true
                Layout.minimumWidth: 0

                Label {
                    text: root.ready ? "Standing policy for " + backend.selectedClient
                                     : "No machine selected"
                    color: Theme.text
                    font.pixelSize: Theme.fontLarge
                    font.bold: true
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                Label {
                    text: root.ready
                        ? "Re-enforced every collection cycle. Queued and replayed if this " +
                          "machine is offline when you apply it."
                        : "Choose a machine on the left to edit its policy"
                    color: Theme.textFaint
                    font.pixelSize: Theme.fontSmall
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }
            }

            StatePill {
                visible: root.ready
                text: backend.selectedPaused ? "PAUSED" : "RUNNING"
                tint: backend.selectedPaused ? Theme.warn : Theme.ok
                muted: !backend.selectedPaused
            }
        }

        // --- the two standing rules -------------------------------------------

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: Theme.space3

            Section {
                title: "Website filtering"
                accent: root.whitelist ? Theme.warn : "transparent"
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space2

                    // Whitelist declares its own colour, so switching into the
                    // restrictive mode is visible before you read the label.
                    SegmentedControl {
                        id: policyMode
                        segments: [
                            { text: "Blacklist" },
                            { text: "Whitelist", tint: Theme.warn }
                        ]
                    }

                    Item { Layout.fillWidth: true }

                    Label {
                        text: "on apply"
                        color: Theme.textFaint
                        font.pixelSize: Theme.fontSmall
                    }

                    ComboBox {
                        id: policyAction
                        model: ["block", "unblock", "replace"]
                        Layout.preferredWidth: 112
                        Layout.preferredHeight: Theme.controlHeight
                        font.pixelSize: Theme.fontBody
                    }
                }

                // The consequence of the mode, stated in the mode's own colour
                // so the warning and the control agree with each other.
                Rectangle {
                    Layout.fillWidth: true
                    implicitHeight: modeNote.implicitHeight + Theme.space2 * 2
                    radius: Theme.radius
                    color: root.whitelist ? Qt.rgba(0.82, 0.6, 0.13, 0.10) : "transparent"
                    border.width: root.whitelist ? 1 : 0
                    border.color: Qt.rgba(0.82, 0.6, 0.13, 0.45)

                    Label {
                        id: modeNote
                        anchors.fill: parent
                        anchors.margins: Theme.space2
                        wrapMode: Text.Wrap
                        font.pixelSize: Theme.fontSmall
                        color: root.whitelist ? Theme.warn : Theme.textFaint
                        text: root.whitelist
                            ? "Whitelist: only these domains will load and everything else is " +
                              "refused. Expect pages to break unless their CDN, font and SSO " +
                              "domains are listed too - accepted for locked-down sessions such " +
                              "as exams."
                            : "Blacklist: these domains are blocked and everything else loads. " +
                              "The right default for general lab use."
                    }
                }

                ListEditor {
                    id: urlList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    enabled: root.ready
                    unit: "domain"
                    unitPlural: "domains"
                    validate: root.isDomain
                    invalidNote: "Not hostnames, so the client has nothing to match. " +
                                 "No wildcards - a hosts file cannot express them"
                    sentText: backend.appliedWebsites
                    sentAt: backend.appliedWebsitesAt
                    placeholder: "One domain per line. A pasted URL is reduced to its\n" +
                                 "host, and the www. form is blocked automatically.\n\n" +
                                 "facebook.com\nyoutube.com\ntiktok.com"
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space2

                    Label {
                        visible: urlList.everSent && urlList.sentAt !== ""
                        text: "Last sent as " + backend.appliedWebsiteMode + " at " +
                              backend.appliedWebsitesAt
                        color: Theme.textFaint
                        font.pixelSize: Theme.fontSmall
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    Item { Layout.fillWidth: !urlList.everSent }

                    Button {
                        text: urlList.modified || !urlList.everSent
                            ? "Apply website policy" : "Re-apply"
                        highlighted: urlList.modified
                        flat: !urlList.modified
                        Layout.preferredHeight: Theme.controlHeight
                        font.pixelSize: Theme.fontBody
                        Material.accent: root.whitelist ? Theme.warn : Theme.accent
                        enabled: root.ready && urlList.count > 0
                        onClicked: backend.setWebsitePolicy(
                            root.whitelist ? "whitelist" : "blacklist",
                            urlList.text, policyAction.currentText)
                    }
                }
            }

            Section {
                title: "Application blacklist"
                hint: "Blacklist only, by design: whitelisting cannot enumerate the OS and " +
                      "helper processes a machine needs. Re-enforced every cycle, so blocking " +
                      "a launch means terminating it shortly after it starts."
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredWidth: 1

                ListEditor {
                    id: appList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    enabled: root.ready
                    unit: "process"
                    unitPlural: "processes"
                    validate: root.isProcess
                    invalidNote: "Not process names - the client compares image names, " +
                                 "not paths"
                    sentText: backend.appliedApps
                    sentAt: backend.appliedAppsAt
                    placeholder: "One process per line\nsteam.exe\ndiscord.exe"
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.space2

                    // An empty list is a real instruction, and one worth
                    // spelling out rather than leaving the operator to infer
                    // from a button that stayed enabled.
                    Label {
                        text: appList.count === 0
                            ? "Applying an empty list clears the blacklist."
                            : (appList.everSent ? "Last sent at " + backend.appliedAppsAt : "")
                        color: Theme.textFaint
                        font.pixelSize: Theme.fontSmall
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    Button {
                        text: appList.count === 0 ? "Clear blacklist"
                            : (appList.modified || !appList.everSent
                                ? "Apply blacklist" : "Re-apply")
                        highlighted: appList.modified
                        flat: !appList.modified
                        Layout.preferredHeight: Theme.controlHeight
                        font.pixelSize: Theme.fontBody
                        enabled: root.ready
                        onClicked: backend.setAppBlacklist(appList.text)
                    }
                }
            }
        }
    }
}
