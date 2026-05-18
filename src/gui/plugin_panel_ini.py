"""
Ini Files tab mixin for PluginPanel.

Owns the ini/json/toml file list:
- Tab construction with combined scrollbar + marker strip.
- Filename search + content keyword search across a broader extension set
  (.txt/.cfg/.yaml/.xml etc).
- Vanilla game-folder + profile-level ini collection alongside filemap entries.
- Row click → opens the ini editor overlay on the toplevel app.

Host (PluginPanel) owns: ``self._game``, ``self._tabs``, ``self._log``,
``self._safe_after``, ``self._get_filemap_path``, ``self._staging_root``,
``self._parse_filemap`` (provided by the Data mixin), and the ini-tab state
initialised in ``PluginPanel.__init__`` (``_ini_files_tab_dirty``).
"""

import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path

import customtkinter as ctk

import gui.theme as _theme
from gui.theme import (
    ACCENT,
    ACCENT_HOV,
    BG_DEEP,
    BG_HEADER,
    BG_HOVER,
    BG_HOVER_ROW,
    BG_LIST,
    BG_PANEL,
    BORDER,
    TEXT_DIM,
    TEXT_MAIN,
    TEXT_OK,
    TEXT_ON_ACCENT,
    TAG_INI_PROFILE,
    scaled,
)
from gui.wheel_compat import LEGACY_WHEEL_REDUNDANT


