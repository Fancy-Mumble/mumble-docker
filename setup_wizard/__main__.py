"""``python -m setup_wizard`` entry point.

Routes between the CLI and GUI views.  Defaults to the CLI; pass
``--gui`` to launch the DearPyGui front-end (which must be installed
separately, see ``requirements.txt``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .model import DEFAULT_ENV_PATH


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="setup_wizard",
        description="Interactive configuration wizard for mumble-docker.",
    )
    p.add_argument(
        "--output", "-o",
        type=Path,
        default=DEFAULT_ENV_PATH,
        help=f"Path to write the .env file (default: {DEFAULT_ENV_PATH}).",
    )
    p.add_argument(
        "--non-interactive",
        action="store_true",
        help="Accept all defaults; useful for smoke tests / CI.",
    )
    p.add_argument(
        "--gui",
        action="store_true",
        help="Launch the DearPyGui front-end instead of the terminal wizard.",
    )
    p.add_argument(
        "--easy",
        action="store_true",
        help="Quick-start: only ask for the essentials (features + admin "
             "password) and accept defaults for everything else.",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.gui:
        if args.non_interactive:
            sys.stderr.write(
                "[ERROR] --gui and --non-interactive cannot be combined.\n"
            )
            return 2
        from .view_gui import run_gui
        return run_gui(args.output, easy=args.easy)

    from .view_cli import run_cli
    return run_cli(args.output, non_interactive=args.non_interactive,
                   easy=args.easy)


if __name__ == "__main__":
    sys.exit(main())
