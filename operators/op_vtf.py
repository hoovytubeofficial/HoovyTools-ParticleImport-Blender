# =============================================================================
#  operators/op_vtf.py  -  IMPORT VTF
# =============================================================================
#
#  Pick a .vtf, decode it in pure Python, land it as a PACKED Image datablock
#  inside the .blend. No loose TGA piles, no VTFEdit, no Source IO at runtime.
#  Decoding + the sprite-sheet table live in tools/vtf.py.
#
#  The browser opens in SFM's usermod\materials when we can find it (paths.py).
#
#  Developer tool - reached from the sidebar's Developer tab, NOT File > Import.
# =============================================================================

from pathlib import Path

import bpy
from bpy.types import Operator
from bpy.props import (StringProperty, BoolProperty, CollectionProperty,
                       EnumProperty)
from bpy.types import OperatorFileListElement
from bpy_extras.io_utils import ImportHelper

from . import op_prefs
from ..tools import vtf


TAG = "[HT_PARTICLE]"

#  THE SOURCE SHADER FAMILIES, as buttons on every texture/material import.
#  One set, shared by all four import operators, so the choice reads the same
#  everywhere: Auto follows what the file says, the other three FORCE it.
SHADER_ITEMS = (
    ("AUTO", "Auto",
     "Follow the file: a .vmt uses its own shader, a bare .vtf gets the "
     "plain preview"),
    ("UNLIT", "UnlitGeneric",
     "Emissive unlit sprite - texture colour glows, texture alpha cuts"),
    ("REFRACT", "Refract",
     "Warp material - the picture is a normal map that bends whatever "
     "renders behind it (needs EEVEE ray tracing or Cycles)"),
    ("SHEET", "SpriteCard",
     "Sprite-sheet shader - unlit like UnlitGeneric; on a preview sphere it "
     "crops to the sheet's first frame instead of wearing the whole grid"),
)


def vtf_to_image(path, name=None):
    """Decode a .vtf and return (image, info). Raises on failure.

    WHY THE TEMP FILE: an image built with images.new() is source='GENERATED',
    and Image.pack() silently refuses to pack those - the pixels then vanish
    the moment the .blend is saved and reopened. Writing a real PNG and
    loading it gives a source='FILE' image that packs properly."""
    import os
    import tempfile

    rgba, info = vtf.decode_u8(path)
    name = name or Path(path).stem

    #  🔴 NEVER REMOVE THE OLD DATABLOCK FIRST. Several systems share one
    #  .vtf (glow_a is on five systems of one effect, under two material
    #  variants), and every earlier-built material still points at the old
    #  image - removing it left their texture slots at None. The EEVEE
    #  viewport kept showing the pixels it had in memory, so everything
    #  LOOKED fine until Cycles re-read the scene and drew every one of
    #  those cards as a flat missing-texture slab. So: import the fresh
    #  copy, RE-POINT every user of the old image at it, then drop the old.
    old = bpy.data.images.get(name)

    tmp = os.path.join(tempfile.gettempdir(), f"_htp_vtf_{abs(hash(name))}.png")
    try:
        vtf.write_png(tmp, rgba)
        img = bpy.data.images.load(tmp)
        try:
            img.pack()
        except Exception as exc:
            print(f"{TAG}  could not pack '{name}': {exc}")
        try:
            img.filepath_raw = ""            # packed - forget the temp path
        except Exception:
            pass
        if old is not None:
            try:
                old.user_remap(img)          # every material follows along
            except Exception as exc:
                print(f"{TAG}  could not remap users of '{name}': {exc}")
            try:
                bpy.data.images.remove(old)
            except Exception:
                pass
        img.name = name
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass

    img.colorspace_settings.name = "Non-Color" if info["is_normal"] else "sRGB"
    img.alpha_mode = "STRAIGHT"
    # A texture imported on its own has no users yet; without this it is
    # purged on save before it can ever be assigned to anything.
    img.use_fake_user = True
    img.update()

    # Stash the sheet layout on the image so the geo-node sprite lookup can
    # read it later without re-opening the .vtf.
    try:
        sheet = vtf.get_sheet(path)
    except Exception as exc:
        sheet = None
        print(f"{TAG}  sheet parse failed for {name}: {exc}")
    if sheet:
        img["htp_sheet_sequences"] = sheet["sequence_count"]
        img["htp_sheet_frames"] = [s["frame_count"] for s in sheet["sequences"]]
        grid = vtf.sheet_grid(sheet, info["width"], info["height"])
        if grid:
            img["htp_sheet_grid"] = list(grid)      # cols, rows, tile_w, tile_h
        info["sheet"] = sheet
        info["grid"] = grid
    return img, info


ROOT_COLLECTION = "__HoovyTools__"
VTF_COLLECTION = "VTF Imports"
PREVIEW_SPACING = 2.5


