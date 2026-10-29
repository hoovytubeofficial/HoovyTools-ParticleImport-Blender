# =============================================================================
# tools/rope_nodes.py  -  RENDER ROPE, the second Source sprite renderer
# =============================================================================
#
# what A ROPE is. render_animated_sprites draws one camera-facing card per
# particle. render_rope draws ONE CONTINUOUS RIBBON through all of them,
# oldest to newest - a trail, a beam, a lightning arc
#
# The logic here is a port of HoovyTube's rope prototype (v22), which had
# already solved the hard parts. The maths is kept exactly; what changed is
# the shape of the code - same DSL, same self-documenting frames, same
# attribute conventions as the animated-sprites renderer, so the two graphs
# read alike and share every operator upstream of them
#
# the pipeline
#  ------------
# points, oldest -> newest        ordered by particle_id, which only ever
# |                             increases and never renumbers
# Points to Curves
# |
# Catmull-Rom + resolution        Source's subdivision_count is a FLOW
# |                             interpolation setting, not a Blender
# |                             edge subdivision
# store per-sample data           centre, camera-facing width axis, V
# |
# Curve to Mesh (2-point profile) quad strip, 2 vertices per sample
# |
# REBUILD the RAILS EXPLICITLY    the one trick that makes it stable
# |
# one ribbon
#
# why the RAILS are REBUILT. Curve To Mesh is kept only as a topology bridge:
# it gives the right two vertices per sample and the right quads. Its own
# profile orientation comes from Blender's internal curve frame, which twists
# and rolls along the curve and made the ribbon flip. So the positions it
# produces are thrown away and each vertex is placed by hand:
#
# P = rope_center + rope_axis * (rope_u * 2 - 1) * half_width * radius
#
# After that no curve-frame roll can rotate the visible ribbon at all
# =============================================================================

import bpy

from .sprite_nodes import _group, _sock, _nd, _lk, _sv, note, proxy_material
from .ras_nodes import _io, _gin, EPS


