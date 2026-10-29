# =============================================================================
#  tools/sprite_nodes.py  -  VTF sprite sheet -> shader + geometry nodes
# =============================================================================
#
#  THE ARCHITECTURAL DECISION (settled - see constitution/RULES.md)
#  --------------------------------------------------------
#  ONE material. The sequence is chosen PER PARTICLE by an attribute.
#  Not one material per sequence: SFM's Sequence Random varies per particle,
#  and you cannot randomise inside a single instanced batch without splitting
#  the geometry every frame.
#
#  THE PATTERN THAT WORKS - memorise it:
#      store the attribute on the POINT domain
#          -> Instance on Points
#              -> shader reads it with attribute_type='INSTANCER'
#  Storing on the INSTANCE domain does NOT work: 'INSTANCER' reads from the
#  instancER (the point cloud), not from the instances.
#
#  LOOPING IS PER SEQUENCE AND IT IS IN THE FILE
#  ---------------------------------------------
#  Each sequence carries a clamp flag (1 = play once and hold, 0 = loop).
#  Across 518 real sheets: 895 sequences clamp, 167 loop. In that corpus no
#  single file mixed the two, but the format stores it per sequence so we
#  honour it per sequence.
#
#  OTHER TRAPS, ALL PAID FOR IN BLOOD
#    * Mesh Grid's UV is an ANONYMOUS output socket, not a named layer. Store
#      it as "UVMap" or the shader has no UVs, samples one transparent corner
#      texel, and the sprite is INVISIBLE - which looks like a broken material.
#    * Set Material must go on the instance SOURCE, before Instance on Points.
#    * NEVER guess socket indices. In 5.2 Random Value is Min=0 Max=1 ID=2
#      Seed=3 for EVERY data type, and Compare(INT) exposes only A=0, B=1.
# =============================================================================

import colorsys
import zlib

import bpy


# ── role colours ─────────────────────────────────────────────────────────────
#  ONE HUE PER ROLE at a shared saturation and value, so a graph reads as one
#  system rather than a paint chart. The wheel positions and the reasoning
#  behind them live in tools/layout.py: warm hues are the things that CHANGE,
#  cool hues are the things that are READ, and green sits between them for
#  values decided once at birth.
#
#  A FRAME gets the same hue a shade darker. Same hue keeps the section and
#  its nodes visibly related; less value makes the frame read as the container
#  BEHIND them rather than as another node - a relationship that survives in
#  greyscale, which a hue difference would not.
from . import layout                                            # noqa: E402

ROLE = layout.role_colours()
FRAME_ROLE = layout.role_colours(frame=True)


# ── tiny node DSL ────────────────────────────────────────────────────────────

def _group(name, kind):
    ng = bpy.data.node_groups.get(name)
    if ng is None:
        ng = bpy.data.node_groups.new(name, kind)
    ng.nodes.clear()
    for item in list(ng.interface.items_tree):
        ng.interface.remove(item)
    #  🔴 A CLEARED GROUP IS AN UNTIDIED GROUP. Custom properties survive the
    #  clear, and tidy() stamps "ht_tidied" to guard its non-idempotent
    #  passes - so REBUILDING a system (importing the same .pcf twice, or
    #  create-ing the same texture again) kept the stale stamp, tidy skipped
    #  everything, and the second build opened as a raw heap with the hand
    #  layout nowhere in sight. Fresh nodes deserve a fresh layout pass.
    for stamp in ("ht_tidied", "ht_hand_layout"):
        if stamp in ng:
            del ng[stamp]
    return ng


def _shared_group(name, kind, sig):
    """A group SEVERAL MATERIALS wire into - the sheet lookup, one per texture.
    -> (group, needs_building).

    🔴 0.26.3: _group REBUILDS IN PLACE, and clearing an interface silently cuts
    every link and value the group's users had. Two systems drawing one .vtf at
    two brightnesses are two materials on ONE sheet group: building the second
    cleared it, and the first material was left with Frame / Columns / Rows at 0
    and its texture on the card's raw UVs - the WHOLE SHEET on every sprite. Same sheet -> the group as it
    was built; a different sheet under the same name -> a new group beside it
    (Blender adds .001), so nothing already wired to the old one changes."""
    ng = bpy.data.node_groups.get(name)
    if ng is not None and ng.get("htp_sig") == sig and len(ng.nodes):
        return ng, False
    if ng is not None and ng.users:
        ng = bpy.data.node_groups.new(name, kind)
    else:
        ng = _group(name, kind)
    ng["htp_sig"] = sig
    return ng, True


def set_structure(s):
    """Pin an interface socket's structure type instead of leaving it AUTO.

    Blender 5.2 CRASHES (EXCEPTION_ACCESS_VIOLATION inside
    calc_structure_type_interface) while inferring AUTO structure types for
    some groups - it takes down the whole process the moment anything
    references the group, with no Python traceback. Setting the type
    explicitly skips that inference entirely.

    DYNAMIC is the honest answer for particle data: these sockets legitimately
    carry either one value or a per-particle field."""
    try:
        s.structure_type = "DYNAMIC"
    except Exception:
        pass                      # geometry / menu sockets have no choice here


def _sock(ng, name, in_out, stype, default=None, smin=None, smax=None):
    s = ng.interface.new_socket(name, in_out=in_out, socket_type=stype)
    set_structure(s)
    if default is not None:
        try:
            s.default_value = default
        except Exception:
            pass
    for attr, val in (("min_value", smin), ("max_value", smax)):
        if val is not None:
            try:
                setattr(s, attr, val)
            except Exception:
                pass
    return s


def _nd(ng, idname, loc=(0, 0), label=None, role=None, **props):
    n = ng.nodes.new(idname)
    n.location = loc
    if label:
        n.label = label
    if role:
        n.use_custom_color = True
        n.color = ROLE[role]
    order = ("data_type", "input_type", "domain", "operation", "mode")
    for key in sorted(props, key=lambda k: (k not in order, k)):
        try:
            setattr(n, key, props[key])
        except Exception as exc:
            print(f"[HT_SPRITE]  prop {idname}.{key}: {exc}")
    return n


def _lk(ng, a, ai, b, bi):
    try:
        ng.links.new(a.outputs[ai], b.inputs[bi])
    except Exception as exc:
        print(f"[HT_SPRITE]  link {a.name}[{ai}]->{b.name}[{bi}]: {exc}")


def _sv(node, idx, value):
    try:
        node.inputs[idx].default_value = value
    except Exception as exc:
        print(f"[HT_SPRITE]  socket {node.name}[{idx}]: {exc}")


