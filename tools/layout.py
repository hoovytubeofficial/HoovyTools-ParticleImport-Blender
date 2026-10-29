# =============================================================================
#  tools/layout.py  -  make a node graph READABLE
# =============================================================================
#
#  A graph nobody can read is a graph nobody can fix, and these graphs are
#  meant to be learned from. Three separate problems, three separate passes -
#  none of them touches what the graph DOES.
#
#  1. LOOSE NODES. A node wired to nothing is a leftover. It is not
#     documentation, it is a question the reader has to answer before they can
#     trust anything else on screen.
#
#  2. OVERLAPPING FRAMES. Two boxes on top of each other read as one broken
#     box. Frames are moved apart WHOLE - a frame's children are stored
#     relative to it, so moving the frame moves the section without disturbing
#     a single hand-placed node inside it.
#
#  3. FRAME TEXT UNDER THE NODES. `NodeFrame.text` draws from the TOP of the
#     frame downwards, and Blender reserves NO space for it - so with the
#     frame shrink-wrapped around its children, every line lands behind a
#     node. That is why the explanations were unreadable. The fix is to stop
#     shrink-wrapping: give the frame an explicit size with a text band at the
#     top, and push the children below it.
#
#  🔴 A frame with `shrink = True` recomputes its own size from its children
#  every draw, so ANY size set here is thrown away. Reserving headroom means
#  turning shrink OFF - it is not an aesthetic flag, it is the whole mechanism.
#
#  COLOUR IS INFORMATION, NOT DECORATION
#  -------------------------------------
#  The palette below is one hue per ROLE, at a shared saturation and value, so
#  the sections read as a family rather than a paint chart. Hues are spaced
#  around the wheel far enough to tell apart at a glance and kept dark enough
#  to sit under white node text all day:
#
#      time 170  ·  emitter 40  ·  initializer 108  ·  operator 15
#      sequence 292  ·  renderer 248  ·  children 65  ·  plumbing grey
#  (the full table with saturations is _HUES below - THAT is the truth)
#
#  Warm hues (emitter, operator) are the things that CHANGE; cool hues (time,
#  renderer, children) are the things that are READ. Green sits between them,
#  for values decided once at birth. That is the whole system.
# =============================================================================

import colorsys


# ── the palette ──────────────────────────────────────────────────────────────
#  (hue in degrees, saturation, value) - one place, so a tweak moves the whole
#  family together instead of drifting one node group at a time.

#  🔴 THE KEY IS THE SFM SECTION, and that is the whole point of the palette.
#  A colour is only information if it means the same thing everywhere, so
#  these are named after the sections in the modifier - CONTROL POINTS,
#  RENDERER, EMITTER - not after some internal notion of what a node does.
#  Before this, the CONTROL POINTS frame was painted with the "plumbing" grey
#  and the sections did not line up with the panels at all, which is exactly
#  why the palette read as random.
#  🔴 EVERY SECTION IS A DIFFERENT COLOUR, and that used to be less true than
#  it looked. CONTROL POINTS and TIME were BOTH hue 195, and EMITTER /
#  OPERATOR / FORCE GENERATOR sat inside 30 degrees of each other - so half the
#  graph was the same warm brown and the sections did not separate at a glance.
#  The hues below are spread around the wheel with no two sections closer than
#  25 degrees, which is the point at which they stop reading as one family.
#
#  ⚠️ MEASURED, NOT ASSUMED - the first "respread" table still had OPERATOR 12
#  against EMITTER 33, a 21 degree gap, and the +11 nudge on a REPEATED
#  operator block then landed at 23: TEN degrees from the emitter, so the one
#  frame whose colour had to say "second OPERATOR" said "EMITTER" instead.
#  Every clockwise gap below is now >= 25, which also guarantees a +/-11
#  nudged repeat stays nearer its OWN base (11) than any neighbour (>= 14).
_HUES = {
    # the frame of reference everything hangs off - cool, calm, structural
    "CONTROL POINTS":   (196, 0.36, 0.31),
    "SYSTEM PROPERTIES": (222, 0.22, 0.28),
    "TIME":             (170, 0.30, 0.30),
    # WARM = it changes. birth, then per-frame change, then forces.
    "EMITTER":          (40,  0.40, 0.33),
    "OPERATOR":         (15,  0.38, 0.32),
    "FORCE GENERATOR":  (350, 0.32, 0.31),
    "CONSTRAINT":       (320, 0.28, 0.29),
    # GREEN = decided once, at birth, and never again.
    "INITIALIZER":      (108, 0.32, 0.29),
    # COOL = it is read, not changed.
    "RENDERER":         (248, 0.32, 0.33),
    "SEQUENCE":         (292, 0.30, 0.31),
    "CHILDREN":         (65,  0.34, 0.30),
    "OUTPUT":           (0,   0.00, 0.27),
}

# The sections that are not roles in their own right still have to land
# somewhere sensible rather than falling through to grey.
_ALIAS = {
    "FORCE": "FORCE GENERATOR",
    "CONTROL POINT": "CONTROL POINTS",
    "SYSTEM": "SYSTEM PROPERTIES",
}

# 🔴 NODES ARE SATURATED, FRAMES ARE NOT - and the node colour IS the icon
# colour, by construction. The palette's original values (~0.3) were authored
# as dim surfaces, and on the dark theme they read as "slightly tinted grey":
# the recolour pass ran and nobody could see it. Now:
#
#     NODES   icon_rgb() verbatim - the exact colours of the sidebar's
#             sys_properties_*.png icons, bright and saturated
#     FRAMES  same hue, saturation cut nearly in half, value pinned dark -
#             a muted ground the vivid nodes sit ON, not compete with
FRAME_SAT_MUL = 0.55
FRAME_VAL = 0.34


def rgb(role, frame=False):
    key = str(role).upper()
    key = _ALIAS.get(key, key)
    h, s, _v = _HUES.get(key, _HUES["OUTPUT"])
    if frame:
        return colorsys.hsv_to_rgb(h / 360.0, s * FRAME_SAT_MUL, FRAME_VAL)
    return icon_rgb(key)          # nodes wear the icon colours, verbatim


def role_colours(frame=False):
    return {name: rgb(name, frame) for name in _HUES}


