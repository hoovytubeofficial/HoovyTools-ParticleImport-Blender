
import json
import platform
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator

from ..icons import icon_id
from ..tools import htlog
from . import op_prefs

OK, WARN, BAD = "OK", "WARN", "BAD"
_ICON = {OK: ("status_ok", "CHECKMARK"), WARN: ("status_warn", "ERROR"), BAD: ("status_bad", "CANCEL")}
HELP_STEM = "__Source Particle Import Log Report Data__"
_PKG = __package__.split(".")[0]
_CACHE = {"key": None, "rows": None}
SESSION_IMPORTER = ("HoovyTools-SFMSessionImport-Blender-Master", "HoovyTools-SFMSessionImport-Blender-master",
                    "HoovyTools-SFMSessionImport-Blender-main")


def addon_version():
    try:
        return ".".join(str(v) for v in sys.modules[_PKG].bl_info["version"])
    except Exception:
        return "?"


#── the checks ────────────────────────────────────────────────────────────

def _check_usermod(_ctx):
    found = op_prefs.find_usermod()
    if found is None:
        return (BAD, "not found", "No SourceFilmmaker usermod folder was found. LOAD it (or set it in the "
                "add-on's preferences) - the .pcf browser and every texture lookup start there", None,
                ("folder", "sfm_usermod"))
    return OK, "found", str(found), Path(found), None


def _check_particles(_ctx):
    d = op_prefs.particles_dir()
    if d is None or not Path(d).is_dir():
        return (WARN, "no folder", "No particles folder under the usermod - LOAD the folder your .pcf files are in",
                None, ("folder", "pcf_dir"))
    n = sum(1 for _ in Path(d).rglob("*.pcf"))
    return (OK if n else WARN), "%d .pcf" % n, str(d), Path(d), None


def _check_materials(_ctx):
    d = op_prefs.texture_dir()
    if d is None or not Path(d).is_dir():
        return (WARN, "not found", "No materials folder - every sprite falls back to the bundled spark / glow / "
                "beam material. LOAD the folder your .vmt / .vtf files are in", None, ("folder", "texture_dir"))
    return OK, "found", str(d), Path(d), None


def _check_fallbacks(_ctx):
    mdir = Path(__file__).resolve().parent.parent / "materials"
    have = sorted(p.name for p in mdir.glob("*.vtf")) if mdir.is_dir() else []
    if len(have) < 3:
        return (BAD, "%d of 3" % len(have), "The add-on's materials folder is incomplete - a system whose texture "
                "is missing has nothing to stand in. Reinstall the add-on", mdir, None)
    return OK, "3 bundled", ", ".join(have), mdir, None


def _check_pillow(_ctx):
    try:
        import PIL
        return OK, "Pillow %s" % getattr(PIL, "__version__", "?"), PIL.__file__, None, None
    except Exception:
        py = Path(sys.executable)
        return (WARN, "missing", "PCF Preview draws its cards with Pillow, which this Blender's Python does not "
                "have. Everything else works. To add it: \"%s\" -m pip install Pillow" % py, None, None)


def _check_worker(_ctx):
    exe = Path(bpy.app.binary_path or "")
    if exe.is_file():
        return OK, "found", str(exe), exe.parent, None
    return (WARN, "not found", "PCF Preview renders in a second Blender and cannot find this one's program file",
            None, None)


def _check_logs(_ctx):
    d = htlog.logs_dir()
    if d is None:
        return WARN, "not writable", "No folder for the log and the PRINT HELP files - console only", None, None
    return OK, d.name, str(d), d, None


def _check_session_importer(_ctx):
    import addon_utils
    installed = {m.__name__ for m in addon_utils.modules()}
    for name in SESSION_IMPORTER:
        _loaded, enabled = addon_utils.check(name)
        if enabled:
            mod = sys.modules.get(name)
            v = getattr(mod, "bl_info", {}).get("version") if mod else None
            return OK, ("v" + ".".join(str(x) for x in v)) if v else "enabled", name, None, None
        if name in installed:
            return (WARN, "installed, off", "SFM Session Importer is installed but not enabled - turn it on to "
                    "import whole SFM sessions with their particles", None, ("enable", name))
    return OK, "optional", "SFM Session Importer imports whole SFM sessions, particles included - not needed " \
        "for anything here", None, None


