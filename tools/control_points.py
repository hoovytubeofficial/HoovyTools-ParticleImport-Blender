# =============================================================================
# tools/control_points.py  -  one way to spawn control points, for everybody
# =============================================================================
#
# why this exists
#  ---------------
# A Source effect is defined relative to numbered transforms - control points
# Every part of this add-on that puts an effect in a scene needs to create
# them, and until now each part invented its own four.
#
# FOUR is the WRONG NUMBER, and the corpus says so plainly. Surveying all 97
# TF2 packs (see `__ForYou/PCF Corpus Survey.txt`, CONTROL POINTS section):
#
# 1 CP   2917 systems        6 CP      6 systems
# 2 CP    279 systems        8 CP      9 systems
# 3 CP     40 systems       10 CP    126 systems
# 4 CP     46 systems       11 CP     46 systems
# 5 CP     97 systems       35 CP      4 systems
# 41 CP      4 systems
#
# The tail is small but it's REAL - taunt_fx.pcf::taunt_demo_nuke_shroom4_base
# wants forty-one. An importer that always makes four is wrong for 8% of TF2
# and silently drops every reference above CP3 on the floor
#
# So: the count comes from the FILE (tools/pcf.py::get_control_points), the
# empties come from here, and the node graph is generated for that many
#
# WHAT THIS MODULE DECIDES
# * how many is sane          (MAX_CONTROL_POINTS)
# * where the empties go      (cp_location - a row that wraps, not a line
# 41 units long you have to zoom out to see)
# * what they look like       (CP0 is ARROWS and bigger; it's the one
# almost every operator actually reads)
# * who they belong to        (parented to the host - see below)
#
# 🔴 one set of empties per effect, not per system.
# A control point is a property of the EFFECT, not of one system inside it -
# in SFM a parent and its children all read CP0, and it is the same CP0. Every
# system spawning its own meant a five-system effect arrived as five stacks of
# empties that all had to be dragged together to move anything, and nothing in
# the outliner said which stack mattered. Now the effect gets one control
# empty, the systems hang off it, and the control points hang off it too -
# counted ONCE, as the highest number any system in the tree asked for
#
# <effect> · CONTROL          the whole effect's transform
# ├── <system>              the mesh carrying the geometry nodes
# ├── <system>-child        ... one per system, all at the origin
# └── <effect> · CP0..CPn   shared by every system above
#
# 🔴 THE EMPTIES are PARENTED, and that's load-bearing. Object Info reads
# control points in RELATIVE space, i.e. measured in the reading system's
# frame. With the empties unparented, moving the effect moves the frame but
# not the empties, so it slides the OTHER WAY and stays pinned to the world
# origin. Parented to the control empty - with every host sitting at that same
# origin - "relative" is a constant, and dragging the control empty takes the
# whole effect with it
# =============================================================================

import bpy


# sixty-four, not forty-one: the corpus is the evidence for the tail, not a
# guarantee that nobody has ever authored more. It is a guard against a
# corrupt file asking for four billion empties, not a statement about SFM.
MAX_CONTROL_POINTS = 64

#🔴 ZERO ON PURPOSE: EVERY CONTROL POINT STARTS ON the HOST, at 0,0,0 in its
#own space. Fanning them out in a row is tidier in the outliner and wrong
#everywhere else - SFM puts a control point where the effect needs it, and an
#empty parked 32 units away that nobody moved is a lie about the effect. They
#start together and you drag out the ones that matter
#
#Set a spread if you want them laid out to grab: `spawn(..., spread=16)` puts
#them one Hammer grid square apart, in rows of eight.
DEFAULT_SPREAD = 0.0

# how many go in a row before wrapping to the next one, when a spread is given
ROW = 8

#all at one point would be unclickable, so the crosses are NESTED instead -
#each one a little smaller than the last. Same position, still tellable apart.
ROOT_SIZE = 12.0
STEP_SIZE = 8.0
MIN_SIZE = 1.5


# the control empty is the thing a user actually grabs, so it is bigger than
# anything hanging off it and shaped like nothing else in the scene
ROOT_EMPTY_SIZE = 24.0


