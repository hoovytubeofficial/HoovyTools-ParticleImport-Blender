# =============================================================================
#  operators/op_vmt.py  -  import a MATERIAL, not just a texture
# =============================================================================
#
#  WHY THIS EXISTS
#  ---------------
#  The .vmt parser has been in `tools/vmt.py` for a while doing real work -
#  it is how a .pcf import knows a beam is additive and fifteen times
#  overbright - but there was NO WAY TO SEE IT WORK. It only ever ran deep
#  inside a .pcf import, so when a material came out looking wrong there was
#  nothing to point at.
#
#  These two are the .vtf pair with the material step put back in front:
#
#      Import VTF                straight to the picture. No material.
#      Import VTF + Build Sprite       ... and a probe emitter wearing it
#      Import VMT                the CHAIN: .vmt -> $basetexture -> .vtf
#      Import VMT + Build Sprite       ... and a probe built the way the
#                                      material says to build it
#
#  The VMT half is the sophisticated one: `$additive` decides whether black is
#  transparent, `$overbrightfactor` decides how hot it burns, and neither is
#  guessable from the .vtf alone. Same picture, correct material.
# =============================================================================

from pathlib import Path

import bpy
from bpy.props import (BoolProperty, CollectionProperty, EnumProperty,
                       FloatProperty, IntProperty, StringProperty)
from bpy.types import Operator, OperatorFileListElement
from bpy_extras.io_utils import ImportHelper

from . import op_prefs
from ..tools import vmt as vmt_tool
from ..tools import warp_nodes
from .op_vtf import (ROOT_COLLECTION, VTF_COLLECTION, SHADER_ITEMS,
                     vtf_collection, vtf_to_image, _preview_sphere)
from .op_vtf_sprite import build_sprite_probe

TAG = "[HT_VMT]"


def _roots(vmt_path=None):
    """Every `materials` folder worth looking in, the .vmt's own first.

    A material handed over on its own - dropped in a folder with its texture,
    outside any SFM install - still has to resolve, and its own directory is
    the one place its texture is guaranteed to be."""
    from .op_particle_import import _material_roots
    found = list(_material_roots())
    if vmt_path is not None:
        here = Path(vmt_path).parent
        found.insert(0, here)
        # ...and whatever `materials` folder it lives under, so a reference
        # like "__hoovytube/generic/beam_bm" resolves from a deep .vmt.
        for parent in Path(vmt_path).parents:
            if parent.name.lower() == "materials":
                found.insert(1, parent)
                break
    return found


def read_material(path):
    """Parse one .vmt and say what it means. Raises nothing.

    Besides the chain, this decides the material's FAMILY once, for everyone:
    `material_class` is "SPRITE" (emissive card - spritecard, unlitgeneric,
    ...) or "WARP" (refract - the picture is a normal map and the particle is
    a distortion), and `warp` carries the refract numbers when it is one."""
    chain = vmt_tool.resolve_path(path, _roots(path))
    chain["overbright"] = vmt_tool.overbright(chain["values"])
    chain["additive"] = vmt_tool.is_additive(chain["values"])
    chain["blend"] = vmt_tool.blend_mode(chain["values"])    # 0.24.0: the real flags
    chain["material_class"] = vmt_tool.material_class(
        chain["shader"], chain["texture_key"])
    chain["warp"] = (vmt_tool.warp_params(chain["values"])
                     if chain["material_class"] == "WARP" else None)
    return chain


#  The extension filter every builder that can take EITHER shares, so adding a
#  format is one edit rather than four that drift apart.
SOURCE_GLOB = "*.vmt;*.vtf"