def icon_rgb(role):
    """The role's hue at ICON strength - same wheel, punchy enough for 32px.

    Node bodies sit at value ~0.3 so they read as surfaces behind sockets;
    a 32px icon at that value is a smudge. Same hue, saturation lifted,
    value pinned high - which is what keeps the sidebar icons, the node
    colours and any future recolour pass all provably ONE palette: every
    one of them derives from _HUES and nowhere else."""
    key = _ALIAS.get(str(role).upper(), str(role).upper())
    h, s, v = _HUES.get(key, _HUES["OUTPUT"])
    return colorsys.hsv_to_rgb(h / 360.0, min(1.0, s * 1.7 + 0.10), 0.86)


# ── the gradient ─────────────────────────────────────────────────────────────
#
#  🔴 A SECTION IS A GRADIENT, NOT A FLAT BLOCK. Fifty nodes painted one exact
#  colour is a wall: you can see where the section starts and ends and nothing
#  else. Ramping VALUE across the section - dark where the data comes in,
#  bright where it leaves - makes the direction of flow visible from zoomed
#  out, at no cost to the meaning, because the HUE still says which section it
#  is. Colour by role stays exactly as it was; this only varies the brightness
#  along the way.
#
#  Kept deliberately narrow. A ramp wide enough to be pretty is wide enough to
#  read as two different sections, which is the one thing the palette exists to
#  prevent.
#  Ramp bounds picked so the BRIGHT node base (0.86) never clips to white:
#  0.72 x 0.86 = 0.62 on the input side, 1.08 x 0.86 = 0.93 at the output.
GRAD_LOW = 0.72          # value multiplier at a section's input side
GRAD_HIGH = 1.08         # ...and at its output side
GRAD_SAT = 0.14          # saturation lifts slightly downstream too


def gradient_rgb(role, t, frame=False):
    """The role's colour, ramped by `t` (0 = input side, 1 = output side)."""
    key = str(role).upper()
    key = _ALIAS.get(key, key)
    h, s, _v = _HUES.get(key, _HUES["OUTPUT"])
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    if frame:
        return colorsys.hsv_to_rgb(h / 360.0, s * FRAME_SAT_MUL, FRAME_VAL)
    #  ramp AROUND the icon-strength base, so the section still reads as one
    #  saturated family with a visible left-to-right flow
    s2 = min(1.0, s * 1.7 + 0.10)
    v2 = 0.86 * (GRAD_LOW + (GRAD_HIGH - GRAD_LOW) * t)
    s2 *= 1.0 - GRAD_SAT * 0.5 + GRAD_SAT * t
    return colorsys.hsv_to_rgb(h / 360.0, min(s2, 1.0), min(v2, 1.0))


def _role_of(node):
    """Which palette entry a node is already painted with, by nearest hue.

    The builders set `role=` at construction and that is the source of truth;
    this reads the colour back rather than making every builder pass its role
    twice. Nearest-hue because float round-tripping through RGB is not exact."""
    if not node.use_custom_color:
        return None
    try:
        h, _s, _v = colorsys.rgb_to_hsv(*tuple(node.color)[:3])
    except Exception:
        return None
    deg = h * 360.0
    best, gap = None, 1e9
    for name, (hh, ss, _vv) in _HUES.items():
        if ss < 0.02:                      # grey has no meaningful hue
            continue
        d = abs((deg - hh + 180.0) % 360.0 - 180.0)
        if d < gap:
            best, gap = name, d
    return best if gap < 22.0 else None


#  How far apart the second, third... frame of the same section are nudged in
#  hue. Big enough to tell two OPERATOR blocks apart, small enough that they
#  still obviously belong to each other.
#
#  🔴 REPEATS ALTERNATE DIRECTION (+11, -11, +22, ...) rather than marching
#  one way. Marching +11 each time walks a repeated section TOWARD its
#  clockwise neighbour - the second OPERATOR block ended up 10 degrees from
#  EMITTER, wearing the wrong section's colour at exactly the place colour is
#  supposed to be navigation. Alternating keeps every repeat 11 degrees from
#  its own base, which the 25-degree section spacing guarantees is nearer its
#  own family than anyone else's.
SIBLING_HUE_STEP = 11.0


def sibling_hue(base, n_seen):
    """The hue for the n-th repeat of a section: 0 -> base, then +11, -11,
    +22, -22... degrees, so repeats fan out AROUND their base instead of
    marching into the next section's colour."""
    if n_seen <= 0:
        return base % 360.0
    k = (n_seen + 1) // 2
    sign = 1.0 if n_seen % 2 == 1 else -1.0
    return (base + sign * k * SIBLING_HUE_STEP) % 360.0


def recolour_frames(ng):
    """Paint every frame from its OWN LABEL, and split repeated sections.

    🔴 A FRAME'S COLOUR HAS TO AGREE WITH ITS TITLE. The CHILDREN section was
    painted with the EMITTER hue - it was built alongside the emitter and
    inherited its role - so the one block whose label said CHILDREN was the
    same brown as the emitter, and the palette looked arbitrary at exactly the
    place someone would be trying to use it. The label is what a reader
    believes, so the label is what picks the colour.

    ⚠️ A SECTION CAN LEGITIMATELY APPEAR TWICE - two OPERATOR blocks is normal,
    they do different jobs at different points. Identical colour makes them
    look like one section drawn twice, so repeats step round the wheel a little
    while staying recognisably the same family."""
    tops = [f for f in ng.nodes if f.bl_idname == "NodeFrame"]
    seen, painted = {}, 0
    for f in sorted(tops, key=lambda n: (n.label or "")):
        if f.get("ht_hand"):
            continue
        label = (f.label or "").upper()
        role = None
        for name in SECTION_ORDER:
            if label.startswith(name):
                role = name
                break
        if role is None:
            continue
        n_seen = seen.get(role, 0)
        seen[role] = n_seen + 1
        h, s, _v = _HUES[role]
        h = sibling_hue(h, n_seen)
        f.color = colorsys.hsv_to_rgb(h / 360.0, s * FRAME_SAT_MUL, FRAME_VAL)
        f.use_custom_color = True
        painted += 1
    return painted


def gradient_nodes(ng):
    """Ramp every framed node's brightness across its own section.

    Position is measured along the section, so the ramp follows the graph's
    own left-to-right reading order rather than the order nodes happen to
    have been created in. Nodes outside any frame are left alone - they have
    no section to be a gradient of."""
    painted = 0
    for frame in [n for n in ng.nodes if n.bl_idname == "NodeFrame"]:
        kids = [n for n in children_of(ng, frame)
                if n.bl_idname != "NodeFrame"]
        if len(kids) < 2:
            continue
        xs = [absolute(n)[0] for n in kids]
        lo, hi = min(xs), max(xs)
        span = (hi - lo) or 1.0
        for n, x in zip(kids, xs):
            role = _role_of(n)
            if role is None:
                continue
            n.color = gradient_rgb(role, (x - lo) / span)
            n.use_custom_color = True
            painted += 1
    return painted


