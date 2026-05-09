# `tools/`

Cross-platform helper scripts for **mumble-docker**, written in pure
Python 3.8+ stdlib.  They run identically on Windows, macOS and Linux —
the only runtime dependency is the `docker` CLI.

## Layout

```
tools/
├── __init__.py
├── __main__.py        - dispatcher: `python -m tools <command>`
├── _common.py         - shared helpers (env loading, docker, paths)
├── dev_build.py       - incremental dev build of mumble-server
├── dev_debug.py       - debug build, executed under gdb
├── vanilla_build.py   - build & run unmodified upstream Mumble
├── export_db.py       - snapshot the SQLite DB out of a container
├── import_db.py       - import a SQLite DB into the data volume
├── buildx.py          - multi-arch build & push
├── setup.py           - thin shim for the setup wizard
└── README.md
```

## Running

From the repository root:

```bash
# Show the dispatcher help
python -m tools

# Subcommands
python -m tools setup                 # interactive configuration wizard
python -m tools setup --gui           # GUI variant (DearPyGui)
python -m tools dev-build             # incremental build + restart
python -m tools dev-build --clean     # also prune BuildKit cache
python -m tools dev-debug             # build with debug symbols, run under gdb
python -m tools vanilla-build         # plain upstream Mumble
python -m tools export-db [path]      # snapshot live DB
python -m tools import-db [path]      # restore a DB into the volume
python -m tools buildx [image]        # multi-arch build & push
```

Every subcommand is also runnable standalone:

```bash
python -m tools.dev_build --clean
python -m tools.export_db ~/backups/mumble.sqlite
```

## Configuration

Every command reads its configuration from three sources, in
descending order of precedence:

1. The current process environment (e.g. `MUMBLE_PORT=64740 python -m tools dev-build`).
2. The `.env` file in the repository root.
3. Built-in defaults (documented in [`.env.example`](../.env.example)).

The fastest way to populate `.env` is the setup wizard:

```bash
python -m tools setup
```

See [`setup_wizard/README.md`](../setup_wizard/README.md) for the full
list of variables.

## Requirements

* Python 3.8 or newer (no third-party packages).
* The `docker` CLI on `PATH`.  All commands abort early with a clear
  message if it isn't installed.
* On Windows: Docker Desktop with the Linux engine.
* `dev-debug` additionally relies on `gdb` being present **inside**
  the debug image (it is — that's what `Dockerfile.debug` installs).

## Why Python instead of `.bat` / `.sh`?

* One implementation per command instead of two.
* `subprocess` calls use argv lists, so paths with spaces and special
  characters Just Work without quoting gymnastics.
* Argument parsing, validation and `--help` come for free via
  `argparse`.
* Easier to extend — drop a new module in this folder and register it
  in `__main__.py`.

## Adding a new command

1. Create `tools/your_command.py` with a `def main(argv) -> int:` entry
   point and an `if __name__ == "__main__": sys.exit(main())` guard.
2. Use the helpers in `tools/_common.py` (`docker(...)`, `banner(...)`,
   `env_with_defaults(...)`) for consistent UX and behaviour.
3. Register it in `_COMMANDS` in `tools/__main__.py`.
