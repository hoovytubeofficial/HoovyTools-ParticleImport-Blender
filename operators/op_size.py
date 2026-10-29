
from pathlib import Path

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from ..tools import htlog, pcf_size

# the last answer, for the Tools tab (draw() reads, never computes).
LAST = {"pcf": "", "system": "", "lines": [], "total": None}


class HTP_OT_CalculateParticleSize(Operator):
    """Estimate how big an effect is, straight from its .pcf - nothing is imported.

Reads the .pcf and system chosen on the Import tab (none chosen: asks for a
file) and works out the box the effect can fill, in Hammer units and
metres: where particles spawn, how far the fastest one travels in the
longest lifetime (slowed by drag the way Source does it), how far gravity
pulls it, how jittery Random Force makes it, plus the largest card or
trail. Children born on their parent's particles start from the parent's
whole cloud.

An UPPER BOUND - turbulence, attraction and collisions only keep particles
closer. The console lists every system's numbers so a surprising size can
be traced to the operator behind it.

THIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE"""
    bl_idname = "htp.calculate_particle_size"
    bl_label = "Calculate Particle Size"
    bl_options = {"REGISTER"}

    whole_file: BoolProperty(
        name="Every Root System",
        description="Size every top-level effect in the .pcf instead of the system chosen on the Import tab",
        default=False)
    include_children: BoolProperty(
        name="Include Children",
        description="Count the child systems too - off sizes the chosen system on its own",
        default=True)
    # set by scripts (the Text Editor tool); the panel leaves them to the Import tab
    pcf_path: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    system: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    filepath: StringProperty(subtype="FILE_PATH", options={"HIDDEN", "SKIP_SAVE"})
    filter_glob: StringProperty(default="*.pcf", options={"HIDDEN"})

    def _target(self, context):
        if self.pcf_path:
            return self.pcf_path, (self.system or None)
        if self.filepath:
            return self.filepath, None
        from . import op_particle_import as pi
        p = pi.props(context)
        raw = getattr(p, "definition_file", "") if p is not None else ""
        sysname = getattr(p, "system", "") if p is not None else ""
        if raw:
            return bpy.path.abspath(raw), (None if sysname in ("", "__none__") else sysname)
        return "", None

    def invoke(self, context, event):
        pcf, _sys = self._target(context)
        if pcf:
            return self.execute(context)
        from . import op_prefs
        start = op_prefs.particles_dir()
        if start is not None:
            self.filepath = str(Path(start)) + "\\"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        pcf, system = self._target(context)
        if not pcf:
            self.report({"ERROR"}, "Choose a .pcf on the Import tab first (or run this from the file browser)")
            return {"CANCELLED"}
        system = None if self.whole_file else system
        try:
            res = pcf_size.estimate(pcf, system, include_children=self.include_children)
        except Exception as exc:
            msg = htlog.failure("Could not size the effect", pcf=pcf, system=system, exc=exc,
                                stage="reading the .pcf for its sizes",
                                hint="open the file in SFM's particle editor - if it loads there, send the "
                                     "PRINT HELP file")
            self.report({"ERROR"}, msg)
            htlog.popup_failure(context, "Could not size %s" % Path(pcf).name, [msg])
            return {"CANCELLED"}
        lines = pcf_size.report_lines(res)
        htlog.event("INFO", "Particle size: %s" % lines[0], lines[1:], pcf=pcf)
        LAST.update(pcf=pcf, system=system or "", lines=lines[:6], total=res["total"])
        for area in context.screen.areas if context.screen else ():
            area.tag_redraw()
        self.report({"INFO"}, "%s: %s" % (Path(pcf).name, pcf_size.fmt_size(res["total"])))
        return {"FINISHED"}


def draw_last(layout):
    """The last answer, under the tool's variables."""
    if not LAST["lines"]:
        return
    col = layout.column(align=True)
    col.scale_y = 0.85
    col.label(text=Path(LAST["pcf"]).name + ("  -  " + LAST["system"] if LAST["system"] else ""), icon="FILE")
    t = LAST["total"]
    col.label(text="%d x %d x %d u" % (round(t["width"]), round(t["depth"]), round(t["height"])),
              icon="CUBE")
    col.label(text="%.2f x %.2f x %.2f m" % (t["width"] * pcf_size.UNIT_M, t["depth"] * pcf_size.UNIT_M,
                                              t["height"] * pcf_size.UNIT_M), icon="BLANK1")


TOOL_DIR = Path(__file__).resolve().parent.parent / "# tools" / "Calculate Particle Size"


class HTP_OT_OpenSizeTool(Operator):
    """Open the folder holding the Text Editor version of Calculate Particle Size.

"Calculate Particle Size (V1).py" does the same from Blender's Text Editor:
set the .pcf (and a system, or none for every root) at the top, press Run
Script - the sizes print to the console.

THIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE"""
    bl_idname = "htp.open_size_tool"
    bl_label = "Open Calculate Particle Size Tool Folder"
    bl_options = {"INTERNAL"}

    def execute(self, context):
        if not TOOL_DIR.is_dir():
            self.report({"ERROR"}, "Missing: %s" % TOOL_DIR)
            return {"CANCELLED"}
        if bpy.app.background:
            print("[HT_SIZE]  tool folder: %s" % TOOL_DIR)
            return {"FINISHED"}
        bpy.ops.wm.path_open(filepath=str(TOOL_DIR))
        return {"FINISHED"}


CLASSES = (HTP_OT_CalculateParticleSize, HTP_OT_OpenSizeTool)
