# =============================================================================
#  operators/op_ras.py  -  Create Render Animated Sprites (.VTF Sprite)
# =============================================================================
#
#  Pick a .vtf and get a full render_animated_sprites system: every operator
#  its own colour-coded node group with its own ENABLE toggle, arranged into
#  SFM's sections as modifier panels.
#
#      CONTROL POINTS · SYSTEM PROPERTIES · RENDERER · EMITTER
#      INITIALIZER · OPERATOR · FORCE GENERATOR · CONSTRAINT · CHILDREN
#
#  Lands in  __HoovyTools__ / Render Animated Sprites / <texture name>.
# =============================================================================

from pathlib import Path

import bpy
from bpy.types import Operator
from bpy.props import (StringProperty, IntProperty, FloatProperty,
                       BoolProperty, EnumProperty)
from bpy_extras.io_utils import ImportHelper

from . import op_prefs
from ..tools import (sprite_nodes, warp_nodes, ras_nodes, ras_ops, ras_system,
                     ras_spec, rope_nodes, trail_nodes, control_points,
                     layout)
from .op_vtf import vtf_to_image, ROOT_COLLECTION


TAG = "[HT_RAS]"
RAS_COLLECTION = "Render Animated Sprites"


def cp_slots(n):
    """The names of the OBJECT sockets, for the count this system was built
    with. It is a set of exact names on purpose: operators also have a socket
    called "Control Point [SFM: control_point_number]", which starts with the
    same words and is an INT, and matching on the prefix wires an empty into
    a number."""
    return tuple(f"Control Point {i}" for i in range(n))


def _collection(name):
    scene_root = bpy.context.scene.collection
    root = bpy.data.collections.get(ROOT_COLLECTION) \
        or bpy.data.collections.new(ROOT_COLLECTION)
    if root.name not in scene_root.children:
        try:
            scene_root.children.link(root)
        except Exception:
            pass
    mid = bpy.data.collections.get(RAS_COLLECTION) \
        or bpy.data.collections.new(RAS_COLLECTION)
    if mid.name not in root.children:
        try:
            root.children.link(mid)
        except Exception:
            pass
    sub = bpy.data.collections.get(name) or bpy.data.collections.new(name)
    if sub.name not in mid.children:
        try:
            mid.children.link(sub)
        except Exception:
            pass
    return sub


# =============================================================================
#  SHARED GROUPS ARE BUILT ONCE PER SESSION
# =============================================================================
#  ⚠️ `_group()` CLEARS an existing node group before refilling it, and
#  clearing an interface DROPS EVERY LINK anything else had made into it -
#  silently. So building a second system re-ran every operator builder and
#  quietly gutted the first system's graph: it kept its nodes, lost its wiring,
#  and emitted nothing. That was invisible until CHILDREN made "two systems in
#  one scene" the normal case rather than the exception.
#
#  The operator groups are pure functions of nothing - "SP · OPERATOR ·
#  Movement Basic" is the same graph every time - so the second build does not
#  need to happen at all. This cache keeps the one that was built.
#
#  It is keyed per Blender SESSION, not per file: reloading the add-on gives a
#  fresh module and a fresh empty cache, so code changes still take effect on
#  the next build. Anything with a material baked into it is keyed by that
#  material's name, and its node group is named after it too.
_SHARED_GROUPS = {}


def _still_there(made):
    """Is what we cached still in this .blend?

    A node group from a previous file is a DEAD POINTER after a file load, and
    touching it raises rather than returning None. Some builders hand back a
    dict of groups, so check every one of them.

    Matched by NAME, never with `is`: every attribute access can hand back a
    fresh Python wrapper around the same data."""
    try:
        vals = list(made.values()) if isinstance(made, dict) else [made]
        return bool(vals) and all(
            v is not None and bpy.data.node_groups.get(v.name) is not None
            for v in vals)
    except (ReferenceError, AttributeError, KeyError):
        return False


def _once(key, builder, *args):
    made = _SHARED_GROUPS.get(key)
    if made is not None and _still_there(made):
        return made
    made = builder(*args)
    _SHARED_GROUPS[key] = made
    return made


# =============================================================================
#  PICKING A PARENT
# =============================================================================
#  An Operator cannot hold a PointerProperty to an Object - Blender does not
#  allow it - so the parent is stored as a NAME and drawn with prop_search,
#  which gives the same searchable object dropdown and resolves at execute.
#
#  🔴 DEPENDENCIES RUN ONE WAY: PARENT -> CHILD. A child reads its parent's
#  particles through Object Info, which makes it depend on the parent, and the
#  depsgraph evaluates them in that order for nothing. If a parent ever read
#  a child back, that is a CYCLE - Blender refuses to evaluate it and hands
#  back stale or empty geometry, with no error that points at the cause.
#
#  So `Set child control points from particle positions` (110 uses in TF2)
#  must never be built by reading the child OBJECT. It is implemented inside
#  the parent's own graph, from the parent's own particles - which is where
#  that data already is. Nothing is lost and the object graph stays acyclic
#  by construction.

