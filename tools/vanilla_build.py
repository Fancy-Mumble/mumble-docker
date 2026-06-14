"""Builds and runs a vanilla upstream Mumble server.

Two upstream versions are supported, selected with ``--version``:

* ``1.6`` (default) - compiled from the ``1.6.x`` branch via
  ``Dockerfile.vanilla``.
* ``1.3`` - the official statically-linked ``murmur`` 1.3.0 release,
  packaged by ``Dockerfile.vanilla-1.3.0``.

Each version gets its own image tag, container name and data volume so
the two can coexist on one host.  All of those (plus ports) remain
overridable via the environment / ``.env``.
"""

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

# Per-version specifics.  ``fileserver`` is False for 1.3.0, which predates
# the file-server feature, so its port is not published.  ``ini_flag`` /
# ``supw_flag`` differ because murmur 1.3.0 only understands the legacy
# single-dash CLI arguments.
VERSIONS = {
    "1.6": {
        "dockerfile": "Dockerfile.vanilla",
        "tag":        "vanilla",
        "container":  "mumble-server-vanilla",
        "volume":     "mumble-data-vanilla",
        "fileserver": True,
        "ini_flag":   "--ini",
        "supw_flag":  "--set-su-pw",
    },
    "1.3": {
        "dockerfile": "Dockerfile.vanilla-1.3.0",
        "tag":        "vanilla-1.3.0",
        "container":  "mumble-server-vanilla-1.3.0",
        "volume":     "mumble-data-vanilla-1.3.0",
        "fileserver": False,
        "ini_flag":   "-ini",
        "supw_flag":  "-supw",
    },
}


def _defaults_for(version: str) -> dict[str, str]:
    spec = VERSIONS[version]
    return {
        "MUMBLE_IMAGE":           "mumble-server",
        "MUMBLE_TAG":             spec["tag"],
        "MUMBLE_CONTAINER":       spec["container"],
        "MUMBLE_DATA_VOLUME":     spec["volume"],
        "MUMBLE_PORT":            "64738",
        "MUMBLE_FILESERVER_PORT": "64739",
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vanilla-build",
        description="Build & run an unmodified upstream Mumble server.",
    )
    parser.add_argument(
        "--version", choices=sorted(VERSIONS), default="1.6", metavar="VERSION",
        help="Upstream Mumble version to build & run: "
             "1.6 (default, built from source) or 1.3 (static release).",
    )
    args = parser.parse_args(argv)
    spec = VERSIONS[args.version]

    c.require_docker()
    env = c.env_with_defaults(_defaults_for(args.version))

    image = f"{env['MUMBLE_IMAGE']}:{env['MUMBLE_TAG']}"
    container = env["MUMBLE_CONTAINER"]

    c.banner(f"Building vanilla Mumble {args.version} ({image})")
    c.docker([
        "buildx", "build", "--load",
        "-f", str(c.REPO_ROOT / spec["dockerfile"]),
        "-t", image,
        str(c.REPO_ROOT),
    ])

    c.banner(f"Replacing container {container}")
    c.stop_and_remove(container)

    run_args = [
        "run", "-d", "--name", container,
        "-p", f"{env['MUMBLE_PORT']}:64738/tcp",
        "-p", f"{env['MUMBLE_PORT']}:64738/udp",
    ]
    if spec["fileserver"]:
        run_args += ["-p", f"{env['MUMBLE_FILESERVER_PORT']}:64739/tcp"]
    run_args += [
        "-v", f"{env['MUMBLE_DATA_VOLUME']}:/data",
        image,
    ]
    c.docker(run_args)

    pw = env.get("MUMBLE_SUPERUSER_PASSWORD")
    if pw:
        c.banner("Setting SuperUser password")
        time.sleep(3)
        c.docker([
            "exec", container,
            "/usr/bin/mumble-server",
            spec["ini_flag"], "/data/mumble_server_config.ini",
            spec["supw_flag"], pw,
        ])

    c.banner(f"Done - server running on localhost:{env['MUMBLE_PORT']}")
    c.info(f"Logs:  docker logs -f {container}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