def _check_icons(_ctx):
    from .. import icons
    have = len(icons._pcoll) if icons._pcoll is not None else 0
    want = len(icons.ICON_KEYS)
    return (OK if have >= want else WARN), "%d/%d" % (have, want), str(icons.ICONS_DIR), icons.ICONS_DIR, None


def _check_chosen(ctx):
    from . import op_particle_import as pi
    p = pi.props(ctx) if ctx is not None else None
    raw = getattr(p, "definition_file", "") if p is not None else ""
    if not raw:
        return OK, "none chosen", "Pick one on the Import tab", None, None
    f = Path(bpy.path.abspath(raw))
    if not f.is_file():
        return BAD, "file is gone", str(f), f.parent, None
    n = len(pi._STASH.get("picker") or [])
    return OK, f.name if len(f.name) < 26 else f.name[:23] + "...", "%s (%d systems)" % (f, n), f.parent, None


def _check_built(_ctx):
    hosts = [o for o in bpy.data.objects if o.get("htp_system")]
    files = sorted({str(o.get("htp_pcf_path") or "") for o in hosts} - {""})
    return OK, "%d system(s)" % len(hosts), "  |  ".join(files[:6]) or "nothing imported yet", None, None


# order is the order things fail in. The two below the line are about THIS .blend, not the install
CHECKS = (("usermod", "SFM usermod", _check_usermod), ("particles", "Particles", _check_particles),
          ("materials", "Materials", _check_materials), ("fallbacks", "Fallbacks", _check_fallbacks),
          ("pillow", "Preview cards", _check_pillow), ("worker", "Worker Blender", _check_worker),
          ("logs", "Log folder", _check_logs), ("session", "Session Importer", _check_session_importer))
PROJECT = (("chosen", "Chosen .pcf", _check_chosen), ("built", "Built here", _check_built))
REPORT_ONLY = (("icons", "Panel icons", _check_icons),)


def _row(key, label, fn, ctx):
    try:
        status, value, detail, path, fix = fn(ctx)
    except Exception as exc:                                     # a check that raises is a red row, never a blank tab
        status, value, detail, path, fix = BAD, "check failed", "%s: %s" % (type(exc).__name__, exc), None, None
    return {"key": key, "label": label, "status": status, "value": value, "detail": detail,
            "path": str(path) if path else "", "fix": fix}


def _key(ctx):
    p = op_prefs.prefs()
    bits = tuple(str(getattr(p, a, "")) for a in ("sfm_usermod", "pcf_dir", "texture_dir")) if p else ()
    try:
        from . import op_particle_import as pi
        chosen = str(getattr(pi.props(ctx), "definition_file", ""))
    except Exception:
        chosen = ""
    return bits + (chosen, len(bpy.data.objects))


def wiring(ctx, force=False, include_hidden=False):
    k = _key(ctx)
    if force or _CACHE["rows"] is None or _CACHE["key"] != k:
        _CACHE["rows"] = [_row(a, b, c, ctx) for a, b, c in CHECKS + PROJECT]
        _CACHE["key"] = k
    rows = list(_CACHE["rows"])
    if include_hidden:
        rows += [_row(a, b, c, ctx) for a, b, c in REPORT_ONLY]
    return rows


def summary(rows):
    return (sum(r["status"] == OK for r in rows), sum(r["status"] == WARN for r in rows),
            sum(r["status"] == BAD for r in rows))


# ── operators ─────────────────────────────────────────────────────────────

class HTP_OT_RecheckWiring(Operator):
    """Run the wiring checks against the disk again.

The readout is cached - draw() runs on every mouse move - and refreshes by
itself when a preference path, the chosen .pcf or the scene changes. Press
this after changing something OUTSIDE Blender: installing Pillow, moving
the SFM folder, adding .pcf files"""
    bl_idname = "htp.recheck_wiring"
    bl_label = "Re-check Wiring"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        rows = wiring(context, force=True, include_hidden=True)
        ok, warn, bad = summary(rows)
        for r in rows:
            print("[HT_WIRING]  %-5s %-16s %-20s %s" % (r["status"], r["label"], r["value"], r["detail"]))
        self.report({"INFO" if not bad else "WARNING"}, "Wiring: %d ok, %d to look at, %d broken" % (ok, warn, bad))
        return {"FINISHED"}


