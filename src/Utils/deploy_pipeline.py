"""
Shared deploy orchestration used by the Deploy button, Run EXE (Play),
the BodySlide / DynDOLOD wizards, and the CLI.

`run_deploy_pipeline` performs the full restore → build_filemap → deploy →
wine-dll → root-folder → root-flagged → swap_launcher sequence. UI-specific
concerns (button enable/disable, status bar, mod panel reload) stay at the
call site.
"""

from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable, Optional

from Utils.deploy import (
    LinkMode,
    deploy_root_folder,
    deploy_root_flagged_mods,
    load_per_mod_strip_prefixes,
    restore_root_folder,
)
from Utils.filemap import build_filemap
from Utils.profile_backup import create_backup
from Utils.profile_state import read_excluded_mod_files
from Utils.ui_config import load_normalize_folder_case
from Utils.wine_dll_config import deploy_game_wine_dll_overrides


LogFn = Callable[[str], None]
ProgressFn = Callable[[int, int, Optional[str]], None]


def _make_ue5_conflict_key_fn(game, index_path: Path):
    """Build a (mod_name, rel_key) → ck callback for UE5 conflict detection.

    Uses _resolve_filemap_entries (whole-mod resolve) so include_siblings drag
    is honoured. Per-entry _resolve_entry can't see siblings, which gives the
    wrong destination for companion files like enabled.txt.

    ``index_path`` must point at the ``modindex.bin`` that sits next to the
    filemap being built (NOT next to modlist.txt, which lives in a profile
    subfolder).
    """
    from Utils.filemap import read_mod_index

    cache: dict[str, dict[str, str]] = {}
    index = None

    def _load(mod_name: str) -> dict[str, str]:
        nonlocal index
        if index is None:
            try:
                index = read_mod_index(index_path) or {}
            except Exception:
                index = {}
        entry = index.get(mod_name)
        if not entry:
            return {}
        normal, _ = entry
        # Build (staged_rel, mod_name) pairs from the raw on-disk paths.
        pairs = [(rel_str, mod_name) for _rk, rel_str in normal.items()]
        try:
            resolved = game._resolve_filemap_entries(pairs)
        except Exception:
            return {}
        out: dict[str, str] = {}
        for staged_rel, _mn, dest, final in resolved:
            rk = staged_rel.replace("\\", "/").lower()
            ck = (dest + "/" + final) if dest else final
            out[rk] = ck
        return out

    def _ck(mod_name: str, rel_key: str) -> str:
        m = cache.get(mod_name)
        if m is None:
            m = _load(mod_name)
            cache[mod_name] = m
        ck = m.get(rel_key)
        if ck is not None:
            return ck
        # Fallback to per-entry resolution (rare — entry not in cached mod map).
        dest, final = game._resolve_entry(rel_key)
        return (dest + "/" + final) if dest else final

    return _ck


def _build_filemap_for_game(game, profile, *, log_fn: LogFn) -> None:
    """Rebuild filemap.txt + filemap_root.txt for *profile* of *game*.

    Mirrors the call in top_bar._run_deploy: pulls excluded-files, root-flagged
    mods (Nexus), folder-case normalization toggle, UE5 conflict-key resolver.
    Errors are logged but not raised — partial filemap is still useful.
    """
    profile_root = game.get_profile_root()
    staging = game.get_effective_mod_staging_path()
    modlist_path = profile_root / "profiles" / profile / "modlist.txt"
    filemap_out = staging.parent / "filemap.txt"
    if not modlist_path.is_file():
        return

    try:
        from Nexus.nexus_meta import collect_root_flagged_mods
        from Games.ue5_game import UE5Game

        exc_raw = read_excluded_mod_files(modlist_path.parent, None)
        exc = {k: set(v) for k, v in exc_raw.items()} if exc_raw else None
        rf_mods = collect_root_flagged_mods(modlist_path, staging, log_fn=log_fn)
        norm_case = (
            getattr(game, "normalize_folder_case", True)
            and load_normalize_folder_case()
        )
        if isinstance(game, UE5Game):
            conflict_key_fn = _make_ue5_conflict_key_fn(
                game, filemap_out.parent / "modindex.bin",
            )
        else:
            _legacy = getattr(game, "filemap_conflict_key_fn", None)
            if _legacy is not None:
                def conflict_key_fn(_mod: str, rk: str, _f=_legacy) -> str:
                    return _f(rk)
            else:
                conflict_key_fn = None

        build_filemap(
            modlist_path, staging, filemap_out,
            strip_prefixes=game.mod_folder_strip_prefixes or None,
            per_mod_strip_prefixes=load_per_mod_strip_prefixes(modlist_path.parent),
            allowed_extensions=game.mod_install_extensions or None,
            root_deploy_folders=game.mod_root_deploy_folders or None,
            excluded_mod_files=exc,
            conflict_ignore_filenames=getattr(game, "conflict_ignore_filenames", None) or None,
            exclude_dirs=getattr(game, "filemap_exclude_dirs", None) or None,
            normalize_folder_case=norm_case,
            filemap_casing=getattr(game, "filemap_casing", "upper"),
            conflict_key_fn=conflict_key_fn,
            root_folder_mods=rf_mods or None,
        )
    except Exception as fm_err:
        log_fn(f"Filemap rebuild warning: {fm_err}")