def build_rope_material(name, image, overbright=1.0, additive=False):
    """Unlit, alpha-blended, driven by the ribbon's own coordinates.

    Reads the SAME per-particle attributes the sprite material reads -
    sprite_alpha and sprite_color - so every initializer and operator upstream
    works on a rope exactly as it does on sprites. The only rope-specific
    inputs are rope_u (across the ribbon) and rope_v (along it).

    NOTE the attributes here are plain GEOMETRY attributes, not INSTANCER
    ones. A rope is one real mesh rather than a cloud of instanced cards, so
    the instancer indirection the sprite material needs does not apply.

    🔴 $OVERBRIGHTFACTOR AND $ADDITIVE ARRIVE HERE, and for a long time they
    did not. The sprite material learned both - "on an additive sheet BLACK IS
    TRANSPARENT", "overbright is the main colour control on a glow" - and this
    one, written later, read neither: emission was pinned at 1.0 and opacity
    came from an alpha channel that additive beam sheets do not have. A laser
    authored at `$overbrightfactor 15 $additive 1` therefore imported as a dim
    ribbon inside a black rectangle, and editing the .vmt changed nothing,
    because nothing downstream was reading it.
    IF A VALUE LOOKS IGNORED, CHECK THAT SOMETHING CONSUMES IT."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    for attr, val in (("surface_render_method", "DITHERED"),
                      ("use_transparency_overlap", True),
                      ("use_backface_culling", False),
                      ("show_transparent_back", True)):
        try:
            setattr(mat, attr, val)
        except Exception:
            pass

    nt = mat.node_tree
    nt.nodes.clear()

    u = _nd(nt, "ShaderNodeAttribute", (-900, 200), "rope_u  (across)")
    u.attribute_name = "rope_u"
    v = _nd(nt, "ShaderNodeAttribute", (-900, 40), "rope_v  (along)")
    v.attribute_name = "rope_v"
    uv = _nd(nt, "ShaderNodeCombineXYZ", (-680, 120), "the ribbon's own UV")
    _lk(nt, u, 2, uv, 0)          # attribute outputs: Color, Vector, Fac, Alpha
    _lk(nt, v, 2, uv, 1)

    tex = _nd(nt, "ShaderNodeTexImage", (-460, 120), "the trail texture")
    tex.image = image
    tex.interpolation = "Linear"
    tex.extension = "REPEAT"
    _lk(nt, uv, 0, tex, 0)

    col = _nd(nt, "ShaderNodeAttribute", (-460, -180), "sprite_color")
    col.attribute_name = "sprite_color"
    tint = _nd(nt, "ShaderNodeVectorMath", (-200, 40), "texture x colour",
               operation="MULTIPLY")
    _lk(nt, tex, 0, tint, 0)
    _lk(nt, col, 0, tint, 1)

    # $OVERBRIGHTFACTOR IS THE BEAM'S MAIN COLOUR CONTROL, not a nicety. Beam
    # materials are authored at 15 and 35; at a fixed strength of 1.0 the
    # imported ribbon is a fifteenth as hot as the thing being copied, which
    # reads as "the colour is wrong" rather than "the brightness is wrong".
    # 2.0 is the house baseline for an emissive card, same as the sprite
    # material, multiplied by whatever the .vmt asked for.
    emit = _nd(nt, "ShaderNodeEmission", (40, 40),
               f"unlit, like Source · overbright {overbright:g}")
    _lk(nt, tint, 0, emit, 0)
    _sv(emit, 1, 2.0 * max(0.0, float(overbright)))

    alpha = _nd(nt, "ShaderNodeAttribute", (-460, -360), "sprite_alpha")
    alpha.attribute_name = "sprite_alpha"

    # 🔴 ON AN ADDITIVE SHEET, BLACK is TRANSPARENT. Source draws
    # `$additive 1` by ADDING the texture to the frame, so a black pixel adds
    # nothing and disappears - which is why beam sheets ship with a solid-1
    # alpha channel, or none at all. The blackness is the mask.
    #
    # `beam_bm` is exactly that: read as alpha-blended it draws a black
    # rectangle with a bright streak inside it, which is the "for some reason
    # it removes the black in SFM and looks goofy on import" case. Nothing
    # mysterious - opacity has to come from LUMINANCE for these
    if additive:
        opacity = _nd(nt, "ShaderNodeRGBToBW", (-460, -80),
                      "additive: black IS transparent")
        _lk(nt, tex, 0, opacity, 0)
        opacity_out = 0
    else:
        opacity, opacity_out = tex, 1          # the sheet's own alpha
    a_mul = _nd(nt, "ShaderNodeMath", (-200, -280),
                "texture alpha x particle alpha", operation="MULTIPLY")
    _lk(nt, opacity, opacity_out, a_mul, 0)
    _lk(nt, alpha, 2, a_mul, 1)

    clear = _nd(nt, "ShaderNodeBsdfTransparent", (40, -200), "see-through")
    mix = _nd(nt, "ShaderNodeMixShader", (280, -60), "fade it")
    _lk(nt, a_mul, 0, mix, 0)
    _lk(nt, clear, 0, mix, 1)
    _lk(nt, emit, 0, mix, 2)
    out = _nd(nt, "ShaderNodeOutputMaterial", (520, -60))
    _lk(nt, mix, 0, out, 0)
    return mat


def build_render_rope(mat, eye_group):
    """One continuous ribbon through every living particle."""
    # named after its material for the same reason as the sprite renderer:
    # the material is baked in, so one shared name means the second rope built
    # wipes the first one's interface and drops its links
    ng = _group(f"SP · RENDERER · render_rope · {mat.name}",
                "GeometryNodeTree")
    _sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    _sock(ng, "Points", "INPUT", "NodeSocketGeometry")
    _sock(ng, "Camera", "INPUT", "NodeSocketObject")
    _sock(ng, "Camera Source", "INPUT", "NodeSocketInt", 0, smin=0, smax=2)
    _sock(ng, "Half Width", "INPUT", "NodeSocketFloat", 1.0, smin=0.0)
    _sock(ng, "Texel Size", "INPUT", "NodeSocketFloat", 0.1, smin=0.0)
    _sock(ng, "Texture Offset", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Texture Scroll Rate", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Subdivision Count", "INPUT", "NodeSocketInt", 2, smin=0)
    # NOT SFM - the low-GPU stand-in, the same switch the card renderers
    # carry. A single ribbon IS cheap geometry, but its sheet shader is not -
    # scrolling texture sample, emission, alpha blend - so the proxy keeps
    # the ribbon and swaps the material for a flat per-system colour
    _sock(ng, "Proxy View", "INPUT", "NodeSocketBool", False)
    gi, go = _io(ng, (-1600, 0), (2200, 0))
    I = _gin(ng)

    # ── 1. one curve, oldest to newest ───────────────────────────────────
    pid = _nd(ng, "GeometryNodeInputNamedAttribute", (-1600, -320),
              "particle_id [read]", role="RENDERER", data_type="INT")
    _sv(pid, 0, "particle_id")
    order = _nd(ng, "ShaderNodeMath", (-1400, -320), "as a sort weight",
                role="RENDERER", operation="ADD")
    _lk(ng, pid, 0, order, 0)
    _sv(order, 1, 0.0)

    curve = _nd(ng, "GeometryNodePointsToCurves", (-1180, 0),
                "one curve through them all", role="RENDERER")
    _lk(ng, gi, I["Points"], curve, 0)
    _lk(ng, order, 0, curve, 2)

    # ── 2. Catmull-Rom, at Source's subdivision count ────────────────────
    smooth = _nd(ng, "GeometryNodeCurveSplineType", (-960, 0),
                 "Catmull-Rom, like Source", role="RENDERER")
    try:
        smooth.spline_type = "CATMULL_ROM"
    except Exception as exc:
        print(f"[HT_ROPE]  spline type: {exc}")
    _lk(ng, curve, 0, smooth, 0)

    # subdivision_count <= 0 is CLAMPED TO 1 by Source, not treated as "off"
    cuts = _nd(ng, "ShaderNodeMath", (-1180, -180), "at least 1",
               role="RENDERER", operation="MAXIMUM")
    _lk(ng, gi, I["Subdivision Count"], cuts, 0)
    _sv(cuts, 1, 1.0)
    cuts_i = _nd(ng, "FunctionNodeFloatToInt", (-1000, -180), role="RENDERER",
                 rounding_mode="FLOOR")
    _lk(ng, cuts, 0, cuts_i, 0)
    res = _nd(ng, "GeometryNodeSetSplineResolution", (-760, 0),
              "how finely to sample it", role="RENDERER")
    _lk(ng, smooth, 0, res, 0)
    _lk(ng, cuts_i, 0, res, 2)

    #── 3. per-sample data, stored ON THE CURVE ──────────────────────────
    #
    #Everything the ribbon needs is written here, while we still have a
    #curve. Curve To Mesh then interpolates all of it onto the evaluated
    #samples for free - which is the entire reason the smooth ribbon has
    #smooth alpha, colour and width rather than per-particle steps
    #Built once by the caller and shared with the sprite renderer - see the
    #note in build_render_animated_sprites
    eye = _nd(ng, "GeometryNodeGroup", (-1180, 420), "where the camera is",
              role="RENDERER")
    eye.node_tree = eye_group
    _lk(ng, gi, I["Camera"], eye, 0)
    _lk(ng, gi, I["Camera Source"], eye, 1)

    pos = _nd(ng, "GeometryNodeInputPosition", (-1180, 260), "sample position",
              role="RENDERER")
    tangent = _nd(ng, "GeometryNodeInputTangent", (-1180, 120),
                  "which way the rope runs", role="RENDERER")
    to_eye = _nd(ng, "ShaderNodeVectorMath", (-960, 340), "sample -> camera",
                 role="RENDERER", operation="SUBTRACT")
    _lk(ng, eye, 0, to_eye, 0)
    _lk(ng, pos, 0, to_eye, 1)

    # SOURCE'S BEAM NORMAL:  N = normalize(cross(tangent, camera - position))
    cross = _nd(ng, "ShaderNodeVectorMath", (-760, 300),
                "across the rope, facing the camera", role="RENDERER",
                operation="CROSS_PRODUCT")
    _lk(ng, tangent, 0, cross, 0)
    _lk(ng, to_eye, 0, cross, 1)
    #THE DEGENERATE CASE, AND IT is VISIBLE. When the rope turns to run
    #straight at the camera, the tangent and the direction to the eye line up
    #and their cross product collapses towards zero. Normalising near-zero
    #amplifies whatever noise is left, so the width axis spins, the ribbon
    #pinches to nothing and flips over - the hourglass pinches you see if
    #this guard is removed.
    #
    #Falling back to an axis across the tangent and a world axis keeps a sane
    #width exactly where the camera-facing rule has nothing to say
    #
    #🔴 AND THE FALLBACK must NOT DEGENERATE EITHER, which is the bug that
    #made the rope INVISIBLE FROM its own SHIPPED DEFAULTS. The fallback used
    #to be cross(tangent, world up) - fine for a rope running along the
    #ground, ZERO for one running straight up. The defaults are gravity +Z
    #and nothing sideways, so the rope goes straight up, so the fallback was
    #exactly zero. Combined with either of the two ways the camera term
    #collapses - no camera in the scene at all (the eye reads 0,0,0) or a
    #camera directly overhead - the width axis came out (0,0,0), every rail
    #landed on the centre line, and the ribbon was a zero-width sliver
    #It looked exactly like a broken material, again.
    #
    #A direction can't be parallel to both world up and world X, so taking
    #whichever cross product is longer can never collapse
    length = _nd(ng, "ShaderNodeVectorMath", (-760, 140), "how degenerate?",
                 role="RENDERER", operation="LENGTH")
    _lk(ng, cross, 0, length, 0)
    degenerate = _nd(ng, "FunctionNodeCompare", (-560, 140),
                     "pointing at the camera?", role="RENDERER",
                     data_type="FLOAT", operation="LESS_THAN")
    _lk(ng, length, 1, degenerate, 0)
    _sv(degenerate, 1, 1e-3)

    up_cross = _nd(ng, "ShaderNodeVectorMath", (-960, -40),
                   "across the tangent and world up", role="RENDERER",
                   operation="CROSS_PRODUCT")
    _lk(ng, tangent, 0, up_cross, 0)
    _sv(up_cross, 1, (0.0, 0.0, 1.0))
    x_cross = _nd(ng, "ShaderNodeVectorMath", (-960, -220),
                  "across the tangent and world X", role="RENDERER",
                  operation="CROSS_PRODUCT")
    _lk(ng, tangent, 0, x_cross, 0)
    _sv(x_cross, 1, (1.0, 0.0, 0.0))
    up_len = _nd(ng, "ShaderNodeVectorMath", (-780, -40), "length of that",
                 role="RENDERER", operation="LENGTH")
    _lk(ng, up_cross, 0, up_len, 0)
    x_len = _nd(ng, "ShaderNodeVectorMath", (-780, -220), "length of that",
                role="RENDERER", operation="LENGTH")
    _lk(ng, x_cross, 0, x_len, 0)
    use_x = _nd(ng, "FunctionNodeCompare", (-600, -140),
                "is the rope running vertically?", role="RENDERER",
                data_type="FLOAT", operation="LESS_THAN")
    _lk(ng, up_len, 1, use_x, 0)
    _lk(ng, x_len, 1, use_x, 1)
    alt = _nd(ng, "GeometryNodeSwitch", (-420, -140),
              "whichever cannot collapse", role="RENDERER",
              input_type="VECTOR")
    _lk(ng, use_x, 0, alt, 0)
    _lk(ng, up_cross, 0, alt, 1)
    _lk(ng, x_cross, 0, alt, 2)

    facing = _nd(ng, "ShaderNodeVectorMath", (-560, 420), "unit width axis",
                 role="RENDERER", operation="NORMALIZE")
    _lk(ng, cross, 0, facing, 0)
    up_unit = _nd(ng, "ShaderNodeVectorMath", (-240, -140), "unit fallback",
                  role="RENDERER", operation="NORMALIZE")
    _lk(ng, alt, 0, up_unit, 0)
    axis = _nd(ng, "GeometryNodeSwitch", (-360, 300),
               "camera-facing, or the fallback", role="RENDERER",
               input_type="VECTOR")
    _lk(ng, degenerate, 0, axis, 0)
    _lk(ng, facing, 0, axis, 1)
    _lk(ng, up_unit, 0, axis, 2)

    texel = _nd(ng, "ShaderNodeMath", (-1180, -520), "texel size, never zero",
                role="SEQUENCE", operation="MAXIMUM")
    _lk(ng, gi, I["Texel Size"], texel, 0)
    _sv(texel, 1, EPS)
    along = _nd(ng, "GeometryNodeSplineParameter", (-1180, -400),
                "0 -> 1 along the whole rope", role="SEQUENCE")
    npts = _nd(ng, "GeometryNodeAttributeDomainSize", (-1400, -560),
               "how many points threaded", role="SEQUENCE")
    npts.component = "POINTCLOUD"
    _lk(ng, gi, I["Points"], npts, 0)
    gaps = _nd(ng, "ShaderNodeMath", (-1180, -640), "point gaps, at least 1",
               role="SEQUENCE", operation="SUBTRACT")
    _lk(ng, npts, 0, gaps, 0)
    _sv(gaps, 1, 1.0)
    gaps_f = _nd(ng, "ShaderNodeMath", (-1000, -640), "never below 1",
                 role="SEQUENCE", operation="MAXIMUM")
    _lk(ng, gaps, 0, gaps_f, 0)
    _sv(gaps_f, 1, 1.0)
    repeats = _nd(ng, "ShaderNodeMath", (-980, -560),
                  "repeats = texel x gaps", role="SEQUENCE",
                  operation="MULTIPLY")
    _lk(ng, texel, 0, repeats, 0)
    _lk(ng, gaps_f, 0, repeats, 1)
    v_base = _nd(ng, "ShaderNodeMath", (-980, -460), "that x repeats",
                 role="SEQUENCE", operation="MULTIPLY")
    _lk(ng, along, 0, v_base, 0)
    _lk(ng, repeats, 0, v_base, 1)
    clock = _nd(ng, "GeometryNodeInputSceneTime", (-1180, -660), "the clock",
                role="TIME")
    scroll = _nd(ng, "ShaderNodeMath", (-980, -660), "seconds x scroll rate",
                 role="SEQUENCE", operation="MULTIPLY")
    _lk(ng, clock, 0, scroll, 0)
    _lk(ng, gi, I["Texture Scroll Rate"], scroll, 1)
    v_off = _nd(ng, "ShaderNodeMath", (-780, -520), "+ texture offset",
                role="SEQUENCE", operation="ADD")
    _lk(ng, v_base, 0, v_off, 0)
    _lk(ng, gi, I["Texture Offset"], v_off, 1)
    v_final = _nd(ng, "ShaderNodeMath", (-580, -560), "+ the scroll",
                  role="SEQUENCE", operation="ADD")
    _lk(ng, v_off, 0, v_final, 0)
    _lk(ng, scroll, 0, v_final, 1)

    chain = res
    stores = []
    for i, (nm, dtype, src, out_i) in enumerate((
            ("rope_center", "FLOAT_VECTOR", pos, 0),
            ("rope_axis", "FLOAT_VECTOR", axis, 0),
            ("rope_v", "FLOAT", v_final, 0))):
        st = _nd(ng, "GeometryNodeStoreNamedAttribute", (-340 + i * 220, 0),
                 f"{nm}  (curve POINT)", role="RENDERER", data_type=dtype,
                 domain="POINT")
        _sv(st, 2, nm)
        _lk(ng, chain, 0, st, 0)
        _lk(ng, src, out_i, st, 3)
        stores.append(st)
        chain = st

    #── 4. the profile: a two-point line that carries rope_u ─────────────
    #
    #The profile's own spline parameter is the across-the-ribbon coordinate
    #Storing it here is what makes it available after Curve To Mesh - there
    #is no other way to know which rail a mesh vertex belongs to.
    line = _nd(ng, "GeometryNodeCurvePrimitiveLine", (-340, -900),
               "a 2-point profile", role="RENDERER", mode="POINTS")
    _sv(line, 0, (0.0, 0.0, 0.0))
    _sv(line, 1, (0.0, 0.0, 1.0))
    across = _nd(ng, "GeometryNodeSplineParameter", (-340, -1060),
                 "0 on one rail, 1 on the other", role="RENDERER")
    store_u = _nd(ng, "GeometryNodeStoreNamedAttribute", (-120, -900),
                  "rope_u  (profile POINT)", role="RENDERER",
                  data_type="FLOAT", domain="POINT")
    _sv(store_u, 2, "rope_u")
    _lk(ng, line, 0, store_u, 0)
    _lk(ng, across, 0, store_u, 3)

    ribbon = _nd(ng, "GeometryNodeCurveToMesh", (400, 0),
                 "quad strip  (topology only)", role="RENDERER")
    _lk(ng, chain, 0, ribbon, 0)
    _lk(ng, store_u, 0, ribbon, 1)
    _sv(ribbon, 3, False)

    # ── 5. rebuild the rails by hand ─────────────────────────────────────
    r_centre = _nd(ng, "GeometryNodeInputNamedAttribute", (400, -320),
                   "rope_center [mesh]", role="RENDERER",
                   data_type="FLOAT_VECTOR")
    _sv(r_centre, 0, "rope_center")
    r_axis = _nd(ng, "GeometryNodeInputNamedAttribute", (400, -460),
                 "rope_axis [mesh]", role="RENDERER",
                 data_type="FLOAT_VECTOR")
    _sv(r_axis, 0, "rope_axis")
    r_u = _nd(ng, "GeometryNodeInputNamedAttribute", (400, -600),
              "rope_u [mesh]", role="RENDERER", data_type="FLOAT")
    _sv(r_u, 0, "rope_u")
    r_rad = _nd(ng, "GeometryNodeInputNamedAttribute", (400, -740),
                "sprite_radius [mesh]", role="RENDERER", data_type="FLOAT")
    _sv(r_rad, 0, "sprite_radius")

    side = _nd(ng, "ShaderNodeMath", (620, -600), "rope_u -> -1 .. +1",
               role="RENDERER", operation="MULTIPLY_ADD")
    _lk(ng, r_u, 0, side, 0)
    _sv(side, 1, 2.0)
    _sv(side, 2, -1.0)
    half = _nd(ng, "ShaderNodeMath", (820, -600), "x half width",
               role="RENDERER", operation="MULTIPLY")
    _lk(ng, side, 0, half, 0)
    _lk(ng, gi, I["Half Width"], half, 1)
    wide = _nd(ng, "ShaderNodeMath", (1020, -600), "x this particle's radius",
               role="RENDERER", operation="MULTIPLY")
    _lk(ng, half, 0, wide, 0)
    _lk(ng, r_rad, 0, wide, 1)
    arm = _nd(ng, "ShaderNodeVectorMath", (1220, -460), "axis x that",
              role="RENDERER", operation="SCALE")
    _lk(ng, r_axis, 0, arm, 0)
    _lk(ng, wide, 0, arm, 3)
    rail = _nd(ng, "ShaderNodeVectorMath", (1420, -320), "centre + arm",
               role="RENDERER", operation="ADD")
    _lk(ng, r_centre, 0, rail, 0)
    _lk(ng, arm, 0, rail, 1)
    place = _nd(ng, "GeometryNodeSetPosition", (1620, 0),
                "put the rails exactly there", role="RENDERER")
    _lk(ng, ribbon, 0, place, 0)
    _lk(ng, rail, 0, place, 2)

    setmat = _nd(ng, "GeometryNodeSetMaterial", (1840, 0), "the trail material",
                 role="RENDERER")
    _lk(ng, place, 0, setmat, 0)
    try:
        setmat.inputs[2].default_value = mat
    except Exception as exc:
        print(f"[HT_ROPE]  set material: {exc}")
    _lk(ng, setmat, 0, go, 0)

    note(ng, "RENDERER  ·  render_rope", "RENDERER", """
