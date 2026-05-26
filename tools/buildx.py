"""Multi-architecture build & push helper (replaces the old buildx.sh)."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

try:
    from . import _common as c
except ImportError:
    import sys as _sys; from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent))
    from tools import _common as c

DEFAULTS = {
    "BUILDX_PLATFORMS": "linux/amd64,linux/arm64",
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="buildx",
        description="Multi-architecture docker buildx build & push helper.",
    )
    parser.add_argument(
        "image", nargs="?",
        help="Target image, e.g. myorg/mumble-server:1.6.0.  "
             "Defaults to BUILDX_IMAGE from .env / environment.",
    )
    parser.add_argument(
        "--platforms",
        help="Comma-separated platforms (default: BUILDX_PLATFORMS or "
             "linux/amd64,linux/arm64).",
    )
    args = parser.parse_args(argv)

    c.require_docker()
    env = c.env_with_defaults(DEFAULTS)
    image = args.image or env.get("BUILDX_IMAGE", "")
    platforms = args.platforms or env.get("BUILDX_PLATFORMS",
                                          DEFAULTS["BUILDX_PLATFORMS"])

    if not image:
        c.error(
            "No image tag specified.\n\n"
            "  Set BUILDX_IMAGE in .env, or pass it positionally:\n"
            "      python -m tools buildx myorg/mumble-server:1.6.0"
        )
        return 1

    c.banner(f"Building {image} for {platforms}")
    c.docker([
        "buildx", "build",
        "--platform", platforms,
        "-t", image,
        "--push",
        str(c.REPO_ROOT),
    ])
    return 0


if __name__ == "__main__":
    sys.exit(main())
