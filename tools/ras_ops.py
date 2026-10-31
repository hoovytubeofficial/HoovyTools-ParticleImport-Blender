# =============================================================================
# tools/ras_ops.py  -  more SFM operators, and the SFM -> Blender unit bridge
# =============================================================================
#
# Split out of ras_nodes.py so that file stays readable. Same DSL, same rules
# =============================================================================

from .sprite_nodes import _group, _sock, _nd, _lk, _sv, note
from .ras_nodes import _io, _gin, EPS


# =============================================================================
# what NEEDS SCALING  -  the SFM -> Blender unit bridge
# =============================================================================
#
# Source authors everything in Hammer units. Anything that's a DISTANCE, a
# SPEED (distance per second) or a FORCE (distance per second squared) must be
# multiplied by Scale on the way in. Anything that's a time, a count, an
# angle, a colour or a normalised 0..1 factor must NOT be
#
# Keyed by SFM functionName exactly as it appears in a .pcf, so the importer
# can consult this table directly once it starts reading real effects
# =============================================================================

OPERATOR_SCALE_MAP = {
    #── randomness / emission ────────────────────────────────────────────
    "radius random": ["radius_min", "radius_max"],
    "velocity random": [
        "speed_min", "speed_max",
        "speed_in_local_coordinate_system_min",
        "speed_in_local_coordinate_system_max",
    ],
    "velocity noise": ["output maximum", "output minimum"],
    "position modify offset random": [
        "offset min", "offset max", "offset_min", "offset_max",
    ],
    "movement basic": ["gravity"],
    # ── physics forces ───────────────────────────────────────────────────
    "random force": ["min force", "max force"],
    "pull towards control point": ["amount of force"],
    "twist around axis": ["amount of force"],
    "force control point towards constraint": [
        "max distance", "min distance", "amount of force",
    ],
    # ── spatial constraints ──────────────────────────────────────────────
    # ⚠️ "constrain", not "constraint" - the old key here had a stray T and
    # matched nothing in any real file (grepped the corpus: the exact
    # functionName is "Constrain distance to control point").
    "constrain distance to control point": [
        "maximum distance", "minimum distance", "offset of center",
    ],
    "movement lock to control point": ["distance_min", "distance_max"],
    # ── oscillation ──────────────────────────────────────────────────────
    "oscillate vector": ["oscillation multiplier"],
    # ── spatial distribution ─────────────────────────────────────────────
    "position within sphere random": [
        "distance_min", "distance_max",
        "distance bias absolute value", "distance_bias_absolute_value",
        "speed_min", "speed_max",
        "speed_in_local_coordinate_system_min",
        "speed_in_local_coordinate_system_max",
    ],
    # `bulge` is a DISTANCE, not a fraction of the path - the corpus runs
    # -2 to 75 across 3874 uses, and a fraction would make 75 meaningless
    "position along path sequential": ["bulge", "maximum distance"],
    # random bulge is NOT here: it's a fraction of the path's own length,
    # not a Hammer-unit distance - scaling it twice would square the scale.
    "constrain distance to path between two control points": [
        "minimum distance", "maximum distance",
        "maximum distance middle", "maximum distance end",
    ],
    #── control-point driven ─────────────────────────────────────────────
    "set control point positions": [
        "first control point location", "second control point location",
        "third control point location", "fourth control point location",
    ],
}


def scaled_fields(function_name):
    """Which attributes of this SFM operator arrive in Hammer units."""
    return OPERATOR_SCALE_MAP.get(str(function_name).strip().lower(), [])


# =============================================================================
# OPERATOR  ·  Alpha Fade In / Out Random
# =============================================================================

def _fade_group(name, label, is_in, salt):
    """One of SFM's two alpha fade operators.

    Checked against the Valve wiki (Particle System Operators):
      * the time range may be a FRACTION of the particle's lifespan
        (proportional = 1) or ABSOLUTE SECONDS (proportional = 0)
      * the EXPONENT biases WHICH value inside min..max is drawn - it shapes
        the random distribution, not the shape of the fade curve
      * fade IN lifts the particle from alpha 0 to its normal alpha
      * fade OUT is measured BACKWARDS from the end of the particle's life
    """
    ng = _group(name, "GeometryNodeTree")
    _sock(ng, "Alpha", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Alpha In", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Age", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Lifetime", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Time Min", "INPUT", "NodeSocketFloat", 0.25)
    _sock(ng, "Time Max", "INPUT", "NodeSocketFloat", 0.25)
    _sock(ng, "Time Exponent", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Proportional", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-1500, 0), (1300, 0))
    I = _gin(ng)

    seed_n = _nd(ng, "ShaderNodeMath", (-1300, -520), "salt the seed",
                 role="OPERATOR", operation="ADD")
    _lk(ng, gi, I["Seed"], seed_n, 0)
    _sv(seed_n, 1, float(salt))
    seed_i = _nd(ng, "FunctionNodeFloatToInt", (-1120, -520), role="OPERATOR")
    _lk(ng, seed_n, 0, seed_i, 0)

    raw = _nd(ng, "FunctionNodeRandomValue", (-1120, -300), "0..1",
              role="OPERATOR", data_type="FLOAT")
    _sv(raw, 0, 0.0)
    _sv(raw, 1, 1.0)
    _lk(ng, gi, I["ID"], raw, 2)
    _lk(ng, seed_i, 0, raw, 3)
    expo = _nd(ng, "ShaderNodeMath", (-920, -300), "bias by the exponent",
               role="OPERATOR", operation="POWER")
    _lk(ng, raw, 0, expo, 0)
    _lk(ng, gi, I["Time Exponent"], expo, 1)
    span = _nd(ng, "ShaderNodeMapRange", (-720, -300), "-> min..max",
               role="OPERATOR", clamp=False)
    _lk(ng, expo, 0, span, 0)
    _sv(span, 1, 0.0)
    _sv(span, 2, 1.0)
    _lk(ng, gi, I["Time Min"], span, 3)
    _lk(ng, gi, I["Time Max"], span, 4)

    as_frac = _nd(ng, "ShaderNodeMath", (-520, -180), "x lifetime",
                  role="OPERATOR", operation="MULTIPLY")
    _lk(ng, span, 0, as_frac, 0)
    _lk(ng, gi, I["Lifetime"], as_frac, 1)
    dur = _nd(ng, "GeometryNodeSwitch", (-320, -240),
              "seconds, or a share of the life", role="OPERATOR",
              input_type="FLOAT")
    _lk(ng, gi, I["Proportional"], dur, 0)
    _lk(ng, span, 0, dur, 1)
    _lk(ng, as_frac, 0, dur, 2)
    dur_safe = _nd(ng, "ShaderNodeMath", (-120, -240), "never a zero window",
                   role="OPERATOR", operation="MAXIMUM")
    _lk(ng, dur, 0, dur_safe, 0)
    _sv(dur_safe, 1, EPS)

    extra = []
    if is_in:
        ramp = _nd(ng, "ShaderNodeMapRange", (160, 120),
                   "0 -> 1 over the fade in", role="OPERATOR", clamp=True)
        _lk(ng, gi, I["Age"], ramp, 0)
        _sv(ramp, 1, 0.0)
        _lk(ng, dur_safe, 0, ramp, 2)
        _sv(ramp, 3, 0.0)
        _sv(ramp, 4, 1.0)
    else:
        start = _nd(ng, "ShaderNodeMath", (100, -60), "lifetime - fade out",
                    role="OPERATOR", operation="SUBTRACT")
        _lk(ng, gi, I["Lifetime"], start, 0)
        _lk(ng, dur_safe, 0, start, 1)
        ramp = _nd(ng, "ShaderNodeMapRange", (300, 120),
                   "1 -> 0 over the fade out", role="OPERATOR", clamp=True)
        _lk(ng, gi, I["Age"], ramp, 0)
        _lk(ng, start, 0, ramp, 1)
        _lk(ng, gi, I["Lifetime"], ramp, 2)
        _sv(ramp, 3, 1.0)
        _sv(ramp, 4, 0.0)
        extra = [start]

    weighted = _nd(ng, "ShaderNodeMapRange", (540, 120), "x operator strength",
                   role="OPERATOR", clamp=True)
    _lk(ng, gi, I["Strength"], weighted, 0)
    _sv(weighted, 1, 0.0)
    _sv(weighted, 2, 1.0)
    _sv(weighted, 3, 1.0)
    _lk(ng, ramp, 0, weighted, 4)

    applied = _nd(ng, "ShaderNodeMath", (760, 60), "x incoming alpha",
                  role="OPERATOR", operation="MULTIPLY")
    _lk(ng, gi, I["Alpha In"], applied, 0)
    _lk(ng, weighted, 0, applied, 1)
    sw = _nd(ng, "GeometryNodeSwitch", (1000, 0), "enabled?", role="OPERATOR",
             input_type="FLOAT")
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, gi, I["Alpha In"], sw, 1)
    _lk(ng, applied, 0, sw, 2)
    _lk(ng, sw, 0, go, 0)

    direction = ("UP from invisible to its normal alpha" if is_in else
                 "DOWN to invisible, measured BACKWARDS from death")
    note(ng, f"OPERATOR  ·  {label}", "OPERATOR", f"""
Takes the particle {direction}.

THE TIME RANGE
  Every particle rolls its OWN fade duration between Time Min and Time Max, so
  a puff of them never fades in lockstep.

PROPORTIONAL  (on by default, as in SFM)
  ON   the times are a FRACTION of that particle's own lifespan, so 0.25 means
       "the first / last quarter of my life" however long that turned out.
  OFF  they are ABSOLUTE SECONDS.

TIME EXPONENT
  Biases WHICH value inside min..max gets drawn. It shapes the random
  DISTRIBUTION, not the shape of the fade curve. 1 is uniform; higher crowds
  results toward Min, lower toward Max.

OPERATOR STRENGTH
  The common envelope scales how much of the fade is applied. At strength 0
  the operator simply stops acting and the alpha passes straight through - it
  never inverts.
""", [seed_n, seed_i, raw, expo, span, as_frac, dur, dur_safe, ramp, weighted,
      applied, sw] + extra)
    return ng


def build_alpha_fade_in():
    return _fade_group("SP · OPERATOR · Alpha Fade In Random",
                       "Alpha Fade In Random", True, 121)


def build_alpha_fade_out():
    return _fade_group("SP · OPERATOR · Alpha Fade Out Random",
                       "Alpha Fade Out Random", False, 131)


# =============================================================================
# INITIALIZER  ·  Velocity Random
# =============================================================================

def build_velocity_random():
    """SFM's Velocity Random: a radial speed plus a local-space XYZ velocity.

    Same two-part shape as the velocity half of Position Within Sphere Random,
    but as a standalone initializer so it can be used with any spawn shape.
    Both halves are in Hammer units per second, so both are scaled."""
    ng = _group("SP · INITIALIZER · Velocity Random", "GeometryNodeTree")
    _sock(ng, "Velocity", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Direction", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
    _sock(ng, "Speed Min", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Speed Max", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Local Speed Min", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Local Speed Max", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "CP Rotation", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Scale", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-1200, 0), (1000, 0))
    I = _gin(ng)

    seed_n = _nd(ng, "ShaderNodeMath", (-1000, -460), "salt the seed",
                 role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I["Seed"], seed_n, 0)
    _sv(seed_n, 1, 141.0)
    seed_i = _nd(ng, "FunctionNodeFloatToInt", (-820, -460),
                 role="INITIALIZER")
    _lk(ng, seed_n, 0, seed_i, 0)

    spd = _nd(ng, "FunctionNodeRandomValue", (-820, 180), "radial speed",
              role="INITIALIZER", data_type="FLOAT")
    _lk(ng, gi, I["Speed Min"], spd, 0)
    _lk(ng, gi, I["Speed Max"], spd, 1)
    _lk(ng, gi, I["ID"], spd, 2)
    _lk(ng, seed_i, 0, spd, 3)
    spd_s = _nd(ng, "ShaderNodeMath", (-620, 180), "x scale",
                role="INITIALIZER", operation="MULTIPLY")
    _lk(ng, spd, 0, spd_s, 0)
    _lk(ng, gi, I["Scale"], spd_s, 1)
    dirn = _nd(ng, "ShaderNodeVectorMath", (-620, 360), "unit direction",
               role="INITIALIZER", operation="NORMALIZE")
    _lk(ng, gi, I["Direction"], dirn, 0)
    vrad = _nd(ng, "ShaderNodeVectorMath", (-400, 280),
               "direction x speed", role="INITIALIZER", operation="SCALE")
    _lk(ng, dirn, 0, vrad, 0)
    _lk(ng, spd_s, 0, vrad, 3)

    vloc = _nd(ng, "FunctionNodeRandomValue", (-820, -160),
               "speed in local XYZ", role="INITIALIZER",
               data_type="FLOAT_VECTOR")
    _lk(ng, gi, I["Local Speed Min"], vloc, 0)
    _lk(ng, gi, I["Local Speed Max"], vloc, 1)
    _lk(ng, gi, I["ID"], vloc, 2)
    _lk(ng, seed_i, 0, vloc, 3)
    vloc_s = _nd(ng, "ShaderNodeVectorMath", (-620, -160), "x scale",
                 role="INITIALIZER", operation="SCALE")
    _lk(ng, vloc, 0, vloc_s, 0)
    _lk(ng, gi, I["Scale"], vloc_s, 3)
    vrot = _nd(ng, "ShaderNodeVectorRotate", (-400, -160),
               "into the CP's frame", role="INITIALIZER",
               rotation_type="EULER_XYZ")
    _lk(ng, vloc_s, 0, vrot, 0)
    _lk(ng, gi, I["CP Rotation"], vrot, 4)

    total = _nd(ng, "ShaderNodeVectorMath", (-160, 60), "radial + local",
                role="INITIALIZER", operation="ADD")
    _lk(ng, vrad, 0, total, 0)
    _lk(ng, vrot, 0, total, 1)
    zero = _nd(ng, "ShaderNodeCombineXYZ", (-160, -420), "off = no velocity",
               role="INITIALIZER")
    out = _nd(ng, "ShaderNodeMix", (400, 0), "enabled?", role="INITIALIZER",
              data_type="VECTOR", factor_mode="UNIFORM")
    _lk(ng, gi, I["Enable"], out, 0)
    _lk(ng, zero, 0, out, 4)
    _lk(ng, total, 0, out, 5)
    _lk(ng, out, 1, go, 0)

    note(ng, "INITIALIZER  ·  Velocity Random", "INITIALIZER", """
The velocity a particle is BORN with, in two parts that SFM adds together:

  Speed Min/Max        speed along Direction - for a sphere spawn this is fed
                       the outward direction, so particles fly away from the
                       control point.
  Local Speed Min/Max  an XYZ velocity in the CONTROL POINT'S OWN frame, which
                       is why it goes through a Vector Rotate: if the empty is
                       tilted, "up" means the empty's up.

BOTH are distances per second in Hammer units, so BOTH are multiplied by
Scale. See OPERATOR_SCALE_MAP in this module for the full list of fields that
need that treatment.
""", [seed_n, seed_i, spd, spd_s, dirn, vrad, vloc, vloc_s, vrot, total, zero,
      out])
    return ng


# =============================================================================
# OPERATOR  ·  Movement Basic  (the global force step)
# =============================================================================

SOURCE_DRAG_HZ = 30.0
"""Source expresses drag as a fraction retained PER 30 Hz TICK, not per second.

    drag 0.10 -> keep 90% of the previous frame's motion, thirty times a second

So the continuous decay rate is  k = 30 x drag, and terminal velocity under a
constant force is

    v_terminal = gravity / (30 x drag)          Hammer units per second

MEASURED, not assumed. Three balls were floated up to a Scout's hat
(81.6924 HU) in SFM and timed:

    gravity  drag   measured   this model
      125    0.30     5.55 s     5.99 s
       15    0.15    24.50 s    24.73 s
        5    0.10    48.10 s    49.35 s

Solving for the constant gives 28.3 / 30.0 / 29.4 - it is 30, the tick rate.
All three arrive slightly EARLY by a roughly constant DISTANCE (6.2 / 0.8 /
2.1 HU), which is what a spawn offset looks like, not a modelling error.

WHY 30 x drag AND NOT -30 x ln(1 - drag). Source's per-frame factor is
q = (1 - drag)^(30 dt). At SFM's own tick, dt = 1/30, that is exactly
(1 - drag), so 1 - q = drag and v_terminal = gravity x dt / drag =
gravity / (30 drag). The logarithm is the dt -> 0 limit of the same
expression, which is a DIFFERENT number - 19% slower at drag 0.3 - and it
does not match the measurements. Simulating the per-frame loop confirms it:
at 30 fps it lands on 5.97 / 24.70 / 49.33, within 0.4% of this closed form.

That per-frame factor is genuinely frame-rate dependent (the same effect
takes 5.75 s at 24 fps and 6.93 s at 240 fps). A closed form has no dt to be
dependent on, so pinning k to 30 x drag makes the preview always show the
30 fps answer - the one SFM itself shows.

AND DRAG 1.0 DOES NOT STOP A PARTICLE. "Retain 0%" means it forgets its
previous motion, but it still gets one tick of gravity every tick, so it
drifts at gravity/30 forever. k = 30 x drag reproduces that endpoint exactly;
the logarithmic form wrongly brings it to a dead stop."""