ONE CONTINUOUS RIBBON through every living particle, oldest to newest.

    points, ordered by particle_id
      -> Points to Curves
      -> Catmull-Rom at subdivision_count
      -> store centre / width axis / V on the CURVE
      -> Curve to Mesh with a 2-point profile
      -> REBUILD THE RAILS BY HAND
      -> one ribbon

ORDERING COMES FROM particle_id, fed in as the sort Weight. The id is handed
out once at birth and only ever increases, so the rope is threaded in birth
order no matter how many particles have died out of the middle.

SUBDIVISION_COUNT IS A FLOW SETTING, not Blender-style edge subdivision.
Source evaluates Catmull-Rom positions BETWEEN particles and interpolates
width, alpha, colour and texcoord linearly - which is why the spline type is
set to Catmull-Rom and the count becomes the spline RESOLUTION. Source clamps
anything <= 0 to 1, so it is never "off".

THE WIDTH AXIS IS SOURCE'S BEAM NORMAL:

    N = normalize( cross( tangent , camera position - sample position ) )

so the ribbon turns its flat face to the camera along its whole length.

WHERE THAT RULE BREAKS DOWN, AND IT IS VISIBLE. When the rope runs straight at
the camera the tangent and the direction to the eye line up, their cross
product collapses to nothing, and normalising near-zero amplifies whatever is
left - the axis spins, the ribbon pinches to a point and flips over. Below a
threshold it falls back to an axis across the tangent and a world axis, which
has no opinion about the camera but does keep a sane width.

