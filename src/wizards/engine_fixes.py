"""
Engine Fixes (SSE) configuration wizard.

Presents every setting in ``EngineFixes.toml`` (the powerofthree / aers Engine
Fixes SKSE plugin) as a typed control with the short description that ships
inline in the toml, and writes the result into a managed mod:

    <staging>/EngineFixes toml/SKSE/Plugins/EngineFixes.toml

Unlike the SSE Display Tweaks wizard, every Engine Fixes setting is a real
value toggle (mostly booleans), so there is no per-row enable/comment-out
control — the value itself is what's written. The wizard rewrites values in
place over a fully-documented template so the inline help comments survive.

The form is seeded, in order of preference, from:
    1. the managed mod's own toml (so it round-trips for editing),
    2. the currently-winning toml in the filemap (what would actually deploy),
    3. the bundled default schema values.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

if TYPE_CHECKING:
    from Games.base_game import BaseGame

from gui.theme import (
    ACCENT, ACCENT_HOV, BG_DEEP, BG_HEADER, BG_PANEL,
    TEXT_ON_ACCENT, TEXT_DIM, TEXT_MAIN,
    FONT_NORMAL, FONT_BOLD, FONT_SMALL,
)
from gui.wheel_compat import bind_scrollable_wheel

MOD_NAME = "EngineFixes toml"
REL_TOML_PATH = "SKSE/Plugins/EngineFixes.toml"
REL_DLL_PATH = "SKSE/Plugins/EngineFixes.dll"

_OK_GREEN = "#6bc76b"
_ERR_RED = "#e06c6c"


# ---------------------------------------------------------------------------
# Setting schema
# ---------------------------------------------------------------------------

class Setting:
    """One configurable toml key.

    kind: "bool" | "int" | "float"
    """

    __slots__ = ("section", "key", "kind", "default", "desc")

    def __init__(self, section, key, kind, default, desc):
        self.section = section
        self.key = key
        self.kind = kind
        self.default = default
        self.desc = desc

    @property
    def id(self) -> tuple[str, str]:
        return (self.section, self.key)


# Ordered list of all settings, grouped by section. Descriptions are the inline
# comments shipped in EngineFixes.toml.
SCHEMA: list[Setting] = [
    # ---- [General] ----
    Setting("General", "bVerboseLogging", "bool", "false",
            "Enable extra log levels."),
    Setting("General", "bCleanSKSECoSaves", "bool", "false",
            "Delete SKSE cosaves with no matching saves."),

    # ---- [Fixes] ----
    Setting("Fixes", "bArcheryDownwardAiming", "bool", "true",
            "Fixes arrows not firing properly when aiming downward while crouching on a ridge."),
    Setting("Fixes", "bAnimationLoadSignedCrash", "bool", "true",
            "Fixes a misplaced use of a signed value in animation loading."),
    Setting("Fixes", "bBethesdaNetCrash", "bool", "true",
            "Fixes the game crashing on startup with special characters in the user name."),
    Setting("Fixes", "bBGSKeywordFormLoadCrash", "bool", "true",
            "Fixes a crash when malformed BGSKeywordForms are loaded."),
    Setting("Fixes", "bBSLightingAmbientSpecular", "bool", "true",
            "Fixes light template Directional Ambient Specular & Fresnel Power sent to BSLightingShader incorrectly."),
    Setting("Fixes", "bBSLightingShaderForceAlphaTest", "bool", "true",
            "Fixes object LOD reflections by forcing the alpha-test flag on when NiAlphaProperty/AlphaTest is true."),
    Setting("Fixes", "bBSLightingShaderParallaxBug", "bool", "true",
            "Fixes the parallax technique breaking if specular is not also set."),
    Setting("Fixes", "bBSLightingShaderPropertyShadowMap", "bool", "true",
            "Fixes re-use of render passes when a light has multiple shadow-map passes."),
    Setting("Fixes", "bBSTempEffectNiRTTI", "bool", "true",
            "Fixes the NiRTTI for this object not being set properly."),
    Setting("Fixes", "bCalendarSkipping", "bool", "true",
            "Fixes the calendar skipping a year if you fast travel far between 20:00 and 23:99 in-game."),
    Setting("Fixes", "bCellInit", "bool", "true",
            "Fixes a rare crash where a form field is not converted from an id to a pointer."),
    Setting("Fixes", "bClimateLoad", "bool", "true",
            "Fixes the game failing to apply sunrise/sunset Climate data when loading inside an interior."),
    Setting("Fixes", "bConjurationEnchantAbsorbs", "bool", "true",
            "Fixes spell absorption triggering on enchanted items using conjuration summons."),
    Setting("Fixes", "bCreateArmorNodeNullPtrCrash", "bool", "true",
            "Fixes a typo that may cause a crash in CreateArmorNode."),
    Setting("Fixes", "bDoublePerkApply", "bool", "true",
            "Fixes NPC perks applying twice when you load a game."),
    Setting("Fixes", "bESLCELLLoadBug", "bool", "true",
            "Fixes issues with interior cells created in ESL files."),
    Setting("Fixes", "bEquipShoutEventSpam", "bool", "true",
            "Fixes a 'shout equipped' event firing even when the shout fails to equip."),
    Setting("Fixes", "bFaceGenMorphDataHeadNullPtrCrash", "bool", "true",
            "Fixes a crash in face morphing, possibly related to decapitations."),
    Setting("Fixes", "bGetKeywordItemCount", "bool", "true",
            "Fixes the 'GetKeywordItemCount' condition function returning broken results sometimes."),
    Setting("Fixes", "bGHeapLeakDetectionCrash", "bool", "true",
            "Fixes a crash where scaleform reports a memory leak using code not present in Skyrim's build."),
    Setting("Fixes", "bGlobalTime", "bool", "true",
            "Fixes systems affected by game time instead of real time (incl. old slow-time camera fix)."),
    Setting("Fixes", "bInitializeHitDataNullPtrCrash", "bool", "true",
            "Fixes a crash on a melee hit that unequipped the weapon at the same time."),
    Setting("Fixes", "bLipSync", "bool", "true",
            "Fixes lip sync desyncing."),
    Setting("Fixes", "bMemoryAccessErrors", "bool", "true",
            "Fixes miscellaneous errors obscured by Skyrim's default allocator."),
    Setting("Fixes", "bMO5STypo", "bool", "true",
            "Fixes a typo preventing the game from loading MO5S entries in ARMA forms."),
    Setting("Fixes", "bMusicOverlap", "bool", "true",
            "Fixes multiple music tracks playing at the same time."),
    Setting("Fixes", "bNiControllerNoTarget", "bool", "true",
            "Fixes a crash from a malformed nif with a time controller that has no target (and logs it)."),
    Setting("Fixes", "bNullProcessCrash", "bool", "true",
            "Fixes crashes when checking the equipped weapons of an actor without an AI process."),
    Setting("Fixes", "bPerkFragmentIsRunning", "bool", "true",
            "Fixes a crash if a perk fragment's IsRunning is called on a non-actor form."),
    Setting("Fixes", "bPrecomputedPaths", "bool", "true",
            "Fixes a crash when NAVI precomputed paths are inaccurate for your load order (and logs a warning)."),
    Setting("Fixes", "bRemovedSpellBook", "bool", "true",
            "Fixes a crash from learning a spell from a book later removed by another plugin."),
    Setting("Fixes", "bSaveScreenshots", "bool", "true",
            "Fixes save screenshots being blank under certain configurations."),
    Setting("Fixes", "bSavedHavokDataLoadInit", "bool", "true",
            "Fixes motion vectors for objects whose saved havok data differs from their base state."),
    Setting("Fixes", "bShadowSceneNodeNullPtrCrash", "bool", "true",
            "Fixes a crash in shadowscenenode."),
    Setting("Fixes", "bTextureLoadCrash", "bool", "true",
            "Fixes a 1.5.97 crash when a texture load fails (built-in to 1.6.1170); logs texture load errors."),
    Setting("Fixes", "bTorchLandscape", "bool", "true",
            "Fixes torches sometimes not lighting the landscape."),
    Setting("Fixes", "bTreeReflections", "bool", "true",
            "Fixes tree LOD reflection alpha."),
    Setting("Fixes", "bVerticalLookSensitivity", "bool", "true",
            "Fixes vertical look sensitivity being tied to framerate."),
    Setting("Fixes", "bWeaponBlockScaling", "bool", "true",
            "Fixes weapon blocking so it scales off the blocking actor's weapon correctly."),

    # ---- [Patches] ----
    Setting("Patches", "bDisableChargenPrecache", "bool", "false",
            "Disables pre-caching of chargen; unnecessary with RaceMenu installed."),
    Setting("Patches", "bDisableSnowFlag", "bool", "false",
            "Forcibly removes snow flags from loaded LTEX, MATO and STAT forms."),
    Setting("Patches", "bEnableAchievementsWithMods", "bool", "true",
            "Enables achievements with mods active."),
    Setting("Patches", "bFormCaching", "bool", "true",
            "Attempts to speed up form lookups."),
    Setting("Patches", "bINISettingCollection", "bool", "true",
            "Slightly speeds up startup time for lists with a large number of plugins."),
    Setting("Patches", "bMaxStdIO", "bool", "true",
            "Sets the maximum number of open file handles to the system maximum (usually 8192)."),
    Setting("Patches", "bRegularQuicksaves", "bool", "false",
            "Makes quicksaves into regular saves."),
    Setting("Patches", "bSafeExit", "bool", "true",
            "Prevents the game from hanging when shutting down."),
    Setting("Patches", "bSaveAddedSoundCategories", "bool", "true",
            "Saves the volume of sound categories added by mods."),
    Setting("Patches", "iSaveGameMaxSize", "int", "128",
            "Max uncompressed save size in MB (default 64). Only raise as high as you need."),
    Setting("Patches", "bScrollingDoesntSwitchPOV", "bool", "false",
            "Disables swapping between 1st/3rd person when using mousewheel zoom."),
    Setting("Patches", "fSleepWaitTimeModifier", "float", "1.0",
            "Modifies sleep/wait time. 1.0 = default, smaller = faster, larger = slower."),
    Setting("Patches", "bTreeLodReferenceCaching", "bool", "true",
            "Requires form caching. Speeds up a tree-LOD function that slows with more plugins loaded."),
    Setting("Patches", "bWaterflowAnimation", "bool", "true",
            "Decouples waterflow speed from in-game timescale."),
    Setting("Patches", "fWaterflowSpeed", "float", "20.0",
            "Waterflow speed. 20.0 = default, smaller = slower, larger = faster."),

    # ---- [MemoryManager] ----
    Setting("MemoryManager", "bOverrideMemoryManager", "bool", "true",
            "Overrides Skyrim's memory manager with direct malloc/free calls."),
    Setting("MemoryManager", "bOverrideScrapHeap", "bool", "true",
            "Overrides Skyrim's scrap heap with direct malloc/free calls."),
    Setting("MemoryManager", "bOverrideScaleformAllocator", "bool", "true",
            "Overrides Skyrim's scaleform allocator with calls to the global memory manager."),
    Setting("MemoryManager", "bOverrideRenderPassCache", "bool", "true",
            "Overrides Skyrim's render pass cache with direct malloc/free calls."),
    Setting("MemoryManager", "bOverrideHavokMemorySystem", "bool", "true",
            "Overrides Havok's memory manager with direct malloc/free calls."),
    Setting("MemoryManager", "bReplaceImports", "bool", "true",
            "Replace imported CRT memory functions with the selected allocator."),

    # ---- [Warnings] ----
    Setting("Warnings", "bTextureLoadFailed", "bool", "true",
            "On exit, pops up a message box if one or more textures failed to load (and have been logged)."),
    Setting("Warnings", "bPrecomputedPathHasErrors", "bool", "false",
            "On exit, pops up a message box if a precomputed path had an error."),
    Setting("Warnings", "bRefHandleLimit", "bool", "true",
            "Warns when close to the reference handle limit at main menu and after loading a save."),
    Setting("Warnings", "uRefrMainMenuLimit", "int", "800000",
            "Handle count to warn at on the main menu."),
    Setting("Warnings", "uRefrLoadedGameLimit", "int", "1000000",
            "Handle count to warn at after loading a save game."),

    # ---- [Debug] ----
    Setting("Debug", "bPrintDetailedPrecomputedPathInfo", "bool", "false",
            "Disables the precomputed-path crash fix and prints detailed info about broken paths."),
    Setting("Debug", "bDisableTBB", "bool", "false",
            "Use the CRT allocator instead of tbb. Can and will cause crashes with broken plugins."),
]

# Section order for rendering (matches the shipped toml).
SECTION_ORDER = ["General", "Fixes", "Patches", "MemoryManager", "Warnings", "Debug"]

_SCHEMA_BY_ID = {s.id: s for s in SCHEMA}


# ---------------------------------------------------------------------------
# TOML parse / render helpers
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(r"^\s*\[([^\]]+)\]\s*$")
# A setting line: "key = value" with an optional trailing "# comment".
# value is captured greedily but stops before an unquoted inline comment.
_SETTING_RE = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)([^#\n]*?)(\s*#.*)?$")


def parse_toml(text: str) -> dict[tuple[str, str], str]:
    """Parse the toml into ``{(section, key): value_str}``.

    Only the simple ``key = value`` lines Engine Fixes uses are recognised;
    inline ``# comments`` are stripped. The first occurrence of a key within a
    section wins.
    """
    result: dict[tuple[str, str], str] = {}
    section = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            sec_m = _SECTION_RE.match(raw)
            if sec_m:
                section = sec_m.group(1).strip()
            continue
        sec_m = _SECTION_RE.match(raw)
        if sec_m:
            section = sec_m.group(1).strip()
            continue
        m = _SETTING_RE.match(raw)
        if not m:
            continue
        key, value = m.group(2), m.group(4).strip()
        ident = (section, key)
        if ident not in result:
            result[ident] = value
    return result


def render_toml(base_text: str, values: dict[tuple[str, str], str]) -> str:
    """Rewrite ``base_text`` in place applying ``values``.

    Preserves the inline ``# comment`` documentation, alignment whitespace and
    the original line-ending style. Settings in ``values`` not present in the
    template are appended under their section.
    """
    newline = "\r\n" if "\r\n" in base_text else "\n"
    lines = base_text.split("\n")
    lines = [ln[:-1] if ln.endswith("\r") else ln for ln in lines]

    seen: set[tuple[str, str]] = set()
    section = ""
    section_last_idx: dict[str, int] = {}

    for i, raw in enumerate(lines):
        sec_m = _SECTION_RE.match(raw)
        if sec_m:
            section = sec_m.group(1).strip()
            section_last_idx[section] = i
            continue
        section_last_idx[section] = i
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        m = _SETTING_RE.match(raw)
        if not m:
            continue
        key = m.group(2)
        ident = (section, key)
        if ident not in values:
            continue
        indent, eq, _old, comment = m.group(1), m.group(3), m.group(4), m.group(5) or ""
        lines[i] = f"{indent}{key}{eq}{values[ident]}{comment}"
        seen.add(ident)

    extras = [ident for ident in values if ident not in seen]
    if extras:
        by_section: dict[str, list[tuple[str, str]]] = {}
        for ident in extras:
            by_section.setdefault(ident[0], []).append(ident)
        for sec in sorted(by_section, key=lambda s: section_last_idx.get(s, len(lines)),
                          reverse=True):
            idx = section_last_idx.get(sec)
            block: list[str] = []
            if idx is None:
                block.append("")
                block.append(f"[{sec}]")
                idx = len(lines) - 1
            for ident in by_section[sec]:
                block.append(f"{ident[1]} = {values[ident]}")
            lines[idx + 1:idx + 1] = block

    return newline.join(lines)


# ---------------------------------------------------------------------------
# Default toml template (shipped Engine Fixes defaults, fully documented)
# ---------------------------------------------------------------------------

DEFAULT_TOML = """# Engine Fixes 7.0 for SSE 1.5.97/1.6.1170
[General]
bVerboseLogging = false                         # enable extra log levels
bCleanSKSECoSaves = false                       # delete SKSE cosaves with no matching saves