#  ── the FLOW ramp, for nodes no section claims ──────────────────────────────
#
#  Plumbing - group inputs and outputs, reroutes, glue maths built without a
#  role - used to sit grey between the coloured sections. Grey says "I don't
#  matter", which is wrong: a Group Input is where everything ENTERS. So the
#  unclaimed nodes wear a flow ramp instead: ORANGE on the input side of the
#  graph fading to BLUE on the output side, matching the palette's own
#  warm-changes / cool-is-read logic. Section-coloured nodes are untouched -
#  the ramp only exists where the palette has nothing to say.
#  Node strength, like everything else now - dim plumbing was invisible.
FLOW_IN = colorsys.hsv_to_rgb(28 / 360.0, 0.58, 0.80)    # orange = input
FLOW_OUT = colorsys.hsv_to_rgb(215 / 360.0, 0.58, 0.80)  # blue = output


def recolour_flow(ng):
    """Orange->blue ramp across every node the palette does not claim."""
    plain = [n for n in ng.nodes
             if n.bl_idname != "NodeFrame" and _role_of(n) is None]
    if not plain:
        return 0
    xs = {n: absolute(n)[0] for n in plain}
    lo, hi = min(xs.values()), max(xs.values())
    span = (hi - lo) or 1.0
    for n, x in xs.items():
        t = (x - lo) / span
        n.color = tuple(a + (b - a) * t for a, b in zip(FLOW_IN, FLOW_OUT))
        n.use_custom_color = True
    return len(plain)


def recolour_all(ng):
    """Every colour pass at once - the whole-project palette, reasserted.

    Safe to run repeatedly: everything derives from labels, roles and node
    positions, so a second run paints the same colours again."""
    return {"frames": recolour_frames(ng),
            "gradient": gradient_nodes(ng),
            "flow": recolour_flow(ng)}


# ── geometry helpers ─────────────────────────────────────────────────────────
#
#  A child node's `location` is RELATIVE TO ITS FRAME, and frames can nest, so
#  anything comparing two nodes has to walk up to absolute coordinates first.
#  Comparing raw locations across frames is how a de-overlap pass ends up
#  making the overlap worse.

DEFAULT_W = 160.0
DEFAULT_H = 120.0


def absolute(node):
    x, y = node.location
    p = node.parent
    while p is not None:
        x += p.location.x
        y += p.location.y
        p = p.parent
    return x, y


def _size(node):
    w = node.width or DEFAULT_W
    # Node.height is unreliable until a node has been drawn - in background
    # mode it is often the default. Guessing generously is the safe error:
    # too much space is untidy, too little is overlap.
    h = node.height if node.height and node.height > 1 else DEFAULT_H
    return w, max(h, 30.0)


def children_of(ng, frame):
    # BY NAME, never with `is`: every attribute access can hand back a fresh
    # Python wrapper around the same node, so `n.parent is frame` is False for
    # a node that really is in that frame - and it fails silently, as an empty
    # list rather than an error.
    return [n for n in ng.nodes
            if n.parent is not None and n.parent.name == frame.name]


def content_bounds(ng, frame):
    """(x0, y0, x1, y1) around a frame's children, in absolute coordinates.

    Returns None for an empty frame - it has no content to measure, so the
    caller keeps whatever size it was given."""
    kids = children_of(ng, frame)
    if not kids:
        return None
    x0 = y0 = 1e18
    x1 = y1 = -1e18
    for n in kids:
        x, y = absolute(n)
        w, h = _size(n)
        x0, x1 = min(x0, x), max(x1, x + w)
        y0, y1 = min(y0, y - h), max(y1, y)
    return x0, y0, x1, y1


# ── 1. loose nodes ───────────────────────────────────────────────────────────

def prune_loose(ng, keep_types=("NodeGroupInput", "NodeGroupOutput",
                                "NodeFrame", "NodeReroute")):
    """Delete nodes with nothing connected to them at all. Returns the count.

    Reroutes are kept: an unconnected one is a leftover too, but they are
    invisible clutter rather than a misleading node, and deleting one that a
    human parked deliberately is ruder than leaving it."""
    linked = set()
    for link in ng.links:
        linked.add(link.from_node.name)
        linked.add(link.to_node.name)
    doomed = [n for n in ng.nodes
              if n.bl_idname not in keep_types and n.name not in linked]
    for n in doomed:
        ng.nodes.remove(n)
    return len(doomed)


def dead_ends(ng):
    """Nodes that are wired IN but whose output goes nowhere.

    NOT deleted - a dead end is usually half-finished work rather than
    rubbish, and deleting somebody's parked experiment is not a cosmetic
    change. Reported so it can be decided on."""
    feeds = {link.from_node.name for link in ng.links}
    eats = {link.to_node.name for link in ng.links}
    return [n for n in ng.nodes
            if n.bl_idname not in ("NodeFrame", "NodeGroupOutput")
            and n.name in eats and n.name not in feeds]


# ── 2. overlapping frames ────────────────────────────────────────────────────

def rect_of(ng, node):
    """A node's absolute rectangle. For a frame, the box it actually draws."""
    if node.bl_idname == "NodeFrame":
        r = content_bounds(ng, node)
        if r is None:
            x, y = absolute(node)
            r = (x, y - (node.height or 200.0), x + (node.width or 300.0), y)
        # a frame draws a margin around its contents, plus its label above
        pad = node.label_size * 0.9 + 12.0
        return (r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad)
    x, y = absolute(node)
    w, h = _size(node)
    return (x, y - h, x + w, y)


def frame_rects(ng, scope=None):
    """{frame: rect} for the frames sitting directly in one scope.

    `scope` is a parent frame name, or None for the top level. A NESTED frame
    is not overlapping its parent - it is inside it, which is the point - so
    frames are only ever compared against their own siblings."""
    out = {}
    for f in ng.nodes:
        if f.bl_idname != "NodeFrame":
            continue
        parent = f.parent.name if f.parent else None
        if parent != scope:
            continue
        out[f] = rect_of(ng, f)
    return out