🔴 AND THE FALLBACK MUST NOT COLLAPSE EITHER. It used to be cross(tangent,
world up) alone - which is ZERO for a rope running straight up, and the
shipped defaults (gravity +Z, nothing sideways) send it straight up. So with
no camera in the scene, or a camera directly overhead, BOTH terms were zero,
every rail landed on the centre line and the ribbon was a zero-width sliver.
Invisible, and indistinguishable from a broken material at a glance.

The fallback now takes whichever of cross(tangent, up) and cross(tangent, X)
is LONGER. A direction cannot be parallel to both, so it can never collapse.

WHY THE RAILS ARE REBUILT BY HAND. Curve To Mesh is kept ONLY as a topology
bridge - it gives the right two vertices per sample and the right quads. Its
own profile orientation comes from Blender's internal curve frame, which rolls
and twists along the curve and made the whole ribbon flip over. So its
positions are discarded and every vertex is placed explicitly:

    P = rope_center + rope_axis * (rope_u * 2 - 1) * half_width * radius

After that no curve-frame roll can rotate the visible ribbon at all.

🔴 ROPE_V: TEXEL SIZE IS PER POINT GAP, NOT PER ROPE. texel 1.0 maps the FULL texture between EVERY pair of emitted
points; 0.01 takes a hundred point gaps to show the picture once. So:

    rope_v = spline parameter x texel_size x (points - 1)