def build_movement_basic():
    """Gravity and drag - the operator every movement system leans on.

    Stateless closed form rather than a per-frame integration, so the maths
    stays exact at any frame rate and does not drift:

        k         = 30 x drag                     (see SOURCE_DRAG_HZ)
        t_eff     = (1 - e^-kt) / k               how far a coasting particle gets
        position  = v0 x t_eff  +  g x (t - t_eff) / k

    DRAG ACTS ON GRAVITY TOO. That is the correction this version carries: the
    previous form dragged only the initial velocity and let gravity accelerate
    unopposed as g t^2 / 2, so a particle under gravity never settled at a
    terminal speed. With drag 0.3 and gravity 125 that put it 82 units up in
    1.1 seconds instead of the measured 5.5.

    With no drag both terms collapse to the plain ballistic answer - t_eff -> t
    and (t - t_eff)/k -> t^2 / 2 - so drag 0 still gives v0 t + g t^2 / 2."""
    ng = _group("SP · OPERATOR · Movement Basic", "GeometryNodeTree")
    _sock(ng, "Offset", "OUTPUT", "NodeSocketVector")
    # The DERIVATIVE of that offset, handed out so a CHILD system can inherit
    # its parent's motion. It is the same closed form differentiated, not a
    # finite difference between frames - so it's exact and costs six nodes:
    #
    # drag     v = v0 e^-kt  +  g (1 - e^-kt)/k     ->  g/k, terminal
    # no drag  v = v0 + g t                             plain ballistics
    #
    # Both pieces already exist above for the position; this only recombines
    # them. It does not include the integrated force correction (Pull towards
    # control point, twist around axis), which lives in the simulation zone
    _sock(ng, "Velocity", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Velocity", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Gravity", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Drag", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Age", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Scale", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1300, 0), (1100, 0))
    I = _gin(ng)

    # SOURCE'S DRAG IS PER 30 Hz TICK, so the per-second rate is 30 x drag.
    # Leaving this out made drag roughly thirty times too weak
    k = _nd(ng, "ShaderNodeMath", (-1260, -240), "k = 30 x drag",
            role="OPERATOR", operation="MULTIPLY")
    _lk(ng, gi, I["Drag"], k, 0)
    _sv(k, 1, SOURCE_DRAG_HZ)

    # drag: travelled = (1 - e^(-k t)) / k,  -> t as k -> 0
    kt = _nd(ng, "ShaderNodeMath", (-1080, -240), "k x age", role="OPERATOR",
             operation="MULTIPLY")
    _lk(ng, k, 0, kt, 0)
    _lk(ng, gi, I["Age"], kt, 1)
    neg = _nd(ng, "ShaderNodeMath", (-900, -240), "negate", role="OPERATOR",
              operation="MULTIPLY")
    _lk(ng, kt, 0, neg, 0)
    _sv(neg, 1, -1.0)
    ex = _nd(ng, "ShaderNodeMath", (-720, -240), "e^-kt", role="OPERATOR",
             operation="EXPONENT")
    _lk(ng, neg, 0, ex, 0)
    one_minus = _nd(ng, "ShaderNodeMath", (-540, -240), "1 - e^-kt",
                    role="OPERATOR", operation="SUBTRACT")
    _sv(one_minus, 0, 1.0)
    _lk(ng, ex, 0, one_minus, 1)
    k_safe = _nd(ng, "ShaderNodeMath", (-720, -420), "k, never zero",
                 role="OPERATOR", operation="MAXIMUM")
    _lk(ng, k, 0, k_safe, 0)
    _sv(k_safe, 1, EPS)
    t_eff = _nd(ng, "ShaderNodeMath", (-360, -300), "effective time",
                role="OPERATOR", operation="DIVIDE")
    _lk(ng, one_minus, 0, t_eff, 0)
    _lk(ng, k_safe, 0, t_eff, 1)
    has_drag = _nd(ng, "FunctionNodeCompare", (-540, -460), "any drag?",
                   role="OPERATOR", data_type="FLOAT", operation="GREATER_THAN")
    _lk(ng, gi, I["Drag"], has_drag, 0)
    _sv(has_drag, 1, EPS)
    t_use = _nd(ng, "GeometryNodeSwitch", (-160, -380), "drag, or plain time",
                role="OPERATOR", input_type="FLOAT")
    _lk(ng, has_drag, 0, t_use, 0)
    _lk(ng, gi, I["Age"], t_use, 1)
    _lk(ng, t_eff, 0, t_use, 2)

    travel = _nd(ng, "ShaderNodeVectorMath", (120, 160), "velocity x time",
                 role="OPERATOR", operation="SCALE")
    _lk(ng, gi, I["Velocity"], travel, 0)
    _lk(ng, t_use, 0, travel, 3)

    # gravity is dragged too.
    # no drag  ->  g t^2 / 2          (free fall)
    # drag     ->  g (t - t_eff) / k  (settles at terminal velocity g/k)
    # The two agree as k -> 0, so the switch is only there to keep the divide
    # away from zero
    g_s = _nd(ng, "ShaderNodeVectorMath", (-1080, 240), "gravity x scale",
              role="OPERATOR", operation="SCALE")
    _lk(ng, gi, I["Gravity"], g_s, 0)
    _lk(ng, gi, I["Scale"], g_s, 3)

    t2 = _nd(ng, "ShaderNodeMath", (-1080, 60), "age squared", role="OPERATOR",
             operation="MULTIPLY")
    _lk(ng, gi, I["Age"], t2, 0)
    _lk(ng, gi, I["Age"], t2, 1)
    half = _nd(ng, "ShaderNodeMath", (-900, 60), "t^2 / 2  (no drag)",
               role="OPERATOR", operation="MULTIPLY")
    _lk(ng, t2, 0, half, 0)
    _sv(half, 1, 0.5)

    lag = _nd(ng, "ShaderNodeMath", (-900, -100), "t - t_eff", role="OPERATOR",
              operation="SUBTRACT")
    _lk(ng, gi, I["Age"], lag, 0)
    _lk(ng, t_eff, 0, lag, 1)
    g_fac_drag = _nd(ng, "ShaderNodeMath", (-720, -100), "(t - t_eff) / k",
                     role="OPERATOR", operation="DIVIDE")
    _lk(ng, lag, 0, g_fac_drag, 0)
    _lk(ng, k_safe, 0, g_fac_drag, 1)
    g_fac = _nd(ng, "GeometryNodeSwitch", (-500, 60), "dragged, or free fall",
                role="OPERATOR", input_type="FLOAT")
    _lk(ng, has_drag, 0, g_fac, 0)
    _lk(ng, half, 0, g_fac, 1)
    _lk(ng, g_fac_drag, 0, g_fac, 2)

    drop = _nd(ng, "ShaderNodeVectorMath", (120, 380), "gravity x that",
               role="OPERATOR", operation="SCALE")
    _lk(ng, g_s, 0, drop, 0)
    _lk(ng, g_fac, 0, drop, 3)

    total = _nd(ng, "ShaderNodeVectorMath", (360, 260), "travel + gravity",
                role="OPERATOR", operation="ADD")
    _lk(ng, travel, 0, total, 0)
    _lk(ng, drop, 0, total, 1)
    strong = _nd(ng, "ShaderNodeVectorMath", (560, 160), "x strength",
                 role="OPERATOR", operation="SCALE")
    _lk(ng, total, 0, strong, 0)
    _lk(ng, gi, I["Strength"], strong, 3)

    zero = _nd(ng, "ShaderNodeCombineXYZ", (560, -160), "off = no movement",
               role="OPERATOR")
    out = _nd(ng, "ShaderNodeMix", (820, 0), "enabled?", role="OPERATOR",
              data_type="VECTOR", factor_mode="UNIFORM")
    _lk(ng, gi, I["Enable"], out, 0)
    _lk(ng, zero, 0, out, 4)
    _lk(ng, strong, 0, out, 5)
    _lk(ng, out, 1, go, 0)

    # ── the velocity, for whoever inherits it ────────────────────────────
    # drag     v = v0 e^-kt + g x t_eff        (t_eff = (1 - e^-kt)/k)
    # no drag  v = v0 + g t
    v_kept = _nd(ng, "ShaderNodeVectorMath", (120, -560), "v0 x e^-kt",
                 role="OPERATOR", operation="SCALE")
    _lk(ng, gi, I["Velocity"], v_kept, 0)
    _lk(ng, ex, 0, v_kept, 3)
    v_gained = _nd(ng, "ShaderNodeVectorMath", (120, -720), "g x t_eff",
                   role="OPERATOR", operation="SCALE")
    _lk(ng, g_s, 0, v_gained, 0)
    _lk(ng, t_eff, 0, v_gained, 3)
    v_drag = _nd(ng, "ShaderNodeVectorMath", (320, -640), "dragged velocity",
                 role="OPERATOR", operation="ADD")
    _lk(ng, v_kept, 0, v_drag, 0)
    _lk(ng, v_gained, 0, v_drag, 1)

    v_gt = _nd(ng, "ShaderNodeVectorMath", (120, -880), "g x t", role="OPERATOR",
               operation="SCALE")
    _lk(ng, g_s, 0, v_gt, 0)
    _lk(ng, gi, I["Age"], v_gt, 3)
    v_free = _nd(ng, "ShaderNodeVectorMath", (320, -880), "v0 + g t",
                 role="OPERATOR", operation="ADD")
    _lk(ng, gi, I["Velocity"], v_free, 0)
    _lk(ng, v_gt, 0, v_free, 1)

    v_pick = _nd(ng, "GeometryNodeSwitch", (520, -760), "dragged, or free",
                 role="OPERATOR", input_type="VECTOR")
    _lk(ng, has_drag, 0, v_pick, 0)
    _lk(ng, v_free, 0, v_pick, 1)
    _lk(ng, v_drag, 0, v_pick, 2)
    v_strong = _nd(ng, "ShaderNodeVectorMath", (720, -760), "x strength",
                   role="OPERATOR", operation="SCALE")
    _lk(ng, v_pick, 0, v_strong, 0)
    _lk(ng, gi, I["Strength"], v_strong, 3)
    v_out = _nd(ng, "ShaderNodeMix", (920, -760), "enabled?", role="OPERATOR",
                data_type="VECTOR", factor_mode="UNIFORM")
    _lk(ng, gi, I["Enable"], v_out, 0)
    _lk(ng, zero, 0, v_out, 4)
    _lk(ng, v_strong, 0, v_out, 5)
    _lk(ng, v_out, 1, go, 1)

    note(ng, "OPERATOR  ·  Movement Basic", "OPERATOR", """
THE core movement operator. Gravity and drag, applied to the velocity the
initializers handed over.

    k        = 30 x drag
    t_eff    = (1 - e^-kt) / k
    position = velocity x t_eff  +  gravity x (t - t_eff) / k

DRAG IS PER 30 Hz TICK, NOT PER SECOND. Source keeps a fraction of the
previous frame's motion thirty times a second, so "drag 0.1" is a decay rate
of 3.0 per second, not 0.1. Reading it as per-second made drag thirty times
too weak and every gravity-driven effect far too fast.

    terminal velocity = gravity / (30 x drag)   Hammer units per second

MEASURED against SFM, three balls floated to a Scout's hat at 81.69 units:
gravity 125 / drag 0.30 crossed at 5.55 s, 15 / 0.15 at 24.5 s, 5 / 0.10 at
48.1 s. Solving for the constant gives 28.3, 30.0 and 29.4. It is the tick.

DRAG ACTS ON GRAVITY, not just on the launch velocity. That is why a particle
under gravity SETTLES at a steady climb instead of accelerating forever. The
earlier version dragged only the initial velocity and let gravity run free as
g t^2 / 2, which put that first ball 82 units up in 1.1 seconds instead of 5.5.

With drag 0 both terms collapse to plain ballistics, v0 t + g t^2 / 2.

GRAVITY IS A VECTOR, not just a Z number - SFM stores it that way and effects
do use sideways gravity. Velocity arrives already scaled by the initializer,
which is why only gravity is scaled here.

THE SECOND OUTPUT IS THE VELOCITY, differentiated from the same closed form
rather than measured between frames, so it is exact at any frame rate like
everything else here. A CHILD system reads it to inherit its parent's motion
(Position From Parent Particles). It does not include the integrated forces -
those live in the simulation zone, not in this group.
""", [k, kt, neg, ex, one_minus, k_safe, t_eff, has_drag, t_use, travel, g_s,
      t2, half, lag, g_fac_drag, g_fac, drop, total, strong, zero, out,
      v_kept, v_gained, v_drag, v_gt, v_free, v_pick, v_strong, v_out])
    return ng


# =============================================================================
# OPERATOR  ·  Radius Scale
# =============================================================================

def build_radius_scale():
    """SFM's `Radius Scale`: ramp the radius between two multipliers.

    Fields read out of 3250 real instances:
        radius_start_scale  radius_end_scale
        start_time  end_time  ease_in_and_out  scale_bias

    TIMES ARE FRACTIONS OF LIFE (0.24.1, measured with calibration kit 2 -
    0.24.0 read seconds off the corpus ranges). scale_bias is Source's
    BiasSIMD, t / ((1/b - 2)(1 - t) + 1); before start_time the radius is
    left alone, after end_time it holds the end scale.

    It is the third most duplicated operator in the corpus (75 systems use two
    or three), so it CHAINS: each instance multiplies the radius it was given.
    """
    ng = _group("SP · OPERATOR · Radius Scale", "GeometryNodeTree")
    _sock(ng, "Radius", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Radius In", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Age", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Lifetime", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Bias", "INPUT", "NodeSocketFloat", 0.5)
    _sock(ng, "Start Scale", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "End Scale", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Start Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "End Time", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Ease", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1200, 0), (1100, 0))
    I = _gin(ng)

    # never a zero-length window: Map Range collapses to 0 when from_min ==
    # from_max, which would pin every particle to Start Scale forever
    bump = _nd(ng, "ShaderNodeMath", (-1180, -220), role="OPERATOR",
               operation="ADD")
    _lk(ng, gi, I["Start Time"], bump, 0)
    _sv(bump, 1, EPS)
    hi = _nd(ng, "ShaderNodeMath", (-980, -220), "never a zero window",
             role="OPERATOR", operation="MAXIMUM")
    _lk(ng, gi, I["End Time"], hi, 0)
    _lk(ng, bump, 0, hi, 1)

    # 0.24.1: AGE AS A FRACTION OF LIFE - measured, see the docstring
    life = _nd(ng, "ShaderNodeMath", (-1180, 120), "lifetime, never zero",
               role="TIME", operation="MAXIMUM")
    _lk(ng, gi, I["Lifetime"], life, 0)
    _sv(life, 1, EPS)
    frac = _nd(ng, "ShaderNodeMath", (-980, 120), "age / lifetime",
               role="TIME", operation="DIVIDE")
    _lk(ng, gi, I["Age"], frac, 0)
    _lk(ng, life, 0, frac, 1)
    ramp = _nd(ng, "ShaderNodeMapRange", (-760, 0), "0 -> 1 across the window",
               role="OPERATOR", clamp=True)
    _lk(ng, frac, 0, ramp, 0)
    _lk(ng, gi, I["Start Time"], ramp, 1)
    _lk(ng, hi, 0, ramp, 2)
    _sv(ramp, 3, 0.0)
    _sv(ramp, 4, 1.0)

    # SMOOTHSTEP is not A MATH OPERATION in 5.2 - the Math node's enum stops
    # at SMOOTH_MIN / SMOOTH_MAX, which are something else entirely. It lives
    # on Map Range as an interpolation type
    eased = _nd(ng, "ShaderNodeMapRange", (-560, -200), "smooth the ends",
                role="OPERATOR", clamp=True,
                interpolation_type="SMOOTHSTEP")
    _lk(ng, ramp, 0, eased, 0)
    _sv(eased, 1, 0.0)
    _sv(eased, 2, 1.0)
    _sv(eased, 3, 0.0)
    _sv(eased, 4, 1.0)
    t = _nd(ng, "GeometryNodeSwitch", (-340, -60), "eased, or linear",
            role="OPERATOR", input_type="FLOAT")
    _lk(ng, gi, I["Ease"], t, 0)
    _lk(ng, ramp, 0, t, 1)
    _lk(ng, eased, 0, t, 2)

    # 0.24.1: SOURCE'S BIAS, MEASURED - BiasSIMD, Schlick's fast bias:
    # t / ((1/b - 2)(1 - t) + 1), b kept inside (0, 1); 0.5 is a straight
    # line. Kit 2's bias-0.95 row fits it to the pixel at every age - the
    # textbook t ^ (log b / log 0.5) was up to 0.15 too big early in life
    b_lo = _nd(ng, "ShaderNodeMath", (-340, -260), "bias, kept inside (0,1)",
               role="OPERATOR", operation="MAXIMUM")
    _lk(ng, gi, I["Bias"], b_lo, 0)
    _sv(b_lo, 1, 0.001)
    b_hi = _nd(ng, "ShaderNodeMath", (-340, -400), "...", role="OPERATOR",
               operation="MINIMUM")
    _lk(ng, b_lo, 0, b_hi, 0)
    _sv(b_hi, 1, 0.999)
    inv_b = _nd(ng, "ShaderNodeMath", (-160, -300), "1 / b", role="OPERATOR",
                operation="DIVIDE")
    _sv(inv_b, 0, 1.0)
    _lk(ng, b_hi, 0, inv_b, 1)
    k = _nd(ng, "ShaderNodeMath", (-160, -440), "1/b - 2", role="OPERATOR",
            operation="SUBTRACT")
    _lk(ng, inv_b, 0, k, 0)
    _sv(k, 1, 2.0)
    one_t = _nd(ng, "ShaderNodeMath", (-160, -580), "1 - t", role="OPERATOR",
                operation="SUBTRACT")
    _sv(one_t, 0, 1.0)
    _lk(ng, t, 0, one_t, 1)
    den = _nd(ng, "ShaderNodeMath", (20, -440), "(1/b - 2)(1 - t) + 1",
              role="OPERATOR", operation="MULTIPLY_ADD")
    _lk(ng, k, 0, den, 0)
    _lk(ng, one_t, 0, den, 1)
    _sv(den, 2, 1.0)
    biased = _nd(ng, "ShaderNodeMath", (-120, -120), "t / that  (Bias)",
                 role="OPERATOR", operation="DIVIDE")
    _lk(ng, t, 0, biased, 0)
    _lk(ng, den, 0, biased, 1)
    scale = _nd(ng, "ShaderNodeMix", (-120, 60), "start -> end scale",
                role="OPERATOR", data_type="FLOAT", factor_mode="UNIFORM")
    _lk(ng, biased, 0, scale, 0)
    _lk(ng, gi, I["Start Scale"], scale, 2)
    _lk(ng, gi, I["End Scale"], scale, 3)

    #the envelope fades the SCALE back towards 1, not towards 0 - strength 0
    #must mean "this operator is not acting", never "no radius at all"
    strong = _nd(ng, "ShaderNodeMix", (120, 60), "x operator strength",
                 role="OPERATOR", data_type="FLOAT", factor_mode="UNIFORM")
    _lk(ng, gi, I["Strength"], strong, 0)
    _sv(strong, 2, 1.0)
    # before start_time Source never touches the radius (scale 1)
    before = _nd(ng, "FunctionNodeCompare", (-120, 260), "before the window?",
                 role="OPERATOR", data_type="FLOAT", operation="LESS_THAN")
    _lk(ng, frac, 0, before, 0)
    _lk(ng, gi, I["Start Time"], before, 1)
    held = _nd(ng, "GeometryNodeSwitch", (40, 200), "untouched before it",
               role="OPERATOR", input_type="FLOAT")
    _lk(ng, before, 0, held, 0)
    _lk(ng, scale, 0, held, 1)
    _sv(held, 2, 1.0)
    _lk(ng, held, 0, strong, 3)

    out = _nd(ng, "ShaderNodeMath", (340, 60), "radius x that",
              role="OPERATOR", operation="MULTIPLY")
    _lk(ng, gi, I["Radius In"], out, 0)
    _lk(ng, strong, 0, out, 1)
    sw = _nd(ng, "GeometryNodeSwitch", (600, 0), "enabled?", role="OPERATOR",
             input_type="FLOAT")
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, gi, I["Radius In"], sw, 1)
    _lk(ng, out, 0, sw, 2)
    _lk(ng, sw, 0, go, 0)

    note(ng, "OPERATOR  ·  Radius Scale", "OPERATOR", """
    scale  = mix( radius_start_scale , radius_end_scale , t )
    radius = radius x scale

where t ramps 0 -> 1 between start_time and end_time, both FRACTIONS OF THE
PARTICLE'S LIFE - measured in SFM's particle editor (0.24.1; 0.24.0 had read
seconds off the corpus ranges). t is then biased the way Source's BiasSIMD
does it: t / ((1/b - 2)(1 - t) + 1).

ease_in_and_out smooths both ends instead of ramping linearly.

IT CHAINS. This is the third most duplicated operator in the corpus - 75
systems use two or three of them - so each instance multiplies the radius it
was handed rather than replacing it. Two Radius Scales are a grow-then-shrink.

Disabled, or strength 0 -> the radius passes through UNCHANGED. Fading an
operator out means "stop acting", never "scale to nothing".

scale_bias (0.24.1, measured): 0.5 is linear; 0.95 is ~60% of the way at
1/16 of life and ~90% by a third. It is what makes the concrete impacts' dust
cloud appear at full size.
""", [bump, hi, ramp, eased, t, scale, strong, out, sw])
    return ng


# =============================================================================
# OPERATOR  ·  Rotation Spin Roll
# =============================================================================

def build_spin_roll():
    """SFM's `Rotation Spin Roll`: the sprite keeps turning.

        spin_rate_degrees   degrees per second (the survey runs -64..300)
        spin_rate_min       the other end of the range
        spin_stop_time      seconds after which it stops. 0 = never stops.

    Closed form, so it is exact at any frame rate:

        roll += rate x min(age, spin_stop_time)
    """
    ng = _group("SP · OPERATOR · Rotation Spin Roll", "GeometryNodeTree")
    _sock(ng, "Roll", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Roll In", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Age", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Rate Min", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Rate Max", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Stop Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-1200, 0), (1200, 0))
    I = _gin(ng)

    salt = _nd(ng, "ShaderNodeMath", (-980, -400), "salt the seed",
               role="OPERATOR", operation="ADD")
    _lk(ng, gi, I["Seed"], salt, 0)
    _sv(salt, 1, 88.0)
    salt_i = _nd(ng, "FunctionNodeFloatToInt", (-800, -400), role="OPERATOR")
    _lk(ng, salt, 0, salt_i, 0)
    rate = _nd(ng, "FunctionNodeRandomValue", (-600, -260), "spin rate",
               role="OPERATOR", data_type="FLOAT")
    _lk(ng, gi, I["Rate Min"], rate, 0)
    _lk(ng, gi, I["Rate Max"], rate, 1)
    _lk(ng, gi, I["ID"], rate, 2)
    _lk(ng, salt_i, 0, rate, 3)

    # stop_time 0 means "never stops", NOT "stops immediately" - reading it the
    # other way freezes every spinning sprite on frame one, and 0 is the
    # commonly authored value
    stops = _nd(ng, "FunctionNodeCompare", (-980, 200), "does it ever stop?",
                role="OPERATOR", data_type="FLOAT", operation="GREATER_THAN")
    _lk(ng, gi, I["Stop Time"], stops, 0)
    _sv(stops, 1, 0.0)
    capped = _nd(ng, "ShaderNodeMath", (-780, 200), "age, but capped",
                 role="OPERATOR", operation="MINIMUM")
    _lk(ng, gi, I["Age"], capped, 0)
    _lk(ng, gi, I["Stop Time"], capped, 1)
    spin_t = _nd(ng, "GeometryNodeSwitch", (-560, 120), "for how long",
                 role="OPERATOR", input_type="FLOAT")
    _lk(ng, stops, 0, spin_t, 0)
    _lk(ng, gi, I["Age"], spin_t, 1)
    _lk(ng, capped, 0, spin_t, 2)

    turned = _nd(ng, "ShaderNodeMath", (-340, 60), "degrees turned",
                 role="OPERATOR", operation="MULTIPLY")
    _lk(ng, rate, 0, turned, 0)
    _lk(ng, spin_t, 0, turned, 1)
    rad = _nd(ng, "ShaderNodeMath", (-120, 60), "degrees -> radians",
              role="OPERATOR", operation="MULTIPLY")
    _lk(ng, turned, 0, rad, 0)
    _sv(rad, 1, 0.017453292519943295)
    strong = _nd(ng, "ShaderNodeMath", (100, 60), "x operator strength",
                 role="OPERATOR", operation="MULTIPLY")
    _lk(ng, rad, 0, strong, 0)
    _lk(ng, gi, I["Strength"], strong, 1)
    total = _nd(ng, "ShaderNodeMath", (320, 60), "on top of the birth roll",
                role="OPERATOR", operation="ADD")
    _lk(ng, gi, I["Roll In"], total, 0)
    _lk(ng, strong, 0, total, 1)
    sw = _nd(ng, "GeometryNodeSwitch", (600, 0), "enabled?", role="OPERATOR",
             input_type="FLOAT")
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, gi, I["Roll In"], sw, 1)
    _lk(ng, total, 0, sw, 2)
    _lk(ng, sw, 0, go, 0)

    note(ng, "OPERATOR  ·  Rotation Spin Roll", "OPERATOR", """
    roll = roll_at_birth + rate x min(age, spin_stop_time)

RATE IS DEGREES PER SECOND. The survey runs -64..300, so it is degrees - not
turns, not radians. Converted once, here, on the way out.

spin_stop_time 0 MEANS "NEVER STOPS". Reading a zero as "stop at t = 0"
freezes every spinning sprite on the first frame, and 0 is the common value.

Rate is rolled per particle between spin_rate_min and spin_rate_degrees, with
its own salt, so a spinning cloud does not spin in unison.

Closed form on purpose: nothing accumulates, so it is exact at any frame rate
and gives the same answer however many times a frame is re-evaluated.
""", [salt, salt_i, rate, stops, capped, spin_t, turned, rad, strong, total,
      sw])
    return ng


