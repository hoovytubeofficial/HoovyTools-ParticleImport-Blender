# =============================================================================
#  api.py  -  the STABLE surface for other add-ons (HoovyTools, scripts)
# =============================================================================
#
#  HoovyTools imports SFM sessions; sessions reference particle effects; this
#  module is how it (or any script) builds one without touching the sidebar
#  UI or scene.htp state. Nothing here reads or writes the import panel.
#
#      from HoovyToolsParticleImport import api
#
#      names = api.list_systems(r"...\explosion.pcf")
#      made  = api.build_effect(bpy.context, r"...\explosion.pcf",
#                               system=names["roots"][0],
#                               start_time=2.5,      # scene seconds
#                               time_scale=1.0)      # 0.5 = half speed
#
#  `build_effect` returns the list of created objects (hosts, the control
#  root, anchors). The effect lands in __HoovyTools__/<system name>/ unless a
#  collection is handed in.
#
#  ⚠️ THE CONTRACT: this module's signatures and the SYSTEM PROPERTIES socket
#  names ("Time Offset", "Time Scale", "Scale", "Seed", "Max Particles") are
#  the stable integration surface. Everything else in this add-on may be
#  refactored without notice - reach through api.py, not around it.
# =============================================================================

from pathlib import Path

from .tools import pcf


def list_systems(pcf_path):
    """What is in this .pcf, without building anything.

    -> {"roots": [name, ...], "order": [name, ...],
        "children": {parent: [child, ...]}}"""
    dm = pcf.load_pcf(Path(pcf_path))
    h = pcf.build_hierarchy(dm)
    return {"roots": list(h["roots"]), "order": list(h["order"]),
            "children": {k: list(v) for k, v in h["children"].items()}}


def build_effect(context, pcf_path, system=None, collection=None,
                 include_children=True, start_time=0.0, time_scale=1.0):
    """Build one effect from a .pcf. Returns the list of created objects.

    system            which definition to build; None takes the first root
    collection        an existing bpy Collection, or None for the standard
                      __HoovyTools__/<system>/ home
    include_children  False builds just the named system, no child tree
    start_time        scene SECONDS the effect begins at (Time Offset)
    time_scale        1 = authored speed, 0.5 = half speed, 0 = frozen

    Raises ValueError for an unreadable file or an unknown system name -
    the caller is another add-on, and a silent empty return would just move
    the mystery one codebase over."""
    from .operators.op_particle_import import (build_system_tree,
                                               particle_collection,
                                               set_system_socket, TAG)

    dm = pcf.load_pcf(Path(pcf_path))
    hierarchy = pcf.build_hierarchy(dm)
    if system is None:
        roots = hierarchy["roots"]
        if not roots:
            raise ValueError(f"no particle systems in {pcf_path}")
        system = roots[0]
    if system not in hierarchy["systems"]:
        raise ValueError(f"{system!r} is not in {Path(pcf_path).name} - "
                         f"list_systems() names what is")

    if not include_children:
        hierarchy = dict(hierarchy)
        hierarchy["children"] = dict(hierarchy["children"])
        hierarchy["children"][system] = []

    coll = collection if collection is not None \
        else particle_collection(context, system)
    made, log = build_system_tree(context, system, hierarchy, collection=coll)
    for line in log:
        print(f"{TAG}{line}")

    for o in made:
        if start_time:
            set_system_socket(o, "Time Offset", float(start_time))
        if abs(float(time_scale) - 1.0) > 1e-9:
            set_system_socket(o, "Time Scale", float(time_scale))
    return made
