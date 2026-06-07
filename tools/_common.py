"""Shared helpers for the cross-platform tools package.

This module deliberately depends only on the Python standard library so
the helpers run on Windows, macOS and Linux without any third-party
packages.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Repo discovery
# ---------------------------------------------------------------------------

# tools/_common.py  ->  <repo>/
REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"


# ---------------------------------------------------------------------------
# .env loading
# ---------------------------------------------------------------------------

def load_env(path: Path = ENV_PATH) -> dict[str, str]:
    """Parse ``path`` and return its key=value map.

    Lines starting with ``#`` and blank lines are ignored.  Values are
    taken literally (no quote stripping, no variable expansion).  The
    real process environment is *not* mutated; values already present
    there always win.
    """

    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k:
            out[k] = v
    return out


def env_with_defaults(defaults: Mapping[str, str]) -> dict[str, str]:
    """Return a merged environment view.

    Precedence (highest first):

    1. The current process environment (``os.environ``).
    2. The ``.env`` file in the repo root.
    3. The ``defaults`` mapping passed in.
    """

    merged: dict[str, str] = dict(defaults)
    merged.update(load_env())
    for k in defaults.keys() | merged.keys():
        if k in os.environ and os.environ[k] != "":
            merged[k] = os.environ[k]
    return merged


# ---------------------------------------------------------------------------
# Logging helpers (no external deps; honour NO_COLOR)
# ---------------------------------------------------------------------------

def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return True


_COLOR = _supports_color()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def banner(msg: str) -> None:
    print()
    print(_c("36;1", f"=== {msg} ==="))
    print()


def info(msg: str) -> None:
    print(msg)


def warn(msg: str) -> None:
    print(_c("33", f"[WARN] {msg}"), file=sys.stderr)


def error(msg: str) -> None:
    print(_c("31;1", f"[ERROR] {msg}"), file=sys.stderr)


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------

def require_docker() -> None:
    """Abort early with a clear message if ``docker`` is not on PATH."""

    if shutil.which("docker") is None:
        error("`docker` was not found on PATH.  Install Docker Desktop "
              "or the Docker Engine and try again.")
        raise SystemExit(127)


def run(
    argv: Sequence[str],
    *,
    check: bool = True,
    capture: bool = False,
    quiet: bool = False,
    env: Optional[Mapping[str, str]] = None,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """Thin wrapper around :func:`subprocess.run` with sane defaults.

    * ``argv`` is always a list (no shell, no quoting issues).
    * Stdout/stderr stream to the terminal unless ``capture`` is set.
    * Errors are surfaced via :class:`SystemExit` with the child's exit
      code so the calling tool's CLI exit code matches Docker's.
    """

    if not quiet:
        info(_c("2", "$ " + " ".join(_quote(_redact(a)) for a in argv)))

    full_env: Optional[Mapping[str, str]] = None
    if env is not None:
        full_env = {**os.environ, **env}

    stdout = subprocess.PIPE if capture or quiet else None
    stderr = subprocess.PIPE if capture or quiet else None

    try:
        cp = subprocess.run(
            list(argv),
            check=False,
            stdout=stdout,
            stderr=stderr,
            input=input_text,
            text=True,
            env=full_env,
        )
    except FileNotFoundError as e:
        error(f"command not found: {argv[0]} ({e})")
        raise SystemExit(127) from e

    if check and cp.returncode != 0:
        if capture or quiet:
            sys.stdout.write(cp.stdout or "")
            sys.stderr.write(cp.stderr or "")
        raise SystemExit(cp.returncode)

    return cp


def _quote(arg: str) -> str:
    if not arg or any(c.isspace() or c in '"\\' for c in arg):
        return '"' + arg.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return arg


# Argument names whose value is a secret and must never be echoed to the
# terminal/logs (FCM service-account key, passwords, tokens, base64 blobs, ...).
_SECRET_NAME_RE = re.compile(
    r"(CREDENTIAL|SECRET|TOKEN|PASSWORD|PASSPHRASE|PRIVATE|APIKEY|API_KEY|_KEY|BASE64)",
    re.IGNORECASE,
)


def _redact(arg: str) -> str:
    """Mask the value of a ``NAME=VALUE`` argument when ``NAME`` looks secret,
    so credentials never reach the printed command line.  The real value is
    still passed to the child process unchanged - only the echo is masked."""
    eq = arg.find("=")
    if eq <= 0:
        return arg
    name = arg[:eq]
    if _SECRET_NAME_RE.search(name):
        return name + "=***"
    return arg


def docker(
    args: Sequence[str],
    *,
    check: bool = True,
    capture: bool = False,
    quiet: bool = False,
    input_text: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """``docker`` invocation with ``DOCKER_BUILDKIT=1`` enabled."""

    return run(["docker", *args],
               check=check, capture=capture, quiet=quiet,
               env={"DOCKER_BUILDKIT": "1"},
               input_text=input_text)


def docker_quiet(args: Sequence[str], *, check: bool = False) -> int:
    """Run docker without printing the command line; return exit code."""

    cp = docker(args, check=check, quiet=True)
    return cp.returncode


def container_running(name: str) -> bool:
    cp = docker(["inspect", "--format", "{{.State.Running}}", name],
                check=False, capture=True, quiet=True)
    return cp.returncode == 0 and cp.stdout.strip().lower() == "true"


def stop_and_remove(*names: str) -> None:
    """Best-effort ``docker stop`` + ``docker rm`` for each name."""

    for n in names:
        if not n:
            continue
        docker_quiet(["stop", n])
        docker_quiet(["rm", n])


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def host_path(value: Optional[str]) -> Optional[Path]:
    """Expand ``value`` (if non-empty) to a resolved absolute :class:`Path`."""

    if not value:
        return None
    return Path(value).expanduser().resolve()


def docker_mount(host: Path, container: str, *, read_only: bool = False) -> str:
    """Format a ``-v`` value with the colon syntax Docker expects.

    On Windows ``Path.resolve()`` returns ``C:\\foo`` style paths which
    Docker Desktop happily accepts when forward slashes are used.
    """

    src = str(host).replace("\\", "/")
    suffix = ":ro" if read_only else ""
    return f"{src}:{container}{suffix}"


def ini_arg(env: Mapping[str, str]) -> list[str]:
    """Pick the right ``--ini`` argument depending on whether MUMBLE_INI is set."""

    if env.get("MUMBLE_INI"):
        return ["--ini", "/data/mumble-server.ini"]
    return ["--ini", "/data/mumble_server_config.ini"]


# ---------------------------------------------------------------------------
# Mount-list helpers shared by the run helpers
# ---------------------------------------------------------------------------

def passthrough_env(env: Mapping[str, str]) -> list[str]:
    """Return ``-e KEY=VALUE`` args for variables that the container's
    entrypoint understands directly.

    Forwards every ``MUMBLE_CONFIG_*`` key (the entrypoint expands these
    into the generated mumble-server.ini) plus the FCM credential helper
    ``MUMBLE_FCM_CREDENTIALS_BASE64``.  Empty values are skipped so a
    blank ``.env`` line doesn't override a non-empty value baked into
    the image or compose file.
    """

    args: list[str] = []
    for key, value in env.items():
        if not value:
            continue
        if key.startswith("MUMBLE_CONFIG_") or key == "MUMBLE_FCM_CREDENTIALS_BASE64":
            args += ["-e", f"{key}={value}"]
    return args


def standard_mounts(env: Mapping[str, str]) -> list[str]:
    """Build the ``-v`` arguments common to every mumble container.

    The data volume is always mounted; the optional MUMBLE_INI and
    MUMBLE_FCM_CREDENTIALS files are mounted read-only when they exist.
    """

    args: list[str] = ["-v", f"{env['MUMBLE_DATA_VOLUME']}:/data"]

    ini = host_path(env.get("MUMBLE_INI"))
    if ini:
        if ini.exists():
            args += ["-v", docker_mount(ini, "/data/mumble-server.ini",
                                        read_only=True)]
        else:
            warn(f"MUMBLE_INI is set but file does not exist: {ini}")

    fcm = host_path(env.get("MUMBLE_FCM_CREDENTIALS"))
    if fcm:
        if fcm.exists():
            args += ["-v", docker_mount(fcm, "/data/fcm-credentials.json",
                                        read_only=True)]
        else:
            warn(f"MUMBLE_FCM_CREDENTIALS is set but file does not exist: {fcm}")

    return args


# ---------------------------------------------------------------------------
# Windows host-port reservations (winnat / Hyper-V)
# ---------------------------------------------------------------------------

def windows_excluded_ports(proto: str) -> list[tuple[int, int, bool]]:
    """Return Windows' reserved host-port ranges for ``proto`` (tcp/udp).

    Each entry is ``(start, end, administered)``.  ``administered`` is
    ``True`` for the rows ``netsh`` marks with ``*`` (persistent
    exclusions added explicitly) and ``False`` for the dynamic ranges
    winnat/Hyper-V allocates on the fly.

    Returns an empty list on non-Windows hosts or if ``netsh`` cannot be
    queried.  Parsing keys off the numeric columns only, so it is immune
    to localised ``netsh`` headers.
    """

    if os.name != "nt":
        return []
    try:
        cp = subprocess.run(
            ["netsh", "interface", "ipv4", "show",
             "excludedportrange", f"protocol={proto}"],
            check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True,
        )
    except OSError:
        return []

    ranges: list[tuple[int, int, bool]] = []
    for line in (cp.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            administered = len(parts) >= 3 and parts[2] == "*"
            ranges.append((int(parts[0]), int(parts[1]), administered))
    return ranges


def assert_host_ports_bindable(ports: Sequence[tuple[int, str]]) -> None:
    """Abort early if any host port is trapped in a Windows reserved range.

    ``ports`` is a sequence of ``(port, proto)`` pairs we are about to
    publish.  A port that lies inside a *dynamic* (non-administered)
    excluded range cannot be bound by Docker -- the daemon fails it with
    the cryptic ``"An attempt was made to access a socket in a way
    forbidden by its access permissions"`` error.  Persistent
    (administered) exclusions stay bindable, so those are ignored.

    No-op on non-Windows hosts.
    """

    if os.name != "nt":
        return

    cache: dict[str, list[tuple[int, int, bool]]] = {}
    blocked: list[tuple[int, str]] = []
    for port, proto in ports:
        ranges = cache.setdefault(proto, windows_excluded_ports(proto))
        for start, end, administered in ranges:
            if start <= port <= end and not administered:
                blocked.append((port, proto))
                break

    if not blocked:
        return

    error("Host port(s) are inside a Windows reserved (winnat/Hyper-V) range "
          "and cannot be bound by Docker:")
    for port, proto in blocked:
        info(f"    - {port}/{proto}")
    info("")
    info("Reserve them as persistent exclusions from an elevated "
         "(Administrator) PowerShell, then restart Docker Desktop:")
    info("")
    info("    net stop winnat")
    for port, proto in blocked:
        info(f"    netsh int ipv4 add excludedportrange protocol={proto} "
             f"startport={port} numberofports=1 store=persistent")
    info("    net start winnat")
    info("")
    info("(Persistent exclusions survive reboots and remain bindable, unlike "
         "the dynamic reservations winnat allocates.)")
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------

def maybe_clean_buildx_cache(args: Iterable[str]) -> None:
    """Honour the ``--clean`` flag accepted by the build helpers."""

    if "--clean" in args:
        info("Pruning BuildKit cache mounts...")
        docker(["builder", "prune", "--filter", "type=exec.cachemount", "-f"])


def require_path(env: Mapping[str, str], key: str, *, what: str = "path") -> Path:
    """Validate that ``env[key]`` is set and points at an existing path."""

    raw = env.get(key, "")
    if not raw:
        error(f"{key} is not set.  Define it in .env or in your shell.")
        raise SystemExit(2)
    p = Path(raw).expanduser().resolve()
    if not p.exists():
        error(f"{key} does not exist: {p}")
        raise SystemExit(2)
    return p


def resolve_fancy_plugins_src(env: Mapping[str, str], mumble_src: Path) -> Path:
    """Resolve the path to the local ``fancy-plugin-example`` checkout.

    Resolution order:

    1. ``MUMBLE_FANCY_PLUGINS_SRC`` environment / ``.env`` entry.
    2. ``<mumble_src>/../fancy-plugin-example`` (true sibling).
    3. ``<mumble_src>/../../fancy/fancy-plugin-example`` (the layout
       this repo's contributor uses locally).

    Aborts with a clear error if none of the candidates exists.  The
    workspace ``Cargo.toml`` declares a path-dep at
    ``../mumble-server/3rdparty/mumble-plugin-host/api``, so the
    checkout the path points at must be the same revision as
    ``MUMBLE_SRC``.
    """

    explicit = host_path(env.get("MUMBLE_FANCY_PLUGINS_SRC"))
    if explicit is not None:
        if not explicit.exists():
            error(f"MUMBLE_FANCY_PLUGINS_SRC does not exist: {explicit}")
            raise SystemExit(2)
        return explicit

    candidates = [
        mumble_src.parent / "fancy-plugin-example",
        mumble_src.parent.parent / "fancy" / "fancy-plugin-example",
    ]
    for cand in candidates:
        if (cand / "Cargo.toml").is_file():
            return cand.resolve()

    error(
        "Could not locate the fancy-plugin-example checkout.\n"
        "  Tried:\n"
        + "\n".join(f"    - {c}" for c in candidates)
        + "\n  Set MUMBLE_FANCY_PLUGINS_SRC in .env or your shell to override."
    )
    raise SystemExit(2)
