"""Blender operators + panels. One op_<thing>.py per feature.

Each module exposes a CLASSES tuple; registration order matters only in that
op_particle_import's PropertyGroup must exist before Scene.htp points at it,
which its own register() handles.

3.0.0: every operator's execute runs inside _guard - the Tools tab's status
slot learns how the last press ended, and an exception becomes the detailed
error (the file it was on, where in the code it broke, what to try) instead
of a bare traceback in the console.
"""

import functools

import bpy

from . import op_prefs
from . import op_particle_import
from . import op_vtf
from . import op_vtf_sprite
from . import op_vmt
from . import op_ras
from . import op_rope
from . import op_trail
from . import op_grid
from . import op_node_to_code
from . import op_support
from . import op_pcf_preview
from . import op_size
from . import op_dev
from . import op_panel

_MODULES = (op_prefs, op_particle_import, op_vtf, op_vtf_sprite, op_vmt,
            op_ras, op_rope, op_trail, op_grid, op_node_to_code, op_support,
            op_pcf_preview, op_size, op_dev, op_panel)


def _file_of(op, context):
    """The file an operator was working on, for the error: its own path, else the .pcf chosen on the Import tab."""
    for attr in ("pcf_path", "filepath"):
        v = getattr(op, attr, "") or ""
        if v and not v.endswith(("\\", "/")):
            return bpy.path.abspath(v)
    try:
        raw = getattr(op_particle_import.props(context), "definition_file", "")
        return bpy.path.abspath(raw) if raw else None
    except Exception:
        return None


def _guard(cls):
    fn = getattr(cls, "execute", None)
    if fn is None or getattr(fn, "_htp_guarded", False):
        return

    @functools.wraps(fn)
    def execute(self, context):
        #  an instance reads its idname back in Blender's own form, HTP_OT_name - the panel keys by htp.name
        idname = getattr(self, "bl_idname", "") or getattr(cls, "bl_idname", "")
        if "_OT_" in idname:
            head, tail = idname.split("_OT_", 1)
            idname = head.lower() + "." + tail
        try:
            result = fn(self, context)
        except Exception as exc:                              # noqa: BLE001
            from ..tools import htlog
            label = getattr(cls, "bl_label", idname)
            msg = htlog.failure("%s failed" % label, pcf=_file_of(self, context), exc=exc,
                                stage="running %s" % idname,
                                hint="press PRINT HELP on the Dev tab and send the .txt it writes")
            self.report({"ERROR"}, msg)
            htlog.popup_failure(context, "%s failed" % label, [msg])
            op_panel.RUNS[idname] = "warn"
            return {"CANCELLED"}
        if isinstance(result, (set, frozenset)):
            if "FINISHED" in result:
                op_panel.RUNS[idname] = "ok"
            elif "CANCELLED" in result:
                op_panel.RUNS[idname] = "warn"
        return result

    execute._htp_guarded = True
    cls.execute = execute


def register():
    for mod in _MODULES:
        for cls in getattr(mod, "CLASSES", ()):
            if issubclass(cls, bpy.types.Operator):
                _guard(cls)
            bpy.utils.register_class(cls)
        if hasattr(mod, "register"):
            mod.register()
    bpy.types.TOPBAR_MT_file_import.append(op_particle_import.menu_func)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(op_particle_import.menu_func)
    for mod in reversed(_MODULES):
        if hasattr(mod, "unregister"):
            mod.unregister()
        for cls in reversed(getattr(mod, "CLASSES", ())):
            bpy.utils.unregister_class(cls)