class HTP_OT_SetPrefFolder(Operator):
    """Pick the folder this row needs - saved in the add-on's preferences (empty there = found by itself)"""
    bl_idname = "htp.set_pref_folder"
    bl_label = "Load Folder"
    bl_options = {"INTERNAL"}

    pref: bpy.props.EnumProperty(items=[("sfm_usermod", "SFM usermod", ""), ("pcf_dir", "Particles", ""),
                                        ("texture_dir", "Materials", ""), ("trail_dir", "Beam textures", "")],
                                 options={"HIDDEN"})
    directory: bpy.props.StringProperty(subtype="DIR_PATH")

    @classmethod
    def description(cls, context, properties):
        return {"sfm_usermod": "Pick your SourceFilmmaker\\game\\usermod folder",
                "pcf_dir": "Pick the folder your .pcf files are in",
                "texture_dir": "Pick the materials folder your .vmt / .vtf files are in",
                "trail_dir": "Pick the folder of beam and trail textures"}.get(properties.pref, "") + (
            "\n\nTHIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE")

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        p = op_prefs.prefs()
        if p is None or not self.directory:
            self.report({"ERROR"}, "No folder picked")
            return {"CANCELLED"}
        setattr(p, self.pref, self.directory)
        wiring(context, force=True)
        self.report({"INFO"}, "%s: %s" % (self.pref, self.directory))
        return {"FINISHED"}


class HTP_OT_EnableSessionImporter(Operator):
    """Turn SFM Session Importer on - it is installed, only switched off"""
    bl_idname = "htp.enable_session_importer"
    bl_label = "Enable SFM Session Importer"
    bl_options = {"INTERNAL"}

    module: bpy.props.StringProperty(options={"HIDDEN"})

    def execute(self, context):
        import addon_utils
        try:
            addon_utils.enable(self.module, default_set=True)
        except Exception as exc:
            self.report({"ERROR"}, "Could not enable %s: %s" % (self.module, exc))
            return {"CANCELLED"}
        wiring(context, force=True)
        return {"FINISHED"}


class HTP_OT_OpenLogFolder(Operator):
    """Open the folder the log and the PRINT HELP files are written to.

One log per Blender session (the newest 20 are kept) and every PRINT HELP
file, numbered. Nothing reads them back - delete them whenever you like"""
    bl_idname = "htp.open_log_folder"
    bl_label = "Open Log Folder"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        d = htlog.logs_dir()
        if d is None:
            self.report({"ERROR"}, "No log folder could be made")
            return {"CANCELLED"}
        bpy.ops.wm.path_open(filepath=str(d))
        return {"FINISHED"}


def _reveal(path):
    if sys.platform == "win32":
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
            return "folder opened, file selected"
        except Exception:
            pass
    try:
        bpy.ops.wm.path_open(filepath=str(Path(path).parent))
        return "folder opened"
    except Exception as exc:
        return "could not open the folder (%s)" % exc


def _sec(title):
    return ["", "-- %s " % title + "-" * max(4, 72 - len(title)), ""]


