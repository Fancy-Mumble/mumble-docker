#!/usr/bin/env bash
# ============================================================================
# buildx.sh
#
# Multi-architecture build & push helper.  Reads BUILDX_IMAGE and
# BUILDX_PLATFORMS from .env (or the environment); falls back to sane
# defaults.  An image tag must be supplied either via BUILDX_IMAGE or as the
# first positional argument.
#
# Usage:
#     ./buildx.sh                                   # uses BUILDX_IMAGE from .env
#     ./buildx.sh myorg/mumble-server:1.6.0         # explicit override
#     BUILDX_PLATFORMS=linux/amd64 ./buildx.sh ...  # restrict platforms
# ============================================================================

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null && pwd)"
repo_root="$(cd -- "${script_dir}/.." >/dev/null && pwd)"

# Load .env if present (do not override variables already in the environment).
if [[ -f "${repo_root}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    . <(grep -E '^[A-Za-z_][A-Za-z0-9_]*=' "${repo_root}/.env")
    set +a
fi

image="${1:-${BUILDX_IMAGE:-}}"
platforms="${BUILDX_PLATFORMS:-linux/amd64,linux/arm64}"

if [[ -z "${image}" ]]; then
    cat >&2 <<'EOF'
[ERROR] No image tag specified.

Set BUILDX_IMAGE in .env, or pass it as the first argument:

    ./buildx.sh myorg/mumble-server:1.6.0
EOF
    exit 1
fi

echo "Building ${image} for ${platforms} ..."
docker buildx build \
    --platform "${platforms}" \
    -t "${image}" \
    --push \
    "${repo_root}"
