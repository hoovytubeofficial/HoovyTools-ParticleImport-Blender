# =============================================================================
#  paths.py  -  find the SFM install so the file browsers open THERE
# =============================================================================
#
#  Nobody wants to click through Downloads to reach
#      ...\SourceFilmmaker\game\usermod\materials
#  every single time. This module finds the usermod folder and hands the
#  browsers a sensible starting directory.
#
#  SEARCH ORDER (all cheap existence checks - no recursive scanning)
#    1. an explicit override (the add-on preferences - operators/op_prefs.py
#       is where preferences and this module meet; nothing here reads bpy)
#    2. Steam's own library list: registry -> libraryfolders.vdf -> every
#       library's steamapps\common\SourceFilmmaker
#    3. common hand-rolled layouts on every fixed drive (C:, D:, E: ...)
#    4. nothing found -> return None and the browser falls back to Blender's
#       default (last-used directory / Downloads)
#
#  bpy-free on purpose: pure path logic, testable outside Blender. Results are
#  cached because this is called from operator invoke(), not draw(), but a
#  rescan is one refresh() away.
# =============================================================================

import os
import re
import string
from pathlib import Path

_REL_SFM = Path("steamapps") / "common" / "SourceFilmmaker"
_REL_USERMOD = Path("game") / "usermod"

# Layouts people actually use, relative to a drive root.
_DRIVE_PATTERNS = (
    Path("Program Files (x86)") / "Steam",
    Path("Program Files") / "Steam",
    Path("Steam"),
    Path("SteamLibrary"),
    Path("Games") / "Steam",
    Path("Games") / "SteamLibrary",
    Path("SteamGames"),
)

_cache = {"usermod": None, "done": False}


# ── steam library discovery ──────────────────────────────────────────────────

def _steam_root_from_registry():
    try:
        import winreg
    except ImportError:
        return None
    for hive, key in ((getattr(winreg, "HKEY_CURRENT_USER"), r"Software\Valve\Steam"),
                      (getattr(winreg, "HKEY_LOCAL_MACHINE"), r"Software\WOW6432Node\Valve\Steam")):
        for value in ("SteamPath", "InstallPath"):
            try:
                with winreg.OpenKey(hive, key) as k:
                    path = Path(winreg.QueryValueEx(k, value)[0])
                if path.is_dir():
                    return path
            except Exception:
                continue
    return None


def _library_folders(steam_root):
    """Every Steam library path listed in libraryfolders.vdf, plus the root."""
    out = []
    if steam_root and steam_root.is_dir():
        out.append(steam_root)
    if not steam_root:
        return out
    for name in ("libraryfolders.vdf", "config/libraryfolders.vdf"):
        vdf = steam_root / "steamapps" / name if name.endswith(".vdf") \
            and "/" not in name else steam_root / name
        if not vdf.is_file():
            continue
        try:
            text = vdf.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # Entries look like:   "path"   "E:\\SteamLibrary"
        for m in re.finditer(r'"path"\s*"([^"]+)"', text):
            p = Path(m.group(1).replace("\\\\", "\\"))
            if p.is_dir():
                out.append(p)
    return out


def _fixed_drives():
    drives = []
    for letter in string.ascii_uppercase:
        root = Path(f"{letter}:\\")
        try:
            if root.exists():
                drives.append(root)
        except Exception:
            continue
    return drives


def _candidate_steam_roots():
    roots = []
    reg = _steam_root_from_registry()
    roots.extend(_library_folders(reg))
    for drive in _fixed_drives():
        for rel in _DRIVE_PATTERNS:
            roots.append(drive / rel)
    seen, unique = set(), []
    for r in roots:
        key = str(r).lower()
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


def _true_case(path):
    """The path as the disk spells it. Steam's registry keeps its folder in lower case ("c:/program files
    (x86)/steam"), and the preferences and Wiring showed it that way (3.0.0). Junctions are not followed."""
    try:
        cur = Path(path.drive.upper() + "\\")
        for name in path.parts[1:]:
            low = name.lower()
            cur = cur / next((e for e in os.listdir(cur) if e.lower() == low), name)
        return cur
    except Exception:
        return path


# ── public API ───────────────────────────────────────────────────────────────

