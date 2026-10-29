# =============================================================================
#  operators/op_rope.py  -  Create Render Rope
# =============================================================================
#
#  The same system as Render Animated Sprites - same emitter, same
#  initializers, same operators - with the last step swapped: instead of one
#  camera-facing card per particle, ONE CONTINUOUS RIBBON threaded through all
#  of them, oldest to newest.
#
#  Pick the trail texture yourself; the browser opens where the trails
#  actually live.
# =============================================================================

from pathlib import Path

import bpy
from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, FloatProperty
from bpy_extras.io_utils import ImportHelper

from bpy.props import BoolProperty

from . import op_prefs
from ..tools import control_points, ras_system
from .op_ras import (build_ras, TAG, PARENT_PROP, draw_parent_picker,
                     resolve_parent)


#  THE SFM STARTER LOOK - measured off a real hand-tuned trail setup, not
#  invented. A bare rope with every operator at its neutral default is a
#  straight dead ribbon; a real SFM trail is born on a flat disc, launched
#  sideways, wanders under noise, shrinks and cools towards blue as it dies.
#  These are the exact values of that reference setup, keyed by the same
#  "Operator::Field" names `build_ras` already resolves, so Create Rope can
#  stand one up out of the box. The toggle that applies them is `sfm_look`.
SFM_LOOK = {
    # launch: sideways out of the control point's own frame
    "Velocity Random": True,
    "Velocity Random::Local Speed Min": (25.0, 0.0, 0.0),
    # wander: noise in the XY plane only, so the streak stays a streak
    "Velocity Noise": True,
    "Velocity Noise::Output Min": (-25.0, -25.0, 0.0),
    "Velocity Noise::Output Max": (25.0, 25.0, 0.0),
    "random force": True,
    "random force::Max Force": (5.0, 5.0, 5.0),
    # herding: drawn towards CP1, so dragging that empty shapes the trail
    "Pull towards control point": True,
    "Pull towards control point::Amount": 5.0,
    "Pull towards control point::Control Point": 1,
    "twist around axis": True,
    # birth: a flat 5-unit disc, not a ball - ground-effect authoring
    "Position Within Sphere Random::Distance Max": 5.0,
    "Position Within Sphere Random::Distance Bias": (1.0, 1.0, 0.0),
    # life: slightly translucent, shrinking, cooling white -> blue
    "Alpha Random::Alpha Min": 215,
    "Color Random::Color 2": (0.2103, 0.4109, 1.0, 1.0),
    "Radius Scale::Start Scale": 0.43,
}


