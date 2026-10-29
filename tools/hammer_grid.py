# =============================================================================
#  tools/hammer_grid.py  -  paint a real Hammer / SFM unit grid on the floor
# =============================================================================
#
#  WHY THIS EXISTS. Every argument about particle scale so far has been someone
#  guessing what a number means. This removes the guessing: it draws SOURCE'S
#  OWN GRID at 1 Blender Unit = 1 Hammer Unit, so a distance in a .pcf can be
#  read straight off the floor.
#
#      1 HU   faint grey        the smallest thing Hammer snaps to
#      8 HU   grey              Hammer's usual working snap
#      16 HU  muted orange      a wall panel
#      64 HU  bright orange     a room
#      X / Y  brightest orange  world origin
#
#  Reference height: a TF2 Scout imports at 81.6924 units. If your effect does
#  not look right next to that empty, the effect is wrong, not the grid.
#
#  ONE plane + ONE procedural shader. Grid lines are shader maths, not
#  geometry, so the extent costs nothing and nothing shows up in the outliner
#  except the plane and two markers.
#
#  THE SCALE POINT. This deliberately does NOT convert to metres. Source works
#  in Hammer units and so should we while translating an effect; a system built
#  against this grid wants Scale = 1.0, not the 0.01905 metres-per-unit default.
# =============================================================================

import bpy

from .sprite_nodes import _nd, _lk, _sv


TAG = "[HT_GRID]"

COLLECTION_NAME = "Hammer Grid"
OBJECT_NAME = "SFM Hammer Grid"
MATERIAL_NAME = "SFM Hammer Grid"

# Source's actual grid hierarchy, in Hammer units.
MINOR_STEP = 1.0
MEDIUM_STEP = 8.0
MAJOR_STEP = 16.0
SUPER_STEP = 64.0
CHECKER_STEP = 16.0

# Line thickness, also in Hammer units. Thickness does not affect spacing.
MINOR_WIDTH = 0.030
MEDIUM_WIDTH = 0.060
MAJOR_WIDTH = 0.100
SUPER_WIDTH = 0.180
AXIS_WIDTH = 0.260

SCOUT_HEIGHT = 81.6924

# ── Valve orange / gray ──────────────────────────────────────────────────────
BACKGROUND_A = (0.060, 0.064, 0.070, 1.0)
BACKGROUND_B = (0.078, 0.082, 0.088, 1.0)
MINOR_COLOR = (0.125, 0.132, 0.140, 1.0)
MEDIUM_COLOR = (0.235, 0.240, 0.245, 1.0)
MAJOR_COLOR = (0.490, 0.255, 0.095, 1.0)   # restrained old-Hammer orange
SUPER_COLOR = (0.920, 0.365, 0.055, 1.0)   # strong Valve orange
AXIS_COLOR = (1.000, 0.520, 0.080, 1.0)
EMISSION_STRENGTH = 0.85

# Frame tints, by what the maths in them is for.
FRAME_COORD = (0.20, 0.26, 0.30)
FRAME_GRID = (0.33, 0.22, 0.12)
FRAME_COLOR = (0.28, 0.24, 0.20)


def _frame(nt, title, body, nodes):
    """Same self-documenting frame as the particle graphs, Valve-tinted.

    NodeFrame.text takes a real Text datablock and Blender draws it inside the
    frame, so whoever opens this in two years can read why it is built this
    way instead of reverse-engineering forty Math nodes."""
    f = nt.nodes.new("NodeFrame")
    f.label = title
    f.use_custom_color = True
    f.color = FRAME_GRID
    f.label_size = 16
    name = f"{MATERIAL_NAME} · {title}"
    txt = bpy.data.texts.get(name) or bpy.data.texts.new(name)
    txt.clear()
    txt.write(body.strip("\n"))
    try:
        f.text = txt
    except Exception as exc:
        print(f"{TAG}  frame text: {exc}")
    f.shrink = True
    for n in nodes:
        n.parent = f
    return f


