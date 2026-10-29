# =============================================================================
#  GN_ToPython.py  -  export a Geometry Nodes group to EXECUTABLE Python
# =============================================================================
#
#  Paste into Blender's Text Editor. Open the geometry-node group in a Geometry
#  Nodes editor (so it is the active tree), or set GROUP_NAME. Run it. The
#  generated rebuild script lands on Your CLIPBOARD (and in a Text block).
#  Paste it into another Blender session and run it to rebuild the group(s).
#
#  Handles the things a naive dump gets wrong:
#    - SIMULATION / REPEAT ZONES: rebuilds the output's state items and pairs
#      the input to it, so the zone sockets actually exist before use
#    - topology enums (data_type / operation / domain / mode) set before defaults
#    - colour ramps (ShaderNodeValToRGB) - stops rebuilt, not dropped
#    - nested node groups - emitted first, in dependency order
#    - material / object pointers - fetched by name, created if absent
#
#  RESILIENCE: every property write, socket default, and link goes through a
#  guarded helper (_set / _sd / _lk) that skips-and-logs on failure instead of
#  aborting. After a rebuild, check the console for "skip ..." lines - they name
#  exactly which node still needs a handler. Nothing can hard-crash the build.
#
#  Read-only on Your scene. Pure bpy.
# =============================================================================

import bpy
import re

GROUP_NAME = ""       # "" = use the group currently open in the node editor
INCLUDE_SCENE = True  # also recreate the host object(s) + the empties the
                      # modifier inputs point at, so the effect works scene-to-scene
MESH_VERT_CAP = 4000  # meshes up to this many verts are rebuilt inline (carrier,
                      # instance sources); bigger ones become an empty placeholder
EMBED_IMAGES = True   # embed sprite-sheet pixels as base64 in the script, so the
                      # rebuild is self-contained (no missing-texture sprites).
                      # False = only reference by filepath (tiny script, but the
                      # recipient must have the same files on disk).
EMBED_IMAGE_MAX_MB = 12   # per-image ceiling; above this we fall back to a
                          # filepath reference and print a loud warning. Real
                          # sprite sheets land well under this (a 2048x512 DXT5
                          # sheet is ~0.4 MB as PNG); the cap exists so one
                          # freak 8K texture cannot produce a script no editor
                          # wants to open.


def _active_trees():
    """EVERY top-level group the effect uses, in modifier-stack order.

    An effect is often a STACK: 'Simple Trails - Base' then '- Resample Length'
    then '- Billboard Instancer' on the same object. Exporting only the first
    modifier (what this used to do) rebuilt one third of the trail and silently
    dropped the other two groups."""
    if GROUP_NAME and bpy.data.node_groups.get(GROUP_NAME):
        return [bpy.data.node_groups[GROUP_NAME]]
    tree = _active_tree()
    if tree is None:
        return []
    obj = bpy.context.object
    if obj:
        stack = [m.node_group for m in obj.modifiers
                 if m.type == 'NODES' and m.node_group]
        if stack:
            if len(stack) > 1:
                print(f"[GN export] '{obj.name}' has {len(stack)} Geometry "
                      f"Nodes modifiers - exporting the whole stack: "
                      f"{[g.name for g in stack]}")
            # de-dupe, keep stack order
            seen, out = set(), []
            for g in stack:
                if g.name not in seen:
                    seen.add(g.name)
                    out.append(g)
            return out
    return [tree]


def _active_tree():
    if GROUP_NAME and bpy.data.node_groups.get(GROUP_NAME):
        return bpy.data.node_groups[GROUP_NAME]
    # Prefer the TOP group of the ACTIVE OBJECT's Geometry Nodes modifier - that
    # is the whole effect (host object + modifier inputs + the object refs inside
    # its nodes). Exporting a sub-group You happen to have open in the editor
    # would miss the host and the empties wired at the modifier level, which is
    # exactly how Beam Start / Beam End got dropped. So: select the effect's
    # object, run this, and You get everything.
    obj = bpy.context.object
    if obj:
        for m in obj.modifiers:
            if m.type == 'NODES' and m.node_group:
                print(f"[GN export] exporting effect on active object "
                      f"'{obj.name}' -> top group '{m.node_group.name}'")
                return m.node_group
    # fallback: whatever group is open in the node editor
    for area in bpy.context.screen.areas:
        if area.type == 'NODE_EDITOR' and getattr(area.spaces.active, "edit_tree", None):
            t = area.spaces.active.edit_tree
            if t and t.bl_idname == 'GeometryNodeTree':
                print(f"[GN export] exporting node-editor group '{t.name}' "
                      f"(no host object active - modifier inputs won't be captured)")
                return t
    # LAST DITCH: nothing selected, no editor open. Guess the effect - the
    # biggest geometry-node group. Prefer one that an object actually applies
    # (a real top-level effect) over a stray/sub group of the same size.
    applied = set()
    for o in bpy.data.objects:
        for m in o.modifiers:
            if m.type == 'NODES' and m.node_group:
                applied.add(m.node_group.name)
    cands = [ng for ng in bpy.data.node_groups if ng.bl_idname == 'GeometryNodeTree']
    if not cands:
        return None
    applied_cands = [ng for ng in cands if ng.name in applied]
    pool = applied_cands or cands
    best = max(pool, key=lambda ng: len(ng.nodes))
    print(f"[GN export] nothing selected or open - guessing the biggest "
          f"{'applied ' if applied_cands else ''}group: '{best.name}' "
          f"({len(best.nodes)} nodes). Select the effect's object for a sure thing.")
    return best


def _collect(tree, seen, order):
    if tree.name in seen:
        return
    for n in tree.nodes:
        if n.bl_idname == 'GeometryNodeGroup' and n.node_tree:
            _collect(n.node_tree, seen, order)
    seen.add(tree.name)
    order.append(tree)


def _lit(v):
    if isinstance(v, bpy.types.Material):
        return f"_mat({v.name!r})"
    if isinstance(v, bpy.types.Object):
        return f"_obj({v.name!r})"
    if isinstance(v, bpy.types.Collection):
        return f"bpy.data.collections.get({v.name!r})"
    if isinstance(v, bpy.types.Image):
        return f"_imgref({v.name!r})"
    if isinstance(v, (bool, int, str)):
        return repr(v)
    # NO rounding: repr() of a Python float already round-trips exactly, while
    # round(v, 6) quietly mangles values - pi/2 came back as -1.570796 instead
    # of -1.5707963705062866, and every authored angle drifted.
    if isinstance(v, float):
        return repr(v)
    try:
        return "(" + ", ".join(repr(float(x)) for x in v) + ")"
    except TypeError:
        return None


_SKIP_PROP = {
    "location", "location_absolute", "width", "height", "dimensions", "name",
    "label", "parent", "type", "select", "hide", "mute", "color",
    "use_custom_color", "show_options", "show_preview", "show_texture",
    "internal_links", "inputs", "outputs", "node_tree", "color_ramp", "mapping",
    "paired_output", "active_index",
}
_PROP_PRIORITY = {"data_type": 0, "input_type": 1, "domain": 2, "mode": 3,
                  "component": 4, "clamp_type": 5, "operation": 6,
                  "rotation_type": 7, "interpolation_type": 8,
                  "factor_mode": 9, "mapping": 10}

