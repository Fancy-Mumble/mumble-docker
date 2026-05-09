"""Builds and runs the vanilla upstream Mumble server (Dockerfile.vanilla)."""

from __future__ import annotations

import argparse
import sys
import time
from typing import Sequence

try:
    from . import _common as c
except ImportError:
    import sys as _sys; from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from tools import _common as c

DEFAULTS = {
    "MUMBLE_IMAGE":           "mumble-server",
    "MUMBLE_TAG":             "vanilla",
    "MUMBLE_CONTAINER":       "mumble-server-vanilla",
    "MUMBLE_DATA_VOLUME":     "mumble-data-vanilla",
    "MUMBLE_PORT":            "64738",
    "MUMBLE_FILESERVER_PORT": "64739",
}


def main(argv: Sequence[str] | None = None) -> int:
    argparse.ArgumentParser(
        prog="vanilla-build",
        description="Build & run an unmodified upstream Mumble server.",
    ).parse_args(argv)

    c.require_docker()
    env = c.env_with_defaults(DEFAULTS)

    image = f"{env['MUMBLE_IMAGE']}:{env['MUMBLE_TAG']}"
    container = env["MUMBLE_CONTAINER"]

    c.banner(f"Building vanilla Mumble ({image})")
    c.docker([
        "buildx", "build", "--load",
        "-f", str(c.REPO_ROOT / "Dockerfile.vanilla"),
        "-t", image,
        str(c.REPO_ROOT),
    ])

    c.banner(f"Replacing container {container}")
    c.stop_and_remove(container)

    c.docker([
        "run", "-d", "--name", container,
        "-p", f"{env['MUMBLE_PORT']}:64738/tcp",
        "-p", f"{env['MUMBLE_PORT']}:64738/udp",
        "-p", f"{env['MUMBLE_FILESERVER_PORT']}:64739/tcp",
        "-v", f"{env['MUMBLE_DATA_VOLUME']}:/data",
        image,
    ])

    pw = env.get("MUMBLE_SUPERUSER_PASSWORD")
    if pw:
        c.banner("Setting SuperUser password")
        time.sleep(3)
        c.docker([
            "exec", container,
            "/usr/bin/mumble-server",
            "--ini", "/data/mumble_server_config.ini",
            "--set-su-pw", pw,
        ])

    c.banner(f"Done — server running on localhost:{env['MUMBLE_PORT']}")
    c.info(f"Logs:  docker logs -f {container}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
