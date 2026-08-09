"""Makes `python -m admin` the Administrator client's command-line entry point.

`python -m admin.main` still works and stays environment-only; this adds the
flags and the `--check-qml` diagnostic. See admin.cli for why the two are
separate.
"""

from __future__ import annotations

import sys

from admin.cli import run

if __name__ == "__main__":
    sys.exit(run())
