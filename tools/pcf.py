# =============================================================================
# _core/pcf.py  -  read a .pcf and figure out its particle-system hierarchy
# =============================================================================
#
# WHAT A .pcf IS (plain words)
#  ----------------------------
# A .pcf is a DMX file. Its root has an attribute "particleSystemDefinitions",
# which is a big list of particle systems (DmeParticleSystemDefinition). Each
# system can spawn CHILD systems - that's the parent/child tree You see in
# SFM's particle picker. The child links live on each system's "children"
# attribute: a list of little DmeParticleChild links, each pointing at another
# system (the "child") with an optional "delay"
#
# So to build the picker we:
# 1. grab every system definition,
# 2. read each one's "children" links,
# 3. whoever is never someone else's child = a ROOT (a top-level effect)
#
# This module has no Blender imports on purpose - it is pure data, so it can be
# unit-tested outside Blender and reused anywhere
#
# NOTE: exact attribute names ("children", "child", "delay") follow the Source
# DmeParticleSystemDefinition spec. Validate against a real .pcf; if a pack
# uses odd names we widen the lookup in _child_links()
# =============================================================================

from . import datamodel


#── loading ──────────────────────────────────────────────────────────────────

def load_pcf(path):
    """Load a .pcf and return the datamodel. Raises on unreadable files."""
    return datamodel.load(str(path))


def get_system_defs(dm):
    """Return the list of particle-system definition Elements in this file.

    We look on the root for 'particleSystemDefinitions' (the normal case) and
    fall back to scanning every element for a Particle-typed one, so a weird or
    hand-edited file still gives us something."""
    root = dm.root
    defs = root.get("particleSystemDefinitions")
    if defs:
        return [e for e in defs if _is_particle_def(e)]
    # Fallback: scan all elements.
    return [e for e in getattr(dm, "elements", []) if _is_particle_def(e)]


def _is_particle_def(elem):
    """True if this element is a particle-system DEFINITION (not an operator /
    renderer / child-link sub-element)."""
    try:
        t = getattr(elem, "type", "") or ""
    except Exception:
        return False
    # DmeParticleSystemDefinition / CParticleSystemDefinition, etc.
    return "ParticleSystemDefinition" in t


# ── hierarchy ────────────────────────────────────────────────────────────────

def _child_links(system):
    """Return the list of child SYSTEM elements this system spawns.

    Each entry in 'children' is usually a DmeParticleChild whose 'child'
    attribute references the real system. Some files store the system element
    directly. We handle both, and skip anything that is not a definition."""
    out = []
    children = system.get("children")
    if not children:
        return out
    for link in children:
        target = None
        if _is_particle_def(link):
            target = link                     # child stored directly
        else:
            # DmeParticleChild wrapper -> the real system is under "child"
            for key in ("child", "m_pChild", "target"):
                cand = link.get(key) if hasattr(link, "get") else None
                if cand is not None and _is_particle_def(cand):
                    target = cand
                    break
        if target is not None:
            out.append(target)
    return out


def _child_delay(link):
    """Best-effort read of a child link's spawn delay (seconds)."""
    for key in ("delay", "m_flDelay"):
        try:
            v = link.get(key)
            if isinstance(v, float):
                return v
        except Exception:
            pass
    return 0.0


def build_hierarchy(dm):
    """
    Return a dict describing the file's particle systems and their tree:

        {
          "systems"  : { name: element, ... },       # every system by name
          "children" : { name: [child_name, ...] },  # parent -> children
          "roots"    : [name, ...],                   # top-level effects
          "order"    : [name, ...],                   # file order (stable list)
        }

    'roots' is what You show first in the picker; the rest are children reached
    by expanding a root. Duplicate names are disambiguated by appending #2, #3.
    """
    defs = get_system_defs(dm)

    # Build a stable name for each element (handle duplicates)
    name_of = {}
    seen = {}
    order = []
    for e in defs:
        base = e.name or "(unnamed)"
        seen[base] = seen.get(base, 0) + 1
        name = base if seen[base] == 1 else f"{base}#{seen[base]}"
        name_of[id(e)] = name
        order.append(name)

    systems = {name_of[id(e)]: e for e in defs}
    child_map = {}
    is_child = set()

    for e in defs:
        pname = name_of[id(e)]
        kids = []
        for target in _child_links(e):
            cname = name_of.get(id(target))
            if cname is None:
                # child not in the definitions list (external ref) - skip
                continue
            kids.append(cname)
            is_child.add(cname)
        child_map[pname] = kids

    roots = [name for name in order if name not in is_child]
    return {"systems": systems, "children": child_map,
            "roots": roots, "order": order}


def flatten_for_picker(hierarchy):
    """
    Return an ordered list of (name, depth) walking roots then their children,
    for a simple indented dropdown. Cycles are guarded against.
    """
    out = []
    visited = set()

    def walk(name, depth):
        if name in visited:
            return
        visited.add(name)
        out.append((name, depth))
        for child in hierarchy["children"].get(name, []):
            walk(child, depth + 1)

    for root in hierarchy["roots"]:
        walk(root, 0)
    # any orphans not reached (shouldn't happen, but be safe)
    for name in hierarchy["order"]:
        if name not in visited:
            out.append((name, 0))
            visited.add(name)
    return out


# ── renderer inspection (used later by the geo-node builders) ────────────────