def _scopes(ng):
    """Every parent scope in the graph: None, then each frame that holds
    other frames or nodes."""
    seen = {None}
    for n in ng.nodes:
        if n.parent is not None:
            seen.add(n.parent.name)
    return list(seen)


def _overlap(a, b):
    ox = min(a[2], b[2]) - max(a[0], b[0])
    oy = min(a[3], b[3]) - max(a[1], b[1])
    return (ox, oy) if ox > 0 and oy > 0 else None


def spread_frames(ng, gap=120.0, passes=12):
    """Push overlapping frames clear, without touching what is inside them.

    🔴 OFF BY DEFAULT, AND MEASURED, NOT ASSUMED. Run against the 667-node,
    19-frame TF2 Explosion graph it made 152 moves and took the overlapping
    frame pairs from 3 to 7: the three it "fixed" were sub-sections legitimately
    sitting inside their parent section, and evicting them broke the grouping
    a human had built while creating fresh collisions elsewhere.

    A hand-authored graph's layout carries MEANING that a rectangle-packer
    cannot see. This is kept for generated graphs, where the only layout is
    the one we produced and there is nothing to lose - `tidy(spread=True)`.

    ONLY FRAMES MOVE, and only against their own SIBLINGS. Two things follow
    from that, and both are the point:

      * a nested frame is not "overlapping" the frame it sits inside - it is
        inside it. Comparing across scopes would try to evict a sub-section
        from its own section, forever.
      * a frame is also compared against sibling NODES, because a section box
        drawn across somebody else's nodes is exactly the mess this is for.
        The frame moves; the loose node stays where its author put it.

    Movement is along the SHORTER axis of the overlap, so a layout stays
    recognisable - two sections side by side are given room rather than being
    re-sorted into a machine's idea of order.

    Iterative, because separating A from B can push B into C. It converges in
    a few passes on real graphs; the cap stops a pathological one spinning."""
    moved = 0
    for _ in range(passes):
        hit = False
        for scope in _scopes(ng):
            frames = frame_rects(ng, scope)
            if not frames:
                continue
            others = [n for n in ng.nodes
                      if n.bl_idname != "NodeFrame"
                      and (n.parent.name if n.parent else None) == scope]
            items = [(f, r, True) for f, r in frames.items()]
            items += [(n, rect_of(ng, n), False) for n in others]

            for i in range(len(items)):
                for j in range(i + 1, len(items)):
                    (na, ra, fa), (nb, rb, fb) = items[i], items[j]
                    if not fa and not fb:
                        continue            # two plain nodes: not our business
                    ov = _overlap(ra, rb)
                    if ov is None:
                        continue
                    ox, oy = ov
                    # the FRAME moves; if both are frames, the one further
                    # along that axis does, so they drift apart evenly
                    if fa and fb:
                        along_y = (ra[1] + ra[3]) >= (rb[1] + rb[3])
                        along_x = (ra[0] + ra[2]) >= (rb[0] + rb[2])
                        tgt = na if (along_y if oy <= ox else along_x) else nb
                        sign = 1.0
                    else:
                        tgt = na if fa else nb
                        if oy <= ox:
                            sign = 1.0 if (rect_of(ng, tgt)[1]
                                           + rect_of(ng, tgt)[3]) >= (
                                (ra[1] + ra[3] + rb[1] + rb[3]) / 2) else -1.0
                        else:
                            sign = 1.0 if (rect_of(ng, tgt)[0]
                                           + rect_of(ng, tgt)[2]) >= (
                                (ra[0] + ra[2] + rb[0] + rb[2]) / 2) else -1.0
                    if oy <= ox:
                        tgt.location.y += sign * (oy + gap)
                    else:
                        tgt.location.x += sign * (ox + gap)
                    moved += 1
                    hit = True
                    # rectangles just changed under us
                    frames = frame_rects(ng, scope)
                    items = [(f, r, True) for f, r in frames.items()]
                    items += [(n, rect_of(ng, n), False) for n in others]
        if not hit:
            break
    return moved


# ── 3. room for the frame's own explanation ──────────────────────────────────

# Blender draws frame text at label_size, one line under the next, with the
# label above it. Measured against the real thing rather than derived: a
# 16pt frame label leaves lines about 1.35x its size apart.
LINE = 1.35
TEXT_PAD = 24.0
CHAR_W = 0.52          # average glyph width as a fraction of label_size


#  The order sections are laid out in - SFM's own, which is also the order the
#  modifier panels are stacked in. Reading the graph left to right then top to
#  bottom therefore walks the effect in the same order as reading the panel.
SECTION_ORDER = (
    "CONTROL POINTS", "SYSTEM PROPERTIES", "TIME",
    "EMITTER", "INITIALIZER", "OPERATOR", "FORCE GENERATOR",
    "CONSTRAINT", "CHILDREN", "SEQUENCE", "RENDERER", "OUTPUT",
)

PACK_GAP = 260.0         # clear space between neighbouring sections
PACK_ROW_WIDTH = 9000.0  # start a new row once a row passes this wide


def _section_rank(frame):
    """Where a frame sits in the pipeline, from its label."""
    label = (frame.label or "").upper()
    for i, name in enumerate(SECTION_ORDER):
        if label.startswith(name):
            return i
    return len(SECTION_ORDER)


def pack_frames(ng, gap=PACK_GAP, row_width=PACK_ROW_WIDTH):
    """Lay the top-level sections out in reading order, never overlapping.

    🔴 THIS MOVES WHOLE SECTIONS AND NOTHING INSIDE THEM. Each frame is taken
    as a rigid block at whatever size its contents make it, and the blocks are
    shelved left to right in SFM's section order, wrapping to a new row when
    one gets too wide. The hand-placed layout inside every section survives
    exactly as it was - which is the difference between this and the auto-
    arrange that was tried and reverted, where deriving node positions from the
    wiring scored beautifully and read worse.

    ⚠️ THE BUILDER LEAVES EVERY FRAME AT (0, 0). Nine sections all at the
    origin is nine sections drawn on top of each other, and Blender's
    shrink-wrap then sizes each one around contents that are interleaved with
    somebody else's - which is the actual reason a generated graph opened as a
    heap. Measured on the laser system: 15 overlapping section pairs before,
    0 after.

    Only sibling frames are compared, because a frame nested inside another is
    not overlapping it - it is inside it, and that is the grouping a reader
    relies on."""
    tops = [f for f in ng.nodes
            if f.bl_idname == "NodeFrame" and f.parent is None]
    if len(tops) < 2:
        return 0

    blocks = []
    for f in tops:
        r = rect_of(ng, f)
        if r is None:
            continue
        blocks.append((_section_rank(f), f.label or "", f, r))
    blocks.sort(key=lambda b: (b[0], b[1]))

    moved = 0
    cur_x, cur_y, row_h = 0.0, 0.0, 0.0
    for _rank, _label, f, (x0, y0, x1, y1) in blocks:
        w, h = x1 - x0, y1 - y0
        if cur_x > 0.0 and cur_x + w > row_width:
            cur_x = 0.0
            cur_y -= row_h + gap
            row_h = 0.0
        # move the frame so its content box lands at (cur_x, cur_y)
        dx = cur_x - x0
        dy = cur_y - y1
        if abs(dx) > 0.5 or abs(dy) > 0.5:
            f.location = (f.location.x + dx, f.location.y + dy)
            moved += 1
        cur_x += w + gap
        row_h = max(row_h, h)
    return moved