def effect_root(name, collection=None, location=None):
    """The ONE empty that carries a whole effect. Created, or re-found.

    Everything else in the effect - every system's mesh, every control point -
    is parented to this. Moving an imported effect is then a single object to
    grab, and a child system cannot be left behind by dragging its parent.

    ⚠️ IT IS THE ONLY THING PLACED AT THE 3D CURSOR. Hosts and control points
    all sit at its origin, so "relative to the host" and "relative to the
    control empty" are the same frame - which is what lets one shared set of
    control points serve every system in the tree."""
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "EMPTY":
        obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "PLAIN_AXES"
    obj.empty_display_size = ROOT_EMPTY_SIZE
    obj["htp_effect_root"] = True
    if location is not None:
        obj.location = tuple(location)
    if collection is not None:
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        collection.objects.link(obj)
    return obj


# the transform empty is what you grab to move every control point at once,
# without moving the effect's origin. Distinct shape so it never reads as a
# control point itself
TRANSFORM_SIZE = 16.0


def transform_root(prefix, root=None, collection=None):
    """The ONE empty every control point of an effect hangs off.

    🔴 STRUCTURAL, NOT COSMETIC. The outliner used to show the control
    points, the override empties and the system meshes all as one flat pile
    of children under the control empty. Now the empties gather under
    "<effect> · TRANSFORM":

        <effect> · CONTROL            move the WHOLE effect
          ├── <root system mesh>
          │     └── <child system mesh>      (the SFM tree, as parenting)
          └── <effect> · TRANSFORM    move every control point at once
                ├── <effect> · CP0..CPn
                └── <system> · CP1...        (Set CP Positions overrides)

    Grabbing TRANSFORM slides all the control points together while the
    effect's origin stays put - which is exactly the handle a beam or a
    five-puff smoke arrangement wants."""
    name = f"{prefix} · TRANSFORM"
    obj = bpy.data.objects.get(name)
    if obj is None or obj.type != "EMPTY":
        obj = bpy.data.objects.new(name, None)
    obj.empty_display_type = "CUBE"
    obj.empty_display_size = TRANSFORM_SIZE
    obj["htp_cp_transform"] = True
    if collection is not None:
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        collection.objects.link(obj)
    if root is not None and obj is not root:
        obj.parent = root
        obj.matrix_parent_inverse.identity()
        obj.location = (0.0, 0.0, 0.0)
    return obj


def find_transform(root):
    """The effect's TRANSFORM empty, if one hangs off this root."""
    for ch in getattr(root, "children", []) or []:
        if ch.get("htp_cp_transform"):
            return ch
    return None


def attach(obj, root):
    """Park an object on the effect root, at the root's own origin.

    ⚠️ IDENTITY PARENT INVERSE, ALWAYS. Blender's default is to bake the
    parent's current transform into the inverse so the child does not appear to
    move - which is exactly wrong here, because it would leave the host offset
    from the frame the control points are measured in."""
    if root is None or obj is root:
        return
    obj.parent = root
    obj.matrix_parent_inverse.identity()
    obj.location = (0.0, 0.0, 0.0)