# =============================================================================
# FORCE GENERATOR  ·  random force
# =============================================================================

def build_random_force():
    """SFM's `random force`: a steady push, different for every particle.

        min force / max force   Hammer units per second squared

    A constant per-particle acceleration is exactly what gravity already is,
    so this vector is ADDED to the gravity vector and inherits Movement
    Basic's drag maths for free. No new integration, no new physics."""
    ng = _group("SP · FORCE · random force", "GeometryNodeTree")
    _sock(ng, "Force", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Min Force", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Max Force", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-900, 0), (900, 0))
    I = _gin(ng)

    salt = _nd(ng, "ShaderNodeMath", (-700, -240), "salt the seed",
               role="OPERATOR", operation="ADD")
    _lk(ng, gi, I["Seed"], salt, 0)
    _sv(salt, 1, 99.0)
    salt_i = _nd(ng, "FunctionNodeFloatToInt", (-520, -240), role="OPERATOR")
    _lk(ng, salt, 0, salt_i, 0)
    rv = _nd(ng, "FunctionNodeRandomValue", (-320, 0), "a force per particle",
             role="OPERATOR", data_type="FLOAT_VECTOR")
    _lk(ng, gi, I["Min Force"], rv, 0)
    _lk(ng, gi, I["Max Force"], rv, 1)
    _lk(ng, gi, I["ID"], rv, 2)
    _lk(ng, salt_i, 0, rv, 3)
    strong = _nd(ng, "ShaderNodeVectorMath", (-60, 0), "x operator strength",
                 role="OPERATOR", operation="SCALE")
    _lk(ng, rv, 0, strong, 0)
    _lk(ng, gi, I["Strength"], strong, 3)
    zero = _nd(ng, "ShaderNodeCombineXYZ", (-60, -220), "off = no force",
               role="OPERATOR")
    sw = _nd(ng, "GeometryNodeSwitch", (300, 0), "enabled?", role="OPERATOR",
             input_type="VECTOR")
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, zero, 0, sw, 1)
    _lk(ng, strong, 0, sw, 2)
    _lk(ng, sw, 0, go, 0)

    note(ng, "FORCE GENERATOR  ·  random force", "OPERATOR", """
    force = random( min force , max force )     Hammer units per second^2

Rolled ONCE per particle from its id, so it is a steady push in a random
direction rather than a jitter - which is what a constant force is.

WHY THERE IS NO NEW PHYSICS HERE. A constant per-particle acceleration is
exactly what gravity already is, so this vector is simply ADDED to the gravity
vector before Movement Basic. It then inherits the whole drag treatment -
including the 30 Hz tick constant - for nothing.

The draw is a VECTOR one, so each axis is independent: min (-100,0,0) to max
(100,0,0) is a sideways shove, not a spherical spray.
""", [salt, salt_i, rv, strong, zero, sw])
    return ng


# =============================================================================
# OPERATOR  ·  Rotation Yaw Flip Random
# =============================================================================

def build_yaw_flip():
    """SFM's `Rotation Yaw Flip Random` (537 uses) / `Randomly Flip Yaw` (25).

        Flip Percentage   0.5 = half the particles, 1.0 = all of them

    ON A CAMERA-FACING CARD, YAW IS A MIRROR. Yawing a billboard 180 degrees
    shows you its back, and the back of a flat card is the same card
    left-right reversed. So this returns +1 or -1 to multiply the card's X
    scale by - which is what the operator is FOR: stopping a repeated sprite
    from reading as repeated."""
    ng = _group("SP · OPERATOR · Rotation Yaw Flip Random",
                "GeometryNodeTree")
    _sock(ng, "Flip", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Flip Percentage", "INPUT", "NodeSocketFloat", 0.5)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-900, 0), (900, 0))
    I = _gin(ng)

    salt = _nd(ng, "ShaderNodeMath", (-700, -240), "salt the seed",
               role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I["Seed"], salt, 0)
    _sv(salt, 1, 111.0)
    salt_i = _nd(ng, "FunctionNodeFloatToInt", (-520, -240),
                 role="INITIALIZER")
    _lk(ng, salt, 0, salt_i, 0)
    rv = _nd(ng, "FunctionNodeRandomValue", (-320, 0), "roll 0..1",
             role="INITIALIZER", data_type="FLOAT")
    _sv(rv, 0, 0.0)
    _sv(rv, 1, 1.0)
    _lk(ng, gi, I["ID"], rv, 2)
    _lk(ng, salt_i, 0, rv, 3)
    hit = _nd(ng, "FunctionNodeCompare", (-100, 0), "under the percentage?",
              role="INITIALIZER", data_type="FLOAT", operation="LESS_THAN")
    _lk(ng, rv, 0, hit, 0)
    _lk(ng, gi, I["Flip Percentage"], hit, 1)
    pick = _nd(ng, "GeometryNodeSwitch", (140, 0), "mirrored, or not",
               role="INITIALIZER", input_type="FLOAT")
    _lk(ng, hit, 0, pick, 0)
    _sv(pick, 1, 1.0)
    _sv(pick, 2, -1.0)
    sw = _nd(ng, "GeometryNodeSwitch", (420, 0), "enabled?",
             role="INITIALIZER", input_type="FLOAT")
    _lk(ng, gi, I["Enable"], sw, 0)
    _sv(sw, 1, 1.0)
    _lk(ng, pick, 0, sw, 2)
    _lk(ng, sw, 0, go, 0)

    note(ng, "OPERATOR  ·  Rotation Yaw Flip Random", "INITIALIZER", """
    flip = ( random(0..1, from the id) < Flip Percentage )  ?  -1  :  +1

and that -1 multiplies the sprite card's X scale.

WHY A MIRROR AND NOT A ROTATION. On a camera-facing card, yaw is not visible
as rotation - the card immediately turns back to face you. Yawing 180 degrees
shows you the BACK of a flat card, and the back of a flat card is the same
card left-right reversed. So the operator's entire visible effect is a mirror,
which is exactly what it is used for.

THREE DIFFERENT OPERATORS LIVE AROUND HERE and they are NOT the same thing:
  Rotation Yaw Flip Random  537 uses.  Flip Percentage. Mirrors. THIS ONE.
  Randomly Flip Yaw          25 uses.  Flip Percentage, always 0.5. Same idea.
  Rotation Yaw Random        22 uses.  yaw_initial / yaw_offset_min / max /
                                       yaw_random_exponent - a real ANGLE, and
                                       only meaningful on a card that is not
                                       camera-facing (orientation type 2).

Decided once at birth from the particle id, so a sprite never flickers between
mirrored and not.
""", [salt, salt_i, rv, hit, pick, sw])
    return ng


# =============================================================================
# INITIALIZER  ·  Velocity Noise
# =============================================================================

def build_velocity_noise():
    """SFM's `Velocity Noise` - and it is NOT a per-frame operator.

    From the Valve documentation: the velocity is "initialized to a select
    range via a noise function", with the noise "mapped based on both time and
    space", the spatial part sampled at the particle's SPAWN LOCATION and the
    time part at its SPAWN TIME - "non-random but vary based on creation time
    and position".

    THAT IS THE WHOLE DIFFERENCE FROM VELOCITY RANDOM, and it decides the
    implementation:

      Velocity Random  an independent draw per particle. White noise. Every
                       particle goes its own way.
      Velocity Noise   one sample of a SMOOTH FIELD at (spawn position, spawn
                       time). Particles born near each other, at near the same
                       moment, get near the same velocity - so it reads as
                       gusts and swirls rather than as scatter.

    Because both coordinates are fixed at birth, this needs NO integration and
    no simulation state. It is a velocity contribution exactly like Velocity
    Random, and it joins the same ADD chain."""
    ng = _group("SP · INITIALIZER · Velocity Noise", "GeometryNodeTree")
    _sock(ng, "Velocity", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Spawn Position", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Birth Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Spatial Scale", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Spatial Offset", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Time Scale", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Time Offset", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Output Min", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Output Max", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Absolute", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Invert Absolute", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1400, 0), (1400, 0))
    I = _gin(ng)

    # noise coordinate = spawn position x spatial scale + spatial offset
    spatial = _nd(ng, "ShaderNodeVectorMath", (-1180, 200), "x spatial scale",
                  role="INITIALIZER", operation="SCALE")
    _lk(ng, gi, I["Spawn Position"], spatial, 0)
    _lk(ng, gi, I["Spatial Scale"], spatial, 3)
    coord = _nd(ng, "ShaderNodeVectorMath", (-980, 200), "+ spatial offset",
                role="INITIALIZER", operation="ADD")
    _lk(ng, spatial, 0, coord, 0)
    _lk(ng, gi, I["Spatial Offset"], coord, 1)

    # the fourth coordinate = birth time x time scale + time offset
    tscale = _nd(ng, "ShaderNodeMath", (-1180, -40), "x time scale",
                 role="TIME", operation="MULTIPLY")
    _lk(ng, gi, I["Birth Time"], tscale, 0)
    _lk(ng, gi, I["Time Scale"], tscale, 1)
    w = _nd(ng, "ShaderNodeMath", (-980, -40), "+ time offset", role="TIME",
            operation="ADD")
    _lk(ng, tscale, 0, w, 0)
    _lk(ng, gi, I["Time Offset"], w, 1)

    #4D SO that TIME is A REAL DIMENSION of the same field, not a separate
    #animation of it. Two particles born a moment apart at the same place
    #must land near each other in the noise, which is what makes the result
    #read as a drifting gust rather than as flicker
    noise = _nd(ng, "ShaderNodeTexNoise", (-760, 100),
                "one smooth field, sampled at birth", role="INITIALIZER",
                noise_dimensions="4D")
    _lk(ng, coord, 0, noise, 0)
    _lk(ng, w, 0, noise, 1)

    #Blender's noise Colour is 0..1 per channel; signed is 2c - 1
    signed = _nd(ng, "ShaderNodeVectorMath", (-520, 100), "-> -1..1",
                 role="INITIALIZER", operation="MULTIPLY_ADD")
    _lk(ng, noise, 1, signed, 0)
    _sv(signed, 1, (2.0, 2.0, 2.0))
    _sv(signed, 2, (-1.0, -1.0, -1.0))
    absed = _nd(ng, "ShaderNodeVectorMath", (-320, -80), "|noise|",
                role="INITIALIZER", operation="ABSOLUTE")
    _lk(ng, signed, 0, absed, 0)
    inverted = _nd(ng, "ShaderNodeVectorMath", (-320, -260), "1 - |noise|",
                   role="INITIALIZER", operation="SUBTRACT")
    _sv(inverted, 0, (1.0, 1.0, 1.0))
    _lk(ng, absed, 0, inverted, 1)
    pick_inv = _nd(ng, "GeometryNodeSwitch", (-120, -180), "inverted?",
                   role="INITIALIZER", input_type="VECTOR")
    _lk(ng, gi, I["Invert Absolute"], pick_inv, 0)
    _lk(ng, absed, 0, pick_inv, 1)
    _lk(ng, inverted, 0, pick_inv, 2)

    # back to 0..1 for the range mapping
    unsigned = _nd(ng, "ShaderNodeVectorMath", (100, 100), "back to 0..1",
                   role="INITIALIZER", operation="MULTIPLY_ADD")
    _lk(ng, signed, 0, unsigned, 0)
    _sv(unsigned, 1, (0.5, 0.5, 0.5))
    _sv(unsigned, 2, (0.5, 0.5, 0.5))
    t = _nd(ng, "GeometryNodeSwitch", (300, 0), "absolute, or signed",
            role="INITIALIZER", input_type="VECTOR")
    _lk(ng, gi, I["Absolute"], t, 0)
    _lk(ng, unsigned, 0, t, 1)
    _lk(ng, pick_inv, 0, t, 2)

    span = _nd(ng, "ShaderNodeVectorMath", (520, -160), "max - min",
               role="INITIALIZER", operation="SUBTRACT")
    _lk(ng, gi, I["Output Max"], span, 0)
    _lk(ng, gi, I["Output Min"], span, 1)
    scaled = _nd(ng, "ShaderNodeVectorMath", (720, -60), "x that",
                 role="INITIALIZER", operation="MULTIPLY")
    _lk(ng, t, 0, scaled, 0)
    _lk(ng, span, 0, scaled, 1)
    mapped = _nd(ng, "ShaderNodeVectorMath", (920, 40), "+ min",
                 role="INITIALIZER", operation="ADD")
    _lk(ng, scaled, 0, mapped, 0)
    _lk(ng, gi, I["Output Min"], mapped, 1)
    strong = _nd(ng, "ShaderNodeVectorMath", (1100, 40), "x strength",
                 role="INITIALIZER", operation="SCALE")
    _lk(ng, mapped, 0, strong, 0)
    _lk(ng, gi, I["Strength"], strong, 3)

    zero = _nd(ng, "ShaderNodeCombineXYZ", (1100, -180), "off = nothing",
               role="INITIALIZER")
    sw = _nd(ng, "GeometryNodeSwitch", (1260, -60), "enabled?",
             role="INITIALIZER", input_type="VECTOR")
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, zero, 0, sw, 1)
    _lk(ng, strong, 0, sw, 2)
    _lk(ng, sw, 0, go, 0)

    note(ng, "INITIALIZER  ·  Velocity Noise", "INITIALIZER", """
    coordinate = spawn position x spatial scale + spatial offset
    w          = spawn TIME     x time scale    + time offset
    velocity   = map( noise4D(coordinate, w) , output min .. output max )

HOW THIS DIFFERS FROM VELOCITY RANDOM, which is the whole point of it:

  Velocity Random  an independent draw per particle. White noise. Every
                   particle goes its own way and the cloud has no structure.
  Velocity Noise   ONE SAMPLE OF A SMOOTH FIELD, taken at the particle's
                   spawn position and spawn time. Particles born near each
                   other at near the same moment get near the same velocity,
                   so the cloud moves in GUSTS and SWIRLS instead of
                   scattering. Valve's own wording: "non-random but vary based
                   on creation time and position".

BOTH COORDINATES ARE FIXED AT BIRTH, so despite living in the operators list
this needs NO simulation state and no integration. It is a velocity
contribution exactly like Velocity Random, and it joins the same ADD chain.

Spatial scale 0 makes every particle sample the SAME point of the field, so
the whole system drifts together - that is a legitimate setting, not a bug.
Larger scales look increasingly random.

The noise is 4D so time is a real dimension of the same field rather than a
separate animation of it - two particles born a moment apart land near each
other in the noise, which is what makes it read as drift rather than flicker.

Absolute folds the field around zero (|n|), and Invert Absolute gives 1 - |n|,
which is how SFM turns a smooth field into ridges.
""", [spatial, coord, tscale, w, noise, signed, absed, inverted, pick_inv,
      unsigned, t, span, scaled, mapped, strong, zero, sw])
    return ng


# =============================================================================
# FORCE GENERATOR  ·  Pull towards control point
# =============================================================================

def build_pull_to_cp():
    """SFM's `Pull towards control point`.

        control point number   which CP to pull towards
        amount of force        Hammer units per second squared
        falloff power          how fast the pull weakens with distance

    POSITION DEPENDENT: the direction changes as the particle moves, so this
    cannot be a closed form. It returns an ACCELERATION, and the caller
    integrates it inside the simulation zone."""
    ng = _group("SP · FORCE · Pull towards control point", "GeometryNodeTree")
    _sock(ng, "Force", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Position", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Control Point", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Amount", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Falloff Power", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1100, 0), (1100, 0))
    I = _gin(ng)

    to_cp = _nd(ng, "ShaderNodeVectorMath", (-880, 120), "particle -> CP",
                role="OPERATOR", operation="SUBTRACT")
    _lk(ng, gi, I["Control Point"], to_cp, 0)
    _lk(ng, gi, I["Position"], to_cp, 1)
    dist = _nd(ng, "ShaderNodeVectorMath", (-680, -60), "how far",
               role="OPERATOR", operation="LENGTH")
    _lk(ng, to_cp, 0, dist, 0)
    # never divide by zero: a particle sitting exactly on the control point
    # has no direction to be pulled in
    safe = _nd(ng, "ShaderNodeMath", (-480, -60), "never zero",
               role="OPERATOR", operation="MAXIMUM")
    _lk(ng, dist, 1, safe, 0)
    _sv(safe, 1, EPS)
    dirn = _nd(ng, "ShaderNodeVectorMath", (-680, 120), "unit direction",
               role="OPERATOR", operation="NORMALIZE")
    _lk(ng, to_cp, 0, dirn, 0)

    fall = _nd(ng, "ShaderNodeMath", (-280, -60), "distance ^ falloff",
               role="OPERATOR", operation="POWER")
    _lk(ng, safe, 0, fall, 0)
    _lk(ng, gi, I["Falloff Power"], fall, 1)
    fall_safe = _nd(ng, "ShaderNodeMath", (-80, -60), "never zero",
                    role="OPERATOR", operation="MAXIMUM")
    _lk(ng, fall, 0, fall_safe, 0)
    _sv(fall_safe, 1, EPS)
    mag = _nd(ng, "ShaderNodeMath", (120, -60), "amount / that",
              role="OPERATOR", operation="DIVIDE")
    _lk(ng, gi, I["Amount"], mag, 0)
    _lk(ng, fall_safe, 0, mag, 1)
    strong = _nd(ng, "ShaderNodeMath", (320, -60), "x strength",
                 role="OPERATOR", operation="MULTIPLY")
    _lk(ng, mag, 0, strong, 0)
    _lk(ng, gi, I["Strength"], strong, 1)
    force = _nd(ng, "ShaderNodeVectorMath", (520, 60), "direction x magnitude",
                role="OPERATOR", operation="SCALE")
    _lk(ng, dirn, 0, force, 0)
    _lk(ng, strong, 0, force, 3)

    zero = _nd(ng, "ShaderNodeCombineXYZ", (520, -220), "off = no pull",
               role="OPERATOR")
    sw = _nd(ng, "GeometryNodeSwitch", (800, 0), "enabled?", role="OPERATOR",
             input_type="VECTOR")
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, zero, 0, sw, 1)
    _lk(ng, force, 0, sw, 2)
    _lk(ng, sw, 0, go, 0)

    note(ng, "FORCE GENERATOR  ·  Pull towards control point", "OPERATOR", """
    force = normalize(CP - position) x  amount / distance ^ falloff power

FALLOFF POWER 0 IS A CONSTANT PULL, the same strength however far away the
particle is. 1 falls off with distance, 2 with distance squared like gravity.
The corpus runs -0.5 to 2, and a NEGATIVE power means the pull gets STRONGER
with distance, which is a real authoring choice and not a mistake.

A NEGATIVE amount pushes instead of pulling.

THIS IS POSITION DEPENDENT, which is why it returns an acceleration instead of
a position. The direction changes as the particle moves, so there is no closed
form - the simulation zone integrates it. That is also why it is the FIRST
thing in this system whose result depends on the frame rate.

Guarded twice against divide-by-zero: a particle sitting exactly on the
control point has no direction to be pulled in, and distance^0 with a negative
power would blow up.
""", [to_cp, dist, safe, dirn, fall, fall_safe, mag, strong, force, zero, sw])
    return ng


# =============================================================================
# FORCE GENERATOR  ·  twist around axis
# =============================================================================

def build_twist_axis():
    """SFM's `twist around axis`.

        amount of force              Hammer units per second squared
        twist axis                   the axis to spin around
        object local space axis 0/1  axis in the CP's frame, or in world space

    POSITION DEPENDENT - the push is tangential, so its direction depends on
    where the particle is around the axis. Returns an ACCELERATION; the caller
    integrates it."""
    ng = _group("SP · FORCE · twist around axis", "GeometryNodeTree")
    _sock(ng, "Force", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Position", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Control Point", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Axis", "INPUT", "NodeSocketVector", (0.0, 0.0, 1.0))
    _sock(ng, "Amount", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1200, 0), (1200, 0))
    I = _gin(ng)

    axis = _nd(ng, "ShaderNodeVectorMath", (-980, -160), "unit axis",
               role="OPERATOR", operation="NORMALIZE")
    _lk(ng, gi, I["Axis"], axis, 0)
    rel = _nd(ng, "ShaderNodeVectorMath", (-980, 120), "particle - CP",
              role="OPERATOR", operation="SUBTRACT")
    _lk(ng, gi, I["Position"], rel, 0)
    _lk(ng, gi, I["Control Point"], rel, 1)

    # the tangent is axis x radius. Taking the cross product with the whole
    # offset rather than only its perpendicular part gives the same direction,
    # bc the component along the axis cancels in the cross product.
    tangent = _nd(ng, "ShaderNodeVectorMath", (-760, 20),
                  "axis x offset = the way round", role="OPERATOR",
                  operation="CROSS_PRODUCT")
    _lk(ng, axis, 0, tangent, 0)
    _lk(ng, rel, 0, tangent, 1)
    unit_t = _nd(ng, "ShaderNodeVectorMath", (-540, 20), "unit tangent",
                 role="OPERATOR", operation="NORMALIZE")
    _lk(ng, tangent, 0, unit_t, 0)

    strong = _nd(ng, "ShaderNodeMath", (-540, -200), "amount x strength",
                 role="OPERATOR", operation="MULTIPLY")
    _lk(ng, gi, I["Amount"], strong, 0)
    _lk(ng, gi, I["Strength"], strong, 1)
    force = _nd(ng, "ShaderNodeVectorMath", (-320, 20), "tangent x that",
                role="OPERATOR", operation="SCALE")
    _lk(ng, unit_t, 0, force, 0)
    _lk(ng, strong, 0, force, 3)

    zero = _nd(ng, "ShaderNodeCombineXYZ", (-320, -260), "off = no twist",
               role="OPERATOR")
    sw = _nd(ng, "GeometryNodeSwitch", (0, 0), "enabled?", role="OPERATOR",
             input_type="VECTOR")
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, zero, 0, sw, 1)
    _lk(ng, force, 0, sw, 2)
    _lk(ng, sw, 0, go, 0)

    note(ng, "FORCE GENERATOR  ·  twist around axis", "OPERATOR", """
    force = normalize( axis x (position - control point) ) x amount

A push at right angles to both the axis and the particle's offset from it -
which is to say, round and round. Positive spins one way, negative the other.

CROSSING WITH THE WHOLE OFFSET IS CORRECT, not sloppy: the component of the
offset that lies ALONG the axis contributes nothing to a cross product with
that axis, so it cancels by itself. There is no need to project it out first.

THIS IS POSITION DEPENDENT, so it returns an acceleration and the simulation
zone integrates it.

⚠️ ONE FIELD IS GENUINELY AMBIGUOUS. Valve's own description calls
`twist axis` "location of the axis in XYZ format", but the corpus holds values
from -1 to 1000, which is far too wide for a unit direction and reads more
like a point. It is treated here as a DIRECTION and normalised, with the axis
passing through the control point. If an imported effect twists about the
wrong line, this is the field to look at first.

A particle exactly ON the axis has no tangent - the cross product is zero and
normalising it yields zero, so it simply feels no force. That is the right
answer and it needs no special case.
""", [axis, rel, tangent, unit_t, strong, force, zero, sw])
    return ng