def proxy_material(seed_name):
    """The Proxy View stand-in's material: ONE flat colour per system.

    The whole point of the proxy is that it costs nothing to draw, and an
    untextured, opaque, single-colour material costs nothing - what the sheet
    shader spends is the texture sample, the emission and the alpha blend,
    none of which are here. What the colour BUYS is telling systems apart:
    a scene of proxied effects used to be identical white squares, so the
    colour is hashed from the renderer group's name - stable across sessions
    (Python's own hash() is salted per process, crc32 is not) - and every
    system wears its own, the way Solid shading's Random object colouring
    reads.

    Solid shading draws `diffuse_color` (the viewport display colour), so the
    colour shows in the mode Proxy View is FOR. Rendered views get the SAME
    colour from a bare Emission shader - 🔴 EMISSION, NOT PRINCIPLED. A lit
    BSDF made the stand-ins vanish in EEVEE (particle scenes rarely have a
    lamp: sprites light themselves, so a diffuse quad renders black) and
    shade with the lighting in Cycles. The proxy's one job is "a flat colour
    you can always see", which is what emission is.

    Rebuilt idempotently on every call, so proxies made by an older version
    of this function pick up fixes the next time anything builds."""
    key = f"HTP Proxy · {seed_name}"
    #  Three INDEPENDENT slices of the hash: similar names can land on near-
    #  identical hues (two cyans did, in testing), so saturation and value
    #  vary too and near-misses still read apart.
    h = zlib.crc32(seed_name.encode("utf-8"))
    hue = (h % 997) / 997.0
    sat = 0.55 + ((h >> 10) % 256) / 255.0 * 0.35      # 0.55 .. 0.90
    val = 0.65 + ((h >> 18) % 256) / 255.0 * 0.30      # 0.65 .. 0.95
    r, g, b = colorsys.hsv_to_rgb(hue, sat, val)
    m = bpy.data.materials.get(key)
    if m is None:
        m = bpy.data.materials.new(key)
    m.diffuse_color = (r, g, b, 1.0)     # what Solid shading actually draws
    m.use_nodes = True
    try:
        nt = m.node_tree
        nt.nodes.clear()
        em = nt.nodes.new("ShaderNodeEmission")
        em.location = (0, 0)
        em.inputs[0].default_value = (r, g, b, 1.0)
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        out.location = (220, 0)
        nt.links.new(em.outputs[0], out.inputs[0])
    except Exception as exc:
        print(f"[HT_SPRITE]  proxy material shader: {exc}")
    return m


def note(ng, title, role, body, nodes, loc=None):
    """A labelled, coloured Frame carrying a REAL multi-line explanation.

    NodeFrame.text takes a Text datablock and Blender draws it inside the
    frame - so the graph explains itself to whoever opens it in two years."""
    f = ng.nodes.new("NodeFrame")
    f.label = title
    f.use_custom_color = True
    f.color = FRAME_ROLE.get(role, FRAME_ROLE["OUTPUT"])
    f.label_size = 16
    name = f"{ng.name} · {title}"
    txt = bpy.data.texts.get(name) or bpy.data.texts.new(name)
    txt.clear()
    txt.write(body.strip("\n"))
    try:
        f.text = txt
    except Exception as exc:
        print(f"[HT_SPRITE]  frame text: {exc}")
    if nodes:
        f.shrink = True
        for n in nodes:
            n.parent = f
    elif loc:
        f.shrink = False
        f.location = loc
        f.width, f.height = 520, 260
    return f


# ── sheet maths ──────────────────────────────────────────────────────────────

def sequence_table(sheet, cols, rows):
    """[(start_tile, frame_count, loops), ...] straight from the VTF.

    The sheet tells us exactly where each sequence starts, so we never guess
    the packing, and whether it loops, so we never guess the playback."""
    table = []
    for seq in (sheet or {}).get("sequences", []):
        if not seq["frames"]:
            continue
        u0, v0, _u1, _v1 = seq["frames"][0]["uv"]
        col = int(round(u0 * cols))
        row = int(round(v0 * rows))
        table.append((row * cols + col, seq["frame_count"], bool(seq["loops"])))
    return table or [(0, 1, False)]


# backwards-compatible helper
def sequence_starts(sheet, cols, rows):
    return [(s, c) for s, c, _l in sequence_table(sheet, cols, rows)]


# ── shader: tile index -> UV ─────────────────────────────────────────────────

