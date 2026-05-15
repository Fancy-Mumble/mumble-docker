"""View-agnostic orchestration for the wizard.

The :class:`Wizard` here owns the *state* of an in-progress edit (the
``values`` dict) and exposes the side-effects (encoding, saving) the
views need.  Both :mod:`setup_wizard.view_cli` and
:mod:`setup_wizard.view_gui` operate on a single ``Wizard`` instance.
"""

from __future__ import annotations

import base64
import shutil
from pathlib import Path
from typing import Optional

from .model import (
    INI_KEY_FOR_ENV,
    REPO_ROOT,
    Section,
    build_sections,
    load_existing_env,
    patch_ini_toggles,
    write_env,
)


INI_EXAMPLE_PATH = REPO_ROOT / "mumble-server.ini.example"


def encode_fcm_credentials(path: Path) -> str:
    """Base64-encode the JSON service-account file at ``path``.

    Raises :class:`FileNotFoundError` if the path is not readable so
    callers can show a friendly error.
    """

    return base64.b64encode(path.read_bytes()).decode()


class Wizard:
    """Stateful, view-agnostic wizard controller.

    ``source`` is the path values are *loaded* from when the wizard
    starts; ``output`` is where they are *saved*.  They default to the
    same path (the classic "edit project .env" flow), but the GUI
    config selector lets the user pick them independently - load from
    a template and save somewhere new without overwriting the original.
    """

    def __init__(self, output: Path, *,
                 source: Optional[Path] = None) -> None:
        self.output = output
        self.source: Optional[Path] = source if source is not None else output
        self.existing: dict[str, str] = (
            load_existing_env(self.source) if self.source else {}
        )
        self.values: dict[str, str] = {}
        self.sections: list[Section] = build_sections(self.existing)

    def reload(self, source: Optional[Path]) -> None:
        """Re-bind the source path and rebuild section defaults.

        Lets the GUI config selector swap between "load existing" and
        "start fresh" without recreating the Wizard instance.
        """
        self.source = source
        self.existing = load_existing_env(source) if source else {}
        self.values = {}
        self.sections = build_sections(self.existing)

    def set_value(self, key: str, value: str, *, skip_if_empty: bool = True) -> None:
        if value or not skip_if_empty:
            self.values[key] = value
        else:
            # Drop empty values so we don't pollute the .env file.
            self.values.pop(key, None)

    def get_value(self, key: str, default: str = "") -> str:
        return self.values.get(key, self.existing.get(key, default))

    def maybe_encode_fcm(self) -> Optional[str]:
        """If the user supplied a JSON path but no base64 value, encode it.

        Returns the encoded string on success, ``None`` if there is
        nothing to do.  Lets callers decide whether to confirm with the
        user first.
        """

        path_str = self.values.get("MUMBLE_FCM_CREDENTIALS", "")
        if not path_str:
            return None
        if self.values.get("MUMBLE_FCM_CREDENTIALS_BASE64"):
            return None
        path = Path(path_str).expanduser()
        if not path.exists():
            return None
        encoded = encode_fcm_credentials(path)
        self.values["MUMBLE_FCM_CREDENTIALS_BASE64"] = encoded
        return encoded

    def save(self) -> Optional[Path]:
        """Persist the wizard's values to ``self.output``.

        When ``MUMBLE_INI`` is set, the same feature toggles are also
        patched into that .ini - the dev-debug flow loads its config
        straight from the mounted file and never sees ``MUMBLE_CONFIG_*``
        env vars, so this keeps the two stores from drifting apart.
        If ``MUMBLE_INI`` points at a path that doesn't exist yet, the
        committed ``mumble-server.ini.example`` is copied to that path
        first as a starting template (the gitignored .ini is meant to
        be a per-deployment local copy of the example).  Returns the
        .ini path if it was patched, otherwise ``None``.
        """

        write_env(self.output, self.values)
        ini_str = self.values.get("MUMBLE_INI", "").strip()
        if not ini_str:
            return None
        ini_path = Path(ini_str).expanduser()
        if not ini_path.exists():
            if not INI_EXAMPLE_PATH.exists():
                return None
            try:
                ini_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(INI_EXAMPLE_PATH, ini_path)
            except OSError:
                return None
        updates: dict[str, str] = {}
        for env_key, ini_key in INI_KEY_FOR_ENV.items():
            if env_key in self.values:
                updates[ini_key] = self.values[env_key]
        if not updates:
            return ini_path
        patch_ini_toggles(ini_path, updates)
        return ini_path