# contains bug fixes
[Fixes]
bArcheryDownwardAiming = true                   # fixes a bug where arrows don't fire properly if you're aiming downward while crouching on a ridge
bAnimationLoadSignedCrash = true                # fixes a misplaced used of a signed value in animation loading
bBethesdaNetCrash = true                        # fixes the game crashing on startup if you live somewhere with special characters in the name
bBGSKeywordFormLoadCrash = true                 # fixes a crash when malformed BGSKeywordForms are loaded by the game
bBSLightingAmbientSpecular = true               # fixes bug where light template Directional Ambient Specular & Fresnel Power are sent to BSLightingShader incorrectly
bBSLightingShaderForceAlphaTest = true          # fixes object LOD reflections by forcing alpha test flag on when NiAlphaProperty/AlphaTest is true
bBSLightingShaderParallaxBug = true             # fixes a bug causing the parallax technique to break if specular is not also set
bBSLightingShaderPropertyShadowMap = true       # fixes re-use of render passes when a light has multiple shadow map passes
bBSTempEffectNiRTTI = true                      # fixes a bug where the NiRTTI for this object is not set properly
bCalendarSkipping = true                        # fixes a bug where the game calendar effectively skips a year if you fast travel too far between 20:00 and 23:99 in-game
bCellInit = true                                # fixes a rare crash where a form field does not get converted from an id to a pointer
bClimateLoad = true                             # fixes a bug where the game fails to properly apply sunrise and sunset data from Climate records if you load a saved game in an interior
bConjurationEnchantAbsorbs = true               # fixes a bug where spell absorption triggers on enchanted items using conjuration summons
bCreateArmorNodeNullPtrCrash = true             # fixes typo that may cause a crash somewhere in CreateArmorNode
bDoublePerkApply = true                         # fixes NPC perks applying twice when you load a game
bESLCELLLoadBug = true                          # fixes issues with interior cells created in ESL files
bEquipShoutEventSpam = true                     # fixes a bug where the "equip shout" procedure will send a "shout equipped" event even if the shout fails to equip
bFaceGenMorphDataHeadNullPtrCrash = true        # fixes a crash in face morphing, possibly related to decapitations
bGetKeywordItemCount = true                     # fixes the condition function "GetKeywordItemCount", which returns broken results sometimes
bGHeapLeakDetectionCrash = true                 # fixes a crash where scaleform attempts to report a memory leak but the code doesn't exist in Skyrim's build
bGlobalTime = true                              # fixes game systems that are affected by game time instead of real time, including old slow time camera movement fix
bInitializeHitDataNullPtrCrash = true           # fixes a crash on melee hit that unequipped the weapon at the same time
bLipSync = true                                 # fixes a bug causing lip sync to desync
bMemoryAccessErrors = true                      # fixes miscellaneous errors that are obscured by Skyrim's default allocator
bMO5STypo = true                                # fixes a typo preventing the game from loading MO5S entries in ARMA forms
bMusicOverlap = true                            # fixes a bug where multiple music tracks are playing at the same time
bNiControllerNoTarget = true                    # fixes a crash if a malformed nif with a time controller that has no target is loaded, and logs a warning for the malformed nif
bNullProcessCrash = true                        # fixes a couple cases where the game can crash when checking the equipped weapons of an actor without an AI process
bPerkFragmentIsRunning = true                   # fixes a crash if the IsRunning function of a perk fragment is called on a non-actor form
bPrecomputedPaths = true                        # fixes a crash when NAVI precomputed paths aren't accurate for your load order and logs a warning
bRemovedSpellBook = true                        # fixes a crash where learning a spell from a book that is later removed in another plugin causes a crash in the inventory
bSaveScreenshots = true                         # fixes save screenshots being blank under certain configurations
bSavedHavokDataLoadInit = true                  # fixes motion vectors for objects with saved havok data that differs significantly from their base state
bShadowSceneNodeNullPtrCrash = true             # fixes a crash in shadowscenenode
bTextureLoadCrash = true                        # fixes a crash in 1.5.97 when a texture load fails (D6DDDA), this behavior is built-in to 1.6.1170; also logs texture load errors
bTorchLandscape = true                          # fixes a bug where torches sometimes don't light the landscape
bTreeReflections = true                         # fixes tree LOD reflection alpha
bVerticalLookSensitivity = true                 # fixes vertical look sensitivity being tied to framerate
bWeaponBlockScaling = true                      # fixes weapon blocking so it correctly scales off of the blocking actor's weapon