def text_headroom(ng, min_width=420.0):
    """Give every frame with a `.text` note room to actually show it.

    Turns shrink OFF - with it on the frame re-fits to its children every draw
    and any reserved space vanishes - then sizes the frame to hold the text
    band ABOVE the nodes, and drops the children by that much so nothing is
    printed over.

    Returns how many frames were adjusted."""
    done = 0
    for f in ng.nodes:
        if f.bl_idname != "NodeFrame" or f.text is None:
            continue
        body = f.text.as_string()
        lines = body.split("\n")
        text_h = (len(lines) + 1) * f.label_size * LINE + TEXT_PAD
        text_w = max((len(s) for s in lines), default=0) * f.label_size * CHAR_W

        kids = children_of(ng, f)
        bounds = content_bounds(ng, f)

        # push the children down out of the text band
        for n in kids:
            n.location.y -= text_h

        if bounds is not None:
            cw = bounds[2] - bounds[0]
            ch = bounds[3] - bounds[1]
        else:
            cw = ch = 0.0

        f.shrink = False
        f.width = max(min_width, text_w + TEXT_PAD * 2, cw + TEXT_PAD * 2)
        f.height = ch + text_h + TEXT_PAD * 2
        done += 1
    return done


# ── 4. which way the graph runs ──────────────────────────────────────────────

def split_group_inputs(ng):
    """One Group Input PER SECTION, so the spaghetti dies at the source.

    🔴 THE MEGA GROUP INPUT IS WHAT MAKES A GENERATED GRAPH READ AS A HAIRBALL.
    A system group has 260+ input sockets, and ONE Group Input node feeding
    all of them throws a link across the entire canvas for every single field
    - the sections can be packed perfectly and the picture is still a wall of
    wires, because every wire starts at the same far-left node.

    So every section gets its OWN Group Input, parented into the frame, just
    left of the nodes it feeds, with every socket that section does not read
    HIDDEN. Same sockets, same values, same evaluation - a Group Input node
    is only a view of the interface, and Blender allows any number of them.
    The links now start and end inside the section they belong to.

    The original global input keeps only whatever fed un-framed plumbing, and
    hides the rest; if nothing is left it is removed."""
    mains = [n for n in ng.nodes if n.bl_idname == "NodeGroupInput"]
    if not mains:
        return 0

    idx_of = {s.identifier: i for i, s in enumerate(mains[0].outputs)}

    def top_frame(n):
        p = n.parent
        while p is not None and p.parent is not None:
            p = p.parent
        return p

    by_frame = {}
    for link in list(ng.links):
        if link.from_node.bl_idname != "NodeGroupInput":
            continue
        f = top_frame(link.to_node)
        if f is None:
            continue                       # un-framed plumbing keeps the main
        by_frame.setdefault(f.name, (f, []))[1].append(link)

    made = 0
    for _fname, (frame, links) in by_frame.items():
        gi = ng.nodes.new("NodeGroupInput")
        gi.label = "inputs"
        gi.width = 140.0
        # left of the section's leftmost consumer, at its mean height
        ax = min(absolute(l.to_node)[0] for l in links) - 320.0
        ay = sum(absolute(l.to_node)[1] for l in links) / len(links)
        fx, fy = absolute(frame)
        gi.parent = frame
        gi.location = (ax - fx, ay - fy)

        used = set()
        for link in links:
            try:
                idx = idx_of[link.from_socket.identifier]
                to_sock = link.to_socket
            except Exception:
                continue
            try:
                #  NO explicit remove: links.new onto an occupied single-
                #  input socket replaces the old link in ONE operation.
                #  Every link mutation costs a FULL tree update - measured
                #  O(node count), 4.4ms each on a 2500-node tree - so the
                #  remove-then-new pair paid that tax twice per link and
                #  was half of this function's 24s on a nine-system import.
                ng.links.new(gi.outputs[idx], to_sock)
                used.add(idx)
            except Exception as exc:
                print(f"[HT_LAYOUT]  split input link failed in "
                      f"{frame.label!r}: {exc}")
        #  fresh sockets start visible - only the unused ones need a write,
        #  which is most of them, but half the RNA traffic of writing all
        for i, out in enumerate(gi.outputs):
            if i not in used:
                try:
                    out.hide = True
                except Exception:
                    pass
        made += 1

    #  What does each surviving main still feed? One pass over the links
    #  instead of hundreds of per-socket is_linked reads per node.
    still = {}
    for l in ng.links:
        if l.from_node.bl_idname == "NodeGroupInput":
            still.setdefault(l.from_node.name, set()).add(
                l.from_socket.identifier)
    for n in mains:
        fed = still.get(n.name)
        if not fed:
            try:
                ng.nodes.remove(n)
            except Exception:
                pass
        else:
            for o in n.outputs:
                try:
                    o.hide = o.identifier not in fed
                except Exception:
                    pass
    return made


