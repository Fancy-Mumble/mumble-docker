"""View-agnostic orchestration for the wizard.

The :class:`Wizard` here owns the *state* of an in-progress edit (the
``values`` dict) and exposes the side-effects (encoding, saving) the
views need.  Both :mod:`setup_wizard.view_cli` and
:mod:`setup_wizard.view_gui` operate on a single ``Wizard`` instance.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

from .model import (
    Section,
    build_sections,
    load_existing_env,
    write_env,
)


def encode_fcm_credentials(path: Path) -> str:
    """Base64-encode the JSON service-account file at ``path``.

    Raises :class:`FileNotFoundError` if the path is not readable so
    callers can show a friendly error.
    """

    return base64.b64encode(path.read_bytes()).decode()


class Wizard:
    """Stateful, view-agnostic wizard controller."""

    def __init__(self, output: Path) -> None:
        self.output = output
        self.existing: dict[str, str] = load_existing_env(output)
        self.values: dict[str, str] = {}
        self.sections: list[Section] = build_sections(self.existing)

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

    def save(self) -> None:
        write_env(self.output, self.values)
