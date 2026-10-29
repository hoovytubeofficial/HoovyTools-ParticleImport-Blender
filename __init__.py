# =============================================================================
#  Source Particle Import  -  bring SFM / Source .pcf particle systems into
#  Blender as geometry-nodes effects.
# =============================================================================
#
#  LAYOUT  (thin operators, fat tools)
#    __init__.py     bl_info + registration, nothing else
#    paths.py        find the SFM install so browsers open in the right place
#    api.py          build an effect from another add-on (SFM Session Importer)
#    operators/      op_<thing>.py - Blender operators and the panel (thin)
#    tools/          the actual logic, bpy-free where possible (fat)
#    images/         the panel's icons, and the preview card's orb
#    materials/      the fallback sprite materials (spark, glow, beam)
#    # tools/        the Text Editor versions of the tools
#
#  The panel lives in the 3D View sidebar (N) > HoovyTools > Source Particle
#  Import: Import, Properties, Tools and Dev (Wiring, PRINT HELP). Every line
#  this add-on prints starts with [Source Particle Import] (tools/htlog.py).
# =============================================================================

bl_info = {
    "name":        "Source Particle Import",
    "description": "Import SFM / Source .pcf particle systems into Blender as editable geometry nodes",
    "author":      "Kajetan (HoovyTube)",
    "version":     (3, 0, 0),
    "blender":     (4, 2, 0),
    "location":    "File > Import > Source Engine (.pcf) + 3D View sidebar (N) > HoovyTools",
    "category":    "Import-Export",
}

from . import icons
from . import operators
from .tools import htlog


def register():
    #  FIRST: every line printed from here on is marked and kept (3.0.0).
    htlog.start()
    icons.load()
    operators.register()


def unregister():
    operators.unregister()
    icons.unload()
    htlog.stop()


if __name__ == "__main__":
    register()
