# =============================================================================
#  HoovyTools Particle Import  -  bring SFM/Source .pcf particle systems into
#  Blender as geometry-nodes effects.
# =============================================================================
#
#  LAYOUT  (same shape as HoovyToolsSFMExportHelper - thin operators, fat tools)
#    __init__.py     bl_info + registration, nothing else
#    paths.py        find the SFM install so browsers open in the right place
#    operators/      op_<thing>.py - Blender operators and panels (thin)
#    tools/          the actual logic, bpy-free where possible (fat)
#
#  This folder is RUNTIME ONLY - it is exactly what ships. All dev material
#  lives in the SIBLING folder "HoovyToolsParticleImportDeveloper":
#    constitution/   the law: RULES.md (codebase), OPERATORS.md (translation)
#                    and work reports/ - READ RULES.md FIRST
#    __ForYou/       latest fixed copies of HoovyTube's own tools
#    __Developer/    HoovyTube's private corner - addon code NEVER imports it
#    versions/       a full installable zip of every release, for rollback
#
#  ROADMAP (see ../HoovyToolsParticleImportDeveloper/constitution/work reports/PROGRESS.md)
#    1. PCF -> read                 done  (vendored MIT datamodel reader)
#    2. Import UI, SFM-style        done  (dialog + inline sidebar, one state)
#    3. Geo-node renderers          next  (animated_sprites first)
#    4. VTF importer                done  (DXT1/3/5 decode + sheet table)
# =============================================================================

bl_info = {
    "name":        "HoovyTools Particle Import",
    "description": "Import SFM/Source .pcf particle systems into Blender",
    "author":      "Kajetan (HoovyTube)",
    "version":     (2, 0, 0),
    "blender":     (4, 2, 0),
    "location":    "File > Import > Source Engine (.pcf) + "
                   "3D View sidebar (N) > Particle Import",
    "category":    "Import-Export",
}

from . import icons
from . import operators


def register():
    icons.load()
    operators.register()


def unregister():
    operators.unregister()
    icons.unload()


if __name__ == "__main__":
    register()