# =============================================================================
# INITIALIZER  ·  Position Along Path Sequential      (the beam-maker)
# =============================================================================

def build_position_along_path():
    """SFM's `Position Along Path Sequential` - what makes a laser a laser.

        control point number       the START of the path
        end control point number   the END of it
        particles to map from      how many particles span start -> end
          start to end             before the numbering starts over
        bulge                      how far the path bows off the straight
                                   line, in HAMMER UNITS (the corpus runs
                                   -2 to 75, so this is a distance and not a
                                   fraction; negative bows the other way)
        bulge control              where the bow points: 0 random per
                                   particle, 1 the START point's orientation,
                                   2 the END point's
        mid point position         where along the path the bow peaks
        maximum distance           random scatter around the result

    ⚠️ IT IS SEQUENTIAL, NOT RANDOM. Particle n sits at n / (map - 1) of the
    way along, and the (map)th particle starts over at the beginning - that
    ordering is the whole point, because a rope renderer draws its ribbon
    through the particles IN ORDER. Scatter them and you get a scribble."""
    ng = _group("SP · INITIALIZER · Position Along Path Sequential",
                "GeometryNodeTree")
    _sock(ng, "Position", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Start", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "End", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Start Rotation", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "End Rotation", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Particles To Map", "INPUT", "NodeSocketFloat", 100.0)
    _sock(ng, "Bulge", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Bulge Control", "INPUT", "NodeSocketInt", 0, smin=0, smax=2)
    _sock(ng, "Mid Point", "INPUT", "NodeSocketFloat", 0.5)
    _sock(ng, "Max Distance", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Scale", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    # 0.26.3: Position Along Path RANDOM rolls t instead of counting it
    _sock(ng, "Random Fraction", "INPUT", "NodeSocketBool", False)
    gi, go = _io(ng, (-1800, 0), (1500, 0))
    I = _gin(ng)

    # ── t: where along the path this particle sits ───────────────────────
    # WRAP, not MODULO - modulo is truncated and returns negatives, and a
    # negative t would put the head of the beam behind the start point
    n_safe = _nd(ng, "ShaderNodeMath", (-1600, 320), "at least two",
                 role="INITIALIZER", operation="MAXIMUM")
    _lk(ng, gi, I["Particles To Map"], n_safe, 0)
    _sv(n_safe, 1, 2.0)
    idx = _nd(ng, "ShaderNodeMath", (-1400, 320), "id, wrapped",
              role="INITIALIZER", operation="WRAP")
    _lk(ng, gi, I["ID"], idx, 0)
    _lk(ng, n_safe, 0, idx, 1)
    _sv(idx, 2, 0.0)
    span = _nd(ng, "ShaderNodeMath", (-1400, 180), "map - 1",
               role="INITIALIZER", operation="SUBTRACT")
    _lk(ng, n_safe, 0, span, 0)
    _sv(span, 1, 1.0)
    t_seq = _nd(ng, "ShaderNodeMath", (-1200, 260), "t = 0..1 along the path",
                role="INITIALIZER", operation="DIVIDE")
    _lk(ng, idx, 0, t_seq, 0)
    _lk(ng, span, 0, t_seq, 1)
    t_salt = _nd(ng, "ShaderNodeMath", (-1400, 480), "seed + salt",
                 role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I["Seed"], t_salt, 0)
    _sv(t_salt, 1, 523.0)
    t_salt_i = _nd(ng, "FunctionNodeFloatToInt", (-1300, 480),
                   role="INITIALIZER")
    _lk(ng, t_salt, 0, t_salt_i, 0)
    t_roll = _nd(ng, "FunctionNodeRandomValue", (-1200, 480),
                 "t rolled 0..1", role="INITIALIZER", data_type="FLOAT")
    _sv(t_roll, 0, 0.0)
    _sv(t_roll, 1, 1.0)
    _lk(ng, gi, I["ID"], t_roll, 2)
    _lk(ng, t_salt_i, 0, t_roll, 3)
    t = _nd(ng, "GeometryNodeSwitch", (-1040, 320), "counted, or rolled",
            role="INITIALIZER", input_type="FLOAT")
    _lk(ng, gi, I["Random Fraction"], t, 0)
    _lk(ng, t_seq, 0, t, 1)
    _lk(ng, t_roll, 0, t, 2)

    #── the straight line from start to end ──────────────────────────────
    along = _nd(ng, "ShaderNodeVectorMath", (-1400, 20), "start -> end",
                role="INITIALIZER", operation="SUBTRACT")
    _lk(ng, gi, I["End"], along, 0)
    _lk(ng, gi, I["Start"], along, 1)
    step = _nd(ng, "ShaderNodeVectorMath", (-1000, 20), "x t",
               role="INITIALIZER", operation="SCALE")
    _lk(ng, along, 0, step, 0)
    _lk(ng, t, 0, step, 3)
    base = _nd(ng, "ShaderNodeVectorMath", (-800, 20), "the point on the line",
               role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I["Start"], base, 0)
    _lk(ng, step, 0, base, 1)
    unit = _nd(ng, "ShaderNodeVectorMath", (-1200, -140), "beam direction",
               role="INITIALIZER", operation="NORMALIZE")
    _lk(ng, along, 0, unit, 0)

    # ── the bow: zero at both ends, widest at the mid point ──────────────
    # A TRIANGLE, not a sine: `mid point position` names the peak, and a
    # triangle is the only shape that puts it exactly there for any value
    # Both halves are guarded - a mid point of 0 or 1 would divide by zero,
    # and the corpus has values above 1, where the peak lands past the end
    # and the bow simply grows all the way along
    m_lo = _nd(ng, "ShaderNodeMath", (-1400, -320), "mid, never zero",
               role="INITIALIZER", operation="MAXIMUM")
    _lk(ng, gi, I["Mid Point"], m_lo, 0)
    _sv(m_lo, 1, EPS)
    rise = _nd(ng, "ShaderNodeMath", (-1200, -320), "t / mid",
               role="INITIALIZER", operation="DIVIDE")
    _lk(ng, t, 0, rise, 0)
    _lk(ng, m_lo, 0, rise, 1)
    to_end = _nd(ng, "ShaderNodeMath", (-1400, -460), "1 - mid",
                 role="INITIALIZER", operation="SUBTRACT")
    _sv(to_end, 0, 1.0)
    _lk(ng, gi, I["Mid Point"], to_end, 1)
    tail = _nd(ng, "ShaderNodeMath", (-1200, -460), "never zero",
               role="INITIALIZER", operation="MAXIMUM")
    _lk(ng, to_end, 0, tail, 0)
    _sv(tail, 1, EPS)
    left = _nd(ng, "ShaderNodeMath", (-1200, -600), "1 - t",
               role="INITIALIZER", operation="SUBTRACT")
    _sv(left, 0, 1.0)
    _lk(ng, t, 0, left, 1)
    fall = _nd(ng, "ShaderNodeMath", (-1000, -520), "(1 - t) / (1 - mid)",
               role="INITIALIZER", operation="DIVIDE")
    _lk(ng, left, 0, fall, 0)
    _lk(ng, tail, 0, fall, 1)
    hump = _nd(ng, "ShaderNodeMath", (-800, -420), "whichever is smaller",
               role="INITIALIZER", operation="MINIMUM")
    _lk(ng, rise, 0, hump, 0)
    _lk(ng, fall, 0, hump, 1)
    hump_pos = _nd(ng, "ShaderNodeMath", (-620, -420), "never negative",
                   role="INITIALIZER", operation="MAXIMUM")
    _lk(ng, hump, 0, hump_pos, 0)
    _sv(hump_pos, 1, 0.0)

    # ── which way the bow points ─────────────────────────────────────────
    # 1 and 2 take the named control point's own UP axis; 0 rolls a
    # direction per particle. Whatever it's, the component ALONG the beam is
    # removed - a bow parallel to the beam is not a bow, it's a particle
    # sliding along the line it's already on.
    up = _nd(ng, "ShaderNodeCombineXYZ", (-1600, -760), "the CP's own up",
             role="INITIALIZER")
    _sv(up, 2, 1.0)
    rot_pick = _nd(ng, "GeometryNodeSwitch", (-1400, -760), "start or end",
                   role="INITIALIZER", input_type="VECTOR")
    is2 = _nd(ng, "FunctionNodeCompare", (-1600, -900), "control == 2",
              role="INITIALIZER", data_type="INT", operation="EQUAL")
    _lk(ng, gi, I["Bulge Control"], is2, 0)
    _sv(is2, 1, 2)
    _lk(ng, is2, 0, rot_pick, 0)
    _lk(ng, gi, I["Start Rotation"], rot_pick, 1)
    _lk(ng, gi, I["End Rotation"], rot_pick, 2)
    oriented = _nd(ng, "ShaderNodeVectorRotate", (-1200, -760),
                   "into that CP's frame", role="INITIALIZER",
                   rotation_type="EULER_XYZ")
    _lk(ng, up, 0, oriented, 0)
    _lk(ng, rot_pick, 0, oriented, 4)

    rnd_dir = _nd(ng, "FunctionNodeRandomValue", (-1200, -1000),
                  "a direction per particle", role="INITIALIZER",
                  data_type="FLOAT_VECTOR")
    _sv(rnd_dir, 0, (-1.0, -1.0, -1.0))
    _sv(rnd_dir, 1, (1.0, 1.0, 1.0))
    _lk(ng, gi, I["ID"], rnd_dir, 2)
    salt = _nd(ng, "ShaderNodeMath", (-1400, -1120), "salt the seed",
               role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I["Seed"], salt, 0)
    _sv(salt, 1, 311.0)
    salt_i = _nd(ng, "FunctionNodeFloatToInt", (-1300, -1120),
                 role="INITIALIZER")
    _lk(ng, salt, 0, salt_i, 0)
    _lk(ng, salt_i, 0, rnd_dir, 3)

    is0 = _nd(ng, "FunctionNodeCompare", (-1000, -1120), "control == 0",
              role="INITIALIZER", data_type="INT", operation="EQUAL")
    _lk(ng, gi, I["Bulge Control"], is0, 0)
    _sv(is0, 1, 0)
    raw_dir = _nd(ng, "GeometryNodeSwitch", (-820, -880), "random, or the CP",
                  role="INITIALIZER", input_type="VECTOR")
    _lk(ng, is0, 0, raw_dir, 0)
    _lk(ng, oriented, 0, raw_dir, 1)
    _lk(ng, rnd_dir, 0, raw_dir, 2)

    # remove the component that runs along the beam
    dot = _nd(ng, "ShaderNodeVectorMath", (-620, -880), "how much lies along",
              role="INITIALIZER", operation="DOT_PRODUCT")
    _lk(ng, raw_dir, 0, dot, 0)
    _lk(ng, unit, 0, dot, 1)
    proj = _nd(ng, "ShaderNodeVectorMath", (-440, -880), "that much of it",
               role="INITIALIZER", operation="SCALE")
    _lk(ng, unit, 0, proj, 0)
    _lk(ng, dot, 1, proj, 3)
    perp = _nd(ng, "ShaderNodeVectorMath", (-260, -880), "the rest: sideways",
               role="INITIALIZER", operation="SUBTRACT")
    _lk(ng, raw_dir, 0, perp, 0)
    _lk(ng, proj, 0, perp, 1)
    # ⚠️ A DIRECTION PARALLEL TO the BEAM LEAVES nothing, and normalizing zero
    # is zero - the bow would silently vanish. Fall back to whichever of the
    # world axes is least parallel, the same trick the rope's width axis uses
    fb_a = _nd(ng, "ShaderNodeVectorMath", (-440, -1060), "beam x up",
               role="INITIALIZER", operation="CROSS_PRODUCT")
    _lk(ng, unit, 0, fb_a, 0)
    _sv(fb_a, 1, (0.0, 0.0, 1.0))
    fb_b = _nd(ng, "ShaderNodeVectorMath", (-440, -1220), "beam x X",
               role="INITIALIZER", operation="CROSS_PRODUCT")
    _lk(ng, unit, 0, fb_b, 0)
    _sv(fb_b, 1, (1.0, 0.0, 0.0))
    la = _nd(ng, "ShaderNodeVectorMath", (-260, -1060), "how long",
             role="INITIALIZER", operation="LENGTH")
    _lk(ng, fb_a, 0, la, 0)
    lb = _nd(ng, "ShaderNodeVectorMath", (-260, -1220), "how long",
             role="INITIALIZER", operation="LENGTH")
    _lk(ng, fb_b, 0, lb, 0)
    longer = _nd(ng, "FunctionNodeCompare", (-100, -1140), "a beats b?",
                 role="INITIALIZER", data_type="FLOAT",
                 operation="GREATER_THAN")
    _lk(ng, la, 1, longer, 0)
    _lk(ng, lb, 1, longer, 1)
    fallback = _nd(ng, "GeometryNodeSwitch", (60, -1140), "the safe one",
                   role="INITIALIZER", input_type="VECTOR")
    _lk(ng, longer, 0, fallback, 0)
    _lk(ng, fb_b, 0, fallback, 1)
    _lk(ng, fb_a, 0, fallback, 2)
    perp_len = _nd(ng, "ShaderNodeVectorMath", (-80, -880), "anything left?",
                   role="INITIALIZER", operation="LENGTH")
    _lk(ng, perp, 0, perp_len, 0)
    flat = _nd(ng, "FunctionNodeCompare", (80, -880), "collapsed?",
               role="INITIALIZER", data_type="FLOAT", operation="LESS_THAN")
    _lk(ng, perp_len, 1, flat, 0)
    _sv(flat, 1, 1e-4)
    side = _nd(ng, "GeometryNodeSwitch", (240, -880), "sideways, guaranteed",
               role="INITIALIZER", input_type="VECTOR")
    _lk(ng, flat, 0, side, 0)
    _lk(ng, perp, 0, side, 1)
    _lk(ng, fallback, 0, side, 2)
    side_n = _nd(ng, "ShaderNodeVectorMath", (420, -880), "as a direction",
                 role="INITIALIZER", operation="NORMALIZE")
    _lk(ng, side, 0, side_n, 0)

    bulge_s = _nd(ng, "ShaderNodeMath", (-620, -240), "bulge x Scale",
                  role="INITIALIZER", operation="MULTIPLY")
    _lk(ng, gi, I["Bulge"], bulge_s, 0)
    _lk(ng, gi, I["Scale"], bulge_s, 1)
    bow_amt = _nd(ng, "ShaderNodeMath", (-440, -320), "x the hump",
                  role="INITIALIZER", operation="MULTIPLY")
    _lk(ng, bulge_s, 0, bow_amt, 0)
    _lk(ng, hump_pos, 0, bow_amt, 1)
    bow = _nd(ng, "ShaderNodeVectorMath", (600, -400), "the bow itself",
              role="INITIALIZER", operation="SCALE")
    _lk(ng, side_n, 0, bow, 0)
    _lk(ng, bow_amt, 0, bow, 3)

    # ── the random scatter around it ─────────────────────────────────────
    jitter = _nd(ng, "FunctionNodeRandomValue", (-620, 500), "scatter",
                 role="INITIALIZER", data_type="FLOAT_VECTOR")
    _sv(jitter, 0, (-1.0, -1.0, -1.0))
    _sv(jitter, 1, (1.0, 1.0, 1.0))
    _lk(ng, gi, I["ID"], jitter, 2)
    salt2 = _nd(ng, "ShaderNodeMath", (-820, 620), "salt the seed",
                role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I["Seed"], salt2, 0)
    _sv(salt2, 1, 907.0)
    salt2_i = _nd(ng, "FunctionNodeFloatToInt", (-700, 620),
                  role="INITIALIZER")
    _lk(ng, salt2, 0, salt2_i, 0)
    _lk(ng, salt2_i, 0, jitter, 3)
    jit_n = _nd(ng, "ShaderNodeVectorMath", (-420, 500), "as a direction",
                role="INITIALIZER", operation="NORMALIZE")
    _lk(ng, jitter, 0, jit_n, 0)
    dist_s = _nd(ng, "ShaderNodeMath", (-620, 380), "max distance x Scale",
                 role="INITIALIZER", operation="MULTIPLY")
    _lk(ng, gi, I["Max Distance"], dist_s, 0)
    _lk(ng, gi, I["Scale"], dist_s, 1)
    jit_r = _nd(ng, "FunctionNodeRandomValue", (-420, 340), "how far out",
                role="INITIALIZER", data_type="FLOAT")
    _sv(jit_r, 0, 0.0)
    _lk(ng, dist_s, 0, jit_r, 1)
    _lk(ng, gi, I["ID"], jit_r, 2)
    _lk(ng, salt2_i, 0, jit_r, 3)
    scatter = _nd(ng, "ShaderNodeVectorMath", (-220, 420), "the scatter",
                  role="INITIALIZER", operation="SCALE")
    _lk(ng, jit_n, 0, scatter, 0)
    _lk(ng, jit_r, 0, scatter, 3)

    total = _nd(ng, "ShaderNodeVectorMath", (860, 0), "line + bow",
                role="INITIALIZER", operation="ADD")
    _lk(ng, base, 0, total, 0)
    _lk(ng, bow, 0, total, 1)
    final = _nd(ng, "ShaderNodeVectorMath", (1040, 0), "+ scatter",
                role="INITIALIZER", operation="ADD")
    _lk(ng, total, 0, final, 0)
    _lk(ng, scatter, 0, final, 1)

    sw = _nd(ng, "GeometryNodeSwitch", (1260, 0), "enabled?",
             role="INITIALIZER", input_type="VECTOR")
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, gi, I["Start"], sw, 1)
    _lk(ng, final, 0, sw, 2)
    _lk(ng, sw, 0, go, 0)

    note(ng, "INITIALIZER  ·  Position Along Path Sequential", "INITIALIZER",
         """
    t        = wrap(particle id, particles to map) / (particles to map - 1)
    position = lerp(start CP, end CP, t)  +  bow  +  scatter

SEQUENTIAL IS THE WHOLE POINT. Particle 0 sits on the start control point,
the last one on the end control point, and the next particle after that
starts over at the beginning. A rope renderer draws its ribbon through the
particles IN ORDER, so this ordering IS the beam - randomise it and the same
data draws a scribble.

BULGE IS A DISTANCE IN HAMMER UNITS, not a fraction of the path. The corpus
runs -2 to 75 across 3874 uses; a fraction would make 75 meaningless.
Negative simply bows the other way.

THE BOW IS A TRIANGLE PEAKING AT `mid point position`, because that field
names where the peak goes and only a triangle puts it exactly there. Real
files carry mid points above 1, where the peak lands past the end and the bow
just keeps growing - that falls out of the same maths, no special case.

⚠️ THE BOW DIRECTION HAS THE BEAM COMPONENT REMOVED. A bow pointing along the
beam is not a bow - it slides the particle along the line it is already on.
And when the chosen direction is entirely parallel, subtracting it leaves
zero, which normalises to zero and loses the bow silently: the fallback takes
whichever of `beam x Z` and `beam x X` is longer, and a direction cannot be
parallel to both.
""", [n_safe, idx, span, t, along, step, base, unit, m_lo, rise, to_end, tail,
      left, fall, hump, hump_pos, up, rot_pick, is2, oriented, rnd_dir, salt,
      salt_i, is0, raw_dir, dot, proj, perp, fb_a, fb_b, la, lb, longer,
      fallback, perp_len, flat, side, side_n, bulge_s, bow_amt, bow, jitter,
      salt2, salt2_i, jit_n, dist_s, jit_r, scatter, total, final, sw])
    return ng


# =============================================================================
# EMITTER  ·  emit_instantaneously
# =============================================================================

def build_emit_instant():
    """SFM's `emit_instantaneously`: one burst, then nothing.

        emission_start_time   when the burst happens
        num_to_emit           how many
        num_to_emit_minimum   the other end of a range, -1 = not used

    Fires on the single frame where the clock CROSSES the start time, so the
    burst happens exactly once however long the shot is."""
    ng = _group("SP · EMITTER · emit_instantaneously", "GeometryNodeTree")
    _sock(ng, "Count", "OUTPUT", "NodeSocketInt")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Delta Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Start Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Count Min", "INPUT", "NodeSocketFloat", -1.0)
    _sock(ng, "Count Max", "INPUT", "NodeSocketFloat", 100.0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-1200, 0), (1200, 0))
    I = _gin(ng)

    #the CROSSING TEST, not "time >= start". A plain >= test re-fires the
    #burst on every single frame after the start time
    now = _nd(ng, "FunctionNodeCompare", (-980, 180), "reached it?",
              role="EMITTER", data_type="FLOAT", operation="GREATER_EQUAL")
    _lk(ng, gi, I["Time"], now, 0)
    _lk(ng, gi, I["Start Time"], now, 1)
    prev_t = _nd(ng, "ShaderNodeMath", (-980, 20), "the previous frame",
                 role="TIME", operation="SUBTRACT")
    _lk(ng, gi, I["Time"], prev_t, 0)
    _lk(ng, gi, I["Delta Time"], prev_t, 1)
    was = _nd(ng, "FunctionNodeCompare", (-760, 20), "had it already?",
              role="EMITTER", data_type="FLOAT", operation="LESS_THAN")
    _lk(ng, prev_t, 0, was, 0)
    _lk(ng, gi, I["Start Time"], was, 1)
    # ...or THIS IS the VERY first FRAME. Outside a simulation zone the clock
    # starts at 0, so a burst authored at start_time 0 - the commonest value
    # there's - would test "0 < 0" and never fire at all
    first = _nd(ng, "FunctionNodeCompare", (-760, -100), "or the first frame?",
                role="TIME", data_type="FLOAT", operation="LESS_EQUAL")
    _lk(ng, prev_t, 0, first, 0)
    _sv(first, 1, 0.0)
    # ⚠️ ...AND THE ZONE'S FIRST FRAME is not that FRAME. A simulation zone
    # reports DELTA TIME 0 on the frame it starts on, so `prev_t` there's the
    # CURRENT time, not 0 - measured 0.033 with the playhead on frame 1. Both
    # tests above then read false and the burst is lost for the whole shot,
    # which is exactly why every start_time 0 burst returned nothing. There is
    # no previous frame to have missed, so dt == 0 is "the first frame".
    dt0 = _nd(ng, "FunctionNodeCompare", (-760, -220), "no previous frame",
              role="TIME", data_type="FLOAT", operation="LESS_EQUAL")
    _lk(ng, gi, I["Delta Time"], dt0, 0)
    _sv(dt0, 1, 0.0)
    started = _nd(ng, "FunctionNodeBooleanMath", (-540, -180),
                  "the clock has no history", role="TIME", operation="OR")
    _lk(ng, first, 0, started, 0)
    _lk(ng, dt0, 0, started, 1)
    fresh = _nd(ng, "FunctionNodeBooleanMath", (-540, -60), "not yet fired",
                role="EMITTER", operation="OR")
    _lk(ng, was, 0, fresh, 0)
    _lk(ng, started, 0, fresh, 1)
    crossing = _nd(ng, "FunctionNodeBooleanMath", (-540, 100),
                   "this frame, and only this frame", role="EMITTER",
                   operation="AND")
    _lk(ng, now, 0, crossing, 0)
    _lk(ng, fresh, 0, crossing, 1)
    fire = _nd(ng, "FunctionNodeBooleanMath", (-320, 100), "and switched on?",
               role="EMITTER", operation="AND")
    _lk(ng, crossing, 0, fire, 0)
    _lk(ng, gi, I["Enable"], fire, 1)

    # num_to_emit_minimum -1 means "not used" - emit exactly num_to_emit
    used = _nd(ng, "FunctionNodeCompare", (-980, -220), "is a minimum set?",
               role="EMITTER", data_type="FLOAT", operation="GREATER_EQUAL")
    _lk(ng, gi, I["Count Min"], used, 0)
    _sv(used, 1, 0.0)
    lo = _nd(ng, "GeometryNodeSwitch", (-760, -220), "the low end",
             role="EMITTER", input_type="FLOAT")
    _lk(ng, used, 0, lo, 0)
    _lk(ng, gi, I["Count Max"], lo, 1)
    _lk(ng, gi, I["Count Min"], lo, 2)
    # ⚠️ NOT `Random Value` - IT IS A FIELD NODE and this IS NOT A FIELD.
    # A burst size is one number for the whole system, and it is consumed as
    # one: it ends up as a point COUNT. Blender doesn't evaluate a field in
    # that position, it substitutes the socket's type default - ZERO - so the
    # burst asked for nothing, on every frame, however correct the crossing
    # test was. It looks fine in any test that reads the count per point,
    # bc there it is a field context. Same seed in, same number out,
    # built from single-value maths instead
    hashed = _nd(ng, "ShaderNodeMath", (-760, -400), "seed, stirred",
                 role="EMITTER", operation="MULTIPLY_ADD")
    _lk(ng, gi, I["Seed"], hashed, 0)
    _sv(hashed, 1, 12.9898)
    _sv(hashed, 2, 78.233)
    wave = _nd(ng, "ShaderNodeMath", (-620, -400), "sin", role="EMITTER",
               operation="SINE")
    _lk(ng, hashed, 0, wave, 0)
    scaled = _nd(ng, "ShaderNodeMath", (-480, -400), "x a big number",
                 role="EMITTER", operation="MULTIPLY")
    _lk(ng, wave, 0, scaled, 0)
    _sv(scaled, 1, 43758.5453)
    roll = _nd(ng, "ShaderNodeMath", (-340, -400), "keep the fraction: 0..1",
               role="EMITTER", operation="FRACT")
    _lk(ng, scaled, 0, roll, 0)
    span = _nd(ng, "ShaderNodeMath", (-340, -260), "how wide the range is",
               role="EMITTER", operation="SUBTRACT")
    _lk(ng, gi, I["Count Max"], span, 0)
    _lk(ng, lo, 0, span, 1)
    rnd = _nd(ng, "ShaderNodeMath", (-200, -300), "how many",
              role="EMITTER", operation="MULTIPLY_ADD")
    _lk(ng, roll, 0, rnd, 0)
    _lk(ng, span, 0, rnd, 1)
    _lk(ng, lo, 0, rnd, 2)

    n = _nd(ng, "GeometryNodeSwitch", (-100, 0), "this frame, or none",
            role="EMITTER", input_type="FLOAT")
    _lk(ng, fire, 0, n, 0)
    _sv(n, 1, 0.0)
    _lk(ng, rnd, 0, n, 2)
    n_i = _nd(ng, "FunctionNodeFloatToInt", (140, 0), "as a count",
              role="EMITTER", rounding_mode="ROUND")
    _lk(ng, n, 0, n_i, 0)
    _lk(ng, n_i, 0, go, 0)

    note(ng, "EMITTER  ·  emit_instantaneously", "EMITTER", """
    count = ( the clock CROSSED start time this frame )  ?  num_to_emit  :  0

THE CROSSING TEST IS THE WHOLE OPERATOR. "time >= start_time" would re-fire
the burst on every frame for the rest of the shot; it has to be true on the
one frame where the previous frame was still before the start.

A START TIME OF 0 STILL FIRES, AND THAT TOOK TWO GOES. A plain
"previous < start" test compares 0 < 0 on the opening frame and never fires -
and 0 is the commonest authored start time there is. The obvious guard,
"previous time <= 0", is right everywhere EXCEPT inside a simulation zone,
which is the only place this operator actually runs: a zone reports DELTA TIME
0 on the frame it starts on, so previous = current - 0 = the current time.
Measured: 0.033 on frame 1, both tests false, burst lost for the whole shot.
The zone's opening frame is recognised by DELTA TIME 0 instead - there is no
previous frame, so there is nothing the burst can have been missed by.

num_to_emit_minimum -1 MEANS "NOT USED" and the burst is exactly num_to_emit.
Set it to 0 or more and the size of the burst is randomised between the two.
Reading -1 as a real minimum would ask for a negative number of particles.

THE SIZE OF THE BURST IS ROLLED WITH PLAIN MATHS, NOT `Random Value`. That
node is a FIELD - it answers per element - and a burst size is ONE number,
consumed as a point count. Blender does not evaluate a field asked for as a
single value; it hands back the type default, ZERO, and the burst quietly
asks for nothing forever. fract(sin(seed x 12.9898 + 78.233) x 43758.5453)
is the same roll in single-value maths.

This feeds the SAME cap as emit_continuously: a burst is throttled by
max_particles like anything else, so asking for 2000 with a cap of 200 gets
200 and the rest are simply never born - SFM does not queue them.
""", [now, prev_t, was, first, dt0, started, fresh, crossing, fire, used, lo,
      hashed, wave, scaled, roll, span, rnd, n, n_i])
    return ng


# =============================================================================
# OPERATOR  ·  Alpha Fade and Decay        (2001 uses - the most common)
# =============================================================================

def build_alpha_fade_and_decay():
    """Fade in from start_alpha, hold, fade out to end_alpha.

    One operator doing what Alpha Fade In Random and Alpha Fade Out Random do
    separately, with FIXED times instead of a per-particle roll - which is why
    it is the common one: most effects want every particle to fade together.

    TIMES ARE FRACTIONS OF LIFE. The corpus keeps fade-in inside 0..1 with an
    average of 0.26; only a proportion reads like that.

    ⚠️ AND SOME ARE PAST 1 - start_fade_out_time reaches 12. That is not a
    mistake to clean up: past 1 it means "never gets there", and a CLAMPED
    ramp expresses that exactly by never completing. Rescaling those values
    into range would invent a fade the author deliberately switched off.

    ⚠️ A ZERO-LENGTH WINDOW RETURNS ZERO. Map Range with from_min == from_max
    collapses, and start_fade_in_time == end_fade_in_time == 0 is the single
    most common setting in the corpus - so with no guard, the most popular
    alpha operator in TF2 makes every particle invisible. Both windows are
    floored."""
    ng = _group("SP · OPERATOR · Alpha Fade and Decay", "GeometryNodeTree")
    _sock(ng, "Alpha", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Alpha In", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Age", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Lifetime", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Start Alpha", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "End Alpha", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Start Fade In", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "End Fade In", "INPUT", "NodeSocketFloat", 0.5)
    _sock(ng, "Start Fade Out", "INPUT", "NodeSocketFloat", 0.5)
    _sock(ng, "End Fade Out", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1200, 0), (1100, 0))
    I = _gin(ng)

    life = _nd(ng, "ShaderNodeMath", (-1000, -260), "lifetime, never zero",
               role="TIME", operation="MAXIMUM")
    _lk(ng, gi, I["Lifetime"], life, 0)
    _sv(life, 1, EPS)
    frac = _nd(ng, "ShaderNodeMath", (-820, -160), "age / lifetime",
               role="TIME", operation="DIVIDE")
    _lk(ng, gi, I["Age"], frac, 0)
    _lk(ng, life, 0, frac, 1)

    def window(a, b, y):
        """b, floored just above a - a collapsed Map Range returns 0."""
        n = _nd(ng, "ShaderNodeMath", (-620, y), "window, never zero-length",
                role="OPERATOR", operation="ADD")
        _lk(ng, gi, I[a], n, 0)
        _sv(n, 1, EPS)
        m = _nd(ng, "ShaderNodeMath", (-440, y), "the later of the two",
                role="OPERATOR", operation="MAXIMUM")
        _lk(ng, gi, I[b], m, 0)
        _lk(ng, n, 0, m, 1)
        return m

    in_end = window("Start Fade In", "End Fade In", 220)
    out_end = window("Start Fade Out", "End Fade Out", -420)

    rise = _nd(ng, "ShaderNodeMapRange", (-220, 260),
               "start_alpha -> normal", role="OPERATOR", clamp=True)
    _lk(ng, frac, 0, rise, 0)
    _lk(ng, gi, I["Start Fade In"], rise, 1)
    _lk(ng, in_end, 0, rise, 2)
    _lk(ng, gi, I["Start Alpha"], rise, 3)
    _sv(rise, 4, 1.0)

    # 0.24.1: the FADE-OUT IS (1 - x)^2, MEASURED. Kit 2's default row,
    # read back through the editor's double draw, fits (1 - x)^2 per draw
    # to 0.01-0.03 alpha; a straight line is 0.1-0.25 too bright late in life
    xo = _nd(ng, "ShaderNodeMapRange", (-220, -380), "fade-out progress x",
             role="OPERATOR", clamp=True)
    _lk(ng, frac, 0, xo, 0)
    _lk(ng, gi, I["Start Fade Out"], xo, 1)
    _lk(ng, out_end, 0, xo, 2)
    _sv(xo, 3, 0.0)
    _sv(xo, 4, 1.0)
    keep = _nd(ng, "ShaderNodeMath", (-40, -460), "1 - x", role="OPERATOR",
               operation="SUBTRACT")
    _sv(keep, 0, 1.0)
    _lk(ng, xo, 0, keep, 1)
    sq = _nd(ng, "ShaderNodeMath", (120, -460), "(1 - x)^2  (measured)",
             role="OPERATOR", operation="POWER")
    _lk(ng, keep, 0, sq, 0)
    _sv(sq, 1, 2.0)
    fall = _nd(ng, "ShaderNodeMix", (-220, -560), "end_alpha -> normal",
               role="OPERATOR", data_type="FLOAT", factor_mode="UNIFORM")
    _lk(ng, sq, 0, fall, 0)
    _lk(ng, gi, I["End Alpha"], fall, 2)
    _sv(fall, 3, 1.0)

    both = _nd(ng, "ShaderNodeMath", (60, 0), "rise x fall", role="OPERATOR",
               operation="MULTIPLY")
    _lk(ng, rise, 0, both, 0)
    _lk(ng, fall, 0, both, 1)
    applied = _nd(ng, "ShaderNodeMath", (260, 0), "x the alpha it was given",
                  role="OPERATOR", operation="MULTIPLY")
    _lk(ng, gi, I["Alpha In"], applied, 0)
    _lk(ng, both, 0, applied, 1)
    strong = _nd(ng, "ShaderNodeMath", (460, -160), "x envelope",
                 role="OPERATOR", operation="MULTIPLY")
    _lk(ng, applied, 0, strong, 0)
    _lk(ng, gi, I["Strength"], strong, 1)
    out = _nd(ng, "GeometryNodeSwitch", (680, 0), "enabled?", role="OPERATOR",
              input_type="FLOAT")
    _lk(ng, gi, I["Enable"], out, 0)
    _lk(ng, gi, I["Alpha In"], out, 1)
    _lk(ng, strong, 0, out, 2)
    _lk(ng, out, 0, go, 0)

    note(ng, "OPERATOR  ·  Alpha Fade and Decay", "OPERATOR", """
THE most common alpha operator in TF2 - 2001 uses, in 92 of the 97 packs.

    rise = ramp from start_alpha to 1, over start_fade_in .. end_fade_in
    fall = ramp from 1 to end_alpha, over start_fade_out .. end_fade_out
    alpha = alpha_in x rise x fall

TIMES ARE FRACTIONS OF LIFE, not seconds - which is the opposite of Color
Fade sitting right next to it in the same section. Read the unit, never the
name.

VALUES PAST 1 ARE MEANINGFUL. start_fade_out_time reaches 12 in real files:
past 1 the particle dies before the fade starts, so it never fades at all.
The clamped ramp says that correctly by never completing - "fixing" those
numbers into range would invent a fade the author switched off on purpose.

⚠️ THE ZERO-LENGTH WINDOW WOULD HAVE MADE EVERY PARTICLE INVISIBLE. Map Range
with from_min == from_max returns 0, and start = end = 0 is the commonest
setting there is. Both windows are floored by EPS.
""", [life, frac, in_end, out_end, rise, fall, both, applied, strong, out])
    return ng


# =============================================================================
# OPERATOR  ·  Remap Distance to Control Point to Scalar     (628 uses here)
# =============================================================================

def build_remap_distance_cp():
    """The distance-driven taper: distance to a control point -> radius/alpha.

    A hologram beam's dots grow with height because this remaps each
    particle's CURRENT distance to CP0 into its radius. Pure function of the
    evaluated position, so it needs no integration and stays exact.

        d   = |position - CP|
        t   = clamp( (d - distance min) / (distance max - distance min) )
        out = mix(output min, output max, t)        <- the CLAMP is the cap

    Source's field ids: 3 = radius, 7 = alpha. Anything else passes the
    particle through untouched (and the importer reports the field id)."""
    ng = _group("SP · OPERATOR · Remap Distance to CP", "GeometryNodeTree")
    _sock(ng, "Radius", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Alpha", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Position", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "CP Position", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Distance Min", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Distance Max", "INPUT", "NodeSocketFloat", 128.0)
    _sock(ng, "Output Min", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Output Max", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Output Field", "INPUT", "NodeSocketInt", 3)
    _sock(ng, "Scale Initial", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Radius In", "INPUT", "NodeSocketFloat", 8.0)
    _sock(ng, "Alpha In", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Scale", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1300, 0), (1100, 0))
    I = _gin(ng)

    diff = _nd(ng, "ShaderNodeVectorMath", (-1050, 260), "particle -> CP",
               role="OPERATOR", operation="SUBTRACT")
    _lk(ng, gi, I["Position"], diff, 0)
    _lk(ng, gi, I["CP Position"], diff, 1)
    dist = _nd(ng, "ShaderNodeVectorMath", (-870, 260), "how far",
               role="OPERATOR", operation="LENGTH")
    _lk(ng, diff, 0, dist, 0)

    # the thresholds are authored in Hammer units; positions arrive in
    # scene units, so the window scales and the output doesn't
    dmin_s = _nd(ng, "ShaderNodeMath", (-1050, 60), "distance min x scale",
                 role="OPERATOR", operation="MULTIPLY")
    _lk(ng, gi, I["Distance Min"], dmin_s, 0)
    _lk(ng, gi, I["Scale"], dmin_s, 1)
    dmax_s = _nd(ng, "ShaderNodeMath", (-1050, -80), "distance max x scale",
                 role="OPERATOR", operation="MULTIPLY")
    _lk(ng, gi, I["Distance Max"], dmax_s, 0)
    _lk(ng, gi, I["Scale"], dmax_s, 1)
    floor_w = _nd(ng, "ShaderNodeMath", (-870, 20), "window, never zero",
                  role="OPERATOR", operation="ADD")
    _lk(ng, dmin_s, 0, floor_w, 0)
    _sv(floor_w, 1, EPS)
    fmax = _nd(ng, "ShaderNodeMath", (-690, -20), "the later of the two",
               role="OPERATOR", operation="MAXIMUM")
    _lk(ng, dmax_s, 0, fmax, 0)
    _lk(ng, floor_w, 0, fmax, 1)

    remap = _nd(ng, "ShaderNodeMapRange", (-500, 140),
                "distance -> output, clamped (the cap)", role="OPERATOR",
                clamp=True)
    _lk(ng, dist, 1, remap, 0)
    _lk(ng, dmin_s, 0, remap, 1)
    _lk(ng, fmax, 0, remap, 2)
    _lk(ng, gi, I["Output Min"], remap, 3)
    _lk(ng, gi, I["Output Max"], remap, 4)

    s_on = _nd(ng, "ShaderNodeMath", (-500, -160), "strength, gated",
               role="OPERATOR", operation="MULTIPLY")
    _lk(ng, gi, I["Strength"], s_on, 0)
    _lk(ng, gi, I["Enable"], s_on, 1)

    def branch(field_id, in_name, y):
        """One output field: SET the remapped value, or scale the initial."""
        scaled = _nd(ng, "ShaderNodeMath", (-260, y),
                     f"x the rolled {in_name.lower()}", role="OPERATOR",
                     operation="MULTIPLY")
        _lk(ng, gi, I[in_name], scaled, 0)
        _lk(ng, remap, 0, scaled, 1)
        val = _nd(ng, "GeometryNodeSwitch", (-80, y),
                  "set, or scale the initial", role="OPERATOR",
                  input_type="FLOAT")
        _lk(ng, gi, I["Scale Initial"], val, 0)
        _lk(ng, remap, 0, val, 1)
        _lk(ng, scaled, 0, val, 2)
        is_f = _nd(ng, "FunctionNodeCompare", (-80, y - 160),
                   f"field == {field_id}?", role="OPERATOR",
                   data_type="INT", operation="EQUAL")
        _lk(ng, gi, I["Output Field"], is_f, 0)
        _sv(is_f, 1, field_id)
        f = _nd(ng, "ShaderNodeMath", (120, y - 100), "only that field",
                role="OPERATOR", operation="MULTIPLY")
        _lk(ng, s_on, 0, f, 0)
        _lk(ng, is_f, 0, f, 1)
        mix = _nd(ng, "ShaderNodeMix", (320, y), "applied", role="OPERATOR",
                  data_type="FLOAT", factor_mode="UNIFORM")
        _lk(ng, f, 0, mix, 0)
        _lk(ng, gi, I[in_name], mix, 2)
        _lk(ng, val, 0, mix, 3)
        return [scaled, val, is_f, f, mix], mix

    r_nodes, r_mix = branch(3, "Radius In", 240)
    a_nodes, a_mix = branch(7, "Alpha In", -240)
    _lk(ng, r_mix, 0, go, 0)
    _lk(ng, a_mix, 0, go, 1)

    note(ng, "OPERATOR  ·  Remap Distance to Control Point to Scalar",
         "OPERATOR", """
The distance-driven taper - how a hologram beam gets thin at the bottom and
fat at the top.

    d   = |particle position - control point|
    t   = (d - distance min) / (distance max - distance min),  clamped 0..1
    out = output min + t x (output max - output min)

THE CLAMP IS THE CAP: outside the distance window the output just sits at
output min / output max. Field 3 writes RADIUS, field 7 writes ALPHA (a 0..1
factor); any other field id passes the particle through and the importer says
so. "Scale Initial" multiplies the initializer's rolled value instead of
replacing it.

POSITION DEPENDENT AND STILL EXACT: the position it reads is the same closed
form the renderer places the particle with, so no per-frame integration is
needed and scrubbing stays correct.
""", [diff, dist, dmin_s, dmax_s, floor_w, fmax, remap, s_on]
         + r_nodes + a_nodes)
    return ng


def build_remap_percentage_cps():
    """SFM's `Remap Percentage Between Two Control Points to Scalar` (3.0.2).

        radial  t = |position - start CP| / |end CP - start CP|
        else    t = (position - start CP) . dir / |end CP - start CP|
        out     = map(t, percentage min .. max -> output min .. max), CLAMPED

    Percentage min may sit above max - Map Range reverses, which is how the
    beams in the user's library taper (1 -> 0: output max at the start CP).
    Field 3 = radius, 7 = alpha; Scale Initial multiplies the rolled value."""
    ng = _group("SP · OPERATOR · Remap Percentage Between Two CPs",
                "GeometryNodeTree")
    _sock(ng, "Radius", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Alpha", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Position", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Start CP Position", "INPUT", "NodeSocketVector",
          (0.0, 0.0, 0.0))
    _sock(ng, "End CP Position", "INPUT", "NodeSocketVector",
          (0.0, 0.0, 0.0))
    _sock(ng, "Percentage Min", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Percentage Max", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Output Min", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Output Max", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Output Field", "INPUT", "NodeSocketInt", 3)
    _sock(ng, "Scale Initial", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Radial", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Radius In", "INPUT", "NodeSocketFloat", 8.0)
    _sock(ng, "Alpha In", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1500, 0), (1100, 0))
    I = _gin(ng)

    span_v = _nd(ng, "ShaderNodeVectorMath", (-1250, 300), "start -> end",
                 role="OPERATOR", operation="SUBTRACT")
    _lk(ng, gi, I["End CP Position"], span_v, 0)
    _lk(ng, gi, I["Start CP Position"], span_v, 1)
    span_len = _nd(ng, "ShaderNodeVectorMath", (-1070, 300), "how far apart",
                   role="OPERATOR", operation="LENGTH")
    _lk(ng, span_v, 0, span_len, 0)
    span_safe = _nd(ng, "ShaderNodeMath", (-890, 300), "never zero",
                    role="OPERATOR", operation="MAXIMUM")
    _lk(ng, span_len, 1, span_safe, 0)
    _sv(span_safe, 1, EPS)
    rel = _nd(ng, "ShaderNodeVectorMath", (-1250, 120), "start -> particle",
              role="OPERATOR", operation="SUBTRACT")
    _lk(ng, gi, I["Position"], rel, 0)
    _lk(ng, gi, I["Start CP Position"], rel, 1)
    rel_len = _nd(ng, "ShaderNodeVectorMath", (-1070, 120), "radial: how far",
                  role="OPERATOR", operation="LENGTH")
    _lk(ng, rel, 0, rel_len, 0)
    dir_n = _nd(ng, "ShaderNodeVectorMath", (-1070, -40), "the line's direction",
                role="OPERATOR", operation="NORMALIZE")
    _lk(ng, span_v, 0, dir_n, 0)
    along = _nd(ng, "ShaderNodeVectorMath", (-890, -40), "along the line",
                role="OPERATOR", operation="DOT_PRODUCT")
    _lk(ng, rel, 0, along, 0)
    _lk(ng, dir_n, 0, along, 1)
    pick = _nd(ng, "GeometryNodeSwitch", (-710, 120), "radial, or along",
               role="OPERATOR", input_type="FLOAT")
    _lk(ng, gi, I["Radial"], pick, 0)
    _lk(ng, along, "Value", pick, 1)
    _lk(ng, rel_len, "Value", pick, 2)
    pct = _nd(ng, "ShaderNodeMath", (-530, 120), "as a fraction of the span",
              role="OPERATOR", operation="DIVIDE")
    _lk(ng, pick, 0, pct, 0)
    _lk(ng, span_safe, 0, pct, 1)

    remap = _nd(ng, "ShaderNodeMapRange", (-330, 140),
                "fraction -> output, clamped", role="OPERATOR", clamp=True)
    _lk(ng, pct, 0, remap, 0)
    _lk(ng, gi, I["Percentage Min"], remap, 1)
    _lk(ng, gi, I["Percentage Max"], remap, 2)
    _lk(ng, gi, I["Output Min"], remap, 3)
    _lk(ng, gi, I["Output Max"], remap, 4)

    s_on = _nd(ng, "ShaderNodeMath", (-330, -160), "strength, gated",
               role="OPERATOR", operation="MULTIPLY")
    _lk(ng, gi, I["Strength"], s_on, 0)
    _lk(ng, gi, I["Enable"], s_on, 1)

    def branch(field_id, in_name, y):
        """One output field: SET the remapped value, or scale the initial."""
        scaled = _nd(ng, "ShaderNodeMath", (-120, y),
                     f"x the rolled {in_name.lower()}", role="OPERATOR",
                     operation="MULTIPLY")
        _lk(ng, gi, I[in_name], scaled, 0)
        _lk(ng, remap, 0, scaled, 1)
        val = _nd(ng, "GeometryNodeSwitch", (60, y),
                  "set, or scale the initial", role="OPERATOR",
                  input_type="FLOAT")
        _lk(ng, gi, I["Scale Initial"], val, 0)
        _lk(ng, remap, 0, val, 1)
        _lk(ng, scaled, 0, val, 2)
        is_f = _nd(ng, "FunctionNodeCompare", (60, y - 160),
                   f"field == {field_id}?", role="OPERATOR",
                   data_type="INT", operation="EQUAL")
        _lk(ng, gi, I["Output Field"], is_f, 0)
        _sv(is_f, 1, field_id)
        f = _nd(ng, "ShaderNodeMath", (260, y - 100), "only that field",
                role="OPERATOR", operation="MULTIPLY")
        _lk(ng, s_on, 0, f, 0)
        _lk(ng, is_f, 0, f, 1)
        mix = _nd(ng, "ShaderNodeMix", (460, y), "applied", role="OPERATOR",
                  data_type="FLOAT", factor_mode="UNIFORM")
        _lk(ng, f, 0, mix, 0)
        _lk(ng, gi, I[in_name], mix, 2)
        _lk(ng, val, 0, mix, 3)
        return [scaled, val, is_f, f, mix], mix

    r_nodes, r_mix = branch(3, "Radius In", 240)
    a_nodes, a_mix = branch(7, "Alpha In", -240)
    _lk(ng, r_mix, 0, go, 0)
    _lk(ng, a_mix, 0, go, 1)

    note(ng, "OPERATOR  ·  Remap Percentage Between Two Control Points "
         "to Scalar", "OPERATOR", """
Where the particle sits between two control points, as a fraction.

    radial on   t = |particle - start CP| / |end CP - start CP|
    radial off  t = the same, measured ALONG the start -> end line
    out         = map(t, percentage min .. max -> output min .. max)

CLAMPED at both ends. Percentage min above max reverses the map - the beams
in your library use 1 -> 0, so the start CP gets output max and the end CP
output min. Field 3 writes RADIUS, field 7 ALPHA; any other id passes the
particle through. "Scale Initial" multiplies the rolled value instead of
replacing it. Reads the particle's final evaluated position, so it stays
exact at any frame rate.

THIS FEATURE WAS ADDED IN VERSION 3.0.2 AND IS IN EXPERIMENTAL STAGE.
""", [span_v, span_len, span_safe, rel, rel_len, dir_n, along, pick, pct,
      remap, s_on] + r_nodes + a_nodes)
    return ng


# =============================================================================
# OPERATOR  ·  Color Fade                          (1493 uses)
# =============================================================================

def build_color_fade():
    """Fade the particle's colour towards a second colour, over time.

    TIMES ARE SECONDS here - 0.05..6 with an average of 0.8 - unlike Alpha
    Fade and Decay, which is a proportion of life. Two operators in the same
    section, two meanings for the word "time".

    ease_in_and_out is true in 1327 of 1493 uses, so smooth is the normal case
    and linear is the exception; both are built and switched."""
    ng = _group("SP · OPERATOR · Color Fade", "GeometryNodeTree")
    _sock(ng, "Color", "OUTPUT", "NodeSocketColor")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Color In", "INPUT", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0))
    _sock(ng, "Fade To", "INPUT", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0))
    _sock(ng, "Age", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Lifetime", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Start Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "End Time", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Ease", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1100, 0), (900, 0))
    I = _gin(ng)

    #0.24.1: FRACTIONS OF LIFE, measured (kit 2's fade ran across the whole life)
    c_life = _nd(ng, "ShaderNodeMath", (-880, 260), "lifetime, never zero",
                 role="TIME", operation="MAXIMUM")
    _lk(ng, gi, I["Lifetime"], c_life, 0)
    _sv(c_life, 1, EPS)
    c_frac = _nd(ng, "ShaderNodeMath", (-700, 260), "age / lifetime",
                 role="TIME", operation="DIVIDE")
    _lk(ng, gi, I["Age"], c_frac, 0)
    _lk(ng, c_life, 0, c_frac, 1)

    # same zero-length trap as the alpha operator
    bump = _nd(ng, "ShaderNodeMath", (-880, -240), "start + eps", role="TIME",
               operation="ADD")
    _lk(ng, gi, I["Start Time"], bump, 0)
    _sv(bump, 1, EPS)
    end = _nd(ng, "ShaderNodeMath", (-700, -240), "end, never before start",
              role="TIME", operation="MAXIMUM")
    _lk(ng, gi, I["End Time"], end, 0)
    _lk(ng, bump, 0, end, 1)

    linear = _nd(ng, "ShaderNodeMapRange", (-480, 120), "linear ramp",
                 role="OPERATOR", clamp=True, interpolation_type="LINEAR")
    _lk(ng, c_frac, 0, linear, 0)
    _lk(ng, gi, I["Start Time"], linear, 1)
    _lk(ng, end, 0, linear, 2)
    _sv(linear, 3, 0.0)
    _sv(linear, 4, 1.0)

    # SMOOTHSTEP IS A MAP RANGE INTERPOLATION, not A MATH OPERATION - the
    # Math node's enum stops at SMOOTH_MIN / SMOOTH_MAX, which are a different
    # thing entirely.
    smooth = _nd(ng, "ShaderNodeMapRange", (-480, -140), "eased ramp",
                 role="OPERATOR", clamp=True,
                 interpolation_type="SMOOTHSTEP")
    _lk(ng, c_frac, 0, smooth, 0)
    _lk(ng, gi, I["Start Time"], smooth, 1)
    _lk(ng, end, 0, smooth, 2)
    _sv(smooth, 3, 0.0)
    _sv(smooth, 4, 1.0)

    pick = _nd(ng, "GeometryNodeSwitch", (-240, 0), "eased, or linear",
               role="OPERATOR", input_type="FLOAT")
    _lk(ng, gi, I["Ease"], pick, 0)
    _lk(ng, linear, 0, pick, 1)
    _lk(ng, smooth, 0, pick, 2)
    strong = _nd(ng, "ShaderNodeMath", (-40, -160), "x envelope",
                 role="OPERATOR", operation="MULTIPLY")
    _lk(ng, pick, 0, strong, 0)
    _lk(ng, gi, I["Strength"], strong, 1)

    mixed = _nd(ng, "ShaderNodeMix", (180, 0), "towards the fade colour",
                role="OPERATOR", data_type="RGBA", blend_type="MIX")
    _lk(ng, strong, 0, mixed, 0)
    _lk(ng, gi, I["Color In"], mixed, 6)
    _lk(ng, gi, I["Fade To"], mixed, 7)

    out = _nd(ng, "GeometryNodeSwitch", (460, 0), "enabled?", role="OPERATOR",
              input_type="RGBA")
    _lk(ng, gi, I["Enable"], out, 0)
    _lk(ng, gi, I["Color In"], out, 1)
    _lk(ng, mixed, 2, out, 2)
    _lk(ng, out, 0, go, 0)

    note(ng, "OPERATOR  ·  Color Fade", "OPERATOR", """
1493 uses. The particle's colour walks towards a second colour between two
times, and then stays there.

TIMES ARE SECONDS, unlike Alpha Fade and Decay sitting next to it, whose
times are fractions of life. The corpus settles it: 0.05 .. 6 with an average
of 0.8 is a clock, not a proportion.

EASE IS THE DEFAULT, not the exception - 1327 of 1493 uses have it on. Both
ramps are built and switched, because the 166 that turn it off mean it.

SMOOTHSTEP IS A MAP RANGE INTERPOLATION TYPE. The Math node has no such
operation; its enum stops at SMOOTH_MIN / SMOOTH_MAX, which are something
else entirely and would silently give a different curve.
""", [bump, end, linear, smooth, pick, strong, mixed, out])
    return ng


