"""Terminal (TTY) view for the setup wizard.

Pure stdlib — works in cmd.exe, PowerShell and any POSIX shell.  Drives
a :class:`setup_wizard.controller.Wizard` instance.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Callable, Optional

from .controller import Wizard
from .model import random_password


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if not sys.stdout.isatty():
        return False
    if os.name == "nt":
        # Enable ANSI on modern Windows 10+ terminals.
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            return True
        except Exception:
            return False
    return True


_COLOR = _supports_color()

# Reconfigure stdout/stderr to UTF-8 where possible (Windows defaults to cp1252).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def bold(t: str) -> str:    return _c("1", t)
def dim(t: str) -> str:     return _c("2", t)
def cyan(t: str) -> str:    return _c("36", t)
def green(t: str) -> str:   return _c("32", t)
def yellow(t: str) -> str:  return _c("33", t)
def red(t: str) -> str:     return _c("31", t)


def hr(title: str = "") -> None:
    width = shutil.get_terminal_size((80, 20)).columns
    if title:
        bar = "-" * max(0, width - len(title) - 3)
        print(cyan(f"\n-- {bold(title)} {bar}"))
    else:
        print(cyan("-" * width))


def info(msg: str) -> None:
    print(f"  {msg}")


def _prompt(
    label: str,
    *,
    default: str,
    help_text: str,
    validator: Callable[[str], Optional[str]],
    secret: bool,
    non_interactive: bool,
) -> str:
    if non_interactive:
        return default

    if help_text:
        for line in help_text.strip().splitlines():
            print(dim(f"    {line}"))

    while True:
        suffix = f" [{green(default)}]" if default else ""
        if secret:
            suffix += dim(" (input hidden)")
        try:
            if secret:
                import getpass
                raw = getpass.getpass(f"  {bold(label)}{suffix}: ")
            else:
                raw = input(f"  {bold(label)}{suffix}: ")
        except EOFError:
            raw = ""
        value = raw.strip() if raw else default
        err = validator(value)
        if err is None:
            return value
        print(red(f"    ! {err}"))


def _prompt_bool(label: str, *, default: bool, non_interactive: bool = False) -> bool:
    if non_interactive:
        return default
    suffix = "Y/n" if default else "y/N"
    while True:
        try:
            raw = input(f"  {bold(label)} [{green(suffix)}]: ").strip().lower()
        except EOFError:
            raw = ""
        if not raw:
            return default
        if raw in ("y", "yes", "true", "1"):
            return True
        if raw in ("n", "no", "false", "0"):
            return False
        print(red("    ! please answer y or n"))


def run_cli(output: Path, *, non_interactive: bool = False) -> int:
    wizard = Wizard(output)

    print()
    print(bold(cyan("  mumble-docker setup wizard")))
    print(dim(f"  Writing to: {output}"))
    if wizard.existing:
        print(dim("  An existing .env was found - its values are pre-filled."))
    print(dim("  Press Enter to accept the default shown in [brackets].\n"))
    print(dim("  Companion repos:"))
    print(dim("    Server:  https://github.com/SetZero/mumble-server"))
    print(dim("    Client:  https://github.com/Fancy-Mumble/FancyMumbleNext"))

    # Optional: offer to generate a random SuperUser password before the loop.
    if not non_interactive and not wizard.existing.get("MUMBLE_SUPERUSER_PASSWORD"):
        if _prompt_bool("Generate a random SuperUser password?", default=False):
            wizard.existing["MUMBLE_SUPERUSER_PASSWORD"] = random_password()
            info(green(f"  generated: {wizard.existing['MUMBLE_SUPERUSER_PASSWORD']}"))
            info(yellow("  -> save this password somewhere safe."))
            # Refresh sections so the new default is visible.
            from .model import build_sections
            wizard.sections = build_sections(wizard.existing)

    for section in wizard.sections:
        hr(section.title)
        if section.description:
            for line in section.description.splitlines():
                print(dim(f"  {line.strip()}"))
            print()
        for setting in section.settings:
            value = _prompt(
                setting.label,
                default=setting.default,
                help_text=setting.help_text,
                validator=setting.validator,
                secret=setting.secret,
                non_interactive=non_interactive,
            )
            wizard.set_value(setting.key, value, skip_if_empty=setting.skip_if_empty)

    # FCM credentials: offer to encode the JSON file automatically.
    fcm_path = wizard.values.get("MUMBLE_FCM_CREDENTIALS", "")
    fcm_b64 = wizard.values.get("MUMBLE_FCM_CREDENTIALS_BASE64", "")
    if fcm_path and not fcm_b64 and not non_interactive:
        if Path(fcm_path).expanduser().exists():
            if _prompt_bool(
                "Encode FCM credentials as base64 for MUMBLE_FCM_CREDENTIALS_BASE64?",
                default=True,
            ):
                wizard.maybe_encode_fcm()
                info(green("  FCM credentials encoded and stored in .env"))
                info(yellow("  Treat MUMBLE_FCM_CREDENTIALS_BASE64 like a password."))
                info(yellow("  Do not commit .env to version control."))

    hr("Summary")
    if not wizard.values:
        print(yellow("  No values to write."))
        return 0
    for k, v in wizard.values.items():
        if k.endswith("PASSWORD") or k.endswith("BASE64"):
            shown = "*" * min(len(v), 20)
        else:
            shown = v
        print(f"  {bold(k)}={shown}")

    if not non_interactive:
        if not _prompt_bool("\n  Write these values to " + str(output) + "?", default=True):
            print(yellow("  Aborted - no file written."))
            return 1

    wizard.save()
    print(green(f"\n  [OK] Wrote {output}"))
    print(dim("  You can re-run this wizard at any time to update values."))
    return 0
