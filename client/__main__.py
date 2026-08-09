"""Makes `python -m client` the Client Agent's command-line entry point.

`python -m client.main` still works and stays environment-only; this adds the
flags and the `--once` / `--check` diagnostics. See client.cli for why the two
are separate.
"""

from __future__ import annotations

import sys

from client.cli import run

if __name__ == "__main__":
    sys.exit(run())