def behavior_lines(context):
    """ADDON BEHAVIOR: versions, wiring, preferences, the chosen file, what this .blend holds, what happened."""
    import addon_utils
    L = ["=" * 78, "  SOURCE PARTICLE IMPORT  -  ADDON BEHAVIOR REPORT", "  generated %s" % time.strftime(
        "%Y-%m-%d %H:%M:%S"), "=" * 78]
    L += _sec("VERSIONS")
    L += ["  Source Particle Import  %s  (%s)" % (addon_version(), _PKG),
          "  Blender                 %s" % bpy.app.version_string,
          "  Python                  %s" % sys.version.split()[0],
          "  Platform                %s" % platform.platform()]
    L += _sec("WIRING")
    for r in wiring(context, force=True, include_hidden=True):
        L.append("  %-5s %-17s %s" % (r["status"], r["label"], r["value"]))
        if r["detail"]:
            L.append("        %s" % r["detail"])
    L += _sec("PREFERENCES")
    p = op_prefs.prefs()
    for attr in ("sfm_usermod", "pcf_dir", "texture_dir", "trail_dir", "fancy_layouts", "viewport_facing",
                 "log_to_file", "feedback"):
        v = getattr(p, attr, "<missing>") if p is not None else "<no preferences>"
        L.append("  %-17s %s" % (attr, v if v not in ("", None) else "(blank - auto-detect)"))
    L += _sec("THE CHOSEN .PCF")
    try:
        from . import op_particle_import as pi
        pr = pi.props(context)
        L.append("  file     %s" % (getattr(pr, "definition_file", "") or "(none)"))
        L.append("  system   %s" % (getattr(pr, "system", "") or "(none)"))
        for name, depth in (pi._STASH.get("picker") or [])[:60]:
            L.append("    %s%s" % ("  " * depth, name))
    except Exception as exc:
        L.append("  unavailable: %s" % exc)
    L += _sec("WHAT THIS .BLEND HOLDS")
    hosts = [o for o in bpy.data.objects if o.get("htp_system")]
    L.append("  blend file     %s" % (bpy.data.filepath or "(unsaved)"))
    L.append("  systems built  %d" % len(hosts))
    for o in hosts[:80]:
        L.append("    %-40s %s" % (o.name[:40], o.get("htp_pcf_path", "")))
    L += _sec("ADD-ONS")
    for name in (_PKG,) + SESSION_IMPORTER + ("SourceIO", "SourceIO-master", "io_scene_valvesource"):
        loaded, enabled = addon_utils.check(name)
        if loaded or enabled:
            L.append("  %-46s loaded=%s enabled=%s" % (name, bool(loaded), bool(enabled)))
    hist = htlog.history()
    L += _sec("WHAT HAPPENED THIS SESSION (%d)" % len(hist))
    if not hist:
        L += ["  Nothing reported yet. Reproduce the problem, THEN press Print Help."]
    for h in hist:
        L.append("  %s  %-7s %s" % (h["t"], h["level"], h["title"]))
        L += ["            %s" % ln for ln in h["lines"]]
    return L


def help_flags(context):
    """[(level, sentence)], worst first - the WHAT'S WRONG list."""
    flags = []
    for r in wiring(context, force=True):
        if r["status"] == OK:
            continue
        lvl = "BREAKS" if r["status"] == BAD else "RISKY"
        flags.append((lvl, "%s is %s - %s" % (r["label"], r["value"], r["detail"])))
    for h in htlog.history():
        if h["level"] == "ERROR":
            first = h["lines"][0] if h["lines"] else ""
            flags.append(("BREAKS", "'%s' failed at %s%s" % (h["title"], h["t"], (" (" + first + ")") if first else "")))
        elif h["level"] == "WARNING":
            flags.append(("RISKY", "'%s' ended with a warning at %s" % (h["title"], h["t"])))
    order = {"BREAKS": 0, "RISKY": 1, "NOTE": 2}
    return sorted(flags, key=lambda f: order.get(f[0], 9))


def help_paragraph(flags):
    serious = [f for f in flags if f[0] in ("BREAKS", "RISKY")]
    if not serious:
        return ("The checks below found no known problem: Source Particle Import finds SFM and everything it "
                "uses, and nothing it reported has failed since Blender started. The checks only know the problems "
                "already seen - if something still went wrong, do it again and press PRINT HELP right after; this "
                "file then shows what happened.")
    head = ("Look, Source Particle Import ran into trouble on this computer, but fear not!" if any(
        f[0] == "BREAKS" for f in serious) else "Look, Source Particle Import mostly works here, but a few things "
            "are off - fear not!")
    ords = ("First of all", "Second", "Third", "Fourth", "Fifth")
    parts = [head] + ["%s, %s." % (ords[i] if i < len(ords) else "Also", s.rstrip(".")) for i, (_l, s) in
                      enumerate(serious[:5])]
    if len(serious) > 5:
        parts.append("And %d more in the list below." % (len(serious) - 5))
    return " ".join(parts + ["Fix the BREAKS first, then press PRINT HELP again."])