def corner_the_ends(ng, margin=400.0):
    """Group Input to the BOTTOM LEFT, Group Output to the TOP RIGHT.

    Not an aesthetic preference - it is what keeps the two nodes everybody
    looks for first out of the middle of the picture, where they otherwise
    sit on top of a frame's explanation. The graph then reads on one diagonal:
    start at the bottom left, finish at the top right.

    Everything else keeps the position it was built with. A full auto-layout
    would be worse than a hand-placed graph, not better."""
    nodes = [n for n in ng.nodes if n.bl_idname != "NodeFrame"]
    if not nodes:
        return
    xs, ys = [], []
    for n in nodes:
        if n.bl_idname in ("NodeGroupInput", "NodeGroupOutput"):
            continue
        x, y = absolute(n)
        w, h = _size(n)
        xs += [x, x + w]
        ys += [y - h, y]
    if not xs:
        return
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)

    for n in nodes:
        # A Group Input PARENTED TO A FRAME is a section's own local input,
        # placed there by split_group_inputs so its links stay short. Yanking
        # it to the corner would undo the whole untangling, so only the
        # global, unparented ends are cornered.
        if n.bl_idname == "NodeGroupInput" and n.parent is None:
            n.location = (x0 - margin, y0)
        elif n.bl_idname == "NodeGroupOutput" and n.parent is None:
            n.location = (x1 + margin, y1)


# ── 5. work the positions out from the links ─────────────────────────────────
#
#  Hand-placed coordinates rot. Every node in a generated graph was given an
#  (x, y) by whoever wrote the builder, and the moment a node is inserted the
#  numbers around it are wrong - which is how a graph ends up tangled and
#  overlapping while every individual line of code looks reasonable.
#
#  So don't place nodes. DERIVE them:
#
#      column = the LONGEST path from an input to that node
#      row    = a free slot in that column, inside its own frame
#
#  Longest path, not shortest: a node must sit to the right of EVERY node
#  feeding it, and the shortest path only guarantees it sits right of one of
#  them. That single choice is what removes backwards-pointing links.

COL_W = 260.0          # a 140-160 wide node plus room for the wires
ROW_H = 320.0          # tall enough for a multi-socket group node
FRAME_GAP = 260.0


def depths(ng):
    """{node name: column}, by longest path from the inputs.

    Kahn's algorithm over the link graph. Anything left over when the queue
    empties was part of a cycle - geometry node graphs are acyclic, zones
    included, but a corrupt file should not hang a cosmetic pass, so the
    remainder is dropped in at column 0 rather than looped on forever."""
    nodes = [n for n in ng.nodes if n.bl_idname != "NodeFrame"]
    incoming = {n.name: set() for n in nodes}
    outgoing = {n.name: set() for n in nodes}
    for link in ng.links:
        a, b = link.from_node.name, link.to_node.name
        if a in outgoing and b in incoming and a != b:
            outgoing[a].add(b)
            incoming[b].add(a)

    depth = {n.name: 0 for n in nodes}
    pending = {k: set(v) for k, v in incoming.items()}
    queue = [k for k, v in pending.items() if not v]
    seen = set(queue)
    while queue:
        cur = queue.pop(0)
        for nxt in outgoing[cur]:
            depth[nxt] = max(depth[nxt], depth[cur] + 1)
            pending[nxt].discard(cur)
            if not pending[nxt] and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return depth


def arrange(ng, col_w=COL_W, row_h=ROW_H):
    """Lay a generated graph out from its own wiring. Returns (cols, rows).

    ⚠️ FOR GENERATED GRAPHS ONLY. A hand-authored layout carries meaning -
    which cluster is which, what sits next to what - and none of that is in
    the link graph, so re-deriving it throws information away. Here the only
    layout is the one a builder produced, and there is nothing to lose.

    Each frame is packed independently, then the frames are stacked in a
    column ordered by how early their contents appear in the flow. That keeps
    a SECTION as a block you can read on its own, which a single global grid
    would shred."""
    depth = depths(ng)
    frames = [n for n in ng.nodes if n.bl_idname == "NodeFrame"]

    buckets = {}                       # frame name (or None) -> [nodes]
    for n in ng.nodes:
        if n.bl_idname == "NodeFrame":
            continue
        buckets.setdefault(n.parent.name if n.parent else None, []).append(n)

    def lay_out(items):
        """Place one bucket. Returns (width, height) of what was placed.

        🔴 THE COLUMN IS GLOBAL, never rebased to the frame. Packing each
        frame from its own column zero looked tidier per box and made 154 of
        413 links run BACKWARDS, because a node in column 20 of one frame sat
        left of column 2 of the next. Depth is a property of the whole graph;
        the frame only decides the row."""
        by_col = {}
        for n in sorted(items, key=lambda q: (depth[q.name], q.name)):
            by_col.setdefault(depth[n.name], []).append(n)
        if not by_col:
            return 0.0, 0.0
        rows = max(len(v) for v in by_col.values())
        for col, members in by_col.items():
            for row, n in enumerate(members):
                n.location = (col * col_w, -row * row_h)
        return (max(by_col) + 1) * col_w, rows * row_h

    # frames first, each in its own coordinate space
    sizes = {}
    for f in frames:
        kids = buckets.get(f.name, [])
        sizes[f] = lay_out(kids)

    # Then stack the frames into horizontal BANDS, earliest flow at the top.
    #
    # ⚠️ A frame's children hang DOWNWARDS from its origin (row 0 is at y=0,
    # row 3 at -960), so a band's origin is its TOP and the next band starts
    # a full height BELOW - not above. Stacking upwards put every frame's
    # children straight through the one before it.
    def frame_order(f):
        kids = buckets.get(f.name, [])
        return min((depth[k.name] for k in kids), default=0)

    band_top = 0.0
    for f in sorted(frames, key=frame_order):
        f.location = (0.0, band_top)
        band_top -= sizes[f][1] + FRAME_GAP

    # Nodes in no frame keep the same global columns - so the left-to-right
    # flow still holds - and get the last band to themselves, where they read
    # as "not part of a section".
    loose = buckets.get(None, [])
    if loose:
        lay_out(loose)
        for n in loose:
            n.location = (n.location.x, n.location.y + band_top)

    return (max(depth.values(), default=0) + 1), len(frames)


def node_overlaps(ng):
    """How many pairs of nodes are drawn on top of each other. The number
    this whole pass exists to bring down, so it is measurable."""
    items = [(n, rect_of(ng, n)) for n in ng.nodes
             if n.bl_idname != "NodeFrame"]
    hits = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _overlap(items[i][1], items[j][1]):
                hits += 1
    return hits


# ── the hand-cleaned layout, replayed ────────────────────────────────────────

