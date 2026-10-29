# =============================================================================
#  tools/ras_spec.py  -  the SFM operator catalogue
# =============================================================================
#
#  ONE TABLE, THREE JOBS
#  ---------------------
#   1. it declares the modifier's sockets - name, type, default, range
#   2. it records the EXACT `.pcf` attribute name behind every socket, so the
#      importer is a lookup rather than a pile of if-statements
#   3. it says how a SECOND instance of the same operator combines with the
#      first, because an operator may legally appear more than once
#
#  EVERY NAME AND RANGE IN HERE WAS READ OUT OF REAL .pcf FILES - 97 TF2 packs,
#  3574 system definitions - not reconstructed from memory. Where the survey
#  disagreed with what we had built, the survey won.
#
#  SOCKET NAMING CONVENTION
#  ------------------------
#      "Readable name [SFM: exact_pcf_attribute]"
#      "Readable name #2 [SFM: exact_pcf_attribute]"     second instance
#
#  Both halves matter. The readable half is what a human reads in the modifier;
#  the bracketed half is what the importer matches on, so wiring a .pcf up is
#  "find the socket whose SFM tag is this attribute" and nothing more.
#
#  UNITS - SFM'S OWN, NOT BLENDER'S
#  --------------------------------
#      deg    degrees. rotation_offset_min/max really do run -360..360.
#      byte   0..255. alpha_min/max and color1/color2 are byte values, and
#             effects DO push alpha past 255 for overbright.
#      hu     Hammer units. 1 Blender Unit = 1 Hammer unit, so nothing is
#             converted - the tag records what the number IS.
#      sec    seconds.
#      factor a plain 0..1 multiplier.
#      count  an integer count or index.
#
#  Conversion to Blender's internal convention (degrees -> radians, byte ->
#  0..1) happens INSIDE the node group that consumes it, never in the socket.
#  The number you type is the number SFM shows you.
# =============================================================================


# =============================================================================
#  THE COMMON OPERATOR ENVELOPE
# =============================================================================
#  Present on EVERY operator in the survey without exception - all 42183 of
#  them. That is what makes stacking useful rather than merely legal: two
#  Velocity Noises with different fade windows are two different gusts, and the
#  envelope is how you offset one against the other.

ENVELOPE = (
    ("Start Fade In", "operator start fadein", "NodeSocketFloat", 0.0,
     None, None, "sec"),
    ("End Fade In", "operator end fadein", "NodeSocketFloat", 0.0,
     None, None, "sec"),
    ("Start Fade Out", "operator start fadeout", "NodeSocketFloat", 0.0,
     None, None, "sec"),
    ("End Fade Out", "operator end fadeout", "NodeSocketFloat", 0.0,
     None, None, "sec"),
    ("Fade Oscillate", "operator fade oscillate", "NodeSocketFloat", 0.0,
     0.0, None, "sec"),
)


# =============================================================================
#  HOW A SECOND INSTANCE COMBINES WITH THE FIRST
# =============================================================================
#
#  ADD        the contributions sum. Velocity and position initializers work
#             this way - Velocity Random already ADDS to the sphere's outward
#             velocity, which is how SFM stacks them.
#  LAST_WINS  each instance WRITES the field, so the last one in the list is
#             the value the particle ends up with. Lifetime, radius, alpha,
#             colour, roll and sequence are all plain setters.
#  CHAIN      each instance takes the previous instance's result as its input
#             and modifies it. The alpha fades already work like this, which is
#             why a particle can fade in and out.
#
#  ⚠️ These are the rules for the operators below. They are NOT universal:
#  Remap-family operators read one field and write another, and stacking those
#  correctly needs the read/write pair modelled, which is not done yet.

ADD, LAST_WINS, CHAIN = "ADD", "LAST_WINS", "CHAIN"


# =============================================================================
#  OPERATORS WE DO NOT BUILD BECAUSE THEY ALREADY HAPPEN
# =============================================================================
#  Not the same thing as "not built". `Lifespan Decay` has NO fields at all
#  beyond the envelope in any of its 1127 uses - it is the operator that kills
#  a particle when its age passes its lifetime, and this build does that
#  unconditionally inside the simulation zone.
#
#  Listed so the importer can say "already handled" instead of reporting 1127
#  systems as having lost something. A warning you have to learn to ignore is
#  worse than no warning at all.

ALREADY_HANDLED = {
    "Lifespan Decay": "particles are deleted at end of life by the emitter",
}


# =============================================================================
#  WHICH FIELDS NAME A CONTROL POINT
# =============================================================================
#  A control point socket cannot carry a fixed maximum in this table, because
#  the maximum belongs to the SYSTEM, not to the operator: an effect with two
#  empties tops out at 1 and one with forty-one tops out at 40. These were
#  pinned at 3, which quietly made every reference above CP3 unselectable - and
#  8% of TF2 asks for more than four control points.
#
#  So the table says None and `build_system` clamps each one to the count it is
#  actually building for. This predicate is how it recognises them.
#
#  The exclusions mirror tools/pcf.py, which is the authority: plenty of
#  attributes contain the words "control point" without being an index -
#  "...Parent", "...Location", "control point movement distance tolerance",
#  "scale emission to used control points" (a flag), and "# of control points
#  to set" (a SPAN LENGTH that pairs with "First control point to set").

_CP_NOT_AN_INDEX = ("parent", "location", "tolerance", "distribute",
                    "scale emission", "field", "offset for",
                    "of control points")


def is_control_point_field(sfm):
    """True if this .pcf attribute holds a control point NUMBER."""
    n = str(sfm).lower().replace("_", " ")
    if "control point" not in n:
        return False
    return not any(bad in n for bad in _CP_NOT_AN_INDEX)


# =============================================================================
#  THE CATALOGUE
# =============================================================================
#  fields: (display, sfm attribute, socket type, default, min, max, unit)
#  ignored: attributes seen in real files that this build does NOT honour yet.
#           Kept so the importer can WARN about what it is dropping instead of
#           silently pretending the effect came through intact.

