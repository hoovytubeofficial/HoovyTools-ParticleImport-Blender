# =============================================================================
#  tools/ras_system.py  -  the top-level RENDER ANIMATED SPRITES system
# =============================================================================
#
#  Wires every operator group from ras_nodes.py into one modifier whose panels
#  are SFM's own sections:
#
#      CONTROL POINTS · SYSTEM PROPERTIES · RENDERER · EMITTER
#      INITIALIZER · OPERATOR · FORCE GENERATOR · CONSTRAINT · CHILDREN
#
#  Every operator has its own ENABLE toggle, and switching one off falls back
#  to a fixed value rather than breaking the chain.
#
#  TWO EMITTERS, ONE GRAPH DOWNSTREAM
#  ----------------------------------
#  "SIMULATION" (default) remembers particles in a Simulation Zone. A particle
#  is real geometry created at the control point's position ON THE FRAME IT WAS
#  BORN, and it is never recomputed - so position memory is free and a moving
#  emitter stops dragging its own past around behind it. Play from frame 1.
#
#  "STATELESS" is the original ring of recycled slots. Every particle's whole
#  life is derived from the clock, so you can scrub backwards and it stays
#  correct - but it cannot remember where a control point USED to be.
#
#  Only the emitter and the base position differ. Every operator group is a
#  pure function of age, particle id, lifetime and the control points, so all
#  of them are shared, unchanged, between the two paths.
# =============================================================================

from . import ras_spec as spec
from . import control_points as cpmod
from .sprite_nodes import _group, _nd, _lk, _sv, note, set_structure
from .ras_nodes import EPS  # noqa: F401  (kept so the constant lives in one place)


MAXP = "Max Particles [SFM: max_particles]"
CAMSRC = "Camera Source [NOT SFM: 0 active · 1 socket · 2 viewport]"
ROPE_HALF = "Half Width [NOT SFM]"
ROPE_OFFSET = "Texture Offset [NOT SFM]"

# CHILDREN. Neither is an SFM field: in SFM a child is a child because it sits
# inside its parent's definition, and there is nothing to point AT. Here the
# two systems are two objects, so the child has to be told which object its
# parent is - and what its parent's renderer left behind to read.
PARENT_OBJ = "Parent System [NOT SFM: the parent's host object]"
PARENT_FROM = ("Parent Particles From "
               "[NOT SFM: 0 instances · 1 points · 2 vertices]")

# How many control points a system gets when nobody says otherwise. Real .pcf
# import passes the count read out of the file. Four is a STARTING POINT, not a
# limit: 8% of TF2 wants more, and one system wants forty-one.
DEFAULT_CONTROL_POINTS = 4

# The five fields every SFM operator carries, in the order the envelope
# group takes them.
ENV_FIELDS = ("Start Fade In", "End Fade In", "Start Fade Out",
              "End Fade Out", "Fade Oscillate")

# Which operators start switched ON. Everything else defaults to on because a
# freshly built system should show you something.
OFF_BY_DEFAULT = ("Velocity Random", "Movement Lock to Control Point",
                  "random force", "Rotation Yaw Flip Random",
                  "Velocity Noise", "emit_instantaneously",
                  "Pull towards control point", "twist around axis",
                  # A system is not a child until you hand it a parent, and
                  # switched on with an empty Parent socket it would look
                  # broken rather than idle.
                  "Position From Parent Particles",
                  # 🔴 AN OPERATOR THAT CHANGES THE PICTURE MUST NOT ARRIVE
                  # SWITCHED ON. Color Fade's default target is WHITE, so
                  # every hand-built system quietly washed out over its first
                  # second and the tint test went from red to blank. A .pcf
                  # import switches on exactly what the FILE lists; anything
                  # else is the builder inventing authoring nobody asked for.
                  "Alpha Fade and Decay", "Color Fade",
                  # 🔴 IT DECIDES WHERE EVERY PARTICLE IS BORN. On by default
                  # it quietly dragged particles a fraction of the way towards
                  # CP1 in a system that had never heard of a path - caught
                  # measuring something else entirely, as a "pull towards
                  # control point" that still moved with the force set to
                  # zero.
                  "Position Along Path Sequential",
                  # 🔴 IT DECIDES WHERE EVERY PARTICLE MAY GO. A constraint
                  # switched on by default would leash systems that never
                  # authored one; the importer enables what the file lists.
                  "Constrain distance to path between two control points",
                  # Squishes every card it touches - importer-enabled only.
                  "Rotation Yaw Random",
                  # Same reason as its path sibling.
                  "Constrain distance to control point",
                  # 🔴 SETTERS MUST NOT ARRIVE SWITCHED ON. Maintain Path
                  # would pin every particle to CP0 (start = end = 0), and
                  # the Remap would overwrite every radius with its 0..1
                  # default range. The Simple fades would add a fade nobody
                  # authored. A .pcf import switches ON exactly what the
                  # file lists.
                  "Movement Maintain Position Along Path",
                  "Remap Distance to Control Point to Scalar",
                  "Alpha Fade In Simple", "Alpha Fade Out Simple")

# Which operators this build can genuinely run more than one of, and how the
# instances combine. See ras_spec.DUPLICATED_IN_THE_WILD for how often real
# files actually do it.
STACKABLE = {
    "Lifetime Random": spec.LAST_WINS,
    "Radius Random": spec.LAST_WINS,
    "Alpha Random": spec.LAST_WINS,
    "Color Random": spec.LAST_WINS,
    "Rotation Random": spec.LAST_WINS,
    "Sequence Random": spec.LAST_WINS,
    "Position Within Sphere Random": spec.ADD,
    "Position Modify Offset Random": spec.ADD,
    "Velocity Random": spec.ADD,
    "Velocity Noise": spec.ADD,
    # N continuous streams sum into the one carry integrator - each instance
    # gates its own rate (start, duration, envelope) and the rates ADD.
    "emit_continuously": spec.ADD,
    "emit_instantaneously": spec.ADD,
    "Pull towards control point": spec.ADD,
    "twist around axis": spec.ADD,
    "Radius Scale": spec.CHAIN,
    "Rotation Spin Roll": spec.ADD,
    "random force": spec.ADD,
    # A second fade simply takes the first one's output as its input.
    "Alpha Fade In Random": spec.CHAIN,
    "Alpha Fade Out Random": spec.CHAIN,
    "Alpha Fade In Simple": spec.CHAIN,
    "Alpha Fade Out Simple": spec.CHAIN,
    "Alpha Fade and Decay": spec.CHAIN,
    "Color Fade": spec.CHAIN,
    # Chained remaps: each SETS its field when its field id matches, so the
    # last one targeting the same field wins and different fields coexist.
    "Remap Distance to Control Point to Scalar": spec.CHAIN,
}


def _lp(ng, pair, b, bi):
    """Link a (node, output index) pair into b's input bi."""
    _lk(ng, pair[0], pair[1], b, bi)


def _si(node, name, out=False):
    """Resolve a simulation-zone socket BY NAME.

    The zone's sockets do not line up: the Simulation OUTPUT node's inputs are
    [Skip, Geometry, ...state] while its outputs are [Geometry, ...state], and
    the INPUT node's outputs lead with [Delta Time, Geometry, ...]. Counting
    them by hand puts geometry one socket out and the renderer silently
    receives a float. Probed in Blender 5.2, resolved by name regardless."""
    coll = node.outputs if out else node.inputs
    i = coll.find(name)
    if i < 0:
        print(f"[HT_RAS]  simulation socket {name!r} not found on {node.name}")
    return i