# zone input nodes carry a paired_output; their matching output holds the items
_ZONE_INPUTS = {"GeometryNodeSimulationInput", "GeometryNodeRepeatInput",
                "GeometryNodeForeachGeometryElementInput"}


def _node_props(node):
    items = []
    for p in node.bl_rna.properties:
        pid = p.identifier
        if pid in _SKIP_PROP or pid.startswith("bl_") or p.is_readonly:
            continue
        if p.type not in {'ENUM', 'BOOLEAN', 'INT', 'FLOAT', 'STRING'}:
            continue
        try:
            val = getattr(node, pid)
        except Exception:
            continue
        lit = _lit(val)
        if lit is None:
            continue
        # Topology enums (input_type / data_type / domain / mode / ...) are
        # ALWAYS emitted. A freshly created node's real value frequently differs
        # from the RNA-reported default, so skipping on "== default" silently
        # left Switch nodes on Float instead of Geometry ("Conversion is not
        # supported: Geometry -> Float"). Non-topology props still skip when they
        # match the default, to keep the script small.
        if pid not in _PROP_PRIORITY:
            try:
                if val == getattr(p, "default", None):
                    continue
            except Exception:
                pass
        items.append((pid, lit))
    items.sort(key=lambda kv: _PROP_PRIORITY.get(kv[0], 100))
    return items


def _sock_index(socket, collection):
    for i, s in enumerate(collection):
        if s == socket:
            return i
    return -1


def _safe(name):
    return "".join(c if c.isalnum() else "_" for c in name)


def emit_tree_body(tree, L):
    """Emit interface + nodes + zones + defaults + parents + locations + links.
    Assumes `ng` (the target tree) is already defined in the generated function.
    Shared by geometry groups, shader groups, and material node trees."""
    L.append("    ng.nodes.clear()")
    L.append("    for _it in list(ng.interface.items_tree): ng.interface.remove(_it)")
    L.append("    _P = {}")
    for item in tree.interface.items_tree:
        kind = getattr(item, "item_type", "")
        # PANELS were skipped entirely, so a 30-input effect rebuilt as one flat
        # wall of fields instead of the author's collapsible groups.
        if kind == 'PANEL':
            L.append(f"    _P[{item.name!r}] = _panel(ng, {item.name!r}, "
                     f"{bool(getattr(item, 'default_closed', False))!r}, "
                     f"{(item.description or '')!r})")
            continue
        if kind != 'SOCKET':
            continue
        parent = getattr(item, "parent", None)
        pname = getattr(parent, "name", None) if parent is not None else None
        # The root panel has no name and must not be passed as a parent.
        L.append(f"    s = _newsock(ng, {item.name!r}, {item.in_out!r}, "
                 f"{item.socket_type!r}, _P.get({pname!r}))")
        st = getattr(item, "subtype", "")
        if st and st != 'NONE':
            L.append(f"    _set(s, 'subtype', {st!r})")
        if hasattr(item, "default_value"):
            lit = _lit(item.default_value)
            if lit is not None:
                L.append(f"    _set(s, 'default_value', {lit})")
        # Int sockets reject a float min/max - cast to the socket's own type.
        _is_int = 'Int' in getattr(item, "socket_type", "")
        for mm in ("min_value", "max_value"):
            if hasattr(item, mm):
                try:
                    raw = getattr(item, mm)
                    val = int(raw) if _is_int else round(float(raw), 6)
                    L.append(f"    _set(s, {mm!r}, {val!r})")
                except Exception:
                    pass
    L.append("    N = {}")
    for n in tree.nodes:
        key = n.name
        L.append(f"    n = ng.nodes.new({n.bl_idname!r}); n.name = {key!r}; N[{key!r}] = n")
        if n.label:
            L.append(f"    n.label = {n.label!r}")
        if getattr(n, "use_custom_color", False):
            L.append("    n.use_custom_color = True")
            try: L.append(f"    n.color = {_lit(n.color)}")
            except Exception: pass
        try:
            if float(n.width): L.append(f"    n.width = {round(float(n.width),1)}")
        except Exception: pass
        if n.bl_idname in ('GeometryNodeGroup', 'ShaderNodeGroup') and n.node_tree:
            L.append(f"    n.node_tree = bpy.data.node_groups.get({n.node_tree.name!r})")
        # POINTER properties are skipped by _node_props (it only walks ENUM /
        # BOOLEAN / INT / FLOAT / STRING), so an Image Texture node's image has
        # to be written explicitly. Without this every sprite sheet is dropped
        # and the sprites render untextured.
        _img = getattr(n, "image", None)
        if isinstance(_img, bpy.types.Image):
            L.append(f"    _set(n, 'image', _imgref({_img.name!r}))")
            iu = getattr(n, "image_user", None)
            if iu is not None:
                for a in ("frame_duration", "frame_start", "frame_offset",
                          "use_auto_refresh", "use_cyclic", "frame_current"):
                    if hasattr(iu, a):
                        try:
                            L.append(f"    _set(n.image_user, {a!r}, "
                                     f"{_lit(getattr(iu, a))})")
                        except Exception:
                            pass
        _pmat = getattr(n, "material", None)
        if isinstance(_pmat, bpy.types.Material):
            L.append(f"    _set(n, 'material', _mat({_pmat.name!r}))")
        for pid, lit in _node_props(n):
            L.append(f"    _set(n, {pid!r}, {lit})")
        if n.bl_idname == 'ShaderNodeValToRGB':
            cr = n.color_ramp
            L.append(f"    _set(n.color_ramp, 'color_mode', {cr.color_mode!r}); _set(n.color_ramp, 'interpolation', {cr.interpolation!r})")
            L.append("    while len(n.color_ramp.elements) > 1: n.color_ramp.elements.remove(n.color_ramp.elements[-1])")
            for i, e in enumerate(cr.elements):
                if i == 0:
                    L.append(f"    e = n.color_ramp.elements[0]; e.position = {round(e.position,6)}; e.color = {_lit(e.color)}")
                else:
                    L.append(f"    e = n.color_ramp.elements.new({round(e.position,6)}); e.color = {_lit(e.color)}")
    for n in tree.nodes:
        if n.bl_idname == 'GeometryNodeSimulationOutput':
            L.append(f"    _z = N[{n.name!r}]")
            L.append("    while len(_z.state_items): _z.state_items.remove(_z.state_items[-1])")
            for it in n.state_items:
                L.append(f"    _si = _z.state_items.new({it.socket_type!r}, {it.name!r})")
                dom = getattr(it, "attribute_domain", None)
                if dom:
                    L.append(f"    _set(_si, 'attribute_domain', {dom!r})")
        elif n.bl_idname == 'GeometryNodeRepeatOutput':
            L.append(f"    _z = N[{n.name!r}]")
            L.append("    while len(_z.repeat_items): _z.repeat_items.remove(_z.repeat_items[-1])")
            for it in n.repeat_items:
                L.append(f"    _z.repeat_items.new({it.socket_type!r}, {it.name!r})")
    for n in tree.nodes:
        if n.bl_idname in _ZONE_INPUTS:
            po = getattr(n, "paired_output", None)
            if po is not None:
                L.append(f"    _pair(N.get({n.name!r}), N.get({po.name!r}))")
    for n in tree.nodes:
        if n.bl_idname in ('GeometryNodeSimulationOutput', 'GeometryNodeRepeatOutput'):
            try:
                L.append(f"    _set(N[{n.name!r}], 'active_index', {int(n.active_index)})")
            except Exception:
                pass
    for n in tree.nodes:
        # A Reroute's socket is typeless plumbing with no writable default.
        if n.bl_idname == 'NodeReroute':
            continue
        for i, s in enumerate(n.inputs):
            # Write defaults even on LINKED sockets. The link wins while it is
            # there, but the stored value is what you see the moment anyone
            # unplugs it - dropping it silently reset authored values to 0/0.5/1.
            if not hasattr(s, "default_value"):
                continue
            lit = _lit(s.default_value)
            if lit is None:
                continue
            L.append(f"    _sd(N[{n.name!r}], {i}, {lit})")

        # ── OUTPUT socket defaults ──────────────────────────────────────
        #
        #  A CONSTANT NODE KEEPS ITS NUMBER ON ITS *OUTPUT*. Value, RGB,
        #  Input Vector / Integer / Bool / String and friends have no inputs
        #  at all - `outputs[0].default_value` IS the value. Writing only
        #  input defaults rebuilt every one of them as ZERO.
        #
        #  That was not a cosmetic loss. The sprite-sheet sequence table is
        #  built out of Value nodes, so a rebuilt effect got sequence length
        #  0 -> "length - 1" = -1 -> every sprite sampled tile -1, off the
        #  end of the sheet, and rendered INVISIBLE. It looked exactly like a
        #  broken material, and the material was fine.
        #
        #  LINKED OUTPUTS ARE WRITTEN TOO, and that is the whole point: a
        #  Value node's output is always linked to something, and its
        #  default_value is still where the number lives. On a computed node
        #  (Math, Compare) the stored value is simply ignored at evaluation
        #  time, so writing it costs nothing.
        for i, s in enumerate(n.outputs):
            if not hasattr(s, "default_value"):
                continue
            lit = _lit(s.default_value)
            if lit is None:
                continue
            L.append(f"    _sdo(N[{n.name!r}], {i}, {lit})")
    for n in tree.nodes:
        if n.parent:
            L.append(f"    _p = N.get({n.parent.name!r})\n    if _p: N[{n.name!r}].parent = _p")
    for n in tree.nodes:
        try:
            L.append(f"    N[{n.name!r}].location = ({round(n.location[0],1)}, {round(n.location[1],1)})")
        except Exception:
            pass
    for lk in tree.links:
        fi = _sock_index(lk.from_socket, lk.from_node.outputs)
        ti = _sock_index(lk.to_socket, lk.to_node.inputs)
        if fi < 0 or ti < 0:
            continue
        L.append(f"    _lk(ng, N[{lk.from_node.name!r}], {fi}, N[{lk.to_node.name!r}], {ti})")