def help_path(folder):
    import re
    rx = re.compile(re.escape(HELP_STEM) + r" \(V(\d+)\)\.txt$")
    top = 0
    for f in folder.glob(HELP_STEM + " (V*).txt"):
        m = rx.match(f.name)
        if m:
            top = max(top, int(m.group(1)))
    return folder / ("%s (V%d).txt" % (HELP_STEM, top + 1)), top + 1


def collect_help(context, version):
    flags = help_flags(context)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    L = ["=" * 78, "  %s (V%d)" % (HELP_STEM, version),
         "  Source Particle Import %s  -  Blender %s  -  %s" % (addon_version(), bpy.app.version_string, stamp),
         "=" * 78, "", "  THIS FILE CONTAINS FILE PATHS FROM THIS COMPUTER, which include your user name.",
         "  Read it before you post it anywhere public.", ""]
    L += _sec("IN PLAIN WORDS") + ["  " + ln for ln in textwrap.wrap(help_paragraph(flags), 74)]
    L += _sec("WHAT'S WRONG (%d)" % len(flags))
    if not flags:
        L.append("  The checks found nothing - but they only know the problems already seen. If something went")
        L.append("  wrong, write what you did and what happened when you send this file.")
    for lvl, sentence in flags:
        w = textwrap.wrap(sentence, 64) or [""]
        L.append("  [%-6s] %s" % (lvl, w[0]))
        L += ["           %s" % x for x in w[1:]]
    fails = [h for h in htlog.history() if h["level"] == "ERROR"]
    L += _sec("FAILURES THIS SESSION, IN FULL (%d)" % len(fails))
    for h in fails:
        L.append("  %s  %s" % (h["t"], h["title"]))
        L += ["      %s" % ln for ln in h["lines"]]
        L += ["      %s" % ln for ln in h.get("traceback", [])[-25:]]
        L.append("")
    L += ["", "=" * 78, "  ADDON BEHAVIOR", "=" * 78]
    try:
        L += behavior_lines(context)
    except Exception as exc:
        import traceback
        L += ["  addon behavior failed: %s" % exc] + traceback.format_exc().splitlines()
    con = htlog.lines()
    L += ["", "=" * 78, "  CONSOLE  (every line this add-on printed since Blender started: %d)" % len(con), "=" * 78]
    L += con[-3000:]
    L += ["", "=" * 78, "  LOGS  (this Blender session's log, then the end of the older ones)", "=" * 78]
    d = htlog.logs_dir(create=False)
    cur = htlog.log_path()
    logs = sorted(d.glob(htlog.LOG_STEM + "*.log"), key=lambda f: f.stat().st_mtime, reverse=True) if d else []
    for i, f in enumerate(logs[:4]):
        try:
            text = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        keep = 4000 if f == cur else 400
        L += ["", "--- %s (%s, %d lines) ---" % (f.name, "this session" if f == cur else "earlier", len(text))]
        L += text[-keep:]
    data = {"tool": "Source Particle Import", "version": addon_version(), "blender": bpy.app.version_string,
            "generated": stamp, "flags": [{"level": a, "what": b} for a, b in flags],
            "wiring": [{k: r[k] for k in ("key", "status", "value", "detail")} for r in
                       wiring(context, include_hidden=True)],
            "failures": [{k: h.get(k) for k in ("t", "title", "lines", "pcf")} for h in fails]}
    L += ["", "=" * 78, "  FOR THE DEVELOPER  (the same facts as JSON)", "=" * 78, ""]
    L += json.dumps(data, indent=2, default=str).splitlines()
    L += ["", "=" * 78, "  end of report", "=" * 78]
    return L, flags


