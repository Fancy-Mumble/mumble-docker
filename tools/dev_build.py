"""Fast incremental dev build of the Mumble server from a local source tree.

Uses ``Dockerfile.dev`` with BuildKit cache mounts so only changed C++
files recompile, then replaces the running container.
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

DEFAULTS = {
    "MUMBLE_IMAGE":           "mumble-server",
    "MUMBLE_TAG":             "dev",
    "MUMBLE_CONTAINER":       "mumble-server-dev",
    "MUMBLE_DATA_VOLUME":     "mumble-data",
    "MUMBLE_PORT":            "64738",
    "MUMBLE_FILESERVER_PORT": "64739",
    "MUMBLE_SFU_PORT":        "10000",
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dev-build",
        description="Incremental dev build of mumble-server from a local source tree.",
    )
    parser.add_argument("--clean", action="store_true",
                        help="Prune the BuildKit cache mount before building.")
    args = parser.parse_args(argv)

    c.require_docker()
    env = c.env_with_defaults(DEFAULTS)
    src = c.require_path(env, "MUMBLE_SRC")

    if args.clean:
        c.maybe_clean_buildx_cache(["--clean"])

    image = f"{env['MUMBLE_IMAGE']}:{env['MUMBLE_TAG']}"
    container = env["MUMBLE_CONTAINER"]

    c.banner(f"Building {image} (incremental)")
    c.docker([
        "buildx", "build", "--load",
        "-f", str(c.REPO_ROOT / "Dockerfile.dev"),
        "-t", image,
        "--build-context", f"mumble-src={src}",
        str(c.REPO_ROOT),
    ])

    c.banner(f"Replacing container {container}")
    c.stop_and_remove(container)

    run_args = [
        "run", "-d", "--name", container,
        "-p", f"{env['MUMBLE_PORT']}:64738/tcp",
        "-p", f"{env['MUMBLE_PORT']}:64738/udp",
        "-p", f"{env['MUMBLE_FILESERVER_PORT']}:64739/tcp",
        "-p", f"{env['MUMBLE_SFU_PORT']}:10000/udp",
    ]
    run_args += c.standard_mounts(env)
    run_args += c.passthrough_env(env)
    if env.get("MUMBLE_INI"):
        run_args += ["-e", "MUMBLE_CUSTOM_CONFIG_FILE=/data/mumble-server.ini"]
    run_args += [image]

    c.docker(run_args)

    pw = env.get("MUMBLE_SUPERUSER_PASSWORD")
    if pw:
        c.banner("Setting SuperUser password")
        time.sleep(2)
        c.docker([
            "exec", container,
            "/usr/bin/mumble-server",
            *c.ini_arg(env),
            "--set-su-pw", pw,
        ])

    c.banner(f"Done — server running on localhost:{env['MUMBLE_PORT']}")
    c.info(f"Logs:  docker logs -f {container}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
