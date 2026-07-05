"""
LOOT integration mixin for PluginPanel.

Owns:
- LOOT groups / plugin-rules overlays (open/close).
- LOOT-driven plugin sort (`_sort_plugins_loot`) and the persisted info cache
  read from / written to <profile>/loot.json (`_load_loot_messages`).
- Tooltip rendering and "is there anything to show?" gating
  (`_format_loot_tooltip`, `_has_loot_tooltip_content`) plus the helpers that
  evaluate LOOT requirement entries against the active profile (Nexus mod IDs
  enabled, staged file paths, files dropped in the game root).

Host (PluginPanel) owns:
- `self._loot_info` (initialised in __init__), `self._loot_info_icon`,
  `self._plugin_entries`, `self._plugins_path`, `self._plugin_locks`,
  `self._vanilla_plugins`, `self._staging_root`, `self._game`, `self._sel_idx`.
- The userlist helpers `_get_userlist_path`, `_parse_userlist`,
  `_write_userlist`, `_refresh_userlist_set`.
- UI hooks `_log`, `_safe_after`, `_refresh_plugins_tab`,
  `_on_plugin_row_selected_cb`, plus `_plugins_star_prefix` /
  `_plugins_include_vanilla` properties.
"""

import re
import threading
from pathlib import Path

from gui.game_helpers import _GAMES
from gui.loot_groups_overlay import LootGroupsOverlay
from gui.loot_plugin_rules_overlay import LootPluginRulesOverlay
from Utils.plugins import PluginEntry, write_plugins, write_loadorder
from LOOT.loot_sorter import (
    sort_plugins as loot_sort,
    find_overlapping_plugins as loot_find_overlaps,
    is_available as loot_available,
    write_loot_info as loot_write_info,
    read_loot_info as loot_read_info,
)
from Nexus.nexus_meta import read_meta