class HTP_OT_PrintHelp(Operator):
    """Write ONE .txt to send when something goes wrong - it says what is wrong first.

Writes "__Source Particle Import Log Report Data__ (V#).txt" into the log
folder (a new number every press) and opens the folder with it selected.
At the top, in plain words: what is broken and what to fix first. Then
every failure of this session in full - the .pcf, the system, the error and
where in the add-on it happened - the add-on's behavior, its console lines
and its logs.

REPRODUCE THE PROBLEM FIRST, THEN PRESS THIS.

It holds file paths from this computer, including your user name. Read it
before you post it anywhere public.

THIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE"""
    bl_idname = "htp.print_help"
    bl_label = "Print Help"
    bl_options = {"INTERNAL"}

    open_folder: BoolProperty(name="Open the folder afterwards", default=True)

    def execute(self, context):
        d = htlog.logs_dir()
        if d is None:
            self.report({"ERROR"}, "No folder can be written for the help file")
            return {"CANCELLED"}
        path, version = help_path(d)
        try:
            lines, flags = collect_help(context, version)
        except Exception as exc:
            import traceback
            lines, flags = ["%s (V%d) - COLLECTION FAILED" % (HELP_STEM, version), str(exc)] + \
                traceback.format_exc().splitlines(), []
        path.write_text("\n".join(lines), encoding="utf-8")
        note = _reveal(path) if (self.open_folder and not bpy.app.background) else "not opened"
        print("[HT_HELP]  %s written - %d problem(s) listed" % (path, len(flags)))
        worst = flags[0][0] if flags else None
        self.report({"WARNING" if worst == "BREAKS" else "INFO"},
                    "%s written - %d problem(s) listed - %s" % (path.name, len(flags), note))
        return {"FINISHED"}


class HTP_OT_PrintBehavior(Operator):
    """Write the add-on's behavior report to a .txt and open its folder.

Versions, the wiring readout, your preferences, the chosen .pcf and its
systems, everything built in this .blend with the .pcf it came from, which
add-ons are loaded, and what was reported since Blender started. PRINT HELP
contains all of this too - this is the short one"""
    bl_idname = "htp.print_behavior"
    bl_label = "Print Addon Behavior"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        d = htlog.logs_dir()
        if d is None:
            self.report({"ERROR"}, "No folder can be written for the report")
            return {"CANCELLED"}
        path = d / (time.strftime("%Y-%m-%d %H-%M") + " Behavior report.txt")
        n = 2
        while path.exists():
            path = d / (time.strftime("%Y-%m-%d %H-%M") + " Behavior report (%d).txt" % n)
            n += 1
        path.write_text("\n".join(behavior_lines(context)), encoding="utf-8")
        note = _reveal(path) if not bpy.app.background else "not opened"
        self.report({"INFO"}, "%s written - %s" % (path.name, note))
        return {"FINISHED"}


#── drawing ───────────────────────────────────────────────────────────────

def _row_button(row, r):
    """The one button a row needs, as SFM Session Importer draws it: LOAD (or ENABLE) when it is not there, the
    folder when it is, nothing otherwise."""
    fix = r.get("fix")
    if fix and fix[0] == "folder":
        row.operator("htp.set_pref_folder", text="LOAD", icon="FILEBROWSER").pref = fix[1]
    elif fix and fix[0] == "enable":
        row.operator("htp.enable_session_importer", text="ENABLE", icon="CHECKBOX_HLT").module = fix[1]
    elif r["path"]:
        row.operator("wm.path_open", text="", icon="FILE_FOLDER").filepath = r["path"]
    else:
        row.label(text="", icon="BLANK1")


def _line(col):
    """A thin rule between two wiring rows."""
    col.separator(factor=0.6, type="LINE")


