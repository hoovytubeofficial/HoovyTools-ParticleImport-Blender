# =============================================================================
# tools/pcf_build.py  -  a parsed .pcf system  ->  a built one
# =============================================================================
#
# Everything else in this add-on was preparation for this file. It contains
# no maths and no node building: it decides which renderer, HOW MANY of each
# operator, what each socket should be set to, and then calls the builders.
#
# why it is a lookup and not a pile of if-statements
#  --------------------------------------------------
# Every socket the system builds is named
#
# "Readable name [SFM: exact_pcf_attribute]"
#
# and `ras_spec` knows that mapping for every operator. So importing an
# attribute is: find the socket whose SFM tag is this attribute name, convert
# the units, set it. That is the entire translation, and it is why the socket
# naming convention was worth the trouble
#
# WHAT IT REFUSES TO DO
#  ---------------------
# 🔴 It never guesses. An attribute with no socket is COLLECTED AND REPORTED,
# not quietly dropped - because "the effect came through" when a third of its
# authoring did not is the single most expensive lie an importer can tell
# Everything skipped comes back in `report["ignored"]`.
#
# PARENT AND CHILD
#  ----------------
# A child is its own object with its own modifier, and it reads its parent's
# particles thru Object Info. Dependencies therefore run parent -> child
# and never back: a parent reading a child is a depsgraph cycle, which
# Blender answers with empty geometry and no error at all
#
# Children are built depth-first AFTER their parent exists, so the parent
# object is there to be pointed at
# =============================================================================

from . import ras_spec as spec
from . import pcf, vmt


# ── which renderer ───────────────────────────────────────────────────────────
# A system's renderer is whatever is in its `renderers` list. Three of
# Source's four are built; `render_models` is not, and a system that wants it
# is reported rather than silently drawn as sprites

RENDERER_BY_FN = {
    "render_animated_sprites": "ANIMATED_SPRITES",
    "render_sprite_trail": "SPRITE_TRAIL",
    "render_rope": "ROPE",
}

# sprites are the overwhelming default - 2569 of 3574 systems - so a system
# whose renderer we don't recognise is still worth building as sprites, WITH
# a warning, rather than not built at all
FALLBACK_RENDERER = "ANIMATED_SPRITES"


def choose_renderer(sysdef):
    """-> (renderer key, functionName, [notes])."""
    notes = []
    found = []
    for fn, _op in pcf.get_renderers(sysdef):
        for known, key in RENDERER_BY_FN.items():
            if fn == known.lower():
                found.append((key, known))
    if not found:
        notes.append("no renderer this build knows - drawn as animated "
                     "sprites")
        return FALLBACK_RENDERER, None, notes
    if len(found) > 1:
        notes.append("more than one renderer; using the first: "
                     + ", ".join(f for _k, f in found))
    return found[0][0], found[0][1], notes


# ── how many of each operator ────────────────────────────────────────────────

def operator_counts(sysdef):
    """{functionName: how many times it appears}, over every operator list.

    THE COUNT IS READ, NOT CHOSEN. An operator appearing twice is legal and
    normal, and this is what makes the stacking machinery usable without
    anybody deciding anything: the file says two, the modifier gets two."""
    counts = {}
    for key in pcf._CP_SUBELEMENT_KEYS:
        for op in (sysdef.get(key) or []):
            try:
                fn = str(op.get("functionName") or "").strip()
            except Exception:
                continue
            if fn and _enabled(op):
                counts[fn] = counts.get(fn, 0) + 1
    return counts


def _enabled(op):
    """0.24.1: `operator enabled 0` SWITCHES AN OPERATOR OFF in SFM. It was
    listed as an attribute with no socket and the operator ran anyway - the
    concrete impacts' disabled Rotation Yaw Flip Random mirrored their dust."""
    try:
        v = op.get("operator enabled")
    except Exception:
        return True
    return v is None or bool(v)


