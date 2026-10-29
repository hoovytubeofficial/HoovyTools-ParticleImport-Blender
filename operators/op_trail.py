# =============================================================================
#  operators/op_trail.py  -  Create Render Sprite Trail
# =============================================================================
#
#  The same system as the other two renderers - same emitter, same
#  initializers, same operators - with the last step swapped for ONE CARD PER
#  PARTICLE, stretched backwards along the way that particle is travelling.
#
#  THE DIALOG IS THE EXPLANATION. The four numbers that decide how a trail
#  looks are three different quantities with almost the same names, so they
#  are grouped and labelled by what they ARE:
#
#      Trail Length Min / Max    SECONDS of the particle's own travel
#      Min / Max Length          HAMMER UNITS - a clamp on the answer
#      Radius                    HAMMER UNITS - the HALF width
#
#  The full reasoning is in tools/trail_nodes.py and inside the node group.
#
#  Sequences come along for free: a trail sheet with several sparks on it is
#  read the same way an animated sprite's is, and Sequence Random picks one
#  per particle. That is why the browser opens where the spark sheets are.
# =============================================================================

from pathlib import Path

from bpy.types import Operator
from bpy.props import StringProperty, IntProperty, FloatProperty, BoolProperty
from bpy_extras.io_utils import ImportHelper

from . import op_prefs
from ..tools import control_points, ras_system
from .op_ras import (build_ras, TAG, PARENT_PROP, draw_parent_picker,
                     resolve_parent)


