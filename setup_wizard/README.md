# `setup_wizard`

Interactive configuration wizard for **mumble-docker**.  Walks you
through every variable documented in [`.env.example`](../.env.example)
and writes a fresh `.env` file to the repository root.

The wizard is **pure Python 3.8+** and ships in two flavours:

| Flavour | Requirements           | When to use                                    |
| ------- | ---------------------- | ---------------------------------------------- |
| CLI     | stdlib only            | servers, SSH sessions, anywhere without a GUI |
| GUI     | `dearpygui` (optional) | local workstations, easier multi-tab editing  |

## Architecture

The package is split along an MVC boundary so adding a new front-end
(e.g. a web UI) only means adding a new view.

```
setup_wizard/
├── __init__.py        - public API re-exports
├── __main__.py        - argparse + view dispatch
├── model.py           - Setting/Section dataclasses, validators, .env I/O
├── controller.py      - Wizard class: state + side-effects (encode/save)
├── view_cli.py        - terminal interface
├── view_gui.py        - DearPyGui interface (optional)
├── requirements.txt   - GUI-only Python dependencies
└── README.md
```

* `model.py` knows nothing about user interaction.
* `controller.Wizard` holds the in-progress edit and exposes operations
  the views need (`set_value`, `maybe_encode_fcm`, `save`).
* The two view modules consume the same `Wizard` instance; switching
  flavours never changes the wizard's behaviour.

## Usage

### From the repository root

```bash
# CLI / TUI (default)
python -m setup_wizard

# Same, write to a different file
python -m setup_wizard --output .env.staging

# GUI
python -m pip install -r setup_wizard/requirements.txt
python -m setup_wizard --gui

# Smoke test (accept all defaults, useful for CI)
python -m setup_wizard --non-interactive --output .env.test
```

### Via the tools dispatcher

The same wizard is also exposed as a subcommand of the `tools` package
(see [`tools/README.md`](../tools/README.md)):

```bash
python -m tools setup            # TUI
python -m tools setup --gui      # GUI
python -m tools setup -o .env.staging
```

## What it configures

The wizard groups its settings into the same logical sections used in
`.env.example`:

| Section                     | Purpose                                        |
| --------------------------- | ---------------------------------------------- |
| Source tree                 | Path to your local `mumble-server` checkout    |
| Image & container names     | Defaults the helper scripts honour             |
| Network ports               | Mumble, file-server, WebRTC SFU                |
| Runtime user                | UID/GID inside the container                   |
| Server admin                | SuperUser password (with random-generator)     |
| Optional file mounts        | Custom `mumble-server.ini`                     |
| Firebase Cloud Messaging    | FCM credentials path **or** base64 payload    |
| Upstream source             | Git repo / branch the production image clones  |
| Multi-arch publish          | `BUILDX_IMAGE` / `BUILDX_PLATFORMS`            |

### Firebase credentials

If you supply `MUMBLE_FCM_CREDENTIALS` (a path to a service-account
JSON) and leave `MUMBLE_FCM_CREDENTIALS_BASE64` blank, the wizard will
**offer to base64-encode the file for you** and store the result in
`.env`.  That value can then be injected straight into the container
via `--env` or a Docker/Podman secret without ever bind-mounting the
host file (or risking it landing in an image layer).

> **Treat the base64 value like a password.**  It is gitignored by
> default; do not commit your `.env`.

## Re-running the wizard

Re-running on top of an existing `.env` is non-destructive — every
prompt is pre-filled with the value already on disk, so you can adjust
a single setting and accept the rest with Enter.

## Embedding from another tool

```python
from pathlib import Path
from setup_wizard import Wizard

w = Wizard(Path(".env"))
w.set_value("MUMBLE_PORT", "64738")
w.set_value("MUMBLE_FCM_CREDENTIALS", "/path/to/key.json")
w.maybe_encode_fcm()        # populates MUMBLE_FCM_CREDENTIALS_BASE64
w.save()
```

