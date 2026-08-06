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

            Button {
                text: "Run script"
                enabled: root.ready && scriptInput.text.trim().length > 0
                // Validated locally before it is sent; a script that will not
                // compile never reaches a lab machine.
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
    }
}
