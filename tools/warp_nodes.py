# =============================================================================
#  tools/warp_nodes.py  -  Source Refract -> Blender warp material
# =============================================================================
#
#  A Refract particle is not a picture, it is a DISTORTION. Source renders the
#  scene, then bends it through the material's normal map - heat haze, shock
#  rings, droplets on the lens. There is no $basetexture at all; the image is
#  $normalmap and it is data, not colour.
#
#  🔴 THE CORE IS THE PREPARED REFERENCE SETUP, PORTED FAITHFULLY - the
#  finished droplet material in `__Developer/Shader Nodes/Refract/`, node for
#  node, label for label, INCLUDING its material settings. The generated
#  version that preceded it was invisible in practice for two reasons that
#  graph checks cannot catch:
#
#    1. It multiplied alpha by the `sprite_alpha` INSTANCER attribute
#       EVERYWHERE - on any mesh that is not an instanced particle the
#       attribute reads 0, so alpha was 0 and the material drew NOTHING.
#       (The sprite_color black-probe bug, again, on the other socket.)
#    2. It skipped `blend_method`/`use_transparent_shadow`/`thickness_mode`,
#       which the reference sets (HASHED / True / SPHERE).
#
#  So: the registered group and the material carry NO particle plumbing by
#  default - drop them on any mesh and they refract. The particle attributes
#  are added ONLY on the system paths (`particle_attrs=True`), where the
#  emitters genuinely store them.
#
#  ⚠️ $refractamount IS NOT AN IOR. It scales the X/Y deviation encoded in
#  the normal map, sign preserved - negative reverses the warp. Blender's
#  IOR must still be >1 for the lobe to bend anything, so "Warp IOR" is a
#  separate control labelled [NOT SFM], exactly as in the reference.
# =============================================================================

import bpy

from .sprite_nodes import _nd, _lk, _sv, _sock, note

WARP_GROUP = 'HoovyTube\'s "REFRACT" shader group'


def _in(node, name, occurrence=0):
    found = [s for s in node.inputs if s.name == name]
    return found[occurrence] if occurrence < len(found) else None


def _set_named(node, name, value):
    """Set a socket BY NAME - Principled indices shift across versions."""
    s = _in(node, name)
    if s is None:
        return False
    try:
        s.default_value = value
        return True
    except Exception as exc:
        print(f"[HT_WARP]  {node.name}.{name}: {exc}")
        return False


def _lkn(nt, a, ai, b, name):
    s = _in(b, name)
    if s is None:
        print(f"[HT_WARP]  missing input {b.name}.{name}")
        return
    try:
        nt.links.new(a.outputs[ai], s)
    except Exception as exc:
        print(f"[HT_WARP]  link {a.name}[{ai}]->{b.name}.{name}: {exc}")


