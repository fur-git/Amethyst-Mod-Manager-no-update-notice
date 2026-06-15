"""
Open Skyrim SE Documents folder in the Proton prefix.
"""

import customtkinter as ctk
from Utils.xdg import xdg_open

PLUGIN_INFO = {
    "id":           "skyrim_se_open_docs",
    "label":        "Open Skyrim Documents Folder",
    "description":  "Opens the Skyrim SE Documents folder in the Proton prefix (INIs, saves, etc.)",
    "game_ids":     ["skyrim_se"],
    "all_games":    False,
    "dialog_class": "SkyrimSEOpenDocsDialog",
    "category":     "Load Order & Config",
}

_RELATIVE_PATH = "drive_c/users/steamuser/My Documents/My Games/Skyrim Special Edition"


class SkyrimSEOpenDocsDialog(ctk.CTkFrame):

    def __init__(self, parent, game, log_fn=None, *, on_close=None, **extra):
        super().__init__(parent, fg_color="#1a1a2e", corner_radius=0)
        self._log = log_fn or (lambda msg: None)

        prefix = game.get_prefix_path()
        if prefix is None:
            self._log("Skyrim SE prefix path not configured.")
            self.destroy()
            return

        docs_path = prefix / _RELATIVE_PATH

        if not docs_path.is_dir():
            self._log(f"Folder not found: {docs_path}")
            self.destroy()
            return

        xdg_open(docs_path, log_fn=self._log)
        self._log(f"Opened: {docs_path}")
        self.destroy()
