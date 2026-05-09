#!/usr/bin/env bash
# Clone the Mumble server source tree.  Repository URL and branch are taken
# from the build args MUMBLE_GIT_REPO and MUMBLE_GIT_BRANCH (exported as env
# vars by the Dockerfile).  Defaults match the upstream project.

set -e
set -x

: "${MUMBLE_GIT_REPO:=https://github.com/SetZero/mumble-server}"
: "${MUMBLE_GIT_BRANCH:=1.6.x}"

git clone --branch "${MUMBLE_GIT_BRANCH}" --filter=tree:0 "${MUMBLE_GIT_REPO}" /mumble/repo

cd /mumble/repo

git config advice.detachedHead false

if [[ -n "${MUMBLE_VERSION:-}" && "${MUMBLE_VERSION}" != "latest" ]]; then
	git checkout "$MUMBLE_VERSION"
fi

git submodule update --init
git submodule update --depth 1