def emit_group(tree, kind='GeometryNodeTree'):
    L = [f"def build_{_safe(tree.name)}():",
         f"    ng = bpy.data.node_groups.get({tree.name!r}) or bpy.data.node_groups.new({tree.name!r}, {kind!r})"]
    emit_tree_body(tree, L)
    L.append("    return ng")
    L.append("")
    return "\n".join(L)


def emit_material(mat):
    L = [f"def build_mat_{_safe(mat.name)}():",
         f"    m = bpy.data.materials.get({mat.name!r}) or bpy.data.materials.new({mat.name!r})",
         "    m.use_nodes = True"]
    for attr in ('blend_method', 'shadow_method', 'use_backface_culling',
                 'show_transparent_back', 'use_screen_refraction', 'diffuse_color',
                 # EEVEE Next (4.2+/5.x) - additive/blended sprites live here
                 'surface_render_method', 'use_transparent_shadow',
                 'use_raytrace_refraction', 'use_backface_culling_shadow',
                 'use_transparency_overlap', 'alpha_threshold',
                 'displacement_method'):
        if hasattr(mat, attr):
            try:
                lit = _lit(getattr(mat, attr))
                if lit is not None:
                    L.append(f"    _set(m, {attr!r}, {lit})")
            except Exception:
                pass
    L.append("    ng = m.node_tree")
    emit_tree_body(mat.node_tree, L)
    L.append("    return m")
    L.append("")
    return "\n".join(L)


def _gather_materials(geo_order, objs=None):
    """Materials the effect needs: Set Material sockets inside the geometry
    groups PLUS the material slots of every object we rebuild. Slot materials
    matter for instance-source cards (the sprite quad an Object Info node
    points at) - miss them and the card instances with no material at all."""
    mats = {}
    for t in geo_order:
        for n in t.nodes:
            for s in n.inputs:
                dv = getattr(s, "default_value", None)
                if isinstance(dv, bpy.types.Material):
                    mats[dv.name] = dv
    for o in (objs or {}).values():
        for slot in getattr(o, "material_slots", []):
            if slot.material is not None:
                mats[slot.material.name] = slot.material
                print(f"[GN export] material '{slot.material.name}' "
                      f"(slot on '{o.name}')")
    return mats


def _gather_images(trees):
    """Every image datablock referenced by a texture node in any of *trees*."""
    imgs = {}
    for t in trees:
        if t is None:
            continue
        for n in t.nodes:
            im = getattr(n, "image", None)
            if isinstance(im, bpy.types.Image) and im.source != 'VIEWER':
                imgs[im.name] = im
    return imgs


def _image_bytes(img):
    """Encode an image's pixels to file bytes. PNG for normal sprite sheets,
    OpenEXR when the image is float so HDR data survives. Returns (bytes, fmt)
    or (None, None)."""
    import os
    import tempfile
    fmt = 'OPEN_EXR' if getattr(img, "is_float", False) else 'PNG'
    ext = '.exr' if fmt == 'OPEN_EXR' else '.png'
    tmp = os.path.join(tempfile.gettempdir(), f"_gn_export_{abs(hash(img.name))}{ext}")
    cp = None
    try:
        cp = img.copy()
        cp.file_format = fmt
        cp.filepath_raw = tmp
        cp.save()
        with open(tmp, 'rb') as fh:
            return fh.read(), fmt
    except Exception as e:
        print(f"[GN export] could not encode image '{img.name}': {e}")
        return None, None
    finally:
        if cp is not None:
            try: bpy.data.images.remove(cp)
            except Exception: pass
        try: os.remove(tmp)
        except Exception: pass


