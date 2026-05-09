"""Shared helpers for the cross-platform tools package.

This module deliberately depends only on the Python standard library so
the helpers run on Windows, macOS and Linux without any third-party
packages.
"""

from __future__ import annotations

import os
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
        info(_c("2", "$ " + " ".join(_quote(a) for a in argv)))

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
