#!/usr/bin/env python3
"""Warning dialog — bundled as its own executable, spawned on demand.

    python -m client.dialog_app --message "Shutting down in 60 seconds" --timeout 60

Used for graceful shutdown warnings and lockout grace periods. Deliberately a
real executable rather than MessageBoxW through ctypes: the agent spawns it the
same way it spawns scripts, so it never blocks the event loop, and the user's
answer comes back through the same exit-code channel everything else uses.

Exit codes are the interface:
    0  OK / acknowledged
    1  Cancelled
    2  Timed out with no answer
    3  Bad arguments
"""

from __future__ import annotations

import argparse
import logging
import sys

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CANCELLED = 1
EXIT_TIMEOUT = 2
EXIT_BAD_ARGS = 3


def run_dialog(title: str, message: str, timeout: int, allow_cancel: bool) -> int:
    """Show the dialog and return the exit code for whatever happened."""
    import tkinter as tk

    outcome = {"code": EXIT_TIMEOUT}

    root = tk.Tk()
    root.title(title)
    root.configure(bg="#161b22")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    # A warning nobody sees is useless, so it opens centred and focused.
    root.eval("tk::PlaceWindow . center")

    frame = tk.Frame(root, bg="#161b22", padx=28, pady=22)
    frame.pack()

    tk.Label(frame, text=title, font=("Segoe UI", 13, "bold"),
             fg="#e6edf3", bg="#161b22").pack(anchor="w")

    tk.Label(frame, text=message, font=("Segoe UI", 10), fg="#8b949e",
             bg="#161b22", wraplength=380, justify="left").pack(anchor="w", pady=(8, 16))

    remaining = tk.Label(frame, text="", font=("Segoe UI", 9), fg="#6e7681", bg="#161b22")
    remaining.pack(anchor="w")

    buttons = tk.Frame(frame, bg="#161b22")
    buttons.pack(anchor="e", pady=(14, 0))

    def finish(code: int) -> None:
        outcome["code"] = code
        root.destroy()

    if allow_cancel:
        tk.Button(buttons, text="Cancel", width=10,
                  command=lambda: finish(EXIT_CANCELLED)).pack(side="right", padx=(8, 0))

    tk.Button(buttons, text="OK", width=10, default="active",
              command=lambda: finish(EXIT_OK)).pack(side="right")

    root.bind("<Return>", lambda _event: finish(EXIT_OK))
    if allow_cancel:
        root.bind("<Escape>", lambda _event: finish(EXIT_CANCELLED))

    # Closing the window is a cancel when cancelling is allowed, and is ignored
    # otherwise — an unacknowledgeable warning should not be dismissible.
    root.protocol(
        "WM_DELETE_WINDOW",
        (lambda: finish(EXIT_CANCELLED)) if allow_cancel else (lambda: None),
    )

    countdown = {"left": timeout}

    def tick() -> None:
        if countdown["left"] <= 0:
            finish(EXIT_TIMEOUT)
            return
        remaining.config(text=f"Closing automatically in {countdown['left']}s")
        countdown["left"] -= 1
        root.after(1000, tick)

    if timeout > 0:
        tick()

    try:
        root.mainloop()
    except KeyboardInterrupt:
        return EXIT_CANCELLED

    return outcome["code"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Client warning dialog")
    parser.add_argument("--message", required=True)
    parser.add_argument("--title", default="Lab Monitor")
    parser.add_argument(
        "--timeout", type=int, default=60,
        help="Seconds before auto-closing with EXIT_TIMEOUT; 0 waits forever",
    )
    parser.add_argument("--allow-cancel", action="store_true")

    try:
        args = parser.parse_args(argv)
    except SystemExit:
        return EXIT_BAD_ARGS

    logging.basicConfig(level="INFO", format="%(asctime)s - %(levelname)s - %(message)s")

    return run_dialog(args.title, args.message, args.timeout, args.allow_cancel)


if __name__ == "__main__":
    sys.exit(main())