def operator_elements(sysdef):
    """{functionName: [element, ...]} in file order, so instance N of an
    operator maps to panel N."""
    out = {}
    for key in pcf._CP_SUBELEMENT_KEYS:
        for op in (sysdef.get(key) or []):
            try:
                fn = str(op.get("functionName") or "").strip()
            except Exception:
                continue
            if fn and _enabled(op):
                out.setdefault(fn, []).append(op)
    return out


# ── units ────────────────────────────────────────────────────────────────────
#
# The socket carries the unit tag from the catalogue, so conversion is a
# lookup too. Only two things actually change on the way in

def convert(value, unit, socket_type):
    """A .pcf value -> what the socket wants. Returns (value, note or None)."""
    # COLOUR IS 0..255 IN the FILE and 0..1 IN A BLENDER SWATCH. This is the
    # one conversion that silently produces a *plausible* wrong answer if
    # missed - everything just renders white, because 255 clamps to 1
    if socket_type == "NodeSocketColor":
        try:
            parts = [float(c) for c in value]
        except (TypeError, ValueError):
            return None, "colour was not a list of numbers"
        while len(parts) < 4:
            parts.append(255.0)
        return tuple(min(1.0, p / 255.0) for p in parts[:4]), None

    if socket_type == "NodeSocketVector":
        try:
            parts = [float(c) for c in value]
        except (TypeError, ValueError):
            return None, "vector was not a list of numbers"
        while len(parts) < 3:
            parts.append(0.0)
        return tuple(parts[:3]), None

    if socket_type == "NodeSocketBool":
        if isinstance(value, bool):
            return value, None
        try:
            return bool(float(value)), None
        except (TypeError, ValueError):
            return None, "not a number, cannot be a flag"

    if socket_type == "NodeSocketInt":
        try:
            return int(round(float(value))), None
        except (TypeError, ValueError):
            return None, "not a number"

    if socket_type == "NodeSocketFloat":
        try:
            return float(value), None
        except (TypeError, ValueError):
            return None, "not a number"

    return None, f"no rule for socket type {socket_type}"


# ── the whole translation ────────────────────────────────────────────────────