def clamp_count(n, default=4):
    """A control point count we are willing to build a graph for."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        n = default
    return max(1, min(MAX_CONTROL_POINTS, n))


def cp_location(i, spread=DEFAULT_SPREAD):
    """Where control point i starts life, in the HOST'S OWN SPACE.

    ALL OF THEM ON THE HOST by default - 0,0,0. With a spread they lay out in
    rows of eight rather than one long line, so forty-one of them is still
    something you can see without zooming out to the horizon."""
    if i <= 0 or not spread:
        return (0.0, 0.0, 0.0)
    j = i - 1
    return (spread * (j % ROW + 1), spread * (j // ROW), 0.0)


def cp_display_size(i):
    """Nested crosses, so a stack of them at one point is still pickable."""
    if i <= 0:
        return ROOT_SIZE
    return max(MIN_SIZE, STEP_SIZE - (i - 1) * 0.35)


def key_at_rest(cp, frame=None, rotation=False):
    """Put ONE location keyframe on a control point where it stands.

    WHY THIS IS ON BY DEFAULT. An effect is authored by MOVING control points,
    and in Blender you cannot record a movement onto a channel that does not
    exist yet - you move the empty, press record, and nothing is captured
    until you have manually keyed a starting pose. One key at rest means the
    channel is already there: turn on auto-key, scrub, drag, done.

    ⚠️ AND IT IS A REAL TRADE, WHICH IS WHY IT CAN BE TURNED OFF. A keyed
    empty is no longer free to move: drag it with auto-key off, scrub one
    frame, and it snaps back to the key. That is correct behaviour and it
    surprises people, so it is a choice rather than a silent default.

    Rotation is NOT keyed unless asked for. Control point rotation matters -
    `speed_in_local_coordinate_system` is rotated into the CP's frame - but
    most effects never turn one, and an unused channel on every empty is
    clutter in the dope sheet."""
    if frame is None:
        try:
            frame = bpy.context.scene.frame_start
        except Exception:
            frame = 1
    try:
        cp.keyframe_insert(data_path="location", frame=frame)
        if rotation:
            cp.keyframe_insert(data_path="rotation_euler", frame=frame)
        return True
    except Exception as exc:
        print(f"[HT_CP]  could not key {cp.name}: {exc}")
        return False


def spawn(prefix, count, root=None, collection=None,
          spread=DEFAULT_SPREAD, indices=None, keyframe=False,
          keyframe_rotation=False, frame=None):
    """Create (or re-find) `count` control point empties. Returns the list.

    ONE CALL PER EFFECT, not per system - see the note at the top of this file.

    prefix      naming - "<prefix> · CP0", "<prefix> · CP1", ...
    root        the effect's control empty; they are parented to it, in its
                own space, and every system's host sits at that same origin
    collection  where they live in the outliner
    indices     which CP numbers the effect actually REFERENCES. Control points
                are dense from 0, so we still create 0..count-1 - this only
                marks the unused ones in the outliner, so you can see at a
                glance which empties matter and which are just holding the
                numbering together.
    """
    count = clamp_count(count)
    used = set(indices or range(count))
    out = []

    # every control point hangs off the TRANSFORM empty, not the root
    # directly - one handle moves them all while the effect stays put
    xform = transform_root(prefix, root, collection) if root is not None \
        else None

    for i in range(count):
        name = f"{prefix} · CP{i}"
        cp = bpy.data.objects.get(name)
        if cp is None:
            cp = bpy.data.objects.new(name, None)
        elif cp.type != "EMPTY":
            # something else already owns the name. Take a new one rather than
            # quietly wiring the effect to a mesh someone was using
            cp = bpy.data.objects.new(name, None)

        #CP0 is the one nearly every operator reads, so it doesn't look like
        #the other forty
        cp.empty_display_type = "ARROWS" if i == 0 else "PLAIN_AXES"
        cp.empty_display_size = cp_display_size(i)
        cp.location = cp_location(i, spread)
        cp["htp_control_point"] = i
        cp["htp_referenced"] = i in used

        if collection is not None:
            for c in list(cp.users_collection):
                c.objects.unlink(cp)
            collection.objects.link(cp)

        if xform is not None and cp is not xform:
            cp.parent = xform
            # the location above is already in the root's space (the
            # transform sits at the root's origin), so the parent inverse
            # must be identity - otherwise Blender bakes in whatever the
            # transform happened to be and CP0 stops sitting on it.
            cp.matrix_parent_inverse.identity()

        # AFTER parenting and placing, never before: a keyframe records the
        # location as it's at the moment it's inserted
        if keyframe:
            key_at_rest(cp, frame=frame, rotation=keyframe_rotation)

        out.append(cp)

    return out


def describe(count, indices=None):
    """One line for a report line or an operator's INFO message."""
    count = clamp_count(count)
    if not indices:
        return f"{count} control point{'s' if count != 1 else ''}"
    gaps = [i for i in range(count) if i not in set(indices)]
    s = f"{count} control point{'s' if count != 1 else ''}"
    if gaps:
        s += f" ({len(gaps)} unreferenced, kept so the numbering stays dense)"
    return s