class HTP_OT_CreateRope(Operator, ImportHelper):
    """Build a render_rope system - ONE RIBBON through every particle

Source's beam renderer. The particles are not drawn: they are the spine,
threaded oldest to newest, and one continuous ribbon is built across them.

This is what lasers, lightning and cables are. Pair it with Position
Along Path Sequential and the particles line up between two control
points - a rope draws through its particles IN ORDER, so that ordering is
the difference between a straight beam and a scribble.

Width is the particle radius; the ribbon faces the camera along its whole
length.

PICK THE .VMT, NOT THE .VTF. Beam materials are authored additive at
$overbrightfactor 15 or 35, and a bare .vtf cannot say so - it is only the
picture. Hand it the material and the beam burns at the brightness it was
written for, with black treated as transparent. A .vtf still works and
builds a neutral material; the console says which you got.

SFM STARTER LOOK is on by default: the rope stands up tuned like a real
trail - flat-disc birth, sideways launch, XY noise, taper, white-to-blue
cooling, herded by CP1 - instead of a bare straight ribbon. Turn it off
for the neutral build."""
    bl_idname = "htp.create_rope"
    bl_label = "Create Render Rope"
    bl_options = {"REGISTER", "UNDO"}

    # A beam is the case that needs this most: beam materials are authored
    # additive at overbright 15, and a .vtf on its own cannot say so.
    filename_ext = ".vmt"
    filter_glob: StringProperty(default="*.vmt;*.vtf", options={"HIDDEN"})

    emission_rate: FloatProperty(
        name="Emission Rate",
        description="Particles per second. A rope wants a steady stream - "
                    "each one becomes a point on the ribbon",
        default=30.0, min=0.0)
    max_particles: IntProperty(
        name="Max Particles",
        description="How long the ribbon can get, in points",
        default=200, min=2, max=10000)
    lifetime: FloatProperty(
        name="Lifetime",
        description="How long the tail lingers behind the control point",
        default=2.0, min=0.001)
    half_width: FloatProperty(
        name="Half Width",
        description="Multiplier on the particle radius. NOT an SFM field - "
                    "Source takes the ribbon's width from the radius alone",
        default=1.0, min=0.0)
    texel_size: FloatProperty(
        name="Texel Size",
        description="1.0 is one texture repeat across the whole rope, 0.5 is "
                    "two [SFM: texel_size]",
        default=0.1, min=0.0)
    scroll_rate: FloatProperty(
        name="Texture Scroll Rate",
        description="Texture repeats per second along the rope "
                    "[SFM: texture_scroll_rate]",
        default=0.0)
    subdivision_count: IntProperty(
        name="Subdivision Count",
        description="Catmull-Rom samples between particles. Source clamps "
                    "anything at or below 0 to 1 [SFM: subdivision_count]",
        default=4, min=0, max=100)
    gravity: FloatProperty(
        name="Gravity Z",
        description="Upward force, Hammer units per second squared. A ROPE "
                    "NEEDS ITS PARTICLES TO TRAVEL - with nothing moving them "
                    "they all sit on the control point and the ribbon has no "
                    "length at all, which looks exactly like a broken "
                    "material. Set this to 0 only when you are animating a "
                    "control point instead [SFM: gravity]",
        default=60.0)
    drag: FloatProperty(
        name="Drag",
        description="Fraction of motion kept per 30 Hz tick. Terminal speed "
                    "is gravity / (30 x drag) [SFM: drag]",
        default=0.03)
    sfm_look: BoolProperty(
        name="SFM Starter Look",
        description="Start from a real trail's tuning instead of a bare "
                    "ribbon: born on a flat disc, launched sideways, wanders "
                    "under velocity noise, shrinks and cools white-to-blue, "
                    "and is herded by Control Point 1. Off builds the plain "
                    "rope with every operator neutral",
        default=True)
    radius: FloatProperty(
        name="Radius",
        description="Particle radius, in Hammer units - the ribbon's "
                    "half-width before Half Width multiplies it",
        default=4.0, min=0.0)
    control_points: IntProperty(
        name="Control Points",
        description="How many CP empties to create, and how far every "
                    "'control point number' socket can reach. A rope usually "
                    "wants one; a real .pcf says",
        default=ras_system.DEFAULT_CONTROL_POINTS, min=1,
        max=control_points.MAX_CONTROL_POINTS)
    key_control_points: BoolProperty(
        name="Keyframe Control Points",
        description="One location key on each control point where it stands, "
                    "so auto-key records a move straight away. A rope is "
                    "usually animated BY its control point, so this is the "
                    "one that matters most here",
        default=False)
    parent_system: StringProperty(**PARENT_PROP)

    def invoke(self, context, event):
        if not self.filepath:
            start = op_prefs.trail_texture_dir()
            if start is not None:
                self.filepath = str(start) + "\\"
        return super().invoke(context, event)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "sfm_look")
        col.separator()
        col.label(text="EMITTER", icon="PARTICLES")
        col.prop(self, "emission_rate")
        col.prop(self, "max_particles")
        col.prop(self, "lifetime")
        col.separator()
        col.label(text="RENDERER · render_rope", icon="OUTLINER_OB_CURVE")
        col.prop(self, "texel_size")
        col.prop(self, "scroll_rate")
        col.prop(self, "subdivision_count")
        col.separator()
        col.label(text="OPERATOR · Movement Basic", icon="FORCE_FORCE")
        col.prop(self, "gravity")
        col.prop(self, "drag")
        col.separator()
        col.prop(self, "radius")
        col.prop(self, "half_width")
        col.separator()
        col.label(text="CONTROL POINTS", icon="EMPTY_AXIS")
        col.prop(self, "control_points")
        col.prop(self, "key_control_points")
        draw_parent_picker(col, self, context)
        box = self.layout.box()
        box.scale_y = 0.8
        box.label(text="A rope needs the simulation emitter,", icon="INFO")
        box.label(text="so play from frame 1.")
        if abs(self.gravity) < 1e-6:
            warn = self.layout.box()
            warn.scale_y = 0.8
            warn.label(text="Gravity is 0 - the rope will only be", icon="ERROR")
            warn.label(text="visible if you ANIMATE a control point.")
            warn.label(text="Otherwise every particle sits on CP0 and")
            warn.label(text="the ribbon has no length to draw.")

    def execute(self, context):
        from .op_vmt import resolve_source
        src = resolve_source(self.filepath)
        if src["vtf"] is None:
            self.report({"ERROR"}, src["note"])
            return {"CANCELLED"}
        path = src["vtf"]
        print(f"{TAG}  {src['note']}")
        values = {
            "Max Particles": self.max_particles,
            "Emission Rate": self.emission_rate,
            "Lifetime Min": self.lifetime,
            "Lifetime Max": self.lifetime,
            "Radius Min": self.radius,
            "Radius Max": self.radius,
            "Texel Size": self.texel_size,
            "Texture Scroll Rate": self.scroll_rate,
            "Subdivision Count": self.subdivision_count,
            "Distance Max": 0.0,
            "Gravity": (0.0, 0.0, self.gravity),
            "Drag": self.drag,
            "Scale": 1.0,
        }
        if self.sfm_look:
            #  The starter look's radius runs 0..Radius rather than a uniform
            #  width - a trail thickens as it lives, so its spine tapers.
            values["Radius Min"] = 0.0
            values.update(SFM_LOOK)
        parent, err = resolve_parent(self)
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        try:
            host, info = build_ras(context, path, values,
                                   emitter="SIMULATION", renderer="ROPE",
                                   cp_count=self.control_points,
                                   parent=parent,
                                   key_cps=self.key_control_points,
                                   overbright=src["overbright"],
                                   additive=src["additive"],
                                   blend=src.get("blend"),
                                   warp=src.get("warp"))
        except Exception as exc:
            self.report({"ERROR"}, f"Could not build the rope: {exc}")
            print(f"{TAG}  ROPE FAILED for {path.name}: {exc}")
            return {"CANCELLED"}

        # Half Width is not an SFM field, so it is not in the spec table and
        # has to be set by its own socket name.
        from ..tools import ras_system
        from .op_ras import _set_input
        mod = host.modifiers[0]
        for item in mod.node_group.interface.items_tree:
            if (getattr(item, "item_type", "") == "SOCKET"
                    and item.name == ras_system.ROPE_HALF):
                _set_input(mod, item.identifier, self.half_width)

        msg = (f"{path.stem}: rope of up to {self.max_particles} points, "
               f"{self.subdivision_count} subdivisions -> {host.name} "
               f"· play from frame 1")
        if abs(self.gravity) < 1e-6:
            # Never let this fail silently: a rope whose particles do not move
            # is a zero-length ribbon, and that is indistinguishable from a
            # broken material at a glance.
            self.report({"WARNING"}, msg + " · GRAVITY IS 0, so the rope has "
                        "no length unless you animate a control point")
        else:
            self.report({"INFO"}, msg)
        for o in context.selected_objects:
            o.select_set(False)
        host.select_set(True)
        context.view_layer.objects.active = host
        return {"FINISHED"}


CLASSES = (HTP_OT_CreateRope,)
