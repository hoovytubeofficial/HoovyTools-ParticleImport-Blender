# =============================================================================
#  tools/ras_nodes.py  -  RENDER ANIMATED SPRITES, built out of SFM's own parts
# =============================================================================
#
#  One node group per SFM operator, each with its own ENABLE toggle, wired into
#  a top-level group whose modifier panels are the SFM sections:
#
#      CONTROL POINTS · RENDERER · EMITTER · INITIALIZER · OPERATOR
#      FORCE GENERATOR · CONSTRAINT · CHILDREN
#
#  STATELESS on purpose - no simulation zone, no cache, no bake. Every
#  particle's whole life is derived from the clock and its slot number, so you
#  can scrub the timeline in BOTH directions and it is always right.
#
#  THE EMISSION RING
#  -----------------
#  "Max Particles" slots sit in a ring. Slot i is born at
#      birth = emission start + i / emission rate
#  and the ring recycles every (Max Particles / rate) seconds. A slot is only
#  visible while its age is inside its lifetime, so raising the rate really
#  does emit more often. Keep Max Particles >= rate x longest lifetime or the
#  ring wraps before particles have died and you get gaps.
#
#  THE OPERATOR ENVELOPE (verified against the Valve wiki, Generic Operator
#  Options - developer.valvesoftware.com/wiki/Particle_System_Operators/
#  Generic_Operator_Options)
#      operator start/end fadein  - operator ramps 0 -> full strength
#      operator start/end fadeout - operator ramps full -> 0
#      operator fade oscillate    - when 0, the four times above are RAW
#                                   SECONDS since the system started. When set
#                                   to N seconds they become PROPORTIONS of N
#                                   and the whole envelope LOOPS every N
#                                   seconds. So oscillate 5 with fadein 0.2
#                                   means one second in, repeating every five.
#  All four at zero = operator always fully on, which is the common default.
# =============================================================================

import bpy

from .sprite_nodes import (_group, _sock, _nd, _lk, _sv, note, ROLE,
                           sequence_table, build_sheet_uv_group,
                           build_sprite_material, proxy_material)

EPS = 1e-4


def _gin(ng):
    """Map a group's INPUT socket names to their index.

    ALWAYS use this instead of hard-coded indices. Inserting one socket
    shifts every index after it, and the graph keeps building happily while
    quietly multiplying distance by the particle ID instead of Scale - which
    is precisely the bug this replaced."""
    idx = {}
    n = 0
    for it in ng.interface.items_tree:
        if getattr(it, "item_type", "") == "SOCKET" and it.in_out == "INPUT":
            idx[it.name] = n
            n += 1
    return idx


def _io(ng, a=(-1200, 0), b=(1200, 0)):
    return _nd(ng, "NodeGroupInput", a), _nd(ng, "NodeGroupOutput", b)


def _enable_mix(ng, gi, enable_idx, off_node, off_out, on_node, on_out,
                loc, label, kind="FLOAT"):
    """Switch between 'operator off' and 'operator on'."""
    sw = _nd(ng, "GeometryNodeSwitch", loc, label, role="OPERATOR",
             input_type=kind)
    _lk(ng, gi, enable_idx, sw, 0)
    _lk(ng, off_node, off_out, sw, 1)
    _lk(ng, on_node, on_out, sw, 2)
    return sw


# =============================================================================
#  THE COMMON OPERATOR ENVELOPE
# =============================================================================