def emit_images(imgs):
    """Emit build_images(): recreate every sprite sheet the materials use.

    THE BUG THIS FIXES: the old exporter emitted bpy.data.images.get(name),
    which is None in a fresh file. Image Texture nodes came back with no image
    and every sprite rendered as an untextured card."""
    import base64
    L = ["def build_images():"]
    if not imgs:
        L.append("    pass"); L.append(""); return "\n".join(L)
    for img in imgs.values():
        try:
            path = bpy.path.abspath(img.filepath) if img.filepath else ""
        except Exception:
            path = ""
        b64 = ""
        fmt = "PNG"
        if EMBED_IMAGES:
            data, fmt2 = _image_bytes(img)
            if data:
                mb = len(data) / (1024 * 1024)
                if mb <= EMBED_IMAGE_MAX_MB:
                    b64 = base64.b64encode(data).decode('ascii')
                    fmt = fmt2
                    print(f"[GN export] embedded image '{img.name}' "
                          f"({img.size[0]}x{img.size[1]}, {mb:.1f} MB as {fmt2})")
                else:
                    print(f"[GN export] WARNING image '{img.name}' is {mb:.1f} MB "
                          f"(cap {EMBED_IMAGE_MAX_MB} MB) - referencing by path "
                          f"instead. The recipient needs the file at: {path or '<none>'}")
        if not b64 and not path:
            print(f"[GN export] WARNING image '{img.name}' has no embedded data "
                  f"and no file on disk - sprites using it will render untextured.")
        cs = getattr(img.colorspace_settings, "name", "sRGB")
        L.append(f"    _b = (")
        if b64:
            for i in range(0, len(b64), 1000):
                L.append(f"        {b64[i:i + 1000]!r}")
        else:
            L.append("        ''")
        L.append("    )")
        L.append(f"    _img_load({img.name!r}, _b, {fmt!r}, {cs!r}, "
                 f"{img.alpha_mode!r}, {path!r})")
    L.append("")
    return "\n".join(L)


def _gather_shader_groups(mats):
    seen, order = set(), []
    def walk(tree):
        for n in tree.nodes:
            if n.bl_idname == 'ShaderNodeGroup' and n.node_tree and n.node_tree.name not in seen:
                seen.add(n.node_tree.name)
                walk(n.node_tree)
                order.append(n.node_tree)
    for m in mats.values():
        if getattr(m, "use_nodes", False) and m.node_tree:
            walk(m.node_tree)
    return order


