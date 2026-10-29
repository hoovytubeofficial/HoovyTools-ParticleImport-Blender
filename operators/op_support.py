# =============================================================================
#  operators/op_support.py  -  one button that answers "send me your console"
# =============================================================================
#
#  Users reporting problems cannot be expected to fish lines out of a system
#  console. ONE click builds a paste-ready report - scene analysis on top,
#  every HoovyTools console line underneath - copies it to the clipboard and
#  saves it as a Text block. They paste it in Discord; the answer is usually
#  on the first screen (SKIPPED / FALLBACK / no .vmt found / versions).
# =============================================================================

import platform

import bpy
from bpy.types import Operator

from ..tools import htlog

TAG = "[HT_SUPPORT]"


def _addon_version():
    try:
        import HoovyToolsParticleImport
        return ".".join(str(v) for v in
                        HoovyToolsParticleImport.bl_info["version"])
    except Exception:
        return "?"


def _scene_analysis(context):
    """The facts a troubleshooter asks for first, gathered in one place."""
    scn = context.scene
    out = []
    out.append("=== HoovyTools support report ===")
    out.append(f"addon    : HoovyTools Particle Import {_addon_version()}")
    out.append(f"blender  : {bpy.app.version_string}")
    out.append(f"os       : {platform.platform()}")
    out.append(f"engine   : {scn.render.engine}   "
               f"view transform: {scn.view_settings.view_transform}")
    try:
        from . import op_particle_import as opi
        out.append(f"last pcf : {opi._STASH.get('path') or '(none loaded)'}")
    except Exception:
        pass

    hosts = [o for o in bpy.data.objects if o.get("htp_system")]
    containers = [o for o in hosts if o.get("htp_container")]
    dropped = sum(int(o.get("htp_dropped", 0)) for o in hosts)
    drivers = [m.name for m in bpy.data.materials
               if m.name.startswith("RAS Driver")]
    out.append(f"systems  : {len(hosts)} built "
               f"({len(containers)} containers), "
               f"{len(drivers)} invisible driver(s), "
               f"{dropped} attribute(s) not translated")

    log = htlog.lines()
    def count(needle):
        return sum(1 for l in log if needle in l)
    out.append(f"log      : {len(log)} HoovyTools line(s) captured - "
               f"{count('SKIPPED')} skip(s), {count('FALLBACK')} fallback(s), "
               f"{count('no .vmt found')} missing .vmt, "
               f"{count('not on disk')} missing .vtf, "
               f"{count('FAILED')} failure(s)")
    return out


class HTP_OT_CopySupport(Operator):
    """Copy a support report: scene analysis + HoovyTools console output

ONE CLICK, then paste (Ctrl+V) wherever you are asking for help. The
report starts with the facts a troubleshooter needs (add-on and Blender
versions, render engine, what was imported, how many systems built) and
then every console line HoovyTools printed this session - the SKIPPED /
FALLBACK / missing-file lines that explain most problems.

Only HoovyTools' own lines are included, nothing else from your console.
Also saved as a Text block ('HoovyTools support report') in case the
clipboard misbehaves."""
    bl_idname = "htp.copy_support"
    bl_label = "Copy Console Output"
    bl_options = {"REGISTER"}

    def execute(self, context):
        head = _scene_analysis(context)
        log = htlog.lines()
        body = ["", "=== console output (HoovyTools lines only) ==="]
        body += log if log else ["(nothing captured yet - import something "
                                 "first, then press this again)"]
        text = "\n".join(head + body)

        name = "HoovyTools support report"
        tb = bpy.data.texts.get(name) or bpy.data.texts.new(name)
        tb.clear()
        tb.write(text)
        copied = True
        try:
            context.window_manager.clipboard = text
        except Exception as exc:
            copied = False
            print(f"{TAG}  clipboard write failed: {exc}")
        n = len(log)
        if copied:
            self.report({"INFO"},
                        f"Support report copied - {n} console line(s) + scene "
                        f"analysis. Paste it wherever you're asking for help.")
        else:
            self.report({"WARNING"},
                        f"Clipboard refused - the report is in the Text block "
                        f"'{name}'.")
        return {"FINISHED"}


CLASSES = (HTP_OT_CopySupport,)


def register():
    htlog.start()


def unregister():
    htlog.stop()