OPERATORS = {

    # ── EMITTER ──────────────────────────────────────────────────────────
    "emit_continuously": dict(
        section="EMITTER", category="EMITTER", stack=ADD, envelope=True,
        seen=2244,
        fields=(
            ("Emission Rate", "emission_rate", "NodeSocketFloat", 20.0,
             0.0, None, "count"),
            ("Emission Start Time", "emission_start_time", "NodeSocketFloat",
             0.0, None, None, "sec"),
            ("Emission Duration", "emission_duration", "NodeSocketFloat",
             0.0, None, None, "sec"),
        ),
        ignored=("scale emission to used control points",
                 "use parent particles for emission scaling"),
        note="emission_duration 0 means FOREVER; real files also use -1.",
    ),

    "emit_instantaneously": dict(
        section="EMITTER", category="EMITTER", stack=ADD, envelope=True,
        seen=1335,
        fields=(
            ("Emission Start Time", "emission_start_time", "NodeSocketFloat",
             0.0, None, None, "sec"),
            ("Num To Emit", "num_to_emit", "NodeSocketFloat", 100.0,
             0.0, None, "count"),
            # -1 means "not used" - emit exactly num_to_emit.
            ("Num To Emit Min", "num_to_emit_minimum", "NodeSocketFloat",
             -1.0, None, None, "count"),
        ),
        ignored=("maximum emission per frame",
                 "emission count scale control point",
                 "emission count scale control point field"),
        note="fires on the single frame where the clock CROSSES the start "
             "time. Goes through the same max_particles cap as continuous "
             "emission.",
    ),

    # ── INITIALIZERS ─────────────────────────────────────────────────────
    "Velocity Noise": dict(
        section="INITIALIZER", category="INITIALIZER", stack=ADD,
        envelope=True, seen=361,
        fields=(
            ("Spatial Scale", "Spatial Noise Coordinate Scale",
             "NodeSocketFloat", 0.0, None, None, "factor"),
            ("Spatial Offset", "Spatial Coordinate Offset",
             "NodeSocketVector", (0.0, 0.0, 0.0), None, None, "factor"),
            ("Time Scale", "Time Noise Coordinate Scale", "NodeSocketFloat",
             0.0, None, None, "factor"),
            ("Time Offset", "Time Coordinate Offset", "NodeSocketFloat", 0.0,
             None, None, "factor"),
            ("Output Min", "output minimum", "NodeSocketVector",
             (0.0, 0.0, 0.0), None, None, "hu"),
            ("Output Max", "output maximum", "NodeSocketVector",
             (0.0, 0.0, 0.0), None, None, "hu"),
            ("Absolute", "Absolute Value", "NodeSocketBool", False,
             None, None, "factor"),
            ("Invert Absolute", "Invert Abs Value", "NodeSocketBool", False,
             None, None, "factor"),
        ),
        ignored=("Control Point Number",
                 "Apply Velocity in Local Space (0/1)"),
        note="NOT a per-frame operator despite living in the operators list: "
             "the noise is sampled at the particle's SPAWN position and SPAWN "
             "time, so the velocity is fixed at birth. Unlike Velocity "
             "Random's independent draw, neighbours get NEAR THE SAME value - "
             "gusts rather than scatter.",
    ),

    "Lifetime Random": dict(
        section="INITIALIZER", category="INITIALIZER", stack=LAST_WINS,
        envelope=True, seen=2974,
        fields=(
            ("Lifetime Min", "lifetime_min", "NodeSocketFloat", 1.0,
             0.0, None, "sec"),
            ("Lifetime Max", "lifetime_max", "NodeSocketFloat", 2.0,
             0.0, None, "sec"),
            ("Lifetime Exponent", "lifetime_random_exponent",
             "NodeSocketFloat", 1.0, 0.001, None, "factor"),
        ),
    ),

    "Radius Random": dict(
        section="INITIALIZER", category="INITIALIZER", stack=LAST_WINS,
        envelope=True, seen=2472,
        fields=(
            ("Radius Min", "radius_min", "NodeSocketFloat", 8.0,
             0.0, None, "hu"),
            ("Radius Max", "radius_max", "NodeSocketFloat", 16.0,
             0.0, None, "hu"),
            ("Radius Exponent", "radius_random_exponent", "NodeSocketFloat",
             1.0, 0.001, None, "factor"),
        ),
    ),

    "Alpha Random": dict(
        section="INITIALIZER", category="INITIALIZER", stack=LAST_WINS,
        envelope=True, seen=2385,
        fields=(
            # 0..255, NOT 0..1. Real files go to 1000 for overbright, so the
            # socket is not clamped at 255 either.
            ("Alpha Min", "alpha_min", "NodeSocketInt", 255, 0, None, "byte"),
            ("Alpha Max", "alpha_max", "NodeSocketInt", 255, 0, None, "byte"),
            ("Alpha Exponent", "alpha_random_exponent", "NodeSocketFloat",
             1.0, 0.001, None, "factor"),
        ),
    ),

    "Color Random": dict(
        section="INITIALIZER", category="INITIALIZER", stack=LAST_WINS,
        envelope=True, seen=2536,
        fields=(
            # SFM stores these as 0..255 bytes and shows you a colour picker.
            # A Blender colour socket IS a picker, so the swatch is the honest
            # equivalent; the importer divides the .pcf bytes by 255.
            ("Color 1", "color1", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0),
             None, None, "byte"),
            ("Color 2", "color2", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0),
             None, None, "byte"),
        ),
        ignored=("tint_perc", "tint control point", "tint clamp min",
                 "tint clamp max", "tint update movement threshold"),
    ),

    "Rotation Random": dict(
        section="INITIALIZER", category="INITIALIZER", stack=LAST_WINS,
        envelope=True, seen=1641,
        fields=(
            # DEGREES. The survey range is -360..360 - a full turn is 360,
            # not 1 and not 2*pi. Converted to radians inside the group.
            ("Roll Initial", "rotation_initial", "NodeSocketFloat", 0.0,
             None, None, "deg"),
            ("Roll Offset Min", "rotation_offset_min", "NodeSocketFloat",
             0.0, None, None, "deg"),
            ("Roll Offset Max", "rotation_offset_max", "NodeSocketFloat",
             360.0, None, None, "deg"),
            ("Roll Exponent", "rotation_random_exponent", "NodeSocketFloat",
             1.0, 0.001, None, "factor"),
        ),
        ignored=("randomly_flip_direction", "rotation_field"),
        note="roll = rotation_initial + random(offset_min, offset_max)",
    ),

    "Sequence Random": dict(
        section="INITIALIZER", category="INITIALIZER", stack=LAST_WINS,
        envelope=True, seen=736,
        fields=(
            ("Sequence Min", "sequence_min", "NodeSocketInt", 0,
             0, None, "count"),
            ("Sequence Max", "sequence_max", "NodeSocketInt", 0,
             0, None, "count"),
        ),
        note="sequence_max 0 with sequence_min 0 means 'sequence 0 only'. "
             "The builder clamps both to the sheet's real sequence count.",
    ),

    "Position Within Sphere Random": dict(
        section="INITIALIZER", category="INITIALIZER", stack=ADD,
        envelope=True, seen=2569,
        # 🔴 DEFAULTS ARE THE ENGINE'S, NOT PLAUSIBLE NUMBERS. A .pcf OMITS
        # every attribute that equals the engine default (a real laser's
        # sphere element carries nothing but 'operator help and notes'), and
        # whatever sits here is what those systems get. Distance Max used to
        # default 10.0 - so every point-emitting system imported as a ten-
        # unit BALL of scatter the author never wrote. Source's default is 0.
        fields=(
            ("Control Point", "control_point_number", "NodeSocketInt", 0,
             0, None, "count"),
            ("Distance Min", "distance_min", "NodeSocketFloat", 0.0,
             None, None, "hu"),
            ("Distance Max", "distance_max", "NodeSocketFloat", 0.0,
             None, None, "hu"),
            # A RATIO, not a distance - never multiplied by Scale. (1,1,1)
            # is a sphere, (1,1,0) a flat disc: the direction is squashed
            # componentwise and re-normalized inside the group.
            ("Distance Bias", "distance_bias", "NodeSocketVector",
             (1.0, 1.0, 1.0), None, None, "factor"),
            ("Speed Min", "speed_min", "NodeSocketFloat", 0.0,
             None, None, "hu"),
            ("Speed Max", "speed_max", "NodeSocketFloat", 0.0,
             None, None, "hu"),
            # rolls 0..1 ^ exponent before mapping onto min..max: 0.5 biases
            # fast, values above 1 bias slow. 1 is the engine default.
            ("Speed Exponent", "speed_random_exponent", "NodeSocketFloat",
             1.0, 0.001, None, "factor"),
            ("Local Speed Min", "speed_in_local_coordinate_system_min",
             "NodeSocketVector", (0.0, 0.0, 0.0), None, None, "hu"),
            ("Local Speed Max", "speed_in_local_coordinate_system_max",
             "NodeSocketVector", (0.0, 0.0, 0.0), None, None, "hu"),
        ),
        ignored=("distance_bias_absolute_value",
                 "bias in local system", "create in model",
                 "randomly distribute to highest supplied Control Point",
                 "randomly distribution growth time"),
    ),

    #  THE GLOBAL POSITION NUDGE. 1017 systems in the TF2 corpus and over a
    #  thousand of this library's files use it - it was the single most
    #  common operator the importer still dropped. Each component of the
    #  offset is rolled independently between Min and Max, so equal Min and
    #  Max is a FIXED offset (the common authoring: lift a flash half a unit
    #  off the ground) and a symmetric range is scatter.
    "Position Modify Offset Random": dict(
        section="INITIALIZER", category="INITIALIZER", stack=ADD,
        envelope=True, seen=1017,
        fields=(
            ("Offset Min", "offset min", "NodeSocketVector",
             (0.0, 0.0, 0.0), None, None, "hu"),
            ("Offset Max", "offset max", "NodeSocketVector",
             (0.0, 0.0, 0.0), None, None, "hu"),
            # Rotates the offset into the control point's frame. Authored in
            # 413 of this library's uses, so it is wired, not ignored.
            ("Local Space", "offset in local space 0/1", "NodeSocketBool",
             False, None, None, "factor"),
        ),
        ignored=("offset proportional to radius 0/1", "control_point_number"),
        note="an ADDITIVE nudge on the spawn position, applied after the "
             "other position initializers - exactly how SFM stacks it on "
             "Position Within Sphere Random. Local Space uses the sphere "
             "initializer's control point frame; a distinct "
             "control_point_number is rare (8 uses) and reported, not built.",
    ),

    #  0.26.3: the beam-maker's curve with the place along it ROLLED per
    #  particle - Source's C_INIT_CreateAlongPath. HoovyTube's smoke rows
    #  spawn their puffs anywhere on CP1 -> CP2 with it; before it was built,
    #  every puff spawned on CP0 in one clump. Source's own defaults (start 0,
    #  end 0, bulge 0, mid 0.5) - a file states what it changes.
    "Position Along Path Random": dict(
        section="INITIALIZER", category="INITIALIZER", stack=ADD,
        envelope=True, seen=3068,
        fields=(
            ("Start Control Point", "start control point number",
             "NodeSocketInt", 0, 0, None, "count"),
            ("End Control Point", "end control point number",
             "NodeSocketInt", 0, 0, None, "count"),
            ("Bulge", "bulge", "NodeSocketFloat", 0.0, None, None, "hu"),
            ("Bulge Control",
             "bulge control 0=random 1=orientation of start pnt "
             "2=orientation of end point",
             "NodeSocketInt", 0, 0, 2, "count"),
            ("Mid Point Position", "mid point position", "NodeSocketFloat",
             0.5, None, None, "factor"),
            ("Max Distance", "maximum distance", "NodeSocketFloat", 0.0,
             0.0, None, "hu"),
        ),
        note="the path curve of Position Along Path Sequential (its node "
             "group, shared) with the fraction along it rolled per particle "
             "instead of counted - puffs anywhere between the two control "
             "points, scattered by maximum distance.",
    ),

    "Position Along Path Sequential": dict(
        section="INITIALIZER", category="INITIALIZER", stack=ADD,
        envelope=True, seen=1387,
        fields=(
            ("Control Point", "control point number", "NodeSocketInt", 0,
             0, None, "count"),
            ("End Control Point", "end control point number",
             "NodeSocketInt", 1, 0, None, "count"),
            ("Particles To Map", "particles to map from start to end",
             "NodeSocketFloat", 100.0, 2.0, None, "count"),
            ("Bulge", "bulge", "NodeSocketFloat", 0.0, None, None, "hu"),
            # 0 random per particle · 1 the START point's orientation ·
            # 2 the END point's. The field name IS the documentation, which
            # is why the .pcf spells the whole thing out.
            ("Bulge Control",
             "bulge control 0=random 1=orientation of start pnt "
             "2=orientation of end point",
             "NodeSocketInt", 0, 0, 2, "count"),
            ("Mid Point Position", "mid point position", "NodeSocketFloat",
             0.5, None, None, "factor"),
            ("Max Distance", "maximum distance", "NodeSocketFloat", 0.0,
             0.0, None, "hu"),
        ),
        ignored=("randomly select sequential CP pairs between start and "
                 "end points",),
        note="the beam-maker: particle n sits n/(map-1) of the way from the "
             "start CP to the end CP, and the numbering starts over after "
             "that - which is what lets a rope draw a straight ribbon.",
    ),

    "Velocity Random": dict(
        section="INITIALIZER", category="INITIALIZER", stack=ADD,
        envelope=True, seen=144,
        fields=(
            ("Control Point", "control_point_number", "NodeSocketInt", 0,
             0, None, "count"),
            ("Random Speed Min", "random_speed_min", "NodeSocketFloat", 0.0,
             None, None, "hu"),
            ("Random Speed Max", "random_speed_max", "NodeSocketFloat", 0.0,
             None, None, "hu"),
            ("Local Speed Min", "speed_in_local_coordinate_system_min",
             "NodeSocketVector", (0.0, 0.0, 0.0), None, None, "hu"),
            ("Local Speed Max", "speed_in_local_coordinate_system_max",
             "NodeSocketVector", (0.0, 0.0, 0.0), None, None, "hu"),
        ),
    ),

    # ── TRAIL LENGTH ─────────────────────────────────────────────────────
    #
    #  🔴 THE FIELD THAT EXPLAINS THE WHOLE TRAIL, AND ITS NAME LIES.
    #
    #  `length_min` / `length_max` here are NOT lengths. They are SECONDS -
    #  how much of the particle's own travel the trail represents. The
    #  renderer multiplies the particle's SPEED by this number, so:
    #
    #      a spark at 600 HU/s with length 0.2  ->  120 HU of trail
    #      the same spark at 60 HU/s            ->   12 HU of trail
    #
    #  That is why a trail stretches when the particle is fast and shrinks as
    #  drag slows it down, without anything animating the length.
    #
    #  And it is why this operator and render_sprite_trail seem to fight: this
    #  one is in SECONDS, the renderer's `min length` / `max length` are in
    #  HAMMER UNITS. Two fields called "length", two different quantities.
    #  The corpus shows it plainly - length_min tops out at 20 while the
    #  renderer's max length reaches 5000.
    "Trail Length Random": dict(
        section="INITIALIZER", category="INITIALIZER", stack=LAST_WINS,
        envelope=True, seen=520,
        fields=(
            ("Length Min", "length_min", "NodeSocketFloat", 0.1,
             0.0, None, "sec"),
            ("Length Max", "length_max", "NodeSocketFloat", 0.5,
             0.0, None, "sec"),
            ("Length Exponent", "length_random_exponent", "NodeSocketFloat",
             1.0, 0.0, None, "factor"),
        ),
        note="SECONDS OF TRAVEL, not a distance. Corpus: length_min 0..20, "
             "length_max 0.03..2000, exponent only ever 0 or 1. 520 uses, and "
             "354 of the 484 render_sprite_trail systems carry one - a trail "
             "without it uses the default length attribute for every "
             "particle, so they all stretch identically.",
    ),

    # ── CHILDREN ─────────────────────────────────────────────────────────
    #  A child system is a system in its own right. What makes it a CHILD is
    #  this operator: it spawns on top of the parent's living particles
    #  instead of on a control point.
    "Position From Parent Particles": dict(
        section="CHILDREN", category="INITIALIZER", stack=LAST_WINS,
        envelope=True, seen=241,
        fields=(
            # The survey's range is -1 .. 7 with an average of 0.2, so most
            # authors inherit a fifth of the parent's motion. NEGATIVE is a
            # real authoring choice: the child flies back the way the parent
            # came.
            ("Inherited Velocity Scale", "Inherited Velocity Scale",
             "NodeSocketFloat", 0.0, None, None, "factor"),
            # true in 9 of 241 uses. Off, a child takes the parent whose
            # number matches its own, so a stream of children traces the
            # parents in order; on, it takes any of them.
            ("Random Parent Distribution",
             "Random Parent Particle Distribution", "NodeSocketBool", False,
             None, None, "factor"),
        ),
        note="241 uses, always in the INITIALIZERS list. The whole operator "
             "is those two fields plus the envelope - it has no control point "
             "and no offset, because the parent particle IS the position.",
    ),

    # ── OPERATORS ────────────────────────────────────────────────────────
    "Movement Basic": dict(
        section="OPERATOR", category="OPERATOR", stack=ADD, envelope=True,
        seen=2989,
        fields=(
            ("Gravity", "gravity", "NodeSocketVector", (0.0, 0.0, 0.0),
             None, None, "hu"),
            # NOT clamped at zero: the survey found drag from -1 to 0.9, and
            # negative drag is a real authoring choice - motion amplifies
            # instead of damping.
            ("Drag", "drag", "NodeSocketFloat", 0.0, None, None, "factor"),
        ),
        ignored=("max constraint passes",),
        note="drag is a fraction kept per 30 Hz TICK: k = 30 x drag, and "
             "terminal velocity = gravity / (30 x drag).",
    ),

    "Movement Lock to Control Point": dict(
        section="OPERATOR", category="OPERATOR", stack=CHAIN, envelope=True,
        seen=1301,
        fields=(
            ("Control Point", "control_point_number", "NodeSocketInt", 0,
             0, None, "count"),
        ),
        ignored=("start_fadeout_min", "start_fadeout_max",
                 "start_fadeout_exponent", "end_fadeout_min",
                 "end_fadeout_max", "end_fadeout_exponent",
                 "distance fade range", "lock rotation"),
        note="its own start/end_fadeout_* fields are a SECOND envelope on top "
             "of the generic one, measured in the particle's life. Not built "
             "yet - the generic envelope is wired in its place.",
    ),

    "Alpha Fade In Random": dict(
        section="OPERATOR", category="OPERATOR", stack=CHAIN, envelope=True,
        seen=647,
        fields=(
            ("Fade In Time Min", "fade in time min", "NodeSocketFloat", 0.25,
             0.0, None, "sec"),
            ("Fade In Time Max", "fade in time max", "NodeSocketFloat", 0.25,
             0.0, None, "sec"),
            ("Fade In Exponent", "fade in time exponent", "NodeSocketFloat",
             1.0, 0.001, None, "factor"),
            ("Proportional", "proportional 0/1", "NodeSocketBool", True,
             None, None, "factor"),
        ),
    ),

    "Alpha Fade Out Random": dict(
        section="OPERATOR", category="OPERATOR", stack=CHAIN, envelope=True,
        seen=878,
        fields=(
            ("Fade Out Time Min", "fade out time min", "NodeSocketFloat",
             0.25, 0.0, None, "sec"),
            ("Fade Out Time Max", "fade out time max", "NodeSocketFloat",
             0.25, 0.0, None, "sec"),
            ("Fade Out Exponent", "fade out time exponent",
             "NodeSocketFloat", 1.0, 0.001, None, "factor"),
            ("Proportional", "proportional 0/1", "NodeSocketBool", True,
             None, None, "factor"),
        ),
        ignored=("fade bias", "ease in and out"),
    ),

    #  THE SIMPLE FADES - one number each, and this library leans on them
    #  hard: 4168 and 3021 uses. They are the Random fades with the roll
    #  taken out: the time is a fixed FRACTION OF LIFE for every particle.
    "Alpha Fade In Simple": dict(
        section="OPERATOR", category="OPERATOR", stack=CHAIN, envelope=True,
        seen=4168,
        fields=(
            ("Proportional Fade In Time", "proportional fade in time",
             "NodeSocketFloat", 0.25, 0.0, 1.0, "factor"),
        ),
        note="alpha ramps 0 -> normal over the FIRST fraction of the "
             "particle's life. Built on the same group as Alpha Fade In "
             "Random with min = max and Proportional pinned on.",
    ),

    "Alpha Fade Out Simple": dict(
        section="OPERATOR", category="OPERATOR", stack=CHAIN, envelope=True,
        seen=3021,
        fields=(
            ("Proportional Fade Out Time", "proportional fade out time",
             "NodeSocketFloat", 0.25, 0.0, 1.0, "factor"),
        ),
        note="alpha ramps normal -> 0 over the LAST fraction of the "
             "particle's life, measured back from death.",
    ),

    #  THE BEAM-HOLDER: puts particle n at fraction (n mod map)/map of the way
    #  from the start CP to the end CP and KEEPS it there - in this build the
    #  path position is evaluated from the live control point empties every
    #  frame, so "maintain" comes free. 511 uses in this library; holograms
    #  author it with start == end to pin a glow exactly ON a control point.
    "Movement Maintain Position Along Path": dict(
        section="OPERATOR", category="OPERATOR", stack=LAST_WINS,
        envelope=True, seen=511,
        fields=(
            ("Start Control Point", "start control point number",
             "NodeSocketInt", 0, 0, None, "count"),
            ("End Control Point", "end control point number",
             "NodeSocketInt", 0, 0, None, "count"),
            ("Particles To Map", "particles to map from start to end",
             "NodeSocketFloat", 100.0, 1.0, None, "count"),
            ("Bulge", "bulge", "NodeSocketFloat", 0.0, None, None, "hu"),
            ("Bulge Control",
             "bulge control 0=random 1=orientation of start pnt "
             "2=orientation of end point",
             "NodeSocketInt", 0, 0, 2, "count"),
            ("Mid Point Position", "mid point position", "NodeSocketFloat",
             0.5, None, None, "factor"),
            ("Max Distance", "maximum distance", "NodeSocketFloat", 0.0,
             0.0, None, "hu"),
        ),
        ignored=("cohesion strength",
                 "restart behavior (0 = bounce, 1 = loop )"),
        note="shares Position Along Path Sequential's node group - the same "
             "curve, held over the particle's life instead of set once. Its "
             "per-frame drift correction (cohesion) is not modelled; drag "
             "and gravity still apply on top.",
    ),

    #  THE DISTANCE-DRIVEN TAPER. Hologram beams author it: the particle's
    #  CURRENT distance to a control point is remapped into radius (or
    #  alpha), clamped to output min/max - which is the "cap". A pure
    #  function of the evaluated position, so it stays exact at any frame
    #  rate.
    "Remap Distance to Control Point to Scalar": dict(
        section="OPERATOR", category="OPERATOR", stack=CHAIN, envelope=True,
        seen=628,
        fields=(
            ("Control Point", "control point", "NodeSocketInt", 0,
             0, None, "count"),
            ("Distance Min", "distance minimum", "NodeSocketFloat", 0.0,
             0.0, None, "hu"),
            ("Distance Max", "distance maximum", "NodeSocketFloat", 128.0,
             0.0, None, "hu"),
            ("Output Min", "output minimum", "NodeSocketFloat", 0.0,
             None, None, "factor"),
            ("Output Max", "output maximum", "NodeSocketFloat", 1.0,
             None, None, "factor"),
            # Source's field ids: 3 = radius, 7 = alpha. Only those two are
            # wired - anything else leaves the particle untouched.
            ("Output Field", "output field", "NodeSocketInt", 3,
             0, None, "count"),
            ("Scale Initial", "output is scalar of initial random range",
             "NodeSocketBool", False, None, None, "factor"),
        ),
        ignored=("output is scalar of current value",),
        note="distance (distance min .. distance max) maps to (output min "
             ".. output max), CLAMPED at both ends - the cap. Field 3 "
             "writes radius, field 7 writes alpha (as a 0..1 factor); Scale "
             "Initial multiplies the rolled value instead of replacing it.",
    ),

    # 2001 uses in 2001 systems, in 92 of the 97 packs - THE most common
    # alpha operator in TF2 and the biggest single gap in the importer.
    "Alpha Fade and Decay": dict(
        section="OPERATOR", category="OPERATOR", stack=CHAIN, envelope=True,
        seen=2001,
        fields=(
            ("Start Alpha", "start_alpha", "NodeSocketFloat", 1.0,
             0.0, None, "factor"),
            ("End Alpha", "end_alpha", "NodeSocketFloat", 0.0,
             0.0, None, "factor"),
            # LIFE FRACTIONS, not seconds: the corpus keeps fade-in inside
            # 0..1 and averages 0.26, which only reads as a proportion.
            #
            # 🔴 THE DISPLAY NAMES MUST NOT BE "Start Fade In" ETC. Those are
            # the ENVELOPE's display names, and every operator carries the
            # envelope - so the builder's (operator, display) socket lookup
            # resolved these four to the ENVELOPE sockets, which default to
            # zero. A zero-width fade-out window starting at 0 clamps every
            # particle straight to End Alpha = 0: THE most common alpha
            # operator in TF2 made every sprite it touched INVISIBLE. The
            # sanity check under ENVELOPE now refuses any operator that
            # shadows an envelope display name.
            ("Fade In Start", "start_fade_in_time", "NodeSocketFloat", 0.0,
             None, None, "factor"),
            # 0.24.1: SOURCE'S DEFAULTS ARE 0.5 / 0.5 - measured, the
            # default fade-out starts at half-life (0.24.0 assumed 0.25 /
            # 0.75). A .pcf only stores what differs from the default, so a
            # wrong default changes every system that left it alone.
            ("Fade In End", "end_fade_in_time", "NodeSocketFloat", 0.5,
             None, None, "factor"),
            ("Fade Out Start", "start_fade_out_time", "NodeSocketFloat", 0.5,
             None, None, "factor"),
            ("Fade Out End", "end_fade_out_time", "NodeSocketFloat", 1.0,
             None, None, "factor"),
        ),
        note="one operator doing what Alpha Fade In Random and Alpha Fade Out "
             "Random do separately, with fixed times instead of a per-particle "
             "roll. Times are FRACTIONS OF LIFE. ⚠️ start_fade_out_time "
             "reaches 12 and end_fade_out_time 5 in the corpus - past 1 those "
             "mean 'never gets there', which a clamped ramp handles correctly "
             "by simply never completing.",
    ),

    # 1493 uses. Fades the particle's colour towards a second colour.
    "Color Fade": dict(
        section="OPERATOR", category="OPERATOR", stack=CHAIN, envelope=True,
        seen=1493,
        fields=(
            ("Fade To", "color_fade", "NodeSocketColor", (1.0, 1.0, 1.0, 1.0),
             None, None, "byte"),
            # SECONDS here, unlike the alpha operator above - 0.05..6 with an
            # average of 0.8 is a time, not a proportion. Two neighbouring
            # operators, two different meanings for "time".
            # 0.24.1: FRACTIONS OF LIFE, MEASURED - kit 2's fade to black ran
            # across the whole 4 s life, eased (0.24.0 read seconds).
            ("Fade Start Time", "fade_start_time", "NodeSocketFloat", 0.0,
             None, None, "factor"),
            ("Fade End Time", "fade_end_time", "NodeSocketFloat", 1.0,
             None, None, "factor"),
            ("Ease In And Out", "ease_in_and_out", "NodeSocketBool", True,
             None, None, "factor"),
        ),
        note="ease_in_and_out is TRUE in 1327 of 1493 uses, so the smooth "
             "ramp is the normal case and the linear one is the exception.",
    ),

    "Radius Scale": dict(
        section="OPERATOR", category="OPERATOR", stack=CHAIN, envelope=True,
        seen=3250,
        fields=(
            ("Start Scale", "radius_start_scale", "NodeSocketFloat", 1.0,
             0.0, None, "factor"),
            ("End Scale", "radius_end_scale", "NodeSocketFloat", 1.0,
             0.0, None, "factor"),
            # 0.24.1: FRACTIONS OF LIFE, MEASURED - not seconds. Kit 2's
            # default row grew across the WHOLE 4 s life, and end_time 0.25
            # was full at a quarter of it. (0.24.0 read seconds off the
            # corpus ranges; start_time 5 just means "never".)
            ("Start Time", "start_time", "NodeSocketFloat", 0.0,
             None, None, "factor"),
            ("End Time", "end_time", "NodeSocketFloat", 1.0,
             None, None, "factor"),
            ("Ease In And Out", "ease_in_and_out", "NodeSocketBool", False,
             None, None, "factor"),
            # 0.24.1: Source's BiasSIMD, t / ((1/b - 2)(1 - t) + 1), measured:
            # bias 0.95 is ~60% of the way at 1/16 of life and ~90% by a
            # third - the dust cloud of the concrete impacts, which grew over
            # a second without it.
            ("Scale Bias", "scale_bias", "NodeSocketFloat", 0.5,
             0.0, 1.0, "factor"),
        ),
        note="third most duplicated operator in the corpus - 75 systems use "
             "two or three. Instances CHAIN, so two are a grow-then-shrink.",
    ),

    "Rotation Spin Roll": dict(
        section="OPERATOR", category="OPERATOR", stack=ADD, envelope=True,
        seen=826,
        fields=(
            ("Spin Rate", "spin_rate_degrees", "NodeSocketFloat", 0.0,
             None, None, "deg"),
            ("Spin Rate Min", "spin_rate_min", "NodeSocketFloat", 0.0,
             None, None, "deg"),
            ("Spin Stop Time", "spin_stop_time", "NodeSocketFloat", 0.0,
             0.0, None, "sec"),
        ),
        note="degrees PER SECOND. spin_stop_time 0 means NEVER STOPS - "
             "reading it as 'stop at t=0' freezes every spinning sprite.",
    ),

    "Rotation Yaw Flip Random": dict(
        section="OPERATOR", category="OPERATOR", stack=LAST_WINS,
        envelope=True, seen=537,
        fields=(
            ("Flip Percentage", "Flip Percentage", "NodeSocketFloat", 0.5,
             0.0, 1.0, "factor"),
        ),
        note="on a camera-facing card, yaw IS a mirror - see the group note. "
             "`Randomly Flip Yaw` (25 uses) is the same operator with the "
             "percentage pinned at 0.5. `Rotation Yaw Random` (22 uses) is a "
             "DIFFERENT thing: a real angle, only visible on orientation 2.",
    ),

    # ── FORCE GENERATOR ──────────────────────────────────────────────────
    "random force": dict(
        section="FORCE GENERATOR", category="FORCE", stack=ADD, envelope=True,
        seen=539,
        fields=(
            ("Min Force", "min force", "NodeSocketVector", (0.0, 0.0, 0.0),
             None, None, "hu"),
            ("Max Force", "max force", "NodeSocketVector", (0.0, 0.0, 0.0),
             None, None, "hu"),
        ),
        note="a constant per-particle acceleration, i.e. exactly what gravity "
             "is - so it is added to the gravity vector and inherits Movement "
             "Basic's drag maths unchanged.",
    ),

    "Pull towards control point": dict(
        section="FORCE GENERATOR", category="FORCE", stack=ADD, envelope=True,
        seen=177,
        fields=(
            ("Control Point", "control point number", "NodeSocketInt", 0,
             0, None, "count"),
            ("Amount", "amount of force", "NodeSocketFloat", 0.0,
             None, None, "hu"),
            ("Falloff Power", "falloff power", "NodeSocketFloat", 0.0,
             None, None, "factor"),
        ),
        note="POSITION DEPENDENT - integrated per frame in the simulation "
             "zone, so it is frame-rate dependent unlike everything else. "
             "falloff 0 is a constant pull; the corpus runs -0.5 to 2, and a "
             "negative power means the pull STRENGTHENS with distance.",
    ),

    "twist around axis": dict(
        section="FORCE GENERATOR", category="FORCE", stack=ADD, envelope=True,
        seen=292,
        fields=(
            ("Amount", "amount of force", "NodeSocketFloat", 0.0,
             None, None, "hu"),
            ("Axis", "twist axis", "NodeSocketVector", (0.0, 0.0, 1.0),
             None, None, "factor"),
        ),
        ignored=("object local space axis 0/1",),
        note="POSITION DEPENDENT - integrated per frame. `twist axis` is "
             "AMBIGUOUS: Valve calls it 'location of the axis in XYZ' but the "
             "corpus holds -1..1000, far too wide for a unit direction. "
             "Treated as a DIRECTION through control point 0.",
    ),

    # ── RENDERER ─────────────────────────────────────────────────────────
    "render_rope": dict(
        section="RENDERER", category="RENDERER", stack=LAST_WINS,
        envelope=True, seen=231,
        fields=(
            # The WHOLE of render_rope in a real .pcf. Three fields.
            ("Texel Size", "texel_size", "NodeSocketFloat", 0.1,
             0.0, None, "factor"),
            ("Texture Scroll Rate", "texture_scroll_rate", "NodeSocketFloat",
             0.0, None, None, "factor"),
            ("Subdivision Count", "subdivision_count", "NodeSocketInt", 2,
             0, None, "count"),
        ),
        note="texel_size 1.0 is one texture repeat across the whole rope, "
             "0.5 is two. subdivision_count is a FLOW interpolation setting - "
             "Source clamps anything <= 0 to 1, so it is never off.",
    ),

    "render_sprite_trail": dict(
        section="RENDERER", category="RENDERER", stack=LAST_WINS,
        envelope=True, seen=484,
        fields=(
            ("Animation Rate", "animation rate", "NodeSocketFloat", 0.1,
             0.0, None, "count"),
            # HAMMER UNITS - unlike Trail Length Random's length_min/max,
            # which are seconds. This is the clamp on the FINISHED length.
            ("Min Length", "min length", "NodeSocketFloat", 1.0,
             0.0, None, "hu"),
            ("Max Length", "max length", "NodeSocketFloat", 2048.0,
             0.0, None, "hu"),
            # 0.24.1: default 0, measured - SFM's streaks are full length
            # from birth (every streak in kit 2's spark row was 22.6 units).
            ("Length Fade In Time", "length fade in time", "NodeSocketFloat",
             0.0, 0.0, None, "sec"),
            # NOT IN THE TF2 CORPUS - none of the 484 uses writes it, so it
            # is either newer than these packs or only saved when non-default.
            # It is a real SFM field and it is the one that stops a slow
            # particle drawing a trail wider than it is long, so it is exposed
            # with the flag on its name rather than left out.
            ("Constrain Radius To Length", "constrain radius to length",
             "NodeSocketBool", True, None, None, "factor"),
        ),
        ignored=("Visibility Proxy Input Control Point Number",
                 "Visibility Proxy Radius", "Visibility input minimum",
                 "Visibility input maximum", "Visibility Alpha Scale minimum",
                 "Visibility Alpha Scale maximum",
                 "Visibility Radius Scale minimum",
                 "Visibility Radius Scale maximum"),
        note="THE LENGTH IS NOT A FIELD, IT IS A CALCULATION:\n"
             "    speed x trail_length  ->  clamp(min length, max length)  "
             "->  x fade in\n"
             "Corpus: animation rate only ever 0.1 / 1 / 3 / 5; min length "
             "0..2500; max length 1.5..5000; length fade in time 0..2 s.",
    ),

    "render_animated_sprites": dict(
        section="RENDERER", category="RENDERER", stack=LAST_WINS,
        envelope=True, seen=2569,
        fields=(
            ("Animation Rate", "animation rate", "NodeSocketFloat", 1.0,
             0.0, None, "count"),
            ("Fit Lifetime", "animation_fit_lifetime", "NodeSocketBool",
             False, None, None, "factor"),
            ("Orientation Type", "orientation_type", "NodeSocketInt", 0,
             0, 2, "count"),
            # -1 IS SOURCE'S DEFAULT AND IT MEANS "NOT BOUND TO ANY CONTROL
            # POINT" - orientation stays in world axes, so a type-2 card lies
            # flat on the ground no matter how the empties are rotated. It
            # was pinned at 0 here, which silently glued every unauthored
            # system's orientation to CP0.
            ("Orientation Control Point", "orientation control point",
             "NodeSocketInt", -1, -1, None, "count"),
        ),
        ignored=("second sequence animation rate", "use animation rate as FPS",
                 "Visibility Proxy Input Control Point Number",
                 "Visibility Proxy Radius", "Visibility input minimum",
                 "Visibility input maximum", "Visibility Alpha Scale minimum",
                 "Visibility Alpha Scale maximum",
                 "Visibility Radius Scale minimum",
                 "Visibility Radius Scale maximum"),
    ),

    "Rotation Yaw Random": dict(
        section="INITIALIZER", category="INITIALIZER", stack=LAST_WINS,
        envelope=False, seen=22,
        fields=(
            ("Yaw Min", "yaw_offset_min", "NodeSocketFloat",
             0.0, None, None, "deg"),
            ("Yaw Max", "yaw_offset_max", "NodeSocketFloat",
             0.0, None, None, "deg"),
        ),
        ignored=("yaw_initial", "yaw_random_exponent"),
        note="a real yaw angle per particle, shown the only way a card that "
             "always faces the camera can show it: horizontal "
             "foreshortening, cos(yaw) on the card's X scale.",
    ),

    # ── CONSTRAINT ───────────────────────────────────────────────────────

    #  The path constraint's SIMPLER SIBLING (106 corpus uses): the same
    #  radial clamp around ONE control point - no travel, no envelope
    #  interpolation, just "stay between min and max of this point". The
    #  centre can be offset (conc_stars lifts it 5 units off the ground).
    "Constrain distance to control point": dict(
        section="CONSTRAINT", category="CONSTRAINT", stack=CHAIN,
        envelope=True, seen=106,
        fields=(
            ("Control Point", "control point number",
             "NodeSocketInt", 0, 0, None, "count"),
            ("Minimum Distance", "minimum distance", "NodeSocketFloat",
             0.0, 0.0, None, "hu"),
            ("Maximum Distance", "maximum distance", "NodeSocketFloat",
             100.0, 0.0, None, "hu"),
            ("Center Offset", "offset of center", "NodeSocketVector",
             (0.0, 0.0, 0.0), None, None, "hu"),
        ),
        #  global center point flips the offset from CP-local to world
        #  space - False in every corpus use sampled; reported if authored.
        ignored=("global center point",),
        note="clamp each particle between Minimum and Maximum Distance of "
             "one control point (plus a CP-local Center Offset). MAX WINS "
             "over MIN where they cross, same as its path sibling.",
    ),

    #  🔴 THE MISSING HALF OF EVERY WILD BEAM. beam (king).pcf authors a
    #  random force of ±1255 with drag 0.001 - terminal velocity ~42000
    #  HU/s - and the author never meant that motion to be SEEN raw: this
    #  constraint is the leash that turns it into crackle. Without it the
    #  beam shot off into infinity, which is exactly what "a constraint is
    #  missing" looks like.
    #
    #  It clamps each particle to within a distance envelope of an ANCHOR
    #  travelling along the start-CP → end-CP path over Travel Time. The
    #  envelope is Maximum Distance at departure, Middle halfway, End on
    #  arrival - beam (king) authors 7.5 → 12.5 → 0, so the crackle blooms
    #  and then pinches ONTO the path. A -1 middle/end means "same as
    #  Maximum Distance" (the engine's own sentinel). MAX WINS over MIN
    #  when they cross - authored end 0 with min 1 pins to the path.
    #
    #  Applied to the FINAL position, after forces and the lock - a pure
    #  function of (position, age), so it costs no integration and stays
    #  exact at any frame rate.
    "Constrain distance to path between two control points": dict(
        section="CONSTRAINT", category="CONSTRAINT", stack=CHAIN,
        envelope=True, seen=82,
        fields=(
            ("Start Control Point", "start control point number",
             "NodeSocketInt", 0, 0, None, "count"),
            ("End Control Point", "end control point number",
             "NodeSocketInt", 0, 0, None, "count"),
            ("Minimum Distance", "minimum distance", "NodeSocketFloat",
             0.0, 0.0, None, "hu"),
            ("Maximum Distance", "maximum distance", "NodeSocketFloat",
             100.0, 0.0, None, "hu"),
            ("Maximum Distance Middle", "maximum distance middle",
             "NodeSocketFloat", -1.0, None, None, "hu"),
            ("Maximum Distance End", "maximum distance end",
             "NodeSocketFloat", -1.0, None, None, "hu"),
            ("Travel Time", "travel time", "NodeSocketFloat",
             10.0, 0.0, None, "sec"),
            ("Mid Point Position", "mid point position", "NodeSocketFloat",
             0.5, None, None, "factor"),
            ("Random Bulge", "random bulge", "NodeSocketFloat",
             0.0, None, None, "factor"),
            #  0 rolls a bow direction per particle; 1/2 take the start/end
            #  CP's own up axis through its rotation - rotate the empty and
            #  the bow follows. Same convention as the path initializer.
            ("Bulge Control",
             "bulge control 0=random 1=orientation of start pnt "
             "2=orientation of end point",
             "NodeSocketInt", 0, 0, 2, "count"),
        ),
        #  travel time scale field scales travel time by another
        #  per-particle field - rare, and reported.
        ignored=("travel time scale field",),
        note="the beam leash: position is clamped to within min..max of an "
             "anchor travelling start CP -> end CP over Travel Time, with "
             "the max interpolating start -> middle -> end along the way.",
    ),
}