class PluginPanelLOOTMixin:
    """LOOT sort, masterlist info cache, tooltip rendering, and overlays."""

    # ------------------------------------------------------------------
    # LOOT groups / plugin-rules overlays
    # ------------------------------------------------------------------

    def _open_loot_groups_overlay(self):
        """Show the LOOT groups overlay over the modlist panel."""
        self._close_loot_groups_overlay()
        ul_path = self._get_userlist_path()
        if ul_path is None:
            self._log("No active profile — cannot configure groups.")
            return
        mod_panel = getattr(self.winfo_toplevel(), "_mod_panel", None)
        if mod_panel is None:
            self._log("Cannot find modlist panel.")
            return
        panel = LootGroupsOverlay(
            mod_panel,
            userlist_path=ul_path,
            parse_userlist=self._parse_userlist,
            write_userlist=self._write_userlist,
            on_close=self._close_loot_groups_overlay,
            on_saved=self._refresh_userlist_set,
        )
        panel.place(relx=0, rely=0, relwidth=1, relheight=1)
        panel.lift()
        self._loot_groups_overlay = panel

    def _close_loot_groups_overlay(self):
        panel = getattr(self, "_loot_groups_overlay", None)
        if panel:
            try:
                panel.destroy()
            except Exception:
                pass
        self._loot_groups_overlay = None

    def _open_loot_plugin_rules_overlay(self):
        """Show the LOOT plugin rules overlay over the modlist panel."""
        self._close_loot_plugin_rules_overlay()
        ul_path = self._get_userlist_path()
        if ul_path is None:
            self._log("No active profile — cannot configure plugin rules.")
            return
        mod_panel = getattr(self.winfo_toplevel(), "_mod_panel", None)
        if mod_panel is None:
            self._log("Cannot find modlist panel.")
            return
        plugin_names = [e.name for e in self._plugin_entries]
        sel_name = ""
        if hasattr(self, "_sel_idx") and 0 <= self._sel_idx < len(self._plugin_entries):
            sel_name = self._plugin_entries[self._sel_idx].name
        panel = LootPluginRulesOverlay(
            mod_panel,
            plugin_names=plugin_names,
            userlist_path=ul_path,
            parse_userlist=self._parse_userlist,
            write_userlist=self._write_userlist,
            selected_plugin=sel_name,
            on_close=self._close_loot_plugin_rules_overlay,
            on_saved=self._refresh_userlist_set,
        )
        panel.place(relx=0, rely=0, relwidth=1, relheight=1)
        panel.lift()
        self._loot_plugin_rules_overlay = panel
        self._on_plugin_row_selected_cb = panel.set_selected_plugin

    def _close_loot_plugin_rules_overlay(self):
        panel = getattr(self, "_loot_plugin_rules_overlay", None)
        if panel:
            try:
                panel.destroy()
            except Exception:
                pass
        self._loot_plugin_rules_overlay = None
        self._on_plugin_row_selected_cb = None

    # ------------------------------------------------------------------
    # LOOT sort
    # ------------------------------------------------------------------

    def _sort_plugins_loot(self):
        """Sort current plugin list using libloot's masterlist rules."""
        if not loot_available():
            self._log("LOOT library not available — cannot sort.")
            return

        if not self._plugins_path or not self._plugin_entries:
            self._log("No plugins loaded to sort.")
            return

        # Get current game from the top bar
        app = self.winfo_toplevel()
        topbar = app._topbar
        game_name = topbar._game_var.get()

        game = _GAMES.get(game_name)
        if not game or not game.is_configured():
            self._log(f"Game '{game_name}' is not configured.")
            return

        if not game.loot_sort_enabled:
            self._log(f"LOOT sorting is not supported for '{game_name}'.")
            return

        game_path = game.get_game_path()
        staging_root = game.get_effective_mod_staging_path()

        # Ensure vanilla plugins are present in the in-memory list before
        # sorting (they are never written to plugins.txt).
        existing_lower = {e.name.lower() for e in self._plugin_entries}
        _ext_order = {".esm": 0, ".esp": 1, ".esl": 2}
        vanilla_added = [
            PluginEntry(name=orig, enabled=True)
            for low, orig in sorted(
                self._vanilla_plugins.items(),
                key=lambda kv: (_ext_order.get(Path(kv[0]).suffix, 9), kv[0]),
            )
            if low not in existing_lower
        ]
        if vanilla_added:
            self._plugin_entries = vanilla_added + self._plugin_entries
            self._log(f"Added {len(vanilla_added)} vanilla plugin(s) for sort.")

        # Separate locked plugins (stay in place) from those LOOT will sort
        locked_indices: dict[int, PluginEntry] = {}
        unlocked_entries: list[PluginEntry] = []
        for i, e in enumerate(self._plugin_entries):
            if self._plugin_locks.get(e.name, False):
                locked_indices[i] = e
            else:
                unlocked_entries.append(e)

        if locked_indices:
            locked_names = [e.name for e in locked_indices.values()]
            self._log(f"Skipping {len(locked_indices)} locked plugin(s): "
                      + ", ".join(locked_names))

        # Build inputs from non-locked entries only
        plugin_names = [e.name for e in unlocked_entries]
        enabled_set = {e.name for e in unlocked_entries if e.enabled}

        active_profile_dir = getattr(game, "_active_profile_dir", None)
        _profile_ul = (active_profile_dir / "userlist.yaml") if active_profile_dir else None
        if _profile_ul and _profile_ul.is_file():
            userlist_path = _profile_ul
        else:
            from Utils.config_paths import get_loot_game_dir
            _global_ul = get_loot_game_dir(game.game_id) / "userlist.yaml"
            userlist_path = _global_ul if _global_ul.is_file() else None

        # Snapshot everything the worker needs — no Tk access from the thread.
        _profile_dir = self._plugins_path.parent
        _game_id = game.game_id
        _game_type_attr = game.loot_game_type
        _masterlist_url = game.loot_masterlist_url
        _masterlist_repo = getattr(game, "loot_masterlist_repo", "")
        _game_data_dir = (game.get_vanilla_plugins_path()
                          if hasattr(game, "get_vanilla_plugins_path") else None)

        from gui.ctk_components import CTkNotification
        _notif = CTkNotification(
            self.winfo_toplevel(),
            state="info",
            message=f"Running Loot on {len(plugin_names)} plugins",
        )

        def _close_notif():
            try:
                if _notif.winfo_exists():
                    _notif.destroy()
            except Exception:
                pass

        def _worker():
            try:
                result = loot_sort(
                    plugin_names=plugin_names,
                    enabled_set=enabled_set,
                    game_name=game_name,
                    game_path=game_path,
                    staging_root=staging_root,
                    log_fn=lambda m: self._safe_after(0, lambda msg=m: self._log(msg)),
                    game_type_attr=_game_type_attr,
                    game_id=_game_id,
                    masterlist_url=_masterlist_url,
                    masterlist_repo=_masterlist_repo,
                    game_data_dir=_game_data_dir,
                    userlist_path=userlist_path,
                )
            except RuntimeError as e:
                self._safe_after(0, _close_notif)
                self._safe_after(0, lambda err=e: self._log(f"LOOT sort failed: {err}"))
                return
            except Exception as e:
                self._safe_after(0, _close_notif)
                self._safe_after(0, lambda err=e: self._log(f"LOOT sort crashed: {err}"))
                return
            self._safe_after(0, _close_notif)
            self._safe_after(0, lambda r=result: _apply_result(r))

        def _apply_result(result):
            for w in result.warnings:
                self._log(f"Warning: {w}")

            # Persist evaluated LOOT metadata to <profile>/loot.json so the UI
            # can surface it without re-running a sort.
            try:
                loot_write_info(
                    _profile_dir,
                    result.plugin_info,
                    result.general_messages,
                    game_id=_game_id,
                )
                self._loot_info = {
                    k.lower(): v for k, v in result.plugin_info.items()
                }
            except OSError as e:
                self._log(f"Could not write loot.json: {e}")

            # Re-interleave: place locked plugins back at their original indices,
            # filling remaining slots with the LOOT-sorted unlocked plugins.
            name_to_enabled = {e.name: e.enabled for e in self._plugin_entries}
            sorted_unlocked = iter(
                PluginEntry(name=n, enabled=name_to_enabled.get(n, True))
                for n in result.sorted_names
            )
            total = len(self._plugin_entries)
            new_entries: list[PluginEntry] = []
            for i in range(total):
                if i in locked_indices:
                    new_entries.append(locked_indices[i])
                else:
                    new_entries.append(next(sorted_unlocked))

            _include_vanilla = self._plugins_include_vanilla

            # Count moves only across plugins the user actually sees in the
            # written load order. Vanilla plugins that get filtered out of
            # plugins.txt would otherwise inflate the count by reshuffling
            # internally without any visible change.
            def _visible(names):
                return [
                    n for n in names
                    if _include_vanilla or n.lower() not in self._vanilla_plugins
                ]
            _before = _visible(plugin_names)
            _after = _visible(result.sorted_names)
            visible_moved = sum(
                1 for i, n in enumerate(_after)
                if i >= len(_before) or _before[i] != n
            )

            # Whether the *full* order (vanilla included) changed. LOOT pins
            # vanilla masters to canonical positions, so a re-sort can leave
            # every mod in place (visible_moved == 0) while still repositioning
            # vanilla plugins. We still want to commit that so the panel shows
            # the canonical vanilla order rather than a stale interleaving.
            _full_changed = [e.name for e in self._plugin_entries] != [
                e.name for e in new_entries
            ]

            if visible_moved == 0 and not locked_indices:
                # No mod the user manages moved — report "already sorted", but
                # still persist if only vanilla plugins shifted (cosmetic).
                if _full_changed:
                    self._plugin_entries = new_entries
                    write_loadorder(
                        self._plugins_path.parent / "loadorder.txt", new_entries,
                    )
                self._log("Load order is already sorted.")
                self._refresh_plugins_tab()
                _done_notif = CTkNotification(
                    self.winfo_toplevel(),
                    state="info",
                    message="Load order is already sorted",
                )
                self.after(4000, lambda n=_done_notif: n.winfo_exists() and n.destroy())
                return

            self._plugin_entries = new_entries
            write_plugins(self._plugins_path, [
                e for e in new_entries
                if _include_vanilla or e.name.lower() not in self._vanilla_plugins
            ], star_prefix=self._plugins_star_prefix)
            write_loadorder(
                self._plugins_path.parent / "loadorder.txt", new_entries,
            )
            self._refresh_plugins_tab()
            self._log(f"Sorted — {visible_moved} plugin(s) changed position.")
            _moved = visible_moved
            _done_notif = CTkNotification(
                self.winfo_toplevel(),
                state="success",
                message=f"Sorted — {_moved} plugin{'s' if _moved != 1 else ''} moved",
            )
            self.after(4000, lambda n=_done_notif: n.winfo_exists() and n.destroy())

        self._log("Sorting plugins with LOOT (running in background)...")
        threading.Thread(target=_worker, daemon=True).start()

    # ------------------------------------------------------------------
    # Record overlap (which plugins conflict at the FormID level)
    # ------------------------------------------------------------------

    def _show_overlapping_plugins(self, plugin_name: str):
        """Find and highlight plugins whose records overlap with `plugin_name`.

        Requires a full libloot plugin load (record bodies), so it runs on a
        background thread with a notification; results are highlighted in the
        load-order list.
        """
        if not loot_available():
            self._log("LOOT library not available — cannot check overlap.")
            return
        if not self._plugins_path or not self._plugin_entries:
            return

        app = self.winfo_toplevel()
        game_name = app._topbar._game_var.get()
        game = _GAMES.get(game_name)
        if not game or not game.is_configured():
            self._log(f"Game '{game_name}' is not configured.")
            return
        if not game.loot_sort_enabled:
            self._log(f"LOOT is not supported for '{game_name}'.")
            return

        # Snapshot everything the worker needs — no Tk access from the thread.
        plugin_names = [e.name for e in self._plugin_entries]
        game_path = game.get_game_path()
        staging_root = game.get_effective_mod_staging_path()
        game_type_attr = game.loot_game_type
        game_data_dir = (game.get_vanilla_plugins_path()
                         if hasattr(game, "get_vanilla_plugins_path") else None)

        from gui.ctk_components import CTkNotification
        _notif = CTkNotification(
            self.winfo_toplevel(),
            state="info",
            message=f"Checking record overlap for {plugin_name}...",
        )

        def _close_notif():
            try:
                if _notif.winfo_exists():
                    _notif.destroy()
            except Exception:
                pass

        def _worker():
            try:
                overlaps = loot_find_overlaps(
                    target_plugin=plugin_name,
                    plugin_names=plugin_names,
                    game_name=game_name,
                    game_path=game_path,
                    staging_root=staging_root,
                    log_fn=lambda m: self._safe_after(0, lambda msg=m: self._log(msg)),
                    game_type_attr=game_type_attr,
                    game_data_dir=game_data_dir,
                )
            except Exception as e:
                self._safe_after(0, _close_notif)
                self._safe_after(0, lambda err=e: self._log(f"Overlap check failed: {err}"))
                return
            self._safe_after(0, _close_notif)
            self._safe_after(0, lambda ov=overlaps: self._apply_overlap_result(plugin_name, ov))

        self._log(f"Checking record overlap for {plugin_name} (running in background)...")
        threading.Thread(target=_worker, daemon=True).start()

    def _apply_overlap_result(self, plugin_name: str, overlaps: list[str]):
        from gui.ctk_components import CTkNotification
        if not overlaps:
            self._log(f"{plugin_name}: no record overlap with other plugins.")
            _n = CTkNotification(
                self.winfo_toplevel(), state="info",
                message=f"{plugin_name}: no record overlap",
            )
            self.after(4000, lambda n=_n: n.winfo_exists() and n.destroy())
            return

        # Highlight the target + overlapping plugins in the load-order list.
        names_lower = {plugin_name.lower(), *(o.lower() for o in overlaps)}
        sel = {
            i for i, e in enumerate(self._plugin_entries)
            if e.name.lower() in names_lower
        }
        if sel:
            self._psel_set = sel
            self._sel_idx = min(sel)
            # Scroll the first highlighted plugin into view (a couple of rows
            # above it for context). yview_moveto takes a fraction of the total
            # scroll height, which is len(entries) rows tall.
            n = len(self._plugin_entries)
            if n > 0:
                frac = max(0, self._sel_idx - 2) / n
                try:
                    self._pcanvas.yview_moveto(frac)
                except Exception:
                    pass
            self._predraw()

        self._log(
            f"{plugin_name} overlaps with {len(overlaps)} plugin(s): "
            + ", ".join(overlaps)
        )
        _n = CTkNotification(
            self.winfo_toplevel(), state="warning",
            message=f"{plugin_name} overlaps {len(overlaps)} plugin(s) — highlighted in list",
        )
        self.after(5000, lambda n=_n: n.winfo_exists() and n.destroy())

    # ------------------------------------------------------------------
    # LOOT tooltip — formatting, content gating, and requirement helpers
    # ------------------------------------------------------------------

    def _format_loot_tooltip(self, info: dict) -> str:
        """Render a loot.json plugin-info dict into a multi-section tooltip string."""
        sections: list[str] = []

        msgs = info.get("messages") or []
        if msgs:
            lines = []
            for m in msgs:
                prefix = {"error": "[!]", "warn": "[!]", "say": "[i]"}.get(
                    m.get("type", "say"), "[i]")
                lines.append(f"{prefix} {m.get('text', '')}")
            sections.append("LOOT messages:\n" + "\n".join(lines))

        # Cache sets used by both requirements and incompatibilities blocks.
        enabled_lower = {
            e.name.lower() for e in self._plugin_entries if e.enabled
        }
        enabled_mod_ids = self._get_enabled_nexus_mod_ids()

        reqs = info.get("requirements") or []
        if reqs:
            staged_paths = self._get_staged_paths()
            lines = []
            for r in reqs:
                raw = r.get("name", "")
                display = r.get("display_name") or raw
                if self._is_requirement_satisfied(
                    raw, display, enabled_lower, enabled_mod_ids, staged_paths
                ):
                    continue
                # Clean a Filename(...) wrapper if it leaked into display.
                dm = re.match(r'^Filename\(["\'](.+?)["\']\)$', display)
                if dm:
                    display = dm.group(1)
                line = f"  - {display}"
                detail = r.get("detail", "")
                if detail:
                    line += f" ({detail})"
                lines.append(line)
            if lines:
                sections.append("Requires (missing):\n" + "\n".join(lines))

        incs = info.get("incompatibilities") or []
        if incs:
            # Only surface incompatibilities that are actually active — i.e.
            # the other plugin is present and enabled in this profile.
            lines = []
            for i in incs:
                raw = i.get("name", "")
                display = i.get("display_name") or raw
                # libloot Filename names come through as Filename("foo.esp"); extract the inner name.
                m = re.match(r'^Filename\(["\'](.+?)["\']\)$', raw)
                fname = m.group(1) if m else raw
                fname_lower = fname.lower().lstrip("./").lstrip("../")
                if fname_lower not in enabled_lower:
                    continue
                # If display is still the Filename(...) wrapper, show the clean name instead.
                dm = re.match(r'^Filename\(["\'](.+?)["\']\)$', display)
                if dm:
                    display = dm.group(1)
                line = f"  - {display}"
                detail = i.get("detail", "")
                if detail:
                    line += f" ({detail})"
                lines.append(line)
            if lines:
                sections.append("Incompatible with (currently active):\n" + "\n".join(lines))

        # Dirty edits — CRC-filtered by libloot, so these apply to the
        # installed version of this plugin.
        dirty = info.get("dirty") or []
        if dirty:
            lines = []
            for d in dirty:
                parts = []
                if d.get("itm"):
                    parts.append(f"{d['itm']} ITM")
                if d.get("udr"):
                    parts.append(f"{d['udr']} UDR")
                if d.get("nav"):
                    parts.append(f"{d['nav']} deleted navmesh")
                counts = ", ".join(parts) if parts else "needs cleaning"
                line = f"  - {counts}"
                util = d.get("utility", "")
                if util:
                    # Strip a [label](url) markdown wrapper to the bare label.
                    um = re.match(r'^\[(.+?)\]\(.+?\)$', util)
                    line += f" — clean with {um.group(1) if um else util}"
                lines.append(line)
                detail = d.get("detail", "")
                if detail:
                    lines.append(f"    {detail}")
            sections.append("Dirty edits:\n" + "\n".join(lines))

        # Bash Tags — current header tags plus masterlist add/remove suggestions.
        tags = info.get("tags") or {}
        if tags:
            lines = []
            cur = tags.get("current") or []
            add = tags.get("add") or []
            rem = tags.get("remove") or []
            if cur:
                lines.append("  Current: " + ", ".join(cur))
            if add:
                lines.append("  Suggested (add): " + ", ".join(f"+{t}" for t in add))
            if rem:
                lines.append("  Suggested (remove): " + ", ".join(f"-{t}" for t in rem))
            if lines:
                sections.append("Bash Tags:\n" + "\n".join(lines))

        return "\n\n".join(sections)

    def _get_enabled_nexus_mod_ids(self) -> set[int]:
        """Return the set of Nexus mod_ids for mods enabled in the current profile.

        Result is cached against modlist.txt's mtime; the underlying per-mod
        ``mod_name → mod_id`` map is cached per meta.ini mtime so a plain mod
        toggle (which rewrites modlist.txt but touches no meta.ini) re-derives
        the id set from the cached map without re-parsing any meta.ini file.
        """
        modlist_path = (
            self._plugins_path.parent / "modlist.txt"
            if self._plugins_path is not None else None
        )
        try:
            ml_mtime = modlist_path.stat().st_mtime if modlist_path else 0.0
        except OSError:
            ml_mtime = 0.0
        cached = getattr(self, "_enabled_mod_ids_cache", None)
        if cached is not None and getattr(self, "_enabled_mod_ids_cache_mtime", None) == ml_mtime:
            return cached

        # Persistent per-mod id map: mod_name → (meta_mtime, mod_id|None).
        # Survives across refreshes; only re-reads a meta.ini whose mtime moved.
        id_map: dict[str, tuple[float, int | None]] = getattr(self, "_mod_id_map", None) or {}
        ids: set[int] = set()
        if self._plugins_path is not None:
            staging_root = self._staging_root
            if staging_root and staging_root.is_dir() and modlist_path and modlist_path.is_file():
                try:
                    from Utils.modlist import read_modlist
                    entries = read_modlist(modlist_path)
                    for e in entries:
                        if not e.enabled:
                            continue
                        meta_path = staging_root / e.name / "meta.ini"
                        try:
                            m_mtime = meta_path.stat().st_mtime
                        except OSError:
                            id_map.pop(e.name, None)
                            continue
                        cached_entry = id_map.get(e.name)
                        if cached_entry is None or cached_entry[0] != m_mtime:
                            mod_id_val: int | None = None
                            try:
                                meta = read_meta(meta_path)
                                if meta.mod_id:
                                    mod_id_val = int(meta.mod_id)
                            except Exception:
                                mod_id_val = None
                            id_map[e.name] = (m_mtime, mod_id_val)
                            cached_entry = id_map[e.name]
                        if cached_entry[1]:
                            ids.add(cached_entry[1])
                except Exception:
                    pass
        self._mod_id_map = id_map
        self._enabled_mod_ids_cache = ids
        self._enabled_mod_ids_cache_mtime = ml_mtime
        return ids

    def _invalidate_enabled_mod_ids(self) -> None:
        # mtime-validated caches self-heal, so a plain plugin-tab refresh no
        # longer needs to clear them (that forced a full modlist + 300×meta.ini
        # re-parse and a 74k-line filemap re-parse on every mod toggle). Kept as
        # a no-op so any external caller is harmless; the getters re-derive
        # against modlist/filemap mtimes.
        return

    def _get_staged_paths(self) -> set[str]:
        """Return the lowercase set of relative paths currently staged.

        Used to resolve LOOT "Requires" entries that name a specific file
        (e.g. 'SKSE/Plugins/PapyrusUtil.dll') rather than a plugin or a
        Nexus link. Paths are normalised to forward slashes and lowercased.
        """
        # Validate the cache against the filemap's mtime rather than clearing it
        # on every plugin-tab refresh. The staged-path set only changes when
        # filemap.txt changes, so re-parsing its 74k lines on every mod toggle
        # (when the relevant content is identical) is wasted work.
        filemap_path = (
            self._staging_root.parent / "filemap.txt"
            if self._staging_root is not None else None
        )
        try:
            fm_mtime = filemap_path.stat().st_mtime if filemap_path else 0.0
        except OSError:
            fm_mtime = 0.0
        cached = getattr(self, "_staged_paths_cache", None)
        if cached is not None and getattr(self, "_staged_paths_cache_mtime", None) == fm_mtime:
            return cached
        paths: set[str] = set()
        if (self._staging_root is not None and self._staging_root.is_dir()
                and filemap_path and filemap_path.is_file()):
            # Reuse the panel's shared mtime-keyed parse instead of re-reading
            # the (large) filemap directly — see PluginPanel._get_parsed_filemap.
            for rel, _mod in self._get_parsed_filemap(filemap_path):
                rel = rel.strip()
                if rel:
                    paths.add(rel.replace("\\", "/").lower())
        self._staged_paths_cache = paths
        self._staged_paths_cache_mtime = fm_mtime
        return paths

    def _get_game_root_files(self) -> set[str]:
        """Return lowercase filenames sitting directly in the game's root folder.

        Many users drop loaders like skse64_loader.exe straight into the game
        root rather than deploying them as a mod, so LOOT requirements such as
        "Skyrim Script Extender" should be treated as satisfied if that file is
        present. Top-level only — we don't recurse into subfolders.
        """
        game = getattr(self, "_game", None)
        game_path = None
        if game is not None and hasattr(game, "get_game_path"):
            try:
                game_path = game.get_game_path()
            except Exception:
                game_path = None
        # Self-validate against the game root's dir mtime so a loader dropped in
        # mid-session is still picked up, without re-listing the dir every refresh.
        try:
            root_mtime = Path(game_path).stat().st_mtime if game_path else 0.0
        except OSError:
            root_mtime = 0.0
        cached = getattr(self, "_game_root_files_cache", None)
        if cached is not None and getattr(self, "_game_root_files_cache_mtime", None) == root_mtime:
            return cached
        names: set[str] = set()
        if game_path is not None:
            root = Path(game_path)
            if root.is_dir():
                try:
                    for entry in root.iterdir():
                        if entry.is_file():
                            names.add(entry.name.lower())
                except OSError:
                    pass
        self._game_root_files_cache = names
        self._game_root_files_cache_mtime = root_mtime
        return names

    @staticmethod
    def _extract_nexus_mod_id(text: str) -> int | None:
        """Pull a Nexus mod_id out of a URL or markdown link, if present."""
        if not text:
            return None
        m = re.search(r"nexusmods\.com/[^/\s)]+/mods/(\d+)", text)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
        return None

    def _is_requirement_satisfied(
        self,
        raw: str,
        display: str,
        enabled_lower: set[str],
        enabled_mod_ids: set[int],
        staged_paths: set[str],
    ) -> bool:
        """True if a LOOT requirement entry is met in the current profile.

        Checks these forms in order:
          1. Filename("foo.esp") → an enabled plugin by that name
          2. Filename("SKSE/Plugins/foo.dll") → a staged file by that rel path,
             or a top-level file in the game root (basename match)
          3. Nexus URL → an enabled mod with that mod_id
          4. Script-extender heuristic → skse/skyui/f4se loader in game root
        """
        m = re.match(r'^Filename\(["\'](.+?)["\']\)$', raw)
        if m:
            inner = m.group(1).replace("\\", "/").lstrip("./").lstrip("../")
            inner_lower = inner.lower()
            if inner_lower in enabled_lower:
                return True
            if inner_lower in staged_paths:
                return True
            # Basename-only check against files in the game root (top-level).
            base = inner_lower.rsplit("/", 1)[-1]
            if base and base in self._get_game_root_files():
                return True
        mod_id = self._extract_nexus_mod_id(display) or self._extract_nexus_mod_id(raw)
        if mod_id is not None and mod_id in enabled_mod_ids:
            return True
        # Script extenders (SKSE/SKSE64/F4SE/OBSE/etc.) — defer to the same
        # framework detection that drives the green/red status banner, so the
        # "missing" line is suppressed whenever the extender is actually
        # installed: in the game root, Root_Folder staging, the enabled filemap,
        # or even a disabled mod. Without this, an extender deployed as a mod
        # (rather than dropped loose in the game root) read as missing here even
        # though the banner showed it installed.
        text = f"{display} {raw}".lower()
        if "script extender" in text or re.search(r"\bsk?se\b|\bf4se\b|\bobse\b|\bnvse\b", text):
            if self._script_extender_detected():
                return True
        return False

    def _has_loot_tooltip_content(self, plugin_name: str) -> bool:
        """True if the LOOT info for this plugin would render any tooltip section.

        Mirrors the filtering done in _format_loot_tooltip so the flag icon
        only lights up when there's something to show:
          - messages always count
          - a requirement counts only if not satisfied by an enabled plugin,
            staged file, or enabled Nexus mod
          - an incompatibility counts only if the conflicting plugin is enabled

        enabled_lower is cached keyed on the tuple of enabled flags so that
        calling this method 60+ times per _predraw doesn't recompute the
        1300-plugin lowercase set; in-place toggles invalidate the cache.
        """
        info = self._loot_info.get(plugin_name.lower())
        if not info:
            return False
        if info.get("messages"):
            return True

        sig = (len(self._plugin_entries), tuple(e.enabled for e in self._plugin_entries))
        if getattr(self, "_enabled_lower_cache_sig", None) != sig:
            self._enabled_lower_cache = {
                e.name.lower() for e in self._plugin_entries if e.enabled
            }
            self._enabled_lower_cache_sig = sig
        enabled_lower = self._enabled_lower_cache
        enabled_mod_ids: set[int] | None = None
        staged_paths: set[str] | None = None

        reqs = info.get("requirements") or []
        for r in reqs:
            raw = r.get("name", "")
            display = r.get("display_name") or raw
            if enabled_mod_ids is None:
                enabled_mod_ids = self._get_enabled_nexus_mod_ids()
            if staged_paths is None:
                staged_paths = self._get_staged_paths()
            if not self._is_requirement_satisfied(
                raw, display, enabled_lower, enabled_mod_ids, staged_paths
            ):
                return True

        incs = info.get("incompatibilities") or []
        if incs:
            for i in incs:
                raw = i.get("name", "")
                m = re.match(r'^Filename\(["\'](.+?)["\']\)$', raw)
                fname = (m.group(1) if m else raw).lower().lstrip("./").lstrip("../")
                if fname in enabled_lower:
                    return True
        return False

    def _has_dirty_edits(self, plugin_name: str) -> bool:
        """True if the plugin has CRC-matched dirty info in the masterlist.

        Drives the brush flag icon, which is shown separately from the generic
        LOOT-info flag so dirty plugins are visually distinct.
        """
        info = self._loot_info.get(plugin_name.lower())
        return bool(info and info.get("dirty"))

    def _has_bash_tags(self, plugin_name: str) -> bool:
        """True if the plugin has any current or suggested Bash Tags.

        Drives the tag flag icon, shown separately from the generic LOOT-info
        flag so Bash-tagged plugins are visually distinct.
        """
        info = self._loot_info.get(plugin_name.lower())
        return bool(info and info.get("tags"))

    def _load_loot_messages(self) -> None:
        """Populate self._loot_info from <profile>/loot.json (if present)."""
        if self._plugins_path is None:
            self._loot_info = {}
            return
        data = loot_read_info(self._plugins_path.parent)
        plugins = data.get("plugins", {}) if isinstance(data, dict) else {}
        version = data.get("version", 1) if isinstance(data, dict) else 1
        out: dict[str, dict] = {}
        if version >= 2:
            for k, v in plugins.items():
                if isinstance(v, dict) and v:
                    out[k.lower()] = v
        else:
            # v1: plugin value was a raw message list
            for k, v in plugins.items():
                if isinstance(v, list) and v:
                    out[k.lower()] = {"messages": v}
        self._loot_info = out
