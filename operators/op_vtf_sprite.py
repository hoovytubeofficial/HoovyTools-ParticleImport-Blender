# =============================================================================
# operators/op_vtf_sprite.py  -  IMPORT VTF SPRITE
# =============================================================================
#
# A PROBE built on the REAL SYSTEM. Pick a .vtf and this stands up a small
# `build_ras` system - the same sectioned, note-carrying, tidied geo-node
# graph as Create RAS and a .pcf import - with gentle probe defaults:
# particles rise, fade in and out, and each plays a RANDOM sequence from the
# VTF's own table, at its own looping behaviour
#
# 🔴 the PROBE USED TO BE ITS own HAND-ROLLED EMITTER GRAPH, and that was a
# mistake paid for twice: the first graph a user ever opened (from the
# Import buttons) was the one with no sections, no notes and no layout, and
# every lesson the system emitters learned (sprite_color!) had to be
# re-learned here. ONE builder now. The probe is a thin values-preset.
#
# LOOPING is READ FROM the FILE, per sequence (1 = clamp/hold, 0 = loop)
# It isn't a user toggle, bc it isn't a preference - it's data
#
# Everything lands in  __HoovyTools__ / VTF Sprite Tests / <texture name>.
# =============================================================================

from pathlib import Path

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, FloatProperty, EnumProperty
from bpy_extras.io_utils import ImportHelper

from . import op_prefs
from .op_vtf import ROOT_COLLECTION, SHADER_ITEMS


TAG = "[HT_SPRITE]"
TEST_COLLECTION = "VTF Sprite Tests"


def _collection(name):
    scene_root = bpy.context.scene.collection
    root = bpy.data.collections.get(ROOT_COLLECTION) \
        or bpy.data.collections.new(ROOT_COLLECTION)
    if root.name not in scene_root.children:
        try:
            scene_root.children.link(root)
        except Exception:
            pass
    tests = bpy.data.collections.get(TEST_COLLECTION) \
        or bpy.data.collections.new(TEST_COLLECTION)
    if tests.name not in root.children:
        try:
            root.children.link(tests)
        except Exception:
            pass
    sub = bpy.data.collections.get(name)
    if sub is None:
        sub = bpy.data.collections.new(name)
    if sub.name not in tests.children:
        try:
            tests.children.link(sub)
        except Exception:
            pass
    return sub


def build_sprite_probe(context, path, particles=12, lifespan=5.0,
                       fade_in=0.5, fade_out=0.5, rise=0.6, spread=0.5,
                       size=0.6, fps=24.0, seed=0,
                       overbright=1.0, additive=False, warp=None):
    """Stand up a SMALL REAL SYSTEM wearing this texture. Returns (host, info).

    🔴 THE PROBE IS NOT ITS OWN GRAPH ANY MORE. It used to be a hand-rolled
    emitter group with none of the section frames, notes, packed layout or
    operator panels - so the one graph a user met FIRST, from the Import
    buttons, was the unreadable one, and it kept needing every material
    lesson re-taught (it rendered black for a day because it never stored
    sprite_color). There is ONE system builder in this add-on. The probe is
    `build_ras` with gentle defaults and a stateless emitter, so what the
    Import buttons build is the same organised geo-node system as Create RAS
    and a .pcf import - scrubbable, sectioned, tidied, documented.

    overbright/additive/warp come from a .vmt when there is one to read;
    straight off a .vtf they stay neutral, and that is the whole difference
    between the VTF and VMT import buttons."""
    from .op_ras import build_ras
    stem = Path(path).stem
    values = {
        # the probe promises `particles` on screen NOW, not after one full
        # lifespan of ramp-up - so the steady stream STARTS one LIFESPAN
        # BEFORE FRAME 0. By the first frame anyone looks at, a full
        # population is already alive and being replaced, exactly like the
        # old always-full probe. (The stateless emitter is a pure function
        # of the clock, so a negative start time is just maths, not history.)
        "Max Particles": int(particles),
        "emit_continuously::Emission Start Time": -float(lifespan),
        "Emission Rate": float(particles) / max(0.01, float(lifespan)),
        "Lifetime Min": float(lifespan), "Lifetime Max": float(lifespan),
        # Card Size is the card's full width; SFM radius is its HALF-width.
        "Radius Min": float(size) / 2.0, "Radius Max": float(size) / 2.0,
        "render_animated_sprites::Animation Rate": float(fps),
        "Seed": int(seed),
        # birth: a flat little disc under the cursor's control point
        "Position Within Sphere Random::Distance Max": float(spread),
        "Position Within Sphere Random::Distance Bias": (1.0, 1.0, 0.0),
        # the old probe's steady rise, expressed as the real initializer
        "Velocity Random": True,
        "Velocity Random::Local Speed Min": (0.0, 0.0, float(rise)),
        "Velocity Random::Local Speed Max": (0.0, 0.0, float(rise)),
        # fades in SECONDS, like the probe always advertised
        "Alpha Fade In Random::Proportional": False,
        "Alpha Fade In Random::Fade In Time Min": float(fade_in),
        "Alpha Fade In Random::Fade In Time Max": float(fade_in),
        "Alpha Fade Out Random::Proportional": False,
        "Alpha Fade Out Random::Fade Out Time Min": float(fade_out),
        "Alpha Fade Out Random::Fade Out Time Max": float(fade_out),
    }
    host, info = build_ras(
        context, path, values,
        emitter="STATELESS",             # the probe's scrub-anywhere promise
        host_name=f"VTF Sprite Test · {stem}",
        overbright=overbright, additive=additive, warp=warp,
        span_sequences=True,             # show every variant the sheet has
        cp_count=1,
        collection=_collection(f"VTF Sprite · {stem}"))
    return host, info