# 🔴 NO OPERATOR MAY NAME A FIELD THE WAY THE ENVELOPE NAMES ITS FIVE.
#  The builder looks sockets up by (operator, display name), and the envelope
#  is appended to every operator's field list - so a shadowed display name
#  silently resolves to the ENVELOPE socket, whose default is 0. That is how
#  Alpha Fade and Decay wired its fade windows to zeros and made every sprite
#  it touched invisible. Refuse the catalogue outright rather than let the
#  next collision ship.
_ENV_DISPLAYS = {f[0] for f in ENVELOPE}
for _op, _ospec in OPERATORS.items():
    _shadow = _ENV_DISPLAYS & {f[0] for f in _ospec["fields"]}
    if _shadow:
        raise ValueError(
            f"ras_spec: operator {_op!r} shadows envelope field(s) "
            f"{sorted(_shadow)} - rename the operator's display names")


# =============================================================================
#  WHICH OPERATORS REALLY DO APPEAR TWICE
# =============================================================================
#  Counted across 97 TF2 .pcf packs / 3574 system definitions. "systems" is how
#  many systems use the operator at all; "dupes" how many use it more than
#  once; "max" the most instances found in a single system.
#
#  It is a small fraction of uses - 377 of 42183, 0.9% - but it is spread over
#  30 different operators, and for some it is the NORM rather than the
#  exception: Remap Initial Distance to Control Point to Scalar is duplicated
#  in 40 of the 76 systems that use it at all.