The earlier reading ("1.0 is one repeat across the whole rope") ignored how
many particles the rope threads, which is exactly the number an author
tunes texel against. Still driven from the NORMALISED spline parameter -
smooth, so no bowtie moire - with the point count carrying the meaning.

EVERYTHING UPSTREAM IS SHARED with render_animated_sprites - the same emitter,
the same initializers, the same operators, and the same sprite_alpha /
sprite_color / sprite_radius attributes. Only this last step differs.
""", [pid, order, curve, smooth, cuts, cuts_i, res, eye, pos, tangent, to_eye,
      cross, length, degenerate, up_cross, x_cross, up_len, x_len, use_x,
      alt, facing, up_unit, axis, texel, npts, gaps, gaps_f, repeats,
      along, v_base, clock, scroll, v_off, v_final, line, across,
      store_u, ribbon, r_centre, r_axis, r_u, r_rad, side, half, wide, arm,
      rail, place, setmat] + stores)

    # PROXY VIEW - appended at the END so no existing node's birth-order
    # name shifts (hand-layout tables match by name first; see RULES)
    # Same ribbon, flat per-system colour instead of the sheet shader:
    # place -> stand-in material -> Switch against the real setmat.
    psm = _nd(ng, "GeometryNodeSetMaterial", (1840, -240),
              "the stand-in's own colour", role="RENDERER")
    _lk(ng, place, 0, psm, 0)
    try:
        psm.inputs[2].default_value = proxy_material(ng.name)
    except Exception as exc:
        print(f"[HT_ROPE]  proxy material: {exc}")
    pick = _nd(ng, "GeometryNodeSwitch", (2040, -120),
               "the real ribbon, or the stand-in", role="RENDERER",
               input_type="GEOMETRY")
    for l in list(ng.links):
        if l.from_node.name == setmat.name and l.to_node.name == go.name:
            ng.links.remove(l)
    _lk(ng, gi, I["Proxy View"], pick, 0)
    _lk(ng, setmat, 0, pick, 1)
    _lk(ng, psm, 0, pick, 2)
    _lk(ng, pick, 0, go, 0)
    return ng
