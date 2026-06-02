"""
Utils/protontricks.py
Helpers for running protontricks commands (native or flatpak),
and winetricks via the bundled copy in the manager's tools folder.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import stat
import subprocess
import tarfile
import urllib.request
from pathlib import Path
from typing import Callable

from Utils.app_log import safe_log as _safe_log

_WINETRICKS_URL = "https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks"
_CABEXTRACT_URL = "https://archlinux.org/packages/extra/x86_64/cabextract/download/"

# d3dcompiler_47: prebuilt DLLs from Mozilla's fxc2 repo (Windows 8.1 SDK redist).
# The winetricks/protontricks d3dcompiler_47 verb installs an older Win7-era DLL
# that lacks SM5.x extended typed UAV loads, which makes Community Shaders / ENB
# fail to compile with "error X3676: typed UAV loads are only allowed for
# single-component 32-bit element types". The fxc2 8.1 build supports it.
_D3DCOMPILER_47_64_URL = "https://github.com/mozilla/fxc2/raw/master/dll/d3dcompiler_47.dll"
_D3DCOMPILER_47_64_SHA256 = "4432bbd1a390874f3f0a503d45cc48d346abc3a8c0213c289f4b615bf0ee84f3"
_D3DCOMPILER_47_32_URL = "https://github.com/mozilla/fxc2/raw/master/dll/d3dcompiler_47_32.dll"
_D3DCOMPILER_47_32_SHA256 = "2ad0d4987fc4624566b190e747c9d95038443956ed816abfd1e2d389b5ec0851"

_DEPS_FILE = "amethyst_deps.json"

D3D_DEP_KEY = "d3dcompiler_47"
VCREDIST_DEP_KEY = "vcredist_x64"


def dotnet_dep_key(version: str) -> str:
    """Marker key for a .NET WindowsDesktop runtime version (e.g. '8' → 'dotnet8_windowsdesktop')."""
    return f"dotnet{version}_windowsdesktop"


def _deps_file(prefix_path: Path) -> Path:
    return prefix_path.parent / _DEPS_FILE


def read_installed_deps(prefix_path: Path) -> list[str]:
    """Return the list of components recorded as installed in *prefix_path*."""
    try:
        return json.loads(_deps_file(prefix_path).read_text(encoding="utf-8")).get("installed", [])
    except (OSError, ValueError):
        return []


def is_dep_installed(prefix_path: Path, key: str) -> bool:
    return key in read_installed_deps(prefix_path)


def mark_dep_installed(prefix_path: Path, key: str) -> None:
    f = _deps_file(prefix_path)
    try:
        data: dict = {}
        if f.is_file():
            data = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    installed: list = data.get("installed", [])
    if key not in installed:
        installed.append(key)
    data["installed"] = installed
    try:
        f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError:
        pass


def _get_tools_dir() -> Path:
    from Utils.config_paths import get_config_dir
    d = get_config_dir() / "tools"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _bundled_winetricks() -> Path:
    return _get_tools_dir() / "winetricks"


def _bundled_cabextract() -> Path:
    return _get_tools_dir() / "cabextract"


def winetricks_installed() -> bool:
    """Return True if winetricks is present in the manager's tools folder."""
    return _bundled_winetricks().is_file()


def cabextract_installed() -> bool:
    """Return True if cabextract is available (system PATH or bundled)."""
    return shutil.which("cabextract") is not None or _bundled_cabextract().is_file()


