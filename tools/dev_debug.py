"""Debug build of mumble-server, executed under gdb in batch mode.

Mirrors the previous ``dev-debug.bat`` workflow:

1. Build the debug image.
2. Reset the data volume.
3. Briefly run the server to create a fresh DB schema.
4. Optionally seed the DB from a local SQLite file.
5. Optionally bake in a SuperUser password.
6. Launch the real server under ``gdb --batch`` so any crash produces a
   full backtrace before the container exits.
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
    "MUMBLE_TAG":             "debug",
    "MUMBLE_CONTAINER":       "mumble-server-debug",
    "MUMBLE_DATA_VOLUME":     "mumble-data-debug",
    "MUMBLE_PORT":            "64738",
    "MUMBLE_FILESERVER_PORT": "64739",
    "MUMBLE_LIVEDOC_PORT":    "64740",
    "MUMBLE_SFU_PORT":        "10000",
    "MUMBLE_UID":             "1000",
    "MUMBLE_GID":             "1000",
}


def _vol(env: dict[str, str]) -> str:
    return f"{env['MUMBLE_DATA_VOLUME']}:/data"


def _sh(env: dict[str, str], image: str, script: str) -> None:
    """Run ``/bin/sh -c <script>`` against the data volume."""

    c.docker([
        "run", "--rm",
        "--entrypoint", "/bin/sh",
        "-v", _vol(env),
        image, "-c", script,
    ])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dev-debug",
        description="Build & run mumble-server with debug symbols under gdb.",
    )
    parser.add_argument("--clean", action="store_true",
                        help="Prune the BuildKit cache mount before building.")
    args = parser.parse_args(argv)

    c.require_docker()
    env = c.env_with_defaults(DEFAULTS)
    src = c.require_path(env, "MUMBLE_SRC")

    seed_default = c.REPO_ROOT / "db" / "murmur.sqlite"
    seed = c.host_path(env.get("MUMBLE_SEED_DB")) or seed_default

    if args.clean:
        c.maybe_clean_buildx_cache(["--clean"])

    image = f"{env['MUMBLE_IMAGE']}:{env['MUMBLE_TAG']}"
    container = env["MUMBLE_CONTAINER"]
    uid_gid = f"{env['MUMBLE_UID']}:{env['MUMBLE_GID']}"

    c.banner(f"Building {image} (with debug symbols)")
    c.docker([
        "buildx", "build", "--load",
        "-f", str(c.REPO_ROOT / "Dockerfile.debug"),
        "-t", image,
        "--build-context", f"mumble-src={src}",
        str(c.REPO_ROOT),
    ])

    c.banner("Cleaning up previous debug containers")
    c.stop_and_remove(container,
                      f"{container}-init",
                      f"{container}-dbcopy")

    mounts = c.standard_mounts(env)
    ini_args = c.ini_arg(env)

    c.banner("Resetting data volume (clearing stale DB / credentials)")
    _sh(env, image,
        "rm -rf /data/mumble-server.sqlite /data/mumble-server.sqlite-wal "
        "/data/mumble-server.sqlite-shm /data/fcm-credentials.json && "
        f"chown -R {uid_gid} /data && chmod 775 /data")

    c.banner("Initialising database (brief server start to create schema)")
    init_name = f"{container}-init"
    c.docker([
        "run", "-d", "--rm",
        "--name", init_name,
        "--user", uid_gid,
        "--network", "none",
        "--entrypoint", "/usr/bin/mumble-server",
        *mounts,
        image,
        "--foreground", *ini_args,
    ])
    time.sleep(3)
    c.docker_quiet(["stop", init_name])

    if seed.exists():
        c.banner(f"Seeding database from {seed}")
        dbcopy = f"{container}-dbcopy"
        c.docker([
            "create", "--name", dbcopy,
            "-v", _vol(env),
            image, "/bin/true",
        ], quiet=True)
        c.docker([
            "cp", str(seed), f"{dbcopy}:/data/mumble-server.sqlite",
        ])
        c.docker_quiet(["rm", dbcopy])
        _sh(env, image,
            f"chown {uid_gid} /data/mumble-server.sqlite && "
            "chmod 664 /data/mumble-server.sqlite && chmod 775 /data && "
            "rm -f /data/mumble-server.sqlite-wal /data/mumble-server.sqlite-shm")
    else:
        c.info(f"(no seed DB at {seed} - skipping)")

    pw = env.get("MUMBLE_SUPERUSER_PASSWORD")
    if pw:
        c.banner("Setting SuperUser password")
        c.docker([
            "run", "--rm",
            "--user", uid_gid,
            "--network", "none",
            "--entrypoint", "/usr/bin/mumble-server",
            *mounts,
            image,
            "--foreground", *ini_args,
            "--set-su-pw", pw,
        ])

    # Ensure file-server storage dir exists with correct ownership.
    _sh(env, image,
        "mkdir -p /data/file-server-storage && "
        f"chown -R {uid_gid} /data/file-server-storage && "
        "chmod 775 /data/file-server-storage")

    # Ensure live-doc state dir exists with correct ownership.
    _sh(env, image,
        "mkdir -p /data/live-doc-state && "
        f"chown -R {uid_gid} /data/live-doc-state && "
        "chmod 775 /data/live-doc-state")

    # Final pre-flight permission fix-up.
    _sh(env, image,
        f"test -f /data/mumble-server.sqlite && chown {uid_gid} /data/mumble-server.sqlite || true; "
        "test -f /data/mumble-server.sqlite && chmod 664 /data/mumble-server.sqlite || true; "
        f"chown {uid_gid} /data; chmod 775 /data; "
        "rm -f /data/mumble-server.sqlite-wal /data/mumble-server.sqlite-shm")

    # Stop anything still bound to the host port.
    cp = c.docker(["ps", "-q", "--filter",
                   f"publish={env['MUMBLE_PORT']}"],
                  capture=True, quiet=True)
    for cid in (cp.stdout or "").split():
        c.info(f"Stopping container {cid} which is using port {env['MUMBLE_PORT']}...")
        c.stop_and_remove(cid)

    c.banner("Launching gdb (batch mode - backtrace on crash)")
    c.docker([
        "run", "--rm",
        "--name", container,
        "--cap-add=SYS_PTRACE", "--security-opt", "seccomp=unconfined",
        "--user", uid_gid,
        "--entrypoint", "gdb",
        "-p", f"{env['MUMBLE_PORT']}:64738/tcp",
        "-p", f"{env['MUMBLE_PORT']}:64738/udp",
        "-p", f"{env['MUMBLE_FILESERVER_PORT']}:64739/tcp",
        "-p", f"{env['MUMBLE_LIVEDOC_PORT']}:64740/tcp",
        "-p", f"{env['MUMBLE_SFU_PORT']}:10000/udp",
        "-e", "RUST_LOG=mumble_file_server=debug,mumble_plugin_host=debug,info",
        "-e", "MUMBLE_PLUGIN_LOG=mumble_file_server=debug,mumble_plugin_host=debug,info",
        *mounts,
        image,
        "--batch",
        "-ex", "set pagination off",
        "-ex", "run",
        "-ex", "thread apply all bt full",
        "-ex", "quit",
        "--args", "/usr/bin/mumble-server", "--foreground", "--verbose",
        *ini_args,
    ], check=False)

    c.banner("gdb session ended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
