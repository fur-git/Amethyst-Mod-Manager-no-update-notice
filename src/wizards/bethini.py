"""
bethini.py
Wizard for running BethINI Pie.

Supported games: Fallout 4, Fallout New Vegas, Skyrim Special Edition, Starfield.

Workflow
--------
1. Prompt the user to download BethINI Pie from Nexus Mods (manual download only).
2. Auto-detect and extract the archive to Profiles/<game>/Applications/BethINI Pie/.
3. Pick the Proton version / prefix placement (same step every other wizard
   uses, via ProtonPrefixStepMixin).
4. Run BethINI Pie.exe via Proton.
"""

from __future__ import annotations

import shutil
import subprocess
from Utils.steam_finder import proton_run_command
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from Utils.xdg import open_url
from Utils.portal_filechooser import pick_file

if TYPE_CHECKING:
    from Games.base_game import BaseGame

from gui.theme import (
    ACCENT, ACCENT_HOV, BG_DEEP, BG_HEADER, BG_PANEL,
    TEXT_ON_ACCENT,
    TEXT_DIM, TEXT_MAIN,
    FONT_NORMAL, FONT_BOLD,
)
from wizards._proton_prefix import (
    ProtonPrefixStepMixin, shutdown_prefix_wineserver, PREFIX_MODE_GAME,
)

_NEXUS_URL = "https://www.nexusmods.com/site/mods/631?tab=files"
_EXE_NAME  = "Bethini.exe"
_APP_DIR   = "BethINI Pie"


def _get_applications_dir(game: "BaseGame") -> Path:
    return game.get_mod_staging_path().parent / "Applications" / _APP_DIR


def _bethini_exe_path(game: "BaseGame") -> Path | None:
    p = _get_applications_dir(game) / _EXE_NAME
    return p if p.is_file() else None