def vtf_collection(context):
    """__HoovyTools__ / VTF Imports - where imported texture previews live."""
    scene_root = context.scene.collection
    root = bpy.data.collections.get(ROOT_COLLECTION)
    if root is None:
        root = bpy.data.collections.new(ROOT_COLLECTION)
    if root.name not in scene_root.children:
        try:
            scene_root.children.link(root)
        except Exception:
            pass
    sub = bpy.data.collections.get(VTF_COLLECTION)
    if sub is None:
        sub = bpy.data.collections.new(VTF_COLLECTION)
    if sub.name not in root.children:
        try:
            root.children.link(sub)
        except Exception:
            pass
    return sub


def _preview_sphere(context, img, index=0, collection=None, shader="AUTO",
                    grid=None, warp_mat=None):
    """A UV sphere wearing the decoded texture.

    Batch imports lay them out in a row so a folder of sheets becomes a strip
    you can scrub along, instead of a pile stacked on the 3D cursor.

    `shader` picks the material FAMILY (see SHADER_ITEMS). A ready-made warp
    material can be handed in as `warp_mat` and the sphere simply wears it -
    a refract preview should REFRACT, and the warp builder already knows how."""
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=48, ring_count=24, radius=1.0,
        location=context.scene.cursor.location)
    obj = context.active_object
    obj.name = f"VTF_Preview_{img.name}"
    obj.location.x += index * PREVIEW_SPACING
    if collection is not None:
        for c in list(obj.users_collection):
            c.objects.unlink(obj)
        collection.objects.link(obj)
    try:
        bpy.ops.object.shade_smooth()
    except Exception:
        pass

    if warp_mat is not None:
        obj.data.materials.append(warp_mat)
        return obj

    mat = bpy.data.materials.new(f"VTF_{img.name}")
    mat.use_nodes = True
    nt = mat.node_tree

    if shader in ("UNLIT", "SHEET"):
        #  UNLITGENERIC / SPRITECARD: the texture GLOWS, nothing lights it -
        #  which is what a Source sprite actually is. SpriteCard additionally
        #  crops to the sheet's FIRST FRAME when the .vtf carries a sheet
        #  table, so a 4x4 grid previews as one frame, not sixteen thumbnails.
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        out.location = (300, 0)
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.location = (100, 0)
        transp = nt.nodes.new("ShaderNodeBsdfTransparent")
        transp.location = (-100, 120)
        em = nt.nodes.new("ShaderNodeEmission")
        em.location = (-100, -60)
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.location = (-420, 0)
        if shader == "SHEET" and grid:
            cols, rows = int(grid[0]), int(grid[1])
            tc = nt.nodes.new("ShaderNodeTexCoord")
            tc.location = (-820, 0)
            mp = nt.nodes.new("ShaderNodeMapping")
            mp.location = (-640, 0)
            # frame 0 is the TOP-LEFT tile; UV origin is bottom-left.
            mp.inputs["Scale"].default_value = (1.0 / cols, 1.0 / rows, 1.0)
            mp.inputs["Location"].default_value = (0.0, 1.0 - 1.0 / rows, 0.0)
            nt.links.new(tc.outputs["UV"], mp.inputs["Vector"])
            nt.links.new(mp.outputs["Vector"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], em.inputs["Color"])
        nt.links.new(tex.outputs["Alpha"], mix.inputs["Fac"])
        nt.links.new(transp.outputs[0], mix.inputs[1])
        nt.links.new(em.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs["Surface"])
    else:
        # AUTO: the plain lit preview - Principled wearing the picture.
        bsdf = nt.nodes.get("Principled BSDF")
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        tex.location = (-360, 260)
        if bsdf is not None:
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
            if "Alpha" in bsdf.inputs:
                nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
            for socket, val in (("Roughness", 1.0), ("Metallic", 0.0)):
                if socket in bsdf.inputs:
                    bsdf.inputs[socket].default_value = val
    # Sprite sheets are mostly alpha - show it through.
    for attr, val in (("blend_method", "BLEND"),
                      ("surface_render_method", "BLENDED")):
        try:
            setattr(mat, attr, val)
        except Exception:
            pass
    obj.data.materials.append(mat)
    return obj