class HTP_OT_ImportVTFSprite(Operator, ImportHelper):
    """Decode a .vtf and stand up a small REAL system wearing it

The same organised geo-node system Create RAS builds - sections, notes,
operator panels - with gentle probe defaults and a stateless emitter, so
you can scrub anywhere and it stays correct. Cards rise and fade, each
playing a random sequence from the VTF's OWN sheet table.

It answers one question: is this sheet being cut up correctly? Looping is
read per sequence from the file, never guessed - across 518 real sheets
895 sequences play once and 167 loop.

NO MATERIAL IS READ, so the shader is neutral. If the sheet is additive
this will draw its black background as opaque black; Import VMT + Build
Sprite is the one that knows better."""
    bl_idname = "htp.import_vtf_sprite"
    bl_label = "Import VTF + Build Sprite"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".vtf"
    filter_glob: StringProperty(default="*.vtf", options={"HIDDEN"})

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
        name="Spread", description="Sideways scatter at birth",
        default=0.5, min=0.0)
    size: FloatProperty(
        name="Card Size", description="Width/height of each sprite card",
        default=0.6, min=0.001)
    fps: FloatProperty(
        name="Sheet FPS",
        description="Sheet frames per second. 24 matches Blender's default "
                    "frame rate, so one sheet frame per rendered frame",
        default=24.0, min=0.01)
    seed: IntProperty(name="Seed", default=0)
    shader: EnumProperty(
        name="Shader", items=SHADER_ITEMS, default="AUTO",
        description="A bare .vtf has no material, so Auto builds the neutral "
                    "sprite. Refract forces the warp build (default "
                    "$refractamount 0.2) - the honest look for a normal-map "
                    "sheet with no .vmt at hand",
    )

    def invoke(self, context, event):
        if not self.filepath:
            start = op_prefs.texture_dir()
            if start is not None:
                self.filepath = str(start) + "\\"
                print(f"{TAG}  sprite browser starting at {start}")
        return super().invoke(context, event)

    def draw(self, context):
        col = self.layout.column()
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
        box = self.layout.box()
        box.scale_y = 0.8
        box.label(text="Looping is read from the VTF, per sequence.",
                  icon="INFO")

    def execute(self, context):
        path = Path(self.filepath)
        if not path.is_file():
            self.report({"ERROR"}, f"Not a file: {path}")
            return {"CANCELLED"}
        #the shader buttons force a family on this material-less probe;
        #Refract gets Source's default $refractamount, said in the tooltip.
        warp = None
        if self.shader == "REFRACT":
            warp = {"refract_amount": 0.2, "blur_amount": 0.0,
                    "tint": (1.0, 1.0, 1.0, 1.0)}
        try:
            host, info = build_sprite_probe(
                context, path, self.particles, self.lifespan, self.fade_in,
                self.fade_out, self.rise, self.spread, self.size, self.fps,
                self.seed, warp=warp)
        except Exception as exc:
            self.report({"ERROR"}, f"Sprite probe failed: {exc}")
            print(f"{TAG}  FAILED for {path.name}: {exc}")
            return {"CANCELLED"}

        if warp:
            # A refractive material renders as nothing in EEVEE until the
            # scene-side ray-tracing switches are on
            from ..tools import warp_nodes
            warp_nodes.configure_eevee_refraction(context.scene)

        seqs = info.get("sequences", [])
        if not info.get("sheet"):
            self.report({"WARNING"},
                        f"{path.stem}: no sprite-sheet table in this VTF - "
                        f"built a single-tile probe instead")
        else:
            loops = sum(1 for _s, _c, lp in seqs if lp)
            self.report(
                {"INFO"},
                f"{path.stem}: {info['cols']}x{info['rows']} grid, "
                f"{len(seqs)} sequence(s), {loops} looping "
                f"-> {host.name}")

        for o in context.selected_objects:
            o.select_set(False)
        host.select_set(True)
        context.view_layer.objects.active = host
        return {"FINISHED"}


CLASSES = (HTP_OT_ImportVTFSprite,)
