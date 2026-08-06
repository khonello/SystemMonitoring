// Command dispatch and live script output.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    readonly property bool ready: backend.connected && backend.selectedClient !== ""

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 6

        RowLayout {
            Layout.fillWidth: true

            Label {
                text: "Commands"
                font.bold: true
            }

            Item { Layout.fillWidth: true }

            ComboBox {
                id: scriptType
                model: ["python", "powershell"]
                Layout.preferredWidth: 130
            }

            // Predefined scripts are extensions for small routine tasks, so
            // execution is capped. The client clamps this to 900s regardless.
            Label { text: "Limit" }

            SpinBox {
                id: scriptTimeout
                from: 10
                to: 900
                stepSize: 30
                value: 300
                editable: true
                Layout.preferredWidth: 120

                textFromValue: function (value) { return value + "s" }
                valueFromText: function (text) { return parseInt(text) || 300 }
            }

            // Checking without sending lets an operator learn the policy
            // before committing, rather than only being told off on send.
            Button {
                text: "Check"
                enabled: scriptInput.text.trim().length > 0
                onClicked: backend.checkScript(scriptInput.text, scriptType.currentText)
            }

            Button {
                text: "Run script"
                enabled: root.ready && scriptInput.text.trim().length > 0
                // Validated locally before it is sent; a script that will not
                // compile, or that breaks the stdlib-only policy, never
                // reaches a lab machine.
                onClicked: backend.sendScript(
                    scriptInput.text, scriptType.currentText, scriptTimeout.value)
            }

            Button {
                text: "Screenshot"
                enabled: root.ready
                onClicked: backend.captureScreen(80)
            }

            ToolSeparator {}

            // Indeterminate to the student: no countdown is shown on the
            // client. The internal cap is an admin fail-safe, surfaced here
            // as a warning rather than there as a deadline.
            Button {
                text: "Pause"
                enabled: root.ready
                onClicked: backend.pauseSelected()
            }

            Button {
                text: "Resume"
                enabled: root.ready
                onClicked: backend.resumeSelected()
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
                    font.family: "Consolas, monospace"
                    placeholderText: root.ready
                        ? "Script to run on " + backend.selectedClient
                        : "Connect and select a client"
                }
            }

            ScrollView {
                SplitView.fillWidth: true

                TextArea {
                    id: outputView
                    readOnly: true
                    wrapMode: TextEdit.NoWrap
                    font.family: "Consolas, monospace"
                    placeholderText: "Script output appears here as it arrives"
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
            implicitHeight: visible ? checkText.implicitHeight + 16 : 0
            radius: 4
            color: passed ? "#12261a" : "#2b1416"
            border.width: 1
            border.color: passed ? "#2e6b45" : "#8b3a3f"

            RowLayout {
                anchors.fill: parent
                anchors.margins: 8
                spacing: 8

                Label {
                    text: checkResult.passed ? "✓" : "✕"
                    color: checkResult.passed ? "#4fbf7b" : "#f0736f"
                    font.pixelSize: 14
                    font.bold: true
                    Layout.alignment: Qt.AlignTop
                }

                Label {
                    id: checkText
                    Layout.fillWidth: true
                    text: checkResult.detail
                    color: checkResult.passed ? "#9fd8b6" : "#f0a9a6"
                    font.pixelSize: 11
                    wrapMode: Text.Wrap
                }

                Label {
                    text: "✕"
                    color: "#6e7681"
                    font.pixelSize: 12
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
            color: "#6e7681"
            font.pixelSize: 10
            wrapMode: Text.Wrap
        }

        RowLayout {
            Layout.fillWidth: true

            TextField {
                id: processName
                Layout.fillWidth: true
                enabled: root.ready
                placeholderText: "Process name, e.g. chrome.exe"
            }

            CheckBox {
                id: forceKill
                text: "Force"
                enabled: root.ready
            }

            Button {
                text: "Terminate"
                enabled: root.ready && processName.text.trim().length > 0
                onClicked: backend.terminateProcess(processName.text.trim(), forceKill.checked)
            }

            ToolSeparator {}

            Button {
                text: "Clear output"
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