def apply_hand_layout(ng):
    """Replay the user's hand-cleaned layout from `ras_layout` (generated
    data - see "__ForYou/Encode Cleaned Layout.py") onto a freshly built
    system group. Returns None when the table has nothing to say about this
    group, else a report dict with "applied".

    🔴 VERIFY BEFORE TRUSTING A NAME. Node names are auto-generated in build
    order, so a variant build (.pcf with a different operator set) can reuse
    a name for a DIFFERENT node. Every table entry carries an identity check
    (its label, or its group's name prefix); under 90% agreement the whole
    table is refused and the normal tidy layout stands - a wrong layout is
    worse than a generated one.

    Positions are RELATIVE TO THE PARENT FRAME (see the geometry helpers), so
    parents are assigned before locations, frames before nodes, and outer
    frames before inner ones. Hand-added frames are stamped "ht_hand": the
    recolour pass leaves them alone, and a re-run reuses them instead of
    stacking duplicates - the whole thing is idempotent on purpose."""
    try:
        from . import ras_layout
    except Exception:
        return None
    if not ng.name.startswith(ras_layout.SYSTEM_PREFIX):
        return None
    #  ONE TABLE PER RENDERER. Sprites, rope and sprite trail all build under
    #  the same group-name prefix and share most of the upstream graph, so
    #  the name cannot pick the table - which "SP · RENDERER · render_*"
    #  group the system instances can, and does.
    renderer = None
    for n in ng.nodes:
        tree = getattr(n, "node_tree", None)
        if tree is not None \
                and tree.name.startswith("SP · RENDERER · render_"):
            renderer = tree.name.split(" · ")[2]
            break
    table = ras_layout.TABLES.get(renderer)
    if table is None:
        return None
    return _apply_table(ng, table, ras_layout.VERSION)


def apply_shader_layout(nt, name):
    """Replay a hand-cleaned SHADER layout onto a freshly built material or
    shader group - same table machinery as the system graphs.

    `name` is the MATERIAL or shader-group name, passed in because a
    material's node_tree is called "Shader Nodetree" no matter what the
    material is - the tree's own name identifies nothing. Tables are keyed
    by the name's FAMILY (the part before the first " · "): "RAS Sprite ·
    australium_trail" and "RAS Sprite · glow_a" share the "RAS Sprite"
    layout, because they are the same builder with a different picture. The
    identity gate still arbitrates - an additive variant whose node set
    differs simply refuses the table and keeps the builder's layout."""
    try:
        from . import ras_layout
    except Exception:
        return None
    family = (name or "").split(" · ")[0]
    table = getattr(ras_layout, "SHADERS", {}).get(family)
    if table is None:
        return None
    return _apply_table(nt, table, ras_layout.VERSION)


def _node_ident(n):
    """A node's identity, computed the same way the encoder stores it."""
    tree = getattr(n, "node_tree", None)
    if tree is not None:
        parts = tree.name.split(" · ")
        keep = 3 if parts[0] == "SP" else 1
        return ("group", " · ".join(parts[:keep]))
    if n.label:
        return ("label", n.label)
    return None


def _apply_table(nt, table, version):
    nodes = nt.nodes

    #  MATCH BY NAME, THEN BY IDENTITY - because names are BIRTH-ORDER
    #  ARTIFACTS. A .pcf import sizes its CP selector chains to the FILE's
    #  control point count and can stack operators, which shifts every
    #  auto-generated name created after them - so an imported system never
    #  matched the table by name alone and fell back to the heap. Two passes:
    #    1. same name AND the identity agrees - the canonical build, cheap;
    #    2. leftover table entries claim unclaimed nodes wearing the same
    #       identity (its label, or its group's name prefix), paired in
    #       creation order - Blender's .001/.002 suffixes sort with creation,
    #       so duplicates like the CP chains stay aligned.
    #  Nodes neither pass claims (a variant's extra instances) keep their
    #  builder position INSIDE their section frame and ride along with it.
    match = {}
    claimed = set()
    for name, (_p, _loc, _w, ident) in table["NODES"].items():
        n = nodes.get(name)
        if n is None or n.bl_idname == "NodeFrame":
            continue
        if ident is None or _node_ident(n) == tuple(ident):
            match[name] = n
            claimed.add(n.name)
    queues = {}
    for n in nodes:                       # ng.nodes iterates creation order
        if n.bl_idname == "NodeFrame" or n.name in claimed:
            continue
        ni = _node_ident(n)
        if ni is not None:
            queues.setdefault(ni, []).append(n)
    for name, (_p, _loc, _w, ident) in table["NODES"].items():
        if name in match or ident is None:
            continue
        q = queues.get(tuple(ident))
        if q:
            n = q.pop(0)
            match[name] = n
            claimed.add(n.name)

    total = sum(1 for n in nodes if n.bl_idname != "NodeFrame")
    #  🔴 THE GATE ASKS "DID THE TABLE FIND ITS NODES?", NOT "DOES THE TABLE
    #  COVER THE GRAPH?" - and getting that backwards threw away every hand
    #  layout on a real import.
    #
    #  It used to divide by the BUILT graph, so a table that matched 160 of
    #  its own 160 entries - a PERFECT score - was refused at 160/230 = 70%
    #  because the build also carried 70 nodes no table could ever own: the
    #  per-sequence ladder ("seq 5 start", "seq 5 length", ... four uniquely
    #  labelled nodes PER SEQUENCE, and a sheet can have ten), extra operator
    #  instances, longer CP chains. The richer the effect, the more certain
    #  the refusal - exactly backwards, since that is where a clean layout is
    #  worth the most, and no amount of hand-cleaning could ever fix it
    #  (cleaning a 10-sequence file just moves the impossibility to 4).
    #
    #  What the gate is actually for is catching the WRONG table (the family
    #  key picked badly, or the builder changed shape underneath it). That
    #  shows up as table entries failing to find identities - table-side
    #  coverage. The build-side number stays as a sanity FLOOR, so a handful
    #  of table entries can never claim to lay out a huge graph.
    #
    #  Surplus nodes are not homeless: they keep their builder position
    #  inside their section frame and ride along with it (below).
    #  A VARIANT MISSES IN BOTH DIRECTIONS, AND BOTH ARE LEGITIMATE:
    #    build RICHER than the table  - ten sequences, stacked operators, a
    #      longer CP chain: surplus nodes with no entry to claim them
    #      (measured: a trail at 160/160 entries but only 70% of the graph);
    #    build SIMPLER than the table - the workbench was cleaned from a
    #      fatter system, so entries find no node (measured: sprites at
    #      164/227 entries covering 87% of the graph).
    #  Neither means the table is WRONG - and the wrong-family case cannot
    #  even reach here, because TABLES is keyed by the renderer group the
    #  system instances. So the gate only has to catch a table that is
    #  genuinely stale (the builder changed shape underneath it), which
    #  shows as BOTH numbers collapsing. Anything else applies, and the
    #  surplus rides along inside its section frame.
    entries = sum(1 for _n, (_p, _l, _w, _i) in table["NODES"].items())
    tcov = (len(match) / entries) if entries else 0.0
    bcov = (len(match) / total) if total else 0.0
    if not total or not entries or tcov < 0.5 or bcov < 0.25:
        return {"applied": False, "matched": len(match), "of": total,
                "entries": entries, "table_cov": tcov, "build_cov": bcov}

    frames = {}
    for name, create, label, lsize, shrink, colour, _p, _loc, size \
            in table["FRAMES"]:
        f = nodes.get(name)
        ours = (f is not None and f.bl_idname == "NodeFrame"
                and (f.get("ht_hand")
                     or (not create and f.label == label)))
        if not ours:
            if not create:
                continue          # builder frame missing: variant build
            f = nodes.new("NodeFrame")
            f.name = name
        f.label = label
        f.label_size = lsize
        f.shrink = shrink
        f.use_custom_color = True
        f.color = colour
        f["ht_hand"] = 1
        frames[name] = f
    for name, _c, _l, _ls, _sh, _col, parent, loc, size in table["FRAMES"]:
        f = frames.get(name)
        if f is None:
            continue
        f.parent = frames.get(parent) if parent else None
        f.location = loc
        if size is not None:
            f.width, f.height = size

    placed = 0
    for name, (parent, loc, w, _ident) in table["NODES"].items():
        n = match.get(name)
        if n is None:
            continue
        n.parent = frames.get(parent) if parent else None
        n.location = loc
        if w and abs(n.width - w) > 0.5:
            try:
                n.width = w
            except Exception:
                pass              # some node types clamp their width
        placed += 1
    nt["ht_hand_layout"] = version
    return {"applied": True, "placed": placed,
            "frames": len(frames), "matched": len(match), "of": total}