DUPLICATED_IN_THE_WILD = {
    # operator: (systems, systems with >1, most in one system)
    "Remap Initial Distance to Control Point to Scalar": (76, 40, 4),
    "Radius Scale": (2469, 75, 3),
    "Rotation Spin Roll": (538, 58, 2),
    "Oscillate Scalar": (129, 22, 2),
    "emit_continuously": (2218, 19, 3),
    "Remap Initial Scalar": (107, 17, 6),
    "Velocity Noise": (241, 13, 3),
    "oscillate_vector": (25, 13, 4),
    "remap initial scalar": (51, 13, 4),
    "Remap Distance to Control Point to Scalar": (66, 11, 3),
    "Movement Dampen Relative to Control Point": (26, 10, 3),
    "Lifetime Random": (2964, 10, 2),
    "render_animated_sprites": (2560, 9, 2),
    "Remap Scalar": (38, 8, 2),
    "Position Modify Offset Random": (1017, 7, 2),
    "Oscillate Vector": (222, 7, 3),
    "Set child control points from particle positions": (103, 7, 2),
    "Movement Basic": (2983, 6, 2),
    "Velocity Random": (138, 6, 2),
    "Remap Noise to Scalar": (69, 5, 2),
    "Set Control Point Positions": (129, 4, 2),
    "radius_scale": (49, 4, 2),
    "Sequence Random": (733, 3, 2),
    "random force": (354, 2, 2),
    "emit_instantaneously": (1043, 2, 2),
    "Prevent passing through a plane": (17, 2, 2),
    "Movement Lock to Control Point": (1300, 1, 2),
    "Alpha Fade Out Random": (877, 1, 2),
    "twist around axis": (204, 1, 2),
    "Pull towards control point": (107, 1, 2),
}