# contains optional game patches
[Patches]
bDisableChargenPrecache = false                 # disables pre-caching of chargen, unnecessary with RaceMenu installed
bDisableSnowFlag = false                        # forcably removes snow flags from loaded LTEX, MATO, and STAT forms
bEnableAchievementsWithMods = true              # enables achievements with mods active
bFormCaching = true                             # attempts to speedup form lookups
bINISettingCollection = true                    # slightly speeds up startup time for lists with a large number of plugins
bMaxStdIO = true                                # sets the maximum number of open file handles to the maximum available on your system (8192 in most cases, 2048 for older versions of windows)
bRegularQuicksaves = false                      # makes quicksaves into regular saves
bSafeExit = true                                # prevent the game from hanging when shutting down
bSaveAddedSoundCategories = true                # save the volume of sound categories added by mods
iSaveGameMaxSize = 128                          # expands the maximum uncompressed size of a save game from 64 MB to a configurable size (MB), game default = 64 MB, only go as high as you need!
bScrollingDoesntSwitchPOV = false               # disables swapping between 1st/3rd person when using mousewheel scroll to zoom
fSleepWaitTimeModifier = 1.0                    # modifies your sleep/wait time, 1.0 = default, smaller = faster, larger = slower
bTreeLodReferenceCaching = true                 # requires form caching to be enabled. speeds up a tree LOD function that slows down proportionate to the number of plugins loaded
bWaterflowAnimation = true                      # decouple waterflow speed from in-game timescale
fWaterflowSpeed = 20.0                          # 20.0 = default, smaller = slower, larger = faster

