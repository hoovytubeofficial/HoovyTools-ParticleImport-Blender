# =============================================================================
# tools/trail_nodes.py  -  render_sprite_trail
# =============================================================================
#
# the THIRD RENDERER, and the one whose maths nobody can hold in their head
# 484 uses in TF2 - sparks, tracers, debris streaks, dust kicked up off the
# ground. A trail is ONE CARD PER PARTICLE, stretched backwards along the way
# that particle is travelling
#
# ═══════════════════════════════════════════════════════════════════════
# THE RADIUS / LENGTH / MAX LENGTH INTERPLAY, ONCE, PROPERLY
# ═══════════════════════════════════════════════════════════════════════
#
# There are FOUR numbers with "length" or "radius" in their name and they are
# three different quantities. That is the whole reason this is confusing
#
# 1. Trail Length Random -> length_min / length_max      SECONDS
# Not a length. How much of the particle's own TRAVEL the trail
# stands for. The renderer multiplies the particle's SPEED by it:
#
# 600 HU/s x 0.2 s  =  120 HU of trail
# 60 HU/s x 0.2 s  =   12 HU of trail
#
# So a trail stretches when the particle is fast and shortens as drag
# slows it down, and nothing has to animate the length to do it. This
# is why a spark shower looks like it's being flung: the fast ones
# are long and the tired ones are stubs, from one number.
#
# The corpus tops this field out at 20 (seconds!) while the renderer's
# max length reaches 5000 (units). Same word, different worlds
#
# 2. render_sprite_trail -> min length / max length      HAMMER UNITS
# A CLAMP on the answer, after the multiply. min length is a floor so
# a nearly-stopped particle still draws something rather than winking
# out; max length is the ceiling that stops a fast one drawing a
# streak across the whole map
#
# 3. render_sprite_trail -> length fade in time          SECONDS
# The trail grows from nothing over the first N secs of the
# particle's life, so it does not pop in at full stretch. Corpus 0..2
#
# 4. Radius Random -> radius_min / radius_max            HAMMER UNITS
# The WHOLE WIDTH (measured in SFM, 0.24.2 - it had been taken for the
# half-width). Independent of everything above: a trail is `length`
# long and `radius` wide
#
# Put together, per particle, every frame:
#
# speed   = | velocity |                      <- Movement Basic, exact
# raw     = speed x trail_length              <- secs -> units
# length  = clamp(raw, min length, max length)
# length  = length x fade_in(age)
# width   = radius
#
# 🔴 and THEN "CONSTRAIN RADIUS TO LENGTH", which is the one that catches
# people. A slow particle has a short trail, but its radius doesn't shrink
# with it - so a 4-unit-radius spark that has slowed to a 2-unit trail draws
# a card WIDER THAN IT is LONG. It stops looking like a streak and starts
# looking like a blob. With the constraint on, the width is capped at
# half the length, so a trail can only ever get squarer, never fatter
#
# ═══════════════════════════════════════════════════════════════════════
#
# HOW the CARD is BUILT, and why it is instanced rather than rebuilt
#  ------------------------------------------------------------------
# The rope rebuilds its rails by hand because a shared curve frame twists.
# A trail has no shared curve - each card is independent - so it can stay as
# a real INSTANCE, which matters for one specific reason:
#
# 🔑 SEQUENCES ONLY WORK ON INSTANCES.
# The sprite material reads `sprite_frame` with attribute_type
# ='INSTANCER'. Realize the instances and that lookup has nothing to read
# from, every card samples tile 0, and the flipbook dies. So the trail
# keeps Instance on Points and does its stretching with the instance's
# ROTATION and SCALE instead of by moving vertices.
#
# The card spans local Y from 0 to -1: its pivot is at the HEAD, so scaling Y
# grows it backwards, away from the particle, exactly like Source
#
# Two Align Rotation to Vector nodes do the aiming, in this order:
# 1. point local -Y down the velocity          (the streak direction)
# 2. spin about that Y until local Z faces the camera   (the billboard)
# Order matters: the second one pivots about Y, so it cannot disturb the
# first. Aiming at the camera first and the velocity second would
# =============================================================================

from .sprite_nodes import _group, _sock, _nd, _lk, _sv, note, proxy_material
from .ras_nodes import _io, _gin, EPS