# =============================================================================
#  RESEARCHED BUT NOT BUILT
# =============================================================================
#  Exact field names and value ranges, read out of the TF2 + Black Mesa packs.
#  Everything here is one step from being implementable; what is missing is
#  noted per entry, not hand-waved.
#
#  THE DIVIDING LINE IS POSITION DEPENDENCE. Every operator we have built is a
#  pure function of AGE - it can be evaluated in closed form, which is why the
#  preview is exact at any frame rate and idempotent under re-evaluation. An
#  operator whose force depends on WHERE THE PARTICLE IS cannot be: the force
#  changes the position, which changes the force. Those need per-frame velocity
#  integration, which the simulation zone could carry but which trades away
#  that exactness. That is a deliberate decision, not an oversight.

NOT_BUILT = {
    "Rotation Spin Yaw": dict(
        seen=38, why="same as above. Fields mirror Rotation Spin Roll exactly.",
        fields=("yaw_rate_degrees", "yaw_rate_min", "yaw_stop_time"),
    ),
    "Rotation Speed Random": dict(
        seen=141, why="a spin rate initializer that Rotation Spin Roll then "
                      "consumes - needs the two wired as a pair.",
        fields=("rotation_speed_constant", "rotation_speed_random_min",
                "rotation_speed_random_max", "rotation_speed_random_exponent",
                "randomly_flip_direction"),
    ),
    "Velocity Noise": dict(
        seen=361, why="POSITION AND TIME DEPENDENT. The noise is sampled at "
                      "the particle's current position every frame, so the "
                      "velocity is not constant and there is no closed form. "
                      "Needs per-frame integration.",
        fields=("Control Point Number", "Time Noise Coordinate Scale",
                "Spatial Noise Coordinate Scale", "Time Coordinate Offset",
                "Spatial Coordinate Offset", "Absolute Value",
                "Invert Abs Value", "output minimum", "output maximum",
                "Apply Velocity in Local Space (0/1)"),
    ),
    "Pull towards control point": dict(
        seen=177, why="POSITION DEPENDENT - the force points at the CP and "
                      "falls off with distance, so it changes as the particle "
                      "moves. Needs per-frame integration.",
        fields=("control point number", "falloff power", "amount of force"),
    ),
    "twist around axis": dict(
        seen=292, why="POSITION DEPENDENT - the force is tangential to an "
                      "axis, so its direction depends on where the particle "
                      "is. Needs per-frame integration.",
        fields=("amount of force", "twist axis", "object local space axis 0/1"),
    ),
    # "Movement Maintain Position Along Path" moved OUT of this list - it is
    # built now, sharing Position Along Path Sequential's curve group.
    "Position Along Path Sequential": dict(
        seen=130, why="same curve machinery, as an INITIALIZER instead - "
                      "particle N is placed at fraction N/count along the "
                      "path. Probably the easier of the two to build first.",
        fields=("start control point number", "end control point number",
                "maximum distance", "bulge", "mid point position",
                "particles to map from start to end",
                "restart behavior (0 = bounce, 1 = loop )"),
    ),
    # "Constrain distance to path between two control points" is BUILT now
    # (section CONSTRAINT) - the beam leash. See OPERATORS.
    "Movement Rotate Particle Around Axis": dict(
        seen=77, why="POSITION DEPENDENT, but the ONLY one of that family "
                     "with a closed form - a steady rotation about an axis "
                     "is just rotating the birth offset by rate x age. Worth "
                     "doing next.",
        fields=("Rotation Axis", "Rotation Rate", "Control Point",
                "Use Local Space"),
    ),
    "Color Fade": dict(
        seen=1738, why="straightforward - fades colour towards color_fade "
                       "between two times. Pure function of age.",
        fields=("color_fade", "fade_start_time", "fade_end_time",
                "ease_in_and_out"),
    ),
    "Alpha Fade and Decay": dict(
        seen=2469, why="the single most common alpha operator in the corpus "
                       "and a pure function of age. Should probably come "
                       "before anything else on this list.",
        fields=("start_alpha", "end_alpha", "start_fade_in_time",
                "end_fade_in_time", "start_fade_out_time",
                "end_fade_out_time"),
    ),
    "Lifespan Decay": dict(
        seen=1127, why="1127 uses and no fields at all beyond the envelope - "
                       "it is the operator that kills a particle when its age "
                       "passes its lifetime, which this build does "
                       "unconditionally in the simulation zone. Listed so the "
                       "importer can recognise it and say 'already handled' "
                       "rather than warn about dropping it.",
        fields=(),
    ),
}