def install_cabextract(log_fn: Callable[[str], None] | None = None) -> bool:
    """Download a portable cabextract binary into the manager's tools folder."""
    _log = _safe_log(log_fn)
    dest = _bundled_cabextract()
    _log("Downloading cabextract …")
    try:
        import zstandard
    except ImportError as exc:
        _log(f"cabextract install needs the 'zstandard' Python module: {exc}")
        return False
    try:
        req = urllib.request.Request(
            _CABEXTRACT_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            pkg_bytes = resp.read()
        dctx = zstandard.ZstdDecompressor()
        raw = dctx.stream_reader(io.BytesIO(pkg_bytes))
        with tarfile.open(fileobj=raw, mode="r|") as tf:
            for member in tf:
                if member.name == "usr/bin/cabextract" and member.isfile():
                    extracted = tf.extractfile(member)
                    if extracted is None:
                        continue
                    dest.write_bytes(extracted.read())
                    break
            else:
                _log("cabextract binary not found inside the downloaded package.")
                return False
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        _log(f"cabextract installed to {dest}.")
        return True
    except Exception as exc:
        _log(f"cabextract download failed: {exc}")
        return False


def install_winetricks(log_fn: Callable[[str], None] | None = None) -> bool:
    """Download winetricks into the manager's tools folder.

    Returns True on success, False on failure.
    """
    _log = _safe_log(log_fn)
    dest = _bundled_winetricks()
    _log("Downloading winetricks …")
    try:
        req = urllib.request.Request(
            _WINETRICKS_URL,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
        dest.write_bytes(data)
        dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        _log(f"winetricks installed to {dest}.")
        return True
    except Exception as exc:
        _log(f"winetricks download failed: {exc}")
        return False


def _get_proton_bin() -> str | None:
    """Return the bin/ path of the newest available Proton installation, or None."""
    proton_root = Path.home() / ".local" / "share" / "Steam" / "steamapps" / "common"
    if not proton_root.is_dir():
        return None
    candidates = sorted(
        [p / "files" / "bin" for p in proton_root.iterdir()
         if p.name.startswith("Proton") and (p / "files" / "bin" / "wine").is_file()],
        key=lambda p: str(p),
        reverse=True,
    )
    return str(candidates[0]) if candidates else None


def _get_protontricks_cmd(steam_id: str) -> list[str] | None:
    """Return the protontricks command prefix for *steam_id*, or None if not found."""
    if shutil.which("protontricks") is not None:
        return ["protontricks", steam_id]
    if shutil.which("flatpak") is not None and subprocess.run(
        ["flatpak", "info", "com.github.Matoking.protontricks"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0:
        return ["flatpak", "run", "com.github.Matoking.protontricks", steam_id]
    return None


def _install_via_winetricks(
    prefix_path: Path,
    component: str,
    log_fn: Callable[[str], None],
) -> bool:
    """Install *component* directly via the bundled winetricks using WINEPREFIX."""
    if not _bundled_winetricks().is_file():
        log_fn("winetricks not found — downloading it now …")
        if not install_winetricks(log_fn=log_fn):
            return False

    if not cabextract_installed():
        log_fn("cabextract not found — downloading a portable copy now …")
        if not install_cabextract(log_fn=log_fn):
            return False

    winetricks = str(_bundled_winetricks())

    env = os.environ.copy()
    env["WINEPREFIX"] = str(prefix_path)

    path_prefix = str(_get_tools_dir())
    proton_bin = _get_proton_bin()
    if proton_bin:
        path_prefix = proton_bin + os.pathsep + path_prefix
    env["PATH"] = path_prefix + os.pathsep + env.get("PATH", "")

    log_fn(f"Installing {component} via winetricks (this may take a minute) …")
    try:
        result = subprocess.run(
            [winetricks, component],
            capture_output=True, text=True, timeout=300, env=env,
        )
        if result.returncode == 0:
            log_fn(f"{component} installed successfully.")
            return True
        else:
            log_fn(f"{component} install failed: {result.stderr or result.stdout or 'unknown error'}")
            return False
    except subprocess.TimeoutExpired:
        log_fn(f"{component} install timed out after 5 minutes.")
        return False
    except Exception as exc:
        log_fn(f"{component} error: {exc}")
        return False


def _install_via_protontricks(
    steam_id: str,
    component: str,
    log_fn: Callable[[str], None],
) -> bool:
    """Install *component* via system protontricks against *steam_id*."""
    cmd = _get_protontricks_cmd(steam_id)
    if cmd is None:
        return False
    cmd = cmd + [component]
    log_fn(f"Installing {component} via protontricks (this may take a minute) …")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode == 0:
            log_fn(f"{component} installed successfully.")
            return True
        log_fn(f"{component} install failed: {result.stderr or result.stdout or 'unknown error'}")
        return False
    except subprocess.TimeoutExpired:
        log_fn(f"{component} install timed out after 5 minutes.")
        return False
    except Exception as exc:
        log_fn(f"{component} error: {exc}")
        return False


def _download_verified(url: str, sha256: str, log_fn: Callable[[str], None]) -> bytes | None:
    """Download *url* and return its bytes if the SHA-256 matches, else None."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except Exception as exc:
        log_fn(f"Download failed for {url}: {exc}")
        return None
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        log_fn(f"Checksum mismatch for {url} (got {digest}).")
        return None
    return data


def _install_d3dcompiler_47_fxc2(prefix_path: Path, log_fn: Callable[[str], None]) -> bool:
    """Drop the Mozilla fxc2 (Win 8.1 SDK) d3dcompiler_47 DLLs into the prefix.

    64-bit → system32, 32-bit → syswow64 — the standard Wine wow64 layout.
    This is the build that supports SM5.x extended typed UAV loads, which the
    winetricks verb's older DLL does not (causes shader error X3676).
    """
    win = prefix_path / "drive_c" / "windows"
    sys32 = win / "system32"
    syswow64 = win / "syswow64"
    if not sys32.is_dir():
        log_fn(f"Prefix has no system32 dir at {sys32}.")
        return False

    log_fn("Installing d3dcompiler_47 (Mozilla fxc2, Win 8.1 SDK) …")
    data64 = _download_verified(_D3DCOMPILER_47_64_URL, _D3DCOMPILER_47_64_SHA256, log_fn)
    if data64 is None:
        return False
    try:
        (sys32 / "d3dcompiler_47.dll").write_bytes(data64)
    except OSError as exc:
        log_fn(f"Failed to write d3dcompiler_47.dll to system32: {exc}")
        return False

    # 32-bit DLL is best-effort: only matters if the prefix has a syswow64.
    if syswow64.is_dir():
        data32 = _download_verified(_D3DCOMPILER_47_32_URL, _D3DCOMPILER_47_32_SHA256, log_fn)
        if data32 is not None:
            try:
                (syswow64 / "d3dcompiler_47.dll").write_bytes(data32)
            except OSError as exc:
                log_fn(f"Failed to write 32-bit d3dcompiler_47.dll to syswow64: {exc}")

    from Utils.deploy_wine_dll import apply_wine_dll_overrides
    apply_wine_dll_overrides(prefix_path, {"d3dcompiler_47": "native"}, log_fn=log_fn)
    log_fn("d3dcompiler_47 installed (fxc2).")
    return True


def install_d3dcompiler_47(
    steam_id: str,
    log_fn: Callable[[str], None] | None = None,
    prefix_path: "Path | None" = None,
) -> bool:
    """Install d3dcompiler_47 into the game's Proton prefix.

    Prefers dropping the Mozilla fxc2 (Win 8.1 SDK) DLL directly, which supports
    SM5.x extended typed UAV loads (the winetricks verb installs an older DLL
    that fails to compile Community Shaders / ENB with error X3676). Falls back
    to protontricks/winetricks only if the direct install can't run. Records
    success in the prefix's amethyst_deps.json so other wizards can skip it.
    """
    _log = _safe_log(log_fn)
    prefix = Path(prefix_path) if prefix_path else None

    def _mark():
        if prefix and prefix.is_dir():
            mark_dep_installed(prefix, D3D_DEP_KEY)

    if prefix and prefix.is_dir():
        if _install_d3dcompiler_47_fxc2(prefix, _log):
            _mark()
            return True
        _log("fxc2 install failed — falling back to protontricks/winetricks "
             "(note: that DLL may not support Community Shaders / ENB).")

    if steam_id and _get_protontricks_cmd(steam_id) is not None:
        if _install_via_protontricks(steam_id, "d3dcompiler_47", _log):
            _mark()
            return True
        _log("Falling back to bundled winetricks …")

    if prefix and prefix.is_dir():
        if _install_via_winetricks(prefix, "d3dcompiler_47", _log):
            _mark()
            return True
        return False

    _log("d3dcompiler_47: no prefix path or working protontricks available — cannot install.")
    return False


def protontricks_available() -> bool:
    """Return True if protontricks (native or flatpak) is available on this system."""
    if shutil.which("protontricks") is not None:
        return True
    if shutil.which("flatpak") is not None and subprocess.run(
        ["flatpak", "info", "com.github.Matoking.protontricks"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    ).returncode == 0:
        return True
    return False