def build_sheet_uv_group(name, cols, rows, width=0, height=0):
    """width/height are the sheet's PIXEL size, for the half-texel inset.

    ⚠️ THE INSET IS WHAT MAKES LINEAR FILTERING SAFE. With the UVs running to
    the exact tile boundary, a Linear sample AT the boundary averages in the
    neighbouring tile's edge texels and every card grows a faint stripe of
    the next spark. Source's own sheet rects are inset half a texel for
    exactly this reason. 0 means size unknown - no inset, which is what the
    old Closest-filtered graphs effectively had."""
    ng, fresh = _shared_group(name, "ShaderNodeTree",
                              f"grid {cols}x{rows} {width}x{height}")
    if not fresh:
        return ng
    _sock(ng, "Vector", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Frame", "INPUT", "NodeSocketFloat", 0.0)
    _sock(ng, "Columns", "INPUT", "NodeSocketFloat", float(cols))
    _sock(ng, "Rows", "INPUT", "NodeSocketFloat", float(rows))
    gi = _nd(ng, "NodeGroupInput", (-900, 0))
    go = _nd(ng, "NodeGroupOutput", (760, 0))
    inset_u = 0.5 / float(width) if width else 0.0
    inset_v = 0.5 / float(height) if height else 0.0

    uv = _nd(ng, "ShaderNodeUVMap", (-900, -300), "the card's own UVs",
             role="RENDERER")
    uv.uv_map = "UVMap"

    col = _nd(ng, "ShaderNodeMath", (-620, 140), "col = frame % cols",
              role="SEQUENCE", operation="MODULO")
    _lk(ng, gi, 0, col, 0)
    _lk(ng, gi, 1, col, 1)
    dv = _nd(ng, "ShaderNodeMath", (-620, -20), role="SEQUENCE",
             operation="DIVIDE")
    _lk(ng, gi, 0, dv, 0)
    _lk(ng, gi, 1, dv, 1)
    row = _nd(ng, "ShaderNodeMath", (-440, -20), "row = floor(frame / cols)",
              role="SEQUENCE", operation="FLOOR")
    _lk(ng, dv, 0, row, 0)

    inv_c = _nd(ng, "ShaderNodeMath", (-620, 320), "1 / cols", role="SEQUENCE",
                operation="DIVIDE")
    _sv(inv_c, 0, 1.0)
    _lk(ng, gi, 1, inv_c, 1)
    inv_r = _nd(ng, "ShaderNodeMath", (-620, 460), "1 / rows", role="SEQUENCE",
                operation="DIVIDE")
    _sv(inv_r, 0, 1.0)
    _lk(ng, gi, 2, inv_r, 1)
    #  Tile MINUS one texel (half each side): the linear-safe sampling window.
    tile_u = _nd(ng, "ShaderNodeMath", (-440, 320),
                 "tile - 1 texel  (linear-safe)", role="SEQUENCE",
                 operation="SUBTRACT")
    _lk(ng, inv_c, 0, tile_u, 0)
    _sv(tile_u, 1, 2.0 * inset_u)
    tile_v = _nd(ng, "ShaderNodeMath", (-440, 460),
                 "tile - 1 texel  (linear-safe)", role="SEQUENCE",
                 operation="SUBTRACT")
    _lk(ng, inv_r, 0, tile_v, 0)
    _sv(tile_v, 1, 2.0 * inset_v)
    scale = _nd(ng, "ShaderNodeCombineXYZ", (-260, 400), "one tile's size",
                role="SEQUENCE")
    _lk(ng, tile_u, 0, scale, 0)
    _lk(ng, tile_v, 0, scale, 1)
    _sv(scale, 2, 1.0)

    offx = _nd(ng, "ShaderNodeMath", (-240, 140), "u = col / cols",
               role="SEQUENCE", operation="DIVIDE")
    _lk(ng, col, 0, offx, 0)
    _lk(ng, gi, 1, offx, 1)
    rp1 = _nd(ng, "ShaderNodeMath", (-240, -20), "row + 1", role="SEQUENCE",
              operation="ADD")
    _lk(ng, row, 0, rp1, 0)
    _sv(rp1, 1, 1.0)
    rdiv = _nd(ng, "ShaderNodeMath", (-60, -20), role="SEQUENCE",
               operation="DIVIDE")
    _lk(ng, rp1, 0, rdiv, 0)
    _lk(ng, gi, 2, rdiv, 1)
    offy = _nd(ng, "ShaderNodeMath", (120, -20), "v = 1 - (row+1)/rows",
               role="SEQUENCE", operation="SUBTRACT")
    _sv(offy, 0, 1.0)
    _lk(ng, rdiv, 0, offy, 1)

    #  ...and slide half a texel INTO the tile, matching the shrunk window.
    ox = _nd(ng, "ShaderNodeMath", (300, 140), "+ half texel", role="SEQUENCE",
             operation="ADD")
    _lk(ng, offx, 0, ox, 0)
    _sv(ox, 1, inset_u)
    oy = _nd(ng, "ShaderNodeMath", (300, -80), "+ half texel", role="SEQUENCE",
             operation="ADD")
    _lk(ng, offy, 0, oy, 0)
    _sv(oy, 1, inset_v)

    off = _nd(ng, "ShaderNodeCombineXYZ", (460, 80), "this tile's corner",
              role="SEQUENCE")
    _lk(ng, ox, 0, off, 0)
    _lk(ng, oy, 0, off, 1)

    mapping = _nd(ng, "ShaderNodeMapping", (540, 0), "slide + shrink the UVs",
                  role="RENDERER", vector_type="POINT")
    _lk(ng, uv, 0, mapping, 0)
    _lk(ng, off, 0, mapping, 1)
    _lk(ng, scale, 0, mapping, 3)
    _lk(ng, mapping, 0, go, 0)

    note(ng, "SHEET LOOKUP  ·  tile index -> UV rectangle", "SEQUENCE", """
WHAT THIS DOES
  Turns one number (the tile index) into the UV rectangle of that tile.

HOW
  The sheet is a uniform grid, so:
      col = frame % columns
      row = floor(frame / columns)
  Then the card's own 0..1 UVs get SHRUNK to one tile (Scale = 1/cols, 1/rows)
  and SLID onto that tile (Location = col/cols, ...).

WHY THE V IS FLIPPED
  Source counts rows DOWNWARD from the top of the image. Blender's V axis
  goes UP. So v = 1 - (row + 1) / rows.

WHY THE CARD'S UVs COME FROM A UV MAP NODE
  Mesh Grid hands its UVs out as an ANONYMOUS socket, not a named layer.
  The geometry side stores them as "UVMap" - without that this reads zeros,
  samples one transparent corner texel, and every sprite is INVISIBLE.

WHY THE WINDOW IS HALF A TEXEL SMALLER THAN THE TILE
  The texture is sampled LINEAR (Closest is what made sprites pixelated
  next to SFM). A linear sample exactly ON a tile boundary averages in the
  neighbouring tile's edge texels, so the window is shrunk half a texel per
  side - the same inset Source bakes into its own sheet rects.
""", [uv, col, dv, row, inv_c, inv_r, tile_u, tile_v, scale, offx, rp1,
      rdiv, offy, ox, oy, off, mapping])
    from . import layout
    layout.apply_shader_layout(ng, name)
    return ng


def rect_sequence_table(sheet, width, height):
    """NON-UNIFORM sheets: frames are different sizes, so there is no grid.
    Flatten the VTF's own per-frame rectangles into one indexed list and return
    ([(start_global_frame, frame_count, loops), ...], rects).

    Each rect is baked straight into Blender UV space: V flipped (Source counts
    rows DOWN from the top) and half a texel inset on every side, so a Linear
    sample never bleeds the neighbour - the same reasons the grid path insets.
    `sprite_frame` then indexes `rects` directly, exactly the way it indexed
    grid TILES before, so the emitter/sequence maths upstream is unchanged."""
    inset_u = 0.5 / float(width) if width else 0.0
    inset_v = 0.5 / float(height) if height else 0.0
    rects, table = [], []
    for seq in (sheet or {}).get("sequences", []):
        frames = seq.get("frames") or []
        if not frames:
            continue
        start = len(rects)
        for f in frames:
            u0, v0, u1, v1 = f["uv"]
            rects.append((u0 + inset_u,               # offset X
                          (1.0 - v1) + inset_v,       # offset Y  (V flipped)
                          (u1 - u0) - 2.0 * inset_u,  # scale  X
                          (v1 - v0) - 2.0 * inset_v)) # scale  Y
        table.append((start, len(frames), bool(seq["loops"])))
    if not rects:
        return [(0, 1, False)], [(0.0, 0.0, 1.0, 1.0)]
    return table, rects


def build_rect_uv_group(name, rects=None, width=0, height=0):
    """Non-uniform sheet: map the card's UVs onto a frame's EXACT rectangle.

    The rect itself is CHOSEN ON THE GEOMETRY SIDE - one Index Switch holding
    every frame's rectangle (see build_system's `rects` branch) - and arrives
    here per particle as two stored attributes. So this group is tiny and
    CONSTANT-SIZE: Corner and Size in, slid-and-shrunk UVs out, whether the
    sheet has 14 frames or 122. (The first version was a shader-side
    compare-and-mix ladder: ~5 nodes per frame, 613 nodes on a real fire
    sheet, and invisible to the hand layouts. Never again.)

    Named under the "RAS Sheet UV" family ON PURPOSE: the hand shader layout
    identifies group nodes by that name prefix, so the material's Sheet
    Processing frame adopts this group exactly like the grid one."""
    ng, fresh = _shared_group(name, "ShaderNodeTree", "rects")
    if not fresh:
        return ng
    _sock(ng, "Vector", "OUTPUT", "NodeSocketVector")
    _sock(ng, "Corner", "INPUT", "NodeSocketVector")
    _sock(ng, "Size", "INPUT", "NodeSocketVector")
    gi = _nd(ng, "NodeGroupInput", (-520, 0))
    go = _nd(ng, "NodeGroupOutput", (260, 0))
    uv = _nd(ng, "ShaderNodeUVMap", (-520, -220), "the card's own UVs",
             role="RENDERER")
    uv.uv_map = "UVMap"
    mapping = _nd(ng, "ShaderNodeMapping", (0, 0),
                  "slide + shrink onto the rect", role="RENDERER",
                  vector_type="POINT")
    _lk(ng, uv, 0, mapping, 0)
    _lk(ng, gi, 0, mapping, 1)     # Corner -> Location
    _lk(ng, gi, 1, mapping, 3)     # Size   -> Scale
    _lk(ng, mapping, 0, go, 0)
    note(ng, "PER-FRAME RECT  ·  the geometry already chose it", "SEQUENCE", """
This sheet's frames are DIFFERENT sizes, so there is no grid to tile. The
geometry side holds every frame's exact rectangle in ONE Index Switch and
stores the chosen corner + size per particle (sprite_rect_min /
sprite_rect_scale, and _next for frame blending). Here the card's own 0..1
UVs are simply slid onto that corner and shrunk to that size.

Each rect was baked V-flipped (Source counts rows downward) and half a texel
inset, so a Linear sample never averages in the neighbouring frame - the same
inset the grid path uses.
""", [gi, uv, mapping])
    from . import layout
    layout.apply_shader_layout(ng, name)
    return ng


def build_invisible_material(name):
    """A fully transparent material for DRIVER systems.

    A material-less SFM `render_animated_sprites` system draws nothing but still
    SIMULATES particles - it is a motion carrier whose CHILDREN (born via
    Position From Parent Particles) do the drawing. We mirror that: one card
    instance per particle (so a child can read them) wearing a Transparent BSDF,
    so the driver contributes no pixels. Also used for a system whose .vmt/.vtf
    is missing, so a broken texture no longer takes its whole subtree down."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (200, 0)
    transp = nt.nodes.new("ShaderNodeBsdfTransparent")
    transp.location = (0, 0)
    nt.links.new(transp.outputs[0], out.inputs["Surface"])
    for attr, val in (("blend_method", "BLEND"),
                      ("surface_render_method", "BLENDED")):
        try:
            setattr(mat, attr, val)
        except Exception:
            pass
    return mat


EDITOR_DRAWS = 2
#  ↑ THE SECOND DRAW, AND WHEN IT HAPPENS - measured twice:
#  0.24.0: calibration kit 1's one-particle tiles fit only as two layers - but
#  every material in kit 1 was used by two systems (a single and a double).
#  0.24.2: kit 3 gave each tile its OWN material and they fit as ONE layer
#  (2.5-4.4 grey levels; two layers were 20-26 off), except the two tiles that
#  shared one material: two layers again (2.6). Trails were drawn once even
#  when three of them shared a material. So: a sprite system whose material
#  another sprite system in the same effect also uses is drawn TWICE, every
#  other system ONCE. The .pcf importer counts that per effect and hands each
#  material its Draws; this is the value for the shared case.


def draws_tag(draws):
    """The material-name suffix for the draw count (0.24.2): the same .vmt
    drawn once by one system and twice by another is two materials."""
    n = int(draws)
    return f" · {n} draw" + ("" if n == 1 else "s")


SHADING_NOTE = """
SFM's SpriteCard, MEASURED (calibration kit, 2026-10-28, 1-3 grey levels).
All in LINEAR light - texture sRGB in, Standard view out; the particle
colour is sRGB too, hence the gamma 2.2 on it.

    s = texture x particle colour      a = texture alpha x particle alpha
    blend         S = min(1, obf s) a           T = 1 - a
    $additive     S = min(1, obf s) a           T = 1
    $addoverblend S = min(1, obf s)             T = 1 - a
    $addself k    S = min(1, obf (1+k) s a)     T = 1 - a
    frame = S + T x frame        (Emission S  +  Transparent T)

DRAWS. SFM draws a sprite system TWICE when another sprite system in the
same effect uses the same material, and ONCE otherwise; trails always once
(measured, calibration kits 1 and 3). Two draws make each card two layers:
    S x (1 + T),   T x T.
The importer sets Draws per material; change it here to override.

Clamp: the colour is clamped to 1 BEFORE blending (an overbright-2 tile's
0.75 and 0.97 greys came out the same).
"""


def legacy_blend(overbright=1.0, additive=False):
    """What the old two switches meant, for callers that only have those
    (a bare .vtf picked by hand: no .vmt, so no flags to read)."""
    return {"mode": "additive" if additive else "blend", "addself": 0.0,
            "overbright": float(overbright)}


def blend_tag(bl):
    """The material-name suffix: different blends are different materials."""
    tag = " · " + bl["mode"]
    if abs(float(bl["overbright"]) - 1.0) > 1e-6:
        tag += f" · x{float(bl['overbright']):g}"
    if bl["mode"] == "addself":
        tag += f" · self{float(bl['addself']):g}"
    return tag


def spritecard_output(nt, rgb, alpha, tint, palpha, blend, x=-140, y=120,
                      n_draws=None):
    """SFM's SpriteCard blend, measured (see SHADING_NOTE). Builds the nodes
    from the sampled texture to the Material Output and returns them.

    rgb, alpha     the sheet's colour (linear - an sRGB image) and alpha
    tint, palpha   the particle's colour (sRGB 0..1) and alpha (0..1)

    ONE SHADER FOR EVERY FLAG: Add( Transparent BSDF tinted T, Emission S ).
    The frame behind is multiplied by T and S is added on top, which is
    exactly `frame = S + T x frame` - the form all four SpriteCard blends
    reduce to. (The old mix-by-opacity could only do the plain blend; it drew
    additive sprites OVER the frame and darkened their mid-tones.)"""
    links = nt.links
    mode = blend.get("mode", "blend")
    obf = max(0.0, float(blend.get("overbright", 1.0)))
    k = float(blend.get("addself", 0.0))
    made = []

    def node(idname, loc, label, **props):
        n = _nd(nt, idname, (x + loc[0], y + loc[1]), label, role="RENDERER",
                **props)
        made.append(n)
        return n

    lin = node("ShaderNodeGamma", (0, 0), "particle colour -> linear (2.2)")
    links.new(tint, lin.inputs[0])
    lin.inputs[1].default_value = 2.2
    s = node("ShaderNodeVectorMath", (180, 0), "s = texture x colour",
             operation="MULTIPLY")
    links.new(rgb, s.inputs[0])
    links.new(lin.outputs[0], s.inputs[1])
    a = node("ShaderNodeMath", (180, -240), "a = texture x particle alpha",
             operation="MULTIPLY")
    links.new(alpha, a.inputs[0])
    links.new(palpha, a.inputs[1])

    gain = obf * (1.0 + k) if mode == "addself" else obf
    pre = node("ShaderNodeVectorMath", (360, 0),
               f"x {gain:g}  (overbright{' x (1+addself)' if mode == 'addself' else ''})",
               operation="SCALE")
    links.new(s.outputs[0], pre.inputs[0])
    pre.inputs[3].default_value = gain
    src = pre.outputs[0]
    if mode == "addself":
        pa = node("ShaderNodeVectorMath", (540, 0), "x a  (addself: alpha first)",
                  operation="SCALE")
        links.new(src, pa.inputs[0])
        links.new(a.outputs[0], pa.inputs[3])
        src = pa.outputs[0]
    clamp = node("ShaderNodeMix", (720, 0), "clamped to 1 BEFORE blending",
                 data_type="RGBA", clamp_result=True)
    clamp.inputs[0].default_value = 0.0
    links.new(src, clamp.inputs[6])
    S = clamp.outputs[2]
    if mode in ("blend", "additive"):
        sa = node("ShaderNodeVectorMath", (900, 0), "x a", operation="SCALE")
        links.new(S, sa.inputs[0])
        links.new(a.outputs[0], sa.inputs[3])
        S = sa.outputs[0]

    draws = node("ShaderNodeValue", (540, -420),
                 "Draws (2 = material shared with another system, 1 = once)")
    draws.outputs[0].default_value = float(EDITOR_DRAWS if n_draws is None
                                           else n_draws)
    if mode == "additive":
        sn = node("ShaderNodeVectorMath", (1080, 0), "x Draws  (additive: T = 1)",
                  operation="SCALE")
        links.new(S, sn.inputs[0])
        links.new(draws.outputs[0], sn.inputs[3])
        S_out, T_out = sn.outputs[0], None
    else:
        tt = node("ShaderNodeMath", (360, -240), "T = 1 - a", operation="SUBTRACT")
        tt.inputs[0].default_value = 1.0
        links.new(a.outputs[0], tt.inputs[1])
        dm1 = node("ShaderNodeMath", (720, -420), "Draws - 1", operation="SUBTRACT")
        links.new(draws.outputs[0], dm1.inputs[0])
        dm1.inputs[1].default_value = 1.0
        f = node("ShaderNodeMath", (900, -300), "(Draws - 1) T", operation="MULTIPLY")
        links.new(dm1.outputs[0], f.inputs[0])
        links.new(tt.outputs[0], f.inputs[1])
        f1 = node("ShaderNodeMath", (1080, -300), "1 + (Draws - 1) T", operation="ADD")
        links.new(f.outputs[0], f1.inputs[0])
        f1.inputs[1].default_value = 1.0
        sn = node("ShaderNodeVectorMath", (1260, 0), "S x (1 + (Draws-1) T)",
                  operation="SCALE")
        links.new(S, sn.inputs[0])
        links.new(f1.outputs[0], sn.inputs[3])
        tn = node("ShaderNodeMath", (1080, -480), "T ^ Draws", operation="POWER")
        links.new(tt.outputs[0], tn.inputs[0])
        links.new(draws.outputs[0], tn.inputs[1])
        S_out, T_out = sn.outputs[0], tn.outputs[0]

    transp = node("ShaderNodeBsdfTransparent", (1440, -220), "the frame x T")
    if T_out is not None:
        links.new(T_out, transp.inputs[0])
    emis = node("ShaderNodeEmission", (1440, 0), "+ S")
    links.new(S_out, emis.inputs[0])
    emis.inputs[1].default_value = 1.0
    add = node("ShaderNodeAddShader", (1620, -80), "frame = S + T x frame")
    links.new(transp.outputs[0], add.inputs[0])
    links.new(emis.outputs[0], add.inputs[1])
    out = node("ShaderNodeOutputMaterial", (1800, -80), "out")
    links.new(add.outputs[0], out.inputs[0])
    return made


def build_sprite_material(name, image, cols, rows, uv_group, overbright=1.0,
                          additive=False, rect_attrs=False, blend=None,
                          draws=None):
    """rect_attrs: the uv_group is the per-frame-RECT variant - feed it the
    geometry-stored sprite_rect_* attributes instead of Frame/Columns/Rows."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    for attr, val in (("blend_method", "BLEND"),
                      ("surface_render_method", "BLENDED"),
                      ("use_backface_culling", False)):
        try:
            setattr(mat, attr, val)
        except Exception:
            pass

    a_frame = _nd(nt, "ShaderNodeAttribute", (-900, 160), "sprite_frame",
                  role="SEQUENCE", attribute_type="INSTANCER",
                  attribute_name="sprite_frame")
    a_alpha = _nd(nt, "ShaderNodeAttribute", (-900, -60), "sprite_alpha",
                  role="OPERATOR", attribute_type="INSTANCER",
                  attribute_name="sprite_alpha")
    # 🔴 COLOR RANDOM DID NOTHING FOR MONTHS AND THIS IS WHY: the geometry
    # stored `sprite_color` on every particle, faithfully, and the material
    # never read it. Nothing errored - the colour was computed, baked and
    # thrown away one node short of the shader. The rope tinted correctly the
    # whole time because it has its OWN material, which does read it, and
    # that difference is what made it look like a geometry bug.
    a_col = _nd(nt, "ShaderNodeAttribute", (-900, -280), "sprite_color",
                role="INITIALIZER", attribute_type="INSTANCER",
                attribute_name="sprite_color")

    uvg = _nd(nt, "ShaderNodeGroup", (-640, 160), "sheet lookup",
              role="SEQUENCE")
    uvg.node_tree = uv_group
    if rect_attrs:
        # Non-uniform sheet: the geometry stored this particle's exact frame
        # rectangle; the group just wants its corner and size.
        a_rmin = _nd(nt, "ShaderNodeAttribute", (-900, 820),
                     "sprite_rect_min", role="SEQUENCE",
                     attribute_type="INSTANCER",
                     attribute_name="sprite_rect_min")
        a_rscl = _nd(nt, "ShaderNodeAttribute", (-900, 1030),
                     "sprite_rect_scale", role="SEQUENCE",
                     attribute_type="INSTANCER",
                     attribute_name="sprite_rect_scale")
        _lk(nt, a_rmin, 1, uvg, 0)      # Vector out -> Corner
        _lk(nt, a_rscl, 1, uvg, 1)      # Vector out -> Size
    else:
        _lk(nt, a_frame, 2, uvg, 0)
        _sv(uvg, 1, float(cols))
        _sv(uvg, 2, float(rows))

    #  LINEAR, NOT CLOSEST. Closest made every sprite visibly pixelated next
    #  to SFM, which filters its sheets bilinearly - a 256px flare that looks
    #  smooth in Source turned into minecraft here. Linear is safe because
    #  the sheet-UV group insets the sampling window half a texel, so a
    #  boundary sample can never average in the neighbouring tile.
    tex = _nd(nt, "ShaderNodeTexImage", (-400, 160), "the sheet",
              role="RENDERER", interpolation="Linear", extension="CLIP")
    tex.image = image
    _lk(nt, uvg, 0, tex, 0)

    # ── FRAME BLENDING - the spritecard crossfade ────────────────────────
    #  SFM never snaps between sheet frames: each frame FADES into the next,
    #  which is what keeps an 8 fps smoke sheet looking liquid instead of
    #  stroboscopic. The geometry bakes which tile comes next
    #  (sprite_frame_next, same loop/hold law as the current one) and how
    #  far between them the particle is (sprite_frame_blend, 0..1); here the
    #  sheet is simply sampled a second time at the next tile and mixed.
    #
    #  "Blend Frames (0/1)" is the switch - ON by default, set it to 0 in
    #  this material to snap like a plain frame-hold. Systems built before
    #  this existed read a missing blend attribute as 0 and are unchanged.
    a_next = _nd(nt, "ShaderNodeAttribute", (-900, 380), "sprite_frame_next",
                 role="SEQUENCE", attribute_type="INSTANCER",
                 attribute_name="sprite_frame_next")
    a_blend = _nd(nt, "ShaderNodeAttribute", (-900, 600),
                  "sprite_frame_blend", role="SEQUENCE",
                  attribute_type="INSTANCER",
                  attribute_name="sprite_frame_blend")
    uvg2 = _nd(nt, "ShaderNodeGroup", (-640, 380), "sheet lookup · next",
               role="SEQUENCE")
    uvg2.node_tree = uv_group
    if rect_attrs:
        a_rmin2 = _nd(nt, "ShaderNodeAttribute", (-1140, 820),
                      "sprite_rect_min_next", role="SEQUENCE",
                      attribute_type="INSTANCER",
                      attribute_name="sprite_rect_min_next")
        a_rscl2 = _nd(nt, "ShaderNodeAttribute", (-1140, 1030),
                      "sprite_rect_scale_next", role="SEQUENCE",
                      attribute_type="INSTANCER",
                      attribute_name="sprite_rect_scale_next")
        _lk(nt, a_rmin2, 1, uvg2, 0)
        _lk(nt, a_rscl2, 1, uvg2, 1)
    else:
        _lk(nt, a_next, 2, uvg2, 0)
        _sv(uvg2, 1, float(cols))
        _sv(uvg2, 2, float(rows))
    tex2 = _nd(nt, "ShaderNodeTexImage", (-400, 440), "the sheet · next",
               role="RENDERER", interpolation="Linear", extension="CLIP")
    tex2.image = image
    _lk(nt, uvg2, 0, tex2, 0)

    blend_sw = _nd(nt, "ShaderNodeValue", (-640, 620), "Blend Frames (0/1)",
                   role="SEQUENCE")
    blend_sw.outputs[0].default_value = 1.0
    blend_f = _nd(nt, "ShaderNodeMath", (-400, 660), "fade x switch",
                  role="SEQUENCE", operation="MULTIPLY")
    _lk(nt, a_blend, 2, blend_f, 0)
    _lk(nt, blend_sw, 0, blend_f, 1)

    fcol = _nd(nt, "ShaderNodeMix", (-260, 340), "this frame -> next",
               role="SEQUENCE", data_type="RGBA", blend_type="MIX")
    _lk(nt, blend_f, 0, fcol, 0)
    _lk(nt, tex, 0, fcol, 6)
    _lk(nt, tex2, 0, fcol, 7)
    falpha = _nd(nt, "ShaderNodeMix", (-260, -260), "alpha, faded too",
                 role="SEQUENCE", data_type="FLOAT", factor_mode="UNIFORM")
    _lk(nt, blend_f, 0, falpha, 0)
    _lk(nt, tex, 1, falpha, 2)
    _lk(nt, tex2, 1, falpha, 3)

    # ── SHADING: SFM's own blend maths, measured (0.24.0) ────────────────
    #  Everything from here to the output is spritecard_output() - the
    #  measured SpriteCard formula, shared with every card material.
    bl = blend or legacy_blend(overbright, additive)
    shading = spritecard_output(nt, fcol.outputs[2], falpha.outputs[0],
                                a_col.outputs[0], a_alpha.outputs[2], bl,
                                n_draws=draws)

    note(nt, "PER-PARTICLE DATA  ·  read from the instancer", "SEQUENCE", """
These two Attribute nodes are the whole reason one material can show
different sequences on different particles.

THE RULE
  attribute_type = 'INSTANCER'  reads a value from the object doing the
  instancing - the point cloud - NOT from the instanced card.

  So the geometry side must store it on the POINT domain:
      store on POINT  ->  Instance on Points  ->  read as INSTANCER
  Storing on the INSTANCE domain instead gives you nothing at all.

sprite_frame = which tile of the sheet this particle is showing right now.
sprite_alpha = its fade in/out value, 0..1.
sprite_color = the tint Color Random rolled for it.

🔴 sprite_color WAS STORED BUT NEVER READ, so Color Random appeared to do
nothing on sprites and trails while working perfectly on the rope - which has
its own material and did read it. Nothing errored: the colour was computed,
baked onto the point and thrown away one node short of the shader. If a value
looks ignored, check that something actually CONSUMES it before assuming the
maths is wrong.
""", [a_frame, a_alpha, a_col])
    note(nt, "SHADING  ·  SFM's SpriteCard, measured", "RENDERER", SHADING_NOTE,
         [tex] + shading)
    from . import layout
    layout.apply_shader_layout(nt, mat.name)
    return mat


