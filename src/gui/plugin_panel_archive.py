"""
Archive tab mixin for PluginPanel.

Owns the BSA/BA2 contents viewer:
- Tab construction, treeview styling, search bar.
- Conflict-cache calculation across BSA + loose-file winners.
- Render mode dispatch (single mod, separator scope, or all mods with archives).

Host (PluginPanel) owns: ``self._game``, ``self._tabs``, ``self._log``,
``self._get_filemap_path``, ``self._plugin_mod_map``, ``self._plugin_entries``,
``self._plugin_extensions``, and the archive-tab state attributes initialised
in ``PluginPanel.__init__`` (``_archive_mod_name``, ``_bsa_index_path``,
``_arc_tree``, ``_arc_tree_expanded``, ``_arc_expand_btn``, ``_archive_label``,
``_bsa_conflict_cache``, ``_arc_search_var``, ``_arc_only_conflicts_var``,
``_archive_tab_dirty``, ``_archive_separator_name``, ``_archive_separator_mods``).
"""

import tkinter as tk
import tkinter.ttk as ttk
from pathlib import Path

import customtkinter as ctk
from PIL import Image as PilImage, ImageTk

import gui.theme as _theme
from gui.theme import (
    ACCENT,
    ACCENT_HOV,
    BG_DEEP,
    BG_HEADER,
    BG_HOVER,
    BG_LIST,
    BG_PANEL,
    BORDER,
    TEXT_DIM,
    TEXT_MAIN,
    SCROLL_BG,
    SCROLL_TROUGH,
    SCROLL_ACTIVE,
    TAG_BSA,
    TAG_FOLDER,
    scaled,
)
from gui.wheel_compat import LEGACY_WHEEL_REDUNDANT