def plan(sysdef, hierarchy=None):
    """Work out everything needed to build this system. Touches no bpy.

    -> dict(renderer, cp_count, cp_indices, stack, values, enabled,
            ignored, notes, material)
    """
    renderer, rend_fn, notes = choose_renderer(sysdef)
    counts = operator_counts(sysdef)
    elements = operator_elements(sysdef)

    cp = pcf.get_control_points(sysdef)
    stack = {}
    values = {}
    enabled = []
    ignored = []
    cp_placements = {}
    cp_frame = (0, False)       # (head CP the offsets are measured from, world space?)

    for fn, n in counts.items():
        # ── Set Control Point Positions ──────────────────────────────────
        # Not a socket operator: in SFM it re-asserts CP1..CP4's positions
        # every frame, relative to CP0 (or wherever "offset positions from"
        # points). In Blender the control points are REAL EMPTIES the user
        # owns, so fighting them per frame would be hostile. The honest
        # translation: apply the authored locations once, as the initial
        # placement of the spawned empties - CP0 stays the ground truth and
        # every placed CP sits at its authored offset from it, exactly the
        # geometry the effect was built around. Move or animate them after
        # that and the effect follows, which is strictly more useful
        if fn == "Set Control Point Positions":
            for elem in elements.get(fn, []):
                for word, default_idx in (("First", 1), ("Second", 2),
                                          ("Third", 3), ("Fourth", 4)):
                    try:
                        loc = elem.get(f"{word} Control Point Location")
                        num = elem.get(f"{word} Control Point Number")
                    except Exception:
                        continue
                    if loc is None:
                        continue
                    # The authored NUMBER overrides the default slot - a
                    # real hologram writes "Fourth Control Point Number 2"
                    # and its Fourth location lands on CP2
                    try:
                        idx = int(num) if num is not None else default_idx
                        cp_placements[idx] = tuple(
                            float(c) for c in loc)[:3]
                    except (TypeError, ValueError):
                        ignored.append((fn, f"{word} Control Point Location",
                                        "could not read the vector"))
            # 0.26.3: which FRAME the offsets are in. Source transforms
            # them by the head control point's whole matrix, so they turn and
            # move with it - unless "Set positions in world space"
            for elem in elements.get(fn, []):
                try:
                    head = elem.get("Control Point to offset positions from")
                    world = elem.get("Set positions in world space")
                    cp_frame = (int(head) if head is not None else 0,
                                bool(world))
                except (TypeError, ValueError):
                    ignored.append((fn, "Control Point to offset positions "
                                        "from", "could not read it"))
                except Exception:
                    continue
            notes.append("Set Control Point Positions: applied as the "
                         "INITIAL placement of the control point empties, "
                         "as offsets in the head control point's frame (CP0 "
                         "unless the file names another) - they turn and "
                         "move with it. Not re-asserted per frame - the "
                         "empties stay yours to animate.")
            for extra in ("Only set position once",
                          "First Control Point Parent",
                          "Second Control Point Parent",
                          "Third Control Point Parent",
                          "Fourth Control Point Parent",
                          "Inherit CP Orientation"):
                for elem in elements.get(fn, []):
                    try:
                        if elem.get(extra) is not None:
                            ignored.append((fn, extra, "not modelled"))
                            break
                    except Exception:
                        pass
            continue
        if fn in spec.ALREADY_HANDLED:
            # not a gap. Reporting it would train you to ignore the warnings
            # that do matter
            notes.append(f"{fn}: {spec.ALREADY_HANDLED[fn]}")
            continue
        if fn not in spec.OPERATORS:
            # not BUILT. Say which, and how many times it was asked for, so
            # the gap is visible in the report rather than in the render
            ignored.append((fn, "*whole operator*", f"x{n}, not built"))
            continue
        stack[fn] = n
        for inst, elem in enumerate(elements.get(fn, []), start=1):
            #PRESENT in the FILE MEANS ON. Some operators default to off in
            #the builder precisely so a hand-made system is not altered
            #behind your back - so the importer has to say so explicitly,
            #rather than relying on whatever the default happens to be.
            panel = spec.panel_name(fn, inst)
            enabled.append(panel)
            values[panel] = True
            by_sfm = {f[1]: f for f in spec.fields_for(fn)}
            for attr in list(elem.keys()):
                if attr == "functionName":
                    continue
                field = by_sfm.get(attr)
                if field is None:
                    ignored.append((fn, attr, "no socket for it"))
                    continue
                disp, sfm, stype, _d, _lo, _hi, unit = field
                try:
                    raw = elem.get(attr)
                except Exception:
                    continue
                val, why = convert(raw, unit, stype)
                if val is None:
                    ignored.append((fn, attr, why or "could not convert"))
                    continue
                values[spec.socket_name(disp, sfm, inst, fn)] = val
            # 0.24.2: what the FILE LEAVES out IS SOURCE'S DEFAULT, not the
            # socket's (those are picked for hand-built systems). A .pcf only
            # stores what differs from Source's default - a Radius Random
            # written w/o radius_min means radius 1, not 8: the metal
            # impacts' dust motes came out as big glowing balls.
            stored = set(elem.keys())
            for disp, sfm, _st, _d, _lo, _hi, _u in spec.fields_for(fn):
                if sfm not in stored and (fn, sfm) in spec.SFM_DEFAULTS:
                    values[spec.socket_name(disp, sfm, inst, fn)] = \
                        spec.SFM_DEFAULTS[(fn, sfm)]

    # 🔴 AN OPERATOR THE FILE DOES not LIST MUST not RUN - ANY operator.
    # The builder gives every catalogue operator a panel, and panels that
    # default ON (so a hand-built system shows something) silently ran on
    # imports too. That gave burst-only shockwaves a phantom 20/s stream,
    # gave every no-rotation system a phantom 0..360 random roll - the
    # zeus strike's screen-filling flare cards jazz-handed at random angles
    # SFM never gave them - and slid a phantom 0.25 fade in/out under
    # systems that never authored one. Present in the file means ON;
    # absent means OFF, for everything with an enable toggle
    #
    # Renderers are exempt: exactly one is always built (with a fallback
    # when the file names none), and its panel toggle drives nothing.
    for fn, fspec in spec.OPERATORS.items():
        if counts.get(fn) or fspec["section"] == "RENDERER":
            continue
        values[spec.panel_name(fn)] = False

    # 0.24.1: WHAT A PARTICLE IS BORN WITH WHEN NO INITIALIZER SETS IT.
    # SFM uses the system's own `color` (white unless authored) and `radius`
    # (5 unless authored). The importer used white and 8 - the concrete
    # impacts' dust flipbook is authored grey (98) and came out white
    if not counts.get("Color Random"):
        try:
            c = sysdef.get("color")
        except Exception:
            c = None
        if c is not None:
            val, _why = convert(c, "byte", "NodeSocketColor")
            if val is not None:
                values[spec.socket_name("Color 1", "color1", 1, "Color Random")] = val
    if not counts.get("Radius Random"):
        try:
            r = sysdef.get("radius")
        except Exception:
            r = None
        values[spec.socket_name("Radius Min", "radius_min", 1, "Radius Random")] = (
            float(r) if r is not None else 5.0)

    # SYSTEM PROPERTIES live on the definition itself, not on an operator
    for attr, socket in (("max_particles", "Max Particles [SFM: max_particles]"),):
        try:
            v = sysdef.get(attr)
        except Exception:
            v = None
        if v is not None:
            values[socket] = int(v)

    try:
        material = sysdef.get("material")
    except Exception:
        material = None

    # A CONTAINER: no renderer of its own and nothing to run. Real and common
    # - a root whose whole job is to hold children, which is how an author
    # groups one effect out of eight. Building it as a sprite system produces
    # an object that emits nothing and draws nothing, so it gets an ANCHOR
    # instead and the children hang off that
    container = rend_fn is None and not counts

    # A placed control point must EXIST: the hologram writes CP3's location
    # while nothing else ever references CP3, so the count from the index
    # scan alone would come up short
    cp_count = max(1, cp["count"])
    if cp_placements:
        cp_count = max(cp_count, max(cp_placements) + 1)

    return {"container": container,
            "renderer": renderer, "renderer_fn": rend_fn,
            "cp_count": cp_count, "cp_indices": cp["indices"],
            "cp_placements": cp_placements, "cp_frame": cp_frame,
            "stack": stack, "values": values, "enabled": enabled,
            "ignored": ignored, "notes": notes, "material": material}