# ── geometry: a small stateless emitter ──────────────────────────────────────

def build_sprite_emitter_group(name, mat, sequences, cols, rows):
    """A small emitter: particles rise, fade in and out, and play a sequence.

    STATELESS on purpose - no simulation zone, no cache, no bake. Every
    particle's age is derived from the clock and its own index, so you can
    scrub the timeline in BOTH directions and it is always right. That makes
    it a preview you can trust; a real system would use a simulation zone."""
    ng = _group(name, "GeometryNodeTree")
    _sock(ng, "Geometry", "OUTPUT", "NodeSocketGeometry")
    _sock(ng, "Particles", "INPUT", "NodeSocketInt", 12, smin=1)
    _sock(ng, "Lifespan", "INPUT", "NodeSocketFloat", 5.0, smin=0.01)
    _sock(ng, "Fade In", "INPUT", "NodeSocketFloat", 0.5, smin=0.0)
    _sock(ng, "Fade Out", "INPUT", "NodeSocketFloat", 0.5, smin=0.0)
    _sock(ng, "Rise Speed", "INPUT", "NodeSocketFloat", 0.6)
    _sock(ng, "Spread", "INPUT", "NodeSocketFloat", 0.5, smin=0.0)
    _sock(ng, "Card Size", "INPUT", "NodeSocketFloat", 0.6, smin=0.001)
    _sock(ng, "Sheet FPS", "INPUT", "NodeSocketFloat", 24.0, smin=0.01)
    _sock(ng, "Seed", "INPUT", "NodeSocketInt", 0)
    gi = _nd(ng, "NodeGroupInput", (-2000, 0))
    go = _nd(ng, "NodeGroupOutput", (1700, 0))

    IN = {"Particles": 0, "Lifespan": 1, "Fade In": 2, "Fade Out": 3,
          "Rise Speed": 4, "Spread": 5, "Card Size": 6, "Sheet FPS": 7,
          "Seed": 8}

    # ---- EMITTER: one point per particle, staggered birth times ------------
    pts = _nd(ng, "GeometryNodePoints", (-1760, 240), "one point per particle",
              role="EMITTER")
    _lk(ng, gi, IN["Particles"], pts, 0)
    idx = _nd(ng, "GeometryNodeInputIndex", (-1760, 40), "particle number",
              role="EMITTER")
    count_f = _nd(ng, "ShaderNodeMath", (-1760, -120), "count as float",
                  role="EMITTER", operation="MAXIMUM")
    _lk(ng, gi, IN["Particles"], count_f, 0)
    _sv(count_f, 1, 1.0)
    interval = _nd(ng, "ShaderNodeMath", (-1580, -120),
                   "gap = lifespan / count", role="EMITTER",
                   operation="DIVIDE")
    _lk(ng, gi, IN["Lifespan"], interval, 0)
    _lk(ng, count_f, 0, interval, 1)
    birth = _nd(ng, "ShaderNodeMath", (-1400, 0), "birth = index x gap",
                role="EMITTER", operation="MULTIPLY")
    _lk(ng, idx, 0, birth, 0)
    _lk(ng, interval, 0, birth, 1)

    # ---- TIME: age, wrapped so the emitter runs forever --------------------
    time = _nd(ng, "GeometryNodeInputSceneTime", (-1760, 460), "the clock",
               role="TIME")
    since = _nd(ng, "ShaderNodeMath", (-1220, 300), "time - birth",
                role="TIME", operation="SUBTRACT")
    _lk(ng, time, 0, since, 0)
    _lk(ng, birth, 0, since, 1)
    age = _nd(ng, "ShaderNodeMath", (-1040, 300), "age = that % lifespan",
              role="TIME", operation="WRAP")
    _lk(ng, since, 0, age, 0)
    _lk(ng, gi, IN["Lifespan"], age, 1)
    _sv(age, 2, 0.0)
    # how many whole lives have passed - makes each life a NEW particle
    lives = _nd(ng, "ShaderNodeMath", (-1040, 120), "which life is this",
                role="TIME", operation="FLOOR")
    div_life = _nd(ng, "ShaderNodeMath", (-1220, 120), role="TIME",
                   operation="DIVIDE")
    _lk(ng, since, 0, div_life, 0)
    _lk(ng, gi, IN["Lifespan"], div_life, 1)
    _lk(ng, div_life, 0, lives, 0)
    pid = _nd(ng, "ShaderNodeMath", (-860, 120), "unique id per life",
              role="TIME", operation="MULTIPLY_ADD")
    _lk(ng, lives, 0, pid, 0)
    _sv(pid, 1, 977.0)
    _lk(ng, idx, 0, pid, 2)
    pid_i = _nd(ng, "FunctionNodeFloatToInt", (-680, 120), "as an integer",
                role="TIME")
    _lk(ng, pid, 0, pid_i, 0)

    # ---- INITIALIZER: things decided once, at birth ------------------------
    seq_pick = _nd(ng, "FunctionNodeRandomValue", (-480, -180),
                   "which sequence", role="INITIALIZER", data_type="INT")
    _sv(seq_pick, 0, 0)
    _sv(seq_pick, 1, len(sequences) - 1)
    _lk(ng, pid_i, 0, seq_pick, 2)
    _lk(ng, gi, IN["Seed"], seq_pick, 3)

    spread = _nd(ng, "FunctionNodeRandomValue", (-480, -420),
                 "sideways scatter", role="INITIALIZER",
                 data_type="FLOAT_VECTOR")
    _sv(spread, 0, (-1.0, -1.0, 0.0))
    _sv(spread, 1, (1.0, 1.0, 0.0))
    _lk(ng, pid_i, 0, spread, 2)
    _lk(ng, gi, IN["Seed"], spread, 3)
    spread_s = _nd(ng, "ShaderNodeVectorMath", (-260, -420), "x spread",
                   role="INITIALIZER", operation="SCALE")
    _lk(ng, spread, 0, spread_s, 0)
    _lk(ng, gi, IN["Spread"], spread_s, 3)

    # sequence -> (start, count, loops) lookup, built from the VTF's own table
    s0, c0, l0 = sequences[0]
    start_n = _nd(ng, "ShaderNodeValue", (-260, 120), "seq 0 start",
                  role="SEQUENCE")
    start_n.outputs[0].default_value = float(s0)
    count_n = _nd(ng, "ShaderNodeValue", (-260, 20), "seq 0 length",
                  role="SEQUENCE")
    count_n.outputs[0].default_value = float(c0)
    loop_n = _nd(ng, "ShaderNodeValue", (-260, -80),
                 f"seq 0 {'LOOPS' if l0 else 'plays once'}", role="SEQUENCE")
    loop_n.outputs[0].default_value = 1.0 if l0 else 0.0
    prev = [start_n, count_n, loop_n]
    seq_nodes = list(prev)
    for i, (si, ci, li) in enumerate(sequences[1:], start=1):
        eq = _nd(ng, "FunctionNodeCompare", (-80, -300 - i * 130),
                 f"is it sequence {i}?", role="SEQUENCE",
                 data_type="INT", operation="EQUAL")
        _lk(ng, seq_pick, 0, eq, 0)
        _sv(eq, 1, i)
        picked = []
        for j, (val, lbl) in enumerate(((float(si), "start"),
                                        (float(ci), "length"),
                                        (1.0 if li else 0.0,
                                         "LOOPS" if li else "plays once"))):
            sw = _nd(ng, "GeometryNodeSwitch", (100, 120 - j * 100 - i * 40),
                     f"seq {i} {lbl}", role="SEQUENCE", input_type="FLOAT")
            _lk(ng, eq, 0, sw, 0)
            _lk(ng, prev[j], 0, sw, 1)
            _sv(sw, 2, val)
            picked.append(sw)
        seq_nodes += [eq] + picked
        prev = picked
    seq_start, seq_count, seq_loops = prev

    # ---- OPERATOR: age -> frame, honouring the per-sequence loop flag ------
    played = _nd(ng, "ShaderNodeMath", (320, 300), "age x sheet fps",
                 role="OPERATOR", operation="MULTIPLY")
    _lk(ng, age, 0, played, 0)
    _lk(ng, gi, IN["Sheet FPS"], played, 1)
    floored = _nd(ng, "ShaderNodeMath", (500, 300), "whole frames",
                  role="OPERATOR", operation="FLOOR")
    _lk(ng, played, 0, floored, 0)
    last = _nd(ng, "ShaderNodeMath", (500, 140), "length - 1", role="OPERATOR",
               operation="SUBTRACT")
    _lk(ng, seq_count, 0, last, 0)
    _sv(last, 1, 1.0)
    held = _nd(ng, "ShaderNodeMath", (680, 380), "clamp: play once and hold",
               role="OPERATOR", operation="MINIMUM")
    _lk(ng, floored, 0, held, 0)
    _lk(ng, last, 0, held, 1)
    wrapped = _nd(ng, "ShaderNodeMath", (680, 200), "wrap: loop forever",
                  role="OPERATOR", operation="MODULO")
    _lk(ng, floored, 0, wrapped, 0)
    _lk(ng, seq_count, 0, wrapped, 1)
    is_loop = _nd(ng, "FunctionNodeCompare", (680, 20), "does it loop?",
                  role="SEQUENCE", data_type="FLOAT", operation="GREATER_THAN")
    _lk(ng, seq_loops, 0, is_loop, 0)
    _sv(is_loop, 1, 0.5)
    pick_mode = _nd(ng, "GeometryNodeSwitch", (880, 260), "loop or hold",
                    role="SEQUENCE", input_type="FLOAT")
    _lk(ng, is_loop, 0, pick_mode, 0)
    _lk(ng, held, 0, pick_mode, 1)
    _lk(ng, wrapped, 0, pick_mode, 2)
    tile = _nd(ng, "ShaderNodeMath", (1060, 300), "+ sequence start",
               role="SEQUENCE", operation="ADD")
    _lk(ng, pick_mode, 0, tile, 0)
    _lk(ng, seq_start, 0, tile, 1)

    # ---- OPERATOR: fade in / fade out --------------------------------------
    fin = _nd(ng, "ShaderNodeMapRange", (320, -160), "fade in", role="OPERATOR",
              clamp=True)
    _lk(ng, age, 0, fin, 0)
    _sv(fin, 1, 0.0)
    fin_safe = _nd(ng, "ShaderNodeMath", (140, -160), "never a zero window",
                   role="OPERATOR", operation="MAXIMUM")
    _lk(ng, gi, IN["Fade In"], fin_safe, 0)
    _sv(fin_safe, 1, 1e-4)
    _lk(ng, fin_safe, 0, fin, 2)
    _sv(fin, 3, 0.0)
    _sv(fin, 4, 1.0)

    fout_start = _nd(ng, "ShaderNodeMath", (140, -420),
                     "lifespan - fade out", role="OPERATOR",
                     operation="SUBTRACT")
    _lk(ng, gi, IN["Lifespan"], fout_start, 0)
    _lk(ng, gi, IN["Fade Out"], fout_start, 1)
    fout = _nd(ng, "ShaderNodeMapRange", (320, -420), "fade out",
               role="OPERATOR", clamp=True)
    _lk(ng, age, 0, fout, 0)
    _lk(ng, fout_start, 0, fout, 1)
    _lk(ng, gi, IN["Lifespan"], fout, 2)
    _sv(fout, 3, 1.0)
    _sv(fout, 4, 0.0)
    alpha = _nd(ng, "ShaderNodeMath", (540, -280), "fade in x fade out",
                role="OPERATOR", operation="MULTIPLY")
    _lk(ng, fin, 0, alpha, 0)
    _lk(ng, fout, 0, alpha, 1)

    # ---- OPERATOR: rise --------------------------------------------------
    rise = _nd(ng, "ShaderNodeMath", (320, -620), "height = speed x age",
               role="OPERATOR", operation="MULTIPLY")
    _lk(ng, gi, IN["Rise Speed"], rise, 0)
    _lk(ng, age, 0, rise, 1)
    up = _nd(ng, "ShaderNodeCombineXYZ", (500, -620), "straight up",
             role="OPERATOR")
    _lk(ng, rise, 0, up, 2)
    where = _nd(ng, "ShaderNodeVectorMath", (700, -560), "scatter + rise",
                role="OPERATOR", operation="ADD")
    _lk(ng, spread_s, 0, where, 0)
    _lk(ng, up, 0, where, 1)
    setpos = _nd(ng, "GeometryNodeSetPosition", (900, -40), "place it",
                 role="OPERATOR")
    _lk(ng, pts, 0, setpos, 0)
    _lk(ng, where, 0, setpos, 2)

    # ---- store on the POINT domain: this is what INSTANCER reads ----------
    st_frame = _nd(ng, "GeometryNodeStoreNamedAttribute", (1240, 40),
                   "sprite_frame  (POINT domain!)", role="SEQUENCE",
                   data_type="FLOAT", domain="POINT")
    _sv(st_frame, 2, "sprite_frame")
    _lk(ng, setpos, 0, st_frame, 0)
    _lk(ng, tile, 0, st_frame, 3)
    st_alpha = _nd(ng, "GeometryNodeStoreNamedAttribute", (1240, -160),
                   "sprite_alpha  (POINT domain!)", role="OPERATOR",
                   data_type="FLOAT", domain="POINT")
    _sv(st_alpha, 2, "sprite_alpha")
    _lk(ng, st_frame, 0, st_alpha, 0)
    _lk(ng, alpha, 0, st_alpha, 3)
    # 🔴 THE MATERIAL MULTIPLIES BY sprite_color, SO IT MUST EXIST. When the
    # material learned Color Random (tex colour x sprite_color), the RAS
    # emitters started storing the attribute - and this probe emitter did
    # not, so an unstored attribute read back (0,0,0) and every probe card
    # rendered BLACK. The shapes were perfect, which made it look like a
    # filtering or alpha bug. The probe has no Color Random, so its tint is
    # constant white - but it has to be STORED white, not left missing.
    st_col = _nd(ng, "GeometryNodeStoreNamedAttribute", (1240, -360),
                 "sprite_color = white  (POINT domain!)", role="INITIALIZER",
                 data_type="FLOAT_COLOR", domain="POINT")
    _sv(st_col, 2, "sprite_color")
    _lk(ng, st_alpha, 0, st_col, 0)
    _sv(st_col, 3, (1.0, 1.0, 1.0, 1.0))

    # ---- RENDERER ---------------------------------------------------------
    grid = _nd(ng, "GeometryNodeMeshGrid", (900, -900), "the sprite card",
               role="RENDERER")
    _lk(ng, gi, IN["Card Size"], grid, 0)
    _lk(ng, gi, IN["Card Size"], grid, 1)
    _sv(grid, 2, 2)
    _sv(grid, 3, 2)
    uvstore = _nd(ng, "GeometryNodeStoreNamedAttribute", (1080, -900),
                  'store its UVs as "UVMap"', role="RENDERER",
                  data_type="FLOAT2", domain="CORNER")
    _sv(uvstore, 2, "UVMap")
    _lk(ng, grid, 0, uvstore, 0)
    _lk(ng, grid, 1, uvstore, 3)
    setmat = _nd(ng, "GeometryNodeSetMaterial", (1260, -900),
                 "material goes HERE, before instancing", role="RENDERER")
    _lk(ng, uvstore, 0, setmat, 0)
    try:
        setmat.inputs[2].default_value = mat
    except Exception as exc:
        print(f"[HT_SPRITE]  set material: {exc}")
    upright = _nd(ng, "FunctionNodeAxisAngleToRotation", (1260, -680),
                  "stand the cards upright", role="RENDERER")
    _sv(upright, 0, (1.0, 0.0, 0.0))
    _sv(upright, 1, 1.5707963705062866)
    inst = _nd(ng, "GeometryNodeInstanceOnPoints", (1480, -100),
               "one card per particle", role="RENDERER")
    _lk(ng, st_col, 0, inst, 0)
    _lk(ng, setmat, 0, inst, 2)
    _lk(ng, upright, 0, inst, 5)
    _lk(ng, inst, 0, go, 0)

    # ---- the explanations --------------------------------------------------
    note(ng, "EMITTER  ·  where particles come from", "EMITTER", """
There is no simulation here, and that is deliberate.

Each particle gets a BIRTH TIME from its own index:
      gap   = lifespan / particle count
      birth = index x gap
so the particles are spread evenly through the lifespan and something is
always being born. Raise "Particles" for a denser stream.

WHY NO SIMULATION ZONE
  A sim zone has to be played forward from frame 1 and cached. This is
  stateless: every particle's state is computed from the clock alone, so you
  can scrub the timeline BACKWARDS and it is still correct. Perfect for a
  previewer. A real particle system would use a sim zone.
""", [pts, idx, count_f, interval, birth])

    note(ng, "TIME  ·  age, and what counts as a new particle", "TIME", """
age = (time - birth) wrapped by lifespan
  so each particle repeatedly lives 0 -> lifespan -> 0 -> lifespan ...

"which life is this" counts how many whole lifespans have gone by. It is
folded into the random seed (id = life x 977 + index) so that every time a
particle is reborn it becomes a genuinely NEW particle - new sequence, new
scatter. Without this, particle 3 would draw the same sequence forever.
""", [time, since, age, div_life, lives, pid, pid_i])

    note(ng, "INITIALIZER  ·  decided once, at birth", "INITIALIZER", """
Values that must NOT change while a particle is alive: which sequence it
plays, and where it scattered to. They depend only on the particle id, so
they stay put for that particle's whole life.

Random Value socket order in Blender 5.2 is Min=0, Max=1, ID=2, Seed=3 for
EVERY data type. Feeding the id into ID is what makes particles differ from
each other; Seed shifts the whole batch.
""", [seq_pick, spread, spread_s])

    note(ng, "SEQUENCE TABLE  ·  read from the VTF, not guessed", "SEQUENCE", """
The .vtf carries its own sequence table, so we never guess the layout:

""" + "\n".join(
        f"    sequence {i}:  starts at tile {s:<4} {c:>3} frames   "
        f"{'LOOPS' if l else 'plays once and holds'}"
        for i, (s, c, l) in enumerate(sequences)) + """

Each row is a Switch: "if the picked sequence is N, use these numbers,
otherwise pass through what the previous Switch chose". Chaining them gives a
lookup table with as many entries as the sheet has.
""", seq_nodes)

    note(ng, "OPERATOR  ·  which frame, and looping vs holding", "OPERATOR", """
frame = floor(age x Sheet FPS)

Then the PER-SEQUENCE loop flag decides what happens at the end:
    LOOPS      -> frame % length      (wraps round to the start forever)
    plays once -> min(frame, length-1)  (stops on the last frame and holds)

This flag comes out of the VTF itself. Across 518 real sheets, 895 sequences
clamp and 167 loop - so guessing one behaviour for everything would be wrong
about 16% of the time.

Finally the sequence's start tile is added, turning a frame number inside the
sequence into an absolute tile index in the sheet.
""", [played, floored, last, held, wrapped, is_loop, pick_mode, tile])

    note(ng, "OPERATOR  ·  fade in / fade out", "OPERATOR", """
Two Map Ranges multiplied together:
    fade in  : age 0 -> Fade In        gives alpha 0 -> 1
    fade out : lifespan-Fade Out -> lifespan   gives alpha 1 -> 0

WATCH OUT: a Map Range whose from_min equals from_max returns 0, so a zero
length fade would make every particle invisible. "never a zero window" floors
the fade time at 0.0001 so "no fade in" means "already visible".
""", [fin_safe, fin, fout_start, fout, alpha])

    note(ng, "OPERATOR  ·  movement", "OPERATOR", """
Deliberately trivial: sideways scatter chosen at birth, plus a steady rise of
(Rise Speed x age) upward. No gravity, no drag, no forces - this is a sprite
previewer, and anything more would hide sheet bugs behind nice motion.
""", [rise, up, where, setpos])

    note(ng, "RENDERER  ·  one card per particle", "RENDERER", """
THE THREE RULES, ALL LEARNED THE HARD WAY

1. Mesh Grid's UV is an ANONYMOUS output socket, not a named layer. Store it
   as "UVMap" or the shader has no UVs at all, samples one transparent corner
   texel, and every sprite renders INVISIBLE - which looks exactly like a
   broken material and is not one.

2. Set Material must go on the SOURCE card, BEFORE Instance on Points.
   Applying it after instancing does nothing.

3. The two Store Named Attribute nodes above write on the POINT domain. The
   shader reads them with attribute_type='INSTANCER', which reads from the
   instancER (these points) - not from the instances. Storing on the INSTANCE
   domain silently gives the shader nothing.
""", [grid, uvstore, setmat, upright, inst])
    return ng


# kept so older callers still work
build_sprite_test_group = build_sprite_emitter_group
