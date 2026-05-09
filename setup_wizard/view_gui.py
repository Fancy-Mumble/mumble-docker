"""DearPyGui stepper view for the setup wizard.

Optional: requires the ``dearpygui`` package (see ``requirements.txt``).
The CLI view is fully usable without it, so this module is imported
lazily by :mod:`setup_wizard.__main__` only when ``--gui`` is passed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

from .controller import Wizard
from .model import Setting, random_password, validate_path_exists_optional

# ── Native OS file/folder picker ─────────────────────────────────────────────

def _native_pick(*, directory: bool, title: str,
                 filetypes: list[tuple[str, str]] | None = None) -> str:
    """Open the OS-native file or folder picker and return the chosen path.

    Must be called from a background thread; blocks until the user dismisses
    the dialog.  Returns an empty string if the user cancelled.
    """
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()          # hide the empty root window
    root.attributes("-topmost", True)
    try:
        if directory:
            result = filedialog.askdirectory(title=title, parent=root)
        else:
            result = filedialog.askopenfilename(
                title=title,
                filetypes=filetypes or [("All files", "*.*")],
                parent=root,
            )
    finally:
        root.destroy()
    return result or ""


def _browse_async(*, directory: bool, title: str,
                  filetypes: list[tuple[str, str]] | None = None,
                  on_result) -> None:
    """Spawn a daemon thread that opens the picker and calls on_result(path)."""
    def _run() -> None:
        path = _native_pick(directory=directory, title=title, filetypes=filetypes)
        if path:
            on_result(path)
    threading.Thread(target=_run, daemon=True).start()


# ── Font discovery ────────────────────────────────────────────────────────────

_CANDIDATE_FONTS: list[Path] = [
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf",
    Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "calibri.ttf",
    Path("/System/Library/Fonts/SFNS.ttf"),
    Path("/System/Library/Fonts/Helvetica.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("/usr/share/fonts/TTF/DejaVuSans.ttf"),
    Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
    Path("/usr/share/fonts/noto/NotoSans-Regular.ttf"),
]


def _pick_font() -> Optional[Path]:
    for candidate in _CANDIDATE_FONTS:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


# ── Colour palette ────────────────────────────────────────────────────────────

_C_ACCENT  = (100, 180, 255)
_C_SUCCESS = (100, 220, 120)
_C_WARN    = (255, 200,  80)
_C_ERROR   = (255,  90,  90)
_C_DIM     = (150, 150, 160)
_C_LABEL   = (220, 220, 230)
_C_DONE    = ( 90, 200, 120)
_C_SEP     = ( 60,  60,  72)


# ── Main entry point ──────────────────────────────────────────────────────────

def run_gui(output: Path) -> int:
    try:
        import dearpygui.dearpygui as dpg
    except ImportError:
        sys.stderr.write(
            "[ERROR] dearpygui is not installed.\n"
            "        Install it with:  pip install -r setup_wizard/requirements.txt\n"
            "        Or run without --gui to use the terminal wizard.\n"
        )
        return 2

    wizard = Wizard(output)
    sections = wizard.sections
    n_steps = len(sections)

    # ── Mutable UI state ──────────────────────────────────────────────────────

    state: dict = {"step": 0}
    input_ids: dict[str, int | str] = {}

    # Tags assigned during window construction; filled by reference capture.
    dot_tags: list[str] = []
    ref: dict[str, int | str] = {
        "title": 0, "desc": 0, "back": 0, "next": 0, "status": 0,
    }

    # Determine which settings are path-type and whether directory or file.
    path_settings: dict[str, bool] = {}   # key -> is_directory
    for section in sections:
        for setting in section.settings:
            if setting.validator is validate_path_exists_optional:
                path_settings[setting.key] = (setting.key == "MUMBLE_SRC")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _collect(idx: int) -> None:
        for setting in sections[idx].settings:
            tag = input_ids.get(setting.key)
            if tag is None:
                continue
            value = str(dpg.get_value(tag) or "").strip()
            wizard.set_value(setting.key, value,
                             skip_if_empty=setting.skip_if_empty)

    def _validate(idx: int) -> list[str]:
        errors: list[str] = []
        for setting in sections[idx].settings:
            err = setting.validator(wizard.values.get(setting.key, ""))
            if err:
                errors.append(f"{setting.label}: {err}")
        return errors

    def _set_status(msg: str, color=_C_DIM) -> None:
        dpg.configure_item(ref["status"], default_value=msg,
                           color=list(color))

    def _refresh_indicator(step: int) -> None:
        for i, tag in enumerate(dot_tags):
            if i < step:
                color = list(_C_DONE)
            elif i == step:
                color = list(_C_ACCENT)
            else:
                color = list(_C_DIM)
            dpg.configure_item(tag, color=color)
        dpg.set_value(ref["title"],
                      f"Step {step + 1} of {n_steps} - {sections[step].title}")
        desc = sections[step].description or ""
        dpg.set_value(ref["desc"], desc)
        dpg.configure_item(ref["desc"], show=bool(desc))

    def _go_to(new_step: int) -> None:
        dpg.configure_item(f"panel_{state['step']}", show=False)
        state["step"] = new_step
        dpg.configure_item(f"panel_{new_step}", show=True)
        dpg.configure_item(ref["back"], enabled=(new_step > 0))
        is_last = (new_step == n_steps - 1)
        dpg.configure_item(ref["next"], label="Save .env" if is_last else "Next >")
        _refresh_indicator(new_step)
        _set_status("")

    def _on_back() -> None:
        if state["step"] > 0:
            _collect(state["step"])
            _go_to(state["step"] - 1)

    def _on_next() -> None:
        idx = state["step"]
        _collect(idx)
        errors = _validate(idx)
        if errors:
            _set_status("Please fix: " + "  |  ".join(errors), _C_ERROR)
            return
        if idx == n_steps - 1:
            _do_save()
        else:
            _go_to(idx + 1)

    def _do_save() -> None:
        all_errors: list[str] = []
        for i in range(n_steps):
            _collect(i)
            all_errors.extend(_validate(i))
        if all_errors:
            _set_status("Errors: " + "  |  ".join(all_errors), _C_ERROR)
            return
        wizard.maybe_encode_fcm()
        b64_tag = input_ids.get("MUMBLE_FCM_CREDENTIALS_BASE64")
        if b64_tag is not None and wizard.values.get("MUMBLE_FCM_CREDENTIALS_BASE64"):
            dpg.set_value(b64_tag, wizard.values["MUMBLE_FCM_CREDENTIALS_BASE64"])
        try:
            wizard.save()
        except OSError as e:
            _set_status(f"Failed to write {output}: {e}", _C_ERROR)
            return
        dpg.configure_item(ref["next"], label="Close")
        dpg.configure_item(ref["next"], callback=dpg.stop_dearpygui)
        _set_status(f"Saved to {output} - you can close this window.",
                    _C_SUCCESS)

    def _on_generate_password() -> None:
        pw = random_password()
        dpg.set_value(input_ids["MUMBLE_SUPERUSER_PASSWORD"], pw)
        _set_status(f"Generated: {pw}   (save it somewhere safe!)", _C_WARN)

    def _on_encode_fcm() -> None:
        _collect(state["step"])
        path_str = wizard.values.get("MUMBLE_FCM_CREDENTIALS", "")
        if not path_str:
            _set_status("Set the FCM JSON path above first.", _C_ERROR)
            return
        p = Path(path_str).expanduser()
        if not p.exists():
            _set_status(f"File not found: {p}", _C_ERROR)
            return
        wizard.values.pop("MUMBLE_FCM_CREDENTIALS_BASE64", None)
        encoded = wizard.maybe_encode_fcm()
        if encoded:
            dpg.set_value(input_ids["MUMBLE_FCM_CREDENTIALS_BASE64"], encoded)
            _set_status(
                f"Encoded {p.name} ({len(encoded)} chars). "
                "Treat it like a password - do not share it.",
                _C_SUCCESS,
            )

    def _start_clone(dest_dir: str) -> None:
        # Read current repo/branch from widgets (user may not have navigated
        # to that step yet, so fall back to wizard.existing).
        repo_tag = input_ids.get("MUMBLE_GIT_REPO")
        branch_tag = input_ids.get("MUMBLE_GIT_BRANCH")
        repo = str(dpg.get_value(repo_tag) if repo_tag else "").strip() or \
               wizard.existing.get("MUMBLE_GIT_REPO", "")
        branch = str(dpg.get_value(branch_tag) if branch_tag else "").strip() or \
                 wizard.existing.get("MUMBLE_GIT_BRANCH", "")
        if not repo:
            _set_status("Set MUMBLE_GIT_REPO before cloning.", _C_ERROR)
            return
        repo_name = repo.rstrip("/").rsplit("/", 1)[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]
        clone_dest = Path(dest_dir) / repo_name
        _set_status(f"Cloning {repo} ...", _C_WARN)
        dpg.configure_item(ref["next"], enabled=False)
        dpg.configure_item(ref["back"], enabled=False)

        def _run() -> None:
            cmd = ["git", "clone"]
            if branch:
                cmd += ["--branch", branch]
            cmd += [repo, str(clone_dest)]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True)
            except FileNotFoundError:
                _set_status("git not found on PATH.", _C_ERROR)
                dpg.configure_item(ref["next"], enabled=True)
                dpg.configure_item(ref["back"], enabled=(state["step"] > 0))
                return
            dpg.configure_item(ref["next"], enabled=True)
            dpg.configure_item(ref["back"], enabled=(state["step"] > 0))
            if result.returncode == 0:
                src_tag = input_ids.get("MUMBLE_SRC")
                if src_tag is not None:
                    dpg.set_value(src_tag, str(clone_dest))
                # Pre-fill the upstream step widgets so the user sees what was used.
                repo_tag2 = input_ids.get("MUMBLE_GIT_REPO")
                if repo_tag2 is not None and repo:
                    dpg.set_value(repo_tag2, repo)
                branch_tag2 = input_ids.get("MUMBLE_GIT_BRANCH")
                if branch_tag2 is not None and branch:
                    dpg.set_value(branch_tag2, branch)
                _set_status(
                    f"Cloned to {clone_dest} - MUMBLE_SRC updated. "
                    "Upstream step pre-filled.",
                    _C_SUCCESS,
                )
            else:
                err = (result.stderr or result.stdout or "").strip().split("\n")[0]
                _set_status(f"Clone failed: {err}", _C_ERROR)

        threading.Thread(target=_run, daemon=True).start()

    def _on_clone_click() -> None:
        _browse_async(
            directory=True,
            title="Choose parent directory for clone",
            on_result=_start_clone,
        )

    # ── DearPyGui context & theme ─────────────────────────────────────────────

    dpg.create_context()

    font_path = _pick_font()
    if font_path is not None:
        with dpg.font_registry():
            with dpg.font(str(font_path), 17) as default_font:
                dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
        dpg.bind_font(default_font)

    with dpg.theme() as global_theme:
        with dpg.theme_component(dpg.mvAll):
            dpg.add_theme_color(dpg.mvThemeCol_WindowBg,       ( 26,  26,  34))
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg,        ( 34,  34,  44))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBg,        ( 46,  46,  60))
            dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered,  ( 58,  58,  76))
            dpg.add_theme_color(dpg.mvThemeCol_Button,         ( 50,  95, 165))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,  ( 70, 125, 210))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,   ( 38,  72, 130))
            dpg.add_theme_color(dpg.mvThemeCol_Header,         ( 50,  95, 165))
            dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered,  ( 70, 125, 210))
            dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg,    ( 20,  20,  28))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding,   6)
            dpg.add_theme_style(dpg.mvStyleVar_WindowRounding,  8)
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding,   6)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding,  18, 16)
            dpg.add_theme_style(dpg.mvStyleVar_FramePadding,    8,  5)
            dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing,    10,  8)
            dpg.add_theme_style(dpg.mvStyleVar_ScrollbarSize,  12)
    dpg.bind_theme(global_theme)

    # ── Primary window ────────────────────────────────────────────────────────

    with dpg.window(tag="primary", no_title_bar=True, no_move=True,
                    no_resize=True, no_scrollbar=True):

        # Banner
        dpg.add_text("  mumble-docker  |  Setup Wizard", color=list(_C_ACCENT))
        dpg.add_text(f"  Output file: {output}", color=list(_C_DIM))
        dpg.add_separator()
        dpg.add_spacer(height=6)

        # Step indicator - numbered dots separated by thin lines
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=2)
            for i, section in enumerate(sections):
                dot_tag = f"dot_{i}"
                color = list(_C_ACCENT) if i == 0 else list(_C_DIM)
                dpg.add_text(str(i + 1), color=color, tag=dot_tag)
                dot_tags.append(dot_tag)
                if i < n_steps - 1:
                    dpg.add_text(" - ", color=list(_C_SEP))

        dpg.add_spacer(height=8)

        # Step title + description
        ref["title"] = dpg.add_text(
            f"Step 1 of {n_steps} - {sections[0].title}",
            color=list(_C_LABEL),
        )
        ref["desc"] = dpg.add_text(
            sections[0].description or "",
            color=list(_C_DIM), wrap=840,
        )
        dpg.configure_item(ref["desc"], show=bool(sections[0].description))
        dpg.add_spacer(height=4)
        dpg.add_separator()
        dpg.add_spacer(height=4)

        # Step panels (child windows - only one visible at a time)
        # height=-130 fills all remaining space minus ~130 px for the footer,
        # so the nav bar + status line are always visible (sticky footer).
        for i, section in enumerate(sections):
            with dpg.child_window(
                height=-130,
                border=False,
                show=(i == 0),
                tag=f"panel_{i}",
            ):
                for setting in section.settings:
                    _add_setting_row(dpg, setting, input_ids, path_settings,
                                     _on_generate_password, _on_encode_fcm,
                                     _on_clone_click)

        dpg.add_spacer(height=6)
        dpg.add_separator()
        dpg.add_spacer(height=6)

        # Navigation bar
        with dpg.group(horizontal=True):
            ref["back"] = dpg.add_button(
                label="< Back", callback=_on_back, width=110, enabled=False,
            )
            dpg.add_spacer(width=6)
            ref["next"] = dpg.add_button(
                label="Next >", callback=_on_next, width=120,
            )
            dpg.add_spacer(width=16)
            dpg.add_button(
                label="Cancel", callback=dpg.stop_dearpygui, width=90,
            )

        dpg.add_spacer(height=6)
        ref["status"] = dpg.add_text("", wrap=860, color=list(_C_DIM))

    # ── Viewport ──────────────────────────────────────────────────────────────

    dpg.create_viewport(
        title="mumble-docker Setup Wizard",
        width=920, height=660,
        resizable=True,
    )
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("primary", True)
    dpg.start_dearpygui()
    dpg.destroy_context()
    return 0


# ── Per-setting row ───────────────────────────────────────────────────────────

def _add_setting_row(
    dpg,
    setting: Setting,
    input_ids: dict[str, int | str],
    path_settings: dict[str, bool],
    on_generate_password,
    on_encode_fcm,
    on_clone,
) -> None:
    with dpg.group():
        dpg.add_text(setting.label, color=list(_C_LABEL))
        if setting.help_text:
            dpg.add_text(
                setting.help_text.replace("\n", " "),
                color=list(_C_DIM), wrap=840, indent=14,
            )
        is_path = setting.key in path_settings
        # MUMBLE_SRC has two buttons (Browse + Clone) so it needs a shorter input.
        if setting.key == "MUMBLE_SRC":
            input_width = 490
        elif (is_path
              or setting.key == "MUMBLE_SUPERUSER_PASSWORD"
              or setting.key == "MUMBLE_FCM_CREDENTIALS_BASE64"):
            input_width = 620
        else:
            input_width = 820
        with dpg.group(horizontal=True):
            tag = dpg.add_input_text(
                default_value=setting.default,
                password=setting.secret,
                hint=setting.key,
                width=input_width,
            )
            input_ids[setting.key] = tag

            if setting.key == "MUMBLE_SRC":
                # Directory picker + one-click clone side by side.
                dpg.add_button(
                    label="Browse...",
                    user_data=setting.key,
                    callback=lambda _s, _a, u: _browse_async(
                        directory=True,
                        title="Select mumble-server source directory",
                        on_result=lambda p, k=u: dpg.set_value(input_ids[k], p),
                    ),
                )
                dpg.add_button(label="Clone...", callback=on_clone)
            elif is_path:
                _is_dir = path_settings[setting.key]
                _title = ("Select directory" if _is_dir else "Select file")
                _ftypes: list[tuple[str, str]] | None = None
                if "CREDENTIALS" in setting.key:
                    _ftypes = [("JSON key file", "*.json"), ("All files", "*.*")]
                elif setting.key.endswith("INI"):
                    _ftypes = [("INI config", "*.ini"), ("All files", "*.*")]
                dpg.add_button(
                    label="Browse folder..." if _is_dir else "Browse file...",
                    user_data=(setting.key, _is_dir, _title, _ftypes),
                    callback=lambda _s, _a, u: _browse_async(
                        directory=u[1],
                        title=u[2],
                        filetypes=u[3],
                        on_result=lambda p, k=u[0]: dpg.set_value(input_ids[k], p),
                    ),
                )
            elif setting.key == "MUMBLE_SUPERUSER_PASSWORD":
                dpg.add_button(label="Generate", callback=on_generate_password)
            elif setting.key == "MUMBLE_FCM_CREDENTIALS_BASE64":
                dpg.add_button(label="Encode from path above",
                               callback=on_encode_fcm)
        dpg.add_spacer(height=6)
