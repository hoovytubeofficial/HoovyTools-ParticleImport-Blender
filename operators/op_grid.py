# =============================================================================
#  operators/op_grid.py  -  Hammer Unit Grid
# =============================================================================
#
#  Two buttons: paint Source's own grid on the floor, and take it away again.
#  All the work is in tools/hammer_grid.py; this only reads properties, calls
#  it, and reports what happened.
# =============================================================================

import bpy
from bpy.types import Operator
from bpy.props import FloatProperty, BoolProperty

from ..tools import hammer_grid


TAG = "[HT_GRID]"


class HTP_OT_HammerGrid(Operator):
    """Paint Source's own floor grid, at 1 Blender Unit = 1 Hammer Unit

The 1 / 8 / 16 / 64 grid Hammer and SFM are authored on, with a TF2 Scout
height marker at 81.6924 units to check an effect against.

FIX THE SCALE BEFORE ANYTHING ELSE. Internal particle space IS Hammer
units - operator values are never multiplied by 0.01905 on the way in,
and Scale stays 1.0. Metres are a display choice, made once, by whoever
is standing an effect next to a human-scale character.

Build against the Scout and no number has to be guessed at."""
    bl_idname = "htp.hammer_grid"
    bl_label = "Hammer Unit Grid"
    bl_options = {"REGISTER", "UNDO"}

    extent: FloatProperty(
        name="Extent",
        description="How far the grid reaches from the origin, in Hammer "
                    "units. The lines are shader maths, so a bigger grid "
                    "costs nothing",
        default=256.0, min=16.0, max=16384.0, subtype="DISTANCE")
    checker: BoolProperty(
        name="16 HU Floor Tiles",
        description="A barely-visible checker so the floor reads as a "
                    "surface instead of a void",
        default=True)
    markers: BoolProperty(
        name="Scale Markers",
        description="An origin empty and a TF2 Scout height marker "
                    f"({hammer_grid.SCOUT_HEIGHT:.4g} units)",
        default=True)
    set_units: BoolProperty(
        name="Scene Units: None",
        description="Stop Blender labelling these units as metres. Without "
                    "this the N panel disagrees with the grid you are "
                    "looking at",
        default=True)
    hide_in_render: BoolProperty(
        name="Hide In Render",
        description="Keep the grid out of renders. It is a reference aid, "
                    "not set dressing",
        default=True)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "extent")
        col.prop(self, "checker")
        col.prop(self, "markers")
        col.separator()
        col.prop(self, "set_units")
        col.prop(self, "hide_in_render")
        box = self.layout.box()
        box.scale_y = 0.8
        box.label(text="1 Blender Unit = 1 Hammer Unit", icon="FIXED_SIZE")
        box.label(text="Build systems against this with Scale = 1.0,")
        box.label(text="not the 0.01905 metres default.")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=340)

    def execute(self, context):
        try:
            obj, info = hammer_grid.build(
                extent=self.extent, checker=self.checker,
                markers=self.markers, set_units=self.set_units,
                hide_in_render=self.hide_in_render)
        except Exception as exc:
            self.report({"ERROR"}, f"Could not paint the grid: {exc}")
            print(f"{TAG}  FAILED: {exc}")
            return {"CANCELLED"}

        span = int(self.extent * 2)
        self.report(
            {"INFO"},
            f"{span} x {span} HU grid · 1 / 8 / 16 / 64 HU · "
            f"Scout at {hammer_grid.SCOUT_HEIGHT:.4g} HU"
            + (" · scene units set to None" if info["units_set"] else ""))
        for o in context.selected_objects:
            o.select_set(False)
        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {"FINISHED"}


class HTP_OT_HammerGridRemove(Operator):
    """Take the Hammer grid and its markers back out

Removes the grid, the Scout marker and their collection. Leaves anything
you built against them alone."""
    bl_idname = "htp.hammer_grid_remove"
    bl_label = "Remove Hammer Grid"
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.collections.get(hammer_grid.COLLECTION_NAME))

    def execute(self, context):
        n = hammer_grid.remove()
        if not n:
            # Never claim to have done something to an empty scene.
            self.report({"WARNING"}, "There was no Hammer grid to remove")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Hammer grid removed ({n} objects)")
        return {"FINISHED"}