def resolve_source(path):
    """Take a .vmt OR a .vtf and return what a system builder needs.

    -> dict(vtf, overbright, additive, note, vmt)

    🔴 THIS IS THE BRIDGE THAT WAS MISSING. The .vmt parser has been reading
    `$overbrightfactor` and `$additive` correctly for a long time, but ONLY on
    the .pcf import path - the three Create Renderer System operators filtered
    `*.vtf` and could not be handed a material at all. So a rope hand-built
    from `beam_bm.vtf` came out at overbright 1 with the sheet's black drawn
    as opaque black, which is the exact bug that was fixed for imports and
    still fully present for anyone building one by hand.

    A .vtf on its own is still perfectly valid - it is a picture with no
    material, so the neutral 1.0 / False is the honest answer for it, and that
    is what `note` says out loud rather than pretending a material was read."""
    def result(vtf=None, overbright=1.0, additive=False, vmt=None,
               material_class="SPRITE", warp=None, note=""):
        return {"vtf": vtf, "overbright": overbright, "additive": additive,
                "vmt": vmt, "material_class": material_class, "warp": warp,
                "note": note}

    path = Path(path)
    if path.suffix.lower() == ".vmt":
        chain = read_material(path)
        if not chain["shader"]:
            return result(vmt=path,
                          note=f"{path.name} is not a readable .vmt")
        if chain["vtf"] is None:
            ref = chain["texture_ref"] or "(no texture named)"
            return result(vmt=path,
                          note=(f"{path.name}: {chain['shader']} -> {ref} - "
                                f"that .vtf is not on disk"))
        return result(vtf=chain["vtf"], overbright=chain["overbright"],
                      additive=chain["additive"], vmt=path,
                      material_class=chain["material_class"],
                      warp=chain["warp"],
                      note=(f"{path.name} -> {chain['vtf'].name} "
                            f"({describe(chain)})"))

    if not path.is_file():
        return result(note=f"Not a file: {path}")
    return result(vtf=path,
                  note=f"{path.name} - a .vtf on its own, so no material "
                       f"settings (pick its .vmt for $overbrightfactor and "
                       f"$additive)")


def describe(chain):
    """The one-line summary both operators report."""
    bits = [f"shader {chain['shader'] or '?'}"]
    warp = chain.get("warp")
    if warp:
        bits.append(f"WARP a{warp['refract_amount']:g}")
        if warp["blur_amount"]:
            bits.append(f"blur {warp['blur_amount']:g}")
    if abs(chain["overbright"] - 1.0) > 1e-6:
        bits.append(f"overbright {chain['overbright']:g}")
    if chain["additive"]:
        bits.append("additive")
    return ", ".join(bits)


class _VMTBase(Operator, ImportHelper):
    """Shared browsing: start where the textures live, filter to .vmt."""
    filename_ext = ".vmt"
    filter_glob: StringProperty(default="*.vmt", options={"HIDDEN"})

    def invoke(self, context, event):
        if not self.filepath:
            start = op_prefs.texture_dir()
            if start is not None:
                self.filepath = str(start) + "\\"
                print(f"{TAG}  VMT browser starting at {start}")
        return super().invoke(context, event)

    def _resolved(self):
        """(chain, error). NEVER guesses a texture - half a chain is a
        different problem from no chain, and saying which is the point."""
        path = Path(self.filepath)
        if not path.is_file():
            return None, f"Not a file: {path}"
        chain = read_material(path)
        if not chain["shader"]:
            return None, f"{path.name} is not a readable .vmt"
        if chain["vtf"] is None:
            ref = chain["texture_ref"] or "(no texture named)"
            return None, (f"{path.name}: {chain['shader']} -> {ref} - "
                          f"that .vtf is not on disk")
        return chain, None


