# =============================================================================
# operators/op_node_to_code.py  -  NODE TO CODE, four one-click flavours
# =============================================================================
#
# Wraps tools/gn_to_python.py. FOUR buttons, each doing exactly one thing -
# no options, no flags to misread:
#
# Geometry Nodes  (textures in the script)   htp.ntc_geo_tex
# Geometry Nodes  (no textures)              htp.ntc_geo_notex
# Shader Nodes    (textures IN the script)   htp.ntc_mat_tex
# Shader Nodes    (no textures)              htp.ntc_mat_notex
#
# Geometry = select the effect's object (or open its group in a Geometry
# Nodes editor). Shader = select an object wearing the material. The rebuild
# script lands on the clipboard AND in a Text block; for 600+ node monsters
# the clipboard can truncate - run the Text block instead.
#
# The module is reloaded on every run so edits take effect w/o a restart
# =============================================================================

import importlib

import bpy
from bpy.types import Operator


def _tools():
    from ..tools import gn_to_python
    importlib.reload(gn_to_python)
    return gn_to_python


class _NTCBase(Operator):
    bl_options = {"REGISTER"}
    SCOPE = "GEO"          #or "MATERIAL"
    EMBED = True

    def execute(self, context):
        g = _tools()
        if self.SCOPE == "GEO":
            # refuse loudly instead of claiming a copy that never happened
            try:
                tree = g._active_tree()
            except Exception as exc:
                self.report({"ERROR"}, f"Node to Code failed to look for a "
                                       f"group: {exc}")
                return {"CANCELLED"}
            if tree is None:
                self.report(
                    {"ERROR"},
                    "No geometry nodes found. Select the object carrying the "
                    "effect's Geometry Nodes modifier, or open its group in "
                    "a Geometry Nodes editor.")
                return {"CANCELLED"}
        try:
            if self.SCOPE == "GEO":
                result = g.main_geo(embed_images=self.EMBED)
            else:
                result = g.main_material(embed_images=self.EMBED)
        except Exception as exc:
            self.report({"ERROR"}, f"Node to Code failed: {exc}")
            print(f"[HT_PARTICLE]  Node to Code ERROR: {exc}")
            return {"CANCELLED"}
        if not result:
            self.report({"ERROR"},
                        "Node to Code produced nothing - see the console.")
            return {"CANCELLED"}
        self.report({"INFO"},
                    f"Node to Code -> clipboard + Text block '{result}'"
                    + ("" if self.EMBED else "  (textures NOT embedded)"))
        return {"FINISHED"}


class HTP_OT_NtcGeoTex(_NTCBase):
    """Geometry Nodes -> script, WITH textures

SELECT THE EFFECT'S OBJECT FIRST. You get a runnable script on the
clipboard and in a Text block: run it in an empty scene and the whole
effect comes back - objects, meshes, materials, node groups, every input.

Sprite sheets are EMBEDDED in the script, so whoever you hand it to does
not need your SFM install or your .vtf files. Big sheets = big script."""
    bl_idname = "htp.ntc_geo_tex"
    bl_label = "Geometry Nodes (with textures)"


class HTP_OT_NtcGeoNoTex(_NTCBase):
    """Geometry Nodes -> script, NO textures

SELECT THE EFFECT'S OBJECT FIRST. Same full rebuild script as the
textured flavour, but image pixels are NOT embedded - the script stays
small and references textures by name. Whoever runs it needs the images
already in their .blend (or does not care about the pictures)."""
    bl_idname = "htp.ntc_geo_notex"
    bl_label = "Geometry Nodes (no textures)"
    EMBED = False


class HTP_OT_NtcMatTex(_NTCBase):
    """Shader Nodes -> script, WITH textures

SELECT AN OBJECT WEARING THE MATERIAL first (its active material slot is
exported). You get a script that rebuilds JUST that material - its shader
groups and its textures, embedded - nothing else. Perfect for handing one
sprite material to somebody."""
    bl_idname = "htp.ntc_mat_tex"
    bl_label = "Shader Nodes (with textures)"
    SCOPE = "MATERIAL"


class HTP_OT_NtcMatNoTex(_NTCBase):
    """Shader Nodes -> script, NO textures

SELECT AN OBJECT WEARING THE MATERIAL first (its active material slot is
exported). Rebuilds just that material's node graph; image pixels are NOT
embedded, so the script is tiny and references textures by name."""
    bl_idname = "htp.ntc_mat_notex"
    bl_label = "Shader Nodes (no textures)"
    SCOPE = "MATERIAL"
    EMBED = False


class HTP_OT_NodeToCode(_NTCBase):
    """Legacy alias: Geometry Nodes with textures (the original button)"""
    bl_idname = "htp.node_to_code"
    bl_label = "Node to Code"


CLASSES = (HTP_OT_NtcGeoTex, HTP_OT_NtcGeoNoTex,
           HTP_OT_NtcMatTex, HTP_OT_NtcMatNoTex, HTP_OT_NodeToCode)