def draw_wiring(layout, context):
    from .op_panel import fold
    p = context.scene.htp
    rows = wiring(context)
    ok, warn, bad = summary(rows)
    if bad:
        title, st = "Wiring - %d broken" % bad, BAD
    else:
        title, st = ("Wiring - ready" if warn else "Wiring - all connected"), OK
    box, head = fold(layout, p, "sec_dev_wiring", title, icon_id("sec_wiring", "PLUGIN"))
    right = head.row(align=True)
    right.alignment = "RIGHT"
    right.label(text="", **icon_id(*_ICON[st]))
    right.operator("htp.recheck_wiring", text="", icon="FILE_REFRESH")
    if box is None:
        return
    #EVERY ROW the same THREE SYMBOLS AS SFM SESSION IMPORTER'S, a rule between rows
    col = box.column()
    split_done = False
    for i, r in enumerate(rows):
        if r["key"] in ("chosen", "built") and not split_done:
            split_done = True
            col.separator(factor=1.4)                   # the install above, this .blend below
        elif i:
            _line(col)
        row = col.row(align=True)
        row.label(text=r["label"], **icon_id(*_ICON[r["status"]]))
        val = row.row(align=True)
        val.alignment = "RIGHT"
        val.enabled = r["status"] == OK
        val.label(text=r["value"])
        _row_button(row, r)
    for r in rows:
        if r["status"] == BAD:
            note = box.row()
            note.alert = True
            note.scale_y = 0.75
            note.label(text="%s: %s" % (r["label"], (textwrap.wrap(r["detail"], 54) or [""])[0]))

    box.separator(factor=0.4)
    row = box.row(align=True)
    row.operator("htp.open_config", text="Open Config", **icon_id("dev_config", "FILE_TEXT"))
    row.operator("htp.reload_config", text="", icon="FILE_REFRESH")


def draw_behavior(layout, context):
    """The same shape as SFM Session Importer's: the version, PRINT HELP, then Print Addon Behavior and the log
    folder, then Logs folded inside."""
    from .op_panel import fold
    p = context.scene.htp
    box, _head = fold(layout, p, "sec_dev_behavior", "Behavior Report", icon_id("print_help", "FILE_TEXT"))
    if box is None:
        return
    ver = box.row()
    ver.alignment = "CENTER"
    ver.label(text="Source Particle Import %s" % addon_version(), **icon_id("particle_import", "INFO"))
    run = box.column(align=True)
    run.scale_y = 1.6
    run.operator("htp.print_help", text="PRINT HELP", **icon_id("print_help", "HELP"))
    row = box.row(align=True)
    row.operator("htp.print_behavior", text="Print Addon Behavior", **icon_id("print_behavior", "FILE_TEXT"))
    row.operator("htp.open_log_folder", text="", **icon_id("log_folder", "FILE_FOLDER"))
    lbox, _lh = fold(box, p, "sec_dev_logs", "Logs", icon_id("logs", "TEXT"))
    if lbox is None:
        return
    prefs = op_prefs.prefs()
    if prefs is None:
        lbox.label(text="Unavailable - re-enable the add-on.", icon="ERROR")
        return
    col = lbox.column(align=True)
    col.use_property_split = False
    col.prop(prefs, "log_to_file", toggle=True, icon="TEXT")
    col.prop(prefs, "feedback", expand=True)
    col.separator()
    col.operator("htp.copy_support", text="Copy Console Output", **icon_id("copy_support", "COPYDOWN"))


def draw_configure(layout, context):
    """CONFIGURE: the add-on's settings in the panel - the same boxes as Edit > Preferences."""
    from .op_panel import fold
    p = context.scene.htp
    box, _head = fold(layout, p, "sec_dev_configure", "Configure", icon_id("dev_config", "PREFERENCES"))
    if box is None:
        return
    prefs = op_prefs.prefs()
    if prefs is None:
        box.label(text="Unavailable - re-enable the add-on.", icon="ERROR")
        return
    op_prefs.draw_settings(box, prefs, sidebar=True)


LINKS = {
    "patreon": ("Patreon", "FUND", "https://www.patreon.com/HoovyTube308", "HoovyTube on Patreon"),
    "website": ("Website", "WORLD", "https://hoovytube.com", "HoovyTube's website"),
    "github": ("GitHub", "URL", "https://github.com/hoovytubeofficial/HoovyTools-ParticleImport-Blender",
               "The source of truth: the newest version of Source Particle Import, its code and its changes"),
}