def find_usermod(override=None, force=False):
    """Return the SFM usermod Path, or None. Cached after the first call."""
    if override:
        p = Path(os.path.expandvars(str(override))).expanduser()
        if (p / "gameinfo.txt").is_file() or p.is_dir():
            return p
    if _cache["done"] and not force:
        return _cache["usermod"]

    found = None
    for root in _candidate_steam_roots():
        usermod = root / _REL_SFM / _REL_USERMOD
        try:
            if usermod.is_dir():
                found = _true_case(usermod)
                break
        except Exception:
            continue
    _cache["usermod"] = found
    _cache["done"] = True
    return found


def subdir(kind, override=None):
    """Starting directory for a browser: usermod/<kind> if it exists.

    kind is 'materials' or 'particles'. Falls back to usermod itself, then to
    None (Blender then uses its own default / last-used directory)."""
    usermod = find_usermod(override)
    if usermod is None:
        return None
    target = usermod / kind
    if target.is_dir():
        return target
    return usermod if usermod.is_dir() else None


# =============================================================================
#  WHERE THE TEXTURES YOU ACTUALLY USE LIVE
# =============================================================================
#  `usermod/materials` is the honest generic answer and the wrong practical
#  one - it is a folder of folders, and the working set is one level down. So
#  every texture browser walks a SEARCH ORDER, most specific first, and opens
#  at the first entry that exists. Same list for all three, so the browser
#  never opens somewhere different depending on which button you pressed.
#
#  Relative to `usermod`.

_TEXTURE_DIRS = (
    Path("materials") / "__hoovytube" / "explosion",
    Path("materials"),
)

# Sparks, tracers and beams live somewhere else again - a trail browser that
# opens on the explosion sheets is a browser you immediately navigate out of.
_TRAIL_TEXTURE_DIRS = (
    Path("materials") / "__hoovytube" / "electricity",
    Path("materials") / "__hoovytube",
    Path("materials"),
)


def trail_sprite_dirs(override=None):
    """The search order for a sprite-TRAIL texture, best first."""
    usermod = find_usermod(override)
    if usermod is None:
        return []
    return [usermod / rel for rel in _TRAIL_TEXTURE_DIRS
            if (usermod / rel).is_dir()]


def trail_sprite_dir(override=None):
    dirs = trail_sprite_dirs(override)
    return dirs[0] if dirs else texture_dir(override)


def texture_dirs(override=None):
    """Every texture folder in the search order that exists, best first."""
    usermod = find_usermod(override)
    if usermod is None:
        return []
    return [usermod / rel for rel in _TEXTURE_DIRS if (usermod / rel).is_dir()]


def texture_dir(override=None):
    """Where a .vtf browser should open. The first folder that exists."""
    dirs = texture_dirs(override)
    return dirs[0] if dirs else find_usermod(override)


def materials_dir(override=None):
    # Kept as the plain "usermod/materials" answer. Texture browsers should
    # call texture_dir() instead - it starts one level deeper, where the
    # textures being worked on actually are.
    return subdir("materials", override)


def particles_dir(override=None):
    return subdir("particles", override)


def refresh():
    _cache["usermod"] = None
    _cache["done"] = False

# ── where trail textures actually live ───────────────────────────────────────
#
#  A rope needs a beam/trail texture, and those are not scattered evenly - they
#  sit in three known places. The browser opens at the first one that EXISTS,
#  most specific first, so the common case is one click instead of ten.
#
#  Relative to the SourceFilmmaker install (game/ is its own root here, so
#  these are not under usermod).

_TRAIL_DIRS = (
    Path("tf") / "materials" / "effects" / "doomsday",
    Path("usermod") / "materials" / "__hoovytube" / "trails",
    Path("tf") / "materials" / "effects",
)


def trail_texture_dirs(override=None):
    """Every trail-texture folder that exists, most specific first."""
    usermod = find_usermod(override)
    if usermod is None:
        return []
    game = usermod.parent          # ...\SourceFilmmaker\game
    out = []
    for rel in _TRAIL_DIRS:
        d = game / rel
        if d.is_dir():
            out.append(d)
    return out


def trail_texture_dir(override=None):
    """The best place to open a rope's texture browser, or None."""
    dirs = trail_texture_dirs(override)
    return dirs[0] if dirs else materials_dir(override)
