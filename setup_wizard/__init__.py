"""mumble-docker setup wizard.

Re-exports the public API for embedding the wizard from other tools.
The CLI / GUI entry points live in :mod:`setup_wizard.__main__`.
"""

from .model import (
    INI_KEY_FOR_ENV,
    Section,
    Setting,
    build_sections,
    load_existing_env,
    patch_ini_toggles,
    random_password,
    write_env,
)
from .controller import Wizard, encode_fcm_credentials

__all__ = [
    "INI_KEY_FOR_ENV",
    "Section",
    "Setting",
    "Wizard",
    "build_sections",
    "encode_fcm_credentials",
    "load_existing_env",
    "patch_ini_toggles",
    "random_password",
    "write_env",
]
