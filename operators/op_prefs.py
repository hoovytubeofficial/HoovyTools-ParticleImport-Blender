# =============================================================================
# operators/op_prefs.py  -  Edit > Preferences > Add-ons > Source Particle Import
# =============================================================================
#
# YOUR PREFERRED PATHS. paths.py auto-detects the SFM install (registry,
# every Steam library, the common hand-rolled layouts) and that is right on
# most machines - these fields are for when it's wrong, or when you want a
# file browser opening somewhere of your own. Every field is OPTIONAL:
# empty means "keep auto-detecting", and a filled field simply WINS.
#
# The rest of the add-on asks this module where browsers should open
# (particles_dir(), texture_dir(), ...) - each answer is the preference if
# set, else the auto-detected place. paths.py itself stays bpy-free and
# knows nothing about preferences; this is the one place the two meet
# =============================================================================

from pathlib import Path

import bpy
from bpy.props import StringProperty
from bpy.types import AddonPreferences

from .. import paths

# The AddonPreferences bl_idname must be the package Blender registered the
# add-on under - the TOP-LEVEL package, not this operators/ subpackage
_PKG = __package__.split(".")[0]


def prefs():
    """This add-on's preferences, or None when not available (headless
    registration corner cases; callers all fall back to auto-detection)."""
    try:
        return bpy.context.preferences.addons[_PKG].preferences
    except Exception:
        return None


def _pref_path(name):
    """A preference folder if it is SET and EXISTS, else None - a stale path
    someone moved must not beat a working auto-detection."""
    p = prefs()
    raw = getattr(p, name, "") if p is not None else ""
    if not raw:
        return None
    try:
        d = Path(bpy.path.abspath(raw))
        return d if d.is_dir() else None
    except Exception:
        return None


def sfm_override():
    """The usermod override to hand paths.py, or None to auto-detect."""
    d = _pref_path("sfm_usermod")
    return str(d) if d is not None else None


# ── what the rest of the add-on calls ────────────────────────────────────
# Preference first, auto-detection second. Same names as paths.py so a call
# site changes one word (paths.texture_dir() -> op_prefs.texture_dir())

def find_usermod():
    return paths.find_usermod(sfm_override())


def particles_dir():
    return _pref_path("pcf_dir") or paths.particles_dir(sfm_override())


def texture_dir():
    return _pref_path("texture_dir") or paths.texture_dir(sfm_override())


def trail_texture_dir():
    return _pref_path("trail_dir") or paths.trail_texture_dir(sfm_override())


def trail_sprite_dir():
    return _pref_path("trail_dir") or paths.trail_sprite_dir(sfm_override())


def _changed(self, _context=None):
    """3.0.0: every preference change keeps _config/config.json in step, once that file exists (tools/config)."""
    from ..tools import config
    config.save(self)


def _rescan(self, context):
    #the auto-detector caches its answer; a changed override must not keep
    #showing the stale one
    paths.refresh()
    _changed(self)


def _push_log_settings(self, _context=None):
    """3.0.0: the log switches live in tools/htlog as plain values - print can run on a worker thread."""
    from ..tools import htlog
    htlog.SETTINGS["log_to_file"] = bool(getattr(self, "log_to_file", True))


def _log_to_file_changed(self, context):
    _push_log_settings(self)
    _changed(self)


def push_log_settings():
    p = prefs()
    if p is not None:
        _push_log_settings(p)


def feedback():
    """REPORT / POPUP / QUIET - how a failure is shown (the console and the log get it either way)."""
    p = prefs()
    return str(getattr(p, "feedback", "POPUP"))


def fancy_layouts():
    p = prefs()
    return bool(getattr(p, "fancy_layouts", True))


def viewport_facing():
    p = prefs()
    return bool(getattr(p, "viewport_facing", False))


