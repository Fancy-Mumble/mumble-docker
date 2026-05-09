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

def run_gui(output: Path, *, easy: bool = False) -> int:
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

    # `active_steps` is the subset of section indices the stepper walks
    # through.  In full mode it's every section; in easy mode it's just
    # the essential ones.  Non-essential sections are still part of the
    # save loop — their widget defaults end up in the .env unchanged.
    state: dict = {
        "step": 0,
        "easy": easy,
        # Recomputed before every navigation by `_compute_active_steps`
        # so toggling a feature mid-wizard pulls its dependent section
        # back into the flow (e.g. enabling FCM in easy mode resurfaces
        # the FCM credentials section).
        "active_steps": [],
        "dest_path": output,
    }
    input_ids: dict[str, int | str] = {}

    # Tags assigned during window construction; filled by reference capture.
    dot_tags: list[str] = []
    sep_tags: list[str] = []  # one per gap between dots; len == n_steps - 1
    ref: dict[str, int | str] = {
        "title": 0, "desc": 0, "back": 0, "next": 0, "status": 0,
        "save_as": 0, "dest_label": 0,
    }

    # Determine which settings are path-type and whether directory or file.
    path_settings: dict[str, bool] = {}   # key -> is_directory
    for section in sections:
        for setting in section.settings:
            if setting.validator is validate_path_exists_optional:
                path_settings[setting.key] = (setting.key == "MUMBLE_SRC")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _depends_met(setting) -> bool:
        if setting.depends_on is None:
            return True
        dep_key, expected = setting.depends_on
        dep_tag = input_ids.get(dep_key)
        if dep_tag is not None:
            raw = dpg.get_value(dep_tag)
            actual = "true" if isinstance(raw, bool) and raw else \
                     "false" if isinstance(raw, bool) else str(raw or "")
        else:
            actual = wizard.existing.get(dep_key, "")
        return actual.strip().lower() == expected.lower()

    def _compute_active_steps() -> list[int]:
        """Return section indices to navigate through.

        Full mode: every section.  Easy mode: essential sections plus
        any non-essential section that has at least one currently-
        relevant dependent setting (e.g. FCM credentials become
        relevant — and thus mandatory to ask for — once the user
        toggles ``MUMBLE_CONFIG_PUSHENABLED`` on).
        """
        out: list[int] = []
        for i, sec in enumerate(sections):
            if not state["easy"] or sec.essential:
                out.append(i)
                continue
            for setting in sec.settings:
                if setting.depends_on is not None and _depends_met(setting):
                    out.append(i)
                    break
        return out

    def _refresh_visibility(idx: int) -> None:
        for setting in sections[idx].settings:
            row_tag = f"row_{setting.key}"
            if dpg.does_item_exist(row_tag):
                dpg.configure_item(row_tag, show=_depends_met(setting))

    def _collect(idx: int) -> None:
        for setting in sections[idx].settings:
            if not _depends_met(setting):
                wizard.values.pop(setting.key, None)
                continue
            tag = input_ids.get(setting.key)
            if tag is None:
                continue
            raw = dpg.get_value(tag)
            if setting.kind == "bool":
                value = "true" if bool(raw) else "false"
            else:
                value = str(raw or "").strip()
            wizard.set_value(setting.key, value,
                             skip_if_empty=setting.skip_if_empty)

    def _validate(idx: int) -> list[str]:
        errors: list[str] = []
        for setting in sections[idx].settings:
            if not _depends_met(setting):
                continue
            err = setting.validator(wizard.values.get(setting.key, ""))
            if err:
                errors.append(f"{setting.label}: {err}")
        return errors

    def _set_status(msg: str, color=_C_DIM) -> None:
        dpg.configure_item(ref["status"], default_value=msg,
                           color=list(color))

    def _refresh_indicator(step: int) -> None:
        active = state["active_steps"]
        active_set = set(active)
        cur_section_idx = active[step]
        # All dots / separators stay visible so the user can see which
        # sections are being skipped — inactive ones are just dimmed.
        for i, tag in enumerate(dot_tags):
            dpg.configure_item(tag, show=True)
            if i not in active_set:
                # Skipped (easy mode): use the very dim "separator" colour
                # so it reads as inactive without disappearing.
                dpg.configure_item(tag, color=list(_C_SEP))
                continue
            pos = active.index(i)
            if pos < step:
                color = list(_C_DONE)
            elif pos == step:
                color = list(_C_ACCENT)
            else:
                color = list(_C_DIM)
            dpg.configure_item(tag, color=color)
        for sep_tag in sep_tags:
            dpg.configure_item(sep_tag, show=True)
        n_active = len(active)
        dpg.set_value(ref["title"],
                      f"Step {step + 1} of {n_active} - "
                      f"{sections[cur_section_idx].title}")
        desc = sections[cur_section_idx].description or ""
        dpg.set_value(ref["desc"], desc)
        dpg.configure_item(ref["desc"], show=bool(desc))

    def _go_to(new_step: int) -> None:
        active = state["active_steps"]
        cur_section_idx = active[state["step"]]
        new_section_idx = active[new_step]
        dpg.configure_item(f"panel_{cur_section_idx}", show=False)
        state["step"] = new_step
        _refresh_visibility(new_section_idx)
        dpg.configure_item(f"panel_{new_section_idx}", show=True)
        dpg.configure_item(ref["back"], enabled=(new_step > 0))
        is_last = (new_step == len(active) - 1)
        dpg.configure_item(ref["next"], label="Save .env" if is_last else "Next >")
        _refresh_indicator(new_step)
        _set_status("")

    def _resync_step_after_recompute(prev_section_idx: int) -> None:
        active = state["active_steps"]
        if prev_section_idx in active:
            state["step"] = active.index(prev_section_idx)
        else:
            # Previously-active section is no longer included — pin to 0
            # so the wizard stays in a consistent state.  In practice this
            # only happens if the user goes back and toggles off a feature
            # whose section they were on, which the dependency rules of
            # `_compute_active_steps` make impossible.
            state["step"] = 0

    # Initial active_steps — uses wizard.existing values for dependency
    # checks since widgets don't exist yet at this point.
    state["active_steps"] = _compute_active_steps()

    def _on_back() -> None:
        cur_section_idx = state["active_steps"][state["step"]]
        _collect(cur_section_idx)
        state["active_steps"] = _compute_active_steps()
        _resync_step_after_recompute(cur_section_idx)
        if state["step"] > 0:
            _go_to(state["step"] - 1)

    def _on_next() -> None:
        cur_section_idx = state["active_steps"][state["step"]]
        _collect(cur_section_idx)
        errors = _validate(cur_section_idx)
        if errors:
            _set_status("Please fix: " + "  |  ".join(errors), _C_ERROR)
            return
        state["active_steps"] = _compute_active_steps()
        _resync_step_after_recompute(cur_section_idx)
        if state["step"] == len(state["active_steps"]) - 1:
            _do_save()
        else:
            _go_to(state["step"] + 1)

    def _write_env_at(path: Path) -> bool:
        """Persist current values to ``path``.  Returns True on success."""
        wizard.output = path
        try:
            patched_ini = wizard.save()
        except OSError as e:
            _set_status(f"Failed to write {path}: {e}", _C_ERROR)
            return False
        dpg.configure_item(ref["next"], label="Close")
        dpg.configure_item(ref["next"], callback=dpg.stop_dearpygui)
        if patched_ini is not None:
            _set_status(
                f"Saved to {path}.  Feature toggles also synced into "
                f"{patched_ini}.  You can close this window.",
                _C_SUCCESS,
            )
        else:
            _set_status(f"Saved to {path} - you can close this window.",
                        _C_SUCCESS)
        return True

    def _do_save(*, force: bool = False) -> None:
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
        dest: Path = state["dest_path"]
        # Don't silently overwrite a config the user didn't explicitly load.
        if (not force
                and dest.exists()
                and dest != wizard.source):
            _show_overwrite_confirm(dest)
            return
        _write_env_at(dest)

    def _show_overwrite_confirm(dest: Path) -> None:
        if dpg.does_item_exist("overwrite_modal"):
            dpg.delete_item("overwrite_modal")
        with dpg.window(label="Overwrite existing file?",
                        tag="overwrite_modal",
                        modal=True, no_close=True,
                        width=520, no_resize=True,
                        pos=[200, 220]):
            dpg.add_text(f"{dest}", color=list(_C_WARN))
            dpg.add_text("already exists and was not loaded as the source.",
                         color=list(_C_DIM))
            dpg.add_text("Overwriting will replace its contents.",
                         color=list(_C_DIM))
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Overwrite", width=120,
                               callback=lambda: (
                                   dpg.configure_item("overwrite_modal", show=False),
                                   _do_save(force=True),
                               ))
                dpg.add_button(label="Save as...", width=120,
                               callback=lambda: (
                                   dpg.configure_item("overwrite_modal", show=False),
                                   _on_save_as(),
                               ))
                dpg.add_button(label="Cancel", width=90,
                               callback=lambda: dpg.configure_item(
                                   "overwrite_modal", show=False))

    def _on_save_as() -> None:
        def _picked(p: str) -> None:
            new_path = Path(p)
            state["dest_path"] = new_path
            dpg.set_value(ref["dest_label"],
                          f"  Output file: {new_path}")
            _do_save()
        _browse_async(
            directory=False,
            title="Save .env as...",
            filetypes=[("Env files", "*.env"), ("All files", "*.*")],
            on_result=_picked,
        )

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
        ref["dest_label"] = dpg.add_text(
            f"  Output file: {output}", color=list(_C_DIM),
        )
        dpg.add_separator()
        dpg.add_spacer(height=6)

        # Step indicator - numbered dots separated by thin lines.
        # Dots / separators for non-active sections are hidden at runtime
        # by `_refresh_indicator`, so easy mode doesn't show empty slots.
        with dpg.group(horizontal=True):
            dpg.add_spacer(width=2)
            for i, section in enumerate(sections):
                dot_tag = f"dot_{i}"
                color = list(_C_ACCENT) if i == 0 else list(_C_DIM)
                dpg.add_text(str(i + 1), color=color, tag=dot_tag)
                dot_tags.append(dot_tag)
                if i < n_steps - 1:
                    sep_tag = f"sep_{i}"
                    dpg.add_text(" - ", color=list(_C_SEP), tag=sep_tag)
                    sep_tags.append(sep_tag)

        dpg.add_spacer(height=8)

        # Step title + description (first active step's content).
        first_idx = state["active_steps"][0]
        n_active = len(state["active_steps"])
        ref["title"] = dpg.add_text(
            f"Step 1 of {n_active} - {sections[first_idx].title}",
            color=list(_C_LABEL),
        )
        ref["desc"] = dpg.add_text(
            sections[first_idx].description or "",
            color=list(_C_DIM), wrap=840,
        )
        dpg.configure_item(ref["desc"], show=bool(sections[first_idx].description))
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
                show=(i == first_idx),
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
            ref["save_as"] = dpg.add_button(
                label="Save as...", callback=_on_save_as, width=110,
            )
            dpg.add_spacer(width=6)
            dpg.add_button(
                label="Cancel", callback=dpg.stop_dearpygui, width=90,
            )

        dpg.add_spacer(height=6)
        ref["status"] = dpg.add_text("", wrap=860, color=list(_C_DIM))

    # ── Startup config selector ──────────────────────────────────────────────

    def _apply_widget_defaults_from_wizard() -> None:
        """Push current `wizard.sections` defaults back into the widgets.

        Called after the user picks a different source in the startup
        dialog — `wizard.reload(...)` rebuilds sections with the new
        existing-values map, which we then mirror into the live UI.
        """
        for sec in wizard.sections:
            for setting in sec.settings:
                tag = input_ids.get(setting.key)
                if tag is None:
                    continue
                if setting.kind == "bool":
                    dpg.set_value(tag,
                                  setting.default.strip().lower() == "true")
                else:
                    dpg.set_value(tag, setting.default)

    def _enter_wizard(*, easy_mode: bool, dest: Path) -> None:
        """Finalise the startup choice and hand control to the stepper."""
        state["easy"] = easy_mode
        state["dest_path"] = dest
        state["active_steps"] = _compute_active_steps()
        state["step"] = 0
        first_idx_now = state["active_steps"][0]
        # Show only the first active panel; hide everything else (the
        # initial display may have shown a different panel before reload).
        for i in range(n_steps):
            dpg.configure_item(f"panel_{i}", show=(i == first_idx_now))
        dpg.set_value(ref["dest_label"], f"  Output file: {dest}")
        dpg.configure_item(ref["back"], enabled=False)
        is_only = (len(state["active_steps"]) == 1)
        dpg.configure_item(ref["next"],
                           label="Save .env" if is_only else "Next >",
                           callback=_on_next)
        _refresh_indicator(0)
        _refresh_visibility(first_idx_now)
        dpg.configure_item("startup_dlg", show=False)

    def _startup_quick() -> None:
        # Quick start: keep whatever auto-loaded from `output` (so re-runs
        # don't lose values), enable easy mode, save back to `output`.
        _enter_wizard(easy_mode=True, dest=output)

    def _startup_fresh() -> None:
        wizard.reload(None)
        _apply_widget_defaults_from_wizard()
        _enter_wizard(easy_mode=False, dest=output)

    def _startup_edit() -> None:
        def _picked(p: str) -> None:
            picked = Path(p)
            wizard.reload(picked)
            _apply_widget_defaults_from_wizard()
            _enter_wizard(easy_mode=False, dest=picked)
        _browse_async(
            directory=False,
            title="Pick an existing .env to edit",
            filetypes=[("Env files", "*.env"), ("All files", "*.*")],
            on_result=_picked,
        )

    with dpg.window(label="Configure mumble-docker",
                    tag="startup_dlg",
                    modal=True, no_close=True,
                    no_resize=True,
                    width=600, height=440,
                    pos=[180, 110]):
        dpg.add_text("How do you want to set up your mumble-docker config?",
                     color=list(_C_LABEL))
        dpg.add_text(f"Default save location: {output}", color=list(_C_DIM))
        dpg.add_separator()
        dpg.add_spacer(height=8)

        dpg.add_button(label="  Quick start (essentials only)  ",
                       width=-1, height=42, callback=_startup_quick)
        dpg.add_text("  Pick features + admin password.  Defaults for "
                     "everything else.\n  Keeps any values already in the "
                     f"project .env.",
                     color=list(_C_DIM), wrap=540)
        dpg.add_spacer(height=6)

        dpg.add_button(label="  Edit existing config (full options)  ",
                       width=-1, height=42, callback=_startup_edit)
        dpg.add_text("  Load a .env from disk and edit it in place.  "
                     "Saves back to the same file.",
                     color=list(_C_DIM), wrap=540)
        dpg.add_spacer(height=6)

        dpg.add_button(label="  Start from scratch (full options)  ",
                       width=-1, height=42, callback=_startup_fresh)
        dpg.add_text("  Ignore any existing .env and start with the wizard "
                     "defaults.  You'll be asked before overwriting an "
                     "existing config.",
                     color=list(_C_DIM), wrap=540)

    # ── Viewport ──────────────────────────────────────────────────────────────

    dpg.create_viewport(
        title="mumble-docker Setup Wizard",
        width=980, height=720,
        min_width=720, min_height=560,
        resizable=True,
    )
    dpg.setup_dearpygui()
    # Bring the indicator + dependency visibility in line with the active
    # step set before any user interaction (matters in easy mode, where
    # non-essential dots must be hidden from the start).
    _refresh_indicator(0)
    _refresh_visibility(state["active_steps"][0])
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
    with dpg.group(tag=f"row_{setting.key}"):
        if setting.kind == "bool":
            tag = dpg.add_checkbox(
                label=setting.label,
                default_value=setting.default.strip().lower() == "true",
            )
            input_ids[setting.key] = tag
            if setting.help_text:
                dpg.add_text(
                    setting.help_text.replace("\n", " "),
                    color=list(_C_DIM), wrap=840, indent=14,
                )
            dpg.add_spacer(height=6)
            return
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