def draw_credits(layout, context):
    from .op_panel import fold
    p = context.scene.htp
    box, _head = fold(layout, p, "sec_dev_credits", "Credits", icon_id("particle_import", "HEART"))
    if box is None:
        return
    box.label(text="Made by HoovyTube", **icon_id("particle_import", "HEART"))
    links = box.row(align=True)
    for key, (text, icon, _url, _desc) in LINKS.items():
        links.operator("htp.open_link", text=text, icon=icon).which = key
    row = box.row(align=True)
    note = row.row()
    note.enabled = False
    note.label(text="Free for everyone")
    lic = Path(__file__).resolve().parent.parent / "LICENSE.txt"
    btn = row.row(align=True)
    btn.ui_units_x = 4.5
    btn.enabled = lic.is_file()
    btn.operator("wm.path_open", text="License", icon="TEXT").filepath = str(lic)
    sub = box.column(align=True)
    sub.enabled = False
    sub.label(text="DMX reader: Tom Edwards (MIT)")


def draw_developer_mode(layout, context):
    """The DEVELOPER MODE switch, the last thing on the Dev tab - the same in both add-ons."""
    p = context.scene.htp
    layout.separator(factor=0.5)
    row = layout.row(align=True)
    row.scale_y = 1.4
    row.prop(p, "developer_mode", toggle=True, text="DEVELOPER MODE",
             **icon_id("developer_mode", "CHECKBOX_HLT" if p.developer_mode else "CHECKBOX_DEHLT"))


def draw_dev(layout, context):
    """The Dev tab, in SFM Session Importer's order: Wiring first, Behavior Report, Configure, Credits - and Developer Mode at the bottom."""
    draw_wiring(layout, context)
    draw_behavior(layout, context)
    draw_configure(layout, context)
    draw_credits(layout, context)
    draw_developer_mode(layout, context)


class HTP_OT_OpenConfig(Operator):
    """Open the settings file to write it by hand: _config/config.json - the same settings as Edit > Preferences
(the SFM folder, where the browsers open, the build options, the reports). The first press writes it from the
settings in use now; after you save it, Reload Config (or the next Blender start) applies it.

THIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE"""
    bl_idname = "htp.open_config"
    bl_label = "Open Config"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..tools import config
        prefs = op_prefs.prefs()
        if prefs is None:
            self.report({"ERROR"}, "The add-on's preferences are not reachable - re-enable the add-on")
            return {"CANCELLED"}
        path = config.path()
        if not path.is_file():
            config.write(prefs)
        if bpy.app.background:
            print("[CONFIG]  %s" % path)
        else:
            bpy.ops.wm.path_open(filepath=str(path))
        self.report({"INFO"}, str(path))
        return {"FINISHED"}


class HTP_OT_ReloadConfig(Operator):
    """Apply _config/config.json now - after you edited it by hand. A setting you deleted keeps its value; one of
the wrong kind is skipped and named.

THIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE"""
    bl_idname = "htp.reload_config"
    bl_label = "Reload Config"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        from ..tools import config
        if not config.path().is_file():
            self.report({"WARNING"}, "No config file yet - Open Config writes one")
            return {"CANCELLED"}
        done, bad = config.apply(op_prefs.prefs())
        wiring(context, force=True)
        if bad:
            self.report({"WARNING"}, "Config: %d setting(s) applied, skipped: %s" % (len(done), "; ".join(bad)))
        else:
            self.report({"INFO"}, "Config: %d setting(s) applied" % len(done))
        return {"FINISHED"}


class HTP_OT_OpenLink(Operator):
    """Open HoovyTube's page"""
    bl_idname = "htp.open_link"
    bl_label = "Open Link"
    bl_options = {"INTERNAL"}

    which: bpy.props.EnumProperty(items=[(k, v[0], v[3]) for k, v in LINKS.items()], options={"HIDDEN"})

    @classmethod
    def description(cls, context, properties):
        _name, _icon, url, desc = LINKS[properties.which]
        return "%s\n%s\n\nTHIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE" % (desc, url)

    def execute(self, context):
        bpy.ops.wm.url_open(url=LINKS[self.which][2])
        return {"FINISHED"}


CLASSES = (HTP_OT_RecheckWiring, HTP_OT_SetPrefFolder, HTP_OT_EnableSessionImporter, HTP_OT_OpenLogFolder,
           HTP_OT_PrintHelp, HTP_OT_PrintBehavior, HTP_OT_OpenConfig, HTP_OT_ReloadConfig, HTP_OT_OpenLink)