_HEADER = '''import bpy

def _set(o, attr, val):
    try: setattr(o, attr, val)
    except Exception as e: print(f"  skip {getattr(o,'name',o)}.{attr} = {val!r}: {e}")

def _sd(node, i, val):
    try: node.inputs[i].default_value = val
    except Exception as e: print(f"  skip default {getattr(node,'name','?')}.in[{i}]: {e}")

def _sdo(node, i, val):
    # A constant node (Value, RGB, Input Vector/Integer/Bool) keeps its number
    # on its OUTPUT socket. Skipping these rebuilt every one of them as zero.
    try: node.outputs[i].default_value = val
    except Exception as e: print(f"  skip default {getattr(node,'name','?')}.out[{i}]: {e}")

def _lk(ng, a, ai, b, bi):
    try: ng.links.new(a.outputs[ai], b.inputs[bi])
    except Exception as e: print(f"  skip link {getattr(a,'name','?')}[{ai}]->{getattr(b,'name','?')}[{bi}]: {e}")

def _pair(inp, out):
    try: inp.pair_with_output(out)
    except Exception as e: print(f"  skip pair {getattr(inp,'name','?')}: {e}")

def _panel(ng, name, closed=False, description=""):
    """Recreate an interface PANEL (the collapsible groups in the modifier UI)."""
    try:
        p = ng.interface.new_panel(name, default_closed=closed)
        if description:
            try: p.description = description
            except Exception: pass
        return p
    except Exception as e:
        print(f"  skip panel {name!r}: {e}")
        return None

def _newsock(ng, name, in_out, socket_type, panel=None):
    """new_socket(), placed inside its panel when it had one."""
    if panel is not None:
        try:
            return ng.interface.new_socket(name, in_out=in_out,
                                           socket_type=socket_type, parent=panel)
        except Exception as e:
            print(f"  socket {name!r} could not join its panel: {e}")
    return ng.interface.new_socket(name, in_out=in_out, socket_type=socket_type)

def _link(o):
    try:
        if o.name not in bpy.context.scene.collection.objects:
            bpy.context.scene.collection.objects.link(o)
    except Exception: pass

def _vis(o, vis):
    """Restore visibility. Instance-source cards are usually hidden in the
    render - miss this and the source quad shows up in frame."""
    if not vis: return
    for attr, val in vis.items():
        if attr == 'hide_get':
            try: o.hide_set(bool(val))
            except Exception as e: print(f"  skip {o.name}.hide_set: {e}")
        else:
            _set(o, attr, val)

def _slots(o, mats):
    """Assign material slots by name (order matters - geometry indexes them)."""
    if not mats or not getattr(o, "data", None): return
    try:
        o.data.materials.clear()
        for mn in mats:
            o.data.materials.append(_mat(mn) if mn else None)
    except Exception as e:
        print(f"  skip material slots on {o.name}: {e}")

def _ensure_obj(name, loc, rot, scale, edisp, esize, vis=None):
    o = bpy.data.objects.get(name)
    if o is None:
        o = bpy.data.objects.new(name, None)   # empty placeholder
    try: o.location, o.rotation_euler, o.scale = loc, rot, scale
    except Exception: pass
    if o.type == 'EMPTY':
        try: o.empty_display_type, o.empty_display_size = edisp, esize
        except Exception: pass
    _link(o); _vis(o, vis)
    return o

def _ensure_mesh_obj(name, verts, edges, faces, loc, rot, scale,
                     uvs=None, mats=None, vis=None):
    o = bpy.data.objects.get(name)
    # A placeholder EMPTY from an earlier partial run cannot become a mesh -
    # an object's type is fixed at creation, so drop it and build properly.
    if o is not None and o.type != 'MESH':
        print(f"  replacing non-mesh placeholder '{name}' with real geometry")
        try: bpy.data.objects.remove(o, do_unlink=True); o = None
        except Exception as e: print(f"  skip replace {name}: {e}")
    if o is None:
        me = bpy.data.meshes.new(name + "_mesh")
        try: me.from_pydata(verts, edges, faces); me.update()
        except Exception as e: print(f"  skip mesh data {name}: {e}")
        for uvname, coords in (uvs or []):
            try:
                lay = me.uv_layers.get(uvname) or me.uv_layers.new(name=uvname)
                for i, c in enumerate(coords):
                    if i < len(lay.data): lay.data[i].uv = c
            except Exception as e: print(f"  skip uv layer {uvname} on {name}: {e}")
        o = bpy.data.objects.new(name, me)
    try: o.location, o.rotation_euler, o.scale = loc, rot, scale
    except Exception: pass
    _slots(o, mats); _link(o); _vis(o, vis)
    return o

def _img_load(name, b64, fmt, colorspace, alpha_mode, filepath):
    """Rebuild an image datablock. Embedded pixels first (self-contained), then
    the original filepath. Without this the sprite sheets come back EMPTY and
    every sprite renders as a flat untextured card."""
    im = bpy.data.images.get(name)
    if im is not None and im.has_data:
        return im
    if b64:
        import base64, os, tempfile
        ext = '.exr' if fmt == 'OPEN_EXR' else '.png'
        tmp = os.path.join(tempfile.gettempdir(), f"_gn_img_{abs(hash(name))}{ext}")
        try:
            with open(tmp, 'wb') as fh:
                fh.write(base64.b64decode(b64))
            im = bpy.data.images.load(tmp)
            im.name = name
            try: im.pack()
            except Exception as e: print(f"  image {name} pack failed: {e}")
            try: im.filepath_raw = ''
            except Exception: pass
        except Exception as e:
            print(f"  embedded image {name} FAILED: {e}")
            im = None
        finally:
            try: os.remove(tmp)
            except Exception: pass
    if im is None and filepath:
        try: im = bpy.data.images.load(filepath, check_existing=True); im.name = name
        except Exception as e: print(f"  image {name} not found at {filepath}: {e}")
    if im is None:
        print(f"  !! image '{name}' could not be rebuilt - sprites using it "
              f"will render untextured")
        return None
    try: im.colorspace_settings.name = colorspace
    except Exception as e: print(f"  skip colorspace {name}: {e}")
    _set(im, 'alpha_mode', alpha_mode)
    return im

def _imgref(name):
    im = bpy.data.images.get(name)
    if im is None:
        print(f"  !! image '{name}' missing when wiring a texture node")
    return im

def _ensure_coll(name):
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        try: bpy.context.scene.collection.children.link(c)
        except Exception: pass
    return c

def _addcon(o, ctype):
    if not o: return None
    try: return o.constraints.new(ctype)
    except Exception as e:
        print(f"  skip constraint {ctype} on {getattr(o,'name','?')}: {e}"); return None

def _add_gn(host, group_name, mod_name='GeometryNodes'):
    """Add ONE geometry-nodes modifier, keeping its original name.

    The name matters: keyframe data paths are modifiers["<name>"]..., so a
    modifier the user called 'shotgun' must come back as 'shotgun'. Modifiers
    are added in call order, which preserves the evaluation stack."""
    if not host: return None
    for mm in list(host.modifiers):
        if mm.type == 'NODES' and mm.node_group and mm.node_group.name == group_name:
            host.modifiers.remove(mm)
    m = host.modifiers.new(mod_name, 'NODES')
    m.node_group = bpy.data.node_groups.get(group_name)
    if m.name != mod_name:
        print(f"  note: modifier renamed {mod_name!r} -> {m.name!r} (name taken)")
    return m

def _mod_socket(mod, ident):
    """Blender 5.x exposes modifier inputs as mod.properties.inputs.<ident>
    with a .value. The old mod[ident] IDProperty access was REMOVED in 5.x -
    it raises 'id properties not supported for this type'. Returns None on
    pre-5.x builds so callers can fall back."""
    try:
        return getattr(mod.properties.inputs, ident)
    except Exception:
        return None

def _minput(mod, ident, val):
    if mod is None: return False
    s = _mod_socket(mod, ident)
    if s is not None:
        try:
            s.value = val
            return True
        except Exception as e:
            print(f"  skip modifier input {ident}: {e}")
            return False
    try:
        mod[ident] = val                      # pre-5.x
        return True
    except Exception as e:
        print(f"  skip modifier input {ident}: {e}")
        return False

def _mod_idents(mod):
    if not mod or not mod.node_group: return []
    return [it.identifier for it in mod.node_group.interface.items_tree
            if getattr(it, 'item_type', '') == 'SOCKET' and it.in_out == 'INPUT']

def _set_input(mod, pos, val):
    ids = _mod_idents(mod)
    if pos >= len(ids):
        print(f"  skip input pos {pos}: group has {len(ids)} inputs"); return
    _minput(mod, ids[pos], val)

def _mod_dp(mod, ident):
    """Keyframe data path for a modifier input, version aware."""
    if _mod_socket(mod, ident) is not None:
        return 'modifiers["%s"].properties.inputs.%s.value' % (mod.name, ident)
    return 'modifiers["%s"]["%s"]' % (mod.name, ident)

def _anim(obj, mod, pos, array_index, keys):
    try:
        if not obj or not mod or not mod.node_group: return
        ids = _mod_idents(mod)
        if pos >= len(ids):
            print(f"  skip anim: input pos {pos} out of range"); return
        ident = ids[pos]
        dp = _mod_dp(mod, ident)
        # Scalars are NOT arrays in 5.x - passing index=0 raises "is not an
        # array". Probe once and key with or without the index accordingly.
        cur = None
        try: cur = obj.path_resolve(dp)
        except Exception: pass
        is_array = hasattr(cur, "__len__") and not isinstance(cur, str)
        # keyframe_insert works on classic AND 4.4+ layered actions and builds
        # the action/layer for us. Set the value, then key it at each frame.
        # F-curve values are always float; a Bool/Int socket rejects that.
        def _coerce(v):
            if isinstance(cur, bool): return bool(round(float(v)))
            if isinstance(cur, int): return int(round(float(v)))
            return v
        for k in keys:
            _minput(mod, ident, _coerce(k[1]) if not is_array else k[1])
            try:
                if is_array:
                    obj.keyframe_insert(data_path=dp, index=array_index,
                                        frame=int(round(k[0])))
                else:
                    obj.keyframe_insert(data_path=dp, frame=int(round(k[0])))
            except Exception as e: print(f"  skip key @{k[0]}: {e}")
        # best-effort interpolation (works on classic + layered actions)
        try:
            for _fc in _fcurves(obj):
                if _fc.data_path != dp:
                    continue
                if is_array and _fc.array_index != array_index:
                    continue
                for kp in _fc.keyframe_points:
                    for k in keys:
                        if abs(kp.co[0] - k[0]) < 0.5:
                            kp.interpolation = k[2]
                _fc.update()
        except Exception:
            pass
        print(f"  animated input pos {pos} ({ident}) - {len(keys)} keys")
    except Exception as e:
        print(f"  skip anim pos {pos}: {e}")

def _fcurves(obj):
    """Yield an object's fcurves across classic and 4.4+ layered actions."""
    ad = getattr(obj, "animation_data", None)
    act = getattr(ad, "action", None)
    if act is None: return
    fcs = getattr(act, "fcurves", None)
    if fcs is not None:
        for fc in fcs: yield fc
        return
    try:
        slots = list(getattr(act, "slots", []))
        for layer in getattr(act, "layers", []):
            for strip in getattr(layer, "strips", []):
                bags = list(getattr(strip, "channelbags", []) or [])
                if not bags:
                    for sl in slots:
                        try: cb = strip.channelbag(sl)
                        except Exception: cb = None
                        if cb: bags.append(cb)
                for cb in bags:
                    for fc in getattr(cb, "fcurves", []): yield fc
    except Exception:
        return

def _mat(name):
    m = bpy.data.materials.get(name)
    if m:
        return m
    import random
    m = bpy.data.materials.new(name)          # preview dupe - random colour
    col = (random.random(), random.random(), random.random(), 1.0)
    try:
        m.use_nodes = True
        bsdf = m.node_tree.nodes.get("Principled BSDF")
        if bsdf:
            if "Base Color" in bsdf.inputs: bsdf.inputs["Base Color"].default_value = col
            if "Emission Color" in bsdf.inputs: bsdf.inputs["Emission Color"].default_value = col
            if "Emission Strength" in bsdf.inputs: bsdf.inputs["Emission Strength"].default_value = 1.0
        m.diffuse_color = col
    except Exception as e:
        print(f"  mat preview colour failed for {name}: {e}")
    return m

def _obj(name):
    """Resolve an object pointer for a node socket. build_objects() runs BEFORE
    the node groups, so this normally finds the real object. The placeholder is
    a safety net: returning None here silently blanks an Object Info socket and
    that whole branch of the effect renders nothing."""
    o = bpy.data.objects.get(name)
    if o is None:
        print(f"  object '{name}' missing - creating placeholder empty")
        o = bpy.data.objects.new(name, None)
        _link(o)
    return o

'''