class PluginPanelArchiveMixin:
    """BSA/BA2 archive contents viewer for PluginPanel."""

    def _update_archive_tab_visibility(self):
        """Add/remove the Archive tab to match the current game's archive support."""
        want = bool(self._game and getattr(self._game, "archive_extensions", None))
        try:
            present = "Archive" in self._tabs._name_list
        except Exception:
            present = False
        if want and not present:
            try:
                self._tabs.insert(1, "Archive")
            except Exception:
                self._tabs.add("Archive")
            self._build_archive_tab()
            self._archive_tab_dirty = False
            self._render_archive_tree(self._archive_mod_name)
        elif not want and present:
            try:
                self._tabs.delete("Archive")
            except Exception:
                pass
            self._arc_tree = None
            self._archive_label = None
            self._arc_expand_btn = None

    def _build_archive_tab(self):
        tab = self._tabs.tab("Archive")
        tab.configure(fg_color=BG_LIST)
        tab.grid_rowconfigure(1, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_columnconfigure(1, weight=0)

        toolbar = tk.Frame(tab, bg=BG_HEADER, height=scaled(28), highlightthickness=0)
        toolbar.grid(row=0, column=0, columnspan=2, sticky="ew")
        toolbar.grid_propagate(False)

        self._arc_tree_expanded = False
        self._arc_expand_btn = tk.Button(
            toolbar, text="⊞ Expand All",
            bg=BG_PANEL, fg=TEXT_MAIN, activebackground=BG_HOVER,
            relief="flat", font=(_theme.FONT_FAMILY, _theme.FS10),
            bd=0, cursor="hand2", highlightthickness=0,
            command=self._toggle_arc_tree_expand,
        )
        self._arc_expand_btn.pack(side="right", padx=(0, 8), pady=2)

        if self._arc_only_conflicts_var is None:
            self._arc_only_conflicts_var = tk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            toolbar, text="Show only conflicts",
            variable=self._arc_only_conflicts_var,
            width=140, height=20,
            checkbox_width=16, checkbox_height=16,
            font=("Cantarell", _theme.FS10),
            text_color=TEXT_MAIN,
            fg_color=ACCENT, hover_color=ACCENT_HOV,
            border_color=BORDER, checkmark_color="white",
            bg_color=BG_HEADER,
            command=lambda: self._render_archive_tree(self._archive_mod_name),
        ).pack(side="right", padx=(0, 8), pady=2)

        self._archive_label = tk.Label(
            toolbar, text="(no mod selected)",
            bg=BG_HEADER, fg=TEXT_DIM,
            font=(_theme.FONT_FAMILY, _theme.FS10),
            anchor="w",
        )
        self._archive_label.pack(side="left", padx=8, pady=4, fill="x", expand=True)

        from gui.ctk_components import _is_flatpak_sandbox
        style = ttk.Style()
        style.theme_use("default")
        use_default_indicator = _is_flatpak_sandbox()
        if not use_default_indicator:
            from gui.ctk_components import ICON_PATH as _ICON_PATH, _load_icon_image as _load_iim
            _im_open = _load_iim(_ICON_PATH.get("arrow"))
            _im_close = _im_open.rotate(90)
            _im_empty = PilImage.new("RGB", (15, 15), BG_DEEP)
            _img_open_arc = ImageTk.PhotoImage(_im_open, name="img_open_arc", size=(15, 15))
            _img_close_arc = ImageTk.PhotoImage(_im_close, name="img_close_arc", size=(15, 15))
            _img_empty_arc = ImageTk.PhotoImage(_im_empty, name="img_empty_arc", size=(15, 15))
            self._arc_arrow_images = (_img_open_arc, _img_close_arc, _img_empty_arc)
            try:
                style.element_create("Treeitem.arcindicator", "image", "img_close_arc",
                    ("user1", "img_open_arc"), ("user2", "img_empty_arc"),
                    sticky="w", width=15, height=15)
            except Exception:
                pass
        try:
            indicator_elem = "Treeitem.indicator" if use_default_indicator else "Treeitem.arcindicator"
            style.layout("Archive.Treeview.Item", [
                ("Treeitem.padding", {"sticky": "nsew", "children": [
                    (indicator_elem, {"side": "left", "sticky": "nsew"}),
                    ("Treeitem.image", {"side": "left", "sticky": "nsew"}),
                    ("Treeitem.focus", {"side": "left", "sticky": "nsew", "children": [
                        ("Treeitem.text", {"side": "left", "sticky": "nsew"}),
                    ]}),
                ]}),
            ])
        except Exception:
            pass

        _bg = BG_LIST
        _fg = TEXT_MAIN
        style.configure("Archive.Treeview",
            background=_bg, foreground=_fg,
            fieldbackground=_bg, borderwidth=0,
            rowheight=scaled(22), font=("Cantarell", _theme.FS10),
            focuscolor=_bg,
        )
        style.map("Archive.Treeview",
            background=[("selected", _bg), ("focus", _bg)],
            foreground=[("selected", ACCENT)],
        )

        self._arc_tree = ttk.Treeview(
            tab,
            style="Archive.Treeview",
            selectmode="browse",
            show="tree",
        )
        self._arc_tree.column("#0", stretch=True, minwidth=150)

        _sb_bg = SCROLL_BG
        _sb_trough = SCROLL_TROUGH
        _sb_active = SCROLL_ACTIVE
        vsb = tk.Scrollbar(
            tab, orient="vertical", command=self._arc_tree.yview,
            bg=_sb_bg, troughcolor=_sb_trough, activebackground=_sb_active,
            highlightthickness=0, bd=0,
        )
        self._arc_tree.configure(yscrollcommand=vsb.set)
        self._arc_tree.grid(row=1, column=0, sticky="nsew")
        vsb.grid(row=1, column=1, sticky="ns")

        if not LEGACY_WHEEL_REDUNDANT:
            self._arc_tree.bind("<Button-4>", lambda e: self._arc_tree.yview_scroll(-3, "units"))
            self._arc_tree.bind("<Button-5>", lambda e: self._arc_tree.yview_scroll(3, "units"))

        # Search bar (bottom) — filter by archive, folder or file name
        arc_search_bar = tk.Frame(tab, bg=BG_HEADER, highlightthickness=0)
        arc_search_bar.grid(row=2, column=0, columnspan=2, sticky="ew")
        tk.Label(
            arc_search_bar, text="Search:", bg=BG_HEADER, fg=TEXT_DIM,
            font=(_theme.FONT_FAMILY, _theme.FS10),
        ).pack(side="left", padx=(8, 4), pady=3)
        self._arc_search_var = tk.StringVar()
        self._arc_search_var.trace_add("write", self._on_arc_search_changed)
        _arc_search_entry = tk.Entry(
            arc_search_bar, textvariable=self._arc_search_var,
            bg=BG_DEEP, fg=TEXT_MAIN, insertbackground=TEXT_MAIN,
            relief="flat", font=(_theme.FONT_FAMILY, _theme.FS10),
            highlightthickness=0, highlightbackground=BG_DEEP,
        )
        _arc_search_entry.pack(side="left", padx=(0, 8), pady=3, fill="x", expand=True)
        _arc_search_entry.bind("<Escape>", lambda e: self._arc_search_var.set(""))
        def _arc_select_all(evt):
            evt.widget.select_range(0, tk.END)
            evt.widget.icursor(tk.END)
            return "break"
        _arc_search_entry.bind("<Control-a>", _arc_select_all)

        self._arc_tree.tag_configure("bsa", foreground=TAG_BSA)
        self._arc_tree.tag_configure("bsa_neutral", foreground=TEXT_MAIN)
        self._arc_tree.tag_configure("folder", foreground=TAG_FOLDER)
        self._arc_tree.tag_configure("conflict_win", foreground=_theme.conflict_higher)
        self._arc_tree.tag_configure("conflict_lose", foreground=_theme.conflict_lower)
        self._arc_tree.tag_configure("conflict_mixed", foreground=TAG_BSA)
        self._arc_tree.tag_configure("dim", foreground=TEXT_DIM)

    def _toggle_arc_tree_expand(self):
        if self._arc_tree is None:
            return
        self._arc_tree_expanded = not self._arc_tree_expanded
        open_state = self._arc_tree_expanded

        def _set_all(item):
            children = self._arc_tree.get_children(item)
            if children:
                self._arc_tree.item(item, open=open_state)
                for child in children:
                    _set_all(child)

        for top in self._arc_tree.get_children(""):
            _set_all(top)
        if self._arc_expand_btn is not None:
            self._arc_expand_btn.configure(
                text="⊟ Collapse All" if self._arc_tree_expanded else "⊞ Expand All"
            )

    def _bsa_owning_plugin_set(self, mod_names: set[str]) -> set[str]:
        """Return {plugin_filename_lower} for plugins in mod_names that own
        a BSA via basename match (exact, or '<stem> - <anything>').

        Plugins without a matching BSA don't load archive contents and so
        aren't participants in a BSA conflict.
        """
        if not mod_names:
            return set()
        bsa_path = self._bsa_index_path
        if bsa_path is None or not bsa_path.is_file():
            return set()
        from Utils.bsa_filemap import read_bsa_index, _bsa_owning_plugin
        bsa_index = read_bsa_index(bsa_path) or {}
        result: set[str] = set()
        for mod in mod_names:
            archives = bsa_index.get(mod)
            if not archives:
                continue
            # Plugin basenames (lowercase, no ext) owned by this mod.
            mod_plugins: set[str] = set()
            for plugin_name, pmod in self._plugin_mod_map.items():
                if pmod != mod:
                    continue
                stem = plugin_name.rsplit(".", 1)[0].lower()
                mod_plugins.add(stem)
            if not mod_plugins:
                continue
            # For each BSA, find the plugin that owns it and add that plugin
            # (with its original extension) to the result.
            for bsa_name, _mt, _paths in archives:
                bsa_stem = bsa_name.rsplit(".", 1)[0]
                owning_stem = _bsa_owning_plugin(bsa_stem, mod_plugins)
                if owning_stem is None:
                    continue
                for plugin_name, pmod in self._plugin_mod_map.items():
                    if pmod == mod and plugin_name.rsplit(".", 1)[0].lower() == owning_stem:
                        result.add(plugin_name.lower())
        return result

    def _get_bsa_conflict_cache(self):
        """Return (bsa_winner, loose_winner, contested) for the current profile.

        Cached on (bsa_index mtime, filemap mtime, modlist mtime) so repeated
        mod selections don't re-walk the index.
        """
        bsa_path = self._bsa_index_path
        fm_str = self._get_filemap_path()
        fm_path = Path(fm_str) if fm_str else None
        profile_dir = getattr(self._game, "_active_profile_dir", None)
        modlist_path = (profile_dir / "modlist.txt") if profile_dir else None

        def _mtime(p):
            try:
                return p.stat().st_mtime if p and p.is_file() else 0.0
            except OSError:
                return 0.0

        # Include plugin load order in the cache signature so reorders
        # invalidate this cache (BSA winners depend on plugin load order).
        plugin_order_sig = tuple(
            (e.name, e.enabled) for e in getattr(self, "_plugin_entries", [])
        )
        sig = (
            str(bsa_path) if bsa_path else None,
            _mtime(bsa_path) if bsa_path else 0.0,
            _mtime(fm_path) if fm_path else 0.0,
            _mtime(modlist_path) if modlist_path else 0.0,
            plugin_order_sig,
        )
        cached = self._bsa_conflict_cache
        if cached is not None and cached[0] == sig:
            return cached[1], cached[2], cached[3]

        from Utils.bsa_filemap import read_bsa_index, _compute_bsa_load_order
        from Utils.modlist import read_modlist

        bsa_index = read_bsa_index(bsa_path) if bsa_path else None
        bsa_winner: dict[str, str] = {}
        path_counts: dict[str, int] = {}
        if bsa_index and modlist_path and modlist_path.is_file():
            entries_ml = read_modlist(modlist_path)
            enabled = [e for e in entries_ml if not e.is_separator and e.enabled]
            priority_low_to_high = [e.name for e in reversed(enabled)]
            plugin_order = [e.name for e in getattr(self, "_plugin_entries", []) if e.enabled]
            plugin_exts = frozenset(
                e.lower() for e in getattr(self, "_plugin_extensions", []) or []
            )
            loose_index_path = (
                Path(fm_str).parent / "modindex.bin"
                if fm_str else None
            )
            scan_units = _compute_bsa_load_order(
                bsa_index, priority_low_to_high,
                plugin_order or None, plugin_exts or None,
                loose_index_path,
            )
            # path_counts tracks how many distinct mods ship a given BSA path
            # (for "contested" display). A mod with multiple BSAs appears as
            # multiple scan units, and two BSAs in the same mod overlapping
            # on a path must only count once — hence the per-mod seen set.
            seen_by_mod: dict[str, set[str]] = {}
            for name, mod_archives in scan_units:
                if not mod_archives:
                    continue
                sset = seen_by_mod.setdefault(name, set())
                for _bsa, _mt, paths in mod_archives:
                    for fp in paths:
                        bsa_winner[fp] = name
                        if fp not in sset:
                            sset.add(fp)
                            path_counts[fp] = path_counts.get(fp, 0) + 1

        loose_winner: dict[str, str] = {}
        if fm_path and fm_path.is_file():
            try:
                for line in fm_path.read_text(encoding="utf-8").splitlines():
                    if "\t" in line:
                        rk, mn = line.split("\t", 1)
                        loose_winner[rk.lower()] = mn
            except Exception:
                pass

        contested = {p for p, c in path_counts.items() if c > 1}
        contested.update(p for p in bsa_winner if p in loose_winner)

        self._bsa_conflict_cache = (sig, bsa_winner, loose_winner, contested)
        return bsa_winner, loose_winner, contested

    def show_mod_archives(self, mod_name: str | None):
        """Populate the Archive tab for the given mod name (lazy: only renders
        when the Archive tab is visible; otherwise flags dirty)."""
        self._archive_mod_name = mod_name
        # Switching to a single-mod (or no) selection clears any active
        # separator scope so the regular all-mods fallback works.
        self._archive_separator_name = None
        self._archive_separator_mods = None
        if self._arc_tree is None:
            return
        try:
            current = self._tabs.get()
        except Exception:
            current = ""
        if current != "Archive":
            self._archive_tab_dirty = True
            return
        self._archive_tab_dirty = False
        self._render_archive_tree(mod_name)

    def show_mod_archives_for_separator(
        self, separator_name: str, mod_names: list[str],
    ):
        """Populate the Archive tab with every BSA owned by any mod under the
        given separator. Lazy: only renders when the Archive tab is visible."""
        self._archive_mod_name = None
        self._archive_separator_name = separator_name
        self._archive_separator_mods = list(mod_names)
        if self._arc_tree is None:
            return
        try:
            current = self._tabs.get()
        except Exception:
            current = ""
        if current != "Archive":
            self._archive_tab_dirty = True
            return
        self._archive_tab_dirty = False
        self._render_archive_tree(None)

    def _archive_term(self) -> str:
        """Return the human-readable name for this game's archive format —
        'BA2' for Fallout 4 / Starfield, 'BSA' otherwise."""
        archive_exts = getattr(self._game, "archive_extensions", None) if self._game else None
        if archive_exts and ".ba2" in archive_exts:
            return "BA2"
        return "BSA"

    def _render_archive_tree(self, mod_name: str | None):
        """Actually populate the Archive treeview."""
        if self._arc_tree is None or self._archive_label is None:
            return
        self._arc_tree.delete(*self._arc_tree.get_children())

        term = self._archive_term()

        bsa_path = self._bsa_index_path
        if bsa_path is None or not bsa_path.is_file():
            self._archive_label.configure(text=f"(no {term} index yet — refresh to scan)")
            return

        from Utils.bsa_filemap import read_bsa_index
        bsa_index = read_bsa_index(bsa_path) or {}

        enabled_mods: set[str] = set()
        profile_dir = getattr(self._game, "_active_profile_dir", None)
        modlist_path = (profile_dir / "modlist.txt") if profile_dir else None
        if modlist_path and modlist_path.is_file():
            try:
                from Utils.modlist import read_modlist
                enabled_mods = {
                    e.name for e in read_modlist(modlist_path)
                    if not e.is_separator and e.enabled
                }
            except Exception:
                enabled_mods = set()

        my_archives = (
            bsa_index.get(mod_name)
            if mod_name and mod_name in enabled_mods
            else None
        )

        bsa_winner, loose_winner, contested = self._get_bsa_conflict_cache()

        def _conflict_tag(path: str, owner: str) -> str | None:
            if path not in contested:
                return None
            loose_mod = loose_winner.get(path)
            if loose_mod is not None and loose_mod != owner:
                return "conflict_lose"
            winner = bsa_winner.get(path)
            if winner is None:
                return None
            if loose_mod == owner:
                return "conflict_win"
            return "conflict_win" if winner == owner else "conflict_lose"

        only_conflicts = bool(
            self._arc_only_conflicts_var and self._arc_only_conflicts_var.get()
        )
        query = ""
        if self._arc_search_var is not None:
            query = self._arc_search_var.get().casefold()

        sep_name = getattr(self, "_archive_separator_name", None)
        sep_mods = getattr(self, "_archive_separator_mods", None)

        # Three view modes:
        #  1. Separator selected → show every archive owned by a child mod.
        #  2. Single mod with archives → scope to that mod.
        #  3. Otherwise → show all enabled mods with archives (the existing fallback).
        # Conflict colouring is per-archive-owner in all modes.
        if sep_name is not None and sep_mods is not None:
            scoped = [
                m for m in sep_mods
                if m in bsa_index and bsa_index.get(m) and m in enabled_mods
            ]
            scoped.sort(key=str.casefold)
            render_units = [(m, bsa_index[m]) for m in scoped]
            show_owner = True
            if render_units:
                self._archive_label.configure(
                    text=f"{sep_name} — {len(render_units)} mod(s) with {term}s"
                )
            else:
                self._archive_label.configure(
                    text=f"{sep_name} — no mods with {term} archives"
                )
                return
        elif my_archives:
            self._archive_label.configure(text=mod_name)
            render_units = [(mod_name, my_archives)]
            show_owner = False
        else:
            all_mods = [
                m for m in bsa_index
                if bsa_index.get(m) and m in enabled_mods
            ]
            all_mods.sort(key=str.casefold)
            render_units = [(m, bsa_index[m]) for m in all_mods]
            show_owner = True
            if render_units:
                if mod_name:
                    self._archive_label.configure(
                        text=f"{mod_name} — no {term} archives (showing all {len(render_units)} mods with {term}s)"
                    )
                else:
                    self._archive_label.configure(
                        text=f"(all {len(render_units)} mods with {term}s)"
                    )
            else:
                self._archive_label.configure(
                    text=f"{mod_name} — no {term} archives" if mod_name else f"(no {term} archives)"
                )
                return

        self._arc_tree_expanded = False
        if self._arc_expand_btn is not None:
            self._arc_expand_btn.configure(text="⊞ Expand All")

        def _insert(parent_iid, name, node, owner):
            folder_iid = self._arc_tree.insert(
                parent_iid, "end", text=name, open=False, tags=("folder",),
            )
            for child in sorted(k for k in node if k != "__files__"):
                _insert(folder_iid, child, node[child], owner)
            for fname, full_path in sorted(node.get("__files__", [])):
                tag = _conflict_tag(full_path, owner)
                self._arc_tree.insert(
                    folder_iid, "end", text=fname,
                    tags=(tag,) if tag else (),
                )

        rendered_any = False
        # Flatten (owner, bsa_name, paths) across all render units. When
        # show_owner is True we display every mod's BSAs together, so sort
        # by BSA filename (case-insensitive) for a true alphabetical list.
        # Otherwise (scoped to one mod) we keep per-BSA alphabetical order.
        flat_archives: list[tuple[str, str, list[str]]] = []
        for owner_mod, archives in render_units:
            for bsa_name, _mt, paths in archives:
                flat_archives.append((owner_mod, bsa_name, paths))
        flat_archives.sort(key=lambda t: t[1].casefold())

        for owner_mod, bsa_name, paths in flat_archives:
            bsa_matches_query = bool(query) and query in bsa_name.casefold()
            subtree: dict = {}
            for p in paths:
                if only_conflicts and _conflict_tag(p, owner_mod) is None:
                    continue
                if query and not bsa_matches_query and query not in p.casefold():
                    continue
                parts = p.split("/")
                node = subtree
                for part in parts[:-1]:
                    node = node.setdefault(part, {})
                node.setdefault("__files__", []).append((parts[-1], p))

            if only_conflicts and not subtree:
                continue
            if query and not bsa_matches_query and not subtree:
                continue

            rendered_any = True
            # Detect conflict status at the BSA level so the archive node
            # itself is coloured (any file in the BSA that loses/wins a
            # contested path colours the BSA row).
            has_win = False
            has_lose = False
            for p in paths:
                t = _conflict_tag(p, owner_mod)
                if t == "conflict_win":
                    has_win = True
                elif t == "conflict_lose":
                    has_lose = True
                if has_win and has_lose:
                    break
            if has_lose and has_win:
                bsa_tag = "conflict_mixed"
            elif has_lose:
                bsa_tag = "conflict_lose"
            elif has_win:
                bsa_tag = "conflict_win"
            elif show_owner:
                bsa_tag = "bsa_neutral"
            else:
                bsa_tag = "bsa"

            label = f"{bsa_name}  [{owner_mod}]" if show_owner else bsa_name
            bsa_iid = self._arc_tree.insert(
                "", "end", text=label, open=False, tags=(bsa_tag,),
            )

            for top in sorted(k for k in subtree if k != "__files__"):
                _insert(bsa_iid, top, subtree[top], owner_mod)
            for fname, full_path in sorted(subtree.get("__files__", [])):
                tag = _conflict_tag(full_path, owner_mod)
                self._arc_tree.insert(
                    bsa_iid, "end", text=fname,
                    tags=(tag,) if tag else (),
                )

        if not rendered_any:
            if query:
                self._arc_tree.insert("", "end", text="  (no matches)", tags=("dim",))
            elif only_conflicts:
                self._arc_tree.insert("", "end", text="  (no conflicts)", tags=("dim",))

        # When searching, expand everything so hits are visible without
        # the user having to click through folders.
        if query:
            self._arc_tree_expanded = True
            if self._arc_expand_btn is not None:
                self._arc_expand_btn.configure(text="⊟ Collapse All")

            def _open_all(item):
                self._arc_tree.item(item, open=True)
                for child in self._arc_tree.get_children(item):
                    _open_all(child)

            for top in self._arc_tree.get_children(""):
                _open_all(top)

    def _on_arc_search_changed(self, *_):
        """Re-render the Archive tree when the search query changes."""
        if self._arc_tree is None:
            return
        self._render_archive_tree(self._archive_mod_name)