class HTP_OT_ImportVMT(_VMTBase):
    """Follow a Source material to its texture and import that

Reads the .vmt, finds what $basetexture points at, decodes that .vtf and
packs it into the .blend - the same chain a .pcf import walks.

Tells you what the material actually says: its shader, its
$overbrightfactor and whether it is $additive. Those three are why the
same texture looks right in one material and wrong in another, and none
of them can be read off the .vtf.

A Refract material has no $basetexture at all - its picture is $normalmap,
which this follows instead, and the image is imported Non-Color because it
is data, not colour.

Use this when an imported effect has the right picture on it and still
looks wrong."""
    bl_idname = "htp.import_vmt"
    bl_label = "Import VMT"
    bl_options = {"REGISTER", "UNDO"}

    #  ON BY DEFAULT: seeing the material on something is the point of the
    #  import - opting OUT is the secondary choice, not opting in.
    preview_sphere: BoolProperty(
        name="Preview on a Sphere",
        description="Also drop a UV sphere wearing the texture, in "
                    "__HoovyTools__ / VTF Imports. Untick for a data-only "
                    "import",
        default=True,
    )
    shader: EnumProperty(
        name="Shader", items=SHADER_ITEMS, default="AUTO",
        description="Auto follows the .vmt's own shader; the other three "
                    "FORCE a family, which is the comparison worth having "
                    "when a material looks wrong",
    )

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "preview_sphere")
        col.separator()
        col.label(text="Shader:")
        col.prop(self, "shader", expand=True)

    def execute(self, context):
        chain, err = self._resolved()
        if err:
            self.report({"ERROR"}, err)
            print(f"{TAG}  {err}")
            return {"CANCELLED"}
        try:
            img, info = vtf_to_image(chain["vtf"])
        except Exception as exc:
            self.report({"ERROR"}, f"{chain['vtf'].name}: {exc}")
            return {"CANCELLED"}

        #  THE SHADER BUTTONS OVERRIDE THE FILE. Auto keeps the .vmt's own
        #  family; Refract forces the warp build even on a sprite material
        #  (default $refractamount when the file has none); UnlitGeneric /
        #  SpriteCard force the emissive-sprite family even on a Refract.
        family = chain["material_class"]
        warp = chain["warp"]
        if self.shader == "REFRACT":
            family = "WARP"
            warp = warp or vmt_tool.warp_params(chain["values"])
        elif self.shader in ("UNLIT", "SHEET"):
            family = "SPRITE"
            warp = None

        warp_mat = None
        if family == "WARP":
            # The picture is a normal map. Mark it as data even on the plain
            # import, so whatever material gets built on it later starts
            # right rather than subtly gamma-bent.
            try:
                img.colorspace_settings.name = "Non-Color"
                print(f"{TAG}  {img.name}: normal-map data -> Non-Color")
            except Exception as exc:
                print(f"{TAG}  could not set Non-Color: {exc}")
            # 🔴 BUILD THE SHADER, NOT JUST THE PICTURE. Importing a Refract
            # material and leaving only a texture behind reads as "nothing
            # happened" - the whole point of the .vmt is the warp. This
            # registers the reference shader group and a material instancing
            # it. particle_attrs=False ON PURPOSE: this material goes on
            # plain meshes (the preview sphere, whatever the user assigns it
            # to), and multiplying by instancer attributes nobody stored is
            # exactly the alpha-0 invisibility bug.
            w = warp
            warp_mat = warp_nodes.build_warp_material(
                f"VMT Warp · {chain['vtf'].stem} · a{w['refract_amount']:g}",
                img, particle_attrs=False, **w)
            warp_nodes.configure_eevee_refraction(context.scene)
            print(f"{TAG}  warp material built: {warp_mat.name}  "
                  f"(shader group: {warp_nodes.WARP_GROUP})")

        print(f"{TAG}  {Path(self.filepath).name} -> {chain['vtf'].name}  "
              f"({describe(chain)})")
        for k, v in sorted(chain["values"].items()):
            print(f"{TAG}     {k} = {v}")

        if self.preview_sphere:
            try:
                #  Auto on a sprite .vmt previews UNLIT - a Source sprite is
                #  an emissive card, and lighting the preview like a plaster
                #  ball misreads every additive sheet. The crop to a single
                #  tile is driven by the .VTF's OWN sheet table (info["grid"]),
                #  NOT the .vmt shader name: an UnlitGeneric spark sheet is a
                #  sheet exactly as much as a SpriteCard one, and keying the
                #  crop on shader == "spritecard" made every other sheet
                #  preview wear the whole grid.
                if self.shader != "AUTO":
                    sphere_shader = self.shader
                elif family == "WARP":
                    sphere_shader = "REFRACT"
                else:
                    sphere_shader = "SHEET" if info.get("grid") else "UNLIT"
                coll = vtf_collection(context)
                _preview_sphere(context, img, index=len(coll.objects),
                                collection=coll, shader=sphere_shader,
                                grid=info.get("grid"), warp_mat=warp_mat)
            except Exception as exc:
                print(f"{TAG}  preview sphere failed: {exc}")

        self.report({"INFO"},
                    f"{Path(self.filepath).stem}: {describe(chain)} -> "
                    f"{img.name} {img.size[0]}x{img.size[1]}"
                    + (f" · warp material + {warp_nodes.WARP_GROUP}"
                       if warp_mat is not None else ""))
        return {"FINISHED"}


