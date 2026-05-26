"""Convenience wrapper: ``python -m tools setup`` -> setup wizard."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Sequence

# When this file is executed directly (python tools/setup.py) the repo root is
# not on sys.path.  Add it so that setup_wizard is importable in both cases.
_REPO_ROOT = str(Path(__file__).resolve().parent.parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def main(argv: Sequence[str] | None = None) -> int:
    from setup_wizard.__main__ import main as wizard_main

    return wizard_main(list(argv) if argv is not None else None)


if __name__ == "__main__":
    sys.exit(main())