def run_deploy_pipeline(
    game,
    profile: str,
    *,
    log_fn: LogFn,
    progress_fn: Optional[ProgressFn] = None,
    root_folder_enabled: bool = True,
    confirm_cet: Optional[Callable[[], bool]] = None,
    do_backup: bool = True,
    on_pre_filemap: Optional[Callable[[], None]] = None,
) -> bool:
    """Run the standard deploy sequence for *game* / *profile*.

    Parameters
    ----------
    log_fn / progress_fn
        Sinks for human-readable log lines and progress ticks. Callers supply
        thread-safe wrappers when invoked from a worker thread.
    root_folder_enabled
        Honors the Mod List panel's Root_Folder toggle; always True off the GUI.
    confirm_cet
        Optional blocking confirmation prompt (Cyberpunk CET symlink check).
        Return False to abort the deploy. None means "always proceed".
    do_backup
        If True, run `create_backup` for the profile dir before deploy.
    on_pre_filemap
        Optional hook fired *after* the profile switch but *before* the
        filemap rebuild. Used by wizards (e.g. BodySlide output redirect)
        to materialize a placeholder mod that needs to be in the filemap.

    Returns True on success, False on user-cancel / error. The active profile
    is always reset to *profile* before returning, even on error.
    """
    game_root = game.get_game_path()

    try:
        # Restore against the last-deployed profile so runtime files (saves,
        # ShaderCache, etc.) land in *that* profile's overwrite/ folder.
        last_deployed = game.get_last_deployed_profile()
        if last_deployed:
            game.set_active_profile_dir(
                game.get_profile_root() / "profiles" / last_deployed
            )
        if getattr(game, "restore_before_deploy", True) and hasattr(game, "restore"):
            try:
                if progress_fn is not None:
                    game.restore(log_fn=log_fn, progress_fn=progress_fn)
                else:
                    game.restore(log_fn=log_fn)
            except RuntimeError:
                pass
        last_root_folder_dir = game.get_effective_root_folder_path()
        if last_root_folder_dir.is_dir() and game_root:
            restore_root_folder(last_root_folder_dir, game_root, log_fn=log_fn)

        # Switch to the target profile before filemap + deploy.
        game.set_active_profile_dir(
            game.get_profile_root() / "profiles" / profile
        )

        if on_pre_filemap is not None:
            on_pre_filemap()

        _build_filemap_for_game(game, profile, log_fn=log_fn)

        if confirm_cet is not None and not confirm_cet():
            log_fn("Deploy: cancelled — CET requires Hardlink mode.")
            return False

        profile_dir = game.get_profile_root() / "profiles" / profile
        if do_backup:
            try:
                create_backup(profile_dir, log_fn)
            except Exception as backup_err:
                log_fn(f"Backup skipped: {backup_err}")

        deploy_mode = (
            game.get_deploy_mode()
            if hasattr(game, "get_deploy_mode")
            else LinkMode.HARDLINK
        )
        if progress_fn is not None:
            game.deploy(log_fn=log_fn, profile=profile, progress_fn=progress_fn,
                        mode=deploy_mode)
        else:
            game.deploy(log_fn=log_fn, profile=profile, mode=deploy_mode)

        pfx = game.get_prefix_path()
        if pfx and pfx.is_dir():
            deploy_game_wine_dll_overrides(
                game.name, pfx, game.wine_dll_overrides, log_fn=log_fn
            )

        game.save_last_deployed_profile(profile)

        target_rf = game.get_effective_root_folder_path()
        rf_allowed = getattr(game, "root_folder_deploy_enabled", True)

        # Step A: shared Root_Folder must run first — its log file is what
        # Step B's root-flagged-mods deploy merges into.
        if rf_allowed and root_folder_enabled and target_rf.is_dir() and game_root:
            count = deploy_root_folder(
                target_rf, game_root, mode=deploy_mode, log_fn=log_fn
            )
            if count:
                log_fn("Root Folder: transferred files to game root.")

        if game_root:
            filemap_root_path = (
                game.get_effective_filemap_path().parent / "filemap_root.txt"
            )
            staging = game.get_effective_mod_staging_path()
            strip = getattr(game, "mod_folder_strip_prefixes", None)
            per_mod_strip = load_per_mod_strip_prefixes(profile_dir)
            rf_count = deploy_root_flagged_mods(
                filemap_root_path, game_root, staging,
                mode=deploy_mode, strip_prefixes=strip,
                per_mod_strip_prefixes=per_mod_strip or None,
                log_fn=log_fn,
            )
            if rf_count:
                log_fn(f"Root-flagged mods: {rf_count} file(s) deployed to game root.")

        # Launcher swap last so SE/SKSE/etc. dlls are present first.
        if hasattr(game, "swap_launcher"):
            game.swap_launcher(log_fn)

        return True
    except Exception as e:
        log_fn(f"Deploy error: {e}\n{traceback.format_exc()}")
        return False
    finally:
        game.set_active_profile_dir(
            game.get_profile_root() / "profiles" / profile
        )
