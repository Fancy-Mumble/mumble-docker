"""Dispatcher for the ``tools`` package.

Usage::

    python -m tools <command> [options]

Available commands:

    setup          Launch the setup wizard (forwards to setup_wizard).
    dev-build      Incremental dev build of mumble-server.
    dev-debug      Debug build executed under gdb.
    dev-fuzz       Build & run the fuzz harnesses in a container.
    vanilla-build  Build & run an unmodified upstream Mumble server.
    export-db      Snapshot the SQLite DB from a running container.
    import-db      Import a local SQLite DB into the data volume.
    buildx         Multi-arch build & push.

Each subcommand is also runnable standalone::

    python -m tools.dev_build [options]
"""

from __future__ import annotations

import sys
from typing import Callable

from . import (
    buildx,
    dev_build,
    dev_debug,
    dev_fuzz,
    export_db,
    import_db,
    setup,
    vanilla_build,
)

# Subcommand -> entry point.  Aliases (with underscores) are accepted too.
_COMMANDS: dict[str, Callable[..., int]] = {
    "setup":         setup.main,
    "dev-build":     dev_build.main,
    "dev-debug":     dev_debug.main,
    "dev-fuzz":      dev_fuzz.main,
    "vanilla-build": vanilla_build.main,
    "export-db":     export_db.main,
    "import-db":     import_db.main,
    "buildx":        buildx.main,
}


def _print_help() -> None:
    sys.stdout.write(__doc__ or "")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    name = args[0]
    rest = args[1:]
    cmd = _COMMANDS.get(name) or _COMMANDS.get(name.replace("_", "-"))
    if cmd is None:
        sys.stderr.write(f"[ERROR] unknown subcommand: {name}\n\n")
        _print_help()
        return 2
    return int(cmd(rest) or 0)


if __name__ == "__main__":
    sys.exit(main())
