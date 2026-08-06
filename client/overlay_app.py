#!/usr/bin/env python3
"""Lockout overlay — bundled as its own executable, spawned on demand.

    python -m client.overlay_app --until 2026-08-06T12:00:00Z

Fullscreen and borderless with a centred dialog-style panel, scoped to the
primary display. Covering every monitor would mean enumerating displays and
managing a window per screen; single-monitor covers the common lab machine
without that complexity, and the limitation is deliberate.

Soft-defeat resistance only, which is the right level for this project:

- The window re-asserts topmost every 500ms, so anything a user Alt-Tabs
  forward is pushed back almost immediately.
- Task Manager is disabled by policy while the overlay is up, and restored
  when it exits.
- A determined user with physical access (safe mode, a live USB, pulling the
  disk) still wins. That is true of all client-side enforcement and is out of
  scope to solve here.

The overlay also closes itself at its own end time. That is a convenience, not
the guarantee — the agent and a Scheduled Task both watch from outside,
precisely because this process might hang.
"""

from __future__ import annotations

import argparse
import ctypes
import logging
import sys
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

IS_WINDOWS = sys.platform == "win32"

TOPMOST_INTERVAL_MS = 500
TICK_INTERVAL_MS = 1000

_TASKMGR_POLICY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Policies\System"
_TASKMGR_POLICY_VALUE = "DisableTaskMgr"


def parse_until(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Task Manager policy
# ---------------------------------------------------------------------------


def set_task_manager_disabled(disabled: bool) -> None:
    """Toggle the standard Task Manager policy.

    Per-user (HKCU) so it needs no elevation. Failures are logged and ignored:
    losing this hardening should never stop the lockout itself from showing.
    """
    if not IS_WINDOWS:
        return

    try:
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_CURRENT_USER, _TASKMGR_POLICY_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if disabled:
                winreg.SetValueEx(key, _TASKMGR_POLICY_VALUE, 0, winreg.REG_DWORD, 1)
            else:
                try:
                    winreg.DeleteValue(key, _TASKMGR_POLICY_VALUE)
                except FileNotFoundError:
                    pass
    except OSError:
        logger.warning("Could not change the Task Manager policy", exc_info=True)


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------


def _force_topmost(window) -> None:
    """Re-assert topmost, at both the Tk and Win32 level."""
    try:
        window.attributes("-topmost", True)
        window.lift()
        window.focus_force()
    except Exception:
        return

    if not IS_WINDOWS:
        return

    try:
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id()) or window.winfo_id()
        HWND_TOPMOST, SWP_NOMOVE, SWP_NOSIZE = -1, 0x0002, 0x0001
        ctypes.windll.user32.SetWindowPos(
            hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE
        )
    except Exception:
        logger.debug("SetWindowPos failed", exc_info=True)


def run_overlay(until: datetime, message: str) -> int:
    """Show the lockout until `until` passes, then exit."""
    import tkinter as tk

    root = tk.Tk()
    root.title("Lab access restricted")
    root.attributes("-fullscreen", True)
    root.configure(bg="#0d1117")
    root.attributes("-alpha", 0.94)
    root.protocol("WM_DELETE_WINDOW", lambda: None)  # ignore Alt-F4

    # Swallow keyboard shortcuts that would otherwise dismiss or bypass it.
    for sequence in ("<Escape>", "<Alt-F4>", "<Control-w>"):
        root.bind(sequence, lambda _event: "break")

    panel = tk.Frame(root, bg="#161b22", padx=48, pady=36,
                     highlightbackground="#30363d", highlightthickness=1)
    panel.place(relx=0.5, rely=0.5, anchor="center")

    tk.Label(panel, text="Lab access is currently restricted",
             font=("Segoe UI", 20, "bold"), fg="#e6edf3", bg="#161b22").pack()

    tk.Label(panel, text=message, font=("Segoe UI", 11), fg="#8b949e",
             bg="#161b22", wraplength=520, justify="center").pack(pady=(12, 20))

    countdown = tk.Label(panel, text="", font=("Consolas", 28),
                         fg="#58a6ff", bg="#161b22")
    countdown.pack()

    tk.Label(panel, text="This screen will clear automatically.",
             font=("Segoe UI", 9), fg="#6e7681", bg="#161b22").pack(pady=(18, 0))

    def tick() -> None:
        remaining = (until - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            root.destroy()
            return

        hours, rest = divmod(int(remaining), 3600)
        minutes, seconds = divmod(rest, 60)
        countdown.config(text=f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        root.after(TICK_INTERVAL_MS, tick)

    def reassert() -> None:
        _force_topmost(root)
        root.after(TOPMOST_INTERVAL_MS, reassert)

    tick()
    reassert()

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Lab lockout overlay")
    parser.add_argument("--until", required=True, help="ISO-8601 end time (UTC)")
    parser.add_argument(
        "--message",
        default="This computer is unavailable during the scheduled restriction "
                "period. Please speak to a lab supervisor if you believe this "
                "is an error.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level="INFO", format="%(asctime)s - %(levelname)s - %(message)s")

    try:
        until = parse_until(args.until)
    except ValueError:
        logger.error("Unparseable --until value: %r", args.until)
        return 2

    if until <= datetime.now(timezone.utc):
        logger.info("End time has already passed; nothing to show")
        return 0

    set_task_manager_disabled(True)
    try:
        return run_overlay(until, args.message)
    finally:
        # Always restore, including on a crash — leaving Task Manager disabled
        # after the block has expired would be a lasting side effect.
        set_task_manager_disabled(False)


if __name__ == "__main__":
    sys.exit(main())
