// Shared visual language for the client-side helper windows.
// Kept in one place so the dialog and the overlay cannot drift apart.
//
// A plain QtObject instantiated per window rather than a QML singleton: a
// singleton needs a qmldir and a declared module, which then competes with the
// context properties the Python host installs. Any Theme.qml in this directory
// is usable as the type `Theme` by its siblings with no registration at all.

import QtQuick

QtObject {
    // Surfaces
    readonly property color scrim:       "#cc0b0f14"
    readonly property color surface:     "#161b22"
    readonly property color surfaceEdge: "#30363d"
    readonly property color raised:      "#1f262e"

    // Text
    readonly property color textPrimary:   "#e6edf3"
    readonly property color textSecondary: "#8b949e"
    readonly property color textMuted:     "#6e7681"

    // Accents
    readonly property color accent:      "#58a6ff"
    readonly property color accentHover: "#79b8ff"
    readonly property color warning:     "#d29922"
    readonly property color warningWash: "#2d2113"

    readonly property int radius: 14
    readonly property int panelPadding: 34

    // One easing curve everywhere, so motion reads as a single system.
    readonly property int durationFast: 140
    readonly property int durationBase: 240
    readonly property int easingType: Easing.OutCubic
}
