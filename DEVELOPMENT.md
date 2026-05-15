# Developer & local build workflow

This document describes the helper scripts used for local development,
debugging and publishing of custom Mumble server images.  They are
**optional** - the production [Dockerfile](Dockerfile) and the
[README](README.md) are sufficient for end users.

Layout:

```
<repo-root>/
├── setup_wizard/   - Python configuration wizard (CLI + optional GUI)
├── tools/          - cross-platform Python helpers (build / run / db / publish)
├── scripts/        - build-time scripts copied into the image
└── Dockerfile*     - production / dev / debug / vanilla images
```

The helpers under [`tools/`](tools/README.md) are pure Python 3.8+
stdlib and run identically on Windows, macOS and Linux - the only
runtime requirement is the `docker` CLI.  All tunables are read from
the environment, with defaults documented in
[`.env.example`](.env.example).

## Quick start

The fastest way to bootstrap a working `.env` is the interactive setup
wizard.  It walks you through every value, validates ports / paths and
can pre-fill from an existing `.env`:

```sh
python -m setup_wizard           # terminal UI (any OS)
python -m setup_wizard --gui     # DearPyGui front-end
python -m tools setup            # same, via the tools dispatcher
```

Re-run it any time to adjust individual settings.  Pass
`--non-interactive` to accept all defaults non-interactively (useful for
CI).  See [`setup_wizard/README.md`](setup_wizard/README.md) for the
full documentation, including the MVC layout and how to embed the
wizard from another tool.

If you'd rather edit the file by hand:

```sh
cp .env.example .env
$EDITOR .env       # set MUMBLE_SRC and any optional values
```

Then invoke any of the helpers from the repo root:

| Command                                | Purpose                                                      |
|----------------------------------------|--------------------------------------------------------------|
| `python -m tools dev-build [--clean]`  | Incremental dev build of the server from a local source tree |
| `python -m tools dev-debug [--clean]`  | Debug build + run under `gdb` with auto-backtrace on crash   |
| `python -m tools vanilla-build`        | Build & run an unmodified upstream Mumble server             |
| `python -m tools export-db [path]`     | Snapshot the live SQLite DB out of a running container       |
| `python -m tools import-db [path]`     | Import a local SQLite DB into the data volume                |
| `python -m tools buildx [image]`       | Multi-arch (`linux/amd64`, `linux/arm64`) build & push       |

Every subcommand is also runnable standalone, e.g.
`python -m tools.dev_build --clean`.  See
[`tools/README.md`](tools/README.md) for details.

## Configuration variables

All variables can be set in `.env` (recommended) or in the current shell
before invoking a script.  Shell values win.  See
[`.env.example`](.env.example) for the full annotated list; the most
important ones are:

| Variable                    | Required by               | Purpose                                                |
|-----------------------------|---------------------------|--------------------------------------------------------|
| `MUMBLE_SRC`                | `dev-build`, `dev-debug`  | Path to a local clone of the mumble-server source tree |
| `MUMBLE_IMAGE` / `MUMBLE_TAG` | all build helpers       | Image name & tag (defaults `mumble-server` + script-specific tag) |
| `MUMBLE_CONTAINER`          | all run helpers           | Container name                                          |
| `MUMBLE_DATA_VOLUME`        | all run helpers           | Named volume mounted at `/data`                         |
| `MUMBLE_PORT`, `MUMBLE_FILESERVER_PORT`, `MUMBLE_SFU_PORT` | run helpers | Host-side ports             |
| `MUMBLE_INI`                | run helpers               | Local `mumble-server.ini` to mount (optional)           |
| `MUMBLE_FCM_CREDENTIALS`    | run helpers               | Firebase service-account JSON to mount (optional)       |
| `MUMBLE_SUPERUSER_PASSWORD` | run helpers               | When set, configured after first start                  |
| `MUMBLE_UID` / `MUMBLE_GID` | `dev-debug`               | UID/GID used inside the debug container                 |
| `BUILDX_IMAGE`              | `buildx.sh`               | Full target tag, e.g. `myorg/mumble-server:1.6.0`       |
| `BUILDX_PLATFORMS`          | `buildx.sh`               | Comma-separated platform list                           |
| `MUMBLE_GIT_REPO` / `MUMBLE_GIT_BRANCH` | `Dockerfile`  | Source repo to clone (defaults to upstream)             |

## Building from a fork

The production [Dockerfile](Dockerfile) clones from
`https://github.com/SetZero/mumble-server` (branch `1.6.x`) by default -
this is the Fancy Mumble server fork that this image is built around.
The matching client lives at
[Fancy-Mumble/FancyMumbleNext](https://github.com/Fancy-Mumble/FancyMumbleNext).

To build from a different fork, pass build args:

```sh
docker build \
  --build-arg MUMBLE_GIT_REPO=https://github.com/youruser/mumble \
  --build-arg MUMBLE_GIT_BRANCH=my-feature \
  --build-arg MUMBLE_VERSION=v1.6.0 \
  .
```

`MUMBLE_VERSION` may be any tag or commit hash on the cloned branch; it
is checked out after the initial clone.

## Local source builds (`Dockerfile.dev`, `Dockerfile.debug`)

These two Dockerfiles use a [BuildKit named build context](https://docs.docker.com/build/building/context/#named-contexts)
called `mumble-src` instead of cloning over the network.  The wrapper
scripts pass it for you:

```bat
docker buildx build --load -f Dockerfile.dev ^
  --build-context mumble-src=%MUMBLE_SRC% ^
  -t mumble-server:dev .
```

If you want to build them manually, set `--build-context mumble-src=...`
to a local path.

## Push notifications (FCM)

Push support is **disabled by default** in the bundled
[`mumble-server.ini.example`](mumble-server.ini.example).  To enable it:

1. Create a Firebase project and download a service-account JSON key.
2. Save the JSON locally and point `MUMBLE_FCM_CREDENTIALS` at it (or
   mount it manually at `/data/fcm-credentials.json`).  The pattern
   `*-firebase-adminsdk*.json` is gitignored to reduce the risk of
   accidentally committing it.
3. Bootstrap your local `mumble-server.ini` from the example
   (`cp mumble-server.ini.example mumble-server.ini`, or let the setup
   wizard do it) and set, in either the .ini or the `MUMBLE_CONFIG_*`
   env vars:
   ```
   pushenabled=true
   pushprojectid=your-firebase-project-id
   ```

**Never commit FCM credentials.**  If a key has been exposed, rotate it
in the Firebase console immediately.

## Cleaning up

Both build helpers accept `--clean` to prune the BuildKit cache mount
used for incremental compilation:

```sh
python -m tools dev-build --clean
```

Containers and volumes can be removed with the usual Docker commands:

```bat
docker rm -f %MUMBLE_CONTAINER%
docker volume rm %MUMBLE_DATA_VOLUME%
```