# patches to replace Skyrim's allocators with tbbmalloc
[MemoryManager]
bOverrideMemoryManager = true                   # overrides Skyrim's memory manager with direct malloc/free calls
bOverrideScrapHeap = true                       # overrides Skyrim's scrap heap with direct malloc/free calls
bOverrideScaleformAllocator = true              # overrides Skyrim's scaleform allocator with calls to the global memory manager
bOverrideRenderPassCache = true                 # overrides Skyrim's render pass cache with direct malloc/free calls
bOverrideHavokMemorySystem = true               # overrides Havok's memory manager with direct malloc/free calls
bReplaceImports = true                          # replace imported CRT memory functions with selected allocator

[Warnings]
bTextureLoadFailed = true                       # On exit, pops up a message box telling you one or more textures failed to load and have been logged
bPrecomputedPathHasErrors = false               # On exit, pops up a message box telling you a precomputed path had an error
bRefHandleLimit = true                          # Warns when you are close to the reference handle limit at main menu and after loading a save
uRefrMainMenuLimit = 800000                     # Handle count to warn at on main menu
uRefrLoadedGameLimit = 1000000                  # Handle count to warn at after loading a save game

[Debug]
bPrintDetailedPrecomputedPathInfo = false       # disables the precomputed path crash fix and prints detailed information about broken paths
bDisableTBB = false                             # use CRT allocator instead of tbb - this can and will cause crashes with broken plugins
"""


# ---------------------------------------------------------------------------
# Filemap helpers / default-value loading
# ---------------------------------------------------------------------------

def _filemap_find(game: "BaseGame", rel_suffix: str) -> Path | None:
    """Return the staging path of the file whose filemap entry ends with rel_suffix."""
    try:
        filemap_path = game.get_effective_filemap_path()
        staging = game.get_effective_mod_staging_path()
    except Exception:
        return None
    if not filemap_path.is_file():
        return None
    target = rel_suffix.lower().replace("\\", "/")
    try:
        text = filemap_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if "\t" not in line:
            continue
        rel_str, mod_name = line.split("\t", 1)
        norm = rel_str.replace("\\", "/").lower()
        if norm.endswith(target):
            candidate = staging / mod_name / rel_str.replace("\\", "/")
            if candidate.is_file():
                return candidate
    return None


def is_installed(game: "BaseGame") -> bool:
    """True when EngineFixes.dll is the winning file in the filemap.

    Used to gate the wizard so it only appears when Engine Fixes is actually
    enabled/deployed.
    """
    return _filemap_find(game, REL_DLL_PATH) is not None


def _schema_defaults() -> dict[tuple[str, str], str]:
    return {s.id: s.default for s in SCHEMA}


def load_initial_values(game: "BaseGame") -> tuple[dict[tuple[str, str], str], str]:
    """Resolve initial form values and a one-line source description.

    Order: managed-mod toml → filemap winner → schema defaults. Loaded values
    overlay the schema defaults so every schema key still gets a row.
    """
    values = _schema_defaults()
    source = "built-in defaults"

    managed = game.get_effective_mod_staging_path() / MOD_NAME / REL_TOML_PATH
    src_path: Path | None = None
    if managed.is_file():
        src_path = managed
        source = f"managed mod '{MOD_NAME}'"
    else:
        fm = _filemap_find(game, REL_TOML_PATH)
        if fm is not None:
            src_path = fm
            source = "the deployed (filemap) toml"

    if src_path is not None:
        try:
            parsed = parse_toml(src_path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            parsed = {}
        for ident, val in parsed.items():
            values[ident] = val
    return values, source


# ============================================================================
# Wizard dialog
# ============================================================================

class EngineFixesWizard(ctk.CTkFrame):
    """Single-page wizard to create/edit EngineFixes.toml."""

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
        self._game = game
        self._log = log_fn or (lambda msg: None)
        # (section, key) -> value_var
        self._rows: dict[tuple[str, str], ctk.StringVar] = {}

        # --- title bar ---
        title_bar = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=0, height=40)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)
        ctk.CTkLabel(
            title_bar, text=f"Engine Fixes — {game.name}",
            font=FONT_BOLD, text_color=TEXT_MAIN, anchor="w",
        ).pack(side="left", padx=12, pady=8)
        ctk.CTkButton(
            title_bar, text="✕", width=32, height=32, font=FONT_BOLD,
            fg_color="transparent", hover_color=BG_PANEL, text_color=TEXT_MAIN,
            command=self._on_cancel,
        ).pack(side="right", padx=4, pady=4)

        # --- intro / status ---
        header = ctk.CTkFrame(self, fg_color=BG_DEEP)
        header.pack(fill="x", padx=20, pady=(12, 4))
        ctk.CTkLabel(
            header,
            text=(
                "Configure EngineFixes.toml. Saving writes to the managed mod "
                f"'{MOD_NAME}', overriding the Engine Fixes mod by priority."
            ),
            font=FONT_NORMAL, text_color=TEXT_DIM, justify="left", anchor="w",
            wraplength=640,
        ).pack(fill="x")
        self._status = ctk.CTkLabel(
            header, text="", font=FONT_SMALL, text_color=TEXT_DIM,
            justify="left", anchor="w", wraplength=640,
        )
        self._status.pack(fill="x", pady=(4, 0))

        # --- scrollable form ---
        scroll = ctk.CTkScrollableFrame(self, fg_color=BG_PANEL, corner_radius=6)
        scroll.pack(fill="both", expand=True, padx=20, pady=(8, 8))
        scroll.grid_columnconfigure(1, weight=1)
        self._scroll = scroll

        values, source = load_initial_values(game)
        self._build_form(scroll)
        self._apply_values(values)
        bind_scrollable_wheel(scroll)
        self._set_status(f"Loaded from {source}.", _OK_GREEN)

        # --- buttons ---
        btns = ctk.CTkFrame(self, fg_color=BG_DEEP)
        btns.pack(fill="x", padx=20, pady=(0, 16))
        ctk.CTkButton(
            btns, text="Save", width=120, height=36, font=FONT_BOLD,
            fg_color=ACCENT, hover_color=ACCENT_HOV, text_color=TEXT_ON_ACCENT,
            command=self._on_save,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btns, text="Reset to defaults", width=150, height=36, font=FONT_BOLD,
            fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
            command=self._on_reset,
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            btns, text="Close", width=100, height=36, font=FONT_BOLD,
            fg_color=BG_HEADER, hover_color="#3d3d3d", text_color=TEXT_MAIN,
            command=self._on_cancel,
        ).pack(side="right")

    # ------------------------------------------------------------------
    # Form construction
    # ------------------------------------------------------------------

    def _build_form(self, parent):
        row = 0
        for section in SECTION_ORDER:
            section_settings = [s for s in SCHEMA if s.section == section]
            if not section_settings:
                continue
            ctk.CTkLabel(
                parent, text=f"[{section}]",
                font=FONT_BOLD, text_color=ACCENT, anchor="w",
            ).grid(row=row, column=0, columnspan=2, sticky="w",
                   padx=8, pady=(14 if row else 4, 2))
            row += 1
            for s in section_settings:
                row = self._build_row(parent, s, row)

    def _build_row(self, parent, s: Setting, row: int) -> int:
        value_var = ctk.StringVar(value=s.default)
        self._rows[s.id] = value_var

        ctk.CTkLabel(
            parent, text=s.key, font=FONT_NORMAL, text_color=TEXT_MAIN, anchor="w",
        ).grid(row=row, column=0, sticky="w", padx=(8, 4), pady=(6, 0))

        self._build_value_widget(parent, s, value_var).grid(
            row=row, column=1, sticky="e", padx=(4, 8), pady=(6, 0))
        row += 1

        ctk.CTkLabel(
            parent, text=s.desc, font=FONT_SMALL, text_color=TEXT_DIM,
            anchor="w", justify="left", wraplength=620,
        ).grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        return row + 1

    def _build_value_widget(self, parent, s: Setting, value_var: ctk.StringVar):
        if s.kind == "bool":
            return ctk.CTkSegmentedButton(
                parent, values=["true", "false"], variable=value_var,
                width=120, font=FONT_SMALL,
                selected_color=ACCENT, selected_hover_color=ACCENT_HOV,
            )
        return ctk.CTkEntry(
            parent, textvariable=value_var, width=170, font=FONT_NORMAL,
            fg_color=BG_DEEP, text_color=TEXT_MAIN,
        )

    # ------------------------------------------------------------------
    # Value <-> form
    # ------------------------------------------------------------------

    def _apply_values(self, values: dict[tuple[str, str], str]):
        for ident, value_var in self._rows.items():
            s = _SCHEMA_BY_ID[ident]
            value = values.get(ident, s.default)
            if s.kind == "bool":
                value = "true" if str(value).strip().lower() in ("true", "1", "yes") else "false"
            value_var.set(value)

    def _collect_values(self) -> dict[tuple[str, str], str]:
        return {ident: var.get().strip() for ident, var in self._rows.items()}

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_cancel(self):
        self._on_close_cb()

    def _on_reset(self):
        self._apply_values(_schema_defaults())
        self._set_status("Form reset to built-in defaults (not yet saved).", TEXT_DIM)

    def _on_save(self):
        values = self._collect_values()

        target = self._game.get_effective_mod_staging_path() / MOD_NAME / REL_TOML_PATH
        try:
            base_text = target.read_text(encoding="utf-8", errors="replace") \
                if target.is_file() else DEFAULT_TOML
        except OSError:
            base_text = DEFAULT_TOML

        try:
            out = render_toml(base_text, values)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".mm_tmp")
            tmp.write_text(out, encoding="utf-8")
            tmp.replace(target)
        except OSError as exc:
            self._set_status(f"Save failed: {exc}", _ERR_RED)
            self._log(f"Engine Fixes wizard: save failed: {exc}")
            return

        self._log(f"Engine Fixes wizard: wrote {target}")
        self._set_status(f"Saved to {MOD_NAME}/{REL_TOML_PATH}.", _OK_GREEN)
        self._reload_mod_panel()

    def _reload_mod_panel(self):
        """Refresh the mod list so a newly-created managed mod shows up."""
        try:
            topbar = self.winfo_toplevel()._topbar
        except Exception:
            topbar = None
        if topbar is not None:
            try:
                topbar.after(0, topbar._reload_mod_panel)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------

    def _set_status(self, text: str, color: str = TEXT_DIM):
        try:
            self._status.configure(text=text, text_color=color)
        except Exception:
            pass