# =============================================================================
# CHILDREN  ·  Position From Parent Particles
# =============================================================================

# how the parent's particles are read out of the parent object. The number is
# a socket, so one node group serves every kind of parent.
PARENT_FROM_INSTANCES = 0
PARENT_FROM_POINTS = 1
PARENT_FROM_VERTICES = 2


def build_position_from_parent():
    """The operator that makes a child a CHILD.

    241 uses across the TF2 corpus, always in the INITIALIZERS list, and the
    whole of it in a real .pcf is two fields plus the envelope:

        Inherited Velocity Scale              -1 .. 7, average 0.2
        Random Parent Particle Distribution   true in 9 of 241 uses

    There is no control point and no offset, because THE PARENT PARTICLE IS
    THE POSITION. Whatever the child's own position initializers produce is
    added on top of it, exactly the way SFM stacks them onto a control point.

    HOW A CHILD FINDS ITS PARENT'S PARTICLES
    ----------------------------------------
    Object Info on the parent host, read RELATIVE so both systems are measured
    in the same frame, and then Sample Index by particle number. What domain to
    sample depends on what the parent's renderer left behind, and it is a
    socket rather than a guess:

        0  INSTANCES   render_animated_sprites - one instance per particle,
                       and an instance's Position IS the particle's position.
                       PROVEN by probe, not assumed: five points at x = 0, 10,
                       20, 30, 40 sampled back as exactly that.
        1  POINTS      a raw point cloud
        2  VERTICES    render_rope - the ribbon's own vertices, which is the
                       nearest honest answer to "where is the parent" for a
                       renderer that produces no per-particle instances

    ⚠️ Sample Index takes domain POINT for BOTH a point cloud and mesh
    vertices, so modes 1 and 2 share one sampler and differ only in which
    count they ask for. Attribute Domain Size does NOT share: its Instance
    Count is output 5 and its Point Count is output 0, and the sockets it does
    not use are still in the list taking up indices. Probed, never counted.

    WHICH parent particle:
        sequential (default)  index = particle id WRAPPED into 0..count-1, so
                              a stream of children walks the parents in order
        random                an independent draw per child

    NO PARENT, NO CHANGE. With the object socket empty the count is zero, the
    operator reports Has Parent = false, and the caller falls straight back to
    the control point - rather than dividing by zero and stacking every child
    on the origin."""
    ng = _group("SP · CHILDREN · Position From Parent Particles",
                "GeometryNodeTree")
    _sock(ng, "Position", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Velocity", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Has Parent", "OUTPUT", "NodeSocketBool")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Parent", "INPUT", "NodeSocketGeometry")
    _sock(ng, "Read From", "INPUT", "NodeSocketInt", 0, 0, 2)
    _sock(ng, "Random", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Velocity Scale", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1500, 0), (1300, 0))
    I = _gin(ng)

    #── how many parent particles are there ──────────────────────────────
    n_inst = _nd(ng, "GeometryNodeAttributeDomainSize", (-1240, 420),
                 "instances", role="EMITTER", component="INSTANCES")
    _lk(ng, gi, I["Parent"], n_inst, 0)
    n_pts = _nd(ng, "GeometryNodeAttributeDomainSize", (-1240, 240),
                "point cloud", role="EMITTER", component="POINTCLOUD")
    _lk(ng, gi, I["Parent"], n_pts, 0)
    n_mesh = _nd(ng, "GeometryNodeAttributeDomainSize", (-1240, 60),
                 "mesh vertices", role="EMITTER", component="MESH")
    _lk(ng, gi, I["Parent"], n_mesh, 0)

    is_pts = _nd(ng, "FunctionNodeCompare", (-1020, 180), "read points?",
                 role="EMITTER", data_type="INT", operation="EQUAL")
    _lk(ng, gi, I["Read From"], is_pts, 0)
    _sv(is_pts, 1, PARENT_FROM_POINTS)
    is_vert = _nd(ng, "FunctionNodeCompare", (-1020, 20), "read vertices?",
                  role="EMITTER", data_type="INT", operation="EQUAL")
    _lk(ng, gi, I["Read From"], is_vert, 0)
    _sv(is_vert, 1, PARENT_FROM_VERTICES)

    #Instance Count is output 5 on that node, Point Count is output 0 - the
    #disabled sockets are still in the list.
    cnt_a = _nd(ng, "GeometryNodeSwitch", (-820, 300), "instances or points",
                role="EMITTER", input_type="INT")
    _lk(ng, is_pts, 0, cnt_a, 0)
    _lk(ng, n_inst, 5, cnt_a, 1)
    _lk(ng, n_pts, 0, cnt_a, 2)
    count = _nd(ng, "GeometryNodeSwitch", (-620, 220), "or mesh vertices",
                role="EMITTER", input_type="INT")
    _lk(ng, is_vert, 0, count, 0)
    _lk(ng, cnt_a, 0, count, 1)
    _lk(ng, n_mesh, 0, count, 2)

    has = _nd(ng, "FunctionNodeCompare", (-420, 380), "any parent particles?",
              role="EMITTER", data_type="INT", operation="GREATER_THAN")
    _lk(ng, count, 0, has, 0)
    _sv(has, 1, 0)
    live = _nd(ng, "FunctionNodeBooleanMath", (-220, 380),
               "enabled AND a parent exists", role="EMITTER", operation="AND")
    _lk(ng, gi, I["Enable"], live, 0)
    _lk(ng, has, 0, live, 1)
    _lk(ng, live, 0, go, 2)

    # ── which one ────────────────────────────────────────────────────────
    cnt_f = _nd(ng, "ShaderNodeMath", (-420, 60), "count as float",
                role="EMITTER", operation="MAXIMUM")
    _lk(ng, count, 0, cnt_f, 0)
    _sv(cnt_f, 1, 1.0)
    id_f = _nd(ng, "ShaderNodeMath", (-420, -100), "id as float",
               role="EMITTER", operation="MULTIPLY")
    _lk(ng, gi, I["ID"], id_f, 0)
    _sv(id_f, 1, 1.0)
    # WRAP, not MODULO. Blender's modulo is truncated and returns a NEGATIVE
    # result for negative input, which would index off the front of the list
    seq = _nd(ng, "ShaderNodeMath", (-220, -20), "id wrapped into range",
              role="EMITTER", operation="WRAP")
    _lk(ng, id_f, 0, seq, 0)
    _lk(ng, cnt_f, 0, seq, 1)
    _sv(seq, 2, 0.0)
    seq_i = _nd(ng, "FunctionNodeFloatToInt", (-40, -20), "as an index",
                role="EMITTER", rounding_mode="FLOOR")
    _lk(ng, seq, 0, seq_i, 0)

    top = _nd(ng, "ShaderNodeMath", (-220, -200), "count - 1", role="EMITTER",
              operation="SUBTRACT")
    _lk(ng, cnt_f, 0, top, 0)
    _sv(top, 1, 1.0)
    top_i = _nd(ng, "FunctionNodeFloatToInt", (-40, -200), "as an index",
                role="EMITTER", rounding_mode="FLOOR")
    _lk(ng, top, 0, top_i, 0)
    rnd = _nd(ng, "FunctionNodeRandomValue", (160, -200), "any of them",
              role="EMITTER", data_type="INT")
    _sv(rnd, 0, 0)
    _lk(ng, top_i, 0, rnd, 1)
    _lk(ng, gi, I["ID"], rnd, 2)
    _lk(ng, gi, I["Seed"], rnd, 3)

    which = _nd(ng, "GeometryNodeSwitch", (360, -100), "in order, or any",
                role="EMITTER", input_type="INT")
    _lk(ng, gi, I["Random"], which, 0)
    _lk(ng, seq_i, 0, which, 1)
    _lk(ng, rnd, 0, which, 2)

    # ── where it is ──────────────────────────────────────────────────────
    ppos = _nd(ng, "GeometryNodeInputPosition", (160, 400),
               "the parent's position", role="EMITTER")
    s_inst = _nd(ng, "GeometryNodeSampleIndex", (560, 400),
                 "sample the instances", role="EMITTER",
                 data_type="FLOAT_VECTOR", domain="INSTANCE")
    _lk(ng, gi, I["Parent"], s_inst, 0)
    _lk(ng, ppos, 0, s_inst, 1)
    _lk(ng, which, 0, s_inst, 2)
    s_pts = _nd(ng, "GeometryNodeSampleIndex", (560, 220),
                "sample the points / vertices", role="EMITTER",
                data_type="FLOAT_VECTOR", domain="POINT")
    _lk(ng, gi, I["Parent"], s_pts, 0)
    _lk(ng, ppos, 0, s_pts, 1)
    _lk(ng, which, 0, s_pts, 2)
    not_inst = _nd(ng, "FunctionNodeBooleanMath", (360, 120),
                   "points or vertices", role="EMITTER", operation="OR")
    _lk(ng, is_pts, 0, not_inst, 0)
    _lk(ng, is_vert, 0, not_inst, 1)
    pos = _nd(ng, "GeometryNodeSwitch", (780, 320), "whichever it was",
              role="EMITTER", input_type="VECTOR")
    _lk(ng, not_inst, 0, pos, 0)
    _lk(ng, s_inst, 0, pos, 1)
    _lk(ng, s_pts, 0, pos, 2)
    _lk(ng, pos, 0, go, 0)

    #── and how fast it was going ────────────────────────────────────────
    #particle_velocity is written by every system this add-on builds, so a
    #parent advertises its motion w/o being asked. A parent that does
    #not carry it reads as zero, which is simply no inheritance
    pvel = _nd(ng, "GeometryNodeInputNamedAttribute", (160, -420),
               "particle_velocity [read]", role="EMITTER",
               data_type="FLOAT_VECTOR")
    _sv(pvel, 0, "particle_velocity")
    v_inst = _nd(ng, "GeometryNodeSampleIndex", (560, -420),
                 "sample the instances", role="EMITTER",
                 data_type="FLOAT_VECTOR", domain="INSTANCE")
    _lk(ng, gi, I["Parent"], v_inst, 0)
    _lk(ng, pvel, 0, v_inst, 1)
    _lk(ng, which, 0, v_inst, 2)
    v_pts = _nd(ng, "GeometryNodeSampleIndex", (560, -600),
                "sample the points / vertices", role="EMITTER",
                data_type="FLOAT_VECTOR", domain="POINT")
    _lk(ng, gi, I["Parent"], v_pts, 0)
    _lk(ng, pvel, 0, v_pts, 1)
    _lk(ng, which, 0, v_pts, 2)
    vel_raw = _nd(ng, "GeometryNodeSwitch", (780, -500), "whichever it was",
                  role="EMITTER", input_type="VECTOR")
    _lk(ng, not_inst, 0, vel_raw, 0)
    _lk(ng, v_inst, 0, vel_raw, 1)
    _lk(ng, v_pts, 0, vel_raw, 2)
    scale = _nd(ng, "ShaderNodeMath", (780, -700), "scale x strength",
                role="EMITTER", operation="MULTIPLY")
    _lk(ng, gi, I["Velocity Scale"], scale, 0)
    _lk(ng, gi, I["Strength"], scale, 1)
    vel = _nd(ng, "ShaderNodeVectorMath", (980, -560), "inherited velocity",
              role="EMITTER", operation="SCALE")
    _lk(ng, vel_raw, 0, vel, 0)
    _lk(ng, scale, 0, vel, 3)
    zero = _nd(ng, "ShaderNodeCombineXYZ", (980, -760), "off = inherit nothing",
               role="EMITTER")
    vel_out = _nd(ng, "ShaderNodeMix", (1140, -620), "enabled?", role="EMITTER",
                  data_type="VECTOR", factor_mode="UNIFORM")
    _lk(ng, live, 0, vel_out, 0)
    _lk(ng, zero, 0, vel_out, 4)
    _lk(ng, vel, 0, vel_out, 5)
    _lk(ng, vel_out, 1, go, 1)

    note(ng, "CHILDREN  ·  Position From Parent Particles", "EMITTER", """
THE PARENT PARTICLE IS THE POSITION. This operator does not offset anything -
it replaces the control point the child would otherwise be born on, and the
child's own position initializers then add their offset on top, the same way
they would around a control point.

WHERE THE PARENT'S PARTICLES COME FROM. Object Info on the parent host, read
RELATIVE so both systems are measured in the same frame, then Sample Index.
The domain is a socket because it depends on the parent's RENDERER:

    0  INSTANCES  animated sprites - one instance per particle, and the
                  instance's Position IS the particle's position
    1  POINTS     a raw point cloud
    2  VERTICES   a rope - it makes no per-particle instances, so its ribbon
                  vertices are the honest answer to "where is the parent"

WHICH PARENT. Off (the default, and what 232 of 241 real uses do), the child
takes the parent whose number matches its own, wrapped into range - so a
stream of children traces the parents in birth order. On, it draws one at
random per child.

WRAP, NOT MODULO. Blender's MODULO is truncated: modulo(-3, 2) is -1, not 1.
A negative index samples off the front of the list.

VELOCITY IS INHERITED FROM THE ATTRIBUTE, not measured. Every system this
add-on builds writes `particle_velocity`, differentiated from Movement Basic's
own closed form, so a parent advertises its motion and the child reads it.
A parent without that attribute reads zero, which is just no inheritance.
The corpus runs the scale from -1 to 7 with an average of 0.2, and negative is
a real choice - the child flies back the way the parent came.

NO PARENT, NO CHANGE. Empty object socket -> zero particles -> Has Parent is
false and the caller uses the control point instead. It never divides by the
count.
""", [n_inst, n_pts, n_mesh, is_pts, is_vert, cnt_a, count, has, live, cnt_f,
      id_f, seq, seq_i, top, top_i, rnd, which, ppos, s_inst, s_pts, not_inst,
      pos, pvel, v_inst, v_pts, vel_raw, scale, vel, zero, vel_out])
    return ng


# =============================================================================
# FORCE GENERATOR  ·  random force, per tick  (the crackle)
# =============================================================================

def build_random_force_tick():
    """SFM's `random force`, the way Source actually rolls it: a NEW random
    vector every 30 Hz tick, SHARED by every particle alive that tick.

    That sharing is the whole look. Each particle integrates the same force
    history over its own life window, so neighbours along a beam - born a
    tick apart - accumulate almost the same wander and the beam KINKS
    COHERENTLY instead of fuzzing per particle. The per-particle-constant
    reading (one steady push rolled from the id) is what made a leashed
    beam drift to one wall of its envelope and sit there, dead straight.

    Single-value maths on purpose - the roll must be one number per tick
    for the whole system, and the sin-hash is the same roll
    emit_instantaneously uses (a field node asked for a single value is
    never evaluated; Blender hands back the type default)."""
    ng = _group("SP · FORCE · random force (per tick)", "GeometryNodeTree")
    _sock(ng, "Force", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Min Force", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Max Force", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1500, 0), (1100, 0))
    I = _gin(ng)

    t30 = _nd(ng, "ShaderNodeMath", (-1280, 200), "time x 30", role="OPERATOR",
              operation="MULTIPLY")
    _lk(ng, gi, I["Time"], t30, 0)
    _sv(t30, 1, 30.0)
    tick = _nd(ng, "ShaderNodeMath", (-1100, 200), "which tick",
               role="OPERATOR", operation="FLOOR")
    _lk(ng, t30, 0, tick, 0)
    # ...and which PARTICLE. A tick-only roll is shared by the whole system
    # and just LEANS the beam collectively (measured: the kink pattern sat
    # still, 0.2 HU of crawl over ten frames). Each particle rolling its
    # own force each tick is what decorrelates neighbours into the lively
    # wiggle the reference shows - the rope's Catmull-Rom then smooths the
    # independent points into kinks
    base = _nd(ng, "ShaderNodeMath", (-920, 200), "tick + id",
               role="OPERATOR", operation="MULTIPLY_ADD")
    _lk(ng, gi, I["ID"], base, 0)
    _sv(base, 1, 57.719)
    _lk(ng, tick, 0, base, 2)
    s_min = _nd(ng, "ShaderNodeSeparateXYZ", (-1280, -40), "min, per axis",
                role="OPERATOR")
    _lk(ng, gi, I["Min Force"], s_min, 0)
    s_max = _nd(ng, "ShaderNodeSeparateXYZ", (-1280, -220), "max, per axis",
                role="OPERATOR")
    _lk(ng, gi, I["Max Force"], s_max, 0)

    comps, made = [], []
    for ci, (axis, salt_c) in enumerate((("x", 12.9898), ("y", 39.3468),
                                         ("z", 67.1234))):
        y = 60 - ci * 180
        seeded = _nd(ng, "ShaderNodeMath", (-740, y + 90),
                     f"+ seed  ({axis})", role="OPERATOR",
                     operation="MULTIPLY_ADD")
        _lk(ng, gi, I["Seed"], seeded, 0)
        _sv(seeded, 1, 78.233)
        _lk(ng, base, 0, seeded, 2)
        swirl = _nd(ng, "ShaderNodeMath", (-740, y), f"x salt  ({axis})",
                    role="OPERATOR", operation="MULTIPLY")
        _lk(ng, seeded, 0, swirl, 0)
        _sv(swirl, 1, salt_c)
        s = _nd(ng, "ShaderNodeMath", (-560, y), f"sin  ({axis})",
                role="OPERATOR", operation="SINE")
        _lk(ng, swirl, 0, s, 0)
        big = _nd(ng, "ShaderNodeMath", (-380, y), f"x 43758.5453  ({axis})",
                  role="OPERATOR", operation="MULTIPLY")
        _lk(ng, s, 0, big, 0)
        _sv(big, 1, 43758.5453)
        r = _nd(ng, "ShaderNodeMath", (-200, y), f"fract = the roll  ({axis})",
                role="OPERATOR", operation="FRACT")
        _lk(ng, big, 0, r, 0)
        span = _nd(ng, "ShaderNodeMath", (-20, y), f"max - min  ({axis})",
                   role="OPERATOR", operation="SUBTRACT")
        _lk(ng, s_max, ci, span, 0)
        _lk(ng, s_min, ci, span, 1)
        f_c = _nd(ng, "ShaderNodeMath", (160, y), f"min + span x roll ({axis})",
                  role="OPERATOR", operation="MULTIPLY_ADD")
        _lk(ng, span, 0, f_c, 0)
        _lk(ng, r, 0, f_c, 1)
        _lk(ng, s_min, ci, f_c, 2)
        comps.append(f_c)
        made += [seeded, swirl, s, big, r, span, f_c]

    vec = _nd(ng, "ShaderNodeCombineXYZ", (360, -120), "this tick's force",
              role="OPERATOR")
    for ci, f_c in enumerate(comps):
        _lk(ng, f_c, 0, vec, ci)
    strong = _nd(ng, "ShaderNodeVectorMath", (540, -120),
                 "x operator strength", role="OPERATOR", operation="SCALE")
    _lk(ng, vec, 0, strong, 0)
    _lk(ng, gi, I["Strength"], strong, 3)
    zero = _nd(ng, "ShaderNodeCombineXYZ", (540, -300), "off = no force",
               role="OPERATOR")
    sw = _nd(ng, "GeometryNodeSwitch", (760, -160), "enabled?",
             role="OPERATOR", input_type="VECTOR")
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, zero, 0, sw, 1)
    _lk(ng, strong, 0, sw, 2)
    _lk(ng, sw, 0, go, 0)

    note(ng, "FORCE GENERATOR  ·  random force, per tick", "OPERATOR", """
    force(tick, id) = min + (max - min) x hash(tick, id, seed)

A NEW ROLL PER PARTICLE, PER 30 Hz TICK. Both parts matter and both were
measured:

  * per particle CONSTANT (the old reading): every particle drifts one way,
    the leash catches it, and the beam lies against its envelope dead
    straight.
  * per tick but SHARED system-wide: every particle leans together and the
    kink pattern sits still (0.2 HU of crawl over ten frames).
  * per particle AND per tick: neighbours random-walk independently inside
    the leash, and the rope's Catmull-Rom smooths those independent points
    into the lively wiggle the SFM reference shows.

Runs inside the simulation zone (the stateless emitter keeps the old
per-particle constant reading - it has no memory to integrate with).
""", [t30, tick, base, s_min, s_max, vec, strong, zero, sw] + made)
    return ng