def warp_group():
    """The registered refract core - the reference setup's WARP VECTOR and
    REFRACTION sections, with its parameter Value nodes promoted to group
    inputs (same names, same defaults). Fetch-or-build, NEVER cleared once
    it exists: clearing a shared group's interface kills every link into it."""
    ng = bpy.data.node_groups.get(WARP_GROUP)
    if ng is not None and len(ng.nodes) > 3:
        return ng
    if ng is None:
        ng = bpy.data.node_groups.new(WARP_GROUP, "ShaderNodeTree")

    _sock(ng, "BSDF", "OUTPUT", "NodeSocketShader")
    _sock(ng, "Normal Map Color", "INPUT", "NodeSocketColor",
          (0.5, 0.5, 1.0, 1.0))
    _sock(ng, "Normal Map Alpha", "INPUT", "NodeSocketFloat", 1.0)
    _sock(ng, "Refract Amount [SFM: $refractamount]", "INPUT",
          "NodeSocketFloat", -1.25)
    _sock(ng, "Blur Amount [SFM: $bluramount]", "INPUT",
          "NodeSocketFloat", 1.0)
    _sock(ng, "Refract Tint [SFM: $refracttint]", "INPUT",
          "NodeSocketColor", (1.0, 1.0, 1.0, 1.0))
    _sock(ng, "Warp IOR [NOT SFM]", "INPUT", "NodeSocketFloat", 1.1)
    _sock(ng, "Blur Scale [NOT SFM]", "INPUT", "NodeSocketFloat", 0.08)
    _sock(ng, "Mask Multiplier [NOT SFM]", "INPUT", "NodeSocketFloat", 1.0)

    gi = _nd(ng, "NodeGroupInput", (-1200, 0))
    go = _nd(ng, "NodeGroupOutput", (1240, 0))
    I = {s.name: i for i, s in enumerate(gi.outputs)}

    # ── WARP · $refractamount × normal XY  (reference, node for node) ────
    sep = _nd(ng, "ShaderNodeSeparateColor", (-880, 260),
              "Separate Normal RGB", role="OPERATOR", mode="RGB")
    _lk(ng, gi, I["Normal Map Color"], sep, 0)

    r2 = _nd(ng, "ShaderNodeMath", (-700, 400), "R × 2", role="OPERATOR",
             operation="MULTIPLY")
    _sv(r2, 1, 2.0)
    _lk(ng, sep, 0, r2, 0)
    rx = _nd(ng, "ShaderNodeMath", (-540, 400), "X = R×2 - 1",
             role="OPERATOR", operation="SUBTRACT")
    _sv(rx, 1, 1.0)
    _lk(ng, r2, 0, rx, 0)
    rxa = _nd(ng, "ShaderNodeMath", (-380, 400), "X × $refractamount",
              role="OPERATOR", operation="MULTIPLY")
    _lk(ng, rx, 0, rxa, 0)
    _lk(ng, gi, I["Refract Amount [SFM: $refractamount]"], rxa, 1)

    g2 = _nd(ng, "ShaderNodeMath", (-700, 240), "G × 2", role="OPERATOR",
             operation="MULTIPLY")
    _sv(g2, 1, 2.0)
    _lk(ng, sep, 1, g2, 0)
    gy = _nd(ng, "ShaderNodeMath", (-540, 240), "Y = G×2 - 1",
             role="OPERATOR", operation="SUBTRACT")
    _sv(gy, 1, 1.0)
    _lk(ng, g2, 0, gy, 0)
    gya = _nd(ng, "ShaderNodeMath", (-380, 240), "Y × $refractamount",
              role="OPERATOR", operation="MULTIPLY")
    _lk(ng, gy, 0, gya, 0)
    _lk(ng, gi, I["Refract Amount [SFM: $refractamount]"], gya, 1)

    b2 = _nd(ng, "ShaderNodeMath", (-700, 80), "B × 2", role="OPERATOR",
             operation="MULTIPLY")
    _sv(b2, 1, 2.0)
    _lk(ng, sep, 2, b2, 0)
    bz = _nd(ng, "ShaderNodeMath", (-540, 80), "Z = B×2 - 1",
             role="OPERATOR", operation="SUBTRACT")
    _sv(bz, 1, 1.0)
    _lk(ng, b2, 0, bz, 0)

    combine = _nd(ng, "ShaderNodeCombineXYZ", (-200, 260),
                  "Scaled Tangent Normal", role="OPERATOR")
    _lk(ng, rxa, 0, combine, 0)
    _lk(ng, gya, 0, combine, 1)
    _lk(ng, bz, 0, combine, 2)
    normalize = _nd(ng, "ShaderNodeVectorMath", (-40, 260),
                    "Normalize Tangent Normal", role="OPERATOR",
                    operation="NORMALIZE")
    _lk(ng, combine, 0, normalize, 0)
    enc_half = _nd(ng, "ShaderNodeVectorMath", (120, 260), "Encode × 0.5",
                   role="OPERATOR", operation="SCALE")
    _lk(ng, normalize, 0, enc_half, 0)
    _sv(enc_half, 3, 0.5)
    encode = _nd(ng, "ShaderNodeVectorMath", (280, 260), "Encode + 0.5",
                 role="OPERATOR", operation="ADD")
    _lk(ng, enc_half, 0, encode, 0)
    _sv(encode, 1, (0.5, 0.5, 0.5))
    nmap = _nd(ng, "ShaderNodeNormalMap", (440, 260),
               "Tangent Normal -> Blender", role="RENDERER", space="TANGENT")
    _lkn(ng, encode, 0, nmap, "Color")
    _set_named(nmap, "Strength", 1.0)

    # ── REFRACTION / TRANSPARENCY  (reference, node for node) ────────────
    principled = _nd(ng, "ShaderNodeBsdfPrincipled", (800, 160),
                     "WARP · Principled Transmission", role="RENDERER")
    _set_named(principled, "Metallic", 0.0)
    _set_named(principled, "Coat Weight", 0.0)
    if not _set_named(principled, "Transmission Weight", 1.0):
        _set_named(principled, "Transmission", 1.0)
    _lkn(ng, nmap, 0, principled, "Normal")
    _lkn(ng, gi, I["Refract Tint [SFM: $refracttint]"], principled,
         "Base Color")
    _lkn(ng, gi, I["Warp IOR [NOT SFM]"], principled, "IOR")

    blur_mul = _nd(ng, "ShaderNodeMath", (440, -20),
                   "$bluramount -> Roughness [APPROX]", role="OPERATOR",
                   operation="MULTIPLY")
    _lk(ng, gi, I["Blur Amount [SFM: $bluramount]"], blur_mul, 0)
    _lk(ng, gi, I["Blur Scale [NOT SFM]"], blur_mul, 1)
    rclamp = _nd(ng, "ShaderNodeClamp", (600, -20), "Clamp Roughness 0..1",
                 role="OPERATOR")
    _lk(ng, blur_mul, 0, rclamp, 0)
    _lkn(ng, rclamp, 0, principled, "Roughness")

    amul = _nd(ng, "ShaderNodeMath", (440, -180), "Alpha × Mask Multiplier",
               role="OPERATOR", operation="MULTIPLY")
    _lk(ng, gi, I["Normal Map Alpha"], amul, 0)
    _lk(ng, gi, I["Mask Multiplier [NOT SFM]"], amul, 1)
    aclamp = _nd(ng, "ShaderNodeClamp", (600, -180), "Final Alpha",
                 role="OPERATOR")
    _lk(ng, amul, 0, aclamp, 0)
    _lkn(ng, aclamp, 0, principled, "Alpha")

    _lk(ng, principled, 0, go, 0)

    note(ng, 'HoovyTube\'s "REFRACT" shader group', "RENDERER", """
The prepared reference setup, registered: feed it a normal map's COLOUR and
ALPHA and it answers with the finished refract BSDF. Drop it into any
material - it carries no particle plumbing, so it works on a plain mesh.

WARP · $refractamount × normal XY
    x = (R*2 - 1) * $refractamount        NOT an IOR, sign preserved -
    y = (G*2 - 1) * $refractamount        negative reverses the warp.
    z = (B*2 - 1)
normalized, re-encoded 0..1, into a Tangent Normal Map node.

REFRACTION / TRANSPARENCY
    One Principled at Transmission 1. $bluramount x Blur Scale -> Roughness
    [APPROX]. Alpha x Mask Multiplier -> the REAL Alpha socket - the Mask
    Multiplier doesn't disturb an alpha channel that is not carried.
    Warp IOR [NOT SFM]: the lobe needs >1 to bend rays at all.
""", [sep, r2, rx, rxa, g2, gy, gya, b2, bz, combine, normalize, enc_half,
      encode, nmap, principled, blur_mul, rclamp, amul, aclamp])
    return ng