def _iter_fcurves(action):
    """Yield an Action's fcurves across Blender versions. Classic actions expose
    .fcurves; 4.4+ layered actions hide them under layers/strips/channelbags."""
    if action is None:
        return
    fcs = getattr(action, "fcurves", None)
    if fcs is not None:
        for fc in fcs:
            yield fc
        return
    try:
        slots = list(getattr(action, "slots", []))
        for layer in getattr(action, "layers", []):
            for strip in getattr(layer, "strips", []):
                bags = list(getattr(strip, "channelbags", []) or [])
                if not bags:
                    for sl in slots:
                        try: cb = strip.channelbag(sl)
                        except Exception: cb = None
                        if cb: bags.append(cb)
                for cb in bags:
                    for fc in getattr(cb, "fcurves", []):
                        yield fc
    except Exception:
        return


def _read_mod_input(mod, ident):
    """Read a geometry-nodes modifier input. Returns (value, error_or_None).

    Blender 5.x moved these to mod.properties.inputs.<ident>.value and REMOVED
    the old mod[ident] IDProperty access, so a 5.x export that only tried the
    old way silently captured NOTHING - every Lifetime / Gravity / Count came
    back at its default."""
    try:
        return getattr(mod.properties.inputs, ident).value, None
    except Exception as e5:
        try:
            return mod[ident], None            # pre-5.x
        except Exception:
            return None, e5


def _gather_scene(trees, order):
    """Collect objects the effect needs: hardcoded object sockets inside the
    groups, the host object(s) that apply any of the TOP groups, and the objects
    their modifier inputs point at. Returns (objs, colls, host_specs).

    *trees* is the modifier STACK (a list) - an effect is frequently several
    Geometry Nodes modifiers on one object, and every one of them has to come
    across with its own name, inputs and keyframes."""
    if not isinstance(trees, (list, tuple)):
        trees = [trees]
    top_names = {t.name for t in trees}
    objs = {}
    colls = {}
    # (A) objects/collections hardcoded on node sockets inside any group
    for t in order:
        for n in t.nodes:
            for s in n.inputs:
                if not hasattr(s, "default_value"):
                    continue
                dv = s.default_value
                if isinstance(dv, bpy.types.Object):
                    objs[dv.name] = dv
                elif isinstance(dv, bpy.types.Collection):
                    colls[dv.name] = dv
    # (B) host objects that apply THIS group + their modifier inputs
    host_specs = []
    hosts_found = 0
    for o in bpy.data.objects:
        for m in o.modifiers:
            if m.type != 'NODES' or not m.node_group or m.node_group.name not in top_names:
                continue
            tree = m.node_group          # THIS modifier's group, not "the" group
            hosts_found += 1
            objs[o.name] = o
            print(f"[GN export] host '{o.name}' modifier '{m.name}' "
                  f"applies '{tree.name}'")
            inputs = []
            iface_inputs = [it for it in tree.interface.items_tree
                            if getattr(it, "item_type", "") == 'SOCKET' and it.in_out == 'INPUT']
            ident_to_pos = {}
            for pos, item in enumerate(iface_inputs):
                ident = getattr(item, "identifier", None)
                if ident:
                    ident_to_pos[ident] = pos
                if getattr(item, "socket_type", "") == 'NodeSocketGeometry' or not ident:
                    continue
                val, err = _read_mod_input(m, ident)
                if err:
                    print(f"[GN export]   input[{pos}] {ident} ({item.name}) UNREADABLE: {err}")
                    continue
                if isinstance(val, bpy.types.Object):
                    objs[val.name] = val
                    inputs.append((pos, "object", val.name))
                    print(f"[GN export]   input[{pos}] {item.name} -> object '{val.name}'")
                elif isinstance(val, bpy.types.Collection):
                    colls[val.name] = val
                    inputs.append((pos, "collection", val.name))
                    print(f"[GN export]   input[{pos}] {item.name} -> collection '{val.name}'")
                elif val is None:
                    pass
                else:
                    lit = _lit(val)
                    if lit is not None:
                        inputs.append((pos, "lit", lit))
            # animation on modifier inputs - the trigger keyframes (e.g. 'Activate').
            # Fully guarded + version-agnostic (4.4+ dropped Action.fcurves).
            anim = []
            try:
              ad = getattr(o, "animation_data", None)
              act = getattr(ad, "action", None) if ad else None
              for fc in _iter_fcurves(act):
                    dp = getattr(fc, "data_path", "") or ""
                    ident2 = None
                    mm = re.match(r'modifiers\["([^"]+)"\]\["([^"]+)"\]', dp)
                    if mm and mm.group(1) == m.name:
                        ident2 = mm.group(2)
                    else:
                        mm2 = re.search(r'modifiers\["([^"]+)"\].*?inputs\.([^.]+)\.value', dp)
                        if mm2 and mm2.group(1) == m.name:
                            ident2 = mm2.group(2)
                    if ident2 is None:
                        continue
                    pos = ident_to_pos.get(ident2)
                    if pos is None:
                        print(f"[GN export]   anim on {ident2}: no matching input - skipped")
                        continue
                    keys = []
                    for kp in fc.keyframe_points:
                        keys.append((round(kp.co[0], 4), round(kp.co[1], 6), kp.interpolation,
                                     round(kp.handle_left[0], 4), round(kp.handle_left[1], 6),
                                     round(kp.handle_right[0], 4), round(kp.handle_right[1], 6)))
                    anim.append((pos, fc.array_index, keys))
                    print(f"[GN export]   captured TRIGGER keyframes on input[{pos}] ({len(keys)} keys)")
            except Exception as _e:
                print(f"[GN export]   animation capture skipped: {_e}")
            # Carry the modifier's REAL name: keyframe data paths are written
            # as modifiers["<name>"]..., and a user-named modifier ('shotgun')
            # coming back as 'GeometryNodes' breaks every path that referenced it.
            host_specs.append((o.name, tree.name, inputs, anim, m.name))
    # (D) empties sharing a host's collection - the effect's control points and
    #     Start/End endpoints live alongside the carrier. This is the reliable
    #     catch-all: it grabs them no matter how they are wired (modifier input,
    #     node socket, or nothing). Only EMPTY objects, so cameras/lights/meshes
    #     in the collection are left alone.
    for host_name, _g, _i, _a, _mn in host_specs:
        hobj = bpy.data.objects.get(host_name)
        if not hobj:
            continue
        for coll in getattr(hobj, "users_collection", []):
            for co in coll.objects:
                if co.type == 'EMPTY' and co.name not in objs:
                    objs[co.name] = co
                    print(f"[GN export] pulled in empty '{co.name}' "
                          f"(shares collection '{coll.name}' with host '{host_name}')")

    # (C) constraint closure: bring in objects constrained TO what we already
    #     have, and the targets those objects are constrained to. Two-way, so a
    #     Beam Start/End empty locked to the carrier gets pulled in even though
    #     it is neither a node ref nor a modifier input.
    def _con_targets(o):
        out = []
        for c in getattr(o, "constraints", []):
            t = getattr(c, "target", None)
            if isinstance(t, bpy.types.Object): out.append(t)
            for st in getattr(c, "targets", []):
                tt = getattr(st, "target", None)
                if isinstance(tt, bpy.types.Object): out.append(tt)
        return out
    changed = True
    while changed:
        changed = False
        have = set(objs)
        # reverse: any scene object constrained to one we already have
        for o in bpy.data.objects:
            if o.name in objs:
                continue
            if any(t.name in have for t in _con_targets(o)):
                objs[o.name] = o; changed = True
                print(f"[GN export] pulled in '{o.name}' (constrained to a captured object)")
        # forward: targets of constraints on objects we have
        for o in list(objs.values()):
            for t in _con_targets(o):
                if t.name not in objs:
                    objs[t.name] = t; changed = True
                    print(f"[GN export] pulled in '{t.name}' (constraint target)")

    if hosts_found == 0:
        print(f"[GN export] WARNING: nothing in the scene applies group '{tree.name}' "
              f"via a Geometry Nodes modifier. The empties wired to the modifier "
              f"(Start/End points) cannot be captured. Fix: keep the host object in "
              f"the scene and export the TOP group (the one on the modifier), not a "
              f"sub-group.")
    print(f"[GN export] objects to rebuild: {sorted(objs)}")
    if colls:
        print(f"[GN export] collections: {sorted(colls)}")
    return objs, colls, host_specs