def build_system(name, mat, sequences, cols, rows, groups,
                 emitter="SIMULATION", stack=None,
                 renderer="ANIMATED_SPRITES",
                 cp_count=DEFAULT_CONTROL_POINTS, rects=None):
    # HOW MANY CONTROL POINTS THIS SYSTEM HAS IS AN ARGUMENT, not a constant.
    # It used to be four everywhere, which silently made every reference above
    # CP3 unreachable - and the corpus has systems asking for 5, 10, 11, 35 and
    # 41. The graph is generated for the count, and every "control point
    # number" socket is clamped to it.
    cp_count = cpmod.clamp_count(cp_count, DEFAULT_CONTROL_POINTS)
    ng = _group(name, "GeometryNodeTree")
    set_structure(ng.interface.new_socket(
        "Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry"))
    set_structure(ng.interface.new_socket(
        "Geometry", in_out="INPUT", socket_type="NodeSocketGeometry"))

    sim = (emitter or "SIMULATION").upper() == "SIMULATION"
    rope = (renderer or "ANIMATED_SPRITES").upper() == "ROPE"
    trail = (renderer or "").upper() == "SPRITE_TRAIL"
    # Which renderer's fields the shared sprite-sheet maths reads. A rope has
    # no sheet at all; the other two both do, and both call the field
    # "animation rate" - but they are different sockets on different
    # operators, and taking the wrong one silently animates nothing.
    rend_op = "render_sprite_trail" if trail else "render_animated_sprites"
    if rope and not sim:
        # A rope is a TRAIL - it is threaded through particles in birth order,
        # and the stateless ring has no birth order to thread. Say so rather
        # than draw a tangle.
        print("[HT_RAS]  render_rope needs the SIMULATION emitter "
              "(the stateless ring has no birth order to thread) - "
              "switching to it.")
        sim = True

    # DOUBLE-FOLDED UI: an SFM SECTION panel, and inside it one sub-panel per
    # operator. new_panel() has no parent argument, so panels are created flat
    # and then re-homed with interface.move_to_parent().
    P = {}

    #  EVERY PANEL STARTS CLOSED. The modifier then opens as a short list of
    #  section titles - CONTROL POINTS, EMITTER, OPERATOR... - and the reader
    #  opens the one they came for, instead of scrolling past every field of
    #  every operator to find it.
    def panel(title, closed=True, parent=None):
        pn = ng.interface.new_panel(title, default_closed=closed)
        if parent is not None:
            try:
                ng.interface.move_to_parent(pn, P[parent], 0)
            except Exception as exc:
                print(f"[HT_RAS]  panel {title} under {parent}: {exc}")
        P[title] = pn
        return pn

    def sk(title, sname, stype, default=None, smin=None, smax=None):
        s = ng.interface.new_socket(sname, in_out="INPUT", socket_type=stype)
        set_structure(s)
        try:
            ng.interface.move_to_parent(s, P[title], 0)
        except Exception as exc:
            print(f"[HT_RAS]  socket {sname} into {title}: {exc}")
        if default is not None:
            try:
                s.default_value = default
            except Exception:
                pass
        for a, v in (("min_value", smin), ("max_value", smax)):
            if v is not None:
                try:
                    setattr(s, a, v)
                except Exception:
                    pass

    panel("CONTROL POINTS")
    for i in range(cp_count):
        sk("CONTROL POINTS", f"Control Point {i}", "NodeSocketObject")
    sk("CONTROL POINTS", "Camera", "NodeSocketObject")
    # NOT an SFM field - SFM has one camera and never has to ask.
    #   0 active camera (default)   1 the socket above   2 the viewport
    sk("CONTROL POINTS", CAMSRC, "NodeSocketInt", 0, smin=0, smax=2)

    panel("SYSTEM PROPERTIES")
    sk("SYSTEM PROPERTIES", MAXP, "NodeSocketInt", 200, smin=1)
    # 1.0 ON PURPOSE. Internal particle space IS Hammer units - 1 Blender Unit
    # = 1 SFM unit - so operator parameters are never multiplied by 0.01905
    # on the way in. Turning metres on is a DISPLAY choice, made once, by the
    # person looking at it next to a human-scale character.
    sk("SYSTEM PROPERTIES", "Scale", "NodeSocketFloat", 1.0, smin=0.0)
    sk("SYSTEM PROPERTIES", "Seed", "NodeSocketInt", 0)
    #  THE EFFECT'S OWN TIMELINE. Everything in this graph runs on SECONDS
    #  (Scene Time's seconds output), so the scene frame rate - 24, 30, 60 -
    #  never changes the effect. These two remap scene seconds into effect
    #  seconds:
    #      effect time = (scene seconds - Time Offset) x Time Scale
    #  Offset delays the whole effect (the import dialog's Start Time lands
    #  here); Scale is the slow-motion knob - 0.5 runs at half speed, 0
    #  freezes. ⚠️ A CONSTANT, not a curve: keyframing it warps the clock
    #  the maths derives everything from.
    sk("SYSTEM PROPERTIES", "Time Offset", "NodeSocketFloat", 0.0)
    sk("SYSTEM PROPERTIES", "Time Scale", "NodeSocketFloat", 1.0, smin=0.0)
    #  NOT SFM - the low-GPU stand-in: quarter-size cards, no material. The
    #  Developer tab's Proxy View button flips this on every built system at
    #  once; this socket is the per-system override.
    sk("SYSTEM PROPERTIES", "Proxy View", "NodeSocketBool", False)

    # ── one panel per OPERATOR INSTANCE, generated from the catalogue ─────
    #
    #  AN OPERATOR MAY APPEAR MORE THAN ONCE. In 97 TF2 packs, 30 different
    #  operators do - two emit_continuously, three Velocity Noises, six Remap
    #  Initial Scalars. So the modifier is not a fixed list of panels: it is
    #  generated from `stack`, a count per operator, and each instance gets its
    #  own panel, its own ENABLE toggle and its own copy of every field
    #  INCLUDING the five envelope fields. That last part is the point - two
    #  Velocity Noises are only useful because they can fade in and out at
    #  different times.
    #
    #  count 0 means the operator is not in this system at all, which is what
    #  importing a real .pcf mostly needs.
    counts = {op: 1 for op in spec.OPERATORS}
    # One renderer per system. The other's panel would only be a control that
    # does nothing.
    counts["render_rope"] = 1 if rope else 0
    counts["render_sprite_trail"] = 1 if trail else 0
    counts["render_animated_sprites"] = 0 if (rope or trail) else 1
    # Trail Length Random only means anything to a trail: it sets how many
    # SECONDS of travel the streak stands for. On any other renderer it would
    # be a panel that does nothing.
    counts["Trail Length Random"] = 1 if trail else 0
    for op, n in (stack or {}).items():
        if op not in spec.OPERATORS:
            print(f"[HT_RAS]  unknown operator in stack: {op!r}")
            continue
        counts[op] = max(0, int(n))
        if counts[op] > 1 and op not in STACKABLE:
            print(f"[HT_RAS]  {op}: {counts[op]} instances requested but this "
                  f"build only combines one - the extra panels will appear "
                  f"and be ignored")

    SOCK = {}                    # (operator, display, instance) -> socket name

    def operator_panels(section):
        """One sub-panel per instance of every operator in this section."""
        for op, ospec in spec.OPERATORS.items():
            if ospec["section"] != section:
                continue
            for inst in range(1, counts[op] + 1):
                title = spec.panel_name(op, inst)
                panel(title, parent=section)
                sk(title, title, "NodeSocketBool", op not in OFF_BY_DEFAULT)
                for (disp, sfm, stype, dflt, lo, hi, _u) in \
                        spec.fields_for(op):
                    nm = spec.socket_name(disp, sfm, inst, op)
                    # A CONTROL POINT SOCKET'S CEILING BELONGS TO THE SYSTEM.
                    # The catalogue cannot know it - it is however many empties
                    # this effect was built with.
                    if spec.is_control_point_field(sfm):
                        hi = cp_count - 1
                    sk(title, nm, stype, dflt, lo, hi)
                    SOCK[(op, disp, inst)] = nm

    for section in ("RENDERER", "EMITTER", "INITIALIZER", "OPERATOR",
                    "FORCE GENERATOR"):
        panel(section)
        operator_panels(section)

    if rope:
        # NOT SFM. Source takes the ribbon's half-width from the particle
        # radius alone; this is a plain multiplier on top, so a trail can be
        # widened without touching Radius Random. Texture Offset is the same
        # kind of convenience - a real .pcf carries only the three fields
        # the spec lists.
        sk(spec.panel_name("render_rope"), ROPE_HALF, "NodeSocketFloat", 1.0,
           0.0, None)
        sk(spec.panel_name("render_rope"), ROPE_OFFSET, "NodeSocketFloat", 0.0)

    panel("CONSTRAINT", closed=True)
    operator_panels("CONSTRAINT")

    # ── CHILDREN ─────────────────────────────────────────────────────────
    #  1148 of 3574 systems in the corpus have children - a third of TF2. A
    #  child is a WHOLE system in its own right, so it is a second object with
    #  its own modifier; what makes it a child is that it is born on its
    #  parent's particles instead of on a control point.
    panel("CHILDREN", closed=True)
    sk("CHILDREN", PARENT_OBJ, "NodeSocketObject")
    sk("CHILDREN", PARENT_FROM, "NodeSocketInt", 0, 0, 2)
    operator_panels("CHILDREN")

    gi = _nd(ng, "NodeGroupInput", (-2800, 0))
    go = _nd(ng, "NodeGroupOutput", (3600, 0))
    IDX = {}
    for i, it in enumerate([x for x in ng.interface.items_tree
                            if getattr(x, "item_type", "") == "SOCKET"
                            and x.in_out == "INPUT"]):
        IDX[it.name] = i

    def g(n):
        return IDX[n]

    def gs(op, disp, inst=1):
        """A modifier socket, by operator and readable field name."""
        return IDX[SOCK[(op, disp, inst)]]

    def gon(op, inst=1):
        """This instance's ENABLE toggle."""
        return IDX[spec.panel_name(op, inst)]

    def n_of(op):
        return counts[op]

    # ── control points ───────────────────────────────────────────────────
    #  AS MANY AS THE SYSTEM ASKED FOR. They read down the screen in rows of
    #  eight and then step left, because forty-one of them in one column is a
    #  graph nobody can navigate.
    cps = []
    for i in range(cp_count):
        col, row = divmod(i, 8)
        oi = _nd(ng, "GeometryNodeObjectInfo",
                 (-2580 - col * 230, 700 - row * 190),
                 f"Control Point {i}", role="CONTROL POINTS",
                 transform_space="RELATIVE")
        _lk(ng, gi, g(f"Control Point {i}"), oi, 0)
        cps.append(oi)

    def cp_select(index_socket, out_idx, loc, label, kind="VECTOR"):
        """Pick one of CP0..CPn by number, with a chain of Switches.

        Returns ((node, output index), [nodes made]) - a PAIR, not a node,
        because with a single control point there is nothing to switch and the
        answer is Object Info's own output. Returning the bare node there
        would hand the caller output 0, which is the TRANSFORM MATRIX, not the
        location - a silent type change rather than an error."""
        if cp_count == 1:
            return (cps[0], out_idx), []
        prev, prev_out, nodes = cps[0], out_idx, []
        for i in range(1, cp_count):
            eq = _nd(ng, "FunctionNodeCompare",
                     (loc[0] - 200, loc[1] - i * 110), f"CP == {i}",
                     role="CONTROL POINTS", data_type="INT", operation="EQUAL")
            _lk(ng, gi, index_socket, eq, 0)
            _sv(eq, 1, i)
            sw = _nd(ng, "GeometryNodeSwitch", (loc[0], loc[1] - i * 55),
                     f"{label} {i}", role="CONTROL POINTS", input_type=kind)
            _lk(ng, eq, 0, sw, 0)
            _lk(ng, prev, prev_out, sw, 1)
            _lk(ng, cps[i], out_idx, sw, 2)
            prev, prev_out = sw, 0
            nodes += [eq, sw]
        return (prev, 0), nodes

    sphere_cp, n1 = cp_select(gs("Position Within Sphere Random", "Control Point"), 1, (-2100, 700),
                              "sphere CP")
    sphere_rot, n2 = cp_select(gs("Position Within Sphere Random", "Control Point"), 2, (-2100, 250),
                               "sphere CP rot", kind="ROTATION")
    lock_cp, n3 = cp_select(gs("Movement Lock to Control Point", "Control Point"), 1, (-2100, -200),
                            "lock CP")
    # Only the sprite renderer has an orientation control point. A rope's
    # facing comes from the camera along its whole length, and a trail's from
    # its own velocity - neither has the field in any real .pcf.
    if rope or trail:
        orient_rot, n4 = None, []
    else:
        orient_rot, n4 = cp_select(
            gs("render_animated_sprites", "Orientation Control Point"), 2,
            (-2100, -650), "orientation CP", kind="ROTATION")
    note(ng, "CONTROL POINTS  ·  what everything hangs off",
         "CONTROL POINTS", f"""
{cp_count} empties, exactly like SFM's CP0..CP{cp_count - 1}.

HOW MANY IS READ OUT OF THE FILE, not assumed. Four was hard-coded here for a
long time, which quietly made every reference above CP3 unreachable. Across
the 97 TF2 packs: 2917 systems need one control point, 279 need two, and the
tail runs 5, 10, 11, 35 and 41 - about 8% want more than four.

Operators refer to them BY NUMBER, so every "Control Point Number" socket runs
through a chain of Switches that picks the right one, and each of those
sockets is clamped to 0..{cp_count - 1}. The chain is as long as the count, which
is why the count is a build-time argument and not a runtime one.

Object Info reads them in RELATIVE space, so they are measured in the host
object's frame. THE EMPTIES ARE PARENTED TO THE HOST for exactly that reason:
unparented, moving the host moves the frame but not the empties, and the
effect slides the other way and stays pinned to the world origin.
""", cps + n1 + n2 + n3 + n4)

    scene_clock = _nd(ng, "GeometryNodeInputSceneTime", (-2580, -960),
                      "the clock", role="TIME")
    #  ── THE EFFECT'S OWN TIMELINE ────────────────────────────────────────
    #  Scene Time's SECONDS output (0) is what everything reads, which is
    #  why the frame rate never matters - 24 and 30 fps produce the same
    #  effect at the same second. Offset and Scale then remap scene seconds
    #  into effect seconds; every consumer below reads the remapped clock,
    #  so the whole closed-form graph slows, delays and freezes as one.
    t_off = _nd(ng, "ShaderNodeMath", (-2400, -960), "- time offset",
                role="TIME", operation="SUBTRACT")
    _lk(ng, scene_clock, 0, t_off, 0)
    _lk(ng, gi, g("Time Offset"), t_off, 1)
    clock = _nd(ng, "ShaderNodeMath", (-2220, -960), "x time scale",
                role="TIME", operation="MULTIPLY")
    _lk(ng, t_off, 0, clock, 0)
    _lk(ng, gi, g("Time Scale"), clock, 1)

    # =====================================================================
    #  EMITTER  -  the one place the two architectures differ
    # =====================================================================
    emitter_nodes = []

    if sim:
        # A particle's IDENTITY and BIRTH TIME are attributes stored on the
        # point when it was created. Everything else about it is recomputed
        # from that id every frame, so tweaking Radius or Lifetime in the
        # modifier still updates live without replaying the simulation.
        pid_read = _nd(ng, "GeometryNodeInputNamedAttribute", (-2100, -1000),
                       "particle_id [read]", role="EMITTER", data_type="INT")
        _sv(pid_read, 0, "particle_id")
        PID = (pid_read, 0)

        birth_read = _nd(ng, "GeometryNodeInputNamedAttribute",
                         (-2100, -1160), "birth_time [read]", role="EMITTER",
                         data_type="FLOAT")
        _sv(birth_read, 0, "birth_time")
        age_n = _nd(ng, "ShaderNodeMath", (-1880, -1080),
                    "age = now - birth_time", role="TIME",
                    operation="SUBTRACT")
        _lk(ng, clock, 0, age_n, 0)
        _lk(ng, birth_read, 0, age_n, 1)
        AGE = (age_n, 0)
        BIRTH = (birth_read, 0)
        # Points never move inside the zone, so Position IS the spawn point.
        spawn_pos = _nd(ng, "GeometryNodeInputPosition", (-2100, -1320),
                        "where it was born", role="EMITTER")
        SPAWN = (spawn_pos, 0)
        emitter_nodes += [pid_read, birth_read, age_n, spawn_pos]
    else:
        pts = _nd(ng, "GeometryNodePoints", (-2580, -1100),
                  "the particle ring", role="EMITTER")
        _lk(ng, gi, g(MAXP), pts, 0)
        idx = _nd(ng, "GeometryNodeInputIndex", (-2580, -1260), "slot number",
                  role="EMITTER")
        maxp = _nd(ng, "ShaderNodeMath", (-2380, -1260), "count as float",
                   role="EMITTER", operation="MAXIMUM")
        _lk(ng, gi, g(MAXP), maxp, 0)
        _sv(maxp, 1, 1.0)
        slot = _nd(ng, "ShaderNodeMath", (-2380, -1420), "slot as float",
                   role="EMITTER", operation="MULTIPLY")
        _lk(ng, idx, 0, slot, 0)
        _sv(slot, 1, 1.0)

        emit = _nd(ng, "GeometryNodeGroup", (-2100, -1100),
                   "emit_continuously", role="EMITTER")
        emit.node_tree = groups["emit"]
        _lk(ng, clock, 0, emit, 0)
        _lk(ng, slot, 0, emit, 1)
        _lk(ng, maxp, 0, emit, 2)
        _lk(ng, gi, gs("emit_continuously", "Emission Rate"), emit, 3)
        _lk(ng, gi, gs("emit_continuously", "Emission Start Time"), emit, 4)
        # THE LONGEST LIFETIME A PARTICLE CAN ACTUALLY ROLL. Random Value does
        # not care which way round Min and Max are - it happily returns values
        # up to whichever is LARGER. Feeding the emitter only "Lifetime Max"
        # meant that with Min 5 / Max 2 the ring was sized for two seconds
        # while particles rolled five-second lifetimes, so EVERY particle was
        # recycled at age 2 and vanished in mid-air. Take the real maximum.
        longest = _nd(ng, "ShaderNodeMath", (-2380, -1580),
                      "longest lifetime a particle can roll", role="EMITTER",
                      operation="MAXIMUM")
        _lk(ng, gi, gs("Lifetime Random", "Lifetime Min"), longest, 0)
        _lk(ng, gi, gs("Lifetime Random", "Lifetime Max"), longest, 1)
        _lk(ng, longest, 0, emit, 5)

        env_emit = _nd(ng, "GeometryNodeGroup", (-1820, -1320),
                       "emitter envelope, AT BIRTH", role="EMITTER")
        env_emit.node_tree = groups["envelope"]
        _lk(ng, emit, 0, env_emit, 0)
        for i, nm in enumerate(ENV_FIELDS):
            _lk(ng, gi, gs("emit_continuously", nm), env_emit, i + 1)
        was_on = _nd(ng, "FunctionNodeCompare", (-1600, -1320),
                     "was the emitter on then?", role="EMITTER",
                     data_type="FLOAT", operation="GREATER_THAN")
        _lk(ng, env_emit, 0, was_on, 0)
        _sv(was_on, 1, 0.0)
        emit_on = _nd(ng, "GeometryNodeSwitch", (-1400, -1320),
                      "emitter enabled?", role="EMITTER",
                      input_type="BOOLEAN")
        _lk(ng, gi, gon("emit_continuously"), emit_on, 0)
        _sv(emit_on, 1, False)
        _lk(ng, was_on, 0, emit_on, 2)
        started = _nd(ng, "FunctionNodeBooleanMath", (-1200, -1320),
                      "and has it started?", role="EMITTER", operation="AND")
        _lk(ng, emit_on, 0, started, 0)
        _lk(ng, emit, 3, started, 1)

        AGE, PID = (emit, 1), (emit, 2)
        BIRTH = (emit, 0)
        spawn_pos = _nd(ng, "GeometryNodeInputPosition", (-2100, -1500),
                        "spawn point", role="EMITTER")
        SPAWN = (spawn_pos, 0)
        emitter_nodes += [spawn_pos, pts, idx, maxp, slot, longest, emit,
                          env_emit,
                          was_on, emit_on, started]

    # ── initializers - identical either way, all pure functions of the id ──
    #
    #  STACKING. Every operator is built once PER INSTANCE and the instances
    #  are then folded together by the rule in STACKABLE:
    #
    #    LAST_WINS  an initializer WRITES its field, so the last instance is
    #               the value the particle keeps - but only if it is ENABLED,
    #               so the fold goes through a Switch on that instance's own
    #               toggle rather than blindly taking the last one
    #    ADD        contributions sum, which is already how Velocity Random
    #               stacks on top of the sphere's outward velocity
    #
    #  Every instance also has its own ENVELOPE, and that is what makes two of
    #  the same operator worth having: two velocity operators fading in and out
    #  at different times are two different gusts, not one louder one.

    def _in(node, sname):
        """A group node's input socket BY NAME.

        Adding one socket to a group shifts every index after it, and the
        graph keeps building happily while quietly feeding the particle id in
        where Scale belonged. Never count these."""
        i = node.inputs.find(sname)
        if i < 0:
            print(f"[HT_RAS]  {node.label}: no input {sname!r}")
        return i

    initializer_nodes = []

    def envelope_for(op, inst, loc):
        """Every operator instance drives its own envelope from its own five
        fields. Runs on the particle's AGE, so a fade releases each particle
        at the same point in its own life rather than all at once."""
        e = _nd(ng, "GeometryNodeGroup", loc,
                f"{spec.panel_name(op, inst)} envelope", role="OPERATOR")
        e.node_tree = groups["envelope"]
        _lp(ng, AGE, e, 0)
        for i, nm in enumerate(ENV_FIELDS):
            _lk(ng, gi, gs(op, nm, inst), e, i + 1)
        return e


    seed_nodes = {}

    def seed_for(inst):
        """Instance 2 must NOT roll the same numbers as instance 1.

        Same particle id + same salt + same seed = identical values, which
        would make a second copy of an operator completely pointless - two
        Velocity Noises would be one Velocity Noise twice as loud. Each
        instance therefore gets its own offset into the random stream."""
        if inst == 1:
            return (gi, g("Seed"))
        if inst not in seed_nodes:
            y = 1100 - inst * 90
            a = _nd(ng, "ShaderNodeMath", (-1560, y),
                    f"seed for instance {inst}", role="INITIALIZER",
                    operation="ADD")
            _lk(ng, gi, g("Seed"), a, 0)
            _sv(a, 1, float(inst * 7919))
            b = _nd(ng, "FunctionNodeFloatToInt", (-1380, y),
                    role="INITIALIZER")
            _lk(ng, a, 0, b, 0)
            initializer_nodes.extend([a, b])
            seed_nodes[inst] = (b, 0)
        return seed_nodes[inst]

    def fold(op, nodes, kind="FLOAT"):
        """Combine one operator's instances down to a single value."""
        if not nodes:
            return None
        rule = STACKABLE.get(op, spec.LAST_WINS)
        out = nodes[0]
        for inst, nxt in enumerate(nodes[1:], start=2):
            x, y = nxt.location[0] + 240, nxt.location[1]
            if rule == spec.ADD:
                f = _nd(ng, "ShaderNodeVectorMath" if kind == "VECTOR"
                        else "ShaderNodeMath", (x, y),
                        f"+ {spec.panel_name(op, inst)}", role="INITIALIZER",
                        operation="ADD")
                _lk(ng, out, 0, f, 0)
                _lk(ng, nxt, 0, f, 1)
            else:
                f = _nd(ng, "GeometryNodeSwitch", (x, y),
                        f"{spec.panel_name(op, inst)} overrides?",
                        role="INITIALIZER", input_type=kind)
                _lk(ng, gi, gon(op, inst), f, 0)
                _lk(ng, out, 0, f, 1)
                _lk(ng, nxt, 0, f, 2)
            initializer_nodes.append(f)
            out = f
        return out

    # key in `groups`, operator, Min/Max/Exponent/Base/Fallback field names
    RANDOMS = (
        ("lifetime", "Lifetime Random", 900, "Lifetime Min", "Lifetime Max",
         "Lifetime Exponent", None, "Lifetime Min", "FLOAT"),
        ("radius", "Radius Random", 700, "Radius Min", "Radius Max",
         "Radius Exponent", None, "Radius Min", "FLOAT"),
        ("alpha", "Alpha Random", 500, "Alpha Min", "Alpha Max",
         "Alpha Exponent", None, "Alpha Max", "FLOAT"),
        ("color", "Color Random", 300, "Color 1", "Color 2",
         None, None, "Color 1", "RGBA"),
        ("rotation", "Rotation Random", 100, "Roll Offset Min",
         "Roll Offset Max", "Roll Exponent", "Roll Initial",
         "Roll Offset Min", "FLOAT"),
    )

    folded = {}
    for key, op, row, mn, mx, exp, base, fb, kind in RANDOMS:
        made = []
        for inst in range(1, n_of(op) + 1):
            n = _nd(ng, "GeometryNodeGroup",
                    (-1200 + (inst - 1) * 240, row),
                    spec.panel_name(op, inst), role="INITIALIZER")
            n.node_tree = groups[key]
            _lk(ng, gi, gon(op, inst), n, _in(n, "Enable"))
            _lk(ng, gi, gs(op, mn, inst), n, _in(n, "Min"))
            _lk(ng, gi, gs(op, mx, inst), n, _in(n, "Max"))
            if exp:
                _lk(ng, gi, gs(op, exp, inst), n, _in(n, "Exponent"))
            if base:
                _lk(ng, gi, gs(op, base, inst), n, _in(n, "Base"))
            _lk(ng, gi, gs(op, fb, inst), n, _in(n, "Fallback"))
            _lp(ng, PID, n, _in(n, "ID"))
            _lp(ng, seed_for(inst), n, _in(n, "Seed"))
            made.append(n)
            initializer_nodes.append(n)
        folded[op] = fold(op, made, kind)

    life = folded["Lifetime Random"]
    radius = folded["Radius Random"]
    alpha = folded["Alpha Random"]
    colour = folded["Color Random"]
    roll = folded["Rotation Random"]

    # ── INITIALIZER · Trail Length Random ────────────────────────────────
    #  SECONDS of travel, drawn once at birth like every other initializer.
    #  The renderer turns it into units by multiplying the particle's speed.
    trail_len = None
    if n_of("Trail Length Random") and groups.get("trail_length") is not None:
        op = "Trail Length Random"
        tl = _nd(ng, "GeometryNodeGroup", (-1200, -1600),
                 spec.panel_name(op), role="INITIALIZER")
        tl.node_tree = groups["trail_length"]
        _lk(ng, gi, gon(op), tl, _in(tl, "Enable"))
        _lk(ng, gi, gs(op, "Length Min"), tl, _in(tl, "Min"))
        _lk(ng, gi, gs(op, "Length Max"), tl, _in(tl, "Max"))
        _lk(ng, gi, gs(op, "Length Exponent"), tl, _in(tl, "Exponent"))
        _lk(ng, gi, gs(op, "Length Min"), tl, _in(tl, "Fallback"))
        _lp(ng, PID, tl, _in(tl, "ID"))
        _lk(ng, gi, g("Seed"), tl, _in(tl, "Seed"))
        trail_len = tl
        initializer_nodes.append(tl)

    seq_made = []
    for inst in range(1, n_of("Sequence Random") + 1):
        n = _nd(ng, "GeometryNodeGroup", (-1200 + (inst - 1) * 240, -100),
                spec.panel_name("Sequence Random", inst), role="INITIALIZER")
        n.node_tree = groups["sequence"]
        _lk(ng, gi, gon("Sequence Random", inst), n, _in(n, "Enable"))
        _lk(ng, gi, gs("Sequence Random", "Sequence Min", inst),
            n, _in(n, "Sequence Min"))
        _lk(ng, gi, gs("Sequence Random", "Sequence Max", inst),
            n, _in(n, "Sequence Max"))
        _sv(n, _in(n, "Sequence Count"), len(sequences))
        _lp(ng, PID, n, _in(n, "ID"))
        _lp(ng, seed_for(inst), n, _in(n, "Seed"))
        seq_made.append(n)
        initializer_nodes.append(n)
    seq = fold("Sequence Random", seq_made, "INT")

    cp_euler = _nd(ng, "FunctionNodeRotationToEuler", (-1400, -560),
                   "CP rotation as euler", role="INITIALIZER")
    _lp(ng, sphere_rot, cp_euler, 0)

    sphere_made = []
    for inst in range(1, n_of("Position Within Sphere Random") + 1):
        n = _nd(ng, "GeometryNodeGroup", (-1200 + (inst - 1) * 240, -420),
                spec.panel_name("Position Within Sphere Random", inst),
                role="INITIALIZER")
        n.node_tree = groups["sphere"]
        op = "Position Within Sphere Random"
        _lk(ng, gi, gon(op, inst), n, _in(n, "Enable"))
        for nm in ("Distance Min", "Distance Max", "Distance Bias",
                   "Speed Min", "Speed Max", "Speed Exponent",
                   "Local Speed Min", "Local Speed Max"):
            _lk(ng, gi, gs(op, nm, inst), n, _in(n, nm))
        _lk(ng, cp_euler, 0, n, _in(n, "CP Rotation"))
        _lk(ng, gi, g("Scale"), n, _in(n, "Scale"))
        _lp(ng, PID, n, _in(n, "ID"))
        _lp(ng, seed_for(inst), n, _in(n, "Seed"))
        sphere_made.append(n)
        initializer_nodes.append(n)
    sphere = sphere_made[0] if sphere_made else None

    # ── INITIALIZER · Position Modify Offset Random ──────────────────────
    #  THE GLOBAL SPAWN NUDGE, and the most-used operator this importer used
    #  to drop on the floor - over a thousand systems in this library carry
    #  one. It ADDS onto the sphere placement below, which is exactly how
    #  SFM stacks position initializers. Local Space turns the nudge with
    #  the sphere's control point frame (a separate control_point_number is
    #  8-uses rare and reported instead of built).
    offset_made = []
    op_off = "Position Modify Offset Random"
    for inst in range(1, n_of(op_off) + 1):
        n = _nd(ng, "GeometryNodeGroup", (-1200 + (inst - 1) * 240, -560),
                spec.panel_name(op_off, inst), role="INITIALIZER")
        n.node_tree = groups["offset"]
        _lk(ng, gi, gon(op_off, inst), n, _in(n, "Enable"))
        _lk(ng, gi, gs(op_off, "Offset Min", inst), n, _in(n, "Offset Min"))
        _lk(ng, gi, gs(op_off, "Offset Max", inst), n, _in(n, "Offset Max"))
        _lk(ng, gi, gs(op_off, "Local Space", inst), n, _in(n, "Local Space"))
        _lk(ng, cp_euler, 0, n, _in(n, "CP Rotation"))
        _lk(ng, gi, g("Scale"), n, _in(n, "Scale"))
        _lp(ng, PID, n, _in(n, "ID"))
        _lp(ng, seed_for(inst), n, _in(n, "Seed"))
        offset_made.append(n)
        initializer_nodes.append(n)

    # Several position initializers ADD their offsets - stacked sphere
    # placements first, then every global offset nudge - the same way SFM
    # stacks them.
    pos_total = None
    for i, n in enumerate(sphere_made + offset_made):
        if pos_total is None:
            pos_total = (n, 0)
            continue
        a = _nd(ng, "ShaderNodeVectorMath", (-980 + i * 200, -300),
                "+ spawn offset", role="INITIALIZER", operation="ADD")
        _lp(ng, pos_total, a, 0)
        _lk(ng, n, 0, a, 1)
        pos_total = (a, 0)
        initializer_nodes.append(a)

    # ── INITIALIZER  ·  Position Along Path Sequential ───────────────────
    #  THE BEAM-MAKER, and the one position initializer that is a SETTER: it
    #  does not offset the particle from its control point, it puts the
    #  particle at an absolute place on the line between TWO of them. So it
    #  arrives at the spawn origin rather than in the offset pile below.
    #  TWO OPERATORS SHARE THE CURVE. Position Along Path Sequential SETS the
    #  spot once at birth; Movement Maintain Position Along Path HOLDS the
    #  particle there for its whole life. In this build both read the live
    #  control point empties every evaluation, so the initializer already
    #  behaves like "maintain" whenever the empties move - one group serves
    #  both, they only differ in which sockets feed it.
    path_pos = None
    #  🔴 CHOSEN FROM THE FILE'S STACK, NOT FROM THE PANEL COUNT - every
    #  catalogue operator gets a panel whether the file uses it or not, so
    #  counting panels always found "both" and bound the path switch to the
    #  Sequential toggle, which defaults OFF: an authored Maintain drove
    #  nothing and the beam collapsed onto CP0. When the file carries both,
    #  Maintain wins - it is the per-frame holder, so it has the last word.
    _in_stack = [o for o in ("Movement Maintain Position Along Path",
                             "Position Along Path Sequential",
                             "Position Along Path Random")
                 if (stack or {}).get(o)]
    op_path = _in_stack[0] if _in_stack else "Position Along Path Sequential"
    if len(_in_stack) > 1:
        print(f"[HT_RAS]  {len(_in_stack)} path operators in this system - "
              f"{op_path!r} places the particles; the other panels are inert")
    if groups.get("path_seq") is not None:
        start_disp = ("Control Point"
                      if op_path == "Position Along Path Sequential"
                      else "Start Control Point")
        p_start, np1 = cp_select(gs(op_path, start_disp), 1,
                                 (-2100, -1000), "path start CP")
        p_srot, np2 = cp_select(gs(op_path, start_disp), 2,
                                (-2100, -1150), "path start CP rot",
                                kind="ROTATION")
        p_end, np3 = cp_select(gs(op_path, "End Control Point"), 1,
                               (-2100, -1300), "path end CP")
        p_erot, np4 = cp_select(gs(op_path, "End Control Point"), 2,
                                (-2100, -1450), "path end CP rot",
                                kind="ROTATION")
        s_eul = _nd(ng, "FunctionNodeRotationToEuler", (-1750, -1150),
                    "start CP rotation as euler", role="INITIALIZER")
        _lp(ng, p_srot, s_eul, 0)
        e_eul = _nd(ng, "FunctionNodeRotationToEuler", (-1750, -1450),
                    "end CP rotation as euler", role="INITIALIZER")
        _lp(ng, p_erot, e_eul, 0)

        pth = _nd(ng, "GeometryNodeGroup", (-1500, -1200),
                  spec.panel_name(op_path), role="INITIALIZER")
        pth.node_tree = groups["path_seq"]
        _lk(ng, gi, gon(op_path), pth, _in(pth, "Enable"))
        _lp(ng, p_start, pth, _in(pth, "Start"))
        _lp(ng, p_end, pth, _in(pth, "End"))
        _lk(ng, s_eul, 0, pth, _in(pth, "Start Rotation"))
        _lk(ng, e_eul, 0, pth, _in(pth, "End Rotation"))
        rolled = op_path == "Position Along Path Random"
        for disp, sock in (("Particles To Map", "Particles To Map"),
                           ("Bulge", "Bulge"),
                           ("Bulge Control", "Bulge Control"),
                           ("Mid Point Position", "Mid Point"),
                           ("Max Distance", "Max Distance")):
            if rolled and disp == "Particles To Map":
                continue            # rolled per particle - nothing to count
            _lk(ng, gi, gs(op_path, disp), pth, _in(pth, sock))
        _sv(pth, _in(pth, "Random Fraction"), rolled)
        _lk(ng, gi, g("Scale"), pth, _in(pth, "Scale"))
        _lp(ng, PID, pth, _in(pth, "ID"))
        _lk(ng, gi, g("Seed"), pth, _in(pth, "Seed"))
        path_pos = (pth, 0)
        initializer_nodes += [s_eul, e_eul, pth] + np1 + np2 + np3 + np4
        if n_of(op_path) > 1:
            print(f"[HT_RAS]  {op_path}: {n_of(op_path)} instances requested "
                  f"but a path is a POSITION, not an offset - the extra "
                  f"panels appear and only the first one places anything")

    # ── CHILDREN  ·  Position From Parent Particles ──────────────────────
    #  This is the operator that turns a system into a CHILD: it replaces the
    #  control point the particle would have been born on with one of the
    #  PARENT'S living particles. Everything else - the sphere offset, the
    #  velocity initializers, the whole operator stack - is unchanged and
    #  simply happens around that new origin, which is exactly how SFM stacks
    #  a child's own initializers on top of where it was placed.
    parent_pos = parent_vel = child_on = None
    child_nodes = []
    op_child = "Position From Parent Particles"
    if n_of(op_child) and groups.get("parent_pos") is not None:
        pinfo = _nd(ng, "GeometryNodeObjectInfo", (-1700, -1660),
                    "the parent system", role="EMITTER",
                    transform_space="RELATIVE")
        # RELATIVE, so the parent's particles arrive measured in THIS host's
        # frame - the same frame our own control points are read in. Read in
        # world space they would be out by the host's transform.
        _lk(ng, gi, g(PARENT_OBJ), pinfo, 0)
        pf = _nd(ng, "GeometryNodeGroup", (-1440, -1660), op_child,
                 role="EMITTER")
        pf.node_tree = groups["parent_pos"]
        _lk(ng, gi, gon(op_child), pf, _in(pf, "Enable"))
        _lk(ng, pinfo, 4, pf, _in(pf, "Parent"))
        _lk(ng, gi, g(PARENT_FROM), pf, _in(pf, "Read From"))
        _lk(ng, gi, gs(op_child, "Random Parent Distribution"),
            pf, _in(pf, "Random"))
        _lk(ng, gi, gs(op_child, "Inherited Velocity Scale"),
            pf, _in(pf, "Velocity Scale"))
        _lp(ng, PID, pf, _in(pf, "ID"))
        _lk(ng, gi, g("Seed"), pf, _in(pf, "Seed"))
        _lk(ng, envelope_for(op_child, 1, (-1700, -1860)), 0,
            pf, _in(pf, "Strength"))
        parent_pos, parent_vel, child_on = (pf, 0), (pf, 1), (pf, 2)
        child_nodes += [pinfo, pf]

    def spawn_origin(loc):
        """Where a particle is born: its control point, a parent particle, or
        a place on a path between two control points.

        The parent switch is on the operator's own "Has Parent" output rather
        than on its ENABLE toggle, so a system with the operator switched on
        but no parent object assigned falls back to the control point instead
        of piling every particle on the origin.

        ⚠️ A PATH BEATS BOTH, because it is the only one of the three that
        names an absolute place rather than a starting point to be offset
        from. The glows on a laser are CHILDREN that also run a path: born on
        the beam's particles they would smear along it, and the file says
        exactly where it wants them."""
        made = []
        base, extra = (sphere_cp, [])
        if child_on is not None:
            sw = _nd(ng, "GeometryNodeSwitch", loc,
                     "control point, or a parent particle", role="EMITTER",
                     input_type="VECTOR")
            _lp(ng, child_on, sw, 0)
            _lp(ng, sphere_cp, sw, 1)
            _lp(ng, parent_pos, sw, 2)
            child_nodes.append(sw)
            base, made = (sw, 0), [sw]
        if path_pos is not None:
            pw = _nd(ng, "GeometryNodeSwitch", (loc[0] + 180, loc[1] - 120),
                     "...or a place on the path", role="INITIALIZER",
                     input_type="VECTOR")
            _lk(ng, gi, gon(op_path), pw, 0)
            _lp(ng, base, pw, 1)
            _lp(ng, path_pos, pw, 2)
            initializer_nodes.append(pw)
            base, made = (pw, 0), made + [pw]
        return base, made

    note(ng, "INITIALIZER  ·  decided once, at birth", "INITIALIZER", """
Every one of these takes the PARTICLE ID, so its value is fixed for that
particle's whole life and never changes while it is alive.

Each has its own ENABLE toggle. Switched off it returns a fixed fallback
rather than dropping out of the graph, so disabling something can never break
the chain downstream.

AN OPERATOR MAY APPEAR MORE THAN ONCE, and these are built one node per
INSTANCE. A setter (lifetime, radius, alpha, colour, roll, sequence) folds
LAST-ENABLED-WINS through a Switch on each later instance's own toggle; a
contribution (sphere position, velocity) folds by ADDING. Each instance also
carries its own envelope, which is the whole reason two of the same operator
is worth having.

WHY THESE ARE RECOMPUTED RATHER THAN STORED. With the simulation emitter it
would be easy to bake every one of these into an attribute at birth. They are
deliberately left as pure functions of the id so that dragging Radius Max in
the modifier updates particles that are ALREADY IN THE AIR, instead of forcing
a replay from frame 1 to see any change. Only the things that genuinely cannot
be recomputed - when a particle was born, and where - are stored.

VALUES ARE IN SFM'S OWN UNITS. Roll is DEGREES (a full turn is 360, not 1 and
not 6.283); alpha is 0..255. Each socket carries the exact .pcf attribute name
in brackets, so importing a real effect is a lookup rather than a translation.
""", initializer_nodes + [cp_euler])

    # ── velocity: sphere + Velocity Random, then Movement Basic ──────────
    vel_parts = [(n, 1) for n in sphere_made]         # each sphere's Velocity

    # INHERITED VELOCITY joins the same ADD chain as every other velocity
    # initializer, because that is what it is.
    #
    # 🔴 WITH THE SIMULATION EMITTER IT IS READ BACK FROM AN ATTRIBUTE, not
    # sampled live. The parent particle a child was born on will eventually
    # die, and the index then lands on somebody else - so sampling every frame
    # would rewrite a child's launch velocity in mid-flight, and its whole
    # closed-form trajectory with it. It is captured once, at birth, exactly
    # like lock_cp_birth. A missing attribute reads as zero, so nothing needs
    # initialising.
    #
    # The stateless ring has no memory to capture it into, so there it is
    # sampled live - the same known limitation that makes that path follow a
    # moving control point around.
    if child_on is not None:
        if sim:
            inh = _nd(ng, "GeometryNodeInputNamedAttribute", (-1200, -1660),
                      "inherit_velocity [read]", role="INITIALIZER",
                      data_type="FLOAT_VECTOR")
            _sv(inh, 0, "inherit_velocity")
            vel_parts.append((inh, 0))
            child_nodes.append(inh)
        else:
            vel_parts.append(parent_vel)
    velrnd_made = []
    for inst in range(1, n_of("Velocity Random") + 1):
        n = _nd(ng, "GeometryNodeGroup", (-1200 + (inst - 1) * 240, -700),
                spec.panel_name("Velocity Random", inst), role="INITIALIZER")
        n.node_tree = groups["velocity"]
        op = "Velocity Random"
        _lk(ng, gi, gon(op, inst), n, _in(n, "Enable"))
        if sphere is not None:
            _lk(ng, sphere, 0, n, _in(n, "Direction"))   # outward direction
        _lk(ng, gi, gs(op, "Random Speed Min", inst), n, _in(n, "Speed Min"))
        _lk(ng, gi, gs(op, "Random Speed Max", inst), n, _in(n, "Speed Max"))
        _lk(ng, gi, gs(op, "Local Speed Min", inst), n, _in(n, "Local Speed Min"))
        _lk(ng, gi, gs(op, "Local Speed Max", inst), n, _in(n, "Local Speed Max"))
        _lk(ng, cp_euler, 0, n, _in(n, "CP Rotation"))
        _lk(ng, gi, g("Scale"), n, _in(n, "Scale"))
        _lp(ng, PID, n, _in(n, "ID"))
        _lp(ng, seed_for(inst), n, _in(n, "Seed"))
        velrnd_made.append(n)
        vel_parts.append((n, 0))

    # INITIALIZER - Velocity Noise. Sampled at the SPAWN position and SPAWN
    # time, so it is fixed at birth and joins this chain like any other
    # velocity initializer - no simulation state, no integration.
    noise_made = []
    for inst in range(1, n_of("Velocity Noise") + 1):
        vn = _nd(ng, "GeometryNodeGroup", (-1200 + (inst - 1) * 240, -1300),
                 spec.panel_name("Velocity Noise", inst), role="INITIALIZER")
        vn.node_tree = groups["velocity_noise"]
        op = "Velocity Noise"
        _lk(ng, gi, gon(op, inst), vn, _in(vn, "Enable"))
        _lp(ng, SPAWN, vn, _in(vn, "Spawn Position"))
        _lp(ng, BIRTH, vn, _in(vn, "Birth Time"))
        for nm in ("Spatial Scale", "Spatial Offset", "Time Scale",
                   "Time Offset", "Output Min", "Output Max", "Absolute",
                   "Invert Absolute"):
            _lk(ng, gi, gs(op, nm, inst), vn, _in(vn, nm))
        _lk(ng, envelope_for(op, inst,
                             (-1200 + (inst - 1) * 240, -1500)),
            0, vn, _in(vn, "Strength"))
        noise_made.append(vn)
        vel_parts.append((vn, 0))

    vel_total = None
    for i, (node, out_idx) in enumerate(vel_parts):
        if vel_total is None:
            vel_total = (node, out_idx)
            continue
        a = _nd(ng, "ShaderNodeVectorMath", (-980 + i * 200, -700 - i * 60),
                "+ velocity", role="INITIALIZER", operation="ADD")
        _lp(ng, vel_total, a, 0)
        _lk(ng, node, out_idx, a, 1)
        vel_total = (a, 0)

    # ── FORCE GENERATOR - random force
    # A constant per-particle acceleration
    # is exactly what gravity is, so the forces are summed onto the gravity
    # vector and inherit the drag treatment for nothing.
    grav = (gi, gs("Movement Basic", "Gravity"))
    force_nodes = []
    for inst in range(1, n_of("random force") + 1):
        f = _nd(ng, "GeometryNodeGroup", (-1200 + (inst - 1) * 240, -1000),
                spec.panel_name("random force", inst), role="OPERATOR")
        f.node_tree = groups["random_force"]
        _lk(ng, gi, gon("random force", inst), f, _in(f, "Enable"))
        _lk(ng, gi, gs("random force", "Min Force", inst),
            f, _in(f, "Min Force"))
        _lk(ng, gi, gs("random force", "Max Force", inst),
            f, _in(f, "Max Force"))
        _lp(ng, PID, f, _in(f, "ID"))
        _lp(ng, seed_for(inst), f, _in(f, "Seed"))
        _lk(ng, envelope_for("random force", inst,
                             (-1200 + (inst - 1) * 240, -1200)),
            0, f, _in(f, "Strength"))
        a = _nd(ng, "ShaderNodeVectorMath", (-960 + inst * 200, -1000),
                "gravity + force", role="OPERATOR", operation="ADD")
        _lp(ng, grav, a, 0)
        _lk(ng, f, 0, a, 1)
        grav = (a, 0)
        force_nodes += [f, a]

    move = _nd(ng, "GeometryNodeGroup", (-760, -700), "Movement Basic",
               role="OPERATOR")
    move.node_tree = groups["movement"]
    _lk(ng, gi, gon("Movement Basic"), move, _in(move, "Enable"))
    if vel_total is not None:
        _lp(ng, vel_total, move, _in(move, "Velocity"))
    _lp(ng, grav, move, _in(move, "Gravity"))
    _lk(ng, gi, gs("Movement Basic", "Drag"), move, _in(move, "Drag"))
    _lp(ng, AGE, move, _in(move, "Age"))
    _lk(ng, gi, g("Scale"), move, _in(move, "Scale"))

    # ── alive / dead ─────────────────────────────────────────────────────
    alive = _nd(ng, "FunctionNodeCompare", (760, -320), "age < lifetime",
                role="OPERATOR", data_type="FLOAT", operation="LESS_THAN")
    _lp(ng, AGE, alive, 0)
    _lk(ng, life, 0, alive, 1)

    # =====================================================================
    #  THE SIMULATION ZONE  -  who exists, and where they were born
    # =====================================================================
    if sim:
        sim_in = _nd(ng, "GeometryNodeSimulationInput", (-1820, -1700),
                     "last frame", role="EMITTER")
        sim_out = _nd(ng, "GeometryNodeSimulationOutput", (500, -1700),
                      "this frame", role="EMITTER")
        while len(sim_out.state_items):
            sim_out.state_items.remove(sim_out.state_items[-1])
        item = sim_out.state_items.new("GEOMETRY", "Geometry")
        try:
            item.attribute_domain = "POINT"
        except Exception:
            pass
        sim_out.state_items.new("FLOAT", "Emission Carry")
        sim_out.state_items.new("INT", "Next ID")
        try:
            sim_in.pair_with_output(sim_out)
        except Exception as exc:
            print(f"[HT_RAS]  simulation pairing failed: {exc}")

        SI_GEO = _si(sim_in, "Geometry", out=True)
        SI_DT = _si(sim_in, "Delta Time", out=True)
        SI_CARRY = _si(sim_in, "Emission Carry", out=True)
        SI_NEXT = _si(sim_in, "Next ID", out=True)

        #  DELTA TIME RIDES THE SAME TIMELINE AS THE CLOCK. Everything that
        #  integrates per frame - the emission carry, bursts, birth-time
        #  backdating, the position-dependent forces - must see EFFECT
        #  seconds, or Time Scale would slow the ages while the emitter and
        #  forces kept running at full speed.
        dt_eff = _nd(ng, "ShaderNodeMath", (-1780, -2140),
                     "dt x time scale", role="TIME", operation="MULTIPLY")
        _lk(ng, sim_in, SI_DT, dt_eff, 0)
        _lk(ng, gi, g("Time Scale"), dt_eff, 1)
        DT = (dt_eff, 0)

        # how many are already alive - the cap needs to know
        alive_n = _nd(ng, "GeometryNodeAttributeDomainSize", (-1600, -1900),
                      "how many exist right now", role="EMITTER",
                      component="POINTCLOUD")
        _lk(ng, sim_in, SI_GEO, alive_n, 0)

        # ── EMIT_CONTINUOUSLY, ONE INSTANCE PER PANEL ────────────────────
        #  🔴 EVERY INSTANCE EMITS, not just the first. A .pcf may carry two
        #  or three emit_continuously operators (19 TF2 systems do) - each
        #  with its own start time, duration, rate and envelope. N emitters
        #  feeding one carry integrator is mathematically the SAME as one
        #  emitter whose rate is the sum of the per-instance gated rates:
        #
        #      carry += ( Σ rate_i x started_i x within_i x envelope_i ) x dt
        #
        #  so each instance gates its own rate and the sum drives the one
        #  emit_sim group. Enable / Start Time / Envelope on the group stay at
        #  their pass-through defaults - all the gating already happened.
        #
        #  EMISSION DURATION: 0 means FOREVER, and so does anything negative
        #  (real files use -1). Only a POSITIVE duration is a deadline. This
        #  socket existed for a long time and drove nothing, which read as
        #  "the field is broken".
        rate_total = None
        for e_inst in range(1, n_of("emit_continuously") + 1):
            ey = -1440 - (e_inst - 1) * 460
            e_op = "emit_continuously"
            since_i = _nd(ng, "ShaderNodeMath", (-1780, ey),
                          "time since this emitter started", role="TIME",
                          operation="SUBTRACT")
            _lk(ng, clock, 0, since_i, 0)
            _lk(ng, gi, gs(e_op, "Emission Start Time", e_inst), since_i, 1)
            #  ⚠️ THE ENVELOPE RUNS ON SYSTEM TIME, not time-since-this-
            #  emitter. SFM's fade times are "raw seconds since the particle
            #  SYSTEM started" - a jet flame's third emitter authors start
            #  0.25 AND fadein 0.25, meaning the same instant. Feeding it
            #  since-start shifted every later instance's envelope past its
            #  own emission window and it emitted nothing at all.
            env_i = _nd(ng, "GeometryNodeGroup", (-1600, ey),
                        f"envelope · {spec.panel_name(e_op, e_inst)}",
                        role="EMITTER")
            env_i.node_tree = groups["envelope"]
            _lk(ng, clock, 0, env_i, 0)
            for i, nm in enumerate(ENV_FIELDS):
                _lk(ng, gi, gs(e_op, nm, e_inst), env_i, i + 1)

            started_i = _nd(ng, "FunctionNodeCompare", (-1600, ey - 120),
                            "has it started?", role="EMITTER",
                            data_type="FLOAT", operation="GREATER_EQUAL")
            _lk(ng, since_i, 0, started_i, 0)
            _sv(started_i, 1, 0.0)
            dur_off = _nd(ng, "FunctionNodeCompare", (-1780, ey - 220),
                          "duration 0 or less = forever", role="EMITTER",
                          data_type="FLOAT", operation="LESS_EQUAL")
            _lk(ng, gi, gs(e_op, "Emission Duration", e_inst), dur_off, 0)
            _sv(dur_off, 1, EPS)
            within = _nd(ng, "FunctionNodeCompare", (-1780, ey - 340),
                         "still inside the window?", role="EMITTER",
                         data_type="FLOAT", operation="LESS_THAN")
            _lk(ng, since_i, 0, within, 0)
            _lk(ng, gi, gs(e_op, "Emission Duration", e_inst), within, 1)
            still = _nd(ng, "FunctionNodeBooleanMath", (-1600, ey - 280),
                        "forever, or not finished yet", role="EMITTER",
                        operation="OR")
            _lk(ng, dur_off, 0, still, 0)
            _lk(ng, within, 0, still, 1)
            live = _nd(ng, "FunctionNodeBooleanMath", (-1460, ey - 200),
                       "enabled AND still emitting", role="EMITTER",
                       operation="AND")
            _lk(ng, gi, gon(e_op, e_inst), live, 0)
            _lk(ng, still, 0, live, 1)
            live2 = _nd(ng, "FunctionNodeBooleanMath", (-1460, ey - 100),
                        "...AND started", role="EMITTER", operation="AND")
            _lk(ng, live, 0, live2, 0)
            _lk(ng, started_i, 0, live2, 1)

            r1 = _nd(ng, "ShaderNodeMath", (-1330, ey),
                     "rate x envelope", role="EMITTER", operation="MULTIPLY")
            _lk(ng, gi, gs(e_op, "Emission Rate", e_inst), r1, 0)
            _lk(ng, env_i, 0, r1, 1)
            r2 = _nd(ng, "ShaderNodeMath", (-1330, ey - 140),
                     "x on/off", role="EMITTER", operation="MULTIPLY")
            _lk(ng, r1, 0, r2, 0)
            _lk(ng, live2, 0, r2, 1)
            emitter_nodes += [since_i, env_i, started_i, dur_off, within,
                              still, live, live2, r1, r2]
            if rate_total is None:
                rate_total = (r2, 0)
            else:
                a = _nd(ng, "ShaderNodeMath", (-1240, ey - 40),
                        "+ another stream", role="EMITTER", operation="ADD")
                _lp(ng, rate_total, a, 0)
                _lk(ng, r2, 0, a, 1)
                rate_total = (a, 0)
                emitter_nodes.append(a)

        emit = _nd(ng, "GeometryNodeGroup", (-1180, -1700),
                   "emit_continuously", role="EMITTER")
        emit.node_tree = groups["emit_sim"]
        # Enable / Start Time / Envelope stay at their defaults (True / 0 /
        # 1): the per-instance gating above already decided who emits when.
        _lk(ng, clock, 0, emit, 1)
        _lp(ng, DT, emit, 2)
        if rate_total is not None:
            _lp(ng, rate_total, emit, 4)
        _lk(ng, sim_in, SI_CARRY, emit, 6)
        _lk(ng, alive_n, 0, emit, 7)
        _lk(ng, gi, g(MAXP), emit, 8)

        # EMITTER - emit_instantaneously. Its burst is added BEFORE the cap,
        # so a 2000-particle burst under a 200 cap gives 200 and the rest are
        # never born rather than queued for later.
        burst_total, burst_nodes = None, []
        for inst in range(1, n_of("emit_instantaneously") + 1):
            b = _nd(ng, "GeometryNodeGroup", (-1400, -1900 - inst * 200),
                    spec.panel_name("emit_instantaneously", inst),
                    role="EMITTER")
            b.node_tree = groups["emit_instant"]
            op = "emit_instantaneously"
            _lk(ng, gi, gon(op, inst), b, _in(b, "Enable"))
            _lk(ng, clock, 0, b, _in(b, "Time"))
            _lp(ng, DT, b, _in(b, "Delta Time"))
            _lk(ng, gi, gs(op, "Emission Start Time", inst),
                b, _in(b, "Start Time"))
            _lk(ng, gi, gs(op, "Num To Emit Min", inst), b, _in(b, "Count Min"))
            _lk(ng, gi, gs(op, "Num To Emit", inst), b, _in(b, "Count Max"))
            # Two bursts in one system must not roll the same size, so each
            # instance takes its own offset into the random stream.
            _lp(ng, seed_for(inst), b, _in(b, "Seed"))
            burst_nodes.append(b)
            if burst_total is None:
                burst_total = (b, 0)
            else:
                a = _nd(ng, "ShaderNodeMath", (-1200, -1900 - inst * 200),
                        "+ another burst", role="EMITTER", operation="ADD")
                _lp(ng, burst_total, a, 0)
                _lk(ng, b, 0, a, 1)
                burst_total = (a, 0)
                burst_nodes.append(a)
        if burst_total is not None:
            _lp(ng, burst_total, emit, _in(emit, "Extra This Frame"))
        emitter_nodes += burst_nodes

        # ── the particles born on this frame ─────────────────────────────
        born = _nd(ng, "GeometryNodePoints", (-960, -1700),
                   "born this frame", role="EMITTER")
        _lk(ng, emit, 0, born, 0)
        born_idx = _nd(ng, "GeometryNodeInputIndex", (-960, -1900),
                       "which one of them", role="EMITTER")

        # particle_id: a serial number that never repeats, so every particle
        # rolls its own random values and no two ever share them.
        pid_new = _nd(ng, "ShaderNodeMath", (-760, -1900),
                      "next id + index", role="EMITTER", operation="ADD")
        _lk(ng, sim_in, SI_NEXT, pid_new, 0)
        _lk(ng, born_idx, 0, pid_new, 1)
        pid_i = _nd(ng, "FunctionNodeFloatToInt", (-580, -1900),
                    "as an id", role="EMITTER", rounding_mode="FLOOR")
        _lk(ng, pid_new, 0, pid_i, 0)
        store_pid = _nd(ng, "GeometryNodeStoreNamedAttribute", (-380, -1700),
                        "particle_id  (POINT)", role="EMITTER",
                        data_type="INT", domain="POINT")
        _sv(store_pid, 2, "particle_id")
        _lk(ng, born, 0, store_pid, 0)
        _lk(ng, pid_i, 0, store_pid, 3)

        next_out = _nd(ng, "ShaderNodeMath", (-380, -2080),
                       "next id += count", role="EMITTER", operation="ADD")
        _lk(ng, sim_in, SI_NEXT, next_out, 0)
        _lk(ng, emit, 0, next_out, 1)

        # BIRTH TIME, SPREAD ACROSS THE FRAME. All the particles born on one
        # frame would otherwise share an age exactly, and a stream emitted at
        # 200/s would come out as visible clumps one frame apart instead of a
        # continuous jet. The last one born is stamped with the current time,
        # the rest are backdated evenly across the frame just gone.
        n_safe = _nd(ng, "ShaderNodeMath", (-960, -2260), "count, never zero",
                     role="EMITTER", operation="MAXIMUM")
        _lk(ng, emit, 0, n_safe, 0)
        _sv(n_safe, 1, 1.0)
        last = _nd(ng, "ShaderNodeMath", (-760, -2260), "count - 1",
                   role="EMITTER", operation="SUBTRACT")
        _lk(ng, emit, 0, last, 0)
        _sv(last, 1, 1.0)
        back = _nd(ng, "ShaderNodeMath", (-580, -2260), "how far back",
                   role="EMITTER", operation="SUBTRACT")
        _lk(ng, last, 0, back, 0)
        _lk(ng, born_idx, 0, back, 1)
        frac = _nd(ng, "ShaderNodeMath", (-400, -2260), "as a fraction",
                   role="EMITTER", operation="DIVIDE")
        _lk(ng, back, 0, frac, 0)
        _lk(ng, n_safe, 0, frac, 1)
        offs = _nd(ng, "ShaderNodeMath", (-220, -2260), "x delta time",
                   role="TIME", operation="MULTIPLY")
        _lk(ng, frac, 0, offs, 0)
        _lp(ng, DT, offs, 1)
        birth_t = _nd(ng, "ShaderNodeMath", (-40, -2260),
                      "birth = now - that", role="TIME", operation="SUBTRACT")
        _lk(ng, clock, 0, birth_t, 0)
        _lk(ng, offs, 0, birth_t, 1)

        store_birth = _nd(ng, "GeometryNodeStoreNamedAttribute",
                          (-160, -1700), "birth_time  (POINT)", role="EMITTER",
                          data_type="FLOAT", domain="POINT")
        _sv(store_birth, 2, "birth_time")
        _lk(ng, store_pid, 0, store_birth, 0)
        _lk(ng, birth_t, 0, store_birth, 3)

        # WHERE THE LOCK'S CONTROL POINT WAS AT BIRTH. This is the whole fix
        # for "particles follow CP0 even with the lock switched off": you
        # cannot ask a geometry node where an empty USED to be, so the answer
        # is written down on the frame it was still true.
        store_lockcp = _nd(ng, "GeometryNodeStoreNamedAttribute",
                           (60, -1700), "lock_cp_birth  (POINT)",
                           role="EMITTER", data_type="FLOAT_VECTOR",
                           domain="POINT")
        _sv(store_lockcp, 2, "lock_cp_birth")
        _lk(ng, store_birth, 0, store_lockcp, 0)
        _lp(ng, lock_cp, store_lockcp, 3)

        # WHAT THE PARENT PARTICLE WAS DOING WHEN THIS CHILD WAS BORN, written
        # down for the same reason as lock_cp_birth: the parent will die, and
        # then there is nobody left to ask.
        born_chain = store_lockcp
        if child_on is not None:
            store_inh = _nd(ng, "GeometryNodeStoreNamedAttribute",
                            (160, -1700), "inherit_velocity  (POINT)",
                            role="EMITTER", data_type="FLOAT_VECTOR",
                            domain="POINT")
            _sv(store_inh, 2, "inherit_velocity")
            _lk(ng, store_lockcp, 0, store_inh, 0)
            _lp(ng, parent_vel, store_inh, 3)
            born_chain = store_inh
            child_nodes.append(store_inh)

        # and finally put them where the emitter actually is, right now
        origin, _onodes = spawn_origin((-140, -2060))
        birth_pos = _nd(ng, "ShaderNodeVectorMath", (60, -1900),
                        "spawn origin + spawn offset", role="EMITTER",
                        operation="ADD")
        _lp(ng, origin, birth_pos, 0)
        if pos_total is not None:
            _lp(ng, pos_total, birth_pos, 1)
        place = _nd(ng, "GeometryNodeSetPosition", (360, -1700),
                    "born HERE, and it stays here", role="EMITTER")
        _lk(ng, born_chain, 0, place, 0)
        _lk(ng, birth_pos, 0, place, 2)

        join = _nd(ng, "GeometryNodeJoinGeometry", (300, -1500),
                   "everyone who already existed, plus the new ones",
                   role="EMITTER")
        _lk(ng, sim_in, SI_GEO, join, 0)
        _lk(ng, place, 0, join, 0)

        # =================================================================
        #  POSITION-DEPENDENT FORCES  -  the one place we integrate
        # =================================================================
        #
        #  Everything else here is a closed form: a pure function of age,
        #  exact at any frame rate. A force that depends on WHERE THE PARTICLE
        #  IS cannot be - the force moves the particle, which changes the
        #  force. So Pull towards control point and twist around axis are
        #  integrated per frame, and ONLY they are.
        #
        #  Two attributes carry the result, and they are a CORRECTION on top
        #  of the closed form rather than a replacement for it:
        #      force_velocity   velocity built up by these forces
        #      force_offset     how far that has moved the particle
        #
        #  So gravity, drag and the launch velocity stay exact, and only this
        #  correction is frame-rate dependent. A missing attribute reads as
        #  zero, so newly born points need no initialisation.
        fvel_read = _nd(ng, "GeometryNodeInputNamedAttribute", (300, -2100),
                        "force_velocity [read]", role="OPERATOR",
                        data_type="FLOAT_VECTOR")
        _sv(fvel_read, 0, "force_velocity")
        foff_read = _nd(ng, "GeometryNodeInputNamedAttribute", (300, -2260),
                        "force_offset [read]", role="OPERATOR",
                        data_type="FLOAT_VECTOR")
        _sv(foff_read, 0, "force_offset")

        pos_closed = _nd(ng, "ShaderNodeVectorMath", (520, -2100),
                         "birth + closed-form travel", role="OPERATOR",
                         operation="ADD")
        _lp(ng, SPAWN, pos_closed, 0)
        _lk(ng, move, 0, pos_closed, 1)
        pos_now = _nd(ng, "ShaderNodeVectorMath", (720, -2100),
                      "+ what the forces have done", role="OPERATOR",
                      operation="ADD")
        _lk(ng, pos_closed, 0, pos_now, 0)
        _lk(ng, foff_read, 0, pos_now, 1)

        accel = None
        force_nodes2 = [fvel_read, foff_read, pos_closed, pos_now]
        for inst in range(1, n_of("Pull towards control point") + 1):
            op = "Pull towards control point"
            cp_pull, cp_nodes = cp_select(gs(op, "Control Point", inst), 1,
                                          (700, -2400 - inst * 200),
                                          "pull CP " + str(inst))
            pl = _nd(ng, "GeometryNodeGroup", (960, -2400 - inst * 200),
                     spec.panel_name(op, inst), role="OPERATOR")
            pl.node_tree = groups["pull_cp"]
            _lk(ng, gi, gon(op, inst), pl, _in(pl, "Enable"))
            _lk(ng, pos_now, 0, pl, _in(pl, "Position"))
            _lp(ng, cp_pull, pl, _in(pl, "Control Point"))
            _lk(ng, gi, gs(op, "Amount", inst), pl, _in(pl, "Amount"))
            _lk(ng, gi, gs(op, "Falloff Power", inst), pl,
                _in(pl, "Falloff Power"))
            _lk(ng, envelope_for(op, inst, (700, -2500 - inst * 200)),
                0, pl, _in(pl, "Strength"))
            force_nodes2 += cp_nodes + [pl]
            if accel is None:
                accel = (pl, 0)
            else:
                a = _nd(ng, "ShaderNodeVectorMath",
                        (1180, -2400 - inst * 200), "+ pull",
                        role="OPERATOR", operation="ADD")
                _lp(ng, accel, a, 0)
                _lk(ng, pl, 0, a, 1)
                accel = (a, 0)
                force_nodes2.append(a)

        for inst in range(1, n_of("twist around axis") + 1):
            op = "twist around axis"
            tw = _nd(ng, "GeometryNodeGroup", (960, -3000 - inst * 200),
                     spec.panel_name(op, inst), role="OPERATOR")
            tw.node_tree = groups["twist_axis"]
            _lk(ng, gi, gon(op, inst), tw, _in(tw, "Enable"))
            _lk(ng, pos_now, 0, tw, _in(tw, "Position"))
            # No control_point_number field exists on this operator in any
            # real file, so the axis passes through control point 0.
            _lk(ng, cps[0], 1, tw, _in(tw, "Control Point"))
            _lk(ng, gi, gs(op, "Axis", inst), tw, _in(tw, "Axis"))
            _lk(ng, gi, gs(op, "Amount", inst), tw, _in(tw, "Amount"))
            _lk(ng, envelope_for(op, inst, (700, -3100 - inst * 200)),
                0, tw, _in(tw, "Strength"))
            force_nodes2.append(tw)
            if accel is None:
                accel = (tw, 0)
            else:
                a = _nd(ng, "ShaderNodeVectorMath",
                        (1180, -3000 - inst * 200), "+ twist",
                        role="OPERATOR", operation="ADD")
                _lp(ng, accel, a, 0)
                _lk(ng, tw, 0, a, 1)
                accel = (a, 0)
                force_nodes2.append(a)

        # v += a dt, then the SAME drag law as Movement Basic: a fraction kept
        # per 30 Hz tick, so k = 30 x drag.
        dv = _nd(ng, "ShaderNodeVectorMath", (1400, -2100), "a x dt",
                 role="OPERATOR", operation="SCALE")
        if accel is not None:
            _lp(ng, accel, dv, 0)
        _lp(ng, DT, dv, 3)
        v_plus = _nd(ng, "ShaderNodeVectorMath", (1600, -2100),
                     "velocity + that", role="OPERATOR", operation="ADD")
        _lk(ng, fvel_read, 0, v_plus, 0)
        _lk(ng, dv, 0, v_plus, 1)

        k30 = _nd(ng, "ShaderNodeMath", (1200, -2300), "30 x drag",
                  role="OPERATOR", operation="MULTIPLY")
        _lk(ng, gi, gs("Movement Basic", "Drag"), k30, 0)
        _sv(k30, 1, 30.0)
        k_dt = _nd(ng, "ShaderNodeMath", (1400, -2300), "x dt",
                   role="OPERATOR", operation="MULTIPLY")
        _lk(ng, k30, 0, k_dt, 0)
        _lp(ng, DT, k_dt, 1)
        keep = _nd(ng, "ShaderNodeMath", (1600, -2300), "1 - that",
                   role="OPERATOR", operation="SUBTRACT")
        _sv(keep, 0, 1.0)
        _lk(ng, k_dt, 0, keep, 1)
        keep_pos = _nd(ng, "ShaderNodeMath", (1800, -2300), "never negative",
                       role="OPERATOR", operation="MAXIMUM")
        _lk(ng, keep, 0, keep_pos, 0)
        _sv(keep_pos, 1, 0.0)
        v_new = _nd(ng, "ShaderNodeVectorMath", (1800, -2100), "after drag",
                    role="OPERATOR", operation="SCALE")
        _lk(ng, v_plus, 0, v_new, 0)
        _lk(ng, keep_pos, 0, v_new, 3)

        step = _nd(ng, "ShaderNodeVectorMath", (2000, -2100), "v x dt",
                   role="OPERATOR", operation="SCALE")
        _lk(ng, v_new, 0, step, 0)
        _lp(ng, DT, step, 3)
        off_new = _nd(ng, "ShaderNodeVectorMath", (2200, -2100),
                      "offset + that", role="OPERATOR", operation="ADD")
        _lk(ng, foff_read, 0, off_new, 0)
        _lk(ng, step, 0, off_new, 1)

        store_fvel = _nd(ng, "GeometryNodeStoreNamedAttribute", (2400, -1500),
                         "force_velocity  (POINT)", role="OPERATOR",
                         data_type="FLOAT_VECTOR", domain="POINT")
        _sv(store_fvel, 2, "force_velocity")
        _lk(ng, join, 0, store_fvel, 0)
        _lk(ng, v_new, 0, store_fvel, 3)
        store_foff = _nd(ng, "GeometryNodeStoreNamedAttribute", (2600, -1500),
                         "force_offset  (POINT)", role="OPERATOR",
                         data_type="FLOAT_VECTOR", domain="POINT")
        _sv(store_foff, 2, "force_offset")
        _lk(ng, store_fvel, 0, store_foff, 0)
        _lk(ng, off_new, 0, store_foff, 3)
        force_nodes2 += [dv, v_plus, k30, k_dt, keep, keep_pos, v_new, step,
                         off_new, store_fvel, store_foff]
        emitter_nodes += force_nodes2

        dead_sim = _nd(ng, "FunctionNodeBooleanMath", (300, -1900),
                       "past its lifetime", role="OPERATOR", operation="NOT")
        _lk(ng, alive, 0, dead_sim, 0)
        reap = _nd(ng, "GeometryNodeDeleteGeometry", (400, -1500),
                   "and remove the dead", role="OPERATOR", domain="POINT",
                   mode="ALL")
        _lk(ng, store_foff, 0, reap, 0)
        _lk(ng, dead_sim, 0, reap, 1)

        _lk(ng, reap, 0, sim_out, _si(sim_out, "Geometry"))
        _lk(ng, emit, 1, sim_out, _si(sim_out, "Emission Carry"))
        _lk(ng, next_out, 0, sim_out, _si(sim_out, "Next ID"))

        stream = (sim_out, _si(sim_out, "Geometry", out=True))

        # OUTSIDE the zone the points are still sitting exactly where they
        # were born, because nothing in the zone ever moved them. So the
        # birth position is simply Position - no attribute needed for it.
        base = _nd(ng, "GeometryNodeInputPosition", (760, -900),
                   "where it was born", role="OPERATOR")
        foff_out = _nd(ng, "GeometryNodeInputNamedAttribute", (760, -1060),
                       "force_offset [read]", role="OPERATOR",
                       data_type="FLOAT_VECTOR")
        _sv(foff_out, 0, "force_offset")
        base_plus = _nd(ng, "ShaderNodeVectorMath", (960, -900),
                        "birth + integrated forces", role="OPERATOR",
                        operation="ADD")
        _lk(ng, base, 0, base_plus, 0)
        _lk(ng, foff_out, 0, base_plus, 1)
        BASE = (base_plus, 0)

        lockcp_read = _nd(ng, "GeometryNodeInputNamedAttribute", (760, -1100),
                          "lock_cp_birth [read]", role="OPERATOR",
                          data_type="FLOAT_VECTOR")
        _sv(lockcp_read, 0, "lock_cp_birth")
        lock_delta = _nd(ng, "ShaderNodeVectorMath", (960, -1100),
                         "how far the lock CP has moved since", role="OPERATOR",
                         operation="SUBTRACT")
        _lp(ng, lock_cp, lock_delta, 0)
        _lk(ng, lockcp_read, 0, lock_delta, 1)
        LOCKREF = (lock_delta, 0)
        DEAD = None

        emitter_nodes += [sim_in, sim_out, alive_n, emit,
                          born, born_idx, pid_new, pid_i, store_pid, next_out,
                          n_safe, last, back, frac, offs, birth_t,
                          store_birth, store_lockcp, birth_pos, place, join,
                          dead_sim, reap] + child_nodes

        note(ng, "EMITTER  ·  a Simulation Zone remembers the particles",
             "EMITTER", """
THE IDEA, TAKEN FROM THE ROPE MODULE. You do not store "where the control
point was when this particle was born" as a NUMBER. You store the GEOMETRY,
created at the control point on that frame, and simply carry it forward. The
points are never recomputed, so position memory comes free.

    emit N points at the control point, this frame
      -> stamp particle_id, birth_time and lock_cp_birth on them
      -> join them to everyone who already existed
      -> delete anyone past their lifetime
      -> remember the rest

    age = scene time - birth_time

WHAT THIS DISSOLVES, all of which were real bugs in the ring:
  · the emitter dragging its own past around behind it - geometry stays
    where it was created, so a particle no longer teleports when CP0 moves
  · particles vanishing in mid-life - there is no recycling, so nothing can
    ever overwrite a live particle
  · Max Particles killing live particles - the cap gates EMISSION only

THE POINTS NEVER MOVE INSIDE THE ZONE. Movement Basic is applied downstream
of the Simulation Output, so what is remembered is always the BIRTH position.
That keeps the maths idempotent: re-evaluating a frame gives the same answer,
and drift cannot accumulate the way it does in a per-frame integration.

THE PRICE, and it is a real one: PLAY FROM FRAME 1. A simulation cannot be
scrubbed backwards into. Build the emitter as STATELESS if you need that -
Import VTF Sprite still uses the scrubbable path.
""", emitter_nodes)
    else:
        origin, _onodes = spawn_origin((-720, -880))
        base_pos = _nd(ng, "ShaderNodeVectorMath", (-520, -880),
                       "spawn origin + spawn offset", role="OPERATOR",
                       operation="ADD")
        _lp(ng, origin, base_pos, 0)
        if pos_total is not None:
            _lp(ng, pos_total, base_pos, 1)
        BASE = (base_pos, 0)
        LOCKREF = lock_cp
        stream = (pts, 0)
        emitter_nodes += child_nodes

        visible = _nd(ng, "FunctionNodeBooleanMath", (960, -320),
                      "alive AND emitted", role="OPERATOR", operation="AND")
        _lk(ng, alive, 0, visible, 0)
        _lk(ng, started, 0, visible, 1)
        DEAD = _nd(ng, "FunctionNodeBooleanMath", (1160, -320),
                   "so delete these", role="OPERATOR", operation="NOT")
        _lk(ng, visible, 0, DEAD, 0)
        emitter_nodes += [base_pos, visible, DEAD]

        note(ng, "EMITTER  ·  emit_continuously and its envelope", "EMITTER",
             """
The RING of slots lives in the emit_continuously group; open it to see how
birth times are laid out.

The ENVELOPE is evaluated AT EACH PARTICLE'S BIRTH TIME rather than at the
current time. That is the SFM behaviour: an emitter that fades out simply
stops producing NEW particles, while the ones already in the air finish their
lives normally.

"longest lifetime a particle can roll" is MAX(Lifetime Min, Lifetime Max), not
just Lifetime Max. Random Value ignores which way round the two are, so with
Min above Max particles roll lifetimes longer than the ring was sized for and
get recycled - and vanish - in mid-air.

THIS PATH CANNOT REMEMBER THE PAST. Every particle's life is derived from the
clock, which is what makes scrubbing backwards work, and it is also why the
unlocked branch measures from where the control point is NOW rather than from
where it was at birth. Use the SIMULATION emitter for anything driven by a
moving control point.
""", emitter_nodes)

    # =====================================================================
    #  POSITION  -  base + travel, optionally riding the lock control point
    # =====================================================================
    offset = _nd(ng, "ShaderNodeVectorMath", (1160, -700), "base + travel",
                 role="OPERATOR", operation="ADD")
    _lp(ng, BASE, offset, 0)
    _lk(ng, move, 0, offset, 1)

    env_lock = _nd(ng, "GeometryNodeGroup", (1160, -900), "lock envelope",
                   role="OPERATOR")
    env_lock.node_tree = groups["envelope"]
    _lp(ng, AGE, env_lock, 0)
    for i, nm in enumerate(ENV_FIELDS):
        _lk(ng, gi, gs("Movement Lock to Control Point", nm),
            env_lock, i + 1)

    lock = _nd(ng, "GeometryNodeGroup", (1400, -700),
               "Movement Lock to Control Point", role="OPERATOR")
    lock.node_tree = groups["lock"]
    _lk(ng, gi, gon("Movement Lock to Control Point"), lock, 0)
    _lk(ng, offset, 0, lock, 1)
    _lp(ng, LOCKREF, lock, 2)
    _lk(ng, env_lock, 0, lock, 3)

    if sim:
        final_pos = lock
    else:
        # The stateless path has no memory of where the CP was, so "unlocked"
        # has to mean "relative to where it is now".
        unlocked = _nd(ng, "ShaderNodeVectorMath", (1400, -940),
                       "spawn origin + offset", role="OPERATOR",
                       operation="ADD")
        _lp(ng, origin, unlocked, 0)
        _lk(ng, move, 0, unlocked, 1)
        final_pos = _nd(ng, "GeometryNodeSwitch", (1620, -800), "locked or not",
                        role="OPERATOR", input_type="VECTOR")
        _lk(ng, gi, gon("Movement Lock to Control Point"), final_pos, 0)
        _lk(ng, offset, 0, final_pos, 1)
        _lk(ng, lock, 0, final_pos, 2)

    setpos = _nd(ng, "GeometryNodeSetPosition", (1840, -300), "place it",
                 role="OPERATOR")
    _lp(ng, stream, setpos, 0)
    _lk(ng, final_pos, 0, setpos, 2)

    note(ng, "OPERATOR  ·  where the particle actually is", "OPERATOR", """
    position = base  +  Movement Basic( sphere velocity + Velocity Random,
                                        gravity, drag )

BASE is where the two emitters differ, and it is the whole point:

  SIMULATION  the position the point was created at, still sitting in the
              simulation zone untouched. The control point can wander off
              and the particle does not care, because nothing recomputes it.
  STATELESS   the sphere control point's position RIGHT NOW plus the spawn
              offset - so every particle silently follows the empty around,
              lock or no lock. That is the known limitation of that path.

THE LOCK rides the control point ON TOP of that. With the simulation emitter
it is fed the DISTANCE THE CONTROL POINT HAS MOVED SINCE THAT PARTICLE WAS
BORN, so locking is genuinely "come with me from here" rather than "teleport
onto the empty".

Velocity Random ADDS to the sphere's outward velocity rather than replacing
it, which is how SFM stacks initializers.

The lock's envelope runs on the particle's AGE, so a fade out releases every
particle at the same point in its own life rather than all at once.
""", velrnd_made + [move, offset, env_lock, lock, setpos, alive]
         + ([] if sim else [unlocked, final_pos]))

    # ── the sprite sheet  (ANIMATED SPRITES ONLY) ────────────────────────
    #
    #  A rope has no sheet: it is one continuous ribbon with a texture running
    #  along it, not a sequence of frames on a card. So the whole sequence
    #  table and the animation-rate maths are built only for the sprite
    #  renderer, and `tile` stays None - the sprite_frame attribute is simply
    #  not written.
    tile = tile_next = frame_frac = None
    if not rope:
        # ── sequence table ───────────────────────────────────────────────────
        s0, c0, l0 = sequences[0]
        st_n = _nd(ng, "ShaderNodeValue", (100, 980), "seq 0 start",
                   role="SEQUENCE")
        st_n.outputs[0].default_value = float(s0)
        ct_n = _nd(ng, "ShaderNodeValue", (100, 860), "seq 0 length",
                   role="SEQUENCE")
        ct_n.outputs[0].default_value = float(c0)
        lp_n = _nd(ng, "ShaderNodeValue", (100, 740),
                   f"seq 0 {'LOOPS' if l0 else 'plays once'}", role="SEQUENCE")
        lp_n.outputs[0].default_value = 1.0 if l0 else 0.0
        prev, seq_nodes = [st_n, ct_n, lp_n], [st_n, ct_n, lp_n]
        for i, (si, ci, li) in enumerate(sequences[1:], start=1):
            eq = _nd(ng, "FunctionNodeCompare", (300, 980 - i * 150),
                     f"sequence == {i}", role="SEQUENCE", data_type="INT",
                     operation="EQUAL")
            _lk(ng, seq, 0, eq, 0)
            _sv(eq, 1, i)
            picked = []
            for j, (val, lbl) in enumerate(((float(si), "start"),
                                            (float(ci), "length"),
                                            (1.0 if li else 0.0,
                                             "LOOPS" if li else "plays once"))):
                sw = _nd(ng, "GeometryNodeSwitch", (520, 980 - j * 120 - i * 40),
                         f"seq {i} {lbl}", role="SEQUENCE", input_type="FLOAT")
                _lk(ng, eq, 0, sw, 0)
                _lk(ng, prev[j], 0, sw, 1)
                _sv(sw, 2, val)
                picked.append(sw)
            seq_nodes += [eq] + picked
            prev = picked
        seq_start, seq_len, seq_loop = prev

        # ── animation rate ───────────────────────────────────────────────────
        # Only built where something reads it - see the note on `played`.
        frac_life = fit = None
        if not trail:
            frac_life = _nd(ng, "ShaderNodeMath", (760, 520), "age / lifetime",
                            role="RENDERER", operation="DIVIDE")
            _lp(ng, AGE, frac_life, 0)
            _lk(ng, life, 0, frac_life, 1)
            fit = _nd(ng, "ShaderNodeMath", (940, 520),
                      "whole sequence over the life", role="RENDERER",
                      operation="MULTIPLY")
            _lk(ng, frac_life, 0, fit, 0)
            _lk(ng, seq_len, 0, fit, 1)
        byrate = _nd(ng, "ShaderNodeMath", (760, 340), "age x animation rate",
                     role="RENDERER", operation="MULTIPLY")
        _lp(ng, AGE, byrate, 0)
        _lk(ng, gi, gs(rend_op, "Animation Rate"), byrate, 1)
        byrate2 = _nd(ng, "ShaderNodeMath", (940, 340), "x sequence length",
                      role="RENDERER", operation="MULTIPLY")
        _lk(ng, byrate, 0, byrate2, 0)
        _lk(ng, seq_len, 0, byrate2, 1)
        # animation_fit_lifetime is an ANIMATED SPRITES field. render_sprite_trail
        # has no such thing in any of its 484 uses - a trail plays at its rate
        # or not at all - so the switch is only built where the field exists.
        if trail:
            played = byrate2
        else:
            played = _nd(ng, "GeometryNodeSwitch", (1140, 420), "fit lifetime?",
                         role="RENDERER", input_type="FLOAT")
            _lk(ng, gi, gs("render_animated_sprites", "Fit Lifetime"),
                played, 0)
            _lk(ng, byrate2, 0, played, 1)
            _lk(ng, fit, 0, played, 2)
        floored = _nd(ng, "ShaderNodeMath", (1320, 420), "whole frames",
                      role="RENDERER", operation="FLOOR")
        _lk(ng, played, 0, floored, 0)
        lastf = _nd(ng, "ShaderNodeMath", (1320, 240), "length - 1",
                    role="SEQUENCE", operation="SUBTRACT")
        _lk(ng, seq_len, 0, lastf, 0)
        _sv(lastf, 1, 1.0)
        held = _nd(ng, "ShaderNodeMath", (1500, 500), "hold on the last frame",
                   role="SEQUENCE", operation="MINIMUM")
        _lk(ng, floored, 0, held, 0)
        _lk(ng, lastf, 0, held, 1)
        wrapped = _nd(ng, "ShaderNodeMath", (1500, 320), "loop forever",
                      role="SEQUENCE", operation="MODULO")
        _lk(ng, floored, 0, wrapped, 0)
        _lk(ng, seq_len, 0, wrapped, 1)
        does_loop = _nd(ng, "FunctionNodeCompare", (1500, 140), "does it loop?",
                        role="SEQUENCE", data_type="FLOAT",
                        operation="GREATER_THAN")
        _lk(ng, seq_loop, 0, does_loop, 0)
        _sv(does_loop, 1, 0.5)
        mode = _nd(ng, "GeometryNodeSwitch", (1700, 400), "loop or hold",
                   role="SEQUENCE", input_type="FLOAT")
        _lk(ng, does_loop, 0, mode, 0)
        _lk(ng, held, 0, mode, 1)
        _lk(ng, wrapped, 0, mode, 2)
        tile = _nd(ng, "ShaderNodeMath", (1880, 440), "+ sequence start",
                   role="SEQUENCE", operation="ADD")
        _lk(ng, mode, 0, tile, 0)
        _lk(ng, seq_start, 0, tile, 1)

        #  ── FRAME BLENDING, the spritecard way ──────────────────────────
        #  SFM crossfades each frame into the NEXT one, which is why an
        #  8 fps smoke sheet looks liquid there and stroboscopic on a plain
        #  frame-hold. The fraction between frames is already sitting in
        #  `played`; the next frame runs through the SAME loop/hold rule,
        #  so a held last frame blends into itself and simply holds. The
        #  material samples both tiles and mixes - its "Blend Frames" value
        #  node is the on/off switch.
        frame_frac = _nd(ng, "ShaderNodeMath", (1500, 20),
                         "how far into this frame", role="SEQUENCE",
                         operation="SUBTRACT")
        _lk(ng, played, 0, frame_frac, 0)
        _lk(ng, floored, 0, frame_frac, 1)
        next_f = _nd(ng, "ShaderNodeMath", (1500, -100), "the frame after",
                     role="SEQUENCE", operation="ADD")
        _lk(ng, floored, 0, next_f, 0)
        _sv(next_f, 1, 1.0)
        held2 = _nd(ng, "ShaderNodeMath", (1700, -60),
                    "hold blends into itself", role="SEQUENCE",
                    operation="MINIMUM")
        _lk(ng, next_f, 0, held2, 0)
        _lk(ng, lastf, 0, held2, 1)
        wrapped2 = _nd(ng, "ShaderNodeMath", (1700, -200),
                       "loop blends into frame 0", role="SEQUENCE",
                       operation="MODULO")
        _lk(ng, next_f, 0, wrapped2, 0)
        _lk(ng, seq_len, 0, wrapped2, 1)
        mode2 = _nd(ng, "GeometryNodeSwitch", (1880, -100), "loop or hold",
                    role="SEQUENCE", input_type="FLOAT")
        _lk(ng, does_loop, 0, mode2, 0)
        _lk(ng, held2, 0, mode2, 1)
        _lk(ng, wrapped2, 0, mode2, 2)
        tile_next = _nd(ng, "ShaderNodeMath", (2040, -60),
                        "+ sequence start", role="SEQUENCE", operation="ADD")
        _lk(ng, mode2, 0, tile_next, 0)
        _lk(ng, seq_start, 0, tile_next, 1)

        note(ng, "RENDERER  ·  which frame of the sheet", "SEQUENCE", """
    Two ways to drive the animation, exactly as SFM offers:

      animation rate          frames = age x rate x sequence length.
                              Rate 1.0 plays the whole sequence in one second.
      animation_fit_lifetime  frames = (age / lifetime) x sequence length, so the
                              sequence lasts exactly as long as the particle,
                              whatever lifetime it happened to roll.

    Then the sequence's OWN loop flag - read out of the .vtf, not guessed -
    decides whether the frame wraps round or stops on the last one. Finally the
    sequence's start tile is added, turning a frame number inside the sequence
    into an absolute tile index in the sheet.
    """, seq_nodes + [n for n in (frac_life, fit) if n is not None]
                    + [byrate, byrate2, played, floored, lastf,
                       held, wrapped, does_loop, mode, tile,
                       frame_frac, next_f, held2, wrapped2, mode2,
                       tile_next])

    # ── per-particle data for the shader ─────────────────────────────────
    rad = _nd(ng, "ShaderNodeMath", (760, -120), "radius x scale",
              role="OPERATOR", operation="MULTIPLY")
    _lk(ng, radius, 0, rad, 0)
    _lk(ng, gi, g("Scale"), rad, 1)

    # OPERATOR - Radius Scale. Instances CHAIN: each multiplies the radius it
    # was handed, so two of them read as grow-then-shrink.
    rad_chain, rad_nodes = rad, []
    for inst in range(1, n_of("Radius Scale") + 1):
        r = _nd(ng, "GeometryNodeGroup", (980 + (inst - 1) * 240, -120),
                spec.panel_name("Radius Scale", inst), role="OPERATOR")
        r.node_tree = groups["radius_scale"]
        _lk(ng, gi, gon("Radius Scale", inst), r, _in(r, "Enable"))
        _lk(ng, rad_chain, 0, r, _in(r, "Radius In"))
        _lp(ng, AGE, r, _in(r, "Age"))
        _lk(ng, life, 0, r, _in(r, "Lifetime"))            # 0.24.1: life fractions
        for a, b in (("Start Scale", "Start Scale"), ("End Scale", "End Scale"),
                     ("Start Time", "Start Time"), ("End Time", "End Time"),
                     ("Ease In And Out", "Ease"), ("Scale Bias", "Bias")):
            _lk(ng, gi, gs("Radius Scale", a, inst), r, _in(r, b))
        _lk(ng, envelope_for("Radius Scale", inst,
                             (980 + (inst - 1) * 240, -320)),
            0, r, _in(r, "Strength"))
        rad_chain = r
        rad_nodes.append(r)

    # OPERATOR - Rotation Spin Roll, on top of the roll chosen at birth.
    roll_chain, spin_nodes = roll, []
    for inst in range(1, n_of("Rotation Spin Roll") + 1):
        sp = _nd(ng, "GeometryNodeGroup", (980 + (inst - 1) * 240, -520),
                 spec.panel_name("Rotation Spin Roll", inst), role="OPERATOR")
        sp.node_tree = groups["spin_roll"]
        _lk(ng, gi, gon("Rotation Spin Roll", inst), sp, _in(sp, "Enable"))
        _lk(ng, roll_chain, 0, sp, _in(sp, "Roll In"))
        _lp(ng, AGE, sp, _in(sp, "Age"))
        for a, b in (("Spin Rate Min", "Rate Min"), ("Spin Rate", "Rate Max"),
                     ("Spin Stop Time", "Stop Time")):
            _lk(ng, gi, gs("Rotation Spin Roll", a, inst), sp, _in(sp, b))
        _lp(ng, PID, sp, _in(sp, "ID"))
        _lp(ng, seed_for(inst), sp, _in(sp, "Seed"))
        _lk(ng, envelope_for("Rotation Spin Roll", inst,
                             (980 + (inst - 1) * 240, -720)),
            0, sp, _in(sp, "Strength"))
        roll_chain = sp
        spin_nodes.append(sp)

    # OPERATOR - Rotation Yaw Flip Random. On a camera-facing card yaw is a
    # MIRROR, so this comes out as a +1 / -1 multiplier on the card's X scale.
    flip = _nd(ng, "GeometryNodeGroup", (760, -900),
               "Rotation Yaw Flip Random", role="OPERATOR")
    flip.node_tree = groups["yaw_flip"]
    _lk(ng, gi, gon("Rotation Yaw Flip Random"), flip, _in(flip, "Enable"))
    _lk(ng, gi, gs("Rotation Yaw Flip Random", "Flip Percentage"), flip,
        _in(flip, "Flip Percentage"))
    _lp(ng, PID, flip, _in(flip, "ID"))
    _lk(ng, gi, g("Seed"), flip, _in(flip, "Seed"))

    #  THE TWO RANDOM FADES, ONE GROUP PER INSTANCE. They are CHAIN
    #  operators, so a second copy simply takes the first one's output as its
    #  input - the same law Alpha Fade and Decay follows below. Each instance
    #  reads its own #N sockets and salts its own random stream.
    fade_chain, fade_nodes = alpha, []
    for inst in range(1, n_of("Alpha Fade In Random") + 1):
        op = "Alpha Fade In Random"
        fi = _nd(ng, "GeometryNodeGroup", (760 + (inst - 1) * 240, -560),
                 spec.panel_name(op, inst), role="OPERATOR")
        fi.node_tree = groups["fade_in"]
        _lk(ng, gi, gon(op, inst), fi, _in(fi, "Enable"))
        _lk(ng, fade_chain, 0, fi, _in(fi, "Alpha In"))
        _lp(ng, AGE, fi, _in(fi, "Age"))
        _lk(ng, life, 0, fi, _in(fi, "Lifetime"))
        for _a, _b in (("Fade In Time Min", "Time Min"),
                       ("Fade In Time Max", "Time Max"),
                       ("Fade In Exponent", "Time Exponent"),
                       ("Proportional", "Proportional")):
            _lk(ng, gi, gs(op, _a, inst), fi, _in(fi, _b))
        _lp(ng, PID, fi, _in(fi, "ID"))
        _lp(ng, seed_for(inst), fi, _in(fi, "Seed"))
        fade_chain = fi
        fade_nodes.append(fi)

    for inst in range(1, n_of("Alpha Fade Out Random") + 1):
        op = "Alpha Fade Out Random"
        fo = _nd(ng, "GeometryNodeGroup", (1000 + (inst - 1) * 240, -560),
                 spec.panel_name(op, inst), role="OPERATOR")
        fo.node_tree = groups["fade_out"]
        _lk(ng, gi, gon(op, inst), fo, _in(fo, "Enable"))
        _lk(ng, fade_chain, 0, fo, _in(fo, "Alpha In"))
        _lp(ng, AGE, fo, _in(fo, "Age"))
        _lk(ng, life, 0, fo, _in(fo, "Lifetime"))
        for _a, _b in (("Fade Out Time Min", "Time Min"),
                       ("Fade Out Time Max", "Time Max"),
                       ("Fade Out Exponent", "Time Exponent"),
                       ("Proportional", "Proportional")):
            _lk(ng, gi, gs(op, _a, inst), fo, _in(fo, _b))
        _lp(ng, PID, fo, _in(fo, "ID"))
        _lp(ng, seed_for(inst), fo, _in(fo, "Seed"))
        fade_chain = fo
        fade_nodes.append(fo)

    #  THE SIMPLE FADES: the Random fades with the roll taken out. Same
    #  groups, min = max = the one authored fraction, Proportional pinned on.
    #  4168 / 3021 uses in this library - the single most-used alpha
    #  operators there are.
    for op, grp, tsock in (("Alpha Fade In Simple", "fade_in",
                            "Proportional Fade In Time"),
                           ("Alpha Fade Out Simple", "fade_out",
                            "Proportional Fade Out Time")):
        for inst in range(1, n_of(op) + 1):
            fs = _nd(ng, "GeometryNodeGroup",
                     (1120 + (inst - 1) * 240,
                      -420 if "In" in op.split("Fade")[1] else -700),
                     spec.panel_name(op, inst), role="OPERATOR")
            fs.node_tree = groups[grp]
            _lk(ng, gi, gon(op, inst), fs, _in(fs, "Enable"))
            _lk(ng, fade_chain, 0, fs, _in(fs, "Alpha In"))
            _lp(ng, AGE, fs, _in(fs, "Age"))
            _lk(ng, life, 0, fs, _in(fs, "Lifetime"))
            _lk(ng, gi, gs(op, tsock, inst), fs, _in(fs, "Time Min"))
            _lk(ng, gi, gs(op, tsock, inst), fs, _in(fs, "Time Max"))
            _sv(fs, _in(fs, "Proportional"), True)
            _lp(ng, PID, fs, _in(fs, "ID"))
            _lp(ng, seed_for(inst), fs, _in(fs, "Seed"))
            fade_chain = fs
            fade_nodes.append(fs)

    # OPERATOR - Alpha Fade and Decay. Chains onto the random fades: a
    # system may carry all three, and 2001 systems carry this one.
    alpha_chain, decay_nodes = fade_chain, []
    for inst in range(1, n_of("Alpha Fade and Decay") + 1):
        op = "Alpha Fade and Decay"
        d = _nd(ng, "GeometryNodeGroup", (1240 + (inst - 1) * 240, -560),
                spec.panel_name(op, inst), role="OPERATOR")
        d.node_tree = groups["fade_decay"]
        _lk(ng, gi, gon(op, inst), d, _in(d, "Enable"))
        _lk(ng, alpha_chain, 0, d, _in(d, "Alpha In"))
        _lp(ng, AGE, d, _in(d, "Age"))
        _lk(ng, life, 0, d, _in(d, "Lifetime"))
        # ⚠️ CATALOGUE NAME vs GROUP INPUT NAME. The catalogue calls the fade
        # windows "Fade In Start" etc. ON PURPOSE - "Start Fade In" is the
        # ENVELOPE's name, and a shadowed display resolved to the envelope's
        # zero sockets, which clamped every particle to alpha 0.
        for nm, sock in (("Start Alpha", "Start Alpha"),
                         ("End Alpha", "End Alpha"),
                         ("Fade In Start", "Start Fade In"),
                         ("Fade In End", "End Fade In"),
                         ("Fade Out Start", "Start Fade Out"),
                         ("Fade Out End", "End Fade Out")):
            _lk(ng, gi, gs(op, nm, inst), d, _in(d, sock))
        _lk(ng, envelope_for(op, inst, (1240 + (inst - 1) * 240, -760)),
            0, d, _in(d, "Strength"))
        alpha_chain = d
        decay_nodes.append(d)

    # OPERATOR - Color Fade, on top of whatever Color Random rolled.
    colour_chain, cfade_nodes = colour, []
    for inst in range(1, n_of("Color Fade") + 1):
        op = "Color Fade"
        c = _nd(ng, "GeometryNodeGroup", (1240 + (inst - 1) * 240, 240),
                spec.panel_name(op, inst), role="OPERATOR")
        c.node_tree = groups["color_fade"]
        _lk(ng, gi, gon(op, inst), c, _in(c, "Enable"))
        _lk(ng, colour_chain, 0, c, _in(c, "Color In"))
        _lp(ng, AGE, c, _in(c, "Age"))
        _lk(ng, life, 0, c, _in(c, "Lifetime"))            # 0.24.1: life fractions
        _lk(ng, gi, gs(op, "Fade To", inst), c, _in(c, "Fade To"))
        _lk(ng, gi, gs(op, "Fade Start Time", inst), c, _in(c, "Start Time"))
        _lk(ng, gi, gs(op, "Fade End Time", inst), c, _in(c, "End Time"))
        _lk(ng, gi, gs(op, "Ease In And Out", inst), c, _in(c, "Ease"))
        _lk(ng, envelope_for(op, inst, (1240 + (inst - 1) * 240, 40)),
            0, c, _in(c, "Strength"))
        colour_chain = c
        cfade_nodes.append(c)

    note(ng, "OPERATOR  ·  alpha and colour over life", "OPERATOR", """
Alpha Random decides the particle's NORMAL alpha at birth. The operators here
then shape it over the particle's life: fade in lifts it from 0 up to normal,
fade out takes it back down, measured backwards from death.

They are chained, so a particle can do all of them. The two RANDOM fades roll
their own duration per particle, so a cloud never fades in unison; ALPHA FADE
AND DECAY uses fixed times, so it does - which is exactly why it is the
common one, at 2001 uses against their 647 and 878.

⚠️ THE TWO KINDS OF "TIME" SIT SIDE BY SIDE HERE. Alpha Fade and Decay's
times are FRACTIONS OF LIFE; Color Fade's are SECONDS. Same section, same
word, different units - the corpus ranges are what settle it, not the names.
""", fade_nodes + [rad, flip] + rad_nodes + spin_nodes
         + decay_nodes + cfade_nodes)

    # ── OPERATOR · Remap Distance to Control Point to Scalar ─────────────
    #  The distance-driven taper, LAST in both value chains because it reads
    #  the particle's FINAL evaluated position - the same closed form the
    #  renderer places the card with. Field 3 rewrites radius, field 7
    #  rewrites alpha; chained instances mean the last writer to a field
    #  wins while different fields coexist.
    rad_src, alpha_src = (rad_chain, 0), (alpha_chain, 0)
    op_rm = "Remap Distance to Control Point to Scalar"
    remap_nodes = []
    if n_of(op_rm) and groups.get("remap_cp") is not None:
        for inst in range(1, n_of(op_rm) + 1):
            rm_cp, np_rm = cp_select(gs(op_rm, "Control Point", inst), 1,
                                     (1500, -1500 - (inst - 1) * 240),
                                     f"remap CP {inst}")
            rm = _nd(ng, "GeometryNodeGroup",
                     (1740 + (inst - 1) * 260, -1300),
                     spec.panel_name(op_rm, inst), role="OPERATOR")
            rm.node_tree = groups["remap_cp"]
            _lk(ng, gi, gon(op_rm, inst), rm, _in(rm, "Enable"))
            _lk(ng, final_pos, 0, rm, _in(rm, "Position"))
            _lp(ng, rm_cp, rm, _in(rm, "CP Position"))
            for nm in ("Distance Min", "Distance Max", "Output Min",
                       "Output Max", "Output Field", "Scale Initial"):
                _lk(ng, gi, gs(op_rm, nm, inst), rm, _in(rm, nm))
            _lp(ng, rad_src, rm, _in(rm, "Radius In"))
            _lp(ng, alpha_src, rm, _in(rm, "Alpha In"))
            _lk(ng, gi, g("Scale"), rm, _in(rm, "Scale"))
            _lk(ng, envelope_for(op_rm, inst,
                                 (1500 + (inst - 1) * 260, -1740)),
                0, rm, _in(rm, "Strength"))
            rad_src, alpha_src = (rm, 0), (rm, 1)
            remap_nodes += [rm] + np_rm
        note(ng, "OPERATOR  ·  Remap Distance to Control Point to Scalar",
             "OPERATOR", """
Distance to a control point, remapped into radius (field 3) or alpha
(field 7) and CLAMPED to output min/max - the cap. Reads the particle's
final evaluated position, so it stays exact at any frame rate. The maths
and the field table live inside the group.
""", remap_nodes)

    # THE TRAIL POINTS WHERE THE PARTICLE ACTUALLY GOES. particle_velocity
    # used to be Movement Basic's closed form alone (launch + gravity + drag),
    # which for a spark born with Velocity Random +-75 on every axis is a
    # FROZEN RANDOM direction - and the sparks are then FLOWN by Pull-towards-
    # CP forces, so the trail stretched along its birth roll while the
    # particle travelled somewhere else: streaks moving sideways. The forces
    # already accumulate per tick into force_velocity, so adding it makes the
    # stored velocity the ACTUAL one (direction AND length: a trail is
    # speed x seconds). On a build with no forces the attribute is missing and
    # reads zero, so nothing changes there.
    fvel_trail = _nd(ng, "GeometryNodeInputNamedAttribute", (2020, -560),
                     "force_velocity [for the trail]", role="OPERATOR",
                     data_type="FLOAT_VECTOR")
    _sv(fvel_trail, 0, "force_velocity")
    vel_total = _nd(ng, "ShaderNodeVectorMath", (2040, -420),
                    "actual velocity = movement + forces", role="OPERATOR",
                    operation="ADD")
    _lk(ng, move, 1, vel_total, 0)
    _lk(ng, fvel_trail, 0, vel_total, 1)

    _store_list = [
            ("sprite_frame", "FLOAT", tile, 0),
            # the two extras that make frame BLENDING possible: which tile
            # comes next (same loop/hold law) and how far between them the
            # particle is right now, 0..1. The material mixes by them.
            ("sprite_frame_next", "FLOAT", tile_next, 0),
            ("sprite_frame_blend", "FLOAT", frame_frac, 0),
            ("sprite_alpha", "FLOAT", alpha_src[0], alpha_src[1]),
            ("sprite_color", "FLOAT_COLOR", colour_chain, 0),
            ("sprite_radius", "FLOAT", rad_src[0], rad_src[1]),
            ("sprite_roll", "FLOAT", roll_chain, 0),
            ("sprite_flip", "FLOAT", flip, 0),
            # NOT for the shader. Every system advertises how fast its
            # particles are going so that a CHILD system can inherit it, and
            # render_sprite_trail stretches along it. Movement Basic's closed
            # form PLUS the integrated force_velocity - the actual velocity.
            # A point attribute survives Instance on Points, which is how a
            # child reads it back off the INSTANCE domain.
            ("particle_velocity", "FLOAT_VECTOR", vel_total, 0),
            # SECONDS of travel. render_sprite_trail reads it back and turns
            # it into units by multiplying the particle's speed.
            ("trail_length", "FLOAT", trail_len, 0)]

    # ── NON-UNIFORM SHEETS: pick each frame's EXACT rectangle here ─────────
    #  A sheet whose frames are different sizes has no cols x rows grid. The
    #  VTF's own per-frame rects arrive as `rects` (already V-flipped and
    #  half-texel inset); ONE Index Switch holds them all as items - a single
    #  node whether the sheet has 14 frames or 122 - indexed by the same
    #  global frame number the grid path uses. The chosen corner and size are
    #  stored per particle and the material just reads them: the shader-side
    #  compare ladder this replaces was ~5 nodes PER FRAME and unmatchable by
    #  the hand layouts.
    if rects and tile is not None:
        def _rect_picker(tag, index_src, part, x):
            isw = _nd(ng, "GeometryNodeIndexSwitch", (x, -520),
                      f"rect {part} · {tag}", role="SEQUENCE",
                      data_type="VECTOR")
            while len(isw.index_switch_items) < len(rects):
                isw.index_switch_items.new()
            for ri, r in enumerate(rects):
                val = (r[0], r[1], 0.0) if part == "corner" \
                    else (r[2], r[3], 1.0)
                isw.inputs[ri + 1].default_value = val
            _lk(ng, index_src, 0, isw, 0)
            return isw
        ridx = _nd(ng, "FunctionNodeFloatToInt", (2000, -680),
                   "frame -> rect index", role="SEQUENCE")
        ridx.rounding_mode = "ROUND"
        _lk(ng, tile, 0, ridx, 0)
        ridx2 = _nd(ng, "FunctionNodeFloatToInt", (2000, -840),
                    "next frame -> rect index", role="SEQUENCE")
        ridx2.rounding_mode = "ROUND"
        _lk(ng, tile_next, 0, ridx2, 0)
        _store_list += [
            ("sprite_rect_min", "FLOAT_VECTOR",
             _rect_picker("this frame", ridx, "corner", 2240), 0),
            ("sprite_rect_scale", "FLOAT_VECTOR",
             _rect_picker("this frame", ridx, "size", 2460), 0),
            ("sprite_rect_min_next", "FLOAT_VECTOR",
             _rect_picker("next frame", ridx2, "corner", 2680), 0),
            ("sprite_rect_scale_next", "FLOAT_VECTOR",
             _rect_picker("next frame", ridx2, "size", 2900), 0)]

    chain, stores = setpos, []
    for i, (nm, dtype, src, sout) in enumerate(x for x in _store_list
            if x[2] is not None):
        st = _nd(ng, "GeometryNodeStoreNamedAttribute",
                 (2060 + i * 220, -140), f"{nm}  (POINT)", role="SEQUENCE",
                 data_type=dtype, domain="POINT")
        _sv(st, 2, nm)
        _lk(ng, chain, 0, st, 0)
        _lk(ng, src, sout, st, 3)
        stores.append(st)
        chain = st

    if DEAD is not None:
        kill = _nd(ng, "GeometryNodeDeleteGeometry", (3180, -140),
                   "remove dead and unborn", role="OPERATOR", domain="POINT",
                   mode="ALL")
        _lk(ng, chain, 0, kill, 0)
        _lk(ng, DEAD, 0, kill, 1)
        chain = kill
        stores.append(kill)

    note(ng, "PER-PARTICLE DATA  ·  POINT domain, for the shader", "SEQUENCE",
         """
These five values are stored on the POINT domain and read in the material with
attribute_type='INSTANCER'. That combination is the ONLY one that works:
'INSTANCER' reads from the instancER - these points - not from the instances.

THEY ARE BAKED BEFORE ANY DELETE, AND READ BACK AFTER. DeleteGeometry
RE-INDEXES the points it keeps, so anything still derived from Input Index at
that stage silently shifts onto a neighbour's value - every sprite took the
size and roll of the particle next to it the instant the first one died. An
attribute travels with its own point through a delete. A live index field does
not.

With the simulation emitter the delete happens inside the zone instead, and
every value here comes from the particle_id ATTRIBUTE rather than from an
index, so the same law is satisfied by construction.
""", stores)

    # ── renderer ─────────────────────────────────────────────────────────
    #  ORIENTATION CONTROL POINT -1 MEANS "NOT BOUND" - Source's own default.
    #  Unbound, the orientation frame is the WORLD's: a type-2 card lies flat
    #  on the ground however the empties are rotated. Only an index >= 0
    #  reads that control point's rotation. (Mix with a boolean factor, not a
    #  vector Switch - the vector Switch crashed 5.2's structure inference.)
    orient_euler = None
    orient_nodes = []
    if orient_rot is not None:
        o_eul = _nd(ng, "FunctionNodeRotationToEuler", (3180, -700),
                    "orientation CP as euler", role="RENDERER")
        _lp(ng, orient_rot, o_eul, 0)
        bound = _nd(ng, "FunctionNodeCompare", (3180, -860),
                    "-1 = not bound to a CP", role="RENDERER",
                    data_type="INT", operation="GREATER_EQUAL")
        _lk(ng, gi, gs("render_animated_sprites", "Orientation Control Point"),
            bound, 0)
        _sv(bound, 1, 0)
        pick_o = _nd(ng, "ShaderNodeMix", (3300, -780),
                     "bound? CP rotation : world", role="RENDERER",
                     data_type="VECTOR", factor_mode="UNIFORM")
        _lk(ng, bound, 0, pick_o, 0)
        _lk(ng, o_eul, 0, pick_o, 5)
        orient_euler = (pick_o, 1)
        orient_nodes = [o_eul, bound, pick_o]
    if rope:
        rend = _nd(ng, "GeometryNodeGroup", (3400, 200), "render_rope",
                   role="RENDERER")
        rend.node_tree = groups["rope"]
        _lk(ng, chain, 0, rend, _in(rend, "Points"))
        _lk(ng, gi, g("Camera"), rend, _in(rend, "Camera"))
        _lk(ng, gi, g(CAMSRC), rend, _in(rend, "Camera Source"))
        _lk(ng, gi, g(ROPE_HALF), rend, _in(rend, "Half Width"))
        _lk(ng, gi, g(ROPE_OFFSET), rend, _in(rend, "Texture Offset"))
        for a, b in (("Texel Size", "Texel Size"),
                     ("Texture Scroll Rate", "Texture Scroll Rate"),
                     ("Subdivision Count", "Subdivision Count")):
            _lk(ng, gi, gs("render_rope", a), rend, _in(rend, b))
    elif trail:
        rend = _nd(ng, "GeometryNodeGroup", (3400, 200), "render_sprite_trail",
                   role="RENDERER")
        rend.node_tree = groups["trail"]
        _lk(ng, chain, 0, rend, _in(rend, "Points"))
        _lk(ng, gi, g("Camera"), rend, _in(rend, "Camera"))
        _lk(ng, gi, g(CAMSRC), rend, _in(rend, "Camera Source"))
        for a in ("Min Length", "Max Length", "Length Fade In Time",
                  "Constrain Radius To Length"):
            _lk(ng, gi, gs("render_sprite_trail", a), rend, _in(rend, a))
    else:
        rend = _nd(ng, "GeometryNodeGroup", (3400, 200),
                   "render_animated_sprites", role="RENDERER")
        rend.node_tree = groups["renderer"]
        _lk(ng, chain, 0, rend, _in(rend, "Points"))
        _lk(ng, gi, g("Camera"), rend, _in(rend, "Camera"))
        _lk(ng, gi, g(CAMSRC), rend, _in(rend, "Camera Source"))
        _lk(ng, gi, gs("render_animated_sprites", "Orientation Type"), rend,
            _in(rend, "Orientation Type"))
        _lp(ng, orient_euler, rend, _in(rend, "Orientation CP Rotation"))
    # radius and roll are NOT passed - the renderer reads them from the baked
    # sprite_radius / sprite_roll attributes, because anything index-derived
    # would be shuffled by a DeleteGeometry.
    _lk(ng, rend, 0, go, 0)
    note(ng, "RENDERER", "RENDERER", """
One camera-facing card per surviving particle. Orientation Type 0/1/2 and why
roll must happen about the VIEW axis are explained inside the renderer group.
Orientation Control Point -1 (the default) means NOT BOUND: world axes.
""", [rend] + orient_nodes)

    if child_nodes:
        note(ng, "CHILDREN  ·  born on somebody else's particles", "EMITTER",
             """
A THIRD OF TF2 IS PARENT AND CHILD - 1148 of 3574 systems in the corpus have
children, 2907 links in all, and one system has fourteen.

A child is NOT a setting on its parent. It is a whole system in its own right,
with its own emitter, its own operators and its own children - the only thing
that makes it a child is that it is born on a parent PARTICLE instead of on a
control point. So here it is a second object with its own modifier, and the
CHILDREN panel points it at its parent.

    Parent System           the parent's host object
    Parent Particles From   what its renderer left behind to read:
                            0 instances (animated sprites - one instance per
                            particle), 1 points, 2 vertices (a rope)

EVERYTHING ELSE IS UNCHANGED. The parent particle replaces the control point,
and this system's own spawn offset, velocity and operators then happen around
it exactly as they would have around CP0.

WITH NO PARENT ASSIGNED IT FALLS BACK TO THE CONTROL POINT rather than piling
every particle on the origin - the switch is on "did we actually find any
parent particles", not on the toggle.

⚠️ Its own emission is INDEPENDENT of the parent's. SFM also scales a child's
emission by the parent's particle count ("use parent particles for emission
scaling"); that is not built, and it is listed as ignored in ras_spec so the
importer can say so out loud.
""", child_nodes)

    OPC = "Constrain distance to path between two control points"
    if groups.get("constrain_path") is not None:
        c_start, nc1 = cp_select(gs(OPC, "Start Control Point"), 1,
                                 (2100, -2300), "constraint start CP")
        c_end, nc2 = cp_select(gs(OPC, "End Control Point"), 1,
                               (2100, -2500), "constraint end CP")
        c_srot, nc3 = cp_select(gs(OPC, "Start Control Point"), 2,
                                (2100, -2700), "constraint start CP rot",
                                kind="ROTATION")
        c_erot, nc4 = cp_select(gs(OPC, "End Control Point"), 2,
                                (2100, -2900), "constraint end CP rot",
                                kind="ROTATION")
        cs_eul = _nd(ng, "FunctionNodeRotationToEuler", (2300, -2700),
                     "start CP rotation as euler", role="CONSTRAINT")
        _lp(ng, c_srot, cs_eul, 0)
        ce_eul = _nd(ng, "FunctionNodeRotationToEuler", (2300, -2900),
                     "end CP rotation as euler", role="CONSTRAINT")
        _lp(ng, c_erot, ce_eul, 0)
        #  The envelope runs on SYSTEM time, same as every operator's.
        env_c = _nd(ng, "GeometryNodeGroup", (2100, -2100),
                    f"envelope · {spec.panel_name(OPC)}", role="CONSTRAINT")
        env_c.node_tree = groups["envelope"]
        _lk(ng, clock, 0, env_c, 0)
        for i, nm in enumerate(ENV_FIELDS):
            _lk(ng, gi, gs(OPC, nm), env_c, i + 1)

        def leash_instance(label, loc, position_pair):
            n = _nd(ng, "GeometryNodeGroup", loc, label, role="CONSTRAINT")
            n.node_tree = groups["constrain_path"]
            _lk(ng, gi, gon(OPC), n, _in(n, "Enable"))
            _lp(ng, position_pair, n, _in(n, "Position"))
            _lp(ng, AGE, n, _in(n, "Age"))
            _lp(ng, c_start, n, _in(n, "Start"))
            _lp(ng, c_end, n, _in(n, "End"))
            _lk(ng, cs_eul, 0, n, _in(n, "Start Rotation"))
            _lk(ng, ce_eul, 0, n, _in(n, "End Rotation"))
            for disp, sock in (("Minimum Distance", "Min Distance"),
                               ("Maximum Distance", "Max Distance"),
                               ("Maximum Distance Middle",
                                "Max Distance Middle"),
                               ("Maximum Distance End", "Max Distance End"),
                               ("Travel Time", "Travel Time"),
                               ("Mid Point Position", "Mid Point"),
                               ("Random Bulge", "Random Bulge"),
                               ("Bulge Control", "Bulge Control")):
                _lk(ng, gi, gs(OPC, disp), n, _in(n, sock))
            _lk(ng, gi, g("Scale"), n, _in(n, "Scale"))
            _lp(ng, PID, n, _in(n, "ID"))
            _lk(ng, gi, g("Seed"), n, _in(n, "Seed"))
            _lk(ng, env_c, 0, n, _in(n, "Strength"))
            return n

        leash = leash_instance(spec.panel_name(OPC), (2340, -2200),
                               (final_pos, 0))

        #  ── the SIMPLER SIBLING: Constrain distance to control point ─────
        #  Chained AFTER the path leash, both here and per frame below -
        #  the order Source runs its constraint list. One CP, one shell,
        #  the centre offset in the CP's own frame.
        OPD = "Constrain distance to control point"
        cp_leash_instance = None
        cp_nodes = []
        if groups.get("constrain_cp") is not None:
            d_cp, nd1 = cp_select(gs(OPD, "Control Point"), 1,
                                  (2100, -3600), "cp-shell CP")
            d_rot, nd2 = cp_select(gs(OPD, "Control Point"), 2,
                                   (2100, -3800), "cp-shell CP rot",
                                   kind="ROTATION")
            d_eul = _nd(ng, "FunctionNodeRotationToEuler", (2300, -3800),
                        "shell CP rotation as euler", role="CONSTRAINT")
            _lp(ng, d_rot, d_eul, 0)
            env_d = _nd(ng, "GeometryNodeGroup", (2100, -3450),
                        f"envelope · {spec.panel_name(OPD)}",
                        role="CONSTRAINT")
            env_d.node_tree = groups["envelope"]
            _lk(ng, clock, 0, env_d, 0)
            for i, nm in enumerate(ENV_FIELDS):
                _lk(ng, gi, gs(OPD, nm), env_d, i + 1)

            def cp_leash_instance(label, loc, position_pair):
                n = _nd(ng, "GeometryNodeGroup", loc, label,
                        role="CONSTRAINT")
                n.node_tree = groups["constrain_cp"]
                _lk(ng, gi, gon(OPD), n, _in(n, "Enable"))
                _lp(ng, position_pair, n, _in(n, "Position"))
                _lp(ng, d_cp, n, _in(n, "CP"))
                _lk(ng, d_eul, 0, n, _in(n, "CP Rotation"))
                for disp, sock in (("Center Offset", "Center Offset"),
                                   ("Minimum Distance", "Min Distance"),
                                   ("Maximum Distance", "Max Distance")):
                    _lk(ng, gi, gs(OPD, disp), n, _in(n, sock))
                _lk(ng, gi, g("Scale"), n, _in(n, "Scale"))
                _lk(ng, env_d, 0, n, _in(n, "Strength"))
                return n

        chain_out = leash
        if cp_leash_instance is not None:
            cp_nodes += [env_d, d_eul] + nd1 + nd2
            chain_out = cp_leash_instance(spec.panel_name(OPD),
                                          (2580, -2200), (leash, 0))
            cp_nodes.append(chain_out)

        #  THE SPLICE: the constraint chain takes over Set Position's input.
        #  Compare nodes BY NAME - wrappers make `is` lie.
        for l in list(ng.links):
            if l.to_node.name == setpos.name \
                    and l.to_socket.name == "Position":
                ng.links.remove(l)
        _lk(ng, chain_out, 0, setpos, 2)

        #  🔴 THE PER-FRAME PASS IS WHAT MAKES IT SFM-TRUE. Clamping only
        #  the final position saturates: the accumulated force offset grows
        #  without bound, so within moments every particle sits pinned AT
        #  the envelope and the beam reads as a fat tube. Source clamps
        #  during the SIMULATION STEP, and the clamped position is what the
        #  next frame's forces push from - so the beam WANDERS inside the
        #  leash. Same trick here: the stored force_offset is corrected so
        #  the particle's whole position obeys the envelope every frame.
        #  (Stateless builds have no memory to correct; the final-position
        #  leash above is their whole story.)
        sim_splice = []
        if sim:
            total_sim = _nd(ng, "ShaderNodeVectorMath", (2600, -2200),
                            "position, forces applied", role="CONSTRAINT",
                            operation="ADD")
            _lk(ng, pos_closed, 0, total_sim, 0)
            _lk(ng, off_new, 0, total_sim, 1)
            leash_sim = leash_instance(
                f"{spec.panel_name(OPC)} · per frame", (2800, -2200),
                (total_sim, 0))
            sim_out = leash_sim
            if cp_leash_instance is not None:
                sim_out = cp_leash_instance(
                    f"{spec.panel_name(OPD)} · per frame", (2800, -2400),
                    (leash_sim, 0))
                cp_nodes.append(sim_out)
            off_corr = _nd(ng, "ShaderNodeVectorMath", (3040, -2200),
                           "the offset the leash allows", role="CONSTRAINT",
                           operation="SUBTRACT")
            _lk(ng, sim_out, 0, off_corr, 0)
            _lk(ng, pos_closed, 0, off_corr, 1)
            for l in list(ng.links):
                if l.to_node.name == store_foff.name \
                        and l.to_socket.name == "Value":
                    ng.links.remove(l)
            _lk(ng, off_corr, 0, store_foff, 3)

            #  🔴 THE CLAMP MUST BLEED OFF VELOCITY TOO, or the beam freezes.
            #  Source stores prev-position, so velocity IS pos - prev: when
            #  the constraint moves a particle back, the outward velocity is
            #  implicitly cancelled. Our stored force_velocity felt nothing,
            #  so with drag 0.001 it grew without bound and every particle's
            #  push direction froze solid - measured as a kink pattern that
            #  crawled 0.2 HU in ten frames whatever the force model did.
            #  Subtracting the clamped-away displacement as velocity (over a
            #  dt floored at EPS: on the dt=0 opening frame the displacement
            #  is zero anyway) keeps the walk alive inside the leash.
            v_lost = _nd(ng, "ShaderNodeVectorMath", (3040, -2380),
                         "what the leash took", role="CONSTRAINT",
                         operation="SUBTRACT")
            _lk(ng, sim_out, 0, v_lost, 0)
            _lk(ng, total_sim, 0, v_lost, 1)
            dt_safe = _nd(ng, "ShaderNodeMath", (3040, -2540),
                          "dt, never zero", role="CONSTRAINT",
                          operation="MAXIMUM")
            _lp(ng, DT, dt_safe, 0)
            _sv(dt_safe, 1, EPS)
            inv_dt = _nd(ng, "ShaderNodeMath", (3220, -2540), "1 / dt",
                         role="CONSTRAINT", operation="DIVIDE")
            _sv(inv_dt, 0, 1.0)
            _lk(ng, dt_safe, 0, inv_dt, 1)
            v_kick = _nd(ng, "ShaderNodeVectorMath", (3220, -2380),
                         "as a velocity change", role="CONSTRAINT",
                         operation="SCALE")
            _lk(ng, v_lost, 0, v_kick, 0)
            _lk(ng, inv_dt, 0, v_kick, 3)
            v_fix = _nd(ng, "ShaderNodeVectorMath", (3400, -2380),
                        "velocity, after the clamp", role="CONSTRAINT",
                        operation="ADD")
            _lk(ng, v_new, 0, v_fix, 0)
            _lk(ng, v_kick, 0, v_fix, 1)
            for l in list(ng.links):
                if l.to_node.name == store_fvel.name \
                        and l.to_socket.name == "Value":
                    ng.links.remove(l)
            _lk(ng, v_fix, 0, store_fvel, 3)
            sim_splice = [total_sim, leash_sim, off_corr, v_lost, dt_safe,
                          inv_dt, v_kick, v_fix]

    # =====================================================================
    #  INITIALIZER  ·  Rotation Yaw Random  (the cos-squish)
    # =====================================================================
    #  Multiplies the same sprite_flip channel the yaw FLIP mirror stores -
    #  flip's -1 and this compression compose by multiplication. Spliced at
    #  the end for the same name-stability reason as the leash; a rope has
    #  no sprite_flip store and correctly gets nothing.
    if groups.get("yaw_random") is not None:
        OPY = "Rotation Yaw Random"
        sf_store = next(
            (n for n in ng.nodes
             if n.bl_idname == "GeometryNodeStoreNamedAttribute"
             and n.inputs[2].default_value == "sprite_flip"), None)
        if sf_store is not None:
            yr = _nd(ng, "GeometryNodeGroup", (3260, -2200),
                     spec.panel_name(OPY), role="INITIALIZER")
            yr.node_tree = groups["yaw_random"]
            _lk(ng, gi, gon(OPY), yr, _in(yr, "Enable"))
            _lk(ng, gi, gs(OPY, "Yaw Min"), yr, _in(yr, "Yaw Min"))
            _lk(ng, gi, gs(OPY, "Yaw Max"), yr, _in(yr, "Yaw Max"))
            _lp(ng, PID, yr, _in(yr, "ID"))
            _lk(ng, gi, g("Seed"), yr, _in(yr, "Seed"))
            old_link = next(
                (l for l in ng.links if l.to_node.name == sf_store.name
                 and l.to_socket.name == "Value"), None)
            mulf = _nd(ng, "ShaderNodeMath", (3440, -2200), "flip x squish",
                       role="INITIALIZER", operation="MULTIPLY")
            if old_link is not None:
                src_sock = old_link.from_socket
                ng.links.remove(old_link)
                ng.links.new(src_sock, mulf.inputs[0])
            else:
                mulf.inputs[0].default_value = 1.0
            _lk(ng, yr, 0, mulf, 1)
            _lk(ng, mulf, 0, sf_store, 3)

    # =====================================================================
    #  FORCE  ·  random force, per tick (the crackle) - SIM BUILDS ONLY
    # =====================================================================
    #  Source rolls random force ONCE PER 30 Hz TICK, shared by every
    #  particle alive - each integrates the same force history over its own
    #  life window, which is what kinks a beam COHERENTLY. The old reading
    #  (a constant per particle, added to gravity) made a leashed beam
    #  drift to one wall of its envelope and lie there straight. So on
    #  simulation builds the constant is retired from the gravity path and
    #  the shared per-tick force joins the integrated forces instead; the
    #  stateless emitter has no memory to integrate with and keeps the old
    #  reading. Spliced at the end for name stability, like everything
    #  above.
    if sim and groups.get("random_force_tick") is not None \
            and n_of("random force") > 0:
        gf = next((nd for nd in ng.nodes
                   if nd.label == "gravity + force"), None)
        if gf is not None:
            for l in list(ng.links):
                if l.to_node.name != gf.name:
                    continue
                src = l.from_node
                tree = getattr(src, "node_tree", None)
                if (tree is not None and tree.name.startswith(
                        "SP · FORCE · random force")) \
                        or src.label == "+ force":
                    ng.links.remove(l)
        tickf = _nd(ng, "GeometryNodeGroup", (2100, -3300),
                    f"{spec.panel_name('random force')} · per tick",
                    role="OPERATOR")
        tickf.node_tree = groups["random_force_tick"]
        _lk(ng, gi, gon("random force"), tickf, _in(tickf, "Enable"))
        _lk(ng, clock, 0, tickf, _in(tickf, "Time"))
        _lk(ng, gi, gs("random force", "Min Force"), tickf,
            _in(tickf, "Min Force"))
        _lk(ng, gi, gs("random force", "Max Force"), tickf,
            _in(tickf, "Max Force"))
        _lk(ng, gi, g("Seed"), tickf, _in(tickf, "Seed"))
        _lp(ng, PID, tickf, _in(tickf, "ID"))
        _lk(ng, envelope_for("random force", 1, (1900, -3400)), 0, tickf,
            _in(tickf, "Strength"))
        old_dv = next((l for l in ng.links
                       if l.to_node.name == dv.name
                       and l.to_socket.name == "Vector"), None)
        if old_dv is not None:
            addf = _nd(ng, "ShaderNodeVectorMath", (2340, -3300),
                       "+ the tick force", role="OPERATOR", operation="ADD")
            src_sock = old_dv.from_socket
            ng.links.remove(old_dv)
            ng.links.new(src_sock, addf.inputs[0])
            _lk(ng, tickf, 0, addf, 1)
            _lk(ng, addf, 0, dv, 0)
        else:
            _lk(ng, tickf, 0, dv, 0)

    #  PROXY VIEW reaches the renderer. All three renderers carry the switch
    #  now - cards and trails swap in the tenth-size stand-in, the rope keeps
    #  its ribbon and swaps the sheet shader for a flat colour. The guard
    #  stays for any renderer built without one.
    try:
        _lk(ng, gi, g("Proxy View"), rend, _in(rend, "Proxy View"))
    except Exception:
        pass

    #  🔴 THIS NOTE USED TO SIT INSIDE THE except ABOVE - an indentation
    #  accident, so the leash frame only appeared on builds where the proxy
    #  link FAILED (ropes), and every card build silently lost it. It is the
    #  constraint section's closing note, so it runs whenever the constraint
    #  groups were built, independent of any renderer wiring.
    if groups.get("constrain_path") is not None:
        fr_leash = note(ng, "CONSTRAINT  ·  the leash on the final position",
                        "CONSTRAINT", """
The one pass that runs AFTER everything that moves a particle: position is
clamped to within a distance envelope of an anchor travelling the start CP
-> end CP path over Travel Time. Details and the maths live inside the
group; the short version is that a beam's +-1000-strength random force was
always authored to be seen THROUGH this leash, and without it the beam
simply leaves the scene.

Wired TWICE: per frame inside the simulation (the pass that makes the beam
wander instead of saturating into a tube - the clamped offset is what the
next frame's forces push from) and once on the final position, so every
renderer - cards, ropes, trails - is held identically. Disabled (the
default, and any .pcf that never authors one) both pass the position
through untouched.
""", [env_c, leash, cs_eul, ce_eul] + nc1 + nc2 + nc3 + nc4 + sim_splice
             + cp_nodes)
        try:
            fr_leash.name = "Constraint Leash"
        except Exception:
            pass
    return ng