# ── the whole pass ───────────────────────────────────────────────────────────

def tidy(ng, prune=True, headroom=True, spread=False, corners=True,
         verbose=True, force=False, arrange_nodes=False,
         pack=True, gradient=True, split_inputs=True):
    """Every cosmetic pass, in the only order that works.

    Headroom BEFORE pack: reserving text space makes frames taller, which
    changes the block sizes the packer is shelving. Doing it the other way
    round lays the sections out and then grows them back into each other.

    Gradient LAST: it measures each node's position inside its section, so it
    has to run after anything that moves nodes.

    ⚠️ NOT IDEMPOTENT, so it stamps the group and refuses to run twice.
    `text_headroom` moves children DOWN by the height of the text; running it
    again moves them down again, and a shared operator group tidied once per
    system would walk its own contents off the bottom of the screen."""
    if ng.get("ht_tidied") and not force:
        return {"loose": 0, "headroom": 0, "moved": 0, "dead_ends": 0,
                "overlaps": 0, "skipped": True}
    ng["ht_tidied"] = True
    report = {"loose": 0, "headroom": 0, "moved": 0,
              "dead_ends": len(dead_ends(ng)),
              "overlaps": node_overlaps(ng), "skipped": False}
    if prune:
        report["loose"] = prune_loose(ng)
    if arrange_nodes:
        # positions derived from the wiring, before anything measures a frame
        arrange(ng)
        report["overlaps_after"] = node_overlaps(ng)
    if split_inputs:
        # BEFORE headroom/pack: the per-section inputs become part of their
        # section's contents, so the packer must see them when it measures.
        report["split_inputs"] = split_group_inputs(ng)
    if headroom:
        report["headroom"] = text_headroom(ng)
    if pack:
        report["packed"] = pack_frames(ng)
    if spread:
        report["moved"] = spread_frames(ng)
    if corners:
        corner_the_ends(ng)
    #  THE HAND-CLEANED LAYOUT WINS. After the movers, before the colour
    #  passes (the gradient measures positions, so it has to see the final
    #  ones). The movers still run first: they are deterministic, they attach
    #  the note texts and split the inputs, and everything they placed is
    #  simply overridden for the nodes the table knows - while a variant
    #  build the table refuses keeps their result untouched.
    hand = apply_hand_layout(ng)
    if hand is not None:
        report["hand_layout"] = hand
        if verbose and hand.get("applied"):
            extra = hand.get("of", 0) - hand.get("placed", 0)
            print(f"[HT_LAYOUT]  {ng.name}: hand-cleaned layout applied "
                  f"({hand['placed']} nodes, {hand['frames']} frames"
                  + (f", {extra} extra node(s) ride in their section frames)"
                     if extra > 0 else ")"))
        elif hand.get("applied") is False:
            #  Say WHICH coverage failed - table-side means the wrong table
            #  or a builder change; build-side means a table far too small
            #  for this graph. Guessing between them used to cost an hour.
            print(f"[HT_LAYOUT]  {ng.name}: hand layout refused - "
                  f"{hand['matched']}/{hand.get('entries', '?')} table "
                  f"entries placed ({hand.get('table_cov', 0):.0%}), "
                  f"covering {hand['matched']}/{hand['of']} built nodes "
                  f"({hand.get('build_cov', 0):.0%})")
    if gradient:
        report["frames"] = recolour_frames(ng)
        report["gradient"] = gradient_nodes(ng)
        report["flow"] = recolour_flow(ng)
    report["frame_overlaps"] = frame_overlaps(ng)
    if verbose:
        print(f"[HT_LAYOUT]  {ng.name}: removed {report['loose']} loose, "
              f"{report['headroom']} frames given text room, "
              f"{report.get('packed', 0)} sections placed, "
              f"{report.get('gradient', 0)} nodes graded, "
              f"{report['frame_overlaps']} section overlaps, "
              f"{report['dead_ends']} dead ends left alone")
    return report


def frame_overlaps(ng):
    """How many SIBLING frames still overlap. The number the packer exists to
    drive to zero, so it is measured rather than assumed."""
    n = 0
    for scope in _scopes(ng):
        rects = list(frame_rects(ng, scope).values())
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                if _overlap(a, b):
                    n += 1
    return n
