"""Makes `python -m engine` the Engine's command-line entry point.

`python -m engine.main` still works and stays environment-only; this adds the
flags. See engine.cli for why the two are separate.
"""

from __future__ import annotations

import sys

from engine.cli import run

if __name__ == "__main__":
    sys.exit(run())
