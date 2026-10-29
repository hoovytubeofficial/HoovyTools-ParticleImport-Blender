# =============================================================================
#  tools/diagnose.py  -  why is the viewport slow? Ask the scene, not a forum.
# =============================================================================
#
#  Viewport lag around particle systems has exactly three usual suspects, and
#  they need different fixes - so guessing wastes an evening:
#
#    1. A VIEW-DEPENDENT NODE (Viewport Transform / Is Viewport) anywhere in
#       a system's tree re-evaluates the WHOLE system on every orbit and
#       mouse move. Builds made before v0.19 carried one in the shared eye
#       group; one rebuild/re-import in the file cleans it for every system.
#    2. OVERDRAW: thousands of BLENDED (sorted-transparency) cards stacked on
#       screen cost GPU fill-rate on every redraw. That is what Proxy View
#       is for.
#    3. Neither - then it is not the systems: selection outlines over huge
#       instance counts, or another overlay, drawn per redraw.
#
#  scan() reads the evaluated scene and reports which suspect is present,
#  per system. bpy-heavy by nature; kept out of the operators per RULES.
# =============================================================================

import bpy

#  Node types whose PRESENCE makes a tree re-evaluate per view change.
VIEW_DEP = ("GeometryNodeViewportTransform", "GeometryNodeIsViewport")


def _walk_groups(ng, seen):
    """Yield every node group reachable from ng, once."""
    if ng is None or ng.name in seen:
        return
    seen.add(ng.name)
    yield ng
    for n in ng.nodes:
        sub = getattr(n, "node_tree", None)
        if sub is not None:
            yield from _walk_groups(sub, seen)


def scan_object(o, depsgraph):
    """One system host -> the three suspects, measured."""
    info = {"name": o.name, "view_dep": [], "instances": 0,
            "blended": set(), "proxy": None}
    mats = set()
    for m in o.modifiers:
        if m.type != "NODES" or m.node_group is None:
            continue
        for g in _walk_groups(m.node_group, set()):
            for n in g.nodes:
                if n.bl_idname in VIEW_DEP:
                    info["view_dep"].append((g.name, n.bl_idname))
                if n.bl_idname == "GeometryNodeSetMaterial":
                    try:
                        mat = n.inputs[2].default_value
                        if mat is not None:
                            mats.add(mat)
                    except Exception:
                        pass
        #  the system's own Proxy View switch, if it has one
        for it in m.node_group.interface.items_tree:
            if getattr(it, "item_type", "") == "SOCKET" \
                    and it.name == "Proxy View":
                try:
                    info["proxy"] = bool(getattr(
                        m.properties.inputs, it.identifier).value)
                except Exception:
                    pass
                break
    #  BLENDED = sorted transparency, the expensive kind. The proxy's
    #  emission material is DITHERED/opaque and free.
    for mat in mats:
        if getattr(mat, "surface_render_method", "") == "BLENDED":
            info["blended"].add(mat.name)
    try:
        ev = o.evaluated_get(depsgraph)
        #  🔴 KEEP THE GeometrySet ALIVE while reading from it. Chaining
        #  `evaluated_geometry().instances_pointcloud()` frees the set the
        #  moment the expression ends, and the PointCloud answers every
        #  later access with "StructRNA has been removed".
        geo = ev.evaluated_geometry()
        pc = geo.instances_pointcloud()
        info["instances"] = len(pc.points) if pc is not None else 0
    except Exception as exc:
        #  a count is nice-to-have; a diagnosis that dies on it is not -
        #  but say WHY, a silent zero misdiagnosed a working scene once
        print(f"[HT_PARTICLE]  diagnose: no instance count for "
              f"{o.name!r}: {exc}")
    return info


def scan(context, is_system_host):
    """Every built system in the scene -> (per-system infos, verdict lines).

    is_system_host: predicate(object) -> bool, supplied by the operator so
    this module does not import UI code."""
    dg = context.evaluated_depsgraph_get()
    infos = [scan_object(o, dg) for o in context.scene.objects
             if is_system_host(o)]
    verdict = []
    stale = [i for i in infos if i["view_dep"]]
    if stale:
        groups = sorted({g for i in stale for g, _ in i["view_dep"]})
        verdict.append("VIEW-DEPENDENT nodes found - these systems re-run")
        verdict.append("on EVERY orbit. Rebuild/re-import in this file")
        verdict.append("(one build refreshes the shared groups):")
        for g in groups:
            verdict.append(f"    {g}")
    total = sum(i["instances"] for i in infos)
    heavy = [i for i in infos
             if i["instances"] > 0 and i["blended"] and not i["proxy"]]
    if heavy and not stale:
        verdict.append(f"{total} live particles wearing sorted-transparency")
        verdict.append("materials - every redraw pays that fill rate.")
        verdict.append("Proxy View (this box) is the tool for that.")
    if not stale and not heavy:
        verdict.append("Systems are clean: nothing view-dependent, and")
        verdict.append("nothing heavy unproxied. Spikes while orbiting are")
        verdict.append("then OVERLAYS, not evaluation - try deselecting the")
        verdict.append("system (outline overlay draws every instance) or")
        verdict.append("toggling viewport overlays off.")
    return infos, verdict