def _mix(nt, under, over_color, factor, loc, label):
    """Paint `over_color` on top of `under` wherever `factor` is 1.

    ShaderNodeMix, not the legacy MixRGB node. Its sockets are shared between
    every data type, so the COLOUR ones are A=6, B=7 and the colour Result is
    output 2 - probed in Blender, not guessed."""
    m = _nd(nt, "ShaderNodeMix", loc, label, data_type="RGBA",
            factor_mode="UNIFORM")
    m.use_custom_color = True
    m.color = FRAME_COLOR
    _lk(nt, factor[0], factor[1], m, 0)
    _lk(nt, under[0], under[1], m, 6)
    _sv(m, 7, over_color)
    return (m, 2)


def _line_mask(nt, coord, step, width, loc, label):
    """A line every `step` units, CENTRED on the multiple.

        coord / step  ->  FRACT  ->  min(f, 1 - f)  <  (width / 2) / step

    Taking min(f, 1-f) is what centres it. A plain "fract < width" test draws
    the line entirely on the positive side of each multiple, which looks fine
    at the origin and visibly wrong once you cross into negative coordinates -
    the grid stops being symmetrical about X=0."""
    x, y = loc
    div = _nd(nt, "ShaderNodeMath", (x, y), f"{label} / {step:g}",
              operation="DIVIDE")
    _lk(nt, coord[0], coord[1], div, 0)
    _sv(div, 1, step)

    fr = _nd(nt, "ShaderNodeMath", (x + 190, y), f"{label} fract",
             operation="FRACT")
    _lk(nt, div, 0, fr, 0)

    inv = _nd(nt, "ShaderNodeMath", (x + 190, y - 120), f"{label} 1 - fract",
              operation="SUBTRACT")
    _sv(inv, 0, 1.0)
    _lk(nt, fr, 0, inv, 1)

    near = _nd(nt, "ShaderNodeMath", (x + 380, y - 40),
               f"{label} distance to the line", operation="MINIMUM")
    _lk(nt, fr, 0, near, 0)
    _lk(nt, inv, 0, near, 1)

    hit = _nd(nt, "ShaderNodeMath", (x + 570, y - 40), f"{label} on a line?",
              operation="LESS_THAN")
    _lk(nt, near, 0, hit, 0)
    _sv(hit, 1, (width * 0.5) / step)

    return (hit, 0), [div, fr, inv, near, hit]


def _axis_mask(nt, coord, loc, label):
    """The world axis itself: |coord| < half the axis width."""
    x, y = loc
    a = _nd(nt, "ShaderNodeMath", (x, y), f"|{label}|", operation="ABSOLUTE")
    _lk(nt, coord[0], coord[1], a, 0)
    m = _nd(nt, "ShaderNodeMath", (x + 190, y), f"{label} = 0 ?",
            operation="LESS_THAN")
    _lk(nt, a, 0, m, 0)
    _sv(m, 1, AXIS_WIDTH * 0.5)
    return (m, 0), [a, m]


