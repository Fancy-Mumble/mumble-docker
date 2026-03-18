#!/usr/bin/env bash

set -e
set -x

git clone --branch 1.6.x --filter=tree:0 https://github.com/SetZero/mumble-server /mumble/repo

cd /mumble/repo

git config advice.detachedHead false

if [[ -n "$MUMBLE_VERSION" && ! "$MUMBLE_VERSION" == "latest" ]]; then
	git checkout "$MUMBLE_VERSION"
fi

git submodule update --init
git submodule update --depth 1