# =============================================================================
#  SOCKET NAMING
# =============================================================================

_AMBIGUOUS = None


def _ambiguous():
    """(display, sfm) pairs that more than one operator uses.

    THE NAMES ARE NOT NATURALLY UNIQUE and this is not a corner case: all FIVE
    envelope fields are on every single operator, `emission_start_time` is on
    both emit_continuously and emit_instantaneously, `control point number` is
    on four operators. Blender lets two interface sockets share a name without
    complaint, so a name-keyed lookup silently resolves every one of them to
    whichever was declared LAST - every operator would drive the same
    envelope."""
    global _AMBIGUOUS
    if _AMBIGUOUS is None:
        seen = {}
        for op in OPERATORS:
            for f in fields_for(op):
                seen.setdefault((f[0], f[1]), set()).add(op)
        _AMBIGUOUS = {k for k, v in seen.items() if len(v) > 1}
    return _AMBIGUOUS


def socket_name(display, sfm, instance=1, operator=None):
    """"Lifetime Min [SFM: lifetime_min]", or "... #2 ..." for instance 2+.

    The bracketed half is what the importer matches on. The instance marker
    goes on the READABLE half so the SFM tag stays a clean attribute name.

    WHERE A NAME WOULD COLLIDE the operator is prepended - "Radius Scale ·
    Start Fade In [SFM: operator start fadein]". Only where it collides, so
    the common fields stay short and readable."""
    tag = f"{display} #{instance}" if instance > 1 else display
    if operator and (display, sfm) in _ambiguous():
        tag = f"{operator} · {tag}"
    return f"{tag} [SFM: {sfm}]"