PARENT_PROP = dict(
    name="Parent System",
    description="Another particle system's host object. This system then "
                "spawns ON that one's particles instead of on its own "
                "control point - SFM's parent/child, one object each. "
                "Leave empty for a standalone system",
    default="")


def draw_parent_picker(layout, op, context):
    layout.separator()
    layout.label(text="CHILDREN", icon="OUTLINER_OB_POINTCLOUD")
    layout.prop_search(op, "parent_system", bpy.data, "objects", text="Parent")
    sub = layout.column()
    sub.scale_y = 0.72
    if op.parent_system:
        sub.label(text="Born on that system's particles, with its")
        sub.label(text="velocity inheritable. Parent evaluates first.")
    else:
        sub.label(text="Empty = standalone, born on its own CP0.")


def resolve_parent(op):
    """The chosen parent object, or None. Never a silent wrong answer.

    Returns (object, error). A NAME that no longer resolves is reported
    rather than treated as 'no parent' - building a child as a standalone
    system because a pointer went stale is exactly the kind of quiet wrong
    result that wastes an afternoon."""
    name = (getattr(op, "parent_system", "") or "").strip()
    if not name:
        return None, None
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, f"No object called '{name}' to parent to"
    if not any(m.type == "NODES" and m.node_group for m in obj.modifiers):
        return None, (f"'{name}' has no geometry-nodes particle system on it "
                      f"- a parent has to be a built system")
    return obj, None


def sfm_view_transform(scene):
    """AgX bleaches particle colour to white - measured, not guessed.

    A pure-red Color Random on an overbright-7 sheet renders at mean
    saturation 0.274 under AgX and 1.000 under Standard: the shader applies
    the colour fully, then the view transform desaturates every overbright
    pixel toward white. That is why Color Random and Color Fade "don't
    influence the sprite hard enough". Source has no filmic transform -
    Standard is what SFM shows.

    Only the UNTOUCHED default is replaced: a scene somebody deliberately
    set to Filmic or a custom look is their call, not ours."""
    try:
        if scene.view_settings.view_transform == "AgX":
            scene.view_settings.view_transform = "Standard"
            return True
    except Exception:
        pass
    return False


def _raise_transparent_bounces(scene, need=64):
    """Stop Cycles drawing a black rim where sprites overlap.

    Every sprite card is a TRANSPARENT surface. A camera ray that crosses
    more of them than Light Paths > Transparent allows is terminated and
    returns BLACK - so a cloud of particles grows dark outlines exactly where
    it is thickest, and the thicker it is the worse it looks. The default is
    8, which a particle effect passes almost immediately.

    Raised, never lowered: if the scene already allows more, that was a
    deliberate choice and this has no business undoing it."""
    try:
        cy = scene.cycles
    except AttributeError:
        return None
    was = cy.transparent_max_bounces
    if was < need:
        cy.transparent_max_bounces = need
        return was
    return None


def _set_input(mod, ident, value):
    try:
        getattr(mod.properties.inputs, ident).value = value
        return
    except Exception:
        pass
    try:
        mod[ident] = value
    except Exception as exc:
        print(f"{TAG}  modifier input {ident}: {exc}")


def _socket_for(display):
    """Turn a readable field name into the real socket name.

    Sockets are called "Radius Min [SFM: radius_min]" so that the exact .pcf
    attribute travels with them; callers should not have to know that."""
    if display in ("Scale", "Seed", "Camera") or display.startswith(
            "Control Point "):
        return display
    if display == "Max Particles":
        return ras_system.MAXP
    # "Operator::Field" disambiguates, and it has to be possible: "Emission
    # Start Time" belongs to BOTH emit_continuously and emit_instantaneously,
    # and "Control Point" to four different operators. Guessing silently
    # meant a burst's start time went to the continuous emitter instead.
    want_op, _, want = display.rpartition("::")
    hits = []
    for op in ras_spec.OPERATORS:
        if want_op and op != want_op:
            continue
        for field in ras_spec.fields_for(op):
            if field[0] == want:
                hits.append(
                    (op, ras_spec.socket_name(field[0], field[1], 1, op)))
    if not hits:
        return display
    if len(hits) > 1:
        print(f"{TAG}  {want!r} is ambiguous - it belongs to "
              f"{', '.join(o for o, _s in hits)}. Using {hits[0][0]}; "
              f"write '{hits[0][0]}::{want}' to choose.")
    return hits[0][1]


