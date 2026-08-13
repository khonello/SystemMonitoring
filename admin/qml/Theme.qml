pragma Singleton

// One place for every colour, radius, spacing step and type size in the
// console. Imported as `Theme.x` from every other file.
//
// WHY A DESIGN SYSTEM AND NOT INLINE VALUES. The Admin is the only component an
// audience looks at for any length of time (issues.md C17), and the thing that
// makes an interface read as unfinished is rarely one bad screen -- it is ten
// screens that each picked their own padding. A shared scale is what makes a
// dense operator console look deliberate rather than assembled.
//
// The palette is a near-black canvas with raised surfaces and hairline borders,
// which is the idiom of monitoring consoles for a practical reason: the data is
// the only bright thing on screen, so the eye goes to it rather than to the
// chrome around it. Accent is used sparingly and means "this is selected or
// active" -- never decoration.

import QtQuick

QtObject {
    // --- surfaces, back to front -------------------------------------------
    readonly property color canvas:      "#0d1014"   // the window itself
    readonly property color surface:     "#141920"   // panels sitting on it
    readonly property color surfaceHigh: "#1b212a"   // inputs, hovered rows
    readonly property color overlay:     "#232b36"   // dialogs, menus

    // --- lines --------------------------------------------------------------
    readonly property color border:      "#242c37"   // hairlines between things
    readonly property color borderStrong:"#333d4b"   // focused, or worth noticing

    // --- text ---------------------------------------------------------------
    readonly property color text:        "#e6ebf2"
    readonly property color textDim:     "#94a1b2"   // secondary, units, hints
    readonly property color textFaint:   "#5d6b7c"   // placeholders, disabled

    // --- meaning ------------------------------------------------------------
    // Accent means selected/active. The rest are states a machine can be in,
    // and they are deliberately few: an operator should be able to learn the
    // whole colour vocabulary in one glance at a legend.
    readonly property color accent:      "#4c8dff"
    readonly property color accentDim:   "#1e3a63"
    readonly property color ok:          "#3fb950"   // online, applied, success
    readonly property color warn:        "#d29922"   // paused, capped, careful
    readonly property color danger:      "#f04747"   // blocked, terminate, all-clients

    // --- geometry -----------------------------------------------------------
    // One radius, small. Material's default pills are why the old console read
    // as a phone app rather than a tool.
    readonly property int radius:        4
    readonly property int radiusLarge:   6

    // A 4px spacing scale. Everything is a multiple, which is most of what
    // "polished" actually means.
    readonly property int space1:        4
    readonly property int space2:        8
    readonly property int space3:        12
    readonly property int space4:        16
    readonly property int space5:        24

    // Controls share one height so a row of them lines up without nudging.
    readonly property int controlHeight: 30
    readonly property int rowHeight:     34

    // --- type ---------------------------------------------------------------
    readonly property int fontTiny:      10
    readonly property int fontSmall:     11
    readonly property int fontBody:      12
    readonly property int fontMedium:    13
    readonly property int fontLarge:     15
    readonly property int fontHuge:      20

    readonly property string mono: "Consolas, 'Cascadia Mono', monospace"
}
