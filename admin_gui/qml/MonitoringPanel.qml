// Live monitoring dashboard.
// PHASE 1 SCAFFOLD - placeholders where Phase 3 binds real data.

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

Item {
    id: root

    property string selectedClient: ""

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8

        Label {
            text: root.selectedClient !== ""
                ? "Monitoring: " + root.selectedClient
                : "Select a client"
            font.bold: true
            font.pixelSize: 14
        }

        TabBar {
            id: tabs
            Layout.fillWidth: true

            TabButton { text: "Applications" }
            TabButton { text: "Network" }
            TabButton { text: "USB Events" }
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: tabs.currentIndex

            // TODO(Phase 3): replace each placeholder with a TableView bound
            // to data pushed from the Engine.
            Placeholder { message: "Application usage - Phase 3" }
            Placeholder { message: "Network usage - Phase 3" }
            Placeholder { message: "USB events - Phase 3" }
        }
    }

    component Placeholder: Rectangle {
        property string message: ""

        color: "transparent"
        border.width: 1
        border.color: Qt.rgba(0.5, 0.5, 0.5, 0.3)

        Label {
            anchors.centerIn: parent
            text: parent.message
            opacity: 0.5
        }
    }
}