def build_envelope():
    ng = _group("SP · ENVELOPE · Operator Fade", "GeometryNodeTree")
    _sock(ng, "Strength", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Start Fade In", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "End Fade In", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Start Fade Out", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "End Fade Out", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Fade Oscillate", "INPUT", "NodeSocketFloat", 0.0)
    gi, go = _io(ng, (-1400, 0), (1200, 0))

    # oscillate > 0 -> time becomes a 0..1 position inside the N second loop
    osc_on = _nd(ng, "FunctionNodeCompare", (-1180, -320), "oscillating?",
                 role="TIME", data_type="FLOAT", operation="GREATER_THAN")
    _lk(ng, gi, 5, osc_on, 0)
    _sv(osc_on, 1, 0.0)
    wrapped = _nd(ng, "ShaderNodeMath", (-1180, -140), "time % oscillate",
                  role="TIME", operation="WRAP")
    _lk(ng, gi, 0, wrapped, 0)
    _lk(ng, gi, 5, wrapped, 1)
    _sv(wrapped, 2, 0.0)
    osc_safe = _nd(ng, "ShaderNodeMath", (-1180, 40), "avoid divide by zero",
                   role="TIME", operation="MAXIMUM")
    _lk(ng, gi, 5, osc_safe, 0)
    _sv(osc_safe, 1, EPS)
    phase = _nd(ng, "ShaderNodeMath", (-980, -140), "-> 0..1 of the loop",
                role="TIME", operation="DIVIDE")
    _lk(ng, wrapped, 0, phase, 0)
    _lk(ng, osc_safe, 0, phase, 1)
    t = _nd(ng, "GeometryNodeSwitch", (-780, -60),
            "raw seconds, or loop phase", role="TIME", input_type="FLOAT")
    _lk(ng, osc_on, 0, t, 0)
    _lk(ng, gi, 0, t, 1)
    _lk(ng, phase, 0, t, 2)

    # fade in ramp, guarded against a zero-length window
    fi_hi = _nd(ng, "ShaderNodeMath", (-560, 320), "never a zero window",
                role="OPERATOR", operation="MAXIMUM")
    _lk(ng, gi, 2, fi_hi, 0)
    add_eps = _nd(ng, "ShaderNodeMath", (-760, 320), role="OPERATOR",
                  operation="ADD")
    _lk(ng, gi, 1, add_eps, 0)
    _sv(add_eps, 1, EPS)
    _lk(ng, add_eps, 0, fi_hi, 1)
    fin = _nd(ng, "ShaderNodeMapRange", (-340, 320), "fade in", role="OPERATOR",
              clamp=True)
    _lk(ng, t, 0, fin, 0)
    _lk(ng, gi, 1, fin, 1)
    _lk(ng, fi_hi, 0, fin, 2)
    _sv(fin, 3, 0.0)
    _sv(fin, 4, 1.0)

    # fade out ramp
    fo_hi = _nd(ng, "ShaderNodeMath", (-560, -20), "never a zero window",
                role="OPERATOR", operation="MAXIMUM")
    _lk(ng, gi, 4, fo_hi, 0)
    add_eps2 = _nd(ng, "ShaderNodeMath", (-760, -20), role="OPERATOR",
                   operation="ADD")
    _lk(ng, gi, 3, add_eps2, 0)
    _sv(add_eps2, 1, EPS)
    _lk(ng, add_eps2, 0, fo_hi, 1)
    fout = _nd(ng, "ShaderNodeMapRange", (-340, -20), "fade out",
               role="OPERATOR", clamp=True)
    _lk(ng, t, 0, fout, 0)
    _lk(ng, gi, 3, fout, 1)
    _lk(ng, fo_hi, 0, fout, 2)
    _sv(fout, 3, 1.0)
    _sv(fout, 4, 0.0)

    # a fade out only applies if one was actually asked for
    has_out = _nd(ng, "FunctionNodeCompare", (-340, -300),
                  "was a fade out set?", role="OPERATOR", data_type="FLOAT",
                  operation="GREATER_THAN")
    _lk(ng, gi, 4, has_out, 0)
    _sv(has_out, 1, 0.0)
    fout_or_1 = _nd(ng, "GeometryNodeSwitch", (-120, -160), "fade out or 1",
                    role="OPERATOR", input_type="FLOAT")
    _lk(ng, has_out, 0, fout_or_1, 0)
    _sv(fout_or_1, 1, 1.0)
    _lk(ng, fout, 0, fout_or_1, 2)

    both = _nd(ng, "ShaderNodeMath", (120, 120), "fade in x fade out",
               role="OPERATOR", operation="MULTIPLY")
    _lk(ng, fin, 0, both, 0)
    _lk(ng, fout_or_1, 0, both, 1)

    # all four at zero = no envelope at all = always fully on
    sum_all = _nd(ng, "ShaderNodeMath", (120, -320), "any envelope set?",
                  role="OPERATOR", operation="ADD")
    _lk(ng, gi, 2, sum_all, 0)
    _lk(ng, gi, 4, sum_all, 1)
    any_env = _nd(ng, "FunctionNodeCompare", (320, -320), role="OPERATOR",
                  data_type="FLOAT", operation="GREATER_THAN")
    _lk(ng, sum_all, 0, any_env, 0)
    _sv(any_env, 1, 0.0)
    final = _nd(ng, "GeometryNodeSwitch", (560, 0), "envelope, or always on",
                role="OPERATOR", input_type="FLOAT")
    _lk(ng, any_env, 0, final, 0)
    _sv(final, 1, 1.0)
    _lk(ng, both, 0, final, 2)
    _lk(ng, final, 0, go, 0)

    note(ng, "OPERATOR ENVELOPE  ·  when is this operator ON?", "OPERATOR", """
This is SFM's COMMON OPERATOR ENVELOPE. It does not touch particle alpha - it
controls how strongly the OPERATOR ITSELF acts, from 0 to 1.

    start fade in  -> end fade in    strength ramps 0 -> 1
    start fade out -> end fade out   strength ramps 1 -> 0

FADE OSCILLATE (verified on the Valve wiki, Generic Operator Options)
    oscillate = 0  the four times above are RAW SECONDS since the particle
                   system started.
    oscillate = N  they become PROPORTIONS of an N second loop, and the whole
                   envelope REPEATS every N seconds. With oscillate 5, a fade
                   in of 0.2 happens one second in; a fade out of 0.8 happens
                   at four seconds; then it starts over.

ALL FOUR AT ZERO means "no envelope", which is the usual default - the
operator is simply always fully on. That case is handled explicitly, because
otherwise a zero-width Map Range would return 0 and silently disable
everything.
""", [osc_on, wrapped, osc_safe, phase, t, add_eps, fi_hi, fin, add_eps2,
      fo_hi, fout, has_out, fout_or_1, both, sum_all, any_env, final])
    return ng


# =============================================================================
#  EMITTER
# =============================================================================

def build_emit_continuously():
    ng = _group("SP · EMITTER · emit_continuously", "GeometryNodeTree")
    _sock(ng, "Birth Time", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Age", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Particle ID", "OUTPUT", "NodeSocketInt")
    _sock(ng, "Emitted", "OUTPUT", "NodeSocketBool")
    _sock(ng, "Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Slot", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Max Particles", "INPUT", "NodeSocketFloat", 100.0)
    _sock(ng, "Emission Rate", "INPUT", "NodeSocketFloat", 20.0)
    _sock(ng, "Emission Start Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Longest Lifetime", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-1200, 0), (1100, 0))
    I = _gin(ng)

    rate = _nd(ng, "ShaderNodeMath", (-980, -180), "rate, never zero",
               role="EMITTER", operation="MAXIMUM")
    _lk(ng, gi, I["Emission Rate"], rate, 0)
    _sv(rate, 1, EPS)
    want_gap = _nd(ng, "ShaderNodeMath", (-800, -260), "1 / rate",
                   role="EMITTER", operation="DIVIDE")
    _sv(want_gap, 0, 1.0)
    _lk(ng, rate, 0, want_gap, 1)
    # A slot may only be reborn once its PREVIOUS life has ended, or particles
    # pop out of existence mid-flight. So the gap can never be shorter than
    # (longest lifetime / slots) - which is exactly what capping the
    # population means: at the cap the emitter throttles, it does not kill.
    slots = _nd(ng, "ShaderNodeMath", (-980, -420), "slots, never zero",
                role="EMITTER", operation="MAXIMUM")
    _lk(ng, gi, I["Max Particles"], slots, 0)
    _sv(slots, 1, 1.0)
    min_gap = _nd(ng, "ShaderNodeMath", (-800, -420),
                  "lifetime / slots = the cap", role="EMITTER",
                  operation="DIVIDE")
    _lk(ng, gi, I["Longest Lifetime"], min_gap, 0)
    _lk(ng, slots, 0, min_gap, 1)
    gap = _nd(ng, "ShaderNodeMath", (-620, -340),
              "whichever is SLOWER", role="EMITTER", operation="MAXIMUM")
    _lk(ng, want_gap, 0, gap, 0)
    _lk(ng, min_gap, 0, gap, 1)
    ring = _nd(ng, "ShaderNodeMath", (-440, -420), "slots x gap = ring time",
               role="EMITTER", operation="MULTIPLY")
    _lk(ng, slots, 0, ring, 0)
    _lk(ng, gap, 0, ring, 1)

    offset = _nd(ng, "ShaderNodeMath", (-260, 0), "slot x gap", role="EMITTER",
                 operation="MULTIPLY")
    _lk(ng, gi, I["Slot"], offset, 0)
    _lk(ng, gap, 0, offset, 1)
    since_start = _nd(ng, "ShaderNodeMath", (-620, 200), "time - start",
                      role="TIME", operation="SUBTRACT")
    _lk(ng, gi, I["Time"], since_start, 0)
    _lk(ng, gi, I["Emission Start Time"], since_start, 1)
    since = _nd(ng, "ShaderNodeMath", (-420, 120), "- this slot's offset",
                role="TIME", operation="SUBTRACT")
    _lk(ng, since_start, 0, since, 0)
    _lk(ng, offset, 0, since, 1)

    age = _nd(ng, "ShaderNodeMath", (-220, 200), "age = that % ring",
              role="TIME", operation="WRAP")
    _lk(ng, since, 0, age, 0)
    _lk(ng, ring, 0, age, 1)
    _sv(age, 2, 0.0)

    life_no = _nd(ng, "ShaderNodeMath", (-220, -80), "how many rings so far",
                  role="TIME", operation="FLOOR")
    div = _nd(ng, "ShaderNodeMath", (-420, -80), role="TIME",
              operation="DIVIDE")
    _lk(ng, since, 0, div, 0)
    _lk(ng, ring, 0, div, 1)
    _lk(ng, div, 0, life_no, 0)

    pid = _nd(ng, "ShaderNodeMath", (0, -80), "a fresh id every ring",
              role="EMITTER", operation="MULTIPLY_ADD")
    _lk(ng, life_no, 0, pid, 0)
    _sv(pid, 1, 977.0)
    _lk(ng, gi, I["Slot"], pid, 2)
    pid_i = _nd(ng, "FunctionNodeFloatToInt", (200, -80), role="EMITTER")
    _lk(ng, pid, 0, pid_i, 0)

    birth = _nd(ng, "ShaderNodeMath", (200, 300), "when it was born",
                role="EMITTER", operation="SUBTRACT")
    _lk(ng, gi, I["Time"], birth, 0)
    _lk(ng, age, 0, birth, 1)

    emitted = _nd(ng, "FunctionNodeCompare", (200, -280),
                  "has the emitter started?", role="EMITTER",
                  data_type="FLOAT", operation="GREATER_EQUAL")
    _lk(ng, since, 0, emitted, 0)
    _sv(emitted, 1, 0.0)

    _lk(ng, birth, 0, go, 0)
    _lk(ng, age, 0, go, 1)
    _lk(ng, pid_i, 0, go, 2)
    _lk(ng, emitted, 0, go, 3)

    note(ng, "EMITTER  ·  emit_continuously", "EMITTER", """
A RING of "Max Particles" slots, recycled forever.

    gap = MAX( 1 / emission rate ,  longest lifetime / slots )
    slot i is born at  start + i x gap
    the ring recycles every  slots x gap  seconds

WHY THE MAX. Max Particles is a CAP on how many exist at once. If you ask for
more than the cap allows, SFM stops emitting until something dies - it does
NOT delete living particles. Taking whichever gap is SLOWER does exactly that:
below the cap you get your requested rate; at the cap the emitter throttles to
(slots / lifetime) per second and the population sits flat.

Without that max, a slot could be reborn while its previous particle was still
alive, and you would see particles vanish in mid-flight. That was a real bug.

"a fresh id every ring" gives each recycled slot a NEW particle id
(ring x 977 + slot) so its random values are re-rolled. Without it, slot 3
would draw the same sequence and the same scatter for ever.
""", [rate, gap, ring, offset, since_start, since, age, div, life_no, pid,
      pid_i, birth, emitted])
    return ng


def build_emit_sim():
    """HOW MANY PARTICLES ARE BORN THIS FRAME.

    The simulation-zone emitter. Unlike the ring, this one does not lay birth
    times out in advance - it is asked once per frame "how many now?" and the
    zone remembers whatever it made.

        carry = carry + rate x envelope x delta time
        want  = floor(carry)          whole particles only
        carry = carry - want          the fraction rolls into the next frame

    THE CARRY IS WHY FRACTIONAL RATES WORK. At 3 particles/second and 60 fps
    a frame is owed 0.05 of a particle; without somewhere to keep that
    fraction it rounds to zero every frame and nothing is ever emitted.

    THE CAP THROTTLES, IT NEVER KILLS.

        count = min(want, max_particles - alive)

    and the carry is reduced by WANT, not by COUNT. That matters: consuming
    only what was emitted would bank a backlog and fire it all at once the
    moment a particle died. SFM does not queue - if there was no room, that
    particle was simply never born."""
    ng = _group("SP · EMITTER · emit_continuously (simulation)",
                "GeometryNodeTree")
    _sock(ng, "Count", "OUTPUT", "NodeSocketInt")
    _sock(ng, "Carry Out", "OUTPUT", "NodeSocketFloat")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Delta Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Emission Start Time", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Emission Rate", "INPUT", "NodeSocketFloat", 20.0)
    _sock(ng, "Envelope", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Carry In", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Alive", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Max Particles", "INPUT", "NodeSocketInt", 200)
    _sock(ng, "Extra This Frame", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-1200, 0), (1200, 0))
    I = _gin(ng)

    started = _nd(ng, "FunctionNodeCompare", (-980, 260), "has it started?",
                  role="TIME", data_type="FLOAT", operation="GREATER_EQUAL")
    _lk(ng, gi, I["Time"], started, 0)
    _lk(ng, gi, I["Emission Start Time"], started, 1)
    on = _nd(ng, "FunctionNodeBooleanMath", (-780, 260), "on, and started",
             role="EMITTER", operation="AND")
    _lk(ng, gi, I["Enable"], on, 0)
    _lk(ng, started, 0, on, 1)

    rate_on = _nd(ng, "GeometryNodeSwitch", (-560, 120), "rate, or nothing",
                  role="EMITTER", input_type="FLOAT")
    _lk(ng, on, 0, rate_on, 0)
    _sv(rate_on, 1, 0.0)
    _lk(ng, gi, I["Emission Rate"], rate_on, 2)

    # The operator envelope SCALES the rate rather than switching it. A fade
    # out therefore thins the stream out instead of cutting it dead, which is
    # what "operator strength" means everywhere else in SFM.
    rate_eff = _nd(ng, "ShaderNodeMath", (-340, 120), "x envelope strength",
                   role="EMITTER", operation="MULTIPLY")
    _lk(ng, rate_on, 0, rate_eff, 0)
    _lk(ng, gi, I["Envelope"], rate_eff, 1)

    carry = _nd(ng, "ShaderNodeMath", (-120, 120), "carry + rate x dt",
                role="EMITTER", operation="MULTIPLY_ADD")
    _lk(ng, rate_eff, 0, carry, 0)
    _lk(ng, gi, I["Delta Time"], carry, 1)
    _lk(ng, gi, I["Carry In"], carry, 2)

    want = _nd(ng, "ShaderNodeMath", (100, 220), "whole particles owed",
               role="EMITTER", operation="FLOOR")
    _lk(ng, carry, 0, want, 0)
    left = _nd(ng, "ShaderNodeMath", (100, 40), "the fraction, kept for later",
               role="EMITTER", operation="SUBTRACT")
    _lk(ng, carry, 0, left, 0)
    _lk(ng, want, 0, left, 1)

    room = _nd(ng, "ShaderNodeMath", (100, -180), "cap - alive",
               role="EMITTER", operation="SUBTRACT")
    _lk(ng, gi, I["Max Particles"], room, 0)
    _lk(ng, gi, I["Alive"], room, 1)
    room_pos = _nd(ng, "ShaderNodeMath", (320, -180), "never negative",
                   role="EMITTER", operation="MAXIMUM")
    _lk(ng, room, 0, room_pos, 0)
    _sv(room_pos, 1, 0.0)

    # A BURST GOES THROUGH THE SAME CAP. emit_instantaneously adds its
    # count here, before the cap, so asking for 2000 with a cap of 200 gets
    # 200 - and the rest are never born rather than queued.
    plus_burst = _nd(ng, "ShaderNodeMath", (320, 220), "+ any burst",
                     role="EMITTER", operation="ADD")
    _lk(ng, want, 0, plus_burst, 0)
    _lk(ng, gi, I["Extra This Frame"], plus_burst, 1)
    count_f = _nd(ng, "ShaderNodeMath", (540, 40), "whichever is fewer",
                  role="EMITTER", operation="MINIMUM")
    _lk(ng, plus_burst, 0, count_f, 0)
    _lk(ng, room_pos, 0, count_f, 1)
    count = _nd(ng, "FunctionNodeFloatToInt", (760, 40), "as a count",
                role="EMITTER", rounding_mode="FLOOR")
    _lk(ng, count_f, 0, count, 0)

    _lk(ng, count, 0, go, 0)
    _lk(ng, left, 0, go, 1)

    note(ng, "EMITTER  ·  emit_continuously, per frame", "EMITTER", """
Asked once per frame: HOW MANY PARTICLES ARE BORN NOW?

    carry = carry + rate x envelope x delta time
    want  = floor(carry)
    carry = carry - want
    count = min( want , max particles - alive )

THE CARRY is what makes fractional rates work. Three particles a second at 60
fps owes each frame 0.05 of a particle; with nowhere to keep that fraction it
rounds to zero every single frame and nothing is ever emitted.

THE CARRY IS REDUCED BY *WANT*, NOT BY *COUNT*. If the cap refused a particle,
that particle is gone - not queued. Subtracting only what was actually emitted
would bank a debt and dump it in one burst the instant something died.

THE ENVELOPE SCALES THE RATE instead of switching emission on and off, so a
fade out thins the stream rather than cutting it dead.

There is no ring here and no recycling. A particle exists from the frame it is
born until the frame it dies, and nothing can overwrite a live one - which is
the entire reason this replaced the ring.
""", [started, on, rate_on, rate_eff, carry, want, left, room, room_pos,
      plus_burst, count_f, count])
    return ng


