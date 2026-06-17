"""
eslifier.py
Wizard for running ESLifier (https://github.com/MaskPlague/ESLifier) with a
Skyrim Special Edition-family game.

ESLifier flags / compacts plugins so they fit in the light (ESL) load-order
space. It ships an MO2-integration mode that reads the load order straight from
the mod-staging folder, which maps cleanly onto this manager's layout — so no
deploy step is needed.

Workflow
--------
1. Download ESLifier.zip from the latest GitHub release and extract it to
   Profiles/<game>/Applications/ESLifier/ (skipped if already present).
2. User picks the Proton version; ESLifier gets its own isolated prefix
   (prefix_<ProtonName>/ next to the exe), independent of the game's Proton.
3. Write ESLifier_Data/settings.json next to the exe with MO2 mode enabled and
   every path pointed at the active profile's staging folders (mods/, overwrite/,
   plugins.txt, modlist.txt), then run ESLifier.exe via Proton.

Because ESLifier runs inside Wine, every path written into settings.json must be
a Wine (``Z:\\``) path — the app reads/walks those folders with plain Python
``os.walk`` / ``open`` from inside the prefix.

The ESLifier Output mod is written into the staging ``mods/`` folder (as the
"ESLifier Output" mod), so it shows up as an installable mod after the run.
"""

from __future__ import annotations

import json
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from gui.path_utils import _to_wine_path

if TYPE_CHECKING:
    from Games.base_game import BaseGame

from gui.theme import (
    ACCENT, ACCENT_HOV, BG_DEEP, BG_HEADER, BG_PANEL,
    TEXT_ON_ACCENT,
    TEXT_DIM, TEXT_MAIN,
    FONT_NORMAL, FONT_BOLD,
)

_GITHUB_API_URL = "https://api.github.com/repos/MaskPlague/ESLifier/releases/latest"
_EXE_NAME       = "ESLifier.exe"
_APP_DIR        = "ESLifier"
_OUTPUT_NAME    = "ESLifier Output"


def _get_applications_dir(game: "BaseGame") -> Path:
    return game.get_mod_staging_path().parent / "Applications" / _APP_DIR


def find_eslifier_exe(game: "BaseGame") -> Path | None:
    p = _get_applications_dir(game) / _EXE_NAME
    return p if p.is_file() else None


from wizards._proton_prefix import ProtonPrefixStepMixin, shutdown_prefix_wineserver


