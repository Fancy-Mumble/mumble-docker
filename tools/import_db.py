"""Import a local SQLite database into the Mumble data volume."""

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
    "MUMBLE_DATA_VOLUME": "mumble-data",
    "MUMBLE_DB_PATH":     "/data/mumble-server.sqlite",
    "MUMBLE_IMAGE":       "mumble-server",
    "MUMBLE_TAG":         "dev",
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="import-db",
        description="Import a local SQLite DB into the Mumble data volume.",
    )
    parser.add_argument(
        "source", nargs="?", type=Path,
        help="Local .sqlite file to import (default: <repo>/db/murmur.sqlite).",
    )
    args = parser.parse_args(argv)

    c.require_docker()
    env = c.env_with_defaults(DEFAULTS)
    volume = env["MUMBLE_DATA_VOLUME"]
    db_path = env["MUMBLE_DB_PATH"]

    src: Path = args.source or (c.REPO_ROOT / "db" / "murmur.sqlite")
    src = src.expanduser().resolve()
    if not src.exists():
        c.error(f"Source file not found: {src}")
        return 1

    # Stop any containers attached to the volume.
    cp = c.docker(["ps", "-q", "--filter", f"volume={volume}"],
                  capture=True, quiet=True)
    for cid in (cp.stdout or "").split():
        c.info(f"Stopping container {cid} ...")
        c.docker_quiet(["stop", cid])

    c.info(f'Importing "{src}" -> volume {volume}:{db_path}')

    helper = f"{env['MUMBLE_IMAGE']}:{env['MUMBLE_TAG']}"
    rc = c.docker_quiet([
        "create", "--name", "mumble-import-tmp",
        "-v", f"{volume}:/data",
        helper, "/bin/true",
    ])
    if rc != 0:
        helper = "alpine"
        c.docker([
            "create", "--name", "mumble-import-tmp",
            "-v", f"{volume}:/data",
            helper, "/bin/true",
        ], quiet=True)

    try:
        c.docker(["cp", str(src), f"mumble-import-tmp:{db_path}"])
    finally:
        c.docker_quiet(["rm", "mumble-import-tmp"])

    # Reset permissions and clear stale WAL/SHM so the next start is clean.
    c.docker([
        "run", "--rm",
        "--entrypoint", "/bin/sh",
        "-v", f"{volume}:/data",
        helper,
        "-c",
        f"chmod 666 '{db_path}' && rm -f '{db_path}-wal' '{db_path}-shm'",
    ])

    c.info(f"Done — imported from: {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