def build_ras(context, path, values=None,
              cp_spread=control_points.DEFAULT_SPREAD,
              emitter="SIMULATION", stack=None,
              renderer="ANIMATED_SPRITES",
              cp_count=ras_system.DEFAULT_CONTROL_POINTS,
              parent=None, key_cps=False, host_name=None, overbright=1.0,
              additive=False, warp=None, span_sequences=False, root=None,
              cps=None, collection=None, blend=None, draws=None):
    """Decode a .vtf and stand up the whole system. Returns (host, info).

    draws     how many times SFM draws this system's cards (0.24.2, measured):
              2 when another sprite system in the same effect shares the
              material - the .pcf importer counts that - else 1. A trail is
              always drawn once.

    cp_count  how many control points to build. Four unless told otherwise;
              a .pcf import passes the number read out of the file.
    parent    an existing system's host object. Assigning it fills in the
              CHILDREN panel, so this system is born on that one's particles.
    root      the effect's control empty. Every system in one effect shares it,
              and the host is parked on its origin. Left out, one is made -
              a single system standing on its own is still an effect.
    cps       the effect's control point empties, already made. Left out, this
              system spawns them; the .pcf importer passes them in so a parent
              and its children read the SAME control points instead of one
              stack of empties each.
    collection  where the objects go. The importer owns the effect collection;
              on its own this builds a `RAS · <texture>` one."""
    # DRIVER SYSTEM (path is None): no texture to draw. Still emit + move
    # particles so its CHILDREN ride them - Position From Parent Particles reads
    # one INSTANCE per parent particle, and an invisible card still IS one
    # instance. Covers material-less SFM systems (deliberate motion carriers,
    # e.g. a "circling" system feeding a beam child) AND systems whose .vmt/.vtf
    # is missing, which now degrade to invisible instead of dropping the whole
    # subtree. Forced to the sprite renderer: it draws nothing anyway, and only
    # the emitter + operators (the motion) matter to the children.
    driver = path is None
    rects = None            # set only by the non-uniform-sheet branch
    if driver:
        import re as _re
        stem = _re.sub(r"[^\w.-]+", "_", str(host_name or "driver")) or "driver"
        img, info, sheet, grid = None, {}, None, None
        cols, rows = 1, 1
        sequences = [(0, 1, False)]
        renderer = "ANIMATED_SPRITES"
        mat = sprite_nodes.build_invisible_material(f"RAS Driver · {stem}")
        print(f"{TAG}  {stem}: DRIVER (no texture) - invisible, children ride it")
    else:
        img, info = vtf_to_image(path)
        sheet = info.get("sheet")
        grid = info.get("grid")
        stem = Path(path).stem
        _w, _h = img.size[0], img.size[1]
        if sheet and grid is None and not warp:
            # NON-UNIFORM sheet: the frames are DIFFERENT sizes, so there is no
            # grid to tile. Cut by the VTF's OWN per-frame rectangles instead:
            # the SYSTEM holds them all in one Index Switch and stores each
            # particle's chosen rect; the material just maps UVs onto it.
            # (This case used to fall back to 1x1 and draw the WHOLE sheet on
            # every card - the variable-width spark strip bug.)
            cols, rows = 1, 1
            sequences, rects = sprite_nodes.rect_sequence_table(sheet, _w, _h)
            print(f"{TAG}  {Path(path).name}: non-uniform sheet -> per-frame "
                  f"rects, {len(sequences)} sequence(s) / {len(rects)} frame(s)")
            for i, (st, ct, lp) in enumerate(sequences):
                print(f"{TAG}     seq {i}: rect {st}, {ct} frame(s), "
                      f"{'LOOPS' if lp else 'plays once'}")
            #  Named under the "RAS Sheet UV" family so the hand shader layout
            #  adopts it into the Sheet Processing frame like the grid group.
            uv_group = sprite_nodes.build_rect_uv_group(
                f"RAS Sheet UV · {stem} · rects", rects, _w, _h)
        else:
            if sheet and grid is None and warp:
                # A warp material samples a normal map through the same UV
                # group, but the warp builder speaks Frame/Columns/Rows - no
                # rect variant exists yet. Said out loud, not silently wrong.
                print(f"{TAG}  ⚠ {Path(path).name}: non-uniform sheet on a "
                      f"WARP material - per-frame rects not built for warps "
                      f"yet, cards sample the whole sheet")
            cols, rows = (grid[0], grid[1]) if grid else (1, 1)
            sequences = sprite_nodes.sequence_table(sheet, cols, rows) if sheet \
                else [(0, 1, False)]
            print(f"{TAG}  {Path(path).name}: {cols}x{rows} grid, "
                  f"{len(sequences)} sequence(s)")
            for i, (st, ct, lp) in enumerate(sequences):
                print(f"{TAG}     sequence {i}: tile {st}, {ct} frames, "
                      f"{'LOOPS' if lp else 'plays once and holds'}")
            uv_group = sprite_nodes.build_sheet_uv_group(
                f"RAS Sheet UV · {stem}", cols, rows, _w, _h)

        if span_sequences and len(sequences) > 1:
            # 🔴 A HAND-BUILT SYSTEM ON A MULTI-SEQUENCE SHEET DREW VARIANT 0
            # FOREVER. Sequence Min/Max default to 0/0 - faithful for a .pcf,
            # which states what it wants - but Create Trail on the 4-spark sheet
            # rolled sequence 0 for every particle, and the sheet looked like it
            # was never divided. Hand-built entry points span the sheet's whole
            # table unless the caller narrowed it themselves.
            values = dict(values or {})
            values.setdefault("Sequence Min", 0)
            values.setdefault("Sequence Max", len(sequences) - 1)
        # The material is keyed by texture AND overbright: the same .vtf used at
        # two brightnesses by two systems is two materials, not one that the
        # second build quietly re-brightens under the first. The material FAMILY
        # was decided by op_vmt.resolve_source: a Refract .vmt hands over `warp`
        # and the cards get the warp material instead of the emissive sprite one
        # - same emitter, same per-particle attributes, different shader.
        if warp:
            mat = warp_nodes.build_warp_material(
                f"RAS Warp · {stem} · a{warp['refract_amount']:g}",
                img, cols, rows, uv_group, **warp)
        else:
            # 0.24.0: the material is keyed by its whole BLEND (mode, overbright,
            # addself), so two systems sharing a .vtf at different settings
            # never share a material. A bare .vtf with no .vmt hands over no
            # blend and keeps what the old switches meant.
            bl = blend or sprite_nodes.legacy_blend(overbright, additive)
            # 0.24.2: HOW MANY TIMES SFM DRAWS IT, measured - a trail once, a
            # sprite twice only when another sprite system in the same effect
            # shares its material. Part of the name, like the blend: the same
            # .vtf drawn once and twice is two materials.
            n_draws = 1 if (renderer or "").upper() == "SPRITE_TRAIL" \
                else max(1, int(draws or 1))
            mat = sprite_nodes.build_sprite_material(
                f"RAS Sprite · {stem}" + sprite_nodes.blend_tag(bl)
                + sprite_nodes.draws_tag(n_draws),
                img, cols, rows, uv_group, overbright=bl["overbright"],
                rect_attrs=bool(rects), blend=bl, draws=n_draws)

    vp = op_prefs.viewport_facing()
    eye = _once("eye·viewport" if vp else "eye",
                ras_nodes.build_camera_eye, vp)
    groups = {
        "envelope": _once("envelope", ras_nodes.build_envelope),
        "emit": _once("emit", ras_nodes.build_emit_continuously),
        "emit_sim": _once("emit_sim", ras_nodes.build_emit_sim),
        "lock": _once("lock", ras_nodes.build_movement_lock_to_cp),
        "renderer": _once(f"renderer·{mat.name}",
                          ras_nodes.build_render_animated_sprites, mat, eye),
        "velocity": _once("velocity", ras_ops.build_velocity_random),
        "movement": _once("movement", ras_ops.build_movement_basic),
        "fade_in": _once("fade_in", ras_ops.build_alpha_fade_in),
        "fade_out": _once("fade_out", ras_ops.build_alpha_fade_out),
        "radius_scale": _once("radius_scale", ras_ops.build_radius_scale),
        "spin_roll": _once("spin_roll", ras_ops.build_spin_roll),
        "random_force": _once("random_force", ras_ops.build_random_force),
        "yaw_flip": _once("yaw_flip", ras_ops.build_yaw_flip),
        "velocity_noise": _once("velocity_noise",
                                ras_ops.build_velocity_noise),
        "pull_cp": _once("pull_cp", ras_ops.build_pull_to_cp),
        "twist_axis": _once("twist_axis", ras_ops.build_twist_axis),
        "emit_instant": _once("emit_instant", ras_ops.build_emit_instant),
        "parent_pos": _once("parent_pos",
                            ras_ops.build_position_from_parent),
        "path_seq": _once("path_seq", ras_ops.build_position_along_path),
        "fade_decay": _once("fade_decay",
                            ras_ops.build_alpha_fade_and_decay),
        "color_fade": _once("color_fade", ras_ops.build_color_fade),
        "remap_cp": _once("remap_cp", ras_ops.build_remap_distance_cp),
        "constrain_path": _once("constrain_path",
                                ras_ops.build_constrain_to_path),
        "constrain_cp": _once("constrain_cp", ras_ops.build_constrain_to_cp),
        "yaw_random": _once("yaw_random", ras_ops.build_yaw_random),
        "random_force_tick": _once("random_force_tick",
                                   ras_ops.build_random_force_tick),
    }
    groups.update(_once("initializers", ras_nodes.build_initializers))
    # A rope drags in its own material and shader; do not build either
    # for a sprite system that will never reference them.
    if (renderer or "").upper() == "ROPE":
        if warp:
            # Honest, not silent: the rope has its OWN material and no warp
            # variant of it exists yet, so a Refract .vmt on a rope gets the
            # neutral rope shader - said out loud rather than half-built.
            print(f"{TAG}  {stem}: Refract material on a ROPE - the warp "
                  f"shader only exists for sprite cards so far, so the rope "
                  f"builds with its normal material")
        # KEYED BY CONTENT, like the sprite material: the same .vtf drawn at
        # two brightnesses is two materials, not one that the second build
        # quietly re-brightens under the first.
        rope_mat = rope_nodes.build_rope_material(
            f"ROPE · {stem}"
            + (f" · x{overbright:g}" if abs(overbright - 1.0) > 1e-6 else "")
            + (" · additive" if additive else ""),
            img, overbright=overbright, additive=additive)
        groups["rope"] = _once(f"rope·{rope_mat.name}",
                               rope_nodes.build_render_rope, rope_mat, eye)
    elif (renderer or "").upper() == "SPRITE_TRAIL":
        # A trail uses the SAME sheet material as an animated sprite - that
        # is what gives it sequences for nothing.
        groups["trail"] = _once(f"trail·{mat.name}",
                                trail_nodes.build_render_sprite_trail,
                                mat, eye)
        groups["trail_length"] = _once("trail_length",
                                       trail_nodes.build_trail_length_random)
    cp_count = control_points.clamp_count(
        cp_count, ras_system.DEFAULT_CONTROL_POINTS)

    coll = collection if collection is not None else _collection(f"RAS · {stem}")

    def put(obj):
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        coll.objects.link(obj)

    # THE CONTROL EMPTY FIRST. It is the effect's transform: hosts and control
    # points all sit on its origin, so "relative to the host" and "relative to
    # the control empty" are one frame, and one shared set of control points
    # can serve every system in the tree. Object Info reads control points
    # RELATIVE, so unparented empties mean moving the effect slides it the
    # OTHER WAY and it stays pinned to the world origin.
    # Re-running the builder on the same .vtf REBUILDS IN PLACE rather than
    # piling up copies - but a child is a different system that happens to
    # share a texture, so it gets its own host. Without this the child would
    # take over the parent it was meant to follow.
    # 🔴 NAME THE HOST AFTER THE SYSTEM, NOT AFTER THE TEXTURE.
    # Naming by .vtf stem loses data: two children of one parent that share a
    # texture - `brightglow_y` twice under one explosion, which is completely
    # normal - resolve to the SAME object name, so the second build reuses the
    # first one's object and node group and the first system is gone. It looks
    # like the import merely built fewer systems than expected.
    # A .pcf system name is unique (build_hierarchy disambiguates with #2),
    # so the importer passes it and this stays a per-system identity.
    if host_name is None:
        host_name = (f"RAS · {stem}" if parent is None
                     else f"RAS · {stem} · child of {parent.name}")
    host = bpy.data.objects.get(host_name)
    if host is None:
        mesh = bpy.data.meshes.new(host_name + "_carrier")
        host = bpy.data.objects.new(host_name, mesh)
    put(host)

    # THE SLOT IS FOR PEOPLE, NOT FOR RENDERING. Set Material inside the
    # renderer group is what actually draws the cards; without a slot the
    # host object LOOKS materialless - click it and the Shader Editor shows
    # nothing, which reads as "the shader was never built". The same
    # material in the mesh's slots makes clicking the host jump straight
    # into editing the real shader.
    try:
        slot_mat = rope_mat if (renderer or "").upper() == "ROPE" else mat
        host.data.materials.clear()
        host.data.materials.append(slot_mat)
    except Exception as exc:
        print(f"{TAG}  material slot on {host_name}: {exc}")

    if root is None:
        root = control_points.effect_root(
            f"{host_name} · CONTROL", collection=coll,
            location=context.scene.cursor.location)
    put(root)
    control_points.attach(host, root)

    # THE SYSTEM GROUP IS NAMED AFTER ITS HOST, not after the texture. Two
    # systems from the same .vtf - which is exactly what a parent and its
    # child usually are - would otherwise share one node group name, and the
    # second build would clear the first one's graph out from under it.
    # Blender guarantees object names are unique, so host names are too.
    system = ras_system.build_system(
        f"RENDER ANIMATED SPRITES · {host.name}", mat, sequences, cols, rows,
        groups, emitter=emitter, stack=stack, renderer=renderer,
        cp_count=cp_count, rects=rects)
    print(f"{TAG}  emitter: {emitter}, "
          f"{control_points.describe(cp_count)}")
    if stack:
        for op, n in sorted(stack.items()):
            if n != 1:
                print(f"{TAG}  stack: {op} x{n}")

    fancy = op_prefs.fancy_layouts()
    if fancy:
        for made in groups.values():
            for g in (made.values() if isinstance(made, dict) else [made]):
                try:
                    layout.tidy(g, verbose=False)
                except Exception as exc:
                    print(f"{TAG}  tidy skipped for "
                          f"{getattr(g, 'name', '?')}: {exc}")

    # ⚠️ AUTO-ARRANGE IS OFF, AND THE NUMBERS WERE NOT THE POINT.
    # Deriving positions from the wiring scored beautifully - 28 overlapping
    # node pairs to 0, 154 backwards links to 0 - and READ WORSE than the
    # hand-placed layout it replaced: one section per horizontal band turned
    # a compact graph you could take in at a glance into a tall ribbon you
    # have to scroll. Compactness is part of readability and no counter here
    # measures it.
    #
    # Keeping it available (layout.arrange) because it is the right tool for
    # a graph with no layout at all. It is the wrong tool for one that has a
    # good one already.
    if fancy:
        try:
            layout.tidy(system, verbose=False)
        except Exception as exc:
            print(f"{TAG}  layout skipped: {exc}")
    else:
        print(f"{TAG}  fast import: node layouts skipped "
              f"(Preferences > Add-ons > HoovyTools to re-enable)")
    #  THE PALETTE, REASSERTED EVERYWHERE. tidy() colours the system tree it
    #  just laid out, but the shared operator groups were built and cached
    #  before some of the colour passes existed - so every build repaints
    #  every add-on group: section hues from tools/layout._HUES (the same
    #  table the sidebar icons derive from) and the orange->blue flow ramp
    #  on anything no section claims. Deterministic, so repainting is free.
    try:
        layout.recolour_all(system)
        for g in bpy.data.node_groups:
            if g.name.startswith("SP · ") \
                    and g.bl_idname == "GeometryNodeTree":
                layout.recolour_all(g)
    except Exception as exc:
        print(f"{TAG}  recolour skipped: {exc}")

    was = _raise_transparent_bounces(context.scene)
    if was is not None:
        print(f"{TAG}  Cycles transparent bounces {was} -> "
              f"{context.scene.cycles.transparent_max_bounces} "
              f"(overlapping sprites render black past the limit)")
    if sfm_view_transform(context.scene):
        print(f"{TAG}  view transform AgX -> Standard (AgX bleaches "
              f"particle colour to white; SFM has no filmic transform)")

    # ONE SET PER EFFECT. Passed in by the .pcf importer so a parent and its
    # children read the SAME empties; spawned here when this system is the
    # whole effect. ⚠️ NO KEYFRAME BY DEFAULT - a key at 0,0,0 on every empty
    # made them snap back the moment anyone scrubbed, and on a five-system
    # import that was five stacks of keyed empties nobody asked for.
    if cps is None:
        cps = control_points.spawn(root.name, cp_count, root=root,
                                   collection=coll, spread=cp_spread,
                                   keyframe=key_cps)
    elif len(cps) < cp_count:
        print(f"{TAG}  {host_name}: wants {cp_count} control points but the "
              f"effect only built {len(cps)} - the extra reads clamp to the "
              f"last one")

    for m in list(host.modifiers):
        host.modifiers.remove(m)
    mod = host.modifiers.new("Render Animated Sprites", "NODES")
    mod.node_group = system

    cam = next((o for o in bpy.data.objects if o.type == "CAMERA"), None)
    slots = cp_slots(cp_count)
    values = {_socket_for(k): v for k, v in (values or {}).items()}
    for item in system.interface.items_tree:
        if getattr(item, "item_type", "") != "SOCKET" or item.in_out != "INPUT":
            continue
        nm = item.name
        # The CP object slots are "Control Point 0".."Control Point N". Do NOT
        # match on the prefix alone - operators now have their own "Control
        # Point [SFM: control_point_number]" sockets, which are ints.
        if nm in slots:
            # Clamped, not indexed blind: a shared set can be shorter than one
            # system's count if the file disagrees with itself, and an
            # IndexError here would take the whole import down.
            _set_input(mod, item.identifier,
                       cps[min(slots.index(nm), len(cps) - 1)])
        elif nm == "Camera" and cam is not None:
            _set_input(mod, item.identifier, cam)
        elif nm == ras_system.PARENT_OBJ and parent is not None:
            _set_input(mod, item.identifier, parent)
        elif nm == ras_system.PARENT_FROM and parent is not None:
            # What the parent's renderer left behind decides how its particles
            # are read: sprites make one INSTANCE per particle, a rope makes a
            # ribbon and no instances at all.
            _set_input(mod, item.identifier,
                       ras_ops.PARENT_FROM_VERTICES if _is_rope(parent)
                       else ras_ops.PARENT_FROM_INSTANCES)
        elif nm in values:
            _set_input(mod, item.identifier, values[nm])

    if parent is not None:
        # Switch the operator ON - it is off by default because a system with
        # no parent assigned should not look broken.
        #
        # 🔴 BUT ONLY WHEN THE AUTHORING SAYS SO. Being someone's child in
        # the .pcf tree does NOT mean being born on their particles - that
        # is Position From Parent Particles' job, and it is a field the file
        # either lists or does not. glow-begin (a child of glow that authors
        # its own sphere AT CP1) was riding its parent's constraint-mapped
        # particles because this switched the operator on for EVERY child.
        # A hand build (stack=None) keeps the convenience: picking a parent
        # in the dialog means you want to spawn on it.
        authored = stack is None or bool(
            stack.get("Position From Parent Particles"))
        if authored:
            for item in system.interface.items_tree:
                if (getattr(item, "item_type", "") == "SOCKET"
                        and item.in_out == "INPUT"
                        and item.name == "Position From Parent Particles"):
                    _set_input(mod, item.identifier, True)
            print(f"{TAG}  child of {parent.name}")
        else:
            print(f"{TAG}  child of {parent.name} in the TREE only - the "
                  f"file does not author Position From Parent Particles, so "
                  f"it is born on its own control point")

    info.update({"cols": cols, "rows": rows, "sequences": sequences,
                 "control_points": cp_count, "root": root, "cps": cps,
                 "groups": len(groups) + 2})
    return host, info