def describe_plan(name, p):
    """One readable block per system, for the console."""
    if p.get("container"):
        return [f"  {name}",
                "      CONTAINER - no renderer, no operators. An anchor for "
                "its children."]
    out = [f"  {name}",
           f"      renderer      {p['renderer']}"
           + (f"  ({p['renderer_fn']})" if p["renderer_fn"] else ""),
           f"      control pts   {p['cp_count']}  referenced {p['cp_indices']}",
           f"      material      {p['material']}",
           f"      operators     {len(p['stack'])} kinds, "
           f"{sum(p['stack'].values())} instances",
           f"      values set    {len(p['values'])}"]
    dupes = {k: v for k, v in p["stack"].items() if v > 1}
    if dupes:
        out.append("      duplicated    "
                   + ", ".join(f"{k} x{v}" for k, v in sorted(dupes.items())))
    for note in p["notes"]:
        out.append(f"      NOTE          {note}")
    if p["ignored"]:
        whole = [i for i in p["ignored"] if i[1] == "*whole operator*"]
        fields = len(p["ignored"]) - len(whole)
        out.append(f"      DROPPED       {len(whole)} operators, "
                   f"{fields} fields")
        for fn, _a, why in whole[:8]:
            out.append(f"                      {fn}  ({why})")
    return out