# =============================================================================
# INITIALIZER  ·  Rotation Yaw Random
# =============================================================================

def build_yaw_random():
    """SFM's `Rotation Yaw Random` - a real yaw ANGLE on a camera-facing card.

    the user's observation IS the implementation: yawing a card that always
    faces you can only read as HORIZONTAL FORESHORTENING - at 90 degrees the
    card is edge-on and vanishes into a sliver. So the group rolls a yaw
    between Min and Max per particle and returns cos(yaw), which multiplies
    the same card X scale the yaw FLIP mirror rides (sprite_flip). Flip's -1
    and this compression compose by multiplication, exactly like Source."""
    ng = _group("SP · INITIALIZER · Rotation Yaw Random", "GeometryNodeTree")
    _sock(ng, "Scale", "OUTPUT", "NodeSocketFloat")
    # 3.0.2: the angle itself (radians, 0 when off) - a card locked to a
    # control point turns by it in its own plane instead of squishing
    _sock(ng, "Yaw", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Yaw Min", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Yaw Max", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Yaw Initial", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Exponent", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-1100, 0), (700, 0))
    I = _gin(ng)

    salt = _nd(ng, "ShaderNodeMath", (-880, -160), "seed + salt",
               role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I["Seed"], salt, 0)
    _sv(salt, 1, 53.0)
    # 3.0.2: the roll is drawn 0..1 and biased by the exponent before the
    # range - Source's yaw = initial + min + rand^exponent x (max - min)
    # Exponent 1 gives the very same yaws as before (same id, same seed).
    yaw = _nd(ng, "FunctionNodeRandomValue", (-700, -60),
              "a roll per particle, 0..1", role="INITIALIZER")
    yaw.data_type = "FLOAT"
    _sv(yaw, 0, 0.0)
    _sv(yaw, 1, 1.0)
    _lk(ng, gi, I["ID"], yaw, 2)
    _lk(ng, salt, 0, yaw, 3)
    biased = _nd(ng, "ShaderNodeMath", (-520, -60), "^ exponent",
                 role="INITIALIZER", operation="POWER")
    _lk(ng, yaw, 0, biased, 0)   # 0.26.3: 5.2's Random Value has one output
    _lk(ng, gi, I["Exponent"], biased, 1)
    span = _nd(ng, "ShaderNodeMath", (-700, -240), "max - min",
               role="INITIALIZER", operation="SUBTRACT")
    _lk(ng, gi, I["Yaw Max"], span, 0)
    _lk(ng, gi, I["Yaw Min"], span, 1)
    in_range = _nd(ng, "ShaderNodeMath", (-340, -60), "min + span x that",
                   role="INITIALIZER", operation="MULTIPLY_ADD")
    _lk(ng, biased, 0, in_range, 0)
    _lk(ng, span, 0, in_range, 1)
    _lk(ng, gi, I["Yaw Min"], in_range, 2)
    plus_init = _nd(ng, "ShaderNodeMath", (-340, -240), "+ yaw initial",
                    role="INITIALIZER", operation="ADD")
    _lk(ng, in_range, 0, plus_init, 0)
    _lk(ng, gi, I["Yaw Initial"], plus_init, 1)
    rad = _nd(ng, "ShaderNodeMath", (-160, -60), "degrees -> radians",
              role="INITIALIZER", operation="RADIANS")
    _lk(ng, plus_init, 0, rad, 0)
    squish = _nd(ng, "ShaderNodeMath", (20, -60), "cos = how much is left",
                 role="INITIALIZER", operation="COSINE")
    _lk(ng, rad, 0, squish, 0)

    one = _nd(ng, "ShaderNodeValue", (20, -220), "off = untouched",
              role="INITIALIZER")
    _sv_out = one.outputs[0]
    _sv_out.default_value = 1.0
    sw = _nd(ng, "GeometryNodeSwitch", (240, 0), "enabled?",
             role="INITIALIZER", input_type="FLOAT")
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, one, 0, sw, 1)
    _lk(ng, squish, 0, sw, 2)
    _lk(ng, sw, 0, go, 0)
    sw_yaw = _nd(ng, "GeometryNodeSwitch", (240, -200), "enabled? (angle)",
                 role="INITIALIZER", input_type="FLOAT")
    _lk(ng, gi, I["Enable"], sw_yaw, 0)
    _sv(sw_yaw, 1, 0.0)
    _lk(ng, rad, 0, sw_yaw, 2)
    _lk(ng, sw_yaw, 0, go, 1)

    note(ng, "INITIALIZER  ·  Rotation Yaw Random", "INITIALIZER", """
    yaw = yaw initial + min + random^exponent x (max - min)
    card X scale x= cos( yaw )
    (3.0.2: a card locked to a control point turns by yaw in its own plane
    instead - the system graph switches it by orientation type.)

YAW ON A CAMERA-FACING CARD IS FORESHORTENING. The card never stops facing
the camera, so a real yaw angle can only show up as the card getting
NARROWER on its own horizontal axis - 0 degrees leaves it alone, 90 is
edge-on and gone. That is why this multiplies into the same sprite_flip
channel the yaw FLIP mirror uses: flip's -1 and this compression compose by
multiplication.

Disabled it returns exactly 1 and the chain is untouched.
""", [salt, yaw, biased, span, in_range, plus_init, rad, squish, one, sw,
      sw_yaw])
    return ng


