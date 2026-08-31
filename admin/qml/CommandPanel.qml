// Command dispatch and live script output.

import QtQuick
import QtQuick.Controls
import QtQuick.Controls.Material
import QtQuick.Layouts
import "."

Item {
    id: root

    readonly property bool ready: backend.connected && backend.selectedClient !== ""

    // A toolbar strip, not a panel: every control is one row height, so the
    // whole bar is 30px rather than the 56 it was when a ComboBox and a SpinBox
    // each brought their own padding. The vertical space this returns goes to
    // the thing an operator is actually reading -- the output below.
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.space3
        spacing: Theme.space2

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            Label {
                text: "COMMANDS"
                color: Theme.textDim
                font.pixelSize: Theme.fontTiny
                font.letterSpacing: 1.1
                font.bold: true
            }

            Item { Layout.fillWidth: true }

            ComboBox {
                id: scriptType
                model: ["python", "powershell"]
                Layout.preferredWidth: 118
                Layout.preferredHeight: Theme.controlHeight
                font.pixelSize: Theme.fontBody
            }

            // Predefined scripts are extensions for small routine tasks, so
            // execution is capped. The client clamps this to 900s regardless.
            SpinBox {
                id: scriptTimeout
                from: 10
                to: 900
                stepSize: 30
                value: 300
                editable: true
                Layout.preferredWidth: 132
                Layout.preferredHeight: Theme.controlHeight
                font.pixelSize: Theme.fontBody

                textFromValue: function (value) { return value + "s" }
                valueFromText: function (text) { return parseInt(text) || 300 }
            }

            // Checking without sending lets an operator learn the policy
            // before committing, rather than only being told off on send.
            Button {
                text: "Check"
                flat: true
                Layout.preferredHeight: Theme.controlHeight
                font.pixelSize: Theme.fontBody
                enabled: scriptInput.text.trim().length > 0
                onClicked: backend.checkScript(scriptInput.text, scriptType.currentText)
            }

            Button {
                text: "Run script"
                highlighted: true
                Layout.preferredHeight: Theme.controlHeight
                font.pixelSize: Theme.fontBody
                enabled: root.ready && scriptInput.text.trim().length > 0
                // Validated locally before it is sent; a script that will not
                // compile, or that breaks the stdlib-only policy, never
                // reaches a lab machine.
                onClicked: backend.sendScript(
                    scriptInput.text, scriptType.currentText, scriptTimeout.value)
            }

            Button {
                text: "Screenshot"
                flat: true
                Layout.preferredHeight: Theme.controlHeight
                font.pixelSize: Theme.fontBody
                enabled: root.ready
                onClicked: backend.captureScreen(80)
            }

            Rectangle { width: 1; height: 20; color: Theme.border }

            // Pause and Resume moved to the Restrictions page. Here they were
            // two flat buttons that looked identical whether the machine was
            // held or not, so the bar showed a control for a state without ever
            // showing the state; on Restrictions they sit beside a pill that
            // says which it is, and only the applicable one is enabled.
            //
            // What stays is a read-only indicator, because an operator running
            // a script needs to know the screen is held without changing page.
            StatePill {
                visible: root.ready && backend.selectedPaused
                text: "SCREEN HELD"
                tint: Theme.warn
            }

            StatePill {
                visible: root.ready && backend.idleSeconds >= 900
                text: "IDLE " + backend.idleText
                tint: Theme.textDim
                muted: true
            }
        }

        SplitView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            orientation: Qt.Horizontal

            ScrollView {
                SplitView.preferredWidth: root.width * 0.5

                TextArea {
                    id: scriptInput
                    enabled: root.ready
                    wrapMode: TextEdit.NoWrap
                    font.family: Theme.mono
                    font.pixelSize: Theme.fontBody
                    placeholderText: root.ready
                        ? "Script to run on " + backend.selectedClient
                        : "Connect and select a client"
                }
            }

            ScrollView {
                id: outputScroll
                SplitView.fillWidth: true

                // Follow the tail as output arrives, the way a log viewer does.
                // A script can run for minutes and the interesting line is
                // almost always the last one, so a pane that stays pinned to
                // the top hides exactly what the operator is waiting for.
                //
                // But only while the view is ALREADY at the bottom. Someone who
                // has scrolled up is reading something, and yanking them back
                // on the next chunk makes long output impossible to follow.
                TextArea {
                    id: outputView
                    readOnly: true
                    wrapMode: TextEdit.NoWrap
                    font.family: Theme.mono
                    font.pixelSize: Theme.fontBody
                    placeholderText: "Script output appears here as it arrives"

                    property bool following: true

                    onTextChanged: if (following) Qt.callLater(outputScroll.toBottom)
                }

                function toBottom() {
                    const bar = ScrollBar.vertical
                    if (bar) { bar.position = Math.max(0, 1.0 - bar.size) }
                }

                // Re-arm as soon as the operator returns to the bottom, so
                // following is the resting state rather than something you have
                // to ask for again.
                ScrollBar.vertical.onPositionChanged: {
                    const bar = ScrollBar.vertical
                    outputView.following = bar.size >= 1.0 ||
                                           bar.position >= 1.0 - bar.size - 0.01
                }
            }
        }

        // Validation result. Always visible once a check has run, pass or
        // fail — seeing which imports were accepted teaches the rule, where a
        // silent success teaches nothing.
        Rectangle {
            id: checkResult

            property string detail: ""
            property bool passed: true

            Layout.fillWidth: true
            visible: detail !== ""
            implicitHeight: visible ? checkText.implicitHeight + Theme.space4 : 0
            radius: Theme.radius
            color: passed ? Qt.rgba(0.25, 0.73, 0.31, 0.10)
                          : Qt.rgba(0.94, 0.28, 0.28, 0.10)
            border.width: 1
            border.color: passed ? Theme.ok : Theme.danger

            RowLayout {
                anchors.fill: parent
                anchors.margins: Theme.space2
                spacing: Theme.space2

                Label {
                    text: checkResult.passed ? "✓" : "✕"
                    color: checkResult.passed ? Theme.ok : Theme.danger
                    font.pixelSize: Theme.fontMedium
                    font.bold: true
                    Layout.alignment: Qt.AlignTop
                }

                Label {
                    id: checkText
                    Layout.fillWidth: true
                    text: checkResult.detail
                    color: checkResult.passed ? Theme.text : Theme.text
                    font.pixelSize: Theme.fontSmall
                    wrapMode: Text.Wrap
                }

                Label {
                    text: "✕"
                    color: Theme.textFaint
                    font.pixelSize: Theme.fontBody
                    Layout.alignment: Qt.AlignTop

                    MouseArea {
                        anchors.fill: parent
                        anchors.margins: -4
                        cursorShape: Qt.PointingHandCursor
                        onClicked: checkResult.detail = ""
                    }
                }
            }
        }

        Label {
            Layout.fillWidth: true
            text: "Python scripts: standard library only, and only modules "
                  + "available on Windows. No third-party packages - the "
                  + "client's runtime has no pip."
            color: Theme.textFaint
            font.pixelSize: Theme.fontTiny
            wrapMode: Text.Wrap
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.space2

            TextField {
                id: processName
                Layout.fillWidth: true
                Layout.preferredHeight: Theme.controlHeight
                enabled: root.ready
                font.family: Theme.mono
                font.pixelSize: Theme.fontBody
                placeholderText: "Process to terminate, e.g. chrome.exe"
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
                highlighted: processName.text.trim().length > 0
                enabled: root.ready && processName.text.trim().length > 0
                onClicked: backend.terminateProcess(processName.text.trim(), forceKill.checked)
            }

            Rectangle { width: 1; height: 20; color: Theme.border }

            Button {
                text: "Clear output"
                flat: true
                Layout.preferredHeight: Theme.controlHeight
                font.pixelSize: Theme.fontBody
                onClicked: outputView.text = ""
            }
        }
    }

    Connections {
        target: backend

        // Streamed in chunks as the script produces output - a long-running
        // script reports continuously rather than only at exit.
        function onCommandOutput(commandId, chunk) {
            outputView.append(chunk.replace(/\n$/, ""))
        }

        function onCommandFinished(commandId, status, message) {
            outputView.append("--- " + commandId + ": " + status + " " + message)
        }

        function onScriptChecked(summary, passed) {
            checkResult.detail = summary
            checkResult.passed = passed
        }
    }
}