class HTP_OT_ImportVMTSprite(_VMTBase):
    """Follow a Source material to its texture and build a probe wearing it

Everything Import VMT does, plus a small REAL system: the same organised
geo-node graph Create RAS builds - sections, notes, operator panels,
stateless emitter so you can scrub anywhere - with each card playing a
random sequence from the VTF's own table.

THE DIFFERENCE FROM THE VTF VERSION IS THE MATERIAL. This one builds the
shader the way the .vmt says to: $overbrightfactor sets how hot it burns,
and $additive makes BLACK TRANSPARENT rather than opaque - which is why
additive sheets ship with a useless solid-1 alpha and look like a bright
blob on a black rectangle when that is ignored.

A Refract .vmt builds a WARP material instead: the normal map bends
whatever renders behind each card ($refractamount, sign preserved),
because a refract particle is a distortion, not a picture. Needs EEVEE
ray tracing or Cycles, with something behind the cards to bend.

This is the honest preview of how a sheet will look inside a real
effect."""
    bl_idname = "htp.import_vmt_sprite"
    bl_label = "Import VMT + Build Sprite"
    bl_options = {"REGISTER", "UNDO"}

    particles: IntProperty(
        name="Particles", description="How many particles are alive at once",
        default=12, min=1, max=512)
    lifespan: FloatProperty(
        name="Lifespan", description="Seconds each particle lives",
        default=5.0, min=0.01)
    fade_in: FloatProperty(
        name="Fade In", description="Seconds spent fading up from invisible",
        default=0.5, min=0.0)
    fade_out: FloatProperty(
        name="Fade Out", description="Seconds spent fading back out",
        default=0.5, min=0.0)
    rise: FloatProperty(
        name="Rise Speed", description="Upward speed, units per second",
        default=0.6)
    spread: FloatProperty(
        name="Spread", description="Sideways scatter at birth", default=0.5,
        min=0.0)
    size: FloatProperty(
        name="Card Size", description="Width/height of each sprite card",
        default=0.6, min=0.001)
    fps: FloatProperty(
        name="Sheet FPS",
        description="Sheet frames per second. 24 matches Blender's default "
                    "frame rate, so one sheet frame per rendered frame",
        default=24.0, min=0.01)
    seed: IntProperty(name="Seed", default=0)
    use_material: BoolProperty(
        name="Use the material's settings",
        description="Build the shader the way the .vmt says to - "
                    "$overbrightfactor and $additive. Off, it builds the "
                    "neutral material Import VTF would, which is the "
                    "comparison worth having when something looks wrong",
        default=True,
    )
    shader: EnumProperty(
        name="Shader", items=SHADER_ITEMS, default="AUTO",
        description="Auto follows the .vmt's own shader; Refract forces the "
                    "warp build, UnlitGeneric / SpriteCard force the "
                    "emissive sprite family",
    )

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "use_material")
        col.separator()
        col.label(text="Shader:")
        col.prop(self, "shader", expand=True)
        col.separator()
        col.label(text="Emitter", icon="PARTICLES")
        col.prop(self, "particles")
        col.prop(self, "lifespan")
        col.separator()
        col.label(text="Fade")
        col.prop(self, "fade_in")
        col.prop(self, "fade_out")
        col.separator()
        col.label(text="Motion")
        col.prop(self, "rise")
        col.prop(self, "spread")
        col.separator()
        col.label(text="Sheet")
        col.prop(self, "size")
        col.prop(self, "fps")
        col.prop(self, "seed")

    def execute(self, context):
        chain, err = self._resolved()
        if err:
            self.report({"ERROR"}, err)
            print(f"{TAG}  {err}")
            return {"CANCELLED"}

        over = chain["overbright"] if self.use_material else 1.0
        add = chain["additive"] if self.use_material else False
        warp = chain["warp"] if self.use_material else None
        #  The shader buttons override the file, same as Import VMT.
        if self.shader == "REFRACT":
            warp = warp or vmt_tool.warp_params(chain["values"])
        elif self.shader in ("UNLIT", "SHEET"):
            warp = None
        print(f"{TAG}  {Path(self.filepath).name} -> {chain['vtf'].name}  "
              f"({describe(chain)}"
              f"{'' if self.use_material else ', IGNORED - neutral material'})")
        try:
            host, info = build_sprite_probe(
                context, chain["vtf"], self.particles, self.lifespan,
                self.fade_in, self.fade_out, self.rise, self.spread,
                self.size, self.fps, self.seed,
                overbright=over, additive=add, warp=warp)
        except Exception as exc:
            self.report({"ERROR"}, f"Sprite probe failed: {exc}")
            print(f"{TAG}  FAILED for {chain['vtf'].name}: {exc}")
            return {"CANCELLED"}

        if warp:
            # A refractive material renders as nothing in EEVEE until the
            # scene-side ray-tracing switches are on. Flip them here, guarded.
            warp_nodes.configure_eevee_refraction(context.scene)

        seqs = info.get("sequences", [])
        if not info.get("sheet"):
            self.report({"WARNING"},
                        f"{chain['vtf'].stem}: no sprite-sheet table in this "
                        f"VTF - built a single-tile probe instead")
        else:
            self.report({"INFO"},
                        f"{Path(self.filepath).stem}: {describe(chain)} · "
                        f"{info['cols']}x{info['rows']} grid, "
                        f"{len(seqs)} sequence(s) -> {host.name}")
        for o in context.selected_objects:
            o.select_set(False)
        host.select_set(True)
        context.view_layer.objects.active = host
        return {"FINISHED"}


CLASSES = (HTP_OT_ImportVMT, HTP_OT_ImportVMTSprite)