# =============================================================================
# CONSTRAINT  ·  Constrain distance to control point
# =============================================================================

def build_constrain_to_cp():
    """SFM's `Constrain distance to control point` - the path constraint's
    simpler sibling (106 corpus uses): clamp each particle between Minimum
    and Maximum Distance of ONE control point, whose centre can be offset
    in the CP's own frame (conc_stars floats it 5 units up). No travel, no
    envelope interpolation - just the radial clamp, MAX WINS over MIN."""
    ng = _group("SP · CONSTRAINT · Constrain Distance to CP",
                "GeometryNodeTree")
    _sock(ng, "Position", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Position", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "CP", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "CP Rotation", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Center Offset", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Min Distance", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Max Distance", "INPUT", "NodeSocketFloat", 100.0)
    _sock(ng, "Scale", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1100, 0), (900, 0))
    I = _gin(ng)

    off_hu = _nd(ng, "ShaderNodeVectorMath", (-880, -160),
                 "offset x scale", role="CONSTRAINT", operation="SCALE")
    _lk(ng, gi, I["Center Offset"], off_hu, 0)
    _lk(ng, gi, I["Scale"], off_hu, 3)
    off_rot = _nd(ng, "ShaderNodeVectorRotate", (-700, -160),
                  "into the CP's frame", role="CONSTRAINT",
                  rotation_type="EULER_XYZ")
    _lk(ng, off_hu, 0, off_rot, 0)
    _lk(ng, gi, I["CP Rotation"], off_rot, 4)
    centre = _nd(ng, "ShaderNodeVectorMath", (-520, -100), "the centre",
                 role="CONSTRAINT", operation="ADD")
    _lk(ng, gi, I["CP"], centre, 0)
    _lk(ng, off_rot, 0, centre, 1)

    delta = _nd(ng, "ShaderNodeVectorMath", (-340, 40),
                "centre -> particle", role="CONSTRAINT",
                operation="SUBTRACT")
    _lk(ng, gi, I["Position"], delta, 0)
    _lk(ng, centre, 0, delta, 1)
    dist = _nd(ng, "ShaderNodeVectorMath", (-160, -20), "how far off it",
               role="CONSTRAINT", operation="LENGTH")
    _lk(ng, delta, 0, dist, 0)
    dirn = _nd(ng, "ShaderNodeVectorMath", (-160, 140), "which way",
               role="CONSTRAINT", operation="NORMALIZE")
    _lk(ng, delta, 0, dirn, 0)
    min_hu = _nd(ng, "ShaderNodeMath", (-340, -220), "min x scale",
                 role="CONSTRAINT", operation="MULTIPLY")
    _lk(ng, gi, I["Min Distance"], min_hu, 0)
    _lk(ng, gi, I["Scale"], min_hu, 1)
    max_hu = _nd(ng, "ShaderNodeMath", (-340, -380), "max x scale",
                 role="CONSTRAINT", operation="MULTIPLY")
    _lk(ng, gi, I["Max Distance"], max_hu, 0)
    _lk(ng, gi, I["Scale"], max_hu, 1)
    at_least = _nd(ng, "ShaderNodeMath", (20, -20), "at least min",
                   role="CONSTRAINT", operation="MAXIMUM")
    _lk(ng, dist, 1, at_least, 0)
    _lk(ng, min_hu, 0, at_least, 1)
    at_most = _nd(ng, "ShaderNodeMath", (200, -20), "at most max (max wins)",
                  role="CONSTRAINT", operation="MINIMUM")
    _lk(ng, at_least, 0, at_most, 0)
    _lk(ng, max_hu, 0, at_most, 1)
    held = _nd(ng, "ShaderNodeVectorMath", (380, 100), "held that far out",
               role="CONSTRAINT", operation="SCALE")
    _lk(ng, dirn, 0, held, 0)
    _lk(ng, at_most, 0, held, 3)
    clamped = _nd(ng, "ShaderNodeVectorMath", (560, 40), "centre + that",
                  role="CONSTRAINT", operation="ADD")
    _lk(ng, centre, 0, clamped, 0)
    _lk(ng, held, 0, clamped, 1)

    eased = _nd(ng, "ShaderNodeMix", (740, -40), "envelope eases it in",
                role="CONSTRAINT", data_type="VECTOR")
    _lk(ng, gi, I["Strength"], eased, 0)
    _lk(ng, gi, I["Position"], eased, 4)
    _lk(ng, clamped, 0, eased, 5)
    sw = _nd(ng, "GeometryNodeSwitch", (740, -220), "enabled?",
             role="CONSTRAINT", input_type="VECTOR")
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, gi, I["Position"], sw, 1)
    _lk(ng, eased, 1, sw, 2)
    _lk(ng, sw, 0, go, 0)

    note(ng, "CONSTRAINT  ·  Constrain distance to CP", "CONSTRAINT", """
    position = centre + direction x clamp(distance, min, max)
    centre   = control point + its own frame's Center Offset

The path constraint's simpler sibling: one control point, one shell. MAX
WINS over MIN where they cross, same as the path version - min 50 with max
0 lands ON the centre.

Chained AFTER the path leash (both per frame in the simulation and on the
final position), the same order Source runs its constraint list.
""", [off_hu, off_rot, centre, delta, dist, dirn, min_hu, max_hu,
      at_least, at_most, held, clamped, eased, sw])
    return ng