def panel_name(operator, instance=1):
    return f"{operator} #{instance}" if instance > 1 else operator


def fields_for(operator):
    """Every socket this operator instance needs: its own, then the envelope."""
    spec = OPERATORS[operator]
    out = list(spec["fields"])
    if spec.get("envelope"):
        out += list(ENVELOPE)
    return out


def sfm_lookup():
    """{(operator, sfm attribute): display} - the importer's whole job."""
    return {(op, f[1]): socket_name(f[0], f[1], 1, op)
            for op in OPERATORS
            for f in fields_for(op)}


def ignored_fields(operator):
    """Attributes real files carry that this build drops on the floor.

    The importer should WARN with these rather than let someone believe an
    effect came through intact when a third of its authoring did not."""
    return tuple(OPERATORS[operator].get("ignored", ()))

SFM_DEFAULTS = {
    ("Radius Random", "radius_min"): 1.0,
    ("Radius Random", "radius_max"): 1.0,
    ("Lifetime Random", "lifetime_min"): 0.0,
    ("Lifetime Random", "lifetime_max"): 0.0,
    ("Trail Length Random", "length_max"): 0.1,
    ("emit_continuously", "emission_rate"): 100.0,
    ("render_animated_sprites", "animation rate"): 0.1,
    ("render_sprite_trail", "min length"): 0.0,
}
