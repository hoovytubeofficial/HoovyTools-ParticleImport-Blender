"""Blender operators + panels. One op_<thing>.py per feature.

Each module exposes a CLASSES tuple; registration order matters only in that
op_particle_import's PropertyGroup must exist before Scene.htp points at it,
which its own register() handles.
"""

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
from . import op_panel

_MODULES = (op_prefs, op_particle_import, op_vtf, op_vtf_sprite, op_vmt,
            op_ras, op_rope, op_trail, op_grid, op_node_to_code, op_support,
            op_panel)


def register():
    for mod in _MODULES:
        for cls in getattr(mod, "CLASSES", ()):
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