class HTP_AddonPrefs(AddonPreferences):
    bl_idname = _PKG

    sfm_usermod: StringProperty(
        name="SFM usermod Folder",
        description="The SourceFilmmaker game/usermod folder. Leave empty to "
                    "auto-detect it from Steam (registry, every library, the "
                    "common layouts on every drive). Set it only if detection "
                    "picks the wrong install or none at all",
        subtype="DIR_PATH", update=_rescan)
    pcf_dir: StringProperty(
        name="Particles (.pcf)",
        description="Where the .pcf browser opens. Empty: the detected "
                    "usermod/particles",
        subtype="DIR_PATH", update=_changed)
    texture_dir: StringProperty(
        name="Textures (.vtf / .vmt)",
        description="Where the texture and material browsers open. Empty: "
                    "the first materials folder that exists under the "
                    "detected usermod",
        subtype="DIR_PATH", update=_changed)
    trail_dir: StringProperty(
        name="Beam / Trail Textures",
        description="Where the rope and sprite-trail browsers open. Empty: "
                    "the known beam folders (tf/materials/effects and "
                    "friends), most specific first",
        subtype="DIR_PATH", update=_changed)
    viewport_facing: bpy.props.BoolProperty(
        name="Viewport-Facing Sprites (Camera Source 2)",
        description="Build systems able to face the VIEWPORT as you orbit "
                    "(Camera Source mode 2). The node that reads the "
                    "viewport makes a whole system re-evaluate on every "
                    "view change even while mode 0 or 1 is selected - "
                    "enormous viewport lag on heavy effects - so it is only "
                    "built in when asked. Off: mode 2 behaves like mode 0 "
                    "(active camera). Applies to NEW builds; re-import an "
                    "effect to change it",
        default=False, update=_changed)
    fancy_layouts: bpy.props.BoolProperty(
        name="Beautiful Node Layouts",
        description="Arrange every built node graph for reading: per-section "
                    "inputs, text room for the notes, the hand-cleaned "
                    "layouts, section packing. Every one of those edits pays "
                    "Blender's per-change full-tree update, so on a big "
                    "multi-system effect this is roughly HALF the import "
                    "time. Turn it off to import fast with plain "
                    "builder-placed graphs - colours and notes stay either "
                    "way",
        default=True, update=_changed)
    log_to_file: bpy.props.BoolProperty(
        name="Write Log File",
        description="Keep everything this add-on prints in _Logs/Source Particle Import_<date>.log (one file per "
                    "Blender session, the newest 20 kept). PRINT HELP puts the newest one into the .txt you send. "
                    "The console prints either way.\n\nTHIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN "
                    "EXPERIMENTAL STAGE",
        default=True, update=_log_to_file_changed)
    feedback: bpy.props.EnumProperty(
        name="Errors",
        description="How a failed import or tool tells you. Every failure is also printed (marked "
                    "[Source Particle Import]) and logged with the .pcf it was reading.\n\nTHIS FEATURE WAS ADDED "
                    "IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE",
        items=[("POPUP", "Popup", "The status bar, plus a popup with the details and a Print Help button"),
               ("REPORT", "Status Bar", "Blender's status bar and Info editor only"),
               ("QUIET", "Console Only", "Nothing on screen - the console and the log file only")],
        default="POPUP", update=_changed)

    def draw(self, context):
        draw_settings(self.layout, self, sidebar=False)
        box = self.layout.box()
        box.label(text="Reports", icon="TEXT")
        col = box.column()
        col.prop(self, "log_to_file")
        row = col.row(align=True)
        row.prop(self, "feedback", expand=True)


def draw_settings(layout, p, sidebar=True):
    """Source Filmmaker, Browsers Open In, Building - the preferences page and Dev > Configure draw the same
    three boxes. In the sidebar a folder's name sits above its field - the panel is too narrow for both on one line."""
    box = layout.box()
    box.label(text="Source Filmmaker", icon="FILE_FOLDER")
    col = box.column(align=True)
    col.prop(p, "sfm_usermod", text="")
    found = find_usermod()
    status = col.row()
    status.enabled = False
    status.label(text=str(found) if found is not None else "found by itself when empty - not found now",
                 icon="CHECKMARK" if found is not None else "ERROR")

    box = layout.box()
    box.label(text="Browsers Open In", icon="FILEBROWSER")
    col = box.column()
    for key in ("pcf_dir", "texture_dir", "trail_dir"):
        if sidebar:
            sub = col.column(align=True)
            sub.label(text=p.bl_rna.properties[key].name)
            sub.prop(p, key, text="")
        else:
            col.prop(p, key)

    box = layout.box()
    box.label(text="Building", icon="PARTICLES")
    col = box.column()
    col.prop(p, "fancy_layouts")
    col.prop(p, "viewport_facing")


class HTP_OT_OpenPrefs(bpy.types.Operator):
    """Open this add-on's preferences and pick your preferred paths.

The SFM install is auto-detected from Steam, and every file browser opens
at the most useful folder it can find. The preferences let you override
any of that: point at a different usermod, or choose your own folders for
the .pcf, texture and beam browsers"""
    bl_idname = "htp.open_prefs"
    bl_label = "Source Particle Import Preferences"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        try:
            bpy.ops.screen.userpref_show()
            bpy.ops.preferences.addon_show(module=_PKG)
        except Exception as exc:
            self.report({"ERROR"}, f"could not open preferences: {exc}")
            return {"CANCELLED"}
        return {"FINISHED"}


CLASSES = (HTP_AddonPrefs, HTP_OT_OpenPrefs)


def register():
    # 3.0.0: _config/config.json, when you have one, wins over what Blender saved (tools/config)
    from ..tools import config
    _done, problems = config.apply(prefs())
    for line in problems:
        print("[CONFIG]  skipped - %s" % line)
    push_log_settings()