_VIS_ATTRS = ("hide_viewport", "hide_render", "visible_camera", "visible_shadow",
              "visible_diffuse", "visible_glossy", "visible_transmission",
              "visible_volume_scatter")


def _vis_spec(o):
    """Capture visibility. Instance-source cards are typically hidden in the
    render; losing that puts a bare quad in frame."""
    spec = {}
    for a in _VIS_ATTRS:
        if hasattr(o, a):
            try:
                spec[a] = bool(getattr(o, a))
            except Exception:
                pass
    try:
        spec["hide_get"] = bool(o.hide_get())
    except Exception:
        pass
    return spec


def emit_objects(objs, colls, host_specs):
    """Emit build_objects(): every object the effect needs, with real geometry.

    Runs BEFORE the node groups so _obj() resolves to a live object instead of
    None (that silent None is what blanked the Object Info sockets)."""
    L = ["def build_objects():"]
    if not objs and not colls:
        L.append("    pass"); L.append(""); return "\n".join(L)
    for c in colls:
        L.append(f"    _ensure_coll({c!r})")
    for o in objs.values():
        loc = tuple(round(float(x), 4) for x in o.location)
        rot = tuple(round(float(x), 4) for x in o.rotation_euler)
        scl = tuple(round(float(x), 4) for x in o.scale)
        vis = _vis_spec(o)
        # RULE: ANY mesh under the cap is rebuilt with real geometry - the
        # modifier host (carrier) AND the instance-source cards an Object Info
        # node points at. Only non-meshes and oversized meshes become empties.
        if o.type == 'MESH' and o.data and len(o.data.vertices) <= MESH_VERT_CAP:
            me = o.data
            verts = [tuple(round(float(c), 5) for c in v.co) for v in me.vertices]
            faces = [tuple(p.vertices) for p in me.polygons]
            edges = [] if faces else [tuple(e.vertices) for e in me.edges]
            uvs = []
            for lay in getattr(me, "uv_layers", []):
                try:
                    uvs.append((lay.name,
                                [(round(float(d.uv[0]), 5), round(float(d.uv[1]), 5))
                                 for d in lay.data]))
                except Exception as e:
                    print(f"[GN export] uv layer '{lay.name}' on '{o.name}' skipped: {e}")
            slot_mats = [s.material.name if s.material else None
                         for s in getattr(o, "material_slots", [])]
            L.append(f"    _ensure_mesh_obj({o.name!r}, {verts}, {edges}, {faces}, "
                     f"{loc}, {rot}, {scl}, {uvs!r}, {slot_mats!r}, {vis!r})")
        else:
            if o.type == 'MESH':
                print(f"[GN export] WARNING '{o.name}' has "
                      f"{len(o.data.vertices)} verts (cap {MESH_VERT_CAP}) - "
                      f"rebuilt as an empty placeholder, geometry NOT carried.")
            ed = getattr(o, "empty_display_type", 'PLAIN_AXES') if o.type == 'EMPTY' else 'PLAIN_AXES'
            es = round(float(getattr(o, "empty_display_size", 1.0)), 4) if o.type == 'EMPTY' else 1.0
            L.append(f"    _ensure_obj({o.name!r}, {loc}, {rot}, {scl}, "
                     f"{ed!r}, {es}, {vis!r})")
    L.append("")
    return "\n".join(L)


def emit_scene(objs, colls, host_specs):
    """Emit build_scene(): constraints, modifiers, inputs, keyframes. Runs LAST
    (the node groups must exist before a modifier can point at them)."""
    L = ["def build_scene():"]
    if not objs and not colls and not host_specs:
        L.append("    pass"); L.append(""); return "\n".join(L)
    try:
        _scn = bpy.context.scene
        L.append(f"    bpy.context.scene.frame_start = {int(_scn.frame_start)}")
        L.append(f"    bpy.context.scene.frame_end = {int(_scn.frame_end)}")
    except Exception:
        pass
    # constraints (all target objects now exist)
    _CON_SKIP = {"target", "name", "type", "is_valid", "error_location",
                 "error_rotation", "is_override_data", "active", "influence"}
    for o in objs.values():
        cons = list(getattr(o, "constraints", []))
        if not cons:
            continue
        for c in cons:
            L.append(f"    _c = _addcon(bpy.data.objects.get({o.name!r}), {c.type!r})")
            L.append(f"    _set(_c, 'name', {c.name!r})")
            tgt = getattr(c, "target", None)
            if isinstance(tgt, bpy.types.Object):
                L.append(f"    _set(_c, 'target', bpy.data.objects.get({tgt.name!r}))")
            L.append(f"    _set(_c, 'influence', {round(float(getattr(c,'influence',1.0)),4)})")
            for p in c.bl_rna.properties:
                pid = p.identifier
                if pid in _CON_SKIP or pid.startswith("bl_") or p.is_readonly:
                    continue
                if p.type not in {'ENUM', 'BOOLEAN', 'INT', 'FLOAT', 'STRING'}:
                    continue
                try:
                    val = getattr(c, pid)
                    if val == getattr(p, "default", None):
                        continue
                    lit = _lit(val)
                    if lit is not None:
                        L.append(f"    _set(_c, {pid!r}, {lit})")
                except Exception:
                    pass
    # Modifiers are added in capture order, which IS the stack order - a trail
    # is Base -> Resample -> Instancer and evaluating them out of order gives
    # you a different (wrong) effect.
    for host_name, group_name, inputs, anim, mod_name in host_specs:
        L.append(f"    _h = bpy.data.objects.get({host_name!r})")
        L.append(f"    _m = _add_gn(_h, {group_name!r}, {mod_name!r})")
        for pos, kind, val in inputs:
            if kind == "object":
                L.append(f"    _set_input(_m, {pos}, bpy.data.objects.get({val!r}))")
            elif kind == "collection":
                L.append(f"    _set_input(_m, {pos}, bpy.data.collections.get({val!r}))")
            else:
                L.append(f"    _set_input(_m, {pos}, {val})")
        for (pos, ai, keys) in anim:
            L.append(f"    _anim(_h, _m, {pos}, {ai}, {keys!r})")
    L.append("")
    return "\n".join(L)


