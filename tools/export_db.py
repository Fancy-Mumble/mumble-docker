"""Export the live mumble-server SQLite DB out of a running container."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

try:
    from . import _common as c
except ImportError:
    import sys as _sys; from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from tools import _common as c

DEFAULTS = {
    "MUMBLE_CONTAINER": "mumble-server-dev",
    "MUMBLE_DB_PATH":   "/data/mumble-server.sqlite",
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="export-db",
        description="Snapshot the live SQLite DB of a running container.",
    )
    parser.add_argument(
        "output", nargs="?", type=Path,
        help="Destination path on the host (default: <repo>/db/murmur.sqlite).",
    )
    args = parser.parse_args(argv)

    c.require_docker()
    env = c.env_with_defaults(DEFAULTS)
    container = env["MUMBLE_CONTAINER"]
    db_path = env["MUMBLE_DB_PATH"]

    out: Path = args.output or (c.REPO_ROOT / "db" / "murmur.sqlite")
    out = out.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    if not c.container_running(container):
        c.error(f'Container "{container}" is not running.')
        return 1

    c.info(f"Exporting {container}:{db_path} -> {out}")

    # Prefer Python's sqlite3 backup API for a consistent online snapshot.
    cp = c.docker([
        "exec", container, "python3", "-c",
        ("import sqlite3;"
         f"src=sqlite3.connect('{db_path}');"
         "bk=sqlite3.connect('/tmp/mumble-export.sqlite');"
         "src.backup(bk); bk.close(); src.close()"),
    ], check=False, quiet=True)

    if cp.returncode == 0:
        c.docker(["cp", f"{container}:/tmp/mumble-export.sqlite", str(out)])
        c.docker_quiet(["exec", container, "rm", "/tmp/mumble-export.sqlite"])
    else:
        c.warn("python3 not available in container, falling back to direct file copy.")
        c.docker(["cp", f"{container}:{db_path}", str(out)])
        # Best-effort copy of WAL / SHM (often absent).
        c.docker_quiet(["cp", f"{container}:{db_path}-wal", f"{out}-wal"])
        c.docker_quiet(["cp", f"{container}:{db_path}-shm", f"{out}-shm"])

    c.info(f"Done — exported to: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