def get_renderers(system):
    """Return [(functionName, element), ...] for this system's renderer
    operators - render_animated_sprites / render_rope / render_sprite_trail /
    render_models. Part 3 wires these to geo-node groups."""
    out = []
    for key in ("renderers", "operators"):
        arr = system.get(key)
        if not arr:
            continue
        for op in arr:
            fn = str(op.get("functionName", "")).strip().lower() if hasattr(op, "get") else ""
            if fn.startswith("render"):
                out.append((fn, op))
    return out


# ── control points ───────────────────────────────────────────────────────────
#
# how many empties does this effect need?
# A Source particle system is driven by CONTROL POINTS - numbered transforms
# the operators read ("Position Within Sphere Random" spawns around CP 0,
# "Movement Lock to Control Point" follows CP 3, and so on). To rebuild an
# effect we must create one empty per control point it actually references
#
# There is no header listing them: you find them by walking every operator /
# initializer / emitter / renderer / force / constraint and reading the
# integer attributes that name a control point
#
# NAMING IS A MESS - verified against 60 real .pcf files:
# control_point_number                     (by far the most common)
# Control Point Number / control point number
# start control point number / end control point number
# First..Fourth Control Point Number
# orientation control point / tint control point
# Visibility Proxy Input Control Point Number
# cull_control_point                       (system level)
#
# TRAPS:
# * -1 means "not used". It appears more than a thousand times across those
# files; counting it would invent a control point that isn't there
# * Several attributes contain "control point" but are not indices -
# "...Parent", "...Location", "control point movement distance tolerance",
# "scale emission to used control points" (a flag), "...field". Those are
# excluded by name
# =============================================================================

_CP_SUBELEMENT_KEYS = ("operators", "initializers", "emitters", "renderers",
                       "forces", "constraints")

# if a normalised attribute name contains any of these it's NOT a CP index.
_CP_NAME_EXCLUDE = ("parent", "location", "tolerance", "distribute",
                    "scale emission", "field", "offset for")


def _norm(name):
    return str(name).lower().replace("_", " ")


def _is_cp_count_attr(name):
    """'# of control points to set' is a SPAN LENGTH, not an index."""
    return "of control points" in _norm(name)


def _is_cp_attr(name):
    n = _norm(name)
    if "control point" not in n:
        return False
    if _is_cp_count_attr(name):
        return False
    return not any(bad in n for bad in _CP_NAME_EXCLUDE)


def _cp_values_in(element):
    """Yield (attr_name, control_point_index) for one element.

    Handles the span case: 'Set child control points from particle positions'
    carries 'First control point to set' + '# of control points to set', which
    together occupy first .. first+count-1. Reading the count as an index gave
    a bogus CP 35 for an effect that really uses 0..35 via a span."""
    try:
        keys = list(element.keys())
    except Exception:
        return

    def as_index(attr):
        try:
            val = element.get(attr)
        except Exception:
            return None
        # bool is an int subclass - a flag is not a control point
        if isinstance(val, bool) or not isinstance(val, int) or val < 0:
            return None
        return val

    span_count = None
    span_count_attr = None
    for attr in keys:
        if _is_cp_count_attr(attr):
            span_count = as_index(attr)
            span_count_attr = attr
            break

    first_for_span = None
    for attr in keys:
        if not _is_cp_attr(attr):
            continue
        val = as_index(attr)
        if val is None:
            continue
        if span_count and "first" in _norm(attr):
            first_for_span = val
        yield attr, val

    if span_count and span_count > 1:
        base = first_for_span or 0
        #the span occupies base .. base + count - 1
        yield f"{span_count_attr} (span of {span_count})", base + span_count - 1


def get_control_points(system, include_children=False, hierarchy=None):
    """Which control points does this system reference?

    Returns {'indices': sorted list, 'count': highest index + 1,
             'sources': {index: [attribute names that asked for it]}}

    'count' is what you need to create: CPs are dense from 0, so referencing
    only CP 3 still means the effect expects 0..3 to exist."""
    sources = {}

    def scan(sysdef):
        for attr, val in _cp_values_in(sysdef):        # system-level attrs
            sources.setdefault(val, set()).add(attr)
        for key in _CP_SUBELEMENT_KEYS:
            for op in (sysdef.get(key) or []):
                fn = ""
                try:
                    fn = str(op.get("functionName") or "")
                except Exception:
                    pass
                for attr, val in _cp_values_in(op):
                    label = f"{fn}.{attr}" if fn else attr
                    sources.setdefault(val, set()).add(label)

    scan(system)
    if include_children and hierarchy:
        name_of = {id(e): n for n, e in hierarchy["systems"].items()}
        seen = set()
        stack = [name_of.get(id(system))]
        while stack:
            cur = stack.pop()
            if cur is None or cur in seen:
                continue
            seen.add(cur)
            child_names = hierarchy["children"].get(cur, [])
            for cn in child_names:
                child = hierarchy["systems"].get(cn)
                if child is not None:
                    scan(child)
                stack.append(cn)

    indices = sorted(sources)
    return {
        "indices": indices,
        "count": (max(indices) + 1) if indices else 0,
        "sources": {k: sorted(v) for k, v in sources.items()},
    }


def get_material_ref(system):
    """Return the first material path referenced by any renderer in this system,
    or None. This is the bridge to the VMT -> VTF importer (part 4)."""
    for _fn, op in get_renderers(system):
        for key in ("material", "sequence"):
            v = op.get(key) if hasattr(op, "get") else None
            if isinstance(v, str) and v.lower().endswith((".vmt", ".vtf")):
                return v
    return None
