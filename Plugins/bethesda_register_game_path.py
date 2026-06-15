"""
Register the game's install path in the Wine registry of its Proton prefix.

Writes ``HKLM\\Software\\Bethesda Softworks\\<Game>\\Installed Path`` (and the
Wow6432Node mirror) into the game's own Steam compatdata prefix, so tools run
inside that prefix (xEdit, LOOT, Wrye Bash, …) can locate the game. Steam only
writes this key when the game is launched through Steam, so fresh installs or
games launched purely through the mod manager may be missing it.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from Utils.bethesda_registry import _marker_path, register_bethesda_game_path
from Utils.steam_finder import (
    find_any_installed_proton,
    find_proton_for_game,
    find_steam_root_for_proton_script,
)

if TYPE_CHECKING:
    from Games.base_game import BaseGame

from gui.theme import (
    ACCENT, ACCENT_HOV, BG_DEEP, BG_HEADER, BG_PANEL, BORDER,
    TEXT_ON_ACCENT, TEXT_DIM, TEXT_MAIN,
    FONT_NORMAL, FONT_BOLD, FONT_SMALL,
)


PLUGIN_INFO = {
    "id":           "bethesda_register_game_path",
    "label":        "Register Game Path in Wine Registry",
    "description":  "Write the game's install path to the Bethesda Softworks "
                    "registry keys in the game's Proton prefix.",
    "game_ids": [
        "skyrim_se",
        "Fallout3",
        "Fallout3GOTY",
        "FalloutNV",
        "Fallout4",
        "Fallout4VR",
        "Oblivion",
        "skyrim",
        "skyrimvr",
        "Starfield",
        "enderal",
        "enderalse",
    ],
    "all_games":    False,
    "dialog_class": "RegisterGamePathDialog",
    "category":     "Setup & Installers",
}


def _resolve_compat_data(prefix_path: Path) -> Path:
    """Return the STEAM_COMPAT_DATA_PATH directory for a pfx/ folder."""
    if (prefix_path / "config_info").is_file():
        return prefix_path
    return prefix_path.parent


def _read_prefix_runner(compat_data: Path) -> str:
    """Read the Proton runner name from <compat_data>/config_info."""
    try:
        return (
            (compat_data / "config_info")
            .read_text(encoding="utf-8")
            .splitlines()[0]
            .strip()
        )
    except (OSError, IndexError):
        return ""


class RegisterGamePathDialog(ctk.CTkFrame):
    """One-button dialog: write the game path into the prefix registry."""

    def __init__(self, parent, game: "BaseGame", log_fn=None, *, on_close=None, **_kwargs):
        super().__init__(parent, fg_color=BG_DEEP, corner_radius=0)
        self._on_close_cb = on_close or (lambda: None)
        self._game = game
        self._log = log_fn or (lambda msg: None)

        title_bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=40)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar, text=f"Register Game Path — {game.name}",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            title_bar, text="✕", width=32, height=32, font=FONT_BOLD,
            fg_color="transparent", hover_color=BG_PANEL, text_color=TEXT_MAIN,
            command=self._on_close_cb,
        ).pack(side="right", padx=4, pady=4)

        body = ctk.CTkFrame(self, fg_color=BG_DEEP)
        body.pack(fill="both", expand=True, padx=20, pady=20)

        registry_name = getattr(game, "synthesis_registry_name", "") or "?"
        game_path = game.get_game_path() if hasattr(game, "get_game_path") else None
        prefix_path = game.get_prefix_path() if hasattr(game, "get_prefix_path") else None

        info = (
            f"Registry key:  HKLM\\Software\\Bethesda Softworks\\{registry_name}\n"
            f"Game path:     {game_path or 'not configured'}\n"
            f"Proton prefix: {prefix_path or 'not configured'}"
        )
        ctk.CTkLabel(
            body, text=info, font=FONT_SMALL, text_color=TEXT_DIM,
            justify="left", anchor="w",
        ).pack(fill="x", pady=(0, 12))

        self._log_box = ctk.CTkTextbox(
            body, width=540, height=180, font=FONT_SMALL,
            fg_color=BG_PANEL, text_color=TEXT_MAIN, border_color=BORDER, border_width=1,
        )
        self._log_box.pack(fill="both", expand=True, pady=(0, 12))
        self._log_box.configure(state="disabled")

        self._run_btn = ctk.CTkButton(
            body, text="Write Registry Keys", width=200, height=36,
            font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._on_run,
        )
        self._run_btn.pack(side="bottom", pady=(8, 0))

        if game_path is None or prefix_path is None or not prefix_path.is_dir():
            self._run_btn.configure(state="disabled")
            if game_path is None:
                self._append_log("Game path is not configured — set it first.")
            else:
                self._append_log("Proton prefix not found — launch the game once via Steam first.")

    def _append_log(self, msg: str):
        def _apply():
            try:
                self._log_box.configure(state="normal")
                self._log_box.insert("end", msg + "\n")
                self._log_box.see("end")
                self._log_box.configure(state="disabled")
            except Exception:
                pass
        try:
            self.after(0, _apply)
        except Exception:
            pass
        self._log(msg)

    def _on_run(self):
        self._run_btn.configure(state="disabled", text="Writing …")
        threading.Thread(target=self._do_register, daemon=True).start()

    def _finish(self, ok: bool):
        def _apply():
            try:
                if ok:
                    self._run_btn.configure(state="normal", text="Done — Write Again")
                else:
                    self._run_btn.configure(state="normal", text="Retry")
            except Exception:
                pass
        try:
            self.after(0, _apply)
        except Exception:
            pass

    def _do_register(self):
        game = self._game

        registry_name = getattr(game, "synthesis_registry_name", None)
        if not registry_name:
            self._append_log("This game has no Bethesda registry name; nothing to do.")
            self._finish(False)
            return

        game_path = game.get_game_path()
        prefix_path = game.get_prefix_path()
        if game_path is None or prefix_path is None or not prefix_path.is_dir():
            self._append_log("Game path or Proton prefix not available.")
            self._finish(False)
            return

        compat_data = _resolve_compat_data(prefix_path)

        steam_id = getattr(game, "steam_id", "")
        proton_script = find_proton_for_game(steam_id) if steam_id else None
        if proton_script is None:
            preferred = _read_prefix_runner(compat_data)
            proton_script = find_any_installed_proton(preferred)
        if proton_script is None:
            self._append_log("No installed Proton tool found — install one via Steam.")
            self._finish(False)
            return

        steam_root = find_steam_root_for_proton_script(proton_script)
        if steam_root is None:
            self._append_log("Could not determine the Steam root for the Proton tool.")
            self._finish(False)
            return

        env = os.environ.copy()
        env["STEAM_COMPAT_DATA_PATH"] = str(compat_data)
        env["STEAM_COMPAT_CLIENT_INSTALL_PATH"] = str(steam_root)
        env["STEAM_COMPAT_INSTALL_PATH"] = str(game_path)
        env["WINEDEBUG"] = "-all"
        if steam_id:
            env.setdefault("SteamAppId", steam_id)
            env.setdefault("SteamGameId", steam_id)

        self._append_log(f"Prefix: {compat_data}")
        self._append_log(f"Proton: {proton_script.parent.name}")

        # Drop the idempotency marker so a manual run always re-writes the
        # keys, even if a previous (possibly stale) registration exists.
        try:
            marker = _marker_path(compat_data, registry_name)
            marker.unlink(missing_ok=True)
        except OSError:
            pass

        try:
            ok = register_bethesda_game_path(
                prefix_dir=compat_data,
                proton_script=proton_script,
                env=env,
                game_path=Path(game_path),
                registry_game_name=registry_name,
                log_fn=self._append_log,
            )
        except Exception as exc:
            self._append_log(f"Registry write raised: {exc}")
            ok = False

        if ok:
            self._append_log("Registry keys written (64-bit + Wow6432Node views).")
        else:
            self._append_log("Registry write finished with errors — see log above.")
        self._finish(ok)