def build_material(checker=True):
    mat = bpy.data.materials.get(MATERIAL_NAME) \
        or bpy.data.materials.new(MATERIAL_NAME)
    mat.use_nodes = True
    mat.diffuse_color = BACKGROUND_A
    nt = mat.node_tree
    nt.nodes.clear()

    # ── world position IS Hammer units ───────────────────────────────────
    geo = _nd(nt, "ShaderNodeNewGeometry", (-1500, 500), "world position")
    sep = _nd(nt, "ShaderNodeSeparateXYZ", (-1300, 500), "X / Y in Hammer units")
    _lk(nt, geo, geo.outputs.find("Position"), sep, 0)
    xs, ys = (sep, 0), (sep, 1)
    _frame(nt, "WORLD POSITION = HAMMER UNITS", """
The shader reads the plane's WORLD position and treats the number as Hammer
units directly, because that is the whole convention this grid exists to
enforce: 1 Blender Unit = 1 Hammer Unit.

Nothing here is divided by 0.01905. If you build a particle system against
this grid, its Scale should be 1.0.
""", [geo, sep])

    # ── background ───────────────────────────────────────────────────────
    rgb = _nd(nt, "ShaderNodeRGB", (-670, 880), "floor")
    rgb.outputs[0].default_value = BACKGROUND_A
    under = (rgb, 0)
    bg_nodes = [rgb]

    if checker:
        dx = _nd(nt, "ShaderNodeMath", (-1240, 780), "X / 16",
                 operation="DIVIDE")
        _lk(nt, xs[0], xs[1], dx, 0)
        _sv(dx, 1, CHECKER_STEP)
        fx = _nd(nt, "ShaderNodeMath", (-1050, 780), "X cell",
                 operation="FLOOR")
        _lk(nt, dx, 0, fx, 0)

        dy = _nd(nt, "ShaderNodeMath", (-1240, 640), "Y / 16",
                 operation="DIVIDE")
        _lk(nt, ys[0], ys[1], dy, 0)
        _sv(dy, 1, CHECKER_STEP)
        fy = _nd(nt, "ShaderNodeMath", (-1050, 640), "Y cell",
                 operation="FLOOR")
        _lk(nt, dy, 0, fy, 0)

        add = _nd(nt, "ShaderNodeMath", (-860, 710), "X + Y", operation="ADD")
        _lk(nt, fx, 0, add, 0)
        _lk(nt, fy, 0, add, 1)
        # WRAP, NOT MODULO. Blender's MODULO is truncated, so cell -3 gives
        # -1 rather than 1; the mix factor then clamps to zero and the checker
        # silently disappears everywhere south-west of the origin. WRAP folds
        # into [0, 2) for negative inputs too.
        odd = _nd(nt, "ShaderNodeMath", (-670, 710), "every other one",
                  operation="WRAP")
        _lk(nt, add, 0, odd, 0)
        _sv(odd, 1, 2.0)
        _sv(odd, 2, 0.0)

        under = _mix(nt, under, BACKGROUND_B, (odd, 0), (-480, 780),
                     "16 HU tiles")
        bg_nodes += [dx, fx, dy, fy, add, odd, under[0]]
    _frame(nt, "FLOOR", """
A barely-there 16 HU checker so the floor reads as a surface rather than a
void, without competing with the grid lines drawn on top of it.
""", bg_nodes)

    # ── the four grid levels ─────────────────────────────────────────────
    levels = []
    for i, (step, width, label) in enumerate((
            (MINOR_STEP, MINOR_WIDTH, "1 HU"),
            (MEDIUM_STEP, MEDIUM_WIDTH, "8 HU"),
            (MAJOR_STEP, MAJOR_WIDTH, "16 HU"),
            (SUPER_STEP, SUPER_WIDTH, "64 HU"))):
        top = 300 - i * 620
        mx, nx = _line_mask(nt, xs, step, width, (-1150, top), f"{label} X")
        my, ny = _line_mask(nt, ys, step, width, (-1150, top - 260),
                            f"{label} Y")
        both = _nd(nt, "ShaderNodeMath", (-380, top - 130), f"{label} grid",
                   operation="MAXIMUM")
        _lk(nt, mx[0], mx[1], both, 0)
        _lk(nt, my[0], my[1], both, 1)
        levels.append(((both, 0), nx + ny + [both]))

    _frame(nt, "HAMMER GRID HIERARCHY  ·  1 / 8 / 16 / 64", """
Source's real snap hierarchy, not a decorative subdivision:

    1 HU    the finest snap Hammer offers
    8 HU    what most brushwork is actually built on
    16 HU   a wall panel
    64 HU   a room

X and Y masks are combined with MAXIMUM, so a line is drawn where EITHER
axis lands on a multiple - that is what makes it a grid rather than a set of
stripes.
""", [n for _m, ns in levels for n in ns])

    # ── world axes ───────────────────────────────────────────────────────
    ax, an = _axis_mask(nt, xs, (100, 340), "X")
    ay, bn = _axis_mask(nt, ys, (100, 180), "Y")
    axes = _nd(nt, "ShaderNodeMath", (480, 260), "X or Y axis",
               operation="MAXIMUM")
    _lk(nt, ax[0], ax[1], axes, 0)
    _lk(nt, ay[0], ay[1], axes, 1)
    _frame(nt, "WORLD ORIGIN", """
X=0 and Y=0 drawn thickest and brightest. Source effects are authored around
a control point sitting at the origin, so being able to see it matters.
""", an + bn + [axes])

    # ── paint them in order, faintest first ──────────────────────────────
    painted = []
    current = under
    for (mask, _ns), colour, label in zip(
            levels,
            (MINOR_COLOR, MEDIUM_COLOR, MAJOR_COLOR, SUPER_COLOR),
            ("1 HU", "8 HU", "16 HU", "64 HU")):
        current = _mix(nt, current, colour, mask, (760 + len(painted) * 200,
                                                   350), f"paint {label}")
        painted.append(current[0])
    current = _mix(nt, current, AXIS_COLOR, (axes, 0),
                   (760 + len(painted) * 200, 350), "paint the axes")
    painted.append(current[0])
    _frame(nt, "PAINT ORDER  ·  faintest first", """
Each level is painted OVER the previous one, so where a 64 HU line and a 1 HU
line coincide - which is every 64 units - the important one wins. Reversing
this order gives a grid where the coarse lines vanish at every intersection.
""", painted)

    emit = _nd(nt, "ShaderNodeEmission", (1900, 350), "unlit, like an editor")
    _lk(nt, current[0], current[1], emit, 0)
    _sv(emit, 1, EMISSION_STRENGTH)
    out = _nd(nt, "ShaderNodeOutputMaterial", (2120, 350))
    _lk(nt, emit, 0, out, 0)
    return mat