class ESLifierWizard(ProtonPrefixStepMixin, ctk.CTkFrame):
    """Step-by-step wizard to install and run ESLifier in MO2 mode."""

    _tool_exe_name     = _EXE_NAME
    _tool_display_name = "ESLifier"
    _proton_step_title = "Step 2: Choose Proton Version"
    _exe_missing_text  = (
        f"{_EXE_NAME} was not found.\n"
        "Please restart the wizard and let it install ESLifier first."
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
        self._exe         = find_eslifier_exe(game)
        self._proton_name = ""

        title_bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=40)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar,
            text=f"Run ESLifier — {game.name}",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            title_bar, text="✕", width=32, height=32, font=FONT_BOLD,
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
    # Step 1 — Download + extract ESLifier (skipped if already installed)
    # ------------------------------------------------------------------

    def _show_step_download(self):
        if find_eslifier_exe(self._game) is not None:
            self._show_step_proton()
            return

        self._clear_body()

        ctk.CTkLabel(
            self._body, text="Step 1: Install ESLifier",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        ctk.CTkLabel(
            self._body,
            text=(
                "ESLifier will be downloaded from GitHub and installed into this\n"
                "game's Applications folder.\n\n"
                "Click Install to begin."
            ),
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        ).pack(pady=(0, 16))

        self._download_status = ctk.CTkLabel(
            self._body, text="",
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        )
        self._download_status.pack(pady=(0, 8))

        self._install_btn = ctk.CTkButton(
            self._body, text="Install", width=160, height=36,
            font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._start_install,
        )
        self._install_btn.pack(side="bottom")

    def _start_install(self):
        try:
            self._install_btn.configure(state="disabled")
        except Exception:
            pass
        self._set_label("_download_status", "Contacting GitHub…")
        threading.Thread(target=self._do_install, daemon=True).start()

    def _do_install(self):
        import tempfile

        from wizards.script_extender import _extract_archive

        try:
            req = urllib.request.Request(
                _GITHUB_API_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "ModManager/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            tag = data.get("tag_name", "unknown")
            url = None
            for asset in data.get("assets", []):
                if asset.get("name", "").lower().endswith(".zip"):
                    url = asset["browser_download_url"]
                    break
            if not url:
                raise RuntimeError(
                    f"No .zip asset found in the latest ESLifier release ({tag})."
                )

            self._log(f"ESLifier Wizard: downloading ESLifier {tag} from {url}")
            self._set_label("_download_status", f"Downloading ESLifier {tag}…")

            tmp_dir = Path(tempfile.mkdtemp())
            archive = tmp_dir / "ESLifier.zip"
            try:
                urllib.request.urlretrieve(url, archive)

                dest = _get_applications_dir(self._game)
                dest.mkdir(parents=True, exist_ok=True)

                self._set_label("_download_status", "Extracting ESLifier…")
                self._log(f"ESLifier Wizard: extracting {archive.name} → {dest}")
                paths = _extract_archive(archive, dest)
                file_count = len([p for p in paths if p.is_file()])
                self._log(f"ESLifier Wizard: extracted {file_count} file(s).")
            finally:
                import shutil
                shutil.rmtree(tmp_dir, ignore_errors=True)

            exe = dest / _EXE_NAME
            if not exe.is_file():
                raise RuntimeError(
                    f"{_EXE_NAME} not found after extraction at {dest}."
                )
            self._exe = exe

            self._set_label("_download_status", "ESLifier installed.", color="#6bc76b")
            self._safe_after(400, self._show_step_proton)

        except Exception as exc:
            self._set_label("_download_status", f"Install error: {exc}", color="#e06c6c")
            self._log(f"ESLifier Wizard: install error: {exc}")
            def _reenable():
                try:
                    self._install_btn.configure(state="normal")
                except Exception:
                    pass
            self._safe_after(0, _reenable)

    # ------------------------------------------------------------------
    # Step 3 — Configure settings.json + run ESLifier
    # ------------------------------------------------------------------

    def _show_step_run(self):
        self._clear_body()

        ctk.CTkLabel(
            self._body, text="Step 3: Run ESLifier",
            font=FONT_BOLD, text_color=TEXT_MAIN,
        ).pack(pady=(0, 12))

        exe = self._exe
        if exe is None:
            ctk.CTkLabel(
                self._body,
                text=self._exe_missing_text,
                font=FONT_NORMAL, text_color="#e06c6c", justify="center",
            ).pack(pady=(0, 16))
            ctk.CTkButton(
                self._body, text="Close", width=120, height=36,
                font=FONT_BOLD,
                fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
                command=self._on_close_cb,
            ).pack(side="bottom")
            return

        ctk.CTkLabel(
            self._body,
            text=(
                "ESLifier runs in MO2 mode, reading your load order directly from\n"
                "the mod staging folder, so no deploy is required.\n\n"
                "When ESLifier finishes, it writes its output as the\n"
                f"'{_OUTPUT_NAME}' mod, which will appear in your mod list."
            ),
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="center", wraplength=460,
        ).pack(pady=(0, 12))

        self._run_status = ctk.CTkLabel(
            self._body, text="Launching ESLifier…",
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

    def _active_profile(self) -> str:
        try:
            return self.winfo_toplevel()._topbar._profile_var.get()
        except Exception:
            return self._game.get_last_deployed_profile() or "default"

    def _write_settings(self, exe: Path, pfx: Path) -> None:
        """Write/merge ESLifier_Data/settings.json next to the exe.

        All paths are stored as Wine (Z:\\) paths because ESLifier walks and
        opens them from inside the Proton prefix. Existing user-tweaked keys
        are preserved; only the path/mode keys we manage are overwritten.
        """
        game    = self._game
        profile = self._active_profile()

        game.set_active_profile_dir(
            game.get_profile_root() / "profiles" / profile
        )

        staging   = game.get_effective_mod_staging_path()
        overwrite = game.get_effective_overwrite_path()
        profile_dir = game.get_profile_root() / "profiles" / profile
        plugins_txt = profile_dir / "plugins.txt"
        modlist_txt = profile_dir / "modlist.txt"

        overwrite.mkdir(parents=True, exist_ok=True)

        settings_dir  = exe.parent / "ESLifier_Data"
        settings_file = settings_dir / "settings.json"
        settings_dir.mkdir(parents=True, exist_ok=True)

        # ESLifier walks every enabled mod's folder with os.walk + os.path.relpath.
        # Tool wizards that run a tool installed as a mod (Pandora, BodySlide, …)
        # leave an isolated Wine prefix (prefix_<ProtonName>/) inside that mod's
        # staging folder. Those prefixes contain dosdevices/com1..6 symlinks which
        # Wine reports as being on mount '\\.\com1' — relpath then crashes ESLifier
        # with "path is on mount '\\.\com1', start on mount 'Z:'". Point ESLifier
        # at a filtered copy of modlist.txt with such mods removed so it never
        # descends into them.
        modlist_for_eslifier = self._write_filtered_modlist(
            modlist_txt, staging, settings_dir / "modlist.txt"
        )

        existing: dict = {}
        if settings_file.is_file():
            try:
                existing = json.loads(settings_file.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    existing = {}
            except (OSError, ValueError):
                existing = {}

        existing.update({
            "mo2_mode": True,
            # In MO2 mode "skyrim_folder_path" is actually the MO2 mods folder.
            "skyrim_folder_path":   _to_wine_path(staging, pfx),
            "output_folder_path":   _to_wine_path(staging, pfx),
            "output_folder_name":   existing.get("output_folder_name") or _OUTPUT_NAME,
            "overwrite_path":       _to_wine_path(overwrite, pfx),
            "plugins_txt_path":     _to_wine_path(plugins_txt, pfx),
            "mo2_modlist_txt_path": _to_wine_path(modlist_for_eslifier, pfx),
        })

        settings_file.write_text(
            json.dumps(existing, ensure_ascii=False, indent=4),
            encoding="utf-8",
        )
        self._log(f"ESLifier Wizard: wrote settings → {settings_file}")
        self._log(f"  mods folder:  {staging}")
        self._log(f"  overwrite:    {overwrite}")
        self._log(f"  plugins.txt:  {plugins_txt}")
        self._log(f"  modlist.txt:  {modlist_for_eslifier}")
        if not plugins_txt.is_file():
            self._log(f"  WARN: plugins.txt not found at {plugins_txt}")

    def _write_filtered_modlist(
        self, modlist_txt: Path, staging: Path, dest: Path
    ) -> Path:
        """Write a copy of *modlist.txt* with enabled mods that contain a Wine
        prefix (``prefix_*/``) removed, and return *dest*.

        Returns the original ``modlist_txt`` unchanged if it can't be read.
        Lines are otherwise preserved verbatim so ESLifier sees the same load
        order, minus the mods that would crash its os.walk.
        """
        try:
            lines = modlist_txt.read_text(encoding="utf-8").splitlines(keepends=True)
        except OSError as exc:
            self._log(f"ESLifier Wizard: could not read modlist.txt ({exc}); using original.")
            return modlist_txt

        def _has_prefix_dir(mod_name: str) -> bool:
            mod_dir = staging / mod_name
            try:
                return any(
                    e.is_dir() and e.name.startswith("prefix_")
                    for e in mod_dir.iterdir()
                )
            except OSError:
                return False

        kept: list[str] = []
        removed: list[str] = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith(("+", "*")) and not stripped.endswith("_separator"):
                mod_name = stripped[1:].strip()
                if mod_name and _has_prefix_dir(mod_name):
                    removed.append(mod_name)
                    continue
            kept.append(line)

        try:
            dest.write_text("".join(kept), encoding="utf-8")
        except OSError as exc:
            self._log(f"ESLifier Wizard: could not write filtered modlist ({exc}); using original.")
            return modlist_txt

        if removed:
            self._log(
                "ESLifier Wizard: excluded "
                f"{len(removed)} mod(s) with a Wine prefix from the scan: "
                + ", ".join(removed)
            )
        return dest

    def _do_run(self, exe: Path):
        proton_script, env, compat_data = self._get_tool_env()
        if proton_script is None:
            self._set_label(
                "_run_status",
                f"Could not find Proton '{self._proton_name}' — "
                "check that it is installed in Steam.",
                color="#e06c6c",
            )
            return

        pfx = compat_data / "pfx"

        try:
            self._write_settings(exe, pfx)
        except Exception as exc:
            self._set_label("_run_status", f"Could not write settings: {exc}", color="#e06c6c")
            self._log(f"ESLifier Wizard: settings error: {exc}")
            return

        self._log(f"ESLifier Wizard: launching {exe} via Proton")
        try:
            proc = subprocess.Popen(
                ["python3", str(proton_script), "run", str(exe)],
                env=env,
                cwd=str(exe.parent),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._set_label(
                "_run_status",
                "ESLifier is running.\nClose it when you are done, then click Done.",
                color="#6bc76b",
            )
            self.after(0, lambda: self._done_btn.configure(state="normal"))
            proc.wait()
            shutdown_prefix_wineserver(
                proton_script, compat_data,
                log_fn=lambda m: self._log(f"ESLifier Wizard: {m}"),
            )
            self._log("ESLifier Wizard: ESLifier closed.")
            self._set_label("_run_status", "ESLifier finished. Click Done to close.", color="#6bc76b")
        except Exception as exc:
            self._set_label("_run_status", f"Launch error: {exc}", color="#e06c6c")
            self._log(f"ESLifier Wizard: launch error: {exc}")