def _find_archive(downloads_dir: Path) -> Path | None:
    if not downloads_dir.is_dir():
        return None
    candidates = [
        p for p in downloads_dir.iterdir()
        if p.is_file()
        and p.suffix.lower() in {".zip", ".7z", ".rar"}
        and "bethini" in p.name.lower()
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _flatten_subdirs(dest: Path, exe_name: str) -> None:
    while True:
        all_entries = [e for e in dest.iterdir() if e.name != "__MACOSX"]
        subdirs = [e for e in all_entries if e.is_dir()]
        if len(subdirs) == 1 and not (dest / exe_name).is_file():
            wrapper = subdirs[0]
            tmp = dest.parent / (dest.name + "_flatten_tmp")
            wrapper.rename(tmp)
            for item in tmp.iterdir():
                shutil.move(str(item), str(dest / item.name))
            tmp.rmdir()
        else:
            break


class BethINIWizard(ProtonPrefixStepMixin, ctk.CTkFrame):
    """Step-by-step wizard to set up and run BethINI Pie."""

    _tool_exe_name      = _EXE_NAME
    _tool_display_name  = "BethINI Pie"
    _proton_step_title  = "Step 4: Choose Proton Version"
    _proton_deps_note   = "Each version gets its own prefix."
    _exe_missing_text   = (
        f"{_EXE_NAME!r} was not found.\n\n"
        "Reopen this wizard and install BethINI Pie first."
    )

    def _proton_next_step(self):
        self._show_step_run()

    def __init__(
        self,
        parent,
        game: "BaseGame",
        log_fn=None,
        *,
        on_close=None,
        **_kwargs,
    ):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self._on_close_cb = on_close or (lambda: None)
        self._game        = game
        self._log         = log_fn or (lambda msg: None)
        self._archive_path: Path | None = None
        self._exe         = _bethini_exe_path(game)
        self._proton_name = ""

        title_bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=40)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar,
            text=f"Run BethINI Pie \u2014 {game.name}",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            title_bar, text="\u2715", width=32, height=32, font=FONT_BOLD,
            fg_color="transparent", hover_color=BG_PANEL, text_color=TEXT_MAIN,
            command=self._on_close_cb,
        ).pack(side="right", padx=4, pady=4)

        self._body = ctk.CTkFrame(self, fg_color=BG_DEEP)
        self._body.pack(fill="both", expand=True, padx=20, pady=20)

        self._show_step_download()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _clear_body(self):
        for w in self._body.winfo_children():
            w.destroy()

    def _set_label(self, attr: str, text: str, color: str = TEXT_DIM):
        def _apply(t=text, c=color):
            try:
                widget = getattr(self, attr, None)
                if widget is not None and widget.winfo_exists():
                    widget.configure(text=t, text_color=c)
            except Exception:
                pass
        self.after(0, _apply)

    def _on_done(self):
        try:
            topbar = self.winfo_toplevel()._topbar
        except Exception:
            topbar = None
        self._on_close_cb()
        if topbar is not None:
            try:
                topbar.after(0, topbar._reload_mod_panel)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Step 1 — Download (skipped if already extracted)
    # ------------------------------------------------------------------

    def _show_step_download(self):
        if _bethini_exe_path(self._game) is not None:
            self._show_step_proton()
            return

        self._clear_body()

        ctk.CTkLabel(
            self._body, text="Step 1: Download BethINI Pie",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        ctk.CTkLabel(
            self._body,
            text=(
                "Click the button below to open the BethINI Pie page on Nexus Mods.\n\n"
                "Download the archive manually (do NOT use the Mod Manager\n"
                "download button), then click Next."
            ),
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center",
        ).pack(pady=(0, 16))

        ctk.CTkButton(
            self._body, text="Open Download Page", width=220, height=36,
            font=FONT_BOLD,
            fg_color="#da8e35", hover_color="#e5a04a", text_color="white",
            command=lambda: open_url(_NEXUS_URL),
        ).pack(pady=(0, 20))

        ctk.CTkButton(
            self._body, text="Next \u2192", width=120, height=36,
            font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._show_step_locate,
        ).pack(side="bottom")

    # ------------------------------------------------------------------
    # Step 2 — Locate archive
    # ------------------------------------------------------------------

    def _show_step_locate(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text="Step 2: Locate the Archive",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        self._locate_status = ctk.CTkLabel(
            self._body, text="Searching Downloads folder\u2026",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        )
        self._locate_status.pack(pady=(0, 12))

        btn_frame = ctk.CTkFrame(self._body, fg_color="transparent")
        btn_frame.pack(side="bottom", pady=(8, 0))

        ctk.CTkButton(
            btn_frame, text="Try Again", width=100, height=36,
            font=FONT_BOLD,
            fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
            command=self._scan_downloads,
        ).pack(side="right", padx=(8, 0))

        ctk.CTkButton(
            btn_frame, text="Browse\u2026", width=100, height=36,
            font=FONT_BOLD,
            fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
            command=self._browse_archive,
        ).pack(side="right")

        self._scan_downloads()

    def _scan_downloads(self):
        found = _find_archive(Path.home() / "Downloads")
        if found:
            self._archive_path = found
            self._locate_status.configure(text=f"Found: {found.name}", text_color="#6bc76b")
            self.after(300, self._show_step_extract)
        else:
            self._archive_path = None
            self._locate_status.configure(
                text=(
                    "BethINI Pie archive not found in Downloads.\n"
                    "Make sure you downloaded it, then press Try Again,\n"
                    "or use Browse to select it manually."
                ),
                text_color="#e06c6c",
            )

    def _browse_archive(self):
        def _on_picked(path: Path | None) -> None:
            if path and path.is_file():
                self._archive_path = path
                self._locate_status.configure(text=f"Selected: {path.name}", text_color="#6bc76b")
                self.after(300, self._show_step_extract)

        pick_file("Select the BethINI Pie archive", lambda p: self.after(0, lambda: _on_picked(p)))

    # ------------------------------------------------------------------
    # Step 3 — Extract
    # ------------------------------------------------------------------

    def _show_step_extract(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text="Step 3: Extract BethINI Pie",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        self._extract_status = ctk.CTkLabel(
            self._body, text="Extracting\u2026",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        )
        self._extract_status.pack(pady=(0, 16))

        threading.Thread(target=self._do_extract, daemon=True).start()

    def _do_extract(self):
        try:
            from wizards.script_extender import _extract_archive

            archive = self._archive_path
            if archive is None or not archive.is_file():
                raise RuntimeError("Archive not found.")

            dest = _get_applications_dir(self._game)
            dest.mkdir(parents=True, exist_ok=True)

            self._set_label("_extract_status", f"Extracting {archive.name}\u2026")
            self._log(f"BethINI Wizard: extracting {archive.name} \u2192 {dest}")

            paths = _extract_archive(archive, dest)
            file_count = len([p for p in paths if p.is_file()])
            self._log(f"BethINI Wizard: extracted {file_count} file(s).")

            _flatten_subdirs(dest, _EXE_NAME)

            if not (dest / _EXE_NAME).is_file():
                raise RuntimeError(
                    f"{_EXE_NAME!r} not found after extraction.\n"
                    f"Check that the archive contains {_EXE_NAME!r}."
                )

            self._exe = _bethini_exe_path(self._game)
            self._set_label("_extract_status", f"Extracted {file_count} file(s).", color="#6bc76b")
            self.after(0, self._show_step_proton)

        except Exception as exc:
            self._set_label("_extract_status", f"Error: {exc}", color="#e06c6c")
            self._log(f"BethINI Wizard: extract error: {exc}")

    # ------------------------------------------------------------------
    # Step 5 — Run BethINI Pie
    # ------------------------------------------------------------------

    def _show_step_run(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text="Step 5: Run BethINI Pie",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        exe = _bethini_exe_path(self._game)
        if exe is None:
            ctk.CTkLabel(
                self._body,
                text=(
                    f"{_EXE_NAME!r} was not found.\n"
                    "Please restart the wizard and install BethINI Pie first."
                ),
                font=FONT_NORMAL, text_color="#e06c6c", justify="center",
            ).pack(pady=(0, 16))
            ctk.CTkButton(
                self._body, text="Close", width=120, height=36,
                font=FONT_BOLD,
                fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
                command=self._on_close_cb,
            ).pack(side="bottom")
            return

        self._run_status = ctk.CTkLabel(
            self._body, text="Launching BethINI Pie\u2026",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        )
        self._run_status.pack(pady=(0, 12))

        self._done_btn = ctk.CTkButton(
            self._body, text="Done", width=120, height=36,
            font=FONT_BOLD,
            fg_color="#2d7a2d", hover_color="#3a9e3a", text_color="white",
            command=self._on_done, state="disabled",
        )
        self._done_btn.pack(side="bottom")

        threading.Thread(target=lambda: self._do_run(exe), daemon=True).start()

    def _do_run(self, exe: Path):
        self._set_label("_run_status", "Preparing BethINI Pie's Wine prefix…")
        proton_script, env, compat_data = self._get_tool_env()
        if proton_script is None:
            self._set_label(
                "_run_status",
                f"Could not find Proton '{self._proton_name}' — "
                "check that it is installed in Steam.",
                color="#e06c6c",
            )
            return

        # On an isolated/shared prefix, seed the Bethesda registry key and link
        # the game's My Games folder so BethINI can locate the game and edit the
        # same INIs the game uses. (No-op when running in the game's own prefix.)
        if self._prefix_mode != PREFIX_MODE_GAME:
            try:
                from Utils.bethesda_registry import maybe_register_for_game
                maybe_register_for_game(
                    prefix_dir=compat_data,
                    proton_script=Path(proton_script),
                    env=env,
                    game=self._game,
                    log_fn=self._log,
                )
            except Exception as exc:
                self._log(f"BethINI Wizard: registry write skipped: {exc}")
            self._link_mygames(compat_data / "pfx")
            self._link_plugins_txt(compat_data / "pfx")

        self._log(f"BethINI Wizard: launching {exe} via Proton")
        try:
            proc = subprocess.Popen(
                proton_run_command(proton_script, "run", str(exe)),
                env=env,
                cwd=str(exe.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._set_label(
                "_run_status",
                "BethINI Pie is running.\nConfigure your INI settings, then close it and click Done.",
                color="#6bc76b",
            )
            self.after(0, lambda: self._done_btn.configure(state="normal"))
            proc.wait()
            shutdown_prefix_wineserver(
                proton_script, compat_data,
                log_fn=lambda m: self._log(f"BethINI Wizard: {m}"),
            )
            self._log("BethINI Wizard: BethINI Pie closed.")
            self._set_label("_run_status", "BethINI Pie finished.", color="#6bc76b")
            self.after(0, self._on_done)
        except Exception as exc:
            self._set_label("_run_status", f"Launch error: {exc}", color="#e06c6c")
            self._log(f"BethINI Wizard: launch error: {exc}")