def build_warp_material(name, image, cols=1, rows=1, uv_group=None,
                        refract_amount=0.2, blur_amount=0.0,
                        tint=(1.0, 1.0, 1.0, 1.0), particle_attrs=True):
    """The warp material: the reference setup around the registered group.

    particle_attrs=True is for SYSTEM materials only - it multiplies in the
    sprite_alpha / sprite_color INSTANCER attributes the emitters store.
    🔴 NEVER set it on a material meant for a plain mesh: an instancer
    attribute that nobody stored reads 0, and alpha x 0 renders NOTHING -
    that is exactly the invisible-material bug this port fixes."""
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()

    # Every material setting from the reference .blend, guarded per Blender
    # generation. HASHED + transparent shadow + SPHERE thickness are part of
    # why the reference draws where the generated version did not.
    for attr, val in (("blend_method", "HASHED"),
                      ("surface_render_method", "DITHERED"),
                      ("use_transparency_overlap", True),
                      ("use_backface_culling", False),
                      ("show_transparent_back", True),
                      ("use_screen_refraction", True),
                      ("use_raytrace_refraction", True),
                      ("use_transparent_shadow", True),
                      ("alpha_threshold", 0.5),
                      ("thickness_mode", "SPHERE")):
        try:
            setattr(mat, attr, val)
        except Exception:
            pass

    # 🔴 A NORMAL MAP MUST NOT BE GAMMA-TRANSFORMED. sRGB bends the encoded
    # vectors and the warp direction comes out subtly, uniformly wrong.
    try:
        image.colorspace_settings.name = "Non-Color"
    except Exception as exc:
        print(f"[HT_WARP]  could not set Non-Color on {image.name}: {exc}")

    # ── SOURCE NORMAL MAP, as in the reference ───────────────────────────
    tex = _nd(nt, "ShaderNodeTexImage", (-700, 160),
              "Normal Map [SFM: $normalmap]", role="RENDERER",
              interpolation="Linear",
              extension="CLIP" if uv_group is not None else "REPEAT")
    tex.image = image

    plumbing = [tex]
    if uv_group is not None:
        a_frame = _nd(nt, "ShaderNodeAttribute", (-1160, 260), "sprite_frame",
                      role="SEQUENCE", attribute_type="INSTANCER",
                      attribute_name="sprite_frame")
        uvg = _nd(nt, "ShaderNodeGroup", (-920, 160), "sheet lookup",
                  role="SEQUENCE")
        uvg.node_tree = uv_group
        _lk(nt, a_frame, 2, uvg, 0)
        _sv(uvg, 1, float(cols))
        _sv(uvg, 2, float(rows))
        _lk(nt, uvg, 0, tex, 0)
        plumbing += [a_frame, uvg]
    else:
        uv = _nd(nt, "ShaderNodeTexCoord", (-920, 160), "UV Coordinates",
                 role="RENDERER")
        _lk(nt, uv, 2, tex, 0)
        plumbing.append(uv)

    # ── THE registered group, with the .vmt's numbers on its inputs ──────
    core = _nd(nt, "ShaderNodeGroup", (-160, 60), WARP_GROUP,
               role="RENDERER")
    core.node_tree = warp_group()
    _lkn(nt, tex, 0, core, "Normal Map Color")
    _set_named(core, "Refract Amount [SFM: $refractamount]",
               float(refract_amount))
    _set_named(core, "Blur Amount [SFM: $bluramount]", float(blur_amount))
    _set_named(core, "Refract Tint [SFM: $refracttint]", tuple(tint))

    if particle_attrs:
        # SYSTEM plumbing: fade and tint per particle, exactly like the
        # sprite material. Only here - the emitters store these attributes.
        a_alpha = _nd(nt, "ShaderNodeAttribute", (-700, -160), "sprite_alpha",
                      role="OPERATOR", attribute_type="INSTANCER",
                      attribute_name="sprite_alpha")
        a_col = _nd(nt, "ShaderNodeAttribute", (-700, -360), "sprite_color",
                    role="INITIALIZER", attribute_type="INSTANCER",
                    attribute_name="sprite_color")
        amul = _nd(nt, "ShaderNodeMath", (-460, -120),
                   "mask x particle fade", role="OPERATOR",
                   operation="MULTIPLY")
        _lk(nt, tex, 1, amul, 0)
        _lk(nt, a_alpha, 2, amul, 1)
        _lkn(nt, amul, 0, core, "Normal Map Alpha")

        tint_rgb = _nd(nt, "ShaderNodeRGB", (-700, -560),
                       "Refract Tint [SFM: $refracttint]", role="INITIALIZER")
        tint_rgb.outputs[0].default_value = tuple(tint)
        tintmix = _nd(nt, "ShaderNodeMix", (-460, -400),
                      "tint x particle colour", role="INITIALIZER",
                      data_type="RGBA", blend_type="MULTIPLY")
        _sv(tintmix, 0, 1.0)
        _lk(nt, tint_rgb, 0, tintmix, 6)
        _lk(nt, a_col, 0, tintmix, 7)
        _lkn(nt, tintmix, 2, core, "Refract Tint [SFM: $refracttint]")
        plumbing += [a_alpha, a_col, amul, tint_rgb, tintmix]
    else:
        _lkn(nt, tex, 1, core, "Normal Map Alpha")

    out = _nd(nt, "ShaderNodeOutputMaterial", (160, 60), "Material Output",
              role="OUTPUT")
    _lk(nt, core, 0, out, 0)

    note(nt, "SOURCE NORMAL MAP  ·  the picture is data", "SEQUENCE", """
A Refract material has NO $basetexture. Its image is $normalmap - encoded
surface directions, not colour - forced Non-Color here: sRGB would bend
every vector and warp everything subtly wrong.

The refraction itself is the REGISTERED group on the right - the prepared
reference setup, reusable in any material. This material only feeds it the
picture""" + (""" and the per-particle fade/tint attributes the emitters
store (sprite_alpha / sprite_color, read as INSTANCER).""" if particle_attrs
             else """. No particle attributes here: this variant works on
any plain mesh, sphere or card.""") + "\n",
         plumbing + [core, out])

    # Breadcrumbs for whoever inspects the material later.
    mat["source_shader"] = "Refract"
    mat["source_refractamount"] = float(refract_amount)
    mat["source_bluramount"] = float(blur_amount)
    return mat


def configure_eevee_refraction(scene):
    """Scene-side switches a refractive material needs in EEVEE - the same
    ones the reference .blend has on. Best effort; Cycles needs none."""
    eevee = getattr(scene, "eevee", None)
    if eevee is None:
        return
    for attr, val in (("use_raytracing", True),
                      ("use_ssr", True),
                      ("use_ssr_refraction", True)):
        try:
            setattr(eevee, attr, val)
        except Exception:
            pass
    try:
        eevee.ray_tracing_method = "SCREEN"
    except Exception:
        pass
