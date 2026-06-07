"""Build & run the Mumble server fuzz harnesses in a container.

Mirrors the ``tools.dev_debug`` workflow: the host builds the toolchain image
(``Dockerfile.fuzz``) and runs it with the mumble-server checkout
(``MUMBLE_SRC``) bind-mounted at ``/src``.  The in-container driver
(``scripts/fuzz_runner.py``) drives cargo-fuzz / CMake against that tree.

Usage::

    python -m tools.dev_fuzz [--rebuild] [--no-cache] <command> [args...]

Commands (forwarded to the in-container runner):

    list                 list every available target
    rust  <target>       run a Rust cargo-fuzz target
    cpp   <target>       build + run a C++ libFuzzer target
    smoke                bounded run of every target (CI gate)
    all [--time SECS]    run every target for SECS each (default 300)

Anything after ``--`` is passed straight through to libFuzzer, e.g.::

    python -m tools.dev_fuzz rust host_zip --smoke
    python -m tools.dev_fuzz cpp fuzz_opengraph -- -timeout=2 -rss_limit_mb=2048
    python -m tools.dev_fuzz all --time 120

Host-only flags:

    --rebuild    rebuild the fuzz image even if it already exists
    --no-cache   pass --no-cache to the image build (implies --rebuild)
"""

from __future__ import annotations

import sys
from typing import Sequence

try:
    from . import _common as c
except ImportError:
    import sys as _sys; from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from tools import _common as c

DEFAULTS = {
    "MUMBLE_FUZZ_IMAGE": "mumble-fuzz",
    "MUMBLE_FUZZ_TAG":   "latest",
}

_HOST_FLAGS = {"--rebuild", "--no-cache"}


def _image_exists(image: str) -> bool:
    cp = c.docker(["image", "inspect", image],
                  check=False, capture=True, quiet=True)
    return cp.returncode == 0


def _build_image(image: str, *, no_cache: bool) -> None:
    c.banner(f"Building fuzz image {image}")
    args = ["build", "-t", image, "-f", str(c.REPO_ROOT / "Dockerfile.fuzz")]
    if no_cache:
        args.append("--no-cache")
    args.append(str(c.REPO_ROOT))
    c.docker(args)


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    # Pull leading host-only flags; everything else is forwarded verbatim to
    # the in-container runner (so its own --smoke / -- passthrough survive).
    rebuild = False
    no_cache = False
    while args and args[0] in _HOST_FLAGS:
        if args[0] == "--rebuild":
            rebuild = True
        elif args[0] == "--no-cache":
            no_cache = True
            rebuild = True
        args.pop(0)

    if args and args[0] in ("-h", "--help", "help"):
        sys.stdout.write(__doc__ or "")
        return 0

    forward = args or ["list"]

    c.require_docker()
    env = c.env_with_defaults(DEFAULTS)
    src = c.require_path(env, "MUMBLE_SRC")
    image = f"{env['MUMBLE_FUZZ_IMAGE']}:{env['MUMBLE_FUZZ_TAG']}"

    if rebuild or not _image_exists(image):
        _build_image(image, no_cache=no_cache)
    else:
        c.info(f"Using existing fuzz image {image} (pass --rebuild to force a rebuild).")

    run_args = ["run", "--rm"]
    if sys.stdin.isatty() and sys.stdout.isatty():
        run_args.append("-it")
    run_args += [
        # AddressSanitizer needs a relaxed seccomp/ptrace profile.
        "--cap-add=SYS_PTRACE", "--security-opt", "seccomp=unconfined",
        "-v", c.docker_mount(src, "/src"),
        image,
        *forward,
    ]

    c.banner(f"fuzz: {' '.join(forward)}")
    cp = c.docker(run_args, check=False)
    return cp.returncode


if __name__ == "__main__":
    sys.exit(main())