def export(tree):
    """*tree* may be one group or the whole modifier stack (a list)."""
    trees = list(tree) if isinstance(tree, (list, tuple)) else [tree]
    seen, order = set(), []
    for t in trees:
        _collect(t, seen, order)                 # geometry groups, deps first

    # Scene FIRST: the objects we rebuild also tell us which slot materials to
    # carry (an instance-source card's material lives on the slot, not on a
    # Set Material socket).
    objs, colls, host_specs = ({}, {}, [])
    if INCLUDE_SCENE:
        objs, colls, host_specs = _gather_scene(trees, order)

    mats = _gather_materials(order, objs)        # geo sockets + object slots
    shader_groups = _gather_shader_groups(mats)  # shader node groups they use
    mat_trees = [m.node_tree for m in mats.values()
                 if getattr(m, "use_nodes", False) and m.node_tree]
    imgs = _gather_images(mat_trees + list(shader_groups) + list(order))

    parts = [_HEADER]
    parts.append(emit_images(imgs))              # sprite sheets before anything
    for g in shader_groups:                      # shader groups (deps-first)
        parts.append(emit_group(g, 'ShaderNodeTree'))
    for m in mats.values():                      # then the materials themselves
        parts.append(emit_material(m))

    have_objects = bool(objs or colls)
    if have_objects:
        parts.append(emit_objects(objs, colls, host_specs))

    for t in order:                              # then geometry groups
        parts.append(emit_group(t, 'GeometryNodeTree'))

    scene_call = ""
    if objs or colls or host_specs:
        parts.append(emit_scene(objs, colls, host_specs))
        scene_call = "build_scene()"

    parts.append("# build order: images -> shader groups -> materials -> "
                 "objects -> geometry -> scene")
    parts.append("# objects come BEFORE the geometry groups so object sockets "
                 "(Object Info) resolve to real objects instead of None.")
    parts.append("build_images()")
    for g in shader_groups:
        parts.append(f"build_{_safe(g.name)}()")
    for m in mats.values():
        parts.append(f"build_mat_{_safe(m.name)}()")
    if have_objects:
        parts.append("build_objects()")
    for t in order:
        parts.append(f"build_{_safe(t.name)}()")
    if scene_call:
        parts.append("# modifiers + inputs + trigger keyframes (groups now exist)")
        parts.append(scene_call)
    parts.append("")
    return "\n".join(parts)


def main():
    """Export the active effect. Returns the Text block name, or None if there
    was nothing to export (the caller reports that as an error - do NOT print
    a 'copied' banner when nothing was found)."""
    trees = _active_trees()
    if not trees:
        print("=" * 62)
        print("  NOTHING TO EXPORT - no geometry node group in this session.")
        print("  Select the object carrying the effect's Geometry Nodes")
        print("  modifier, or open its group in a Geometry Nodes editor.")
        print("=" * 62)
        return None
    code = export(trees)
    name = f"{trees[0].name}__rebuild.py"
    tb = bpy.data.texts.get(name) or bpy.data.texts.new(name)
    tb.clear(); tb.write(code)
    copied = True
    try:
        bpy.context.window_manager.clipboard = code
    except Exception as e:
        copied = False
        print(f"[GN export] clipboard write FAILED: {e}")
    print("=" * 62)
    if copied:
        print(f"  COPIED TO CLIPBOARD  -  {len(code):,} characters")
        print(f"  Paste (Ctrl+V) into a fresh Blender Text Editor and Run Script.")
    else:
        print(f"  Clipboard didn't take - open the Text block instead:")
    print(f"  Also saved as Text block:  '{name}'")
    print("=" * 62)
    return name


def main_geo(embed_images=True):
    """GEOMETRY NODES export, texture embedding chosen explicitly.

    The four one-click operators route here / to main_material so each button
    does EXACTLY ONE THING - no flags to misread. EMBED_IMAGES is restored
    afterwards, so the classic main() keeps its module-default behaviour."""
    global EMBED_IMAGES
    keep = EMBED_IMAGES
    EMBED_IMAGES = bool(embed_images)
    try:
        return main()
    finally:
        EMBED_IMAGES = keep


def export_material(mat):
    """A standalone script that rebuilds ONE material - its shader groups and
    (per EMBED_IMAGES) its textures. Same helper preamble as the full export."""
    mats = {mat.name: mat}
    shader_groups = _gather_shader_groups(mats)
    mat_trees = [m.node_tree for m in mats.values()
                 if getattr(m, "use_nodes", False) and m.node_tree]
    imgs = _gather_images(mat_trees + list(shader_groups))
    parts = [_HEADER]
    parts.append(emit_images(imgs))
    for g in shader_groups:
        parts.append(emit_group(g, 'ShaderNodeTree'))
    parts.append(emit_material(mat))
    parts.append("build_images()")
    for g in shader_groups:
        parts.append(f"build_{_safe(g.name)}()")
    parts.append(f"build_mat_{_safe(mat.name)}()")
    parts.append("")
    return "\n".join(parts)


def _active_material():
    """The material to export: the active object's active slot, else its
    first filled slot, else the material open in a Shader Editor."""
    ob = getattr(bpy.context, "object", None)
    if ob is not None:
        m = ob.active_material
        if m is not None:
            return m
        for slot in getattr(ob, "material_slots", []):
            if slot.material is not None:
                return slot.material
    space = getattr(bpy.context, "space_data", None)
    if getattr(space, "type", "") == "NODE_EDITOR":
        idb = getattr(space, "id", None)
        if isinstance(idb, bpy.types.Material):
            return idb
    return None


def main_material(embed_images=True):
    """SHADER NODES export: the active material only. Returns the Text block
    name, or None when there is no material to export."""
    global EMBED_IMAGES
    mat = _active_material()
    if mat is None or not getattr(mat, "use_nodes", False):
        print("=" * 62)
        print("  NOTHING TO EXPORT - no material found. Select an object")
        print("  wearing the material (its active material slot is used).")
        print("=" * 62)
        return None
    keep = EMBED_IMAGES
    EMBED_IMAGES = bool(embed_images)
    try:
        code = export_material(mat)
    finally:
        EMBED_IMAGES = keep
    name = f"{mat.name}__material_rebuild.py"
    tb = bpy.data.texts.get(name) or bpy.data.texts.new(name)
    tb.clear()
    tb.write(code)
    copied = True
    try:
        bpy.context.window_manager.clipboard = code
    except Exception as e:
        copied = False
        print(f"[GN export] clipboard write FAILED: {e}")
    print("=" * 62)
    if copied:
        print(f"  COPIED TO CLIPBOARD  -  {len(code):,} characters")
        print("  Paste (Ctrl+V) into a fresh Blender Text Editor and Run Script.")
    else:
        print("  Clipboard didn't take - open the Text block instead:")
    print(f"  Also saved as Text block:  '{name}'")
    print("=" * 62)
    return name


if __name__ == "__main__":
    main()