# =============================================================================
#  INITIALIZERS
# =============================================================================

def _random_group(name, label, socket, dmin, dmax, salt,
                  mix_type="FLOAT", convert=None, base=False):
    """One SFM "<something> Random" initializer.

    socket     the type Min/Max/Fallback are authored in, in SFM'S OWN UNITS
    mix_type   FLOAT / VECTOR / RGBA - which half of the Mix node to use
    convert    "deg2rad" or "byte", applied on the way OUT so the sockets stay
               in the units the particle editor shows
    base       add a "Base" input (rotation_initial) before converting
    """
    ng = _group(name, "GeometryNodeTree")
    # The OUTPUT is always the value Blender wants: radians, 0..1 alpha, a
    # colour. The INPUTS are always what SFM wrote in the .pcf.
    _sock(ng, "Value", "OUTPUT",
          "NodeSocketFloat" if convert else socket)
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Min", "INPUT", socket, dmin)
    _sock(ng, "Max", "INPUT", socket, dmax)
    _sock(ng, "Exponent", "INPUT", "NodeSocketFloat", 1.0, smin=0.001)
    if base:
        _sock(ng, "Base", "INPUT", socket, 0.0)
    _sock(ng, "Fallback", "INPUT", socket, dmin)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-800, 0), (900, 0))
    I = _gin(ng)

    salt_n = _nd(ng, "ShaderNodeMath", (-600, -320), "salt the seed",
                 role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I["Seed"], salt_n, 0)
    _sv(salt_n, 1, float(salt))
    salt_i = _nd(ng, "FunctionNodeFloatToInt", (-420, -320),
                 role="INITIALIZER")
    _lk(ng, salt_n, 0, salt_i, 0)

    # A PLAIN 0..1 ROLL, THEN A MIX - not Random Value between Min and Max.
    # Two reasons. SFM's *_random_exponent biases WHICH value gets drawn, and
    # that only exists if the roll is separable from the range. And Random
    # Value has NO COLOUR TYPE - its data_type only accepts FLOAT, INT,
    # BOOLEAN and FLOAT_VECTOR, so "RGBA" was silently rejected and Color
    # Random quietly returned a float. Mix handles every type.
    rv = _nd(ng, "FunctionNodeRandomValue", (-420, 60), f"{label} roll 0..1",
             role="INITIALIZER", data_type="FLOAT")
    _sv(rv, 0, 0.0)
    _sv(rv, 1, 1.0)
    _lk(ng, gi, I["ID"], rv, 2)
    _lk(ng, salt_i, 0, rv, 3)

    biased = _nd(ng, "ShaderNodeMath", (-220, 60), "roll ^ exponent",
                 role="INITIALIZER", operation="POWER")
    _lk(ng, rv, 0, biased, 0)
    _lk(ng, gi, I["Exponent"], biased, 1)

    A, B, OUT = {"FLOAT": (2, 3, 0), "VECTOR": (4, 5, 1),
                 "RGBA": (6, 7, 2)}[mix_type]
    mixed = _nd(ng, "ShaderNodeMix", (0, 0), f"{label} min -> max",
                role="INITIALIZER", data_type=mix_type,
                factor_mode="UNIFORM")
    _lk(ng, biased, 0, mixed, 0)
    _lk(ng, gi, I["Min"], mixed, A)
    _lk(ng, gi, I["Max"], mixed, B)

    kind = {"FLOAT": "FLOAT", "VECTOR": "VECTOR", "RGBA": "RGBA"}[mix_type]
    sw = _nd(ng, "GeometryNodeSwitch", (240, 0), "enabled?",
             role="INITIALIZER", input_type=kind)
    _lk(ng, gi, I["Enable"], sw, 0)
    _lk(ng, gi, I["Fallback"], sw, 1)
    _lk(ng, mixed, OUT, sw, 2)

    result, extra = sw, []
    if base:
        # rotation_initial is ADDED to the rolled offset, in SFM's own units,
        # before anything is converted.
        add_base = _nd(ng, "ShaderNodeMath", (440, 0), "+ initial",
                       role="INITIALIZER", operation="ADD")
        _lk(ng, sw, 0, add_base, 0)
        _lk(ng, gi, I["Base"], add_base, 1)
        result, extra = add_base, [add_base]

    if convert:
        # SFM UNITS IN, BLENDER UNITS OUT - and the conversion happens HERE,
        # after the switch, so the Fallback is quoted in SFM's units too. The
        # number in the modifier is the number the particle editor shows.
        factor, why = {"deg2rad": (0.017453292519943295, "degrees -> radians"),
                       "byte": (1.0 / 255.0, "0..255 -> 0..1")}[convert]
        conv = _nd(ng, "ShaderNodeMath", (640, 0), why, role="INITIALIZER",
                   operation="MULTIPLY")
        _lk(ng, result, 0, conv, 0)
        _sv(conv, 1, factor)
        result = conv
        extra.append(conv)

    _lk(ng, result, 0, go, 0)

    note(ng, f"INITIALIZER  ·  {label}", "INITIALIZER", f"""
Chosen ONCE, at birth, from the particle's id - so it never changes while the
particle is alive.

    roll  = random(0..1, from this particle's id)
    t     = roll ^ exponent
    value = mix(Min, Max, t)

THE EXPONENT BIASES THE DISTRIBUTION, NOT THE CURVE. Exponent 1 is uniform;
above 1 crowds the draw towards Min, below 1 towards Max. It is a real SFM
field ({label.lower().replace(' ', '_')}_exponent in the .pcf) and it was
missing entirely before.

WHY MIX AND NOT RANDOM VALUE BETWEEN MIN AND MAX. Random Value's data_type
accepts only FLOAT, INT, BOOLEAN and FLOAT_VECTOR - there is NO colour type,
so asking for one failed silently and Color Random returned a float. Mix
handles colour, and separating the roll from the range is what makes the
exponent possible at all.

The salt ({salt}) keeps this initializer's random stream independent from the
others, or every property would move together on the same particle.

Disabled -> the Fallback value is used instead.
""", [salt_n, salt_i, rv, biased, mixed, sw] + extra)
    return ng