class HTP_OT_ImportVTF(Operator, ImportHelper):
    """Decode a Source .vtf straight into the .blend as a packed image

Pure Python - no VTFEdit, no converters. DXT1/3/5 and the plain 8-bit
layouts, packed so the texture travels with the file.

Multi-select works: pick a whole folder of sheets and they all come in.
Tick Preview on a Sphere in this window to also get a ball wearing each
one, laid out in a row.

NO MATERIAL IS READ. A .vtf is only the picture - whether it is additive,
and how hot it burns, live in the .vmt. Use Import VMT for that."""
    bl_idname = "htp.import_vtf"
    bl_label = "Import VTF"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".vtf"
    filter_glob: StringProperty(default="*.vtf", options={"HIDDEN"})
    # Multi-select: pick a whole folder of sheets in one go.
    files: CollectionProperty(type=OperatorFileListElement, options={"HIDDEN"})
    directory: StringProperty(subtype="DIR_PATH", options={"HIDDEN"})
    #  ON BY DEFAULT: seeing the texture on something is the point of the
    #  import - opting OUT is the secondary choice, not opting in.
    preview_sphere: BoolProperty(
        name="Preview on a Sphere",
        description="Also drop a UV sphere wearing each texture. Batch "
                    "imports are laid out in a row inside "
                    "__HoovyTools__ / VTF Imports. Untick for a data-only "
                    "import",
        default=True,
    )
    shader: EnumProperty(
        name="Shader", items=SHADER_ITEMS, default="AUTO",
        description="Which Source shader family the preview material uses",
    )

    def invoke(self, context, event):
        # THE TOGGLE LIVES IN THIS WINDOW, not in the sidebar. It is a choice
        # about the import you are making right now, so it belongs next to the
        # file you are choosing - not as a panel button you have to remember
        # to set first.
        if not self.filepath:
            start = op_prefs.texture_dir()
            if start is not None:
                self.filepath = str(start) + "\\"
                print(f"{TAG}  VTF browser starting at {start}")
        return super().invoke(context, event)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "preview_sphere")
        col.separator()
        col.label(text="Shader:")
        col.prop(self, "shader", expand=True)

    def _paths(self):
        """Every selected file. Falls back to the single filepath."""
        if self.files and self.directory:
            out = [Path(self.directory) / f.name for f in self.files if f.name]
            if out:
                return out
        return [Path(self.filepath)] if self.filepath else []

    def execute(self, context):
        paths = [p for p in self._paths() if p.is_file()]
        if not paths:
            self.report({"ERROR"}, "No .vtf files selected.")
            return {"CANCELLED"}

        collection = vtf_collection(context) if self.preview_sphere else None
        # Append to the existing row instead of stacking a second batch on top
        # of the first.
        start_index = len(collection.objects) if collection is not None else 0
        done, failed, notes = [], [], []
        for i, path in enumerate(sorted(paths)):
            try:
                img, info = vtf_to_image(path)
            except Exception as exc:
                failed.append(f"{path.name}: {exc}")
                print(f"{TAG}  VTF import FAILED for {path.name}: {exc}")
                continue

            sheet = info.get("sheet")
            sheet_note = ""
            if sheet:
                frames = sum(s["frame_count"] for s in sheet["sequences"])
                grid = info.get("grid")
                sheet_note = (f", sheet: {sheet['sequence_count']} sequence(s) / "
                              f"{frames} frames"
                              + (f" ({grid[0]}x{grid[1]} grid of "
                                 f"{grid[2]}x{grid[3]}px)" if grid else ""))
            print(f"{TAG}  VTF {path.name}: v{info['version']} "
                  f"{info['width']}x{info['height']} {info['format']} "
                  f"{info['mipmaps']} mip(s){sheet_note}")
            done.append(img)
            notes.append(sheet_note)

            if self.preview_sphere:
                try:
                    warp_mat = None
                    if self.shader == "REFRACT":
                        # Forced refract: the picture is DATA, and the warp
                        # builder makes the material that actually bends.
                        from ..tools import warp_nodes
                        try:
                            img.colorspace_settings.name = "Non-Color"
                        except Exception:
                            pass
                        warp_mat = warp_nodes.build_warp_material(
                            f"VTF Warp · {img.name}", img,
                            particle_attrs=False)
                        warp_nodes.configure_eevee_refraction(context.scene)
                    _preview_sphere(context, img,
                                    index=start_index + len(done) - 1,
                                    collection=collection,
                                    shader=self.shader,
                                    grid=info.get("grid"),
                                    warp_mat=warp_mat)
                except Exception as exc:
                    print(f"{TAG}  preview sphere failed for {img.name}: {exc}")

        if not done:
            self.report({"ERROR"}, f"No VTF imported. {failed[0] if failed else ''}")
            return {"CANCELLED"}

        where = (f" -> {ROOT_COLLECTION}/{VTF_COLLECTION}"
                 if self.preview_sphere else "")
        if len(done) == 1:
            msg = f"Imported {done[0].name}: {done[0].size[0]}x{done[0].size[1]}" \
                  f"{notes[0]}{where}"
        else:
            msg = f"Imported {len(done)} textures{where}"
        if failed:
            msg += f"  ({len(failed)} failed - see console)"
            self.report({"WARNING"}, msg)
        else:
            self.report({"INFO"}, msg)
        return {"FINISHED"}


CLASSES = (HTP_OT_ImportVTF,)
