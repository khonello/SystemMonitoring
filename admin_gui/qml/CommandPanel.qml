// Command dispatch.
// PHASE 1 SCAFFOLD - controls call backend slots that only log.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    property string selectedClient: ""

    readonly property bool ready: backend.connected && root.selectedClient !== ""

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

            Button {
                text: "Run script"
                enabled: root.ready && scriptInput.text.length > 0
                onClicked: backend.sendScript(
                    root.selectedClient, scriptInput.text, scriptType.currentText)
            }

            Button {
                text: "Screenshot"
                enabled: root.ready
                onClicked: backend.captureScreen(root.selectedClient, 80)
            }
        }

        ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true

            TextArea {
                id: scriptInput
                placeholderText: root.ready
                    ? "Script to run on " + root.selectedClient
                    : "Connect and select a client"
                enabled: root.ready
                wrapMode: TextEdit.NoWrap
                font.family: "Consolas, monospace"
            }
        }

        RowLayout {
            Layout.fillWidth: true

            TextField {
                id: processName
                placeholderText: "Process name, e.g. chrome.exe"
                enabled: root.ready
                Layout.fillWidth: true
            }

            CheckBox {
                id: forceKill
                text: "Force"
                enabled: root.ready
            }

            Button {
                text: "Terminate"
                enabled: root.ready && processName.text.length > 0
                onClicked: backend.terminateProcess(
                    root.selectedClient, processName.text, forceKill.checked)
            }
        }
    }
}
