# Mumble Docker - Fancy Mumble Edition

Mumble is a free, open source, low latency, high quality voice chat application.

This Docker image builds the **[Fancy Mumble](https://github.com/SetZero/mumble-server) server fork**, which extends the upstream Mumble server with:

- **Persistent chat** - encrypted, server-stored message history
- **Push notifications** - Firebase Cloud Messaging (FCM) support via a pluggable shared library
- **WebRTC SFU** - server-side relay for screen sharing streams (Rust, `libwebrtc_sfu.so`)
- **File server plugin** - custom emotes, avatar uploads and file attachments (`libmumble_plugin_host.so`)

<p align="center">
  <b>
    <a href="https://github.com/SetZero/mumble-server">Server source</a> •
    <a href="https://github.com/Fancy-Mumble/FancyMumbleNext">Desktop client</a> •
    <a href="https://mumble.info">Mumble website</a>
  </b>
</p>

### Companion repositories

| Component  | Repository |
|------------|------------|
| Server     | [SetZero/mumble-server](https://github.com/SetZero/mumble-server) (fork, branch `1.6.x`) |
| Client     | [Fancy-Mumble/FancyMumbleNext](https://github.com/Fancy-Mumble/FancyMumbleNext) |
| Docker     | this repository |

-----

## Quick Start Guide

1. [Setup wizard walkthrough](#setup-wizard-walkthrough)
2. [Running the container](#running-the-container)
3. [Exposed ports](#exposed-ports)
4. [Configuration](#configuration)
5. [Configuration wizard reference](#configuration-wizard)
6. [Building the container](#building-the-container)
7. [Fancy Mumble features](#fancy-mumble-features)
8. [Local development & helper scripts](DEVELOPMENT.md)


## Setup wizard walkthrough

The fastest way to get a working server is to let the interactive setup
wizard generate your `.env` file and then start the container.  The
wizard runs on any OS with Python 3.8+ and needs no third-party packages
for the terminal mode.

### 1 - Clone this repository

```bash
git clone https://github.com/SetZero/mumble-docker
cd mumble-docker
```

### 2 - Run the setup wizard

**Terminal (any OS)**

```bash
python -m setup_wizard
```

**Graphical UI** (optional - requires `dearpygui`)

```bash
pip install -r setup_wizard/requirements.txt
python -m setup_wizard --gui
```

The GUI wizard is a multi-step form:

- **Step 1 - Source tree**: point the wizard at your local
  `mumble-server` checkout, or click **Clone...** to let the wizard
  clone the server source for you and fill in the path automatically.
- **Steps 2–7**: configure image names, ports, runtime UID/GID, the
  SuperUser password (or click **Generate** for a strong random one),
  optional file mounts, and Firebase push-notification credentials.
- Navigate with **Next / Back**.  Each step is validated before
  advancing.  Clicking **Save .env** on the last step writes the file.

The wizard pre-fills every prompt from an existing `.env` so re-running
it later to tweak a single value is non-destructive.

### 3 - Start the server

```bash
# Pull the pre-built image and start
docker compose up -d

# Or build from source first (uses the .env you just created)
python -m tools dev-build
```

### 4 - Set the SuperUser password (first run only)

If you left `MUMBLE_SUPERUSER_PASSWORD` blank during the wizard the
server prints a randomly generated password to its log on first start:

```bash
docker logs mumble-server 2>&1 | grep -i superuser
```

You can also set or reset the password at any time:

```bash
docker exec mumble-server mumble-server --ini /data/mumble_server_config.ini \
    --set-su-pw <newpassword>
```

### 5 - Connect

Open the [Fancy Mumble client](https://github.com/Fancy-Mumble/FancyMumbleNext)
and connect to `<your-host>:64738`.  Log in as **SuperUser** with the
password from the previous step to manage channels and permissions.

> **Re-run the wizard any time** to update your configuration:
> `python -m setup_wizard` or `python -m tools setup`.


## Running the container

### Requirements

This documentation assumes that you already have Docker installed and configured on your target machine.

In order for Mumble to store permanent data the image uses a [volume](https://docs.docker.com/storage/volumes/) mapped to `/data/` inside the container. By default the server runs as UID/GID `10000:10000`, but both can be overridden at build time (see [below](#using-a-different-uidgid)).

### Using docker

```bash
docker run --detach \
           --name mumble-server \
           --publish 64738:64738/tcp \
           --publish 64738:64738/udp \
           --publish 64739:64739/tcp \
           --publish 10000:10000/udp \
           --volume mumble-data:/data \
           --restart on-failure \
           ghcr.io/setzero/mumble-server:latest
```

### Using docker compose

```yaml
services:
  mumble-server:
    image: ghcr.io/setzero/mumble-server:latest
    container_name: mumble-server
    hostname: mumble-server
    restart: on-failure
    ports:
      - "64738:64738/tcp"   # Mumble voice + control
      - "64738:64738/udp"
      - "64739:64739/tcp"   # File server (emotes, avatars, attachments)
      - "10000:10000/udp"   # WebRTC SFU (screen sharing)
    volumes:
      - mumble-data:/data
    environment:
      MUMBLE_SUPERUSER_PASSWORD: "changeme"
      # All server settings can be passed as MUMBLE_CONFIG_<key>=<value>
      # MUMBLE_CONFIG_USERS: 100
      # MUMBLE_CONFIG_WELCOMETEXT: "Hello!"

volumes:
  mumble-data:
```

> **ICE RPC** (admin interface, default port `6502`) is bound to `127.0.0.1` inside the container and is not exposed by default. Map it explicitly when you need it.


## Exposed ports

| Port | Protocol | Purpose |
|------|----------|---------|
| `64738` | TCP + UDP | Mumble voice and control (standard port) |
| `64739` | TCP | Built-in file server - emotes, avatar uploads, attachments |
| `10000` | UDP | WebRTC SFU - server-side relay for screen sharing |
| `6502`  | TCP | ICE RPC admin interface (loopback only, opt-in) |


## Configuration

The preferred way to configure the server is via environment variables of the form `MUMBLE_CONFIG_<configName>`. All options from the standard Mumble server configuration file are supported. For an overview of available options see [Murmur.ini](https://wiki.mumble.info/wiki/Murmur.ini).

`<configName>` is case-insensitive and underscores may be inserted for readability. `MUMBLE_CONFIG_dbhost`, `MUMBLE_CONFIG_DBHOST` and `MUMBLE_CONFIG_DB_HOST` all refer to the same option.

```bash
docker run -e "MUMBLE_CONFIG_USERS=200" -e "MUMBLE_CONFIG_SERVER_PASSWORD=secret" ...
```

Or in docker compose:

```yaml
environment:
  MUMBLE_CONFIG_USERS: 100
  MUMBLE_CONFIG_SENDVERSION: false
  MUMBLE_CONFIG_WELCOMETEXT: 'Hello World'
  # String values containing special characters must be quoted:
  MUMBLE_CONFIG_USERNAME: '"^[-_a-z0-9]{3,15}$"'
```

### Using a custom config file

Mount your own `mumble-server.ini` and point the entrypoint at it - all `MUMBLE_CONFIG_*` variables are then **ignored**:

```yaml
environment:
  MUMBLE_CUSTOM_CONFIG_FILE: /data/mumble-server.ini
volumes:
  - ./mumble-server.ini:/data/mumble-server.ini:ro
  - mumble-data:/data
```

A documented sample config is provided at [`mumble-server.ini.example`](mumble-server.ini.example).  Copy it to `mumble-server.ini` (gitignored) and edit to taste - the setup wizard will also bootstrap and patch this local copy for you when `MUMBLE_INI` is set.

### Using Docker / Podman secrets

Configuration values can also be read from files in `/run/secrets/` following the `MUMBLE_CONFIG_<name>` naming pattern:

```bash
echo -n "supersecret" | podman secret create MUMBLE_CONFIG_SERVER_PASSWORD -
echo -n "adminpass"   | podman secret create MUMBLE_SUPERUSER_PASSWORD -

podman run --detach \
           --name mumble-server \
           --publish 64738:64738/tcp \
           --publish 64738:64738/udp \
           --publish 64739:64739/tcp \
           --publish 10000:10000/udp \
           --secret MUMBLE_CONFIG_SERVER_PASSWORD \
           --secret MUMBLE_SUPERUSER_PASSWORD \
           --volume mumble-data:/data \
           --restart on-failure \
           ghcr.io/setzero/mumble-server:latest
```

### Additional environment variables

| Variable | Description |
|----------|-------------|
| `MUMBLE_SUPERUSER_PASSWORD` | SuperUser (admin) password. A random one is printed to the log on first start if unset. |
| `MUMBLE_CUSTOM_CONFIG_FILE` | Path to a custom ini file. All `MUMBLE_CONFIG_*` variables are ignored when this is set. |
| `MUMBLE_CHOWN_DATA` | Set to `false` to skip taking ownership of `/data` at startup. |
| `MUMBLE_ACCEPT_UNKNOWN_SETTINGS` | Set to `true` to pass through unknown `MUMBLE_CONFIG_*` values without failing. |
| `MUMBLE_VERBOSE` | Set to `true` to enable verbose server logging. |
| `PUID` / `PGID` | UID / GID the server process runs as (default `10000`/`10000`). |


## Configuration wizard

For local development the repository ships with an interactive **setup
wizard** that walks you through every value documented in
[`.env.example`](.env.example) and writes a fresh `.env` file.  The
wizard is split along an MVC boundary so the same business logic backs
both a terminal UI and an optional graphical front-end:

| Mode | Command                                              | Requirements           |
|------|------------------------------------------------------|------------------------|
| TUI  | `python -m setup_wizard`                             | stdlib only            |
| GUI  | `python -m setup_wizard --gui`                       | `dearpygui` (optional) |
| via tools | `python -m tools setup [--gui]`                 | Python 3.8+            |

Install the GUI dependency once:

```bash
python -m pip install -r setup_wizard/requirements.txt
```

The wizard:

- Pre-fills every prompt from an existing `.env`, so re-running it to
  tweak a single value is non-destructive.
- Validates ports, paths and UID/GID values.
- Generates a strong random `MUMBLE_SUPERUSER_PASSWORD` on demand.
- Auto-encodes a Firebase service-account JSON into
  `MUMBLE_FCM_CREDENTIALS_BASE64` so credentials never need to live on a
  bind-mounted host path or in an image layer.

See [`setup_wizard/README.md`](setup_wizard/README.md) for the full
documentation, the package layout (`model.py` / `controller.py` /
`view_cli.py` / `view_gui.py`) and how to embed the wizard from another
tool.


## Building the container

Clone this repository and run:

```bash
docker build .
```

This clones the [Fancy Mumble server fork](https://github.com/SetZero/mumble-server) (branch `1.6.x`), builds the C++ server, the Rust WebRTC SFU library and the plugin-host shared library, and produces a minimal runtime image.

### Build arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `MUMBLE_GIT_REPO` | `https://github.com/SetZero/mumble-server` | Source repository to clone |
| `MUMBLE_GIT_BRANCH` | `1.6.x` | Branch to build |
| `MUMBLE_VERSION` | `latest` | Tag or commit hash to check out after cloning |
| `MUMBLE_CMAKE_ARGS` | `-Dwebrtc-sfu=OFF` | Extra CMake arguments passed to the build |
| `MUMBLE_BUILD_NUMBER` | _(empty)_ | Optional build number embedded in the binary |
| `PUID` / `PGID` | `10000` | UID/GID of the `mumble` user in the final image |

Example - build from a specific tag with the WebRTC SFU enabled:

```bash
docker build \
  --build-arg MUMBLE_VERSION=v1.6.0 \
  --build-arg MUMBLE_CMAKE_ARGS="-Dwebrtc-sfu=ON" \
  .
```

Example - build from a different fork:

```bash
docker build \
  --build-arg MUMBLE_GIT_REPO=https://github.com/youruser/mumble \
  --build-arg MUMBLE_GIT_BRANCH=my-feature \
  .
```

### Using a different UID/GID

Pass `PUID` and `PGID` as build arguments to bake a different user into the image. The entrypoint also accepts them as runtime environment variables when the container starts as root:

```bash
docker build --build-arg PUID=1000 --build-arg PGID=1000 .
```

### Common build issues

**`Got permission denied while trying to connect to the Docker daemon socket`** - you need to be in the `docker` group. See the [official docs](https://docs.docker.com/engine/install/linux-postinstall/#manage-docker-as-a-non-root-user).

**`apt-get` fails with "not valid yet"** - clock skew in BuildKit. The Dockerfiles already pass `-o Acquire::Check-Date=false` to work around this.


## Fancy Mumble features

### Persistent chat

Server-side, encrypted message history.  All text messages are stored in the database and delivered to clients that reconnect after being offline.

```ini
pchatenabled=true
; pchatrequireregistration=false
; pchatdefaultmaxhistory=5000
; pchatdefaultretentiondays=90
```

### Push notifications (FCM)

The server dynamically loads `libmumble_push_fcm.so` (included in the image) to send Firebase Cloud Messaging push notifications to mobile/desktop clients.

> **Security note:** Firebase service-account JSON keys must never be baked into a Docker image layer. The entrypoint decodes the credentials at runtime into a tmpfs path (`/tmp/fcm-credentials.json`) that exists only inside the running container and is never committed to any layer.

#### Step 1 - obtain a service-account key

Create a Firebase project, go to **Project settings → Service accounts → Generate new private key** and download the JSON file.

#### Step 2 - supply credentials at runtime (pick one method)

**Method A - Docker / Podman secret (recommended for production)**

```bash
# Create the secret from the JSON file
docker secret create MUMBLE_FCM_CREDENTIALS ./your-firebase-key.json

# Reference it in docker-compose (Swarm) or podman run
```

```yaml
services:
  mumble-server:
    secrets:
      - MUMBLE_FCM_CREDENTIALS
    environment:
      MUMBLE_CONFIG_PUSHENABLED: true
      MUMBLE_CONFIG_PUSHPROJECTID: your-firebase-project-id

secrets:
  MUMBLE_FCM_CREDENTIALS:
    external: true
```

The entrypoint reads `/run/secrets/MUMBLE_FCM_CREDENTIALS` automatically and sets `pushcredentialspath` for you.

**Method B - base64 environment variable (good for Kubernetes / CI)**

Encode the JSON key on your workstation:

```bash
# Linux / macOS
base64 -w 0 your-firebase-key.json

# PowerShell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("your-firebase-key.json"))
```

Then pass the output as an environment variable (or set it in `.env`):

```yaml
environment:
  MUMBLE_FCM_CREDENTIALS_BASE64: "<base64 string>"
  MUMBLE_CONFIG_PUSHENABLED: true
  MUMBLE_CONFIG_PUSHPROJECTID: your-firebase-project-id
```

The setup wizard (`python -m setup_wizard`, see [Configuration wizard](#configuration-wizard)) can encode the file for you automatically.

**Method C - file mount (local development only)**

```yaml
volumes:
  - ./fcm-credentials.json:/data/fcm-credentials.json:ro
environment:
  MUMBLE_CONFIG_PUSHENABLED: true
  MUMBLE_CONFIG_PUSHPROJECTID: your-firebase-project-id
  MUMBLE_CONFIG_PUSHCREDENTIALSPATH: /data/fcm-credentials.json
```

> Do not use a file mount in production - it couples the container to a host path and risks the file being accidentally included in an image build context. A `.dockerignore` is provided but defence in depth matters.

#### Step 3 - tune notification events

```ini
pushnotifytextmessage=true
pushnotifyreaction=false
pushnotifyuserjoin=false
pushtopicprefix=mumble
```

### WebRTC SFU (screen sharing)

The server dynamically loads `libwebrtc_sfu.so` (already included in the image) to relay WebRTC screen-share streams.  Expose port `10000/udp` and set the public IP:

```yaml
ports:
  - "10000:10000/udp"
environment:
  MUMBLE_CONFIG_WEBRTCSFUENABLED: true
  MUMBLE_CONFIG_WEBRTCSFUPORT: 10000
  MUMBLE_CONFIG_WEBRTCSFUPUBLICIP: "203.0.113.1"   # your server's public IP
```

Without a public IP configured, screen sharing still works between clients on the same network via direct signalling (no SFU relay).

### File server (emotes, avatars, attachments)

The plugin-host loads a built-in file server on port `64739`.  A storage directory inside the volume is required:

```yaml
ports:
  - "64739:64739/tcp"
environment:
  MUMBLE_CUSTOM_CONFIG_FILE: /data/mumble-server.ini
```

```ini
plugin.file-server.storagePath=/data/file-server-storage
plugin.file-server.bindAddress=0.0.0.0
plugin.file-server.port=64739
plugin.file-server.tlsTerminatedByProxy=true
; plugin.file-server.baseUrl=https://your-domain.example/mumble-files
; plugin.file-server.allowedOrigins=https://your-domain.example
```

> The file server currently requires a custom ini file (`MUMBLE_CUSTOM_CONFIG_FILE`); `plugin.*` keys cannot yet be set via `MUMBLE_CONFIG_*` environment variables.