# =============================================================================
#  THE HOUSE CAMERA
# =============================================================================
#  ONE agreed viewpoint, so every effect is judged from the same place.
#
#  A particle effect has no size of its own - it only has a size NEXT TO
#  SOMETHING. Judging one from a viewport you happened to orbit to is how an
#  effect ends up correct on your screen and wrong in the shot. This is the
#  angle the explosion work was built against: it frames the TF2 Scout at
#  81.6924 units, so what you see here is what the effect is.
#
#  🔴 THESE NUMBERS ARE THE SPEC, not a calculation. They were measured in the
#  scene where the effects were authored and are reproduced exactly.
#
#  The Y rotation is 0: the brief gave two rotation numbers for three axes,
#  and Y is a camera's ROLL - banking the horizon, which nobody wants. Both
#  of the other two check out against the position, which is how we know the
#  reading is right:
#
#      bearing   atan2(131, 256) = 27.1 degrees   against a Z of -26
#      pitch     68 up, 287 out, aimed at about mid-Scout height, is roughly
#                6 degrees DOWN - and 83 is 7 degrees down from level
#
#  Z is +68: the camera stands a bit above the floor and looks slightly down
#  at a Scout standing on it. (-68 would put it underground, aiming at his
#  feet from below.)

CAMERA_NAME = "HT · House Camera"
CAMERA_LOCATION = (-131.0, -256.0, 68.0)
CAMERA_ROTATION_DEG = (83.0, 0.0, -26.0)
CAMERA_LENS = 50.0


class HTP_OT_HouseCamera(Operator):
    """Drop the house camera - the ONE agreed viewpoint

Placed at (-131, -256, 68) looking at a TF2 Scout, so "this effect is too
big" means the same thing to everybody looking at it.

An effect judged from a viewpoint nobody else uses is an effect judged
against nothing."""
    bl_idname = "htp.house_camera"
    bl_label = "Create Camera"
    bl_options = {"REGISTER", "UNDO"}

    make_active: BoolProperty(
        name="Make It The Scene Camera",
        description="Point the scene at it. Sprites read the ACTIVE camera by "
                    "default, so this is also what they will face",
        default=True)
    reset_existing: BoolProperty(
        name="Move It Back If It Exists",
        description="If the house camera is already in the scene, put it back "
                    "at the agreed transform instead of adding a second one",
        default=True)

    def execute(self, context):
        from math import radians
        cam = bpy.data.objects.get(CAMERA_NAME)
        made = cam is None
        if cam is None:
            cam = bpy.data.objects.new(CAMERA_NAME,
                                       bpy.data.cameras.new(CAMERA_NAME))
        elif cam.type != "CAMERA":
            self.report({"ERROR"},
                        f"'{CAMERA_NAME}' exists and is not a camera")
            return {"CANCELLED"}

        if cam.name not in context.scene.collection.objects:
            try:
                context.scene.collection.objects.link(cam)
            except Exception:
                pass

        if made or self.reset_existing:
            cam.location = CAMERA_LOCATION
            cam.rotation_mode = "XYZ"
            cam.rotation_euler = tuple(radians(a) for a in CAMERA_ROTATION_DEG)
            try:
                cam.data.lens = CAMERA_LENS
                # The effects are hundreds of units across and the camera sits
                # 300 out, so the default 100-unit clip end would cut the far
                # half of an explosion off.
                cam.data.clip_start = 1.0
                cam.data.clip_end = 10000.0
            except Exception:
                pass

        if self.make_active:
            context.scene.camera = cam

        x, y, z = CAMERA_LOCATION
        self.report(
            {"INFO"},
            f"{'Created' if made else 'Reset'} {CAMERA_NAME} at "
            f"({x:g}, {y:g}, {z:g}), rotation "
            f"({CAMERA_ROTATION_DEG[0]:g}, {CAMERA_ROTATION_DEG[1]:g}, "
            f"{CAMERA_ROTATION_DEG[2]:g}) degrees"
            + (" · scene camera" if self.make_active else ""))
        print(f"{TAG}  house camera {'created' if made else 'reset'}")
        for o in context.selected_objects:
            o.select_set(False)
        cam.select_set(True)
        context.view_layer.objects.active = cam
        return {"FINISHED"}


CLASSES = (HTP_OT_HammerGrid, HTP_OT_HammerGridRemove, HTP_OT_HouseCamera)