def build_initializers():
    out = {}
    out["lifetime"] = _random_group(
        "SP · INITIALIZER · Lifetime Random", "Lifetime Random",
        "NodeSocketFloat", 1.0, 2.0, 11)
    out["radius"] = _random_group(
        "SP · INITIALIZER · Radius Random", "Radius Random",
        "NodeSocketFloat", 8.0, 16.0, 22)
    # alpha_min / alpha_max are 0..255 BYTES in a .pcf, not 0..1 factors.
    out["alpha"] = _random_group(
        "SP · INITIALIZER · Alpha Random", "Alpha Random",
        "NodeSocketFloat", 255.0, 255.0, 33, convert="byte")
    out["color"] = _random_group(
        "SP · INITIALIZER · Color Random", "Color Random",
        "NodeSocketColor", (1.0, 1.0, 1.0, 1.0), (1.0, 1.0, 1.0, 1.0), 44,
        mix_type="RGBA")
    # rotation_offset_min / max are DEGREES - a full turn is 360, and real
    # files run -360..360. rotation_initial is added on top.
    out["rotation"] = _random_group(
        "SP · INITIALIZER · Rotation Random", "Rotation Random",
        "NodeSocketFloat", 0.0, 360.0, 55, convert="deg2rad", base=True)

    # ── Position Within Sphere Random ────────────────────────────────────
    ng = _group("SP · INITIALIZER · Position Within Sphere Random",
                "GeometryNodeTree")
    _sock(ng, "Offset", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Velocity", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Distance Min", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Distance Max", "INPUT", "NodeSocketFloat", 10.0)
    _sock(ng, "Distance Bias", "INPUT", "NodeSocketVector", (1.0, 1.0, 1.0))
    _sock(ng, "Speed Min", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Speed Max", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Speed Exponent", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Local Speed Min", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Local Speed Max", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "CP Rotation", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Scale", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-1400, 0), (1200, 0))
    I = _gin(ng)

    seed_n = _nd(ng, "ShaderNodeMath", (-1200, -560), "salt the seed",
                 role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I['Seed'], seed_n, 0)
    _sv(seed_n, 1, 66.0)
    seed_i = _nd(ng, "FunctionNodeFloatToInt", (-1020, -560),
                 role="INITIALIZER")
    _lk(ng, seed_n, 0, seed_i, 0)

    rdir = _nd(ng, "FunctionNodeRandomValue", (-1000, 260), "random direction",
               role="INITIALIZER", data_type="FLOAT_VECTOR")
    _sv(rdir, 0, (-1.0, -1.0, -1.0))
    _sv(rdir, 1, (1.0, 1.0, 1.0))
    _lk(ng, gi, I['ID'], rdir, 2)
    _lk(ng, seed_i, 0, rdir, 3)
    #  distance_bias SQUASHES THE DIRECTION, componentwise, BEFORE the
    #  normalize. (1,1,1) is untouched; (1,1,0) kills Z and the sphere
    #  becomes a flat disc - which is how flat ground effects are authored.
    #  The re-normalize afterwards is what makes it a shape change rather
    #  than a size change: only the RATIO of the components matters.
    bias = _nd(ng, "ShaderNodeVectorMath", (-880, 380),
               "x distance bias [SFM: distance_bias]", role="INITIALIZER",
               operation="MULTIPLY")
    _lk(ng, rdir, 0, bias, 0)
    _lk(ng, gi, I['Distance Bias'], bias, 1)
    unit = _nd(ng, "ShaderNodeVectorMath", (-720, 260), "make it unit length",
               role="INITIALIZER", operation="NORMALIZE")
    _lk(ng, bias, 0, unit, 0)

    dist = _nd(ng, "FunctionNodeRandomValue", (-1000, 60), "distance out",
               role="INITIALIZER", data_type="FLOAT")
    _lk(ng, gi, I['Distance Min'], dist, 0)
    _lk(ng, gi, I['Distance Max'], dist, 1)
    _lk(ng, gi, I['ID'], dist, 2)
    _lk(ng, seed_i, 0, dist, 3)
    dist_s = _nd(ng, "ShaderNodeMath", (-800, 60), "x scale",
                 role="INITIALIZER", operation="MULTIPLY")
    _lk(ng, dist, 0, dist_s, 0)
    _lk(ng, gi, I['Scale'], dist_s, 1)
    offset = _nd(ng, "ShaderNodeVectorMath", (-600, 180),
                 "direction x distance", role="INITIALIZER",
                 operation="SCALE")
    _lk(ng, unit, 0, offset, 0)
    _lk(ng, dist_s, 0, offset, 3)

    # radial speed, along the same direction. Rolled 0..1, BENT BY THE
    # EXPONENT, then mapped onto min..max - a plain Random Value(min, max)
    # cannot express speed_random_exponent, and real files use 0.5 and 0.1.
    spd_u = _nd(ng, "FunctionNodeRandomValue", (-1060, -160), "roll 0..1",
                role="INITIALIZER", data_type="FLOAT")
    _sv(spd_u, 0, 0.0)
    _sv(spd_u, 1, 1.0)
    _lk(ng, gi, I['ID'], spd_u, 2)
    _lk(ng, seed_i, 0, spd_u, 3)
    spd_pow = _nd(ng, "ShaderNodeMath", (-920, -160), "^ exponent",
                  role="INITIALIZER", operation="POWER")
    _lk(ng, spd_u, 0, spd_pow, 0)
    _lk(ng, gi, I['Speed Exponent'], spd_pow, 1)
    spd_span = _nd(ng, "ShaderNodeMath", (-1060, -300), "max - min",
                   role="INITIALIZER", operation="SUBTRACT")
    _lk(ng, gi, I['Speed Max'], spd_span, 0)
    _lk(ng, gi, I['Speed Min'], spd_span, 1)
    spd = _nd(ng, "ShaderNodeMath", (-780, -220), "min + t x span",
              role="INITIALIZER", operation="MULTIPLY_ADD")
    _lk(ng, spd_pow, 0, spd, 0)
    _lk(ng, spd_span, 0, spd, 1)
    _lk(ng, gi, I['Speed Min'], spd, 2)
    spd_s = _nd(ng, "ShaderNodeMath", (-600, -160), "x scale",
                role="INITIALIZER", operation="MULTIPLY")
    _lk(ng, spd, 0, spd_s, 0)
    _lk(ng, gi, I['Scale'], spd_s, 1)
    vrad = _nd(ng, "ShaderNodeVectorMath", (-600, -160),
               "direction x radial speed", role="INITIALIZER",
               operation="SCALE")
    _lk(ng, unit, 0, vrad, 0)
    _lk(ng, spd_s, 0, vrad, 3)

    # local-space speed, rotated into the control point's frame
    vloc = _nd(ng, "FunctionNodeRandomValue", (-1000, -380),
               "speed in local XYZ", role="INITIALIZER",
               data_type="FLOAT_VECTOR")
    _lk(ng, gi, I['Local Speed Min'], vloc, 0)
    _lk(ng, gi, I['Local Speed Max'], vloc, 1)
    _lk(ng, gi, I['ID'], vloc, 2)
    _lk(ng, seed_i, 0, vloc, 3)
    vloc_s = _nd(ng, "ShaderNodeVectorMath", (-800, -380), "x scale",
                 role="INITIALIZER", operation="SCALE")
    _lk(ng, vloc, 0, vloc_s, 0)
    _lk(ng, gi, I['Scale'], vloc_s, 3)
    vrot = _nd(ng, "ShaderNodeVectorRotate", (-600, -380),
               "into the CP's frame", role="INITIALIZER",
               rotation_type="EULER_XYZ")
    _lk(ng, vloc_s, 0, vrot, 0)
    _lk(ng, gi, I['CP Rotation'], vrot, 4)

    vel = _nd(ng, "ShaderNodeVectorMath", (-360, -260), "radial + local",
              role="INITIALIZER", operation="ADD")
    _lk(ng, vrad, 0, vel, 0)
    _lk(ng, vrot, 0, vel, 1)

    zero = _nd(ng, "ShaderNodeCombineXYZ", (-360, 420), "off = no offset",
               role="INITIALIZER")
    # NOTE: these two used to be GeometryNodeSwitch(VECTOR). In Blender 5.2 a
    # vector Switch here crashed the group-interface structure-type inference
    # (EXCEPTION_ACCESS_VIOLATION inside calc_structure_type_interface) the
    # moment anything referenced this group. Mix with a boolean factor is
    # exactly equivalent for an on/off choice and does not trip it.
    sw_o = _nd(ng, "ShaderNodeMix", (400, 180), "enabled?",
               role="INITIALIZER", data_type="VECTOR", factor_mode="UNIFORM")
    _lk(ng, gi, 0, sw_o, 0)
    _lk(ng, zero, 0, sw_o, 4)
    _lk(ng, offset, 0, sw_o, 5)
    sw_v = _nd(ng, "ShaderNodeMix", (400, -160), "enabled?",
               role="INITIALIZER", data_type="VECTOR", factor_mode="UNIFORM")
    _lk(ng, gi, 0, sw_v, 0)
    _lk(ng, zero, 0, sw_v, 4)
    _lk(ng, vel, 0, sw_v, 5)
    _lk(ng, sw_o, 1, go, 0)
    _lk(ng, sw_v, 1, go, 1)

    note(ng, "INITIALIZER  ·  Position Within Sphere Random", "INITIALIZER", """
Spawns the particle on a random direction from the control point, somewhere
between Distance Min and Distance Max, and gives it a starting velocity.

DISTANCE BIAS RESHAPES THE SPHERE. The random direction is multiplied by it
componentwise and then re-normalized, so only the component RATIO matters:
(1,1,1) is a sphere, (1,1,0) is a flat disc (ground effects), (1,1,2) leans
toward the poles. The radial speed follows the same biased direction, which
is what SFM does.

TWO SEPARATE VELOCITY SOURCES, and SFM really does add both:
  * Speed Min/Max      - speed ALONG the spawn direction, so particles fly
                         outward from the control point.
  * Local Speed Min/Max - an XYZ velocity in the CONTROL POINT'S OWN frame,
                         which is why it goes through a Vector Rotate: if the
                         empty is rotated, "up" means the empty's up.

Everything is multiplied by Scale, because distances and speeds arrive in
Hammer units and the scene is usually in metres.

The offset is returned RELATIVE to the control point. Whoever calls this adds
the control point's position - that is what lets Movement Lock to Control
Point work.
""", [rdir, bias, unit, dist, dist_s, offset, spd_u, spd_pow, spd_span, spd,
      spd_s, vrad, vloc, vloc_s, vrot, vel, zero, sw_o, sw_v, seed_n, seed_i])
    out["sphere"] = ng

    # ── Position Modify Offset Random ────────────────────────────────────
    #  THE GLOBAL SPAWN NUDGE - the most-used operator the importer used to
    #  drop. Each component rolls independently between Offset Min and Offset
    #  Max; equal Min and Max is therefore a FIXED offset (lift the flash off
    #  the ground), a symmetric range is scatter. ADDS onto whatever the
    #  sphere initializer produced, which is how SFM stacks them.
    ng = _group("SP · INITIALIZER · Position Modify Offset Random",
                "GeometryNodeTree")
    _sock(ng, "Offset", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Offset Min", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Offset Max", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Local Space", "INPUT", "NodeSocketBool", False)
    _sock(ng, "CP Rotation", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Scale", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-1200, 0), (900, 0))
    I = _gin(ng)

    seed_n = _nd(ng, "ShaderNodeMath", (-1000, -300), "salt the seed",
                 role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I["Seed"], seed_n, 0)
    _sv(seed_n, 1, 88.0)
    seed_i = _nd(ng, "FunctionNodeFloatToInt", (-820, -300),
                 role="INITIALIZER")
    _lk(ng, seed_n, 0, seed_i, 0)

    #  FLOAT_VECTOR Random Value rolls each component on its own between the
    #  min and max vectors - exactly Source's per-component draw.
    roll_v = _nd(ng, "FunctionNodeRandomValue", (-820, 120),
                 "offset, per component", role="INITIALIZER",
                 data_type="FLOAT_VECTOR")
    _lk(ng, gi, I["Offset Min"], roll_v, 0)
    _lk(ng, gi, I["Offset Max"], roll_v, 1)
    _lk(ng, gi, I["ID"], roll_v, 2)
    _lk(ng, seed_i, 0, roll_v, 3)
    scaled = _nd(ng, "ShaderNodeVectorMath", (-620, 120), "x scale",
                 role="INITIALIZER", operation="SCALE")
    _lk(ng, roll_v, 0, scaled, 0)
    _lk(ng, gi, I["Scale"], scaled, 3)

    #  "offset in local space 0/1" turns the offset with the control point.
    local = _nd(ng, "ShaderNodeVectorRotate", (-440, 0),
                "into the CP's frame", role="INITIALIZER",
                rotation_type="EULER_XYZ")
    _lk(ng, scaled, 0, local, 0)
    _lk(ng, gi, I["CP Rotation"], local, 4)
    #  Mix with a boolean factor, NOT a vector GeometryNodeSwitch - see the
    #  sphere group note: a vector Switch here crashed Blender 5.2's
    #  structure-type inference the moment anything referenced this group.
    pick = _nd(ng, "ShaderNodeMix", (-260, 60), "local space?",
               role="INITIALIZER", data_type="VECTOR", factor_mode="UNIFORM")
    _lk(ng, gi, I["Local Space"], pick, 0)
    _lk(ng, scaled, 0, pick, 4)
    _lk(ng, local, 0, pick, 5)

    zero_o = _nd(ng, "ShaderNodeCombineXYZ", (-260, -180),
                 "off = no offset", role="INITIALIZER")
    sw_off = _nd(ng, "ShaderNodeMix", (300, 0), "enabled?",
                 role="INITIALIZER", data_type="VECTOR",
                 factor_mode="UNIFORM")
    _lk(ng, gi, 0, sw_off, 0)
    _lk(ng, zero_o, 0, sw_off, 4)
    _lk(ng, pick, 1, sw_off, 5)
    _lk(ng, sw_off, 1, go, 0)

    note(ng, "INITIALIZER  ·  Position Modify Offset Random", "INITIALIZER",
         """
A random nudge on the SPAWN POSITION, rolled once at birth:

    offset.x = random(Min.x .. Max.x)     and the same for y and z,
                                          each component independent

EQUAL MIN AND MAX IS A FIXED OFFSET - that is the commonest authoring in real
files: (0,0,25) on both lifts a shockwave 25 units off its control point.
A symmetric range like (-3,-3,0)..(3,3,1) scatters the spawns instead.

LOCAL SPACE rotates the offset into the control point's frame, so "up" means
the empty's up. Off (the default), the offset is world XYZ, which is why the
user-facing name for this operator is the GLOBAL position offset.

Multiplied by Scale like every other distance, added on top of Position
Within Sphere Random's placement - SFM runs both, in that order.

The salt (88) keeps this roll independent from the sphere's, or the nudge
would always point at the same corner the sphere direction chose.
""", [seed_n, seed_i, roll_v, scaled, local, pick, zero_o, sw_off])
    out["offset"] = ng

    # ── Sequence Random ──────────────────────────────────────────────────
    ng = _group("SP · INITIALIZER · Sequence Random", "GeometryNodeTree")
    _sock(ng, "Sequence", "OUTPUT", "NodeSocketInt")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Sequence Min", "INPUT", "NodeSocketInt", 0, smin=0)
    _sock(ng, "Sequence Max", "INPUT", "NodeSocketInt", 0, smin=0)
    _sock(ng, "Sequence Count", "INPUT", "NodeSocketInt", 1)
    _sock(ng, "ID", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi, go = _io(ng, (-1000, 0), (760, 0))
    I = _gin(ng)
    last = _nd(ng, "ShaderNodeMath", (-800, -180), "count - 1",
               role="INITIALIZER", operation="SUBTRACT")
    _lk(ng, gi, I["Sequence Count"], last, 0)
    _sv(last, 1, 1.0)

    # sequence_min / sequence_max are REAL SFM fields, and a .pcf routinely
    # leaves both at 0 meaning "sequence 0 only". They are also authored
    # against the sheet the effect shipped with, so clamp to the sheet we
    # actually loaded rather than indexing off the end of the table.
    hi_asked = _nd(ng, "ShaderNodeMath", (-800, -20), "the wider end",
                   role="INITIALIZER", operation="MAXIMUM")
    _lk(ng, gi, I["Sequence Min"], hi_asked, 0)
    _lk(ng, gi, I["Sequence Max"], hi_asked, 1)
    hi = _nd(ng, "ShaderNodeMath", (-600, -100), "clamped to the sheet",
             role="INITIALIZER", operation="MINIMUM")
    _lk(ng, hi_asked, 0, hi, 0)
    _lk(ng, last, 0, hi, 1)
    lo_asked = _nd(ng, "ShaderNodeMath", (-800, 140), "the narrower end",
                   role="INITIALIZER", operation="MINIMUM")
    _lk(ng, gi, I["Sequence Min"], lo_asked, 0)
    _lk(ng, gi, I["Sequence Max"], lo_asked, 1)
    lo = _nd(ng, "ShaderNodeMath", (-600, 140), "never below zero",
             role="INITIALIZER", operation="MAXIMUM")
    _lk(ng, lo_asked, 0, lo, 0)
    _sv(lo, 1, 0.0)
    lo_i = _nd(ng, "FunctionNodeFloatToInt", (-420, 140), role="INITIALIZER")
    _lk(ng, lo, 0, lo_i, 0)
    hi_i = _nd(ng, "FunctionNodeFloatToInt", (-420, -100), role="INITIALIZER")
    _lk(ng, hi, 0, hi_i, 0)

    seed_n = _nd(ng, "ShaderNodeMath", (-800, -360), "salt the seed",
                 role="INITIALIZER", operation="ADD")
    _lk(ng, gi, I["Seed"], seed_n, 0)
    _sv(seed_n, 1, 77.0)
    seed_i = _nd(ng, "FunctionNodeFloatToInt", (-620, -360),
                 role="INITIALIZER")
    _lk(ng, seed_n, 0, seed_i, 0)
    rv = _nd(ng, "FunctionNodeRandomValue", (-200, 0), "which sequence",
             role="INITIALIZER", data_type="INT")
    _lk(ng, lo_i, 0, rv, 0)
    _lk(ng, hi_i, 0, rv, 1)
    _lk(ng, gi, I["ID"], rv, 2)
    _lk(ng, seed_i, 0, rv, 3)
    sw = _nd(ng, "GeometryNodeSwitch", (240, 0), "enabled?",
             role="INITIALIZER", input_type="INT")
    _lk(ng, gi, I["Enable"], sw, 0)
    _sv(sw, 1, 0)
    _lk(ng, rv, 0, sw, 2)
    _lk(ng, sw, 0, go, 0)
    note(ng, "INITIALIZER  ·  Sequence Random", "INITIALIZER", """
Picks which SEQUENCE of the sprite sheet this particle plays, once, at birth.

    sequence = random( sequence_min , sequence_max )

Both are real .pcf fields. A file routinely leaves BOTH at 0, which means
"sequence 0 only" rather than "pick anything" - so honouring them is what
stops a two-sequence sheet flickering between sequences the author never
asked for.

RANGES ARE NOT ORDERED (constitutional law): min and max are sorted here
before use, and then CLAMPED to the sequence count of the sheet we actually
loaded. A .pcf is authored against the sheet it shipped with; point it at a
different .vtf and sequence_max can easily run off the end of the table.

A sheet can hold several sequences (arcs_a has two: tiles 0..33 and 34..69).
This only chooses the INDEX; the sequence's start tile, length and whether it
loops are looked up afterwards from the table read out of the .vtf.

Disabled -> everything plays sequence 0.
""", [last, hi_asked, hi, lo_asked, lo, lo_i, hi_i, seed_n, seed_i, rv, sw])
    out["sequence"] = ng
    return out


# =============================================================================
#  OPERATORS
# =============================================================================

def build_movement_lock_to_cp():
    ng = _group("SP · OPERATOR · Movement Lock to Control Point",
                "GeometryNodeTree")
    _sock(ng, "Position", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Enable", "INPUT", "NodeSocketBool", True)
    _sock(ng, "Local Offset", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Control Point", "INPUT", "NodeSocketVector", (0.0, 0.0, 0.0))
    _sock(ng, "Strength", "INPUT", "NodeSocketFloat", 1.0)
    gi, go = _io(ng, (-900, 0), (760, 0))

    locked = _nd(ng, "ShaderNodeVectorMath", (-500, 160),
                 "control point + offset", role="OPERATOR", operation="ADD")
    _lk(ng, gi, 2, locked, 0)
    _lk(ng, gi, 1, locked, 1)
    blend = _nd(ng, "ShaderNodeMix", (-260, 0), "how strongly it is locked",
                role="OPERATOR", data_type="VECTOR", factor_mode="UNIFORM")
    _lk(ng, gi, 3, blend, 0)
    _lk(ng, gi, 1, blend, 4)
    _lk(ng, locked, 0, blend, 5)
    sw = _nd(ng, "GeometryNodeSwitch", (300, 0), "enabled?", role="OPERATOR",
             input_type="VECTOR")
    _lk(ng, gi, 0, sw, 0)
    _lk(ng, gi, 1, sw, 1)
    _lk(ng, blend, 1, sw, 2)
    _lk(ng, sw, 0, go, 0)

    note(ng, "OPERATOR  ·  Movement Lock to Control Point", "OPERATOR", """
The particle KEEPS ITS RELATIVE OFFSET and rides the control point. It is NOT
"snap every particle onto the CP" - the offset chosen at birth is preserved,
the CP's movement is inherited on top of it.

    locked   ->  position = control point + offset      (follows the empty)
    unlocked ->  position = offset                      (stays put)

Strength blends between the two, which is what the operator envelope drives -
so a Movement Lock with a fade out will gradually release its particles.

WHAT "CONTROL POINT" MEANS HERE DEPENDS ON THE EMITTER, and this is the fix
for "particles are locked to the control point even with the lock switched
off":

  SIMULATION  it is the DISTANCE THE CP HAS MOVED SINCE THIS PARTICLE WAS
              BORN - the CP's birth position is written onto the point as an
              attribute on the frame it was still true. Locked means "come
              with me from here". Unlocked leaves the particle exactly where
              it was born, no matter where the empty wanders off to.
  STATELESS   it is the CP's position RIGHT NOW, because nothing remembers
              the past. Every particle follows the empty around whether the
              lock is on or not. That is a known limitation of that path,
              not a bug in this operator.
""", [locked, blend, sw])
    return ng


# =============================================================================
#  WHERE IS THE EYE?  -  shared by every renderer
# =============================================================================

def build_camera_eye(viewport=False):
    """The point every camera-facing thing turns towards, in the HOST'S frame.

     0  ACTIVE CAMERA   whatever scene.camera is, right now. Nothing to wire
                        up: drop a camera in and things turn to it, swap
                        cameras and they follow. This is what SFM does.
     1  CAMERA SOCKET   an explicit object, for when a scene has several
                        cameras and the effect must face one in particular.
     2  VIEWPORT        whatever you are actually looking through. Faces you
                        as you orbit, and falls back to the render camera when
                        rendering, because that is what the Viewport Transform
                        node returns outside a viewport.

    The cost of 2 is real: reading the viewport transform makes the tree
    depend on the view, so it re-evaluates every time you move the mouse in
    the 3D view. Fine for looking at one effect, expensive with thousands of
    particles. Hence 0 by default.

    ONE COPY, TWO RENDERERS. Sprites and ropes both need this and both need it
    to behave identically, so it lives in its own group rather than being
    written out twice."""
    ng = _group("SP · RENDERER · the eye"
                + (" · viewport" if viewport else ""), "GeometryNodeTree")
    _sock(ng, "Eye", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Camera", "INPUT", "NodeSocketObject")
    _sock(ng, "Camera Source", "INPUT", "NodeSocketInt", 0, smin=0, smax=2)
    gi, go = _io(ng, (-1700, 0), (400, 0))
    I = _gin(ng)

    active = _nd(ng, "GeometryNodeInputActiveCamera", (-1700, 460),
                 "scene.camera, live", role="RENDERER")
    use_socket = _nd(ng, "FunctionNodeCompare", (-1700, 300),
                     "source == 1 (explicit)", role="RENDERER",
                     data_type="INT", operation="EQUAL")
    _lk(ng, gi, I["Camera Source"], use_socket, 0)
    _sv(use_socket, 1, 1)
    which = _nd(ng, "GeometryNodeSwitch", (-1500, 400), "which camera object",
                role="RENDERER", input_type="OBJECT")
    _lk(ng, use_socket, 0, which, 0)
    _lk(ng, active, 0, which, 1)
    _lk(ng, gi, I["Camera"], which, 2)

    cam = _nd(ng, "GeometryNodeObjectInfo", (-1300, 400), "the camera",
              role="RENDERER", transform_space="RELATIVE")
    _lk(ng, which, 0, cam, 0)

    # THE VIEWPORT BRANCH ONLY EXISTS WHEN ASKED FOR - see the docstring:
    # the Viewport Transform node makes any tree containing it re-evaluate
    # on every view change, selected or not, so the default group must not
    # contain one at all.
    if viewport:
        # THE VIEWPORT EYE, CONVERTED INTO THE HOST'S SPACE. Object Info is
        # read RELATIVE - in the modified object's frame, which is the frame
        # the particles live in. The viewport matrix is WORLD space, so it
        # has to be pushed through the host's inverse transform or everything
        # faces a point offset by wherever the host object happens to sit.
        view = _nd(ng, "GeometryNodeViewportTransform", (-1700, 60),
                   "the viewport", role="RENDERER")
        eye_world = _nd(ng, "FunctionNodeInvertMatrix", (-1500, 60),
                        "view matrix -> camera to world", role="RENDERER")
        _lk(ng, view, 1, eye_world, 0)
        eye_split = _nd(ng, "FunctionNodeSeparateTransform", (-1320, 60),
                        "where the eye is", role="RENDERER")
        _lk(ng, eye_world, 0, eye_split, 0)
        host = _nd(ng, "GeometryNodeSelfObject", (-1700, -100), "this object",
                   role="RENDERER")
        host_info = _nd(ng, "GeometryNodeObjectInfo", (-1520, -100),
                        "its transform", role="RENDERER",
                        transform_space="ORIGINAL")
        _lk(ng, host, 0, host_info, 0)
        host_inv = _nd(ng, "FunctionNodeInvertMatrix", (-1320, -100),
                       "world -> this object", role="RENDERER")
        _lk(ng, host_info, 0, host_inv, 0)
        eye_local = _nd(ng, "FunctionNodeTransformPoint", (-1120, -20),
                        "eye, in the particles' frame", role="RENDERER")
        _lk(ng, eye_split, 0, eye_local, 0)
        _lk(ng, host_inv, 0, eye_local, 1)

        use_view = _nd(ng, "FunctionNodeCompare", (-1120, 220),
                       "source == 2 (viewport)", role="RENDERER",
                       data_type="INT", operation="EQUAL")
        _lk(ng, gi, I["Camera Source"], use_view, 0)
        _sv(use_view, 1, 2)
        eye = _nd(ng, "GeometryNodeSwitch", (-920, 340), "the eye to face",
                  role="RENDERER", input_type="VECTOR")
        _lk(ng, use_view, 0, eye, 0)
        _lk(ng, cam, 1, eye, 1)
        _lk(ng, eye_local, 0, eye, 2)
        eye_pos, eye_idx = eye, 0
        vp_nodes = [view, eye_world, eye_split, host, host_info, host_inv,
                    eye_local, use_view, eye]
    else:
        eye_pos, eye_idx = cam, 1          # Object Info's Location output
        vp_nodes = []

    #  🔴 NO CAMERA MUST NOT MEAN "FACE THE ORIGIN". With no camera in the
    #  scene, Object Info reads (0,0,0) and every card aimed at a point
    #  INSIDE the effect - per-particle orientations all disagreeing, the
    #  worst case for both the look and the shader. The honest stand-in is a
    #  camera infinitely far up +Z: every card agrees on one orientation
    #  (a top-down billboard), which is also the cheapest thing to draw.
    #  A real camera parked exactly on the origin hits the same switch, and
    #  loses nothing - it was degenerate before this too.
    eye_len = _nd(ng, "ShaderNodeVectorMath", (-740, 200), "is there one?",
                  role="RENDERER", operation="LENGTH")
    _lk(ng, eye_pos, eye_idx, eye_len, 0)
    no_cam = _nd(ng, "FunctionNodeCompare", (-560, 200), "no camera at all",
                 role="RENDERER", data_type="FLOAT", operation="LESS_THAN")
    _lk(ng, eye_len, 1, no_cam, 0)
    _sv(no_cam, 1, EPS)
    far_up = _nd(ng, "ShaderNodeCombineXYZ", (-560, 60),
                 "infinitely far up +Z", role="RENDERER")
    _sv(far_up, 2, 100000.0)
    eye_out = _nd(ng, "GeometryNodeSwitch", (-360, 200), "the eye, always",
                  role="RENDERER", input_type="VECTOR")
    _lk(ng, no_cam, 0, eye_out, 0)
    _lk(ng, eye_pos, eye_idx, eye_out, 1)
    _lk(ng, far_up, 0, eye_out, 2)
    _lk(ng, eye_out, 0, go, 0)

    note(ng, "RENDERER  ·  where the eye is", "RENDERER", """
Camera Source - NOT an SFM field; SFM has one camera and never has to ask.

  0  ACTIVE CAMERA   scene.camera, read live. Drop a camera into the scene
                     and things turn to it, swap cameras and they follow.
                     Default, and what SFM does.
  1  CAMERA SOCKET   an explicit object, for a scene with several cameras.
  2  VIEWPORT        whatever you are looking through right now. Faces you as
                     you orbit, and falls back to the render camera when
                     rendering, because that is what Viewport Transform
                     returns outside a viewport.

The cost of 2 is real and worth knowing: the Viewport Transform node makes
the whole tree view-dependent BY EXISTING - re-evaluated on every orbit even
with mode 0 or 1 selected. That is why mode 2 is a build-time opt-in
(preferences: Viewport-Facing Sprites): this group is built WITHOUT the node
unless asked, and then mode 2 simply behaves as mode 0.

Mode 2 also has to push the viewport eye through the HOST OBJECT'S INVERSE
TRANSFORM. Object Info here is read RELATIVE - in the modified object's frame,
which is the frame the particles live in - while the viewport matrix is world
space. Skip that conversion and everything aims at a point offset by wherever
the host object sits.

NO CAMERA -> A CAMERA INFINITELY FAR UP +Z. With none in the scene the eye
read (0,0,0) - every card aiming at a point inside the effect, each with its
own orientation. The far-up stand-in makes every card agree on one top-down
orientation, which is also the cheapest to draw, and the moment a real camera
appears the live read takes over again.
""", [active, use_socket, which, cam] + vp_nodes
         + [eye_len, no_cam, far_up, eye_out])
    return ng


# =============================================================================
#  RENDERER
# =============================================================================

def build_render_animated_sprites(mat, eye_group):
    # THE MATERIAL IS BAKED INTO THIS GROUP, so the name has to carry it.
    # Under one shared name, building a second system from a different texture
    # CLEARS this group and refills it with the new material - and clearing an
    # interface silently drops every link the first system had made into it.
    ng = _group(f"SP · RENDERER · render_animated_sprites · {mat.name}",
                "GeometryNodeTree")
    _sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    _sock(ng, "Points", "INPUT", "NodeSocketGeometry")
    _sock(ng, "Camera", "INPUT", "NodeSocketObject")
    _sock(ng, "Camera Source", "INPUT", "NodeSocketInt", 0, smin=0, smax=2)
    _sock(ng, "Orientation Type", "INPUT", "NodeSocketInt", 0)
    _sock(ng, "Orientation CP Rotation", "INPUT", "NodeSocketVector",
          (0.0, 0.0, 0.0))
    #  NOT SFM - the low-GPU stand-in. See the proxy branch below.
    _sock(ng, "Proxy View", "INPUT", "NodeSocketBool", False)
    gi, go = _io(ng, (-1700, 0), (1300, 0))
    I = _gin(ng)

    # ---- READ THE BAKED ATTRIBUTES, never take live fields ----------------
    # These are stored on the POINT domain BEFORE dead particles are deleted,
    # so they travel with each surviving point. Taking them as group inputs
    # instead meant they were index-dependent fields evaluated AFTER
    # DeleteGeometry had re-indexed the points - so the instant any particle
    # died, every remaining sprite picked up a neighbour's radius and roll.
    # That is the "all the sprites suddenly recalculate" bug.
    a_rad = _nd(ng, "GeometryNodeInputNamedAttribute", (-1300, -760),
                "sprite_radius (baked)", role="RENDERER", data_type="FLOAT")
    _sv(a_rad, 0, "sprite_radius")
    a_roll = _nd(ng, "GeometryNodeInputNamedAttribute", (-1300, -900),
                 "sprite_roll (baked)", role="RENDERER", data_type="FLOAT")
    _sv(a_roll, 0, "sprite_roll")
    a_flip = _nd(ng, "GeometryNodeInputNamedAttribute", (-1300, -1040),
                 "sprite_flip (baked)", role="RENDERER", data_type="FLOAT")
    _sv(a_flip, 0, "sprite_flip")

    grid = _nd(ng, "GeometryNodeMeshGrid", (-1100, -560), "the sprite card",
               role="RENDERER")
    _sv(grid, 0, 1.0)
    _sv(grid, 1, 1.0)
    _sv(grid, 2, 2)
    _sv(grid, 3, 2)
    uvstore = _nd(ng, "GeometryNodeStoreNamedAttribute", (-900, -560),
                  'store its UVs as "UVMap"', role="RENDERER",
                  data_type="FLOAT2", domain="CORNER")
    _sv(uvstore, 2, "UVMap")
    _lk(ng, grid, 0, uvstore, 0)
    _lk(ng, grid, 1, uvstore, 3)
    setmat = _nd(ng, "GeometryNodeSetMaterial", (-700, -560),
                 "material HERE, before instancing", role="RENDERER")
    _lk(ng, uvstore, 0, setmat, 0)
    try:
        setmat.inputs[2].default_value = mat
    except Exception as exc:
        print(f"[HT_RAS]  set material: {exc}")

    # ---- where the eye is -------------------------------------------------
    # BUILT ONCE AND PASSED IN, never built here. _group() CLEARS an existing
    # group before refilling it, so a second builder calling build_camera_eye()
    # would wipe this group's interface and silently drop the links the first
    # renderer had already made into it.
    eye = _nd(ng, "GeometryNodeGroup", (-1300, 400), "where the camera is",
              role="RENDERER")
    eye.node_tree = eye_group
    _lk(ng, gi, I["Camera"], eye, 0)
    _lk(ng, gi, I["Camera Source"], eye, 1)

    # ---- orientation ------------------------------------------------------
    pos = _nd(ng, "GeometryNodeInputPosition", (-1100, 120), role="RENDERER")
    to_cam = _nd(ng, "ShaderNodeVectorMath", (-720, 220),
                 "particle -> eye", role="RENDERER", operation="SUBTRACT")
    _lk(ng, eye, 0, to_cam, 0)
    _lk(ng, pos, 0, to_cam, 1)

    # type 0: full billboard - Z points at the camera
    billboard = _nd(ng, "FunctionNodeAlignRotationToVector", (-660, 340),
                    "0 · face the camera", role="RENDERER",
                    axis="Z", pivot_axis="AUTO")
    _lk(ng, to_cam, 0, billboard, 2)
    # type 1: ERECT. 🔴 Align-to-vector CANNOT do this one: the card's normal
    # starts at world +Z, and "rotate about pivot Z" never moves +Z anywhere -
    # so the old align node quietly left every type-1 card LYING FLAT. The rod
    # is built directly instead: pitch the card upright (90° about X - its
    # in-plane up becomes world Z), then yaw about Z toward the camera.
    cam_xy = _nd(ng, "ShaderNodeSeparateXYZ", (-880, 140),
                 "camera direction, flattened", role="RENDERER")
    _lk(ng, to_cam, 0, cam_xy, 0)
    yaw0 = _nd(ng, "ShaderNodeMath", (-720, 140), "atan2(y, x)",
               role="RENDERER", operation="ARCTAN2")
    _lk(ng, cam_xy, 1, yaw0, 0)
    _lk(ng, cam_xy, 0, yaw0, 1)
    yaw = _nd(ng, "ShaderNodeMath", (-560, 140), "+ 90°  (normal was -Y)",
              role="RENDERER", operation="ADD")
    _lk(ng, yaw0, 0, yaw, 0)
    _sv(yaw, 1, 1.5707963705062866)
    erect_e = _nd(ng, "ShaderNodeCombineXYZ", (-560, 20),
                  "pitch 90°, yaw to camera", role="RENDERER")
    _sv(erect_e, 0, 1.5707963705062866)
    _lk(ng, yaw, 0, erect_e, 2)
    upright = _nd(ng, "FunctionNodeEulerToRotation", (-400, 140),
                  "1 · ERECT - the rod", role="RENDERER")
    _lk(ng, erect_e, 0, upright, 0)
    # type 2: locked to the control point's own rotation
    cp_rot = _nd(ng, "FunctionNodeEulerToRotation", (-660, -60),
                 "2 · locked to the CP", role="RENDERER")
    _lk(ng, gi, I["Orientation CP Rotation"], cp_rot, 0)

    is1 = _nd(ng, "FunctionNodeCompare", (-880, -220), "type == 1",
              role="RENDERER", data_type="INT", operation="EQUAL")
    _lk(ng, gi, I["Orientation Type"], is1, 0)
    _sv(is1, 1, 1)
    is2 = _nd(ng, "FunctionNodeCompare", (-880, -380), "type == 2",
              role="RENDERER", data_type="INT", operation="EQUAL")
    _lk(ng, gi, I["Orientation Type"], is2, 0)
    _sv(is2, 1, 2)
    pick1 = _nd(ng, "GeometryNodeSwitch", (-420, 240), "billboard or upright",
                role="RENDERER", input_type="ROTATION")
    _lk(ng, is1, 0, pick1, 0)
    _lk(ng, billboard, 0, pick1, 1)
    _lk(ng, upright, 0, pick1, 2)
    pick2 = _nd(ng, "GeometryNodeSwitch", (-220, 140), "...or CP locked",
                role="RENDERER", input_type="ROTATION")
    _lk(ng, is2, 0, pick2, 0)
    _lk(ng, pick1, 0, pick2, 1)
    _lk(ng, cp_rot, 0, pick2, 2)

    # roll happens around the card's OWN Z, i.e. the view axis - so the card
    # keeps facing the camera and merely spins in place.
    #
    # ⚠️ EXCEPT AT ORIENTATION TYPE 1, WHICH IS ERECT ON PURPOSE. Type 1 is a
    # rod through the card's middle: it yaws to face you and stays STRAIGHT -
    # that is what fire is authored with, so licks of flame never lie on
    # their side. Rolling it about its own normal would tip the upright card
    # over, which is exactly the "fire particles rotate randomly" bug. So the
    # roll angle is switched to zero whenever type == 1.
    roll_amt = _nd(ng, "GeometryNodeSwitch", (-420, -180),
                   "type 1 is ERECT - no roll", role="RENDERER",
                   input_type="FLOAT")
    _lk(ng, is1, 0, roll_amt, 0)
    _lk(ng, a_roll, 0, roll_amt, 1)          # any other type: the real roll
    _sv(roll_amt, 2, 0.0)                    # type 1: none
    roll = _nd(ng, "FunctionNodeAxisAngleToRotation", (-220, -180),
               "roll about the view axis", role="RENDERER")
    _sv(roll, 0, (0.0, 0.0, 1.0))
    _lk(ng, roll_amt, 0, roll, 1)
    spun = _nd(ng, "FunctionNodeRotateRotation", (20, 40), "orient, then roll",
               role="RENDERER", rotation_space="LOCAL")
    _lk(ng, pick2, 0, spun, 0)
    _lk(ng, roll, 0, spun, 1)

    # ---- size: radius is a HALF extent ------------------------------------
    diam = _nd(ng, "ShaderNodeMath", (20, -260), "radius x 2  (half extent)",
               role="RENDERER", operation="MULTIPLY")
    _lk(ng, a_rad, 0, diam, 0)
    _sv(diam, 1, 2.0)
    # X carries the MIRROR. Rotation Yaw Flip Random hands over +1 or -1, and
    # a negative X scale is what yawing a flat card 180 degrees actually looks
    # like: the same sprite, left-right reversed.
    flip_x = _nd(ng, "ShaderNodeMath", (220, -420), "x sprite_flip",
                 role="RENDERER", operation="MULTIPLY")
    _lk(ng, diam, 0, flip_x, 0)
    _lk(ng, a_flip, 0, flip_x, 1)
    scale_v = _nd(ng, "ShaderNodeCombineXYZ", (420, -260),
                  "uniform scale, X mirrored", role="RENDERER")
    _lk(ng, flip_x, 0, scale_v, 0)
    _lk(ng, diam, 0, scale_v, 1)
    _lk(ng, diam, 0, scale_v, 2)

    proxy_card = _nd(ng, "GeometryNodeTransform", (-700, -760),
                     "the stand-in card (unit)", role="RENDERER")
    _lk(ng, uvstore, 0, proxy_card, 0)
    _sv(proxy_card, 3, (1.0, 1.0, 1.0))
    card_pick = _nd(ng, "GeometryNodeSwitch", (-500, -640),
                    "the real card, or the stand-in", role="RENDERER",
                    input_type="GEOMETRY")
    _lk(ng, gi, I["Proxy View"], card_pick, 0)
    _lk(ng, setmat, 0, card_pick, 1)
    _lk(ng, proxy_card, 0, card_pick, 2)

    inst = _nd(ng, "GeometryNodeInstanceOnPoints", (520, 0),
               "one card per particle", role="RENDERER")
    _lk(ng, gi, I["Points"], inst, 0)
    _lk(ng, card_pick, 0, inst, 2)
    _lk(ng, spun, 0, inst, 5)
    _lk(ng, scale_v, 0, inst, 6)
    _lk(ng, inst, 0, go, 0)

    note(ng, "RENDERER  ·  render_animated_sprites", "RENDERER", """
CAMERA SOURCE - what the sprites actually turn towards. NOT an SFM field;
SFM has exactly one camera and no question to ask.

  0  ACTIVE CAMERA   scene.camera, read live. Nothing to wire up: drop a
                     camera into the scene and the sprites turn to it, swap
                     cameras and they follow. This is the default and it is
                     what SFM does.
  1  CAMERA SOCKET   an explicit object, for a scene with several cameras
                     where this effect must face one in particular.
  2  VIEWPORT        whatever you are looking through right now. The sprites
                     face you as you orbit, and fall back to the render camera
                     when rendering, because that is what Viewport Transform
                     returns outside a viewport.

The cost of 2 is real and worth knowing: the Viewport Transform node makes a
tree view-dependent BY EXISTING - re-evaluated on every orbit even with mode
0 or 1 selected, which the user measured as half the viewport lag on a heavy
effect. Mode 2 is therefore a build-time opt-in (preferences: Viewport-Facing
Sprites); systems built without it treat 2 as the active camera and pay
nothing.

Mode 2 also has to push the viewport's eye through the HOST OBJECT'S INVERSE
TRANSFORM. Object Info here is read RELATIVE - in the modified object's frame,
which is the frame the particles live in - while the viewport matrix is world
space. Skip that conversion and the sprites aim at a point offset by wherever
the host object happens to sit.

ORIENTATION TYPE, straight from SFM:
  0  Screen-aligned billboard. The card's Z is aimed at the camera, so it
     faces you from any angle. Standard for smoke, explosions.
  1  ERECT. A rod through the card's middle: it yaws to face you as you
     orbit, stays dead straight, and is nearly invisible from above. Fire is
     authored with this so flames stand up - and it takes NO random roll,
     because rolling an upright card about its normal tips it over.
  2  Locked to a control point's rotation. Needed if the effect must turn
     with SFM's animation-set translation wheels.

ROLL IS NOT ORIENTATION. Rotation Random feeds Roll, and roll is applied about
the card's OWN Z - which after orientation IS the view axis. So the sprite
spins in place and NEVER stops facing the camera. Rolling in world space
instead would tip the card away from the view, which is the classic mistake.
Type 1 is the exception: its roll is forced to zero, see above.

Radius is a HALF extent, so a card is radius x 2 across.

THE THREE RULES:
  1. Mesh Grid's UV is an ANONYMOUS socket - store it as "UVMap" or the shader
     has no UVs and every sprite is invisible.
  2. Set Material goes on the SOURCE card, before Instance on Points.
  3. Per-particle values are stored on the POINT domain and read in the shader
     with attribute_type='INSTANCER'.

RADIUS AND ROLL ARE READ FROM BAKED ATTRIBUTES, not passed in as fields.
DeleteGeometry RE-INDEXES the points it keeps. Anything derived from the point
INDEX and evaluated after that delete silently shifts onto a neighbour - so the
moment the first particle died, every sprite took someone else's size and
rotation, and the whole effect appeared to recalculate itself. Baked attributes
travel with their point through the delete; live index fields do not.
""", [grid, uvstore, setmat, eye, pos, to_cam, billboard, upright, cp_rot,
      is1, is2, pick1, pick2, roll, spun, diam, scale_v, inst, a_rad, a_roll,
      a_flip, flip_x])

    #  PROXY COLOUR - appended at the END so no existing node's birth-order
    #  name shifts (the hand-layout tables match by name first; see RULES).
    #  The stand-in used to carry NO material and every system's proxies were
    #  the same white; a flat per-system colour keeps the cost at zero and
    #  makes a scene of proxied effects read like Solid shading's Random
    #  mode - you can tell whose particles are whose at a glance.
    psm = _nd(ng, "GeometryNodeSetMaterial", (-560, -900),
              "the stand-in's own colour", role="RENDERER")
    try:
        psm.inputs[2].default_value = proxy_material(ng.name)
    except Exception as exc:
        print(f"[HT_RAS]  proxy material: {exc}")
    for l in list(ng.links):
        if l.from_node.name == proxy_card.name \
                and l.to_node.name == card_pick.name:
            ng.links.remove(l)
    _lk(ng, proxy_card, 0, psm, 0)
    _lk(ng, psm, 0, card_pick, 2)

    #  PROXY SIZE IS CLAMPED, NOT PROPORTIONAL - appended at the END, same
    #  name-stability reason as above. No constant shrink survives contact
    #  with glow sprites: their radii are authored in the THOUSANDS of HU
    #  (soft falloff over a huge card), so 1/4, 1/10 and 1/40 all produced
    #  wall-sized opaque squares. The stand-in is 1/16th of the sprite,
    #  CAPPED AT 8 HU - small sprites keep a proportional marker, huge ones
    #  become a hand-sized one, and nothing can obscure the effect. Wired as
    #  a Switch on the INSTANCE scale so the real card's sizing is untouched.
    psize = _nd(ng, "ShaderNodeMath", (240, -560), "1/16th of the sprite",
                role="RENDERER", operation="MULTIPLY")
    _lk(ng, diam, 0, psize, 0)
    _sv(psize, 1, 1.0 / 16.0)
    pcap = _nd(ng, "ShaderNodeMath", (400, -560), "capped at 8 HU",
               role="RENDERER", operation="MINIMUM")
    _lk(ng, psize, 0, pcap, 0)
    _sv(pcap, 1, 8.0)
    pvec = _nd(ng, "ShaderNodeCombineXYZ", (560, -560),
               "uniform stand-in scale", role="RENDERER")
    _lk(ng, pcap, 0, pvec, 0)
    _lk(ng, pcap, 0, pvec, 1)
    _lk(ng, pcap, 0, pvec, 2)
    scale_pick = _nd(ng, "GeometryNodeSwitch", (700, -420),
                     "the real scale, or the stand-in's", role="RENDERER",
                     input_type="VECTOR")
    _lk(ng, gi, I["Proxy View"], scale_pick, 0)
    _lk(ng, scale_v, 0, scale_pick, 1)
    _lk(ng, pvec, 0, scale_pick, 2)
    #  links.new onto the occupied Scale input replaces the old link in one
    #  operation (see layout.split_group_inputs on why that matters).
    _lk(ng, scale_pick, 0, inst, 6)
    return ng
