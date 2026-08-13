"""The Qt Quick Controls style, chosen in exactly one place.

WHY THIS MODULE EXISTS AT ALL. Nothing set a style before, so the console
inherited the platform default: Windows' own chrome around Qt's dark content,
which is why the window arrived looking like two half-finished themes stacked
on each other -- a white title bar, a light toolbar, a dark body and light grey
text areas (`issues.md` C17).

WHY BOTH ENTRY POINTS CALL IT. `--check-qml` loads the same QML offscreen to
report errors and warnings. If it ran under a different style than the console
does, it would be checking a different tree of controls than the one that
ships, and the Material attached properties in main.qml would warn there while
working in the real window. A check that does not exercise what ships is the
same class of mistake as running a check as the wrong user.

Material rather than Fusion: it has a coherent dark palette out of the box and
takes accent and background as attached properties, so the whole console is
themed from four lines in main.qml instead of a hand-built QPalette.
"""

from __future__ import annotations


def apply_style() -> None:
    """Select the Controls style. Must be called before any QML is loaded."""
    from PySide6.QtQuickControls2 import QQuickStyle

    QQuickStyle.setStyle("Material")