def build_render_sprite_trail(mat, eye_group):
    """One camera-facing card per particle, stretched along its velocity."""
    # named after its material for the same reason as the other two
    # renderers: the material is baked in, so a shared name means the second
    # trail built wipes the first one's interface and drops its links.
    ng = _group(f"SP · RENDERER · render_sprite_trail · {mat.name}",
                "GeometryNodeTree")
    _sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    _sock(ng, "Points", "INPUT", "NodeSocketGeometry")
    _sock(ng, "Camera", "INPUT", "NodeSocketObject")
    _sock(ng, "Camera Source", "INPUT", "NodeSocketInt", 0, smin=0, smax=2)
    _sock(ng, "Min Length", "INPUT", "NodeSocketFloat", 1.0, smin=0.0)
    _sock(ng, "Max Length", "INPUT", "NodeSocketFloat", 2048.0, smin=0.0)
    _sock(ng, "Length Fade In Time", "INPUT", "NodeSocketFloat", 0.0,
          smin=0.0)
    _sock(ng, "Constrain Radius To Length", "INPUT", "NodeSocketBool", True)
    # not SFM - the low-GPU stand-in, same as the sprite renderer's.
    _sock(ng, "Proxy View", "INPUT", "NodeSocketBool", False)
    gi, go = _io(ng, (-1700, 0), (1900, 0))
    I = _gin(ng)

    #── what the particle is doing ───────────────────────────────────────
    vel = _nd(ng, "GeometryNodeInputNamedAttribute", (-1700, -320),
              "particle_velocity [read]", role="OPERATOR",
              data_type="FLOAT_VECTOR")
    _sv(vel, 0, "particle_velocity")
    rad = _nd(ng, "GeometryNodeInputNamedAttribute", (-1700, -480),
              "sprite_radius [read]", role="OPERATOR", data_type="FLOAT")
    _sv(rad, 0, "sprite_radius")
    tlen = _nd(ng, "GeometryNodeInputNamedAttribute", (-1700, -640),
               "trail_length [read]  (SECONDS)", role="INITIALIZER",
               data_type="FLOAT")
    _sv(tlen, 0, "trail_length")
    birth = _nd(ng, "GeometryNodeInputNamedAttribute", (-1700, -800),
                "birth_time [read]", role="EMITTER", data_type="FLOAT")
    _sv(birth, 0, "birth_time")
    clock = _nd(ng, "GeometryNodeInputSceneTime", (-1700, -960), "the clock",
                role="TIME")
    age = _nd(ng, "ShaderNodeMath", (-1500, -880), "age = now - birth",
              role="TIME", operation="SUBTRACT")
    _lk(ng, clock, 0, age, 0)
    _lk(ng, birth, 0, age, 1)

    # ── 1. speed x seconds = units ───────────────────────────────────────
    speed = _nd(ng, "ShaderNodeVectorMath", (-1500, -320), "| velocity |",
                role="OPERATOR", operation="LENGTH")
    _lk(ng, vel, 0, speed, 0)
    raw = _nd(ng, "ShaderNodeMath", (-1300, -400),
              "speed x trail_length  ->  HU", role="OPERATOR",
              operation="MULTIPLY")
    _lk(ng, speed, 1, raw, 0)            # LENGTH answers on output 1, not 0
    _lk(ng, tlen, 0, raw, 1)

    # ── 2. clamp it, in Hammer units ─────────────────────────────────────
    # MIN and MAX are not ordered in SFM any more than anywhere else, so the
    # floor and the ceiling are sorted before use - a Clamp node with them
    # the wrong way round returns the min for everything, and every trail in
    # the effect comes out exactly the same length.
    lo = _nd(ng, "ShaderNodeMath", (-1300, -600), "the real floor",
             role="RENDERER", operation="MINIMUM")
    _lk(ng, gi, I["Min Length"], lo, 0)
    _lk(ng, gi, I["Max Length"], lo, 1)
    hi = _nd(ng, "ShaderNodeMath", (-1300, -760), "the real ceiling",
             role="RENDERER", operation="MAXIMUM")
    _lk(ng, gi, I["Min Length"], hi, 0)
    _lk(ng, gi, I["Max Length"], hi, 1)
    clamped = _nd(ng, "ShaderNodeClamp", (-1100, -500), "clamp to min / max",
                  role="RENDERER")
    _lk(ng, raw, 0, clamped, 0)
    _lk(ng, lo, 0, clamped, 1)
    _lk(ng, hi, 0, clamped, 2)

    # ── 3. fade the length in ────────────────────────────────────────────
    # age / fade_in_time, held at 1. A fade time of 0 means "no fade" - and
    # a plain divide by 0 would make every trail either nothing or infinite,
    # so the window is floored and the result switched
    win = _nd(ng, "ShaderNodeMath", (-1100, -880), "fade window, never zero",
              role="TIME", operation="MAXIMUM")
    _lk(ng, gi, I["Length Fade In Time"], win, 0)
    _sv(win, 1, EPS)
    grow = _nd(ng, "ShaderNodeMath", (-900, -880), "age / window",
               role="TIME", operation="DIVIDE")
    _lk(ng, age, 0, grow, 0)
    _lk(ng, win, 0, grow, 1)
    grown = _nd(ng, "ShaderNodeMath", (-720, -880), "held at 1",
                role="TIME", operation="MINIMUM")
    _lk(ng, grow, 0, grown, 0)
    _sv(grown, 1, 1.0)
    fading = _nd(ng, "FunctionNodeCompare", (-900, -1040), "is there a fade?",
                 role="TIME", data_type="FLOAT", operation="GREATER_THAN")
    _lk(ng, gi, I["Length Fade In Time"], fading, 0)
    _sv(fading, 1, EPS)
    fade = _nd(ng, "GeometryNodeSwitch", (-540, -960), "fade, or full length",
               role="TIME", input_type="FLOAT")
    _lk(ng, fading, 0, fade, 0)
    _sv(fade, 1, 1.0)
    _lk(ng, grown, 0, fade, 2)
    length = _nd(ng, "ShaderNodeMath", (-340, -640), "FINAL TRAIL LENGTH",
                 role="RENDERER", operation="MULTIPLY")
    _lk(ng, clamped, 0, length, 0)
    _lk(ng, fade, 0, length, 1)

    # ── 4. width, and the constraint ─────────────────────────────────────
    half_cap = _nd(ng, "ShaderNodeMath", (-340, -860), "half the length",
                   role="RENDERER", operation="MULTIPLY")
    _lk(ng, length, 0, half_cap, 0)
    _sv(half_cap, 1, 0.5)
    capped = _nd(ng, "ShaderNodeMath", (-140, -860),
                 "radius, capped by the length", role="RENDERER",
                 operation="MINIMUM")
    _lk(ng, rad, 0, capped, 0)
    _lk(ng, half_cap, 0, capped, 1)
    half = _nd(ng, "GeometryNodeSwitch", (60, -800), "constrain?",
               role="RENDERER", input_type="FLOAT")
    _lk(ng, gi, I["Constrain Radius To Length"], half, 0)
    _lk(ng, rad, 0, half, 1)
    _lk(ng, capped, 0, half, 2)
    # 0.24.2: THE RADIUS is THE whole WIDTH, measured - calibration kit 3's
    # radius-12 trails were 12-13 units wide in SFM, its radius-16 one 17.6.
    # (Drawn twice as wide, a spark carried twice the light on that alone.)
    width = _nd(ng, "ShaderNodeMath", (260, -800), "width = radius (measured)",
                role="RENDERER", operation="MULTIPLY")
    _lk(ng, half, 0, width, 0)
    _sv(width, 1, 1.0)

    # ── 5. aim it ────────────────────────────────────────────────────────
    eye = _nd(ng, "GeometryNodeGroup", (-1500, 420), "where the camera is",
              role="RENDERER")
    eye.node_tree = eye_group
    _lk(ng, gi, I["Camera"], eye, 0)
    _lk(ng, gi, I["Camera Source"], eye, 1)
    pos = _nd(ng, "GeometryNodeInputPosition", (-1500, 260), "the particle",
              role="RENDERER")
    to_eye = _nd(ng, "ShaderNodeVectorMath", (-1300, 340), "particle -> camera",
                 role="RENDERER", operation="SUBTRACT")
    _lk(ng, eye, 0, to_eye, 0)
    _lk(ng, pos, 0, to_eye, 1)

    # A stationary particle has no direction to point in. Falling back to
    # straight up keeps the card valid instead of collapsing it - and a
    # particle that's not moving has no streak to draw anyway, which the
    # length maths has already taken care of
    moving = _nd(ng, "FunctionNodeCompare", (-1300, 120), "is it moving?",
                 role="OPERATOR", data_type="FLOAT", operation="GREATER_THAN")
    _lk(ng, speed, 1, moving, 0)
    _sv(moving, 1, EPS)
    up = _nd(ng, "ShaderNodeCombineXYZ", (-1300, -40), "straight up",
             role="OPERATOR")
    _sv(up, 2, 1.0)
    heading = _nd(ng, "GeometryNodeSwitch", (-1100, 60), "velocity, or up",
                  role="OPERATOR", input_type="VECTOR")
    _lk(ng, moving, 0, heading, 0)
    _lk(ng, up, 0, heading, 1)
    _lk(ng, vel, 0, heading, 2)

    #the CARD'S -Y IS its TAIL, so aiming +Y at the velocity points the tail
    #the way the particle CAME FROM. That is what a trail is
    aim = _nd(ng, "FunctionNodeAlignRotationToVector", (-900, 200),
              "point Y along the velocity", role="RENDERER",
              axis="Y", pivot_axis="AUTO")
    _sv(aim, 1, 1.0)
    _lk(ng, heading, 0, aim, 2)
    face = _nd(ng, "FunctionNodeAlignRotationToVector", (-700, 200),
               "then spin about Y to face the camera", role="RENDERER",
               axis="Z", pivot_axis="Y")
    _lk(ng, aim, 0, face, 0)
    _sv(face, 1, 1.0)
    _lk(ng, to_eye, 0, face, 2)

    # ── 6. the card ──────────────────────────────────────────────────────
    grid = _nd(ng, "GeometryNodeMeshGrid", (-900, 700), "one quad",
               role="RENDERER")
    _sv(grid, 0, 1.0)
    _sv(grid, 1, 1.0)
    _sv(grid, 2, 2)
    _sv(grid, 3, 2)
    # ⚠️ Mesh Grid's UV is an ANONYMOUS output socket, not a layer. Without
    # storing it as "UVMap" the shader has no UVs at all, samples one
    # transparent corner texel, and every trail renders INVISIBLE - which
    # looks exactly like a broken material and is not one
    uv = _nd(ng, "GeometryNodeStoreNamedAttribute", (-700, 700),
             "UVMap  (so the sheet can be read)", role="SEQUENCE",
             data_type="FLOAT2", domain="POINT")
    _sv(uv, 2, "UVMap")
    _lk(ng, grid, 0, uv, 0)
    _lk(ng, grid, 1, uv, 3)
    # Slide it so the head sits on the particle and the body hangs off the
    # BACK: local Y runs 0 at the head to -1 at the tail. Scaling Y then grows
    # the trail backwards, away from the particle, the way Source does it
    shift = _nd(ng, "GeometryNodeTransform", (-500, 700),
                "pivot at the head", role="RENDERER")
    _lk(ng, uv, 0, shift, 0)
    _sv(shift, 2, (0.0, -0.5, 0.0))
    # ⚠️ SET MATERIAL GOES ON THE INSTANCE SOURCE, before Instance on Points.
    # After instancing it does nothing at all.
    setmat = _nd(ng, "GeometryNodeSetMaterial", (-300, 700), "the trail sheet",
                 role="RENDERER")
    _lk(ng, shift, 0, setmat, 0)
    try:
        setmat.inputs[2].default_value = mat
    except Exception as exc:
        print(f"[HT_TRAIL]  set material: {exc}")

    scale = _nd(ng, "ShaderNodeCombineXYZ", (460, -600),
                "wide x long x 1", role="RENDERER")
    _lk(ng, width, 0, scale, 0)
    _lk(ng, length, 0, scale, 1)
    _sv(scale, 2, 1.0)

    #PROXY VIEW [not SFM] - the low-GPU stand-in. The sheet shader is most
    #of what a swarm of overlapping streaks costs the viewport; a flat
    #untextured colour costs nothing. The proxy keeps the streak's FULL
    #length - the stretch is the information a trail carries - and thins it
    #to a quarter of the width, so overdraw drops w/o the motion
    #becoming unreadable. Toggled from the Developer tab
    proxy_card = _nd(ng, "GeometryNodeTransform", (-300, 520),
                     "quarter width, full length", role="RENDERER")
    _lk(ng, shift, 0, proxy_card, 0)
    _sv(proxy_card, 3, (0.25, 1.0, 1.0))
    card_pick = _nd(ng, "GeometryNodeSwitch", (-100, 620),
                    "the real card, or the stand-in", role="RENDERER",
                    input_type="GEOMETRY")
    _lk(ng, gi, I["Proxy View"], card_pick, 0)
    _lk(ng, setmat, 0, card_pick, 1)
    _lk(ng, proxy_card, 0, card_pick, 2)

    inst = _nd(ng, "GeometryNodeInstanceOnPoints", (700, 200),
               "one card per particle", role="RENDERER")
    _lk(ng, gi, I["Points"], inst, 0)
    _lk(ng, card_pick, 0, inst, 2)
    _lk(ng, face, 0, inst, 5)
    _lk(ng, scale, 0, inst, 6)
    _lk(ng, inst, 0, go, 0)

    note(ng, "RENDERER  ·  render_sprite_trail", "RENDERER", """
ONE CARD PER PARTICLE, stretched backwards along the way it is travelling.

    speed   = | particle_velocity |            exact, from Movement Basic
    raw     = speed x trail_length             SECONDS become UNITS here
    length  = clamp(raw, min length, max length)
    length  = length x fade_in(age)
    width   = radius                         (measured, 0.24.2)

THE FOUR NUMBERS ARE THREE QUANTITIES, and that is the whole confusion:

  Trail Length Random  length_min/max   SECONDS of travel. Not a length.
  render_sprite_trail  min/max length   HAMMER UNITS. A clamp on the answer.
  render_sprite_trail  length fade in   SECONDS. Grows in from nothing.
  Radius Random        radius_min/max   HAMMER UNITS. The WHOLE width.

Because the length is speed x seconds, a trail stretches when the particle is
fast and shortens as drag slows it down, with nothing animating it. That is
what makes a spark shower read as thrown rather than drawn.

CONSTRAIN RADIUS TO LENGTH is the one that catches people. Radius does NOT
shrink with the trail, so a slowed particle draws a card wider than it is
long - a blob instead of a streak. The constraint caps the width at half
the length, so a trail can get squarer but never fatter.

WHY THIS STAYS AN INSTANCE while the rope rebuilds its vertices by hand:
SEQUENCES. The material reads sprite_frame with attribute_type='INSTANCER',
which has nothing to read from once instances are realized - every card would
sample tile 0 and the flipbook would die. So the stretching is done with the
instance's ROTATION and SCALE instead of by moving vertices.

THE CARD'S PIVOT IS AT ITS HEAD (local Y runs 0 to -1), so scaling Y grows it
backwards, away from the particle.

TWO ALIGNMENTS, IN THIS ORDER: point Y down the velocity, THEN spin about Y
until Z faces the camera. The second pivots about Y so it cannot disturb the
first. Doing it the other way round would.
""", [vel, rad, tlen, birth, clock, age, speed, raw, lo, hi, clamped, win,
      grow, grown, fading, fade, length, half_cap, capped, half, width,
      eye, pos, to_eye, moving, up, heading, aim, face, grid, uv, shift,
      setmat, scale, inst])

    # PROXY COLOUR - appended at the END so no existing node's birth-order
    # name shifts (hand-layout tables match by name first; see RULES). Flat
    # per-system colour on the stand-in, same reasoning as the sprite
    # renderer's: zero draw cost, and proxied systems stay tellable apart
    psm = _nd(ng, "GeometryNodeSetMaterial", (-160, 480),
              "the stand-in's own colour", role="RENDERER")
    try:
        psm.inputs[2].default_value = proxy_material(ng.name)
    except Exception as exc:
        print(f"[HT_TRAIL]  proxy material: {exc}")
    for l in list(ng.links):
        if l.from_node.name == proxy_card.name \
                and l.to_node.name == card_pick.name:
            ng.links.remove(l)
    _lk(ng, proxy_card, 0, psm, 0)
    _lk(ng, psm, 0, card_pick, 2)

    # 0.24.2: the TEXTURE'S TOP ROW SITS AT the TAIL, measured - kit 3's ramp
    # trail in SFM was brightest (texture alpha 1, its top row) at the tail
    # and faded toward the head; the grid's own UVs put that row at the head
    # Flipped here, appended LAST so no node's birth-order name shifts
    vflip = _nd(ng, "ShaderNodeVectorMath", (-820, 860),
                "v = 1 - v  (top row at the tail)", role="SEQUENCE",
                operation="MULTIPLY_ADD")
    _sv(vflip, 1, (1.0, -1.0, 1.0))
    _sv(vflip, 2, (0.0, 1.0, 0.0))
    for l in list(ng.links):
        # the UV link only - the grid's MESH runs into the same node
        if l.from_node.name == grid.name and l.to_node.name == uv.name \
                and l.from_socket.identifier == grid.outputs[1].identifier:
            ng.links.remove(l)
    _lk(ng, grid, 1, vflip, 0)
    _lk(ng, vflip, 0, uv, 3)
    return ng