def _is_rope(obj):
    """Was that object built as a rope? A rope outputs a ribbon MESH and no
    per-particle instances, so a child of one has to read vertices."""
    for m in getattr(obj, "modifiers", []):
        ng = getattr(m, "node_group", None)
        if ng is None:
            continue
        for item in ng.interface.items_tree:
            if getattr(item, "item_type", "") == "PANEL" \
                    and item.name == "render_rope":
                return True
    return False


class HTP_OT_CreateRAS(Operator, ImportHelper):
    """Build a render_animated_sprites system - one CARD per particle

Source's workhorse renderer, and the one most effects use. Every SFM
operator arrives as its own node group with its own ENABLE toggle, and
the modifier panels ARE the SFM sections you already know:

    RENDERER · EMITTER · INITIALIZER · OPERATOR
    FORCE GENERATOR · CONSTRAINT · CHILDREN

Sockets are named `Readable [SFM: exact_pcf_attribute]`, so a value you
find in a .pcf has one obvious place to go. Every node group carries a
written note explaining what it does and what the trap was - open one and
read it.

Sequences come from the sheet's own table, per particle.

TAKES A .VMT OR A .VTF. Give it the material and $overbrightfactor and
$additive come with it - which is the difference between a glow that burns
and a bright blob on a black rectangle. A bare .vtf is only the picture, so
it builds a neutral material and says so in the console."""
    bl_idname = "htp.create_ras"
    bl_label = "Create Render Animated Sprites"
    bl_options = {"REGISTER", "UNDO"}

    # EITHER a .vmt or a .vtf. Pick the material and its $overbrightfactor
    # and $additive come with it; pick the bare texture and the material is
    # neutral, which the console says out loud rather than implying one was
    # read.
    filename_ext = ".vmt"
    filter_glob: StringProperty(default="*.vmt;*.vtf", options={"HIDDEN"})

    emitter: EnumProperty(
        name="Emitter",
        description="How particles are born and remembered",
        items=[
            ("SIMULATION", "Simulation",
             "Particles are remembered in a simulation zone, created at the "
             "control point's position on the frame they were born. Handles "
             "a moving emitter correctly. Play from frame 1"),
            ("STATELESS", "Stateless (scrubbable)",
             "A ring of recycled slots derived entirely from the clock. You "
             "can scrub backwards, but particles follow the control point "
             "around because nothing remembers where it used to be"),
        ],
        default="SIMULATION")
    max_particles: IntProperty(
        name="Max Particles",
        description="Ceiling on how many can be alive at once. Keep it at or "
                    "above emission rate x longest lifetime",
        default=200, min=1, max=10000)
    emission_rate: FloatProperty(
        name="Emission Rate", description="Particles per second",
        default=20.0, min=0.0)
    lifetime_min: FloatProperty(name="Lifetime Min", default=1.0, min=0.001)
    lifetime_max: FloatProperty(name="Lifetime Max", default=2.0, min=0.001)
    distance_max: FloatProperty(name="Distance Max", default=10.0, min=0.0)
    radius_min: FloatProperty(name="Radius Min", default=8.0, min=0.0)
    radius_max: FloatProperty(name="Radius Max", default=16.0, min=0.0)
    animation_rate: FloatProperty(
        name="Animation Rate",
        description="1.0 plays the whole sequence in one second",
        default=1.0, min=0.0)
    fit_lifetime: BoolProperty(
        name="Animation Fit Lifetime",
        description="Stretch the sequence to last exactly as long as the "
                    "particle, ignoring Animation Rate",
        default=False)
    scale: FloatProperty(
        name="Scale",
        description="Leave at 1.0: internal particle space is Hammer units, "
                    "1 Blender Unit = 1 SFM unit. Set 0.01905 only if you "
                    "want the effect shrunk to metres for display",
        default=1.0, min=0.0)
    seed: IntProperty(name="Seed", default=0)
    control_points: IntProperty(
        name="Control Points",
        description="How many CP empties to create, and how far every "
                    "'control point number' socket can reach. A real .pcf "
                    "says how many it needs - most want 1, but 8% of TF2 "
                    "wants more than four and one system wants 41",
        default=ras_system.DEFAULT_CONTROL_POINTS, min=1,
        max=control_points.MAX_CONTROL_POINTS)
    key_control_points: BoolProperty(
        name="Keyframe Control Points",
        description="Put one location key on each control point where it "
                    "stands, so auto-key records a move immediately instead "
                    "of needing a starting pose keyed by hand. Off, they "
                    "stay free to drag around",
        default=False)
    parent_system: StringProperty(**PARENT_PROP)

    def invoke(self, context, event):
        if not self.filepath:
            start = op_prefs.texture_dir()
            if start is not None:
                self.filepath = str(start) + "\\"
        return super().invoke(context, event)

    def draw(self, context):
        col = self.layout.column()
        col.label(text="EMITTER", icon="PARTICLES")
        col.prop(self, "emitter", expand=True)
        if self.emitter == "SIMULATION":
            sub = col.column()
            sub.scale_y = 0.75
            sub.label(text="Play from frame 1 - a simulation", icon="INFO")
            sub.label(text="cannot be scrubbed backwards into.")
        col.prop(self, "emission_rate")
        col.prop(self, "max_particles")
        col.separator()
        col.label(text="INITIALIZER", icon="PARTICLEMODE")
        col.prop(self, "lifetime_min")
        col.prop(self, "lifetime_max")
        col.prop(self, "distance_max")
        col.prop(self, "radius_min")
        col.prop(self, "radius_max")
        col.separator()
        col.label(text="RENDERER", icon="RENDER_RESULT")
        col.prop(self, "animation_rate")
        col.prop(self, "fit_lifetime")
        col.separator()
        col.label(text="CONTROL POINTS", icon="EMPTY_AXIS")
        col.prop(self, "control_points")
        col.prop(self, "key_control_points")
        draw_parent_picker(col, self, context)
        col.separator()
        col.prop(self, "scale")
        col.prop(self, "seed")
        box = self.layout.box()
        box.scale_y = 0.8
        box.label(text="Every operator gets its own toggle", icon="INFO")
        box.label(text="in the modifier, sorted by SFM section.")
        box.label(text="CHILDREN: point another system's host at")
        box.label(text="Parent System and this one spawns on it.")

    def execute(self, context):
        from .op_vmt import resolve_source
        src = resolve_source(self.filepath)
        if src["vtf"] is None:
            self.report({"ERROR"}, src["note"])
            return {"CANCELLED"}
        path = src["vtf"]
        print(f"{TAG}  {src['note']}")
        values = {
            "Max Particles": self.max_particles,
            "Emission Rate": self.emission_rate,
            "Lifetime Min": self.lifetime_min,
            "Lifetime Max": self.lifetime_max,
            "Distance Max": self.distance_max,
            "Radius Min": self.radius_min,
            "Radius Max": self.radius_max,
            "Animation Rate": self.animation_rate,
            "Fit Lifetime": self.fit_lifetime,
            "Scale": self.scale,
            "Seed": self.seed,
        }
        parent, err = resolve_parent(self)
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        try:
            host, info = build_ras(context, path, values,
                                   emitter=self.emitter,
                                   cp_count=self.control_points,
                                   parent=parent,
                                   key_cps=self.key_control_points,
                                   overbright=src["overbright"],
                                   additive=src["additive"],
                                   blend=src.get("blend"),
                                   warp=src.get("warp"),
                                   span_sequences=True)
        except Exception as exc:
            self.report({"ERROR"}, f"Could not build the system: {exc}")
            print(f"{TAG}  FAILED for {path.name}: {exc}")
            return {"CANCELLED"}

        seqs = info["sequences"]
        loops = sum(1 for _s, _c, lp in seqs if lp)
        self.report(
            {"INFO"},
            f"{path.stem}: {info['cols']}x{info['rows']} sheet, "
            f"{len(seqs)} sequence(s) ({loops} looping), "
            f"{info['groups']} node groups, "
            f"{info['control_points']} control point(s), "
            f"{self.emitter.lower()} emitter -> {host.name}"
            + (" · play from frame 1"
               if self.emitter == "SIMULATION" else ""))
        for o in context.selected_objects:
            o.select_set(False)
        host.select_set(True)
        context.view_layer.objects.active = host
        return {"FINISHED"}


class HTP_OT_RendererNotYet(Operator):
    """This Source renderer is not implemented yet"""
    bl_idname = "htp.renderer_not_yet"
    bl_label = "Renderer not implemented"
    bl_options = {"REGISTER", "INTERNAL"}

    renderer: StringProperty(default="")
    reason: StringProperty(default="")

    def execute(self, context):
        # Say so out loud rather than doing nothing. A dead button that
        # silently succeeds is worse than one that admits the gap.
        self.report({"WARNING"},
                    f"{self.renderer} is not implemented yet. {self.reason}")
        print(f"{TAG}  {self.renderer}: not implemented. {self.reason}")
        return {"CANCELLED"}


CLASSES = (HTP_OT_CreateRAS, HTP_OT_RendererNotYet)