class PluginPanelIniMixin:
    """Ini/json/toml file list with filename search + content search."""

    _INI_JSON_EXTENSIONS = frozenset({
        ".ini", ".json", ".toml", ".txt", ".cfg", ".conf", ".config",
        ".yaml", ".yml", ".xml", ".log", ".md",
    })
    _INI_CONTENT_SEARCH_EXTENSIONS = frozenset({
        ".ini", ".json", ".toml", ".txt", ".cfg", ".conf", ".config",
        ".yaml", ".yml", ".xml", ".log", ".md",
    })

    @staticmethod
    def _ini_display_name(rel_path: str) -> str:
        """Return '<parent>/<filename>' when the file is nested, else just '<filename>'."""
        p = Path(rel_path)
        if p.parent != Path("."):
            return f"{p.parent.name}/{p.name}"
        return p.name

    def _build_ini_files_tab(self):
        """Build the Ini Files tab: list of ini/json files with search and marker strip."""
        tab = self._tabs.tab("Ini Files")
        tab.configure(fg_color=BG_LIST)
        tab.grid_rowconfigure(3, weight=1)
        tab.grid_columnconfigure(0, weight=1)

        # Toolbar with Refresh and Search
        toolbar = tk.Frame(tab, bg=BG_HEADER, height=scaled(28), highlightthickness=0)
        toolbar.grid(row=0, column=0, sticky="ew")
        toolbar.grid_propagate(False)

        ctk.CTkButton(
            toolbar, text="↺ Refresh", width=72, height=26,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_MAIN,
            font=_theme.FONT_HEADER, corner_radius=4,
            command=self._refresh_ini_files_tab,
        ).pack(side="left", padx=8, pady=2)

        ctk.CTkButton(
            toolbar, text="Search Content", width=140, height=26,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_MAIN,
            font=_theme.FONT_HEADER, corner_radius=4,
            command=self._on_search_ini_content,
        ).pack(side="left", padx=(0, 8), pady=2)

        self._ini_filter_btn = ctk.CTkButton(
            toolbar, text="Filters", width=72, height=26,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            font=_theme.FONT_HEADER, corner_radius=4,
            command=self._toggle_ini_filter_panel,
        )
        self._ini_filter_btn.pack(side="left", padx=(0, 8), pady=2)
        self._build_ini_filter_side_panel()

        # Content-filter status row (row 1) — hidden when no content filter is active
        self._ini_content_status_row = tk.Frame(tab, bg=BG_HEADER, highlightthickness=0)
        self._ini_content_status_row.grid(row=1, column=0, sticky="ew")
        self._ini_content_status_row.grid_remove()
        self._ini_content_status_var = tk.StringVar(value="")
        self._ini_content_status_lbl = tk.Label(
            self._ini_content_status_row, textvariable=self._ini_content_status_var,
            bg=BG_HEADER, fg=TEXT_DIM,
            font=(_theme.FONT_FAMILY, _theme.FS10),
        )
        self._ini_content_status_lbl.pack(side="left", padx=(8, 6), pady=2)
        self._ini_content_clear_btn = ctk.CTkButton(
            self._ini_content_status_row, text="✕ Clear", width=60, height=22,
            fg_color=BG_HOVER, hover_color=BG_HOVER_ROW, text_color=TEXT_MAIN,
            font=(_theme.FONT_FAMILY, _theme.FS10), corner_radius=4,
            command=self._clear_ini_content_filter,
        )
        self._ini_content_clear_btn.pack(side="left", padx=(0, 8), pady=2)

        # Inline content-search bar (row 2) — hidden by default
        self._build_ini_content_search_bar(tab)

        # List frame: tree | combined scrollbar+marker strip
        list_frame = tk.Frame(tab, bg=BG_LIST)
        list_frame.grid(row=3, column=0, sticky="nsew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        _bg = BG_LIST
        _fg = TEXT_MAIN
        _style_name = "IniFiles.Treeview"
        style = ttk.Style()
        style.theme_use("default")
        style.configure(_style_name,
            background=_bg, foreground=_fg,
            fieldbackground=_bg, borderwidth=0,
            rowheight=scaled(22), font=(_theme.FONT_FAMILY, _theme.FS10),
            focuscolor=_bg,
        )
        style.map(_style_name,
            background=[("selected", _bg), ("focus", _bg)],
            foreground=[("selected", ACCENT)],
        )
        style.configure(f"{_style_name}.Heading",
            background=_bg, foreground=_fg,
            font=(_theme.FONT_FAMILY, _theme.FS10, "bold"), relief="flat",
        )
        # Remove the expand/collapse indicator (dark box) — flat list has no hierarchy
        try:
            style.configure(f"{_style_name}.Item", indent=0, indicatorsize=0)
        except Exception:
            pass
        try:
            style.layout(f"{_style_name}.Item", [
                ("Treeitem.padding", {"sticky": "nsew", "children": [
                    ("Treeitem.image", {"side": "left", "sticky": "nsew"}),
                    ("Treeitem.focus", {"side": "left", "sticky": "nsew", "children": [
                        ("Treeitem.text", {"side": "left", "sticky": "nsew"}),
                    ]}),
                ]}),
            ])
        except Exception:
            pass

        self._ini_files_tree = ttk.Treeview(
            list_frame, columns=("mod",), style=_style_name,
            selectmode="browse", show="tree headings",
        )
        self._ini_files_tree.heading("#0", text="File", anchor="w")
        self._ini_files_tree.heading("mod", text="Mod", anchor="w")
        self._ini_files_tree.column("#0", minwidth=150, stretch=True)
        self._ini_files_tree.column("mod", minwidth=120, stretch=True)
        self._ini_files_tree.tag_configure("mod_highlight", background=_theme.plugin_mod, foreground=TEXT_MAIN)
        self._ini_files_tree.tag_configure("game_folder", foreground=TEXT_OK)
        self._ini_files_tree.tag_configure("profile_folder", foreground=TAG_INI_PROFILE)

        # Combined scrollbar + marker strip — same pattern as modlist_panel /
        # plugins tab: one canvas paints trough, ticks, and thumb.
        self._INI_SCROLL_W = 16
        self._ini_marker_strip = tk.Canvas(
            list_frame, bg=BG_DEEP, bd=0, highlightthickness=0,
            width=self._INI_SCROLL_W, takefocus=0,
        )
        self._ini_vsb = self._ini_marker_strip  # alias kept for any external refs
        self._ini_files_tree.configure(yscrollcommand=self._ini_scroll_set)

        self._ini_files_tree.grid(row=0, column=0, sticky="nsew")
        self._ini_marker_strip.grid(row=0, column=1, sticky="ns")

        self._ini_scroll_first = 0.0
        self._ini_scroll_last = 1.0
        self._ini_thumb_drag_offset: float | None = None

        self._ini_marker_strip.bind("<Configure>",        self._on_ini_marker_strip_resize)
        self._ini_marker_strip.bind("<ButtonPress-1>",    self._on_ini_scrollbar_press)
        self._ini_marker_strip.bind("<B1-Motion>",        self._on_ini_scrollbar_drag)
        self._ini_marker_strip.bind("<ButtonRelease-1>",  self._on_ini_scrollbar_release)
        self._ini_marker_strip.bind("<Button-4>",         lambda e: self._ini_files_tree.yview_scroll(-3, "units"))
        self._ini_marker_strip.bind("<Button-5>",         lambda e: self._ini_files_tree.yview_scroll(3, "units"))
        self._ini_marker_strip.bind("<MouseWheel>",       self._on_ini_mousewheel)

        # Search bar (bottom)
        ini_search_bar = tk.Frame(tab, bg=BG_HEADER, highlightthickness=0)
        ini_search_bar.grid(row=4, column=0, sticky="ew")
        tk.Label(
            ini_search_bar, text="Search:", bg=BG_HEADER, fg=TEXT_DIM,
            font=(_theme.FONT_FAMILY, _theme.FS10),
        ).pack(side="left", padx=(8, 4), pady=3)
        self._ini_search_var = tk.StringVar()
        self._ini_search_var.trace_add("write", self._on_ini_search_changed)
        self._ini_search_entry = tk.Entry(
            ini_search_bar, textvariable=self._ini_search_var,
            bg=BG_DEEP, fg=TEXT_MAIN, insertbackground=TEXT_MAIN,
            relief="flat", font=(_theme.FONT_FAMILY, _theme.FS10),
            highlightthickness=0, highlightbackground=BG_DEEP,
        )
        self._ini_search_entry.pack(side="left", padx=(0, 8), pady=3, fill="x", expand=True)
        self._ini_search_entry.bind("<Escape>", lambda e: self._ini_search_var.set(""))
        def _ini_select_all(evt):
            evt.widget.select_range(0, tk.END)
            evt.widget.icursor(tk.END)
            return "break"
        self._ini_search_entry.bind("<Control-a>", _ini_select_all)

        self._ini_files_tree.bind("<<TreeviewSelect>>", self._on_ini_file_select)
        if not LEGACY_WHEEL_REDUNDANT:
            self._ini_files_tree.bind("<Button-4>", lambda e: self._ini_files_tree.yview_scroll(-3, "units"))
            self._ini_files_tree.bind("<Button-5>", lambda e: self._ini_files_tree.yview_scroll(3, "units"))

        self._ini_files_entries: list[tuple[str, str, Path]] = []  # full list
        self._ini_files_displayed: list[tuple[str, str, Path]] = []  # filtered for display
        self._ini_files_status: str | None = None  # "load"|"nofile"|None
        self._highlighted_ini_mod: str | None = None
        self._ini_marker_strip_after_id: str | None = None
        self._ini_content_query: str | None = None
        self._ini_content_matches: set[tuple[str, str]] | None = None
        self._ini_content_extra_entries: list[tuple[str, str, Path]] = []
        self._ini_filter_extensions: set[str] = set()  # empty = no filter
        self._ini_filter_panel_open: bool = False

    def _build_ini_filter_side_panel(self) -> None:
        """Build the Ini Files filter side panel — same pattern as the Data /
        Downloads filter panels, sharing column 0 on the ModListPanel."""
        mod_panel = getattr(self.winfo_toplevel(), "_mod_panel", None)
        parent = mod_panel if mod_panel is not None else self
        panel = ctk.CTkFrame(parent, fg_color=BG_PANEL, corner_radius=0, width=380)
        panel.grid(row=0, column=0, rowspan=5, sticky="nsew")
        panel.grid_propagate(False)
        panel.grid_remove()
        self._ini_filter_side_panel = panel

        header = tk.Frame(panel, bg=BG_HEADER, height=scaled(36))
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        tk.Label(
            header, text="Ini Filters", bg=BG_HEADER, fg=TEXT_MAIN,
            font=_theme.FONT_BOLD, anchor="w",
        ).pack(side="left", padx=10, pady=6)

        close_btn = tk.Label(
            header, text="×", bg=BG_HEADER, fg=TEXT_DIM,
            font=(_theme.FONT_FAMILY, 16, "bold"), cursor="hand2",
        )
        close_btn.pack(side="right", padx=8)
        close_btn.bind("<Button-1>", lambda _e: self._close_ini_filter_panel())
        close_btn.bind("<Enter>",    lambda _e: close_btn.configure(fg=TEXT_MAIN))
        close_btn.bind("<Leave>",    lambda _e: close_btn.configure(fg=TEXT_DIM))

        clear_btn = tk.Label(
            header, text="Clear all", bg=BG_HEADER, fg=TEXT_DIM,
            font=_theme.FONT_SMALL, cursor="hand2",
        )
        clear_btn.pack(side="right", padx=(0, 4))
        clear_btn.bind("<Button-1>", lambda _e: self._clear_all_ini_filters())
        clear_btn.bind("<Enter>",    lambda _e: clear_btn.configure(fg=TEXT_MAIN))
        clear_btn.bind("<Leave>",    lambda _e: clear_btn.configure(fg=TEXT_DIM))

        tk.Frame(panel, bg=BORDER, height=1).pack(fill="x")

        scroll_frame = ctk.CTkScrollableFrame(
            panel, fg_color="transparent", corner_radius=0,
        )
        scroll_frame.pack(fill="both", expand=True, padx=8, pady=6)
        self._ini_filter_scroll_frame = scroll_frame

        ctk.CTkLabel(
            scroll_frame, text="By file type",
            font=_theme.FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(anchor="w", pady=(2, 4))

        self._ifsp_filetype_frame = ctk.CTkFrame(scroll_frame, fg_color="transparent")
        self._ifsp_filetype_frame.pack(anchor="w", fill="x", pady=(2, 0))
        self._ifsp_filetype_vars = {}

        self._bind_ini_filter_panel_scroll()

    def _bind_ini_filter_panel_scroll(self) -> None:
        scroll_frame = getattr(self, "_ini_filter_scroll_frame", None)
        if not scroll_frame or not hasattr(scroll_frame, "_parent_canvas"):
            return
        step = 2

        def _on_wheel(evt):
            num = getattr(evt, "num", None)
            delta = getattr(evt, "delta", 0) or 0
            if num == 4 or delta > 0:
                scroll_frame._parent_canvas.yview_scroll(-step, "units")
            elif num == 5 or delta < 0:
                scroll_frame._parent_canvas.yview_scroll(step, "units")
            return "break"

        _legacy = None if LEGACY_WHEEL_REDUNDANT else _on_wheel

        def _bind_recursive(w):
            if _legacy is not None:
                w.bind("<Button-4>", _legacy)
                w.bind("<Button-5>", _legacy)
            for child in w.winfo_children():
                _bind_recursive(child)

        _bind_recursive(scroll_frame)

    def _get_ini_filetype_counts(self) -> "dict[str, int]":
        """Extension (lowercase, with dot) → count across the full ini entries list."""
        counts: dict[str, int] = {}
        for rel_path, _mod, _p in self._ini_files_entries:
            ext = Path(rel_path).suffix.lower()
            if ext:
                counts[ext] = counts.get(ext, 0) + 1
        return counts

    def _refresh_ini_filter_filetype_list(self) -> None:
        frame = self._ifsp_filetype_frame
        if frame is None:
            return
        for w in frame.winfo_children():
            w.destroy()
        self._ifsp_filetype_vars.clear()
        counts = self._get_ini_filetype_counts()
        if not counts:
            ctk.CTkLabel(
                frame, text="(no files in Ini tab)",
                font=_theme.FONT_SMALL, text_color=TEXT_DIM, anchor="w",
            ).pack(anchor="w", pady=2)
            self._bind_ini_filter_panel_scroll()
            return
        for ext, count in sorted(counts.items(), key=lambda kv: kv[0]):
            var = tk.BooleanVar(value=ext in self._ini_filter_extensions)
            self._ifsp_filetype_vars[ext] = var
            ctk.CTkCheckBox(
                frame,
                text=f"{ext}  ({count:,})",
                variable=var,
                font=_theme.FONT_SMALL,
                text_color=TEXT_MAIN,
                fg_color=ACCENT,
                hover_color=ACCENT_HOV,
                border_color=BORDER,
                checkmark_color="white",
                command=self._on_ini_filter_panel_change,
            ).pack(anchor="w", pady=2)
        self._bind_ini_filter_panel_scroll()

    def _on_ini_filter_panel_change(self) -> None:
        self._ini_filter_extensions = {
            ext for ext, v in self._ifsp_filetype_vars.items() if v.get()
        }
        self._update_ini_filter_btn_color()
        self._apply_ini_search_filter()

    def _clear_all_ini_filters(self) -> None:
        self._ini_filter_extensions = set()
        for v in self._ifsp_filetype_vars.values():
            v.set(False)
        self._update_ini_filter_btn_color()
        self._apply_ini_search_filter()

    def _toggle_ini_filter_panel(self) -> None:
        if getattr(self, "_ini_filter_panel_open", False):
            self._close_ini_filter_panel()
        else:
            self._open_ini_filter_panel()

    def _open_ini_filter_panel(self) -> None:
        mod_panel = getattr(self.winfo_toplevel(), "_mod_panel", None)
        if mod_panel is None or self._ini_filter_side_panel is None:
            return
        # Mutual exclusion with the other filter panels that share column 0.
        if getattr(mod_panel, "_filter_panel_open", False):
            try:
                mod_panel._close_filter_side_panel()
            except Exception:
                pass
        if getattr(self, "_plugin_filter_panel_open", False):
            try:
                self._close_plugin_filter_panel()
            except Exception:
                pass
        if getattr(self, "_data_filter_panel_open", False):
            try:
                self._close_data_filter_panel()
            except Exception:
                pass
        app = self.winfo_toplevel()
        dl_panel = getattr(app, "_downloads_panel", None)
        if dl_panel is not None and getattr(dl_panel, "_filter_panel_open", False):
            try:
                dl_panel._close_filter_side_panel()
            except Exception:
                pass
        self._ini_filter_panel_open = True
        mod_panel.grid_columnconfigure(0, minsize=scaled(380))
        self._ini_filter_side_panel.grid()
        self._refresh_ini_filter_filetype_list()
        self._update_ini_filter_btn_color()

    def _close_ini_filter_panel(self) -> None:
        mod_panel = getattr(self.winfo_toplevel(), "_mod_panel", None)
        self._ini_filter_panel_open = False
        if mod_panel is not None:
            mod_panel.grid_columnconfigure(0, minsize=0)
        if self._ini_filter_side_panel is not None:
            self._ini_filter_side_panel.grid_remove()
        self._update_ini_filter_btn_color()

    def _update_ini_filter_btn_color(self) -> None:
        btn = getattr(self, "_ini_filter_btn", None)
        if btn is None:
            return
        if self._ini_filter_extensions:
            btn.configure(fg_color=ACCENT_HOV, hover_color=ACCENT_HOV)
        else:
            btn.configure(fg_color=ACCENT, hover_color=ACCENT_HOV)

    def _resolve_ini_file_path(self, rel_path: str, mod_name: str) -> Path | None:
        """Resolve full file path from filemap entry. Returns None if staging_root unknown.

        Tries an exact path first; if that doesn't exist, walks each path segment
        case-insensitively to handle case-normalised filemap paths on Linux.
        """
        if self._staging_root is None:
            return None
        from Utils.filemap import OVERWRITE_NAME, ROOT_FOLDER_NAME
        rel_path = rel_path.replace("\\", "/")
        if mod_name == OVERWRITE_NAME:
            base = self._staging_root.parent / "overwrite"
        elif mod_name == ROOT_FOLDER_NAME:
            base = self._staging_root.parent / "Root_Folder"
        else:
            base = self._staging_root / mod_name
        exact = base / rel_path
        if exact.exists():
            return exact
        # Case-insensitive fallback: resolve each segment against the actual directory.
        current = base
        for segment in rel_path.split("/"):
            if not current.is_dir():
                return exact  # can't resolve further — return exact for display
            seg_lower = segment.lower()
            match = next(
                (child for child in current.iterdir() if child.name.lower() == seg_lower),
                None,
            )
            if match is None:
                return exact  # segment not found — return exact for display
            current = match
        return current

    def _refresh_ini_files_tab(self):
        """Populate Ini Files tab from filemap.txt, filtering to .ini and .json.

        Deferred when the Ini Files tab is not visible — rebuilt on tab switch.
        """
        try:
            if self._tabs.get() != "Ini Files":
                self._ini_files_tab_dirty = True
                return
        except Exception:
            pass
        self._ini_files_tab_dirty = False
        self._ini_files_entries.clear()
        if self._ini_content_matches is not None:
            self._ini_content_query = None
            self._ini_content_matches = None
            self._ini_content_extra_entries = []
            self._update_ini_content_status()

        filemap_path_str = self._get_filemap_path()
        if filemap_path_str is None or not self._staging_root:
            self._ini_files_displayed = []
            self._ini_files_status = "load"
            self._build_ini_tree_from_displayed()
            return

        filemap_path = Path(filemap_path_str)
        if not filemap_path.is_file():
            self._ini_files_displayed = []
            self._ini_files_status = "nofile"
            self._build_ini_tree_from_displayed()
            return
        self._ini_files_status = None

        entries = self._parse_filemap(filemap_path)
        ini_entries: list[tuple[str, str, Path]] = []
        for rel_path, mod_name in entries:
            ext = Path(rel_path).suffix.lower()
            if ext not in self._INI_JSON_EXTENSIONS:
                continue
            full_path = self._resolve_ini_file_path(rel_path, mod_name)
            if full_path is None:
                continue
            ini_entries.append((rel_path, mod_name, full_path))

        # Also scan the game folder for vanilla ini/json files (not hardlinks/symlinks).
        game_path = self._game.get_game_path() if self._game and hasattr(self._game, "get_game_path") else None
        if game_path and Path(game_path).is_dir():
            game_root = Path(game_path)
            for fpath in game_root.rglob("*"):
                if fpath.suffix.lower() not in self._INI_JSON_EXTENSIONS:
                    continue
                try:
                    st = fpath.stat()
                except OSError:
                    continue
                # Skip symlinks and hardlinks (deployed files have nlink > 1)
                if fpath.is_symlink() or st.st_nlink > 1:
                    continue
                rel = fpath.relative_to(game_root).as_posix()
                ini_entries.append((rel, "Game Folder", fpath))

        # Also include profile-level ini files (the ones that get symlinked into My Games).
        for rel, fpath in self._collect_profile_ini_files(self._INI_JSON_EXTENSIONS):
            ini_entries.append((rel, "Profile", fpath))

        self._ini_files_entries = sorted(ini_entries, key=lambda t: (t[0].lower(), t[1].lower()))
        self._apply_ini_search_filter()

    def _collect_profile_ini_files(self, extensions: "frozenset[str]") -> "list[tuple[str, Path]]":
        """Return (rel_path, full_path) for config files at the top of the active profile folder.
        rel_path is just the filename. Returns [] if no profile dir is known."""
        profile_dir = getattr(self._game, "_active_profile_dir", None) if self._game else None
        if not profile_dir:
            return []
        profile_dir = Path(profile_dir)
        if not profile_dir.is_dir():
            return []
        results: list[tuple[str, Path]] = []
        try:
            for fpath in profile_dir.iterdir():
                if not fpath.is_file():
                    continue
                if fpath.suffix.lower() not in extensions:
                    continue
                results.append((fpath.name, fpath))
        except OSError:
            return []
        return results

    def _on_ini_search_changed(self, *_):
        """Filter displayed ini files by search query (filename or mod name)."""
        self._apply_ini_search_filter()

    def _apply_ini_search_filter(self):
        """Apply search filter and rebuild tree."""
        query = self._ini_search_var.get().strip().casefold()
        content_matches = self._ini_content_matches
        entries = self._ini_files_entries
        if content_matches is not None:
            extra = getattr(self, "_ini_content_extra_entries", None) or []
            combined = list(entries) + list(extra)
            entries = [e for e in combined if (e[0], e[1]) in content_matches]
            entries.sort(key=lambda t: (t[0].lower(), t[1].lower()))
        ext_filter = self._ini_filter_extensions
        if ext_filter:
            entries = [e for e in entries if Path(e[0]).suffix.lower() in ext_filter]
        if not query:
            self._ini_files_displayed = list(entries)
        else:
            self._ini_files_displayed = [
                (r, m, p) for r, m, p in entries
                if query in r.casefold() or query in m.casefold()
            ]
        self._build_ini_tree_from_displayed()

    def _build_ini_content_search_bar(self, tab):
        """Inline search bar shown at the top of the Ini Files tab (hidden by default)."""
        bar = tk.Frame(tab, bg=BG_HEADER, highlightthickness=0)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_remove()
        self._ini_content_search_bar = bar

        tk.Label(
            bar, text="Search content:", bg=BG_HEADER, fg=TEXT_MAIN,
            font=(_theme.FONT_FAMILY, _theme.FS10),
        ).pack(side="left", padx=(8, 4), pady=6)

        self._ini_content_search_var = tk.StringVar()
        self._ini_content_search_entry = ctk.CTkEntry(
            bar, textvariable=self._ini_content_search_var,
            font=(_theme.FONT_FAMILY, _theme.FS10),
            fg_color=BG_PANEL, text_color=TEXT_MAIN, border_color=BORDER,
            placeholder_text="e.g.  fCompassPosY",
            width=140, height=26,
        )
        self._ini_content_search_entry.pack(side="left", padx=(0, 6), pady=6, fill="x", expand=True)
        self._ini_content_search_entry.bind(
            "<Return>", lambda _e: self._on_ini_content_search_submit()
        )
        self._ini_content_search_entry.bind(
            "<Escape>", lambda _e: self.hide_ini_content_search_bar()
        )

        ctk.CTkButton(
            bar, text="Search", width=72, height=26, font=_theme.FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._on_ini_content_search_submit,
        ).pack(side="left", padx=(0, 4), pady=6)

        ctk.CTkButton(
            bar, text="Cancel", width=72, height=26, font=_theme.FONT_NORMAL,
            fg_color=BG_HOVER, hover_color=BG_HOVER, text_color=TEXT_MAIN,
            command=self.hide_ini_content_search_bar,
        ).pack(side="left", padx=(0, 8), pady=6)

    def _on_search_ini_content(self):
        """Toggle the inline content-search bar at the top of the tab."""
        bar = getattr(self, "_ini_content_search_bar", None)
        if bar is None:
            return
        if bar.winfo_manager():
            self.hide_ini_content_search_bar()
            return
        self._ini_content_search_var.set(self._ini_content_query or "")
        bar.grid()
        self._ini_content_search_entry.focus_set()
        try:
            self._ini_content_search_entry.select_range(0, tk.END)
        except Exception:
            pass

    def hide_ini_content_search_bar(self):
        bar = getattr(self, "_ini_content_search_bar", None)
        if bar is not None:
            bar.grid_remove()

    def _on_ini_content_search_submit(self):
        kw = self._ini_content_search_var.get().strip()
        if not kw:
            return
        self.hide_ini_content_search_bar()
        self._run_ini_content_search(kw)

    def _collect_ini_content_search_entries(self) -> list[tuple[str, str, Path]]:
        """Return every text-like config file from filemap + game folder for content search.
        Uses a broader extension set than the Ini Files tab (.txt/.cfg/.yaml/.xml etc)."""
        out: list[tuple[str, str, Path]] = []
        seen: set[tuple[str, str]] = set()

        for r, m, p in self._ini_files_entries:
            key = (r, m)
            if key in seen:
                continue
            seen.add(key)
            out.append((r, m, p))

        filemap_path_str = self._get_filemap_path()
        if filemap_path_str and self._staging_root:
            filemap_path = Path(filemap_path_str)
            if filemap_path.is_file():
                for rel_path, mod_name in self._parse_filemap(filemap_path):
                    ext = Path(rel_path).suffix.lower()
                    if ext not in self._INI_CONTENT_SEARCH_EXTENSIONS:
                        continue
                    key = (rel_path, mod_name)
                    if key in seen:
                        continue
                    full_path = self._resolve_ini_file_path(rel_path, mod_name)
                    if full_path is None:
                        continue
                    seen.add(key)
                    out.append((rel_path, mod_name, full_path))

        game_path = self._game.get_game_path() if self._game and hasattr(self._game, "get_game_path") else None
        if game_path and Path(game_path).is_dir():
            game_root = Path(game_path)
            for fpath in game_root.rglob("*"):
                if fpath.suffix.lower() not in self._INI_CONTENT_SEARCH_EXTENSIONS:
                    continue
                try:
                    st = fpath.stat()
                except OSError:
                    continue
                if fpath.is_symlink() or st.st_nlink > 1:
                    continue
                rel = fpath.relative_to(game_root).as_posix()
                key = (rel, "Game Folder")
                if key in seen:
                    continue
                seen.add(key)
                out.append((rel, "Game Folder", fpath))

        for rel, fpath in self._collect_profile_ini_files(self._INI_CONTENT_SEARCH_EXTENSIONS):
            key = (rel, "Profile")
            if key in seen:
                continue
            seen.add(key)
            out.append((rel, "Profile", fpath))

        return out

    def _run_ini_content_search(self, keyword: str):
        """Scan every text-like config file (broad extension set) for keyword (case-insensitive)."""
        needle = keyword.casefold()
        candidates = self._collect_ini_content_search_entries()
        matched_entries: list[tuple[str, str, Path]] = []
        for rel_path, mod_name, full_path in candidates:
            try:
                if not full_path.is_file():
                    continue
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    if needle in f.read().casefold():
                        matched_entries.append((rel_path, mod_name, full_path))
            except OSError:
                continue

        self._ini_content_query = keyword
        self._ini_content_matches = {(r, m) for r, m, _ in matched_entries}
        self._ini_content_extra_entries = [
            (r, m, p) for r, m, p in matched_entries
            if (r, m) not in {(er, em) for er, em, _ in self._ini_files_entries}
        ]
        self._update_ini_content_status()
        self._apply_ini_search_filter()

    def _clear_ini_content_filter(self):
        self._ini_content_query = None
        self._ini_content_matches = None
        self._ini_content_extra_entries = []
        self._update_ini_content_status()
        self._apply_ini_search_filter()

    def _update_ini_content_status(self):
        if self._ini_content_matches is None:
            self._ini_content_status_var.set("")
            try:
                self._ini_content_status_row.grid_remove()
            except Exception:
                pass
        else:
            n = len(self._ini_content_matches)
            q = self._ini_content_query or ""
            self._ini_content_status_var.set(f"Content: \"{q}\"  ({n} match{'es' if n != 1 else ''})")
            try:
                self._ini_content_status_row.grid()
            except Exception:
                pass

    def _build_ini_tree_from_displayed(self):
        """Rebuild tree from _ini_files_displayed."""
        self._ini_files_tree.delete(*self._ini_files_tree.get_children())
        status = getattr(self, "_ini_files_status", None)
        if status == "load":
            self._ini_files_tree.insert("", "end", text="(load a game first)", values=("",))
            return
        if status == "nofile":
            self._ini_files_tree.insert("", "end", text="(filemap.txt not found)", values=("",))
            return
        if not self._ini_files_displayed:
            if self._ini_search_var.get().strip() or self._ini_content_matches is not None:
                self._ini_files_tree.insert("", "end", text="(no matches)", values=("",))
            else:
                self._ini_files_tree.insert("", "end", text="(no ini/json files in filemap)", values=("",))
            return
        for rel_path, mod_name, _ in self._ini_files_displayed:
            if mod_name == self._highlighted_ini_mod:
                tags = ("mod_highlight",)
            elif mod_name == "Game Folder":
                tags = ("game_folder",)
            elif mod_name == "Profile":
                tags = ("profile_folder",)
            else:
                tags = ()
            self._ini_files_tree.insert("", "end", text=self._ini_display_name(rel_path), values=(mod_name,), tags=tags)
        self._draw_ini_marker_strip()

    def _on_ini_marker_strip_resize(self, _event=None):
        if self._ini_marker_strip_after_id is not None:
            self.after_cancel(self._ini_marker_strip_after_id)
        self._ini_marker_strip_after_id = self.after(50, self._draw_ini_marker_strip)

    def _apply_ini_row_highlight(self):
        """Update row background (orange) for items belonging to the selected mod."""
        displayed = self._ini_files_displayed
        children = self._ini_files_tree.get_children()
        for i, iid in enumerate(children):
            if i >= len(displayed):
                break
            _, mod_name, _ = displayed[i]
            if self._highlighted_ini_mod and mod_name == self._highlighted_ini_mod:
                tags = ("mod_highlight",)
            elif mod_name == "Game Folder":
                tags = ("game_folder",)
            elif mod_name == "Profile":
                tags = ("profile_folder",)
            else:
                tags = ()
            self._ini_files_tree.item(iid, tags=tags)

    def _draw_ini_marker_strip(self):
        """Paint the combined scrollbar + marker strip for the Ini Files tab.

        Layers (bottom → top):
          1. Trough background
          2. Orange tick marks for ini/json files belonging to the selected mod
          3. Thumb rectangle
        """
        self._ini_marker_strip_after_id = None
        c = self._ini_marker_strip
        c.delete("all")
        strip_h = c.winfo_height()
        strip_w = c.winfo_width()
        if strip_h <= 1 or strip_w <= 1:
            return

        c.create_rectangle(0, 0, strip_w, strip_h, fill=BG_DEEP, outline="", tags="trough")

        displayed = self._ini_files_displayed
        n = len(displayed)
        if n and self._highlighted_ini_mod:
            highlighted_rows = [
                i for i, (_, mod_name, _) in enumerate(displayed)
                if mod_name == self._highlighted_ini_mod
            ]
            if highlighted_rows:
                strip_max = strip_h - 4
                inv_n = 1.0 / n
                color = _theme.plugin_mod
                for row_idx in highlighted_rows:
                    y = int(row_idx * inv_n * strip_h)
                    if y < 2:
                        y = 2
                    elif y > strip_max:
                        y = strip_max
                    c.create_rectangle(0, y, strip_w, y + 3, fill=color, outline="", tags="marker")

        self._redraw_ini_thumb()

    def _redraw_ini_thumb(self) -> None:
        c = self._ini_marker_strip
        c.delete("thumb")
        strip_h = c.winfo_height()
        strip_w = c.winfo_width()
        if strip_h <= 1 or strip_w <= 1:
            return
        first = max(0.0, min(1.0, self._ini_scroll_first))
        last = max(first, min(1.0, self._ini_scroll_last))
        if last - first >= 0.999:
            return
        y1 = int(first * strip_h)
        y2 = max(y1 + 8, int(last * strip_h))
        if y2 > strip_h:
            y2 = strip_h
            y1 = max(0, y2 - 8)
        c.create_rectangle(
            0, y1, strip_w, y2,
            fill=_theme.BG_SEP, outline="", tags="thumb",
        )

    def _ini_scroll_set(self, first: str, last: str) -> None:
        try:
            f = float(first); l = float(last)
        except (TypeError, ValueError):
            return
        if f == self._ini_scroll_first and l == self._ini_scroll_last:
            return
        self._ini_scroll_first = f
        self._ini_scroll_last = l
        self._redraw_ini_thumb()

    def _on_ini_scrollbar_press(self, event):
        strip_h = self._ini_marker_strip.winfo_height()
        if strip_h <= 1:
            return
        first = self._ini_scroll_first
        last = self._ini_scroll_last
        thumb_top = first * strip_h
        thumb_bot = last * strip_h
        if thumb_top <= event.y <= thumb_bot:
            self._ini_thumb_drag_offset = (event.y - thumb_top) / strip_h
        else:
            self._ini_thumb_drag_offset = (last - first) / 2.0
            self._ini_scroll_to_pointer(event.y)

    def _on_ini_scrollbar_drag(self, event):
        if self._ini_thumb_drag_offset is None:
            return
        self._ini_scroll_to_pointer(event.y)

    def _on_ini_scrollbar_release(self, _event):
        self._ini_thumb_drag_offset = None

    def _ini_scroll_to_pointer(self, py: int) -> None:
        strip_h = self._ini_marker_strip.winfo_height()
        if strip_h <= 1 or self._ini_thumb_drag_offset is None:
            return
        frac = (py / strip_h) - self._ini_thumb_drag_offset
        frac = max(0.0, min(1.0, frac))
        self._ini_files_tree.yview_moveto(frac)

    def _on_ini_mousewheel(self, event):
        delta = event.delta
        if delta == 0:
            return
        step = -3 if delta > 0 else 3
        self._ini_files_tree.yview_scroll(step, "units")

    def _on_ini_file_select(self, _event=None):
        self._on_ini_file_edit()

    def _on_ini_file_edit(self):
        """Open the ini/json file editor overlay."""
        sel = self._ini_files_tree.selection()
        if not sel:
            return
        item = sel[0]
        children = self._ini_files_tree.get_children()
        try:
            idx = children.index(item)
        except ValueError:
            return
        if idx < 0 or idx >= len(self._ini_files_displayed):
            return
        rel_path, mod_name, full_path = self._ini_files_displayed[idx]
        app = self.winfo_toplevel()
        show_fn = getattr(app, "show_ini_editor_panel", None)
        if show_fn:
            show_fn(str(full_path), rel_path, mod_name, highlight=self._ini_content_query)