# =============================================================================
# INITIALIZER  ·  Trail Length Random
# =============================================================================

def build_trail_length_random():
    """How many SECONDS of its own travel this particle's trail represents.

    A plain per-particle draw between min and max with an exponent bias, like
    the other Random initializers - the interesting part is not the maths, it
    is that the number is a TIME and everything downstream treats it as one.

    ⚠️ The corpus only ever writes an exponent of 0 or 1, and 0 is NOT a
    sensible power: value = min + (max-min) * rand^0 = max, every time. It is
    read as "no bias" instead, which is what 1 means, because an operator
    that silently pins every particle to its maximum is never what an author
    meant by leaving a field at zero."""
    ng = _group("SP · INITIALIZER · Trail Length Random", "GeometryNodeTree")
    _sock(ng, "Length", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Min", "INPUT", "NodeSocketFloat", 0.1)
    _sock(ng, "Max", "INPUT", "NodeSocketFloat", 0.5)
    _sock(ng, "Exponent", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Fallback", "INPUT", "NodeSocketFloat", 0.1)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-900, 0), (900, 0))
    I = _gin(ng)

    salt = _nd(ng, "ShaderNodeMath", (-700, -220), "its own salt",
               role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I["Seed"], salt, 0)
    _sv(salt, 1, 5407.0)
    salt_i = _nd(ng, "FunctionNodeFloatToInt", (-520, -220),
                 role="INITIALIZER")
    _lk(ng, salt, 0, salt_i, 0)

    roll = _nd(ng, "FunctionNodeRandomValue", (-520, 60), "roll 0..1",
               role="INITIALIZER", data_type="FLOAT")
    _sv(roll, 0, 0.0)
    _sv(roll, 1, 1.0)
    _lk(ng, gi, I["ID"], roll, 2)
    _lk(ng, salt_i, 0, roll, 3)

    # exponent 0 means "no bias", not "power of zero" - see the docstring
    exp_ok = _nd(ng, "ShaderNodeMath", (-520, -60), "exponent, never zero",
                 role="INITIALIZER", operation="MAXIMUM")
    _lk(ng, gi, I["Exponent"], exp_ok, 0)
    _sv(exp_ok, 1, EPS)
    biased = _nd(ng, "ShaderNodeMath", (-320, 0), "roll ^ exponent",
                 role="INITIALIZER", operation="POWER")
    _lk(ng, roll, 0, biased, 0)
    _lk(ng, exp_ok, 0, biased, 1)

    span = _nd(ng, "ShaderNodeMath", (-320, -200), "max - min",
               role="INITIALIZER", operation="SUBTRACT")
    _lk(ng, gi, I["Max"], span, 0)
    _lk(ng, gi, I["Min"], span, 1)
    scaled = _nd(ng, "ShaderNodeMath", (-120, -100), "x that",
                 role="INITIALIZER", operation="MULTIPLY")
    _lk(ng, biased, 0, scaled, 0)
    _lk(ng, span, 0, scaled, 1)
    value = _nd(ng, "ShaderNodeMath", (80, 0), "min + that",
                role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I["Min"], value, 0)
    _lk(ng, scaled, 0, value, 1)

    out = _nd(ng, "GeometryNodeSwitch", (320, 0), "enabled?",
              role="INITIALIZER", input_type="FLOAT")
    _lk(ng, gi, I["Enable"], out, 0)
    _lk(ng, gi, I["Fallback"], out, 1)
    _lk(ng, value, 0, out, 2)
    _lk(ng, out, 0, go, 0)

    note(ng, "INITIALIZER  ·  Trail Length Random", "INITIALIZER", """
SECONDS, NOT UNITS. This is how much of the particle's own travel its trail
stands for - render_sprite_trail multiplies the particle's SPEED by it.

    600 HU/s x 0.2 s  =  120 HU of trail
     60 HU/s x 0.2 s  =   12 HU of trail

Corpus: length_min 0..20, length_max 0.03..2000, and the exponent is only
ever 0 or 1.

EXPONENT 0 IS READ AS "NO BIAS". Taken literally, rand^0 is 1 for every
particle, so every trail would be exactly length_max - which is plainly not
what an author meant by leaving a field at zero.

354 of the 484 trail systems in TF2 carry this operator. The other 130 leave
every particle on the same default length, so they all stretch identically.
""", [salt, salt_i, roll, exp_ok, biased, span, scaled, value, out])
    return ng