class HTP_OT_CreateTrail(Operator, ImportHelper):
    """Build a render_sprite_trail system - one STREAK per particle

A camera-facing card per particle, stretched along the direction it is
travelling. Sparks, embers, rain.

⚠️ LENGTH IS SPEED x SECONDS. Trail Length Random is measured in SECONDS
OF TRAVEL, not units - the renderer's own Min/Max Length are the units,
clamping the answer. Three quantities, four similar names, and the corpus
proves it: length_min tops out at 20 while max length reaches 5000.

Radius is the HALF WIDTH and does not shrink with the streak, so a slowed
particle draws a blob - which is what Constrain Radius To Length is for.

TAKES A .VMT OR A .VTF. Sparks are usually additive; pick the material and
it comes out that way rather than as streaks on black cards."""
    bl_idname = "htp.create_trail"
    bl_label = "Create Render Sprite Trail"
    bl_options = {"REGISTER", "UNDO"}

    filename_ext = ".vmt"
    filter_glob: StringProperty(default="*.vmt;*.vtf", options={"HIDDEN"})

    emission_rate: FloatProperty(
        name="Emission Rate", description="Particles per second",
        default=40.0, min=0.0)
    max_particles: IntProperty(
        name="Max Particles", default=200, min=1, max=10000)
    lifetime_min: FloatProperty(name="Lifetime Min", default=0.2, min=0.001)
    lifetime_max: FloatProperty(name="Lifetime Max", default=0.6, min=0.001)

    # ── the streak ───────────────────────────────────────────────────────
    trail_length_min: FloatProperty(
        name="Trail Length Min",
        description="SECONDS of the particle's own travel, not a distance. "
                    "The renderer multiplies the particle's SPEED by this, so "
                    "0.2 means 'draw the last fifth of a second of movement' "
                    "[SFM: length_min]",
        default=0.1, min=0.0, soft_max=2.0)
    trail_length_max: FloatProperty(
        name="Trail Length Max",
        description="The other end of that draw, also in SECONDS "
                    "[SFM: length_max]",
        default=0.5, min=0.0, soft_max=2.0)
    min_length: FloatProperty(
        name="Min Length",
        description="HAMMER UNITS. A floor under the finished length, so a "
                    "nearly-stopped particle still draws something "
                    "[SFM: min length]",
        default=1.0, min=0.0)
    max_length: FloatProperty(
        name="Max Length",
        description="HAMMER UNITS. The ceiling, so a fast particle cannot "
                    "draw a streak across the whole map [SFM: max length]",
        default=2048.0, min=0.0)
    length_fade_in: FloatProperty(
        name="Length Fade In Time",
        description="Seconds over which the streak grows from nothing, so it "
                    "does not pop in at full stretch [SFM: length fade in "
                    "time]",
        default=0.1, min=0.0)
    constrain: BoolProperty(
        name="Constrain Radius To Length",
        description="Cap the half-width at half the length. Without it a "
                    "slowed particle draws a card WIDER than it is long - a "
                    "blob instead of a streak",
        default=True)
    radius: FloatProperty(
        name="Radius",
        description="HALF the width, in Hammer units. A trail is radius x 2 "
                    "across [SFM: radius_min / radius_max]",
        default=2.0, min=0.0)

    # ── how they are thrown ──────────────────────────────────────────────
    speed_min: FloatProperty(
        name="Speed Min",
        description="Outward speed, Hammer units per second. THE TRAIL "
                    "LENGTH IS SPEED x SECONDS, so this is what actually "
                    "makes a streak long",
        default=200.0)
    speed_max: FloatProperty(name="Speed Max", default=600.0)
    distance_max: FloatProperty(
        name="Distance Max",
        description="Radius of the sphere particles are born in",
        default=4.0, min=0.0)
    gravity: FloatProperty(name="Gravity Z", default=-200.0)
    drag: FloatProperty(
        name="Drag",
        description="Fraction of motion kept per 30 Hz tick. Drag SHORTENS "
                    "the trail over time, because the length follows the "
                    "speed",
        default=0.1)
    control_points_n: IntProperty(
        name="Control Points", default=1, min=1,
        max=control_points.MAX_CONTROL_POINTS)
    key_control_points: BoolProperty(
        name="Keyframe Control Points",
        description="One location key on each control point where it stands, "
                    "so auto-key records a move straight away",
        default=False)
    parent_system: StringProperty(**PARENT_PROP)
    seed: IntProperty(name="Seed", default=0)

    def invoke(self, context, event):
        if not self.filepath:
            start = op_prefs.trail_sprite_dir()
            if start is not None:
                self.filepath = str(start) + "\\"
                print(f"{TAG}  trail browser starting at {start}")
        return super().invoke(context, event)

    def draw(self, context):
        col = self.layout.column()
        col.label(text="EMITTER", icon="PARTICLES")
        col.prop(self, "emission_rate")
        col.prop(self, "max_particles")
        col.prop(self, "lifetime_min")
        col.prop(self, "lifetime_max")

        col.separator()
        col.label(text="INITIALIZER · Trail Length Random",
                  icon="IPO_LINEAR")
        sub = col.column()
        sub.scale_y = 0.72
        sub.label(text="SECONDS of travel, not a distance.")
        sub.label(text="length = speed x this, then clamped below.")
        col.prop(self, "trail_length_min")
        col.prop(self, "trail_length_max")

        col.separator()
        col.label(text="RENDERER · render_sprite_trail",
                  icon="RENDER_RESULT")
        sub = col.column()
        sub.scale_y = 0.72
        sub.label(text="These two are HAMMER UNITS - a clamp on")
        sub.label(text="the answer, not the length itself.")
        col.prop(self, "min_length")
        col.prop(self, "max_length")
        col.prop(self, "length_fade_in")
        col.prop(self, "constrain")

        col.separator()
        col.label(text="INITIALIZER · thrown how fast", icon="FORCE_WIND")
        col.prop(self, "speed_min")
        col.prop(self, "speed_max")
        col.prop(self, "distance_max")
        col.prop(self, "gravity")
        col.prop(self, "drag")

        col.separator()
        col.prop(self, "radius")
        col.prop(self, "control_points_n")
        col.prop(self, "key_control_points")
        draw_parent_picker(col, self, context)
        col.prop(self, "seed")

        box = self.layout.box()
        box.scale_y = 0.8
        box.label(text="Sequences in the sheet are read and", icon="INFO")
        box.label(text="picked per particle by Sequence Random.")
        box.label(text="Simulation emitter - play from frame 1.")
        if self.speed_max <= 0.0:
            warn = self.layout.box()
            warn.scale_y = 0.8
            warn.label(text="Speed Max is 0, so nothing moves -", icon="ERROR")
            warn.label(text="and a trail's length IS its speed.")
            warn.label(text="Every streak will collapse to Min Length.")

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
            "Lifetime Min": self.lifetime_min,
            "Lifetime Max": self.lifetime_max,
            "Distance Max": self.distance_max,
            "Speed Min": self.speed_min,
            "Speed Max": self.speed_max,
            "Radius Min": self.radius,
            "Radius Max": self.radius,
            "Length Min": self.trail_length_min,
            "Length Max": self.trail_length_max,
            "render_sprite_trail::Min Length": self.min_length,
            "render_sprite_trail::Max Length": self.max_length,
            "Length Fade In Time": self.length_fade_in,
            "Constrain Radius To Length": self.constrain,
            "Gravity": (0.0, 0.0, self.gravity),
            "Drag": self.drag,
            "Scale": 1.0,
            "Seed": self.seed,
        }
        parent, err = resolve_parent(self)
        if err:
            self.report({"ERROR"}, err)
            return {"CANCELLED"}
        try:
            host, info = build_ras(context, path, values,
                                   emitter="SIMULATION",
                                   renderer="SPRITE_TRAIL",
                                   cp_count=self.control_points_n,
                                   parent=parent,
                                   key_cps=self.key_control_points,
                                   overbright=src["overbright"],
                                   additive=src["additive"],
                                   blend=src.get("blend"),
                                   warp=src.get("warp"),
                                   span_sequences=True)
        except Exception as exc:
            self.report({"ERROR"}, f"Could not build the trail: {exc}")
            print(f"{TAG}  TRAIL FAILED for {path.name}: {exc}")
            return {"CANCELLED"}

        seqs = info["sequences"]
        # Say what the sheet actually held. A trail sheet with one sequence is
        # fine, but if you picked it expecting several sparks you want to know
        # now rather than after wondering why they all look the same.
        msg = (f"{path.stem}: {info['cols']}x{info['rows']} sheet, "
               f"{len(seqs)} sequence(s), "
               f"{info['control_points']} control point(s) -> {host.name} "
               f"· play from frame 1")
        if len(seqs) == 1:
            self.report({"WARNING"}, msg + " · ONE sequence in this sheet, so "
                        "every particle draws the same spark")
        else:
            self.report({"INFO"}, msg)
        for o in context.selected_objects:
            o.select_set(False)
        host.select_set(True)
        context.view_layer.objects.active = host
        return {"FINISHED"}


CLASSES = (HTP_OT_CreateTrail,)