def build(extent=256.0, checker=True, markers=True, set_units=True,
          hide_in_render=True):
    """Stand the grid up. Returns (object, info)."""
    scene = bpy.context.scene

    # Remove the previous one first, or a second run leaves two coplanar
    # planes z-fighting and it looks like the shader is broken.
    old_coll = bpy.data.collections.get(COLLECTION_NAME)
    if old_coll is not None:
        for obj in list(old_coll.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(old_coll)

    from ..operators.op_vtf import ROOT_COLLECTION
    root = bpy.data.collections.get(ROOT_COLLECTION) \
        or bpy.data.collections.new(ROOT_COLLECTION)
    if root.name not in scene.collection.children:
        try:
            scene.collection.children.link(root)
        except Exception:
            pass
    coll = bpy.data.collections.new(COLLECTION_NAME)
    root.children.link(coll)

    e = float(extent)
    mesh = bpy.data.meshes.new(OBJECT_NAME + " mesh")
    mesh.from_pydata([(-e, -e, 0.0), (e, -e, 0.0), (e, e, 0.0), (-e, e, 0.0)],
                     [], [(0, 1, 2, 3)])
    mesh.update()
    obj = bpy.data.objects.new(OBJECT_NAME, mesh)
    coll.objects.link(obj)

    # The plane must stay at scale 1: the shader reads WORLD position, so
    # scaling the object would stretch the maths and every line would land on
    # the wrong number while still looking like a tidy grid.
    obj.scale = (1.0, 1.0, 1.0)
    obj.hide_render = bool(hide_in_render)

    mat = build_material(checker=checker)
    obj.data.materials.append(mat)

    made = [obj]
    if markers:
        origin = bpy.data.objects.new("0,0,0", None)
        origin.empty_display_type = "PLAIN_AXES"
        origin.empty_display_size = 8.0
        coll.objects.link(origin)
        made.append(origin)

        scout = bpy.data.objects.new(
            f"TF2 Scout · {SCOUT_HEIGHT:.4g} HU tall", None)
        scout.empty_display_type = "SINGLE_ARROW"
        scout.empty_display_size = SCOUT_HEIGHT
        scout.show_name = True          # the number is the point of the marker
        coll.objects.link(scout)
        made.append(scout)

    if set_units:
        # Blender must stop claiming these are metres, or every readout in the
        # N panel disagrees with the grid you are looking at.
        try:
            scene.unit_settings.system = "NONE"
        except Exception as exc:
            print(f"{TAG}  unit system: {exc}")

    print(f"{TAG}  {int(2 * e)} x {int(2 * e)} HU grid, "
          f"1 / 8 / 16 / 64 HU, Scout at {SCOUT_HEIGHT} HU")
    return obj, {"extent": e, "objects": len(made), "units_set": set_units}


LINE_MATERIAL_NAME = "SFM Grid Lines"


def build_line_material():
    """3.0.0: plain white, unlit, slightly see-through - the lines are the only geometry, so everything between
    them is empty and a particle under the grid shows."""
    mat = bpy.data.materials.get(LINE_MATERIAL_NAME) or bpy.data.materials.new(LINE_MATERIAL_NAME)
    mat.diffuse_color = (0.92, 0.92, 0.92, 0.8)          # Solid mode draws this
    if mat.node_tree is None:
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (1.0, 1.0, 1.0, 1.0)
    emit.inputs["Strength"].default_value = 1.0
    clear = nt.nodes.new("ShaderNodeBsdfTransparent")
    mix = nt.nodes.new("ShaderNodeMixShader")
    mix.inputs["Fac"].default_value = 0.8
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    emit.location, clear.location, mix.location, out.location = (-300, -60), (-300, 120), (-80, 40), (140, 40)
    nt.links.new(clear.outputs[0], mix.inputs[1])
    nt.links.new(emit.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    for attr, value in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
        try:
            setattr(mat, attr, value)
        except Exception:
            pass
    return mat


def build_lines(extent=128.0, spacing=16.0, width=0.35, markers=False, set_units=True, hide_in_render=True):
    """3.0.0: thin white strips along every
    `spacing` units out to `extent`, nothing between them. Returns (object, info)."""
    scene = bpy.context.scene
    old_coll = bpy.data.collections.get(COLLECTION_NAME)
    if old_coll is not None:
        for obj in list(old_coll.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(old_coll)
    from ..operators.op_vtf import ROOT_COLLECTION
    root = bpy.data.collections.get(ROOT_COLLECTION) or bpy.data.collections.new(ROOT_COLLECTION)
    if root.name not in scene.collection.children:
        try:
            scene.collection.children.link(root)
        except Exception:
            pass
    coll = bpy.data.collections.new(COLLECTION_NAME)
    root.children.link(coll)

    e, step, hw = float(extent), max(1e-3, float(spacing)), max(1e-4, float(width)) * 0.5
    n = max(1, int(round(e / step)))
    e = n * step
    verts, faces = [], []
    for i in range(-n, n + 1):
        t = i * step
        for quad in (((t - hw, -e), (t + hw, -e), (t + hw, e), (t - hw, e)),
                     ((-e, t - hw), (e, t - hw), (e, t + hw), (-e, t + hw))):
            b = len(verts)
            verts += [(x, y, 0.0) for x, y in quad]
            faces.append((b, b + 1, b + 2, b + 3))
    mesh = bpy.data.meshes.new(OBJECT_NAME + " mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(OBJECT_NAME, mesh)
    coll.objects.link(obj)
    obj.hide_render = bool(hide_in_render)
    obj.data.materials.append(build_line_material())
    made = [obj]
    if markers:
        origin = bpy.data.objects.new("0,0,0", None)
        origin.empty_display_type = "PLAIN_AXES"
        origin.empty_display_size = 8.0
        coll.objects.link(origin)
        scout = bpy.data.objects.new(f"TF2 Scout · {SCOUT_HEIGHT:.4g} HU tall", None)
        scout.empty_display_type = "SINGLE_ARROW"
        scout.empty_display_size = SCOUT_HEIGHT
        scout.show_name = True
        coll.objects.link(scout)
        made += [origin, scout]
    if set_units:
        try:
            scene.unit_settings.system = "NONE"
        except Exception as exc:
            print(f"{TAG}  unit system: {exc}")
    print(f"{TAG}  {int(2 * e)} x {int(2 * e)} HU grid, {step:g} HU squares, lines {2 * hw:g} HU")
    return obj, {"extent": e, "objects": len(made), "units_set": set_units}


def remove():
    """Take it away again. Returns how many objects went."""
    coll = bpy.data.collections.get(COLLECTION_NAME)
    if coll is None:
        return 0
    n = len(coll.objects)
    for obj in list(coll.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    bpy.data.collections.remove(coll)
    mat = bpy.data.materials.get(MATERIAL_NAME)
    if mat is not None and mat.users == 0:
        bpy.data.materials.remove(mat)
    return n