# =============================================================================
# CONSTRAINT  ·  Constrain distance to path between two control points
# =============================================================================

def build_constrain_to_path():
    """SFM's `Constrain distance to path between two control points`.

    THE BEAM LEASH. An anchor point travels from the start CP to the end CP
    over Travel Time (per particle, on its own age); the particle is then
    clamped to within a distance envelope of that anchor:

        departure   Maximum Distance
        halfway     Maximum Distance Middle   (-1 = same as Maximum)
        arrival     Maximum Distance End      (-1 = same as Maximum)

    MAX WINS over MIN where they cross - beam (king) authors end 0 with
    min 1, which is how a crackling beam pinches ONTO its path. Random
    Bulge bows the path through a per-particle random midpoint offset, so
    every particle rides a slightly different curve and the beam reads as
    a bundle instead of a pipe.

    A pure function of (position, age): no integration, exact at any frame
    rate, applied to the FINAL position after forces and the lock."""
    ng = _group("SP · CONSTRAINT · Constrain Distance to Path",
                "GeometryNodeTree")
    _sock(ng, "Position", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", False)
    _sock(ng, "Position", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Age", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Start", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "End", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    #eulers, converted OUTSIDE the group - same convention as the path
    #initializer's Start/End Rotation inputs
    _sock(ng, "Start Rotation", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "End Rotation", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Bulge Control", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Min Distance", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Max Distance", "INPUT", "NodeSocketFloat", 100.0)
    _sock(ng, "Max Distance Middle", "INPUT", "NodeSocketFloat", -1.0)
    _sock(ng, "Max Distance End", "INPUT", "NodeSocketFloat", -1.0)
    _sock(ng, "Travel Time", "INPUT", "NodeSocketFloat", 10.0)
    _sock(ng, "Mid Point", "INPUT", "NodeSocketFloat", 0.5)
    _sock(ng, "Random Bulge", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Scale", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1700, 0), (1500, 0))
    I = _gin(ng)

    # ── t: how far along the path this particle's anchor has travelled ───
    tt_safe = _nd(ng, "ShaderNodeMath", (-1450, 400), "travel time, never 0",
                  role="CONSTRAINT", operation="MAXIMUM")
    _lk(ng, gi, I["Travel Time"], tt_safe, 0)
    _sv(tt_safe, 1, EPS)
    t_raw = _nd(ng, "ShaderNodeMath", (-1270, 400), "age / travel time",
                role="CONSTRAINT", operation="DIVIDE")
    _lk(ng, gi, I["Age"], t_raw, 0)
    _lk(ng, tt_safe, 0, t_raw, 1)
    t = _nd(ng, "ShaderNodeMath", (-1090, 400), "arrived = stay arrived",
            role="CONSTRAINT", operation="MINIMUM")
    _lk(ng, t_raw, 0, t, 0)
    _sv(t, 1, 1.0)

    # ── the path: a bow thru a (bulged) midpoint ──────────────────────
    mid_base = _nd(ng, "ShaderNodeMix", (-1270, 120), "midpoint on the line",
                   role="CONSTRAINT", data_type="VECTOR")
    _lk(ng, gi, I["Mid Point"], mid_base, 0)
    _lk(ng, gi, I["Start"], mid_base, 4)
    _lk(ng, gi, I["End"], mid_base, 5)

    # which WAY the BOW POINTS - the path initializer's own convention:
    # bulge control 1/2 take the named CP's UP axis thru its rotation,
    # 0 rolls a direction per particle. Either way the component ALONG the
    # beam is removed (a bow along the beam is a slide, not a bow), with
    # the least-parallel-axis fallback so a vertical beam under an
    # unrotated CP still bows somewhere instead of silently not at all.
    seg = _nd(ng, "ShaderNodeVectorMath", (-1630, -80), "start -> end",
              role="CONSTRAINT", operation="SUBTRACT")
    _lk(ng, gi, I["End"], seg, 0)
    _lk(ng, gi, I["Start"], seg, 1)
    seg_len = _nd(ng, "ShaderNodeVectorMath", (-1630, -240), "how long",
                  role="CONSTRAINT", operation="LENGTH")
    _lk(ng, seg, 0, seg_len, 0)
    unit = _nd(ng, "ShaderNodeVectorMath", (-1630, -400), "unit beam",
               role="CONSTRAINT", operation="NORMALIZE")
    _lk(ng, seg, 0, unit, 0)
    up = _nd(ng, "ShaderNodeCombineXYZ", (-1450, -80), "the CP's own up",
             role="CONSTRAINT")
    _sv(up, 2, 1.0)
    is2 = _nd(ng, "FunctionNodeCompare", (-1450, -220), "control == 2",
              role="CONSTRAINT", data_type="INT", operation="EQUAL")
    _lk(ng, gi, I["Bulge Control"], is2, 0)
    _sv(is2, 1, 2)
    rot_pick = _nd(ng, "GeometryNodeSwitch", (-1270, -220), "start or end",
                   role="CONSTRAINT", input_type="VECTOR")
    _lk(ng, is2, 0, rot_pick, 0)
    _lk(ng, gi, I["Start Rotation"], rot_pick, 1)
    _lk(ng, gi, I["End Rotation"], rot_pick, 2)
    oriented = _nd(ng, "ShaderNodeVectorRotate", (-1090, -220),
                   "into that CP's frame", role="CONSTRAINT",
                   rotation_type="EULER_XYZ")
    _lk(ng, up, 0, oriented, 0)
    _lk(ng, rot_pick, 0, oriented, 4)
    salt = _nd(ng, "ShaderNodeMath", (-1450, -400), "seed + salt",
               role="CONSTRAINT", operation="ADD")
    _lk(ng, gi, I["Seed"], salt, 0)
    _sv(salt, 1, 77.0)
    roll = _nd(ng, "FunctionNodeRandomValue", (-1270, -400),
               "a direction per particle", role="CONSTRAINT")
    roll.data_type = "FLOAT_VECTOR"
    _sv(roll, 0, (-1.0, -1.0, -1.0))
    _sv(roll, 1, (1.0, 1.0, 1.0))
    _lk(ng, gi, I["ID"], roll, 2)
    _lk(ng, salt, 0, roll, 3)
    is0 = _nd(ng, "FunctionNodeCompare", (-1090, -400), "control == 0",
              role="CONSTRAINT", data_type="INT", operation="EQUAL")
    _lk(ng, gi, I["Bulge Control"], is0, 0)
    _sv(is0, 1, 0)
    raw_dir = _nd(ng, "GeometryNodeSwitch", (-910, -300),
                  "random, or the CP", role="CONSTRAINT",
                  input_type="VECTOR")
    _lk(ng, is0, 0, raw_dir, 0)
    _lk(ng, oriented, 0, raw_dir, 1)
    _lk(ng, roll, 0, raw_dir, 2)
    dot = _nd(ng, "ShaderNodeVectorMath", (-730, -300),
              "how much lies along", role="CONSTRAINT",
              operation="DOT_PRODUCT")
    _lk(ng, raw_dir, 0, dot, 0)
    _lk(ng, unit, 0, dot, 1)
    proj = _nd(ng, "ShaderNodeVectorMath", (-730, -460), "that much of it",
               role="CONSTRAINT", operation="SCALE")
    _lk(ng, unit, 0, proj, 0)
    _lk(ng, dot, 1, proj, 3)
    perp = _nd(ng, "ShaderNodeVectorMath", (-550, -300),
               "the rest: sideways", role="CONSTRAINT",
               operation="SUBTRACT")
    _lk(ng, raw_dir, 0, perp, 0)
    _lk(ng, proj, 0, perp, 1)
    fb_a = _nd(ng, "ShaderNodeVectorMath", (-730, -620), "beam x up",
               role="CONSTRAINT", operation="CROSS_PRODUCT")
    _lk(ng, unit, 0, fb_a, 0)
    _sv(fb_a, 1, (0.0, 0.0, 1.0))
    fb_b = _nd(ng, "ShaderNodeVectorMath", (-730, -780), "beam x X",
               role="CONSTRAINT", operation="CROSS_PRODUCT")
    _lk(ng, unit, 0, fb_b, 0)
    _sv(fb_b, 1, (1.0, 0.0, 0.0))
    la = _nd(ng, "ShaderNodeVectorMath", (-550, -620), "how long",
             role="CONSTRAINT", operation="LENGTH")
    _lk(ng, fb_a, 0, la, 0)
    lb = _nd(ng, "ShaderNodeVectorMath", (-550, -780), "how long",
             role="CONSTRAINT", operation="LENGTH")
    _lk(ng, fb_b, 0, lb, 0)
    longer = _nd(ng, "FunctionNodeCompare", (-370, -700), "a beats b?",
                 role="CONSTRAINT", data_type="FLOAT",
                 operation="GREATER_THAN")
    _lk(ng, la, 1, longer, 0)
    _lk(ng, lb, 1, longer, 1)
    fb = _nd(ng, "GeometryNodeSwitch", (-190, -700), "the longer fallback",
             role="CONSTRAINT", input_type="VECTOR")
    _lk(ng, longer, 0, fb, 0)
    _lk(ng, fb_b, 0, fb, 1)
    _lk(ng, fb_a, 0, fb, 2)
    p_len = _nd(ng, "ShaderNodeVectorMath", (-370, -460), "anything left?",
                role="CONSTRAINT", operation="LENGTH")
    _lk(ng, perp, 0, p_len, 0)
    degen = _nd(ng, "FunctionNodeCompare", (-190, -460),
                "parallel to the beam?", role="CONSTRAINT",
                data_type="FLOAT", operation="LESS_THAN")
    _lk(ng, p_len, 1, degen, 0)
    _sv(degen, 1, 1e-4)
    dir_use = _nd(ng, "GeometryNodeSwitch", (-10, -540), "sideways, always",
                  role="CONSTRAINT", input_type="VECTOR")
    _lk(ng, degen, 0, dir_use, 0)
    _lk(ng, perp, 0, dir_use, 1)
    _lk(ng, fb, 0, dir_use, 2)
    dirn_b = _nd(ng, "ShaderNodeVectorMath", (170, -540), "unit bow",
                 role="CONSTRAINT", operation="NORMALIZE")
    _lk(ng, dir_use, 0, dirn_b, 0)

    salt2 = _nd(ng, "ShaderNodeMath", (-1450, -540), "seed + salt'",
                role="CONSTRAINT", operation="ADD")
    _lk(ng, gi, I["Seed"], salt2, 0)
    _sv(salt2, 1, 78.0)
    mag_roll = _nd(ng, "FunctionNodeRandomValue", (-1270, -540),
                   "how much of it, per particle", role="CONSTRAINT")
    mag_roll.data_type = "FLOAT"
    _sv(mag_roll, 0, 0.0)
    _sv(mag_roll, 1, 1.0)
    _lk(ng, gi, I["ID"], mag_roll, 2)
    _lk(ng, salt2, 0, mag_roll, 3)
    mag_a = _nd(ng, "ShaderNodeMath", (350, -620), "bulge x roll",
                role="CONSTRAINT", operation="MULTIPLY")
    _lk(ng, gi, I["Random Bulge"], mag_a, 0)
    _lk(ng, mag_roll, 0, mag_a, 1)   # 0.26.3: 5.2's Random Value has one output
    mag = _nd(ng, "ShaderNodeMath", (530, -620), "x path length",
              role="CONSTRAINT", operation="MULTIPLY")
    _lk(ng, mag_a, 0, mag, 0)
    _lk(ng, seg_len, 1, mag, 1)
    bow = _nd(ng, "ShaderNodeVectorMath", (710, -540), "the bow itself",
              role="CONSTRAINT", operation="SCALE")
    _lk(ng, dirn_b, 0, bow, 0)
    _lk(ng, mag, 0, bow, 3)
    mid = _nd(ng, "ShaderNodeVectorMath", (-910, 40), "midpoint, bowed",
              role="CONSTRAINT", operation="ADD")
    _lk(ng, mid_base, 1, mid, 0)
    _lk(ng, bow, 0, mid, 1)

    # Quadratic bezier thru start / mid / end, evaluated at t
    leg_a = _nd(ng, "ShaderNodeMix", (-730, 200), "start -> mid",
                role="CONSTRAINT", data_type="VECTOR")
    _lk(ng, t, 0, leg_a, 0)
    _lk(ng, gi, I["Start"], leg_a, 4)
    _lk(ng, mid, 0, leg_a, 5)
    leg_b = _nd(ng, "ShaderNodeMix", (-730, 20), "mid -> end",
                role="CONSTRAINT", data_type="VECTOR")
    _lk(ng, t, 0, leg_b, 0)
    _lk(ng, mid, 0, leg_b, 4)
    _lk(ng, gi, I["End"], leg_b, 5)
    anchor = _nd(ng, "ShaderNodeMix", (-550, 120), "the anchor, travelling",
                 role="CONSTRAINT", data_type="VECTOR")
    _lk(ng, t, 0, anchor, 0)
    _lk(ng, leg_a, 1, anchor, 4)
    _lk(ng, leg_b, 1, anchor, 5)

    # ── the distance envelope along the path ─────────────────────────────
    # -1 (the engine's sentinel) means "same as Maximum Distance"
    def sentinel(idx_name, y, tag):
        neg = _nd(ng, "ShaderNodeMath", (-1450, y), f"{tag} authored?",
                  role="CONSTRAINT", operation="LESS_THAN")
        _lk(ng, gi, I[idx_name], neg, 0)
        _sv(neg, 1, 0.0)
        pick = _nd(ng, "GeometryNodeSwitch", (-1270, y),
                   f"{tag}: -1 = same as max", role="CONSTRAINT",
                   input_type="FLOAT")
        _lk(ng, neg, 0, pick, 0)
        _lk(ng, gi, I[idx_name], pick, 1)
        _lk(ng, gi, I["Max Distance"], pick, 2)
        return pick

    mid_d = sentinel("Max Distance Middle", 620, "middle")
    end_d = sentinel("Max Distance End", 800, "end")
    t2 = _nd(ng, "ShaderNodeMath", (-910, 620), "t x 2", role="CONSTRAINT",
             operation="MULTIPLY")
    _lk(ng, t, 0, t2, 0)
    _sv(t2, 1, 2.0)
    t2b = _nd(ng, "ShaderNodeMath", (-910, 780), "t x 2 - 1",
              role="CONSTRAINT", operation="SUBTRACT")
    _lk(ng, t2, 0, t2b, 0)
    _sv(t2b, 1, 1.0)
    e1 = _nd(ng, "ShaderNodeMix", (-730, 620), "max -> middle",
             role="CONSTRAINT", data_type="FLOAT")
    _lk(ng, t2, 0, e1, 0)
    _lk(ng, gi, I["Max Distance"], e1, 2)
    _lk(ng, mid_d, 0, e1, 3)
    e2 = _nd(ng, "ShaderNodeMix", (-730, 460), "middle -> end",
             role="CONSTRAINT", data_type="FLOAT")
    _lk(ng, t2b, 0, e2, 0)
    _lk(ng, mid_d, 0, e2, 2)
    _lk(ng, end_d, 0, e2, 3)
    first_half = _nd(ng, "FunctionNodeCompare", (-550, 540),
                     "first half of the path?", role="CONSTRAINT",
                     data_type="FLOAT", operation="LESS_THAN")
    _lk(ng, t, 0, first_half, 0)
    _sv(first_half, 1, 0.5)
    env = _nd(ng, "GeometryNodeSwitch", (-370, 540), "the envelope now",
              role="CONSTRAINT", input_type="FLOAT")
    _lk(ng, first_half, 0, env, 0)
    # ⚠️ OUTPUT 0, not 1. A FLOAT-mode Mix keeps its answer on Result
    # index 0; index 1 is the VECTOR result, which a float Mix never
    # computes - it reads back as ZERO, silently. Wired to 1, the whole
    # distance envelope evaluated to 0, every particle was glued exactly
    # onto its anchor, and no Maximum Distance slider (or any force) could
    # ever do anything - measured as "max 500 + force 9000 changes
    # nothing". The vector mixes above really do use output 1
    _lk(ng, e2, 0, env, 1)
    _lk(ng, e1, 0, env, 2)
    env_hu = _nd(ng, "ShaderNodeMath", (-190, 540), "envelope x scale",
                 role="CONSTRAINT", operation="MULTIPLY")
    _lk(ng, env, 0, env_hu, 0)
    _lk(ng, gi, I["Scale"], env_hu, 1)
    min_hu = _nd(ng, "ShaderNodeMath", (-190, 700), "min x scale",
                 role="CONSTRAINT", operation="MULTIPLY")
    _lk(ng, gi, I["Min Distance"], min_hu, 0)
    _lk(ng, gi, I["Scale"], min_hu, 1)

    # ── clamp the particle to the envelope ───────────────────────────────
    delta = _nd(ng, "ShaderNodeVectorMath", (-370, 120), "anchor -> particle",
                role="CONSTRAINT", operation="SUBTRACT")
    _lk(ng, gi, I["Position"], delta, 0)
    _lk(ng, anchor, 1, delta, 1)
    dist = _nd(ng, "ShaderNodeVectorMath", (-190, 60), "how far off the path",
               role="CONSTRAINT", operation="LENGTH")
    _lk(ng, delta, 0, dist, 0)
    dirn = _nd(ng, "ShaderNodeVectorMath", (-190, 220), "which way off it",
               role="CONSTRAINT", operation="NORMALIZE")
    _lk(ng, delta, 0, dirn, 0)
    at_least = _nd(ng, "ShaderNodeMath", (-10, 60), "at least min",
                   role="CONSTRAINT", operation="MAXIMUM")
    _lk(ng, dist, 1, at_least, 0)
    _lk(ng, min_hu, 0, at_least, 1)
    # MAX WINS: min first, max second, so "end 0 min 1" lands ON the path
    at_most = _nd(ng, "ShaderNodeMath", (170, 60), "at most the envelope",
                  role="CONSTRAINT", operation="MINIMUM")
    _lk(ng, at_least, 0, at_most, 0)
    _lk(ng, env_hu, 0, at_most, 1)
    held = _nd(ng, "ShaderNodeVectorMath", (350, 160), "held that far out",
               role="CONSTRAINT", operation="SCALE")
    _lk(ng, dirn, 0, held, 0)
    _lk(ng, at_most, 0, held, 3)
    clamped = _nd(ng, "ShaderNodeVectorMath", (530, 120), "anchor + that",
                  role="CONSTRAINT", operation="ADD")
    _lk(ng, anchor, 1, clamped, 0)
    _lk(ng, held, 0, clamped, 1)

    # ── envelope strength + the enable switch ────────────────────────────
    eased = _nd(ng, "ShaderNodeMix", (710, 60), "envelope eases it in",
                role="CONSTRAINT", data_type="VECTOR")
    _lk(ng, gi, I["Strength"], eased, 0)
    _lk(ng, gi, I["Position"], eased, 4)
    _lk(ng, clamped, 0, eased, 5)
    sw = _nd(ng, "GeometryNodeSwitch", (890, 0), "enabled?",
             role="CONSTRAINT", input_type="VECTOR")
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, gi, I["Position"], sw, 1)
    _lk(ng, eased, 1, sw, 2)
    _lk(ng, sw, 0, go, 0)

    note(ng, "CONSTRAINT  ·  Constrain distance to path", "CONSTRAINT", """
    anchor(t) = bezier(start, bowed midpoint, end)   t = min(age/travel, 1)
    position  = anchor + direction x clamp(distance, min, envelope(t))

THE ENVELOPE is Maximum Distance at departure, Middle halfway, End on
arrival - and -1 for Middle or End means "same as Maximum", which is the
engine's own sentinel for "not authored".

MAX WINS OVER MIN where they cross. beam (king) authors end 0 with min 1:
by the time the anchor arrives, every particle is ON the path. That is the
authoring idiom for a beam that crackles and then converges.

RANDOM BULGE bows the path through an offset midpoint. Bulge Control picks
the DIRECTION - 0 rolls one per particle, 1/2 take the start/end control
point's own up axis through its rotation, so rotating the empty steers
where the bow goes. The magnitude is Random Bulge x roll(0..1) x the
path's own length - a FRACTION of the path, and the SIGN survives: a
negative Random Bulge bows the whole system to the OPPOSITE side, which is
how three beams with +RB / -RB / +RB' read as three different beams.

⚠️ APPLIED PER FRAME INSIDE THE SIMULATION as well as on the final
position. The per-frame pass is what makes it SFM-true: forces push the
particle a little, the leash pulls it back, and the next frame pushes from
the CLAMPED spot - so the beam WANDERS inside the envelope instead of
saturating against it as a fat tube.

WHY THIS EXISTS: a beam's random force is authored WILD - +-1255 with drag
0.001 is a terminal velocity of ~42000 HU/s - because the author knows this
constraint reins it in every frame. Import the force without the constraint
and the beam simply leaves.
""", [tt_safe, t_raw, t, mid_base, seg, seg_len, unit, up, is2, rot_pick,
      oriented, salt, roll, is0, raw_dir, dot, proj, perp, fb_a, fb_b, la,
      lb, longer, fb, p_len, degen, dir_use, dirn_b, salt2, mag_roll, mag_a,
      mag, bow, mid, leg_a, leg_b, anchor, mid_d, end_d, t2, t2b, e1, e2,
      first_half, env, env_hu, min_hu, delta, dist, dirn, at_least, at_most,
      held, clamped, eased, sw])
    return ng
