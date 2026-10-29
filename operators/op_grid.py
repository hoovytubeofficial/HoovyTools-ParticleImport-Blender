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
    """Lay a simple floor grid, at 1 Blender Unit = 1 Hammer Unit

Thin white lines and nothing between them, like SFM's own grid - a
particle under it stays visible. 16 Hammer units a square by default, with
an optional TF2 Scout height marker at 81.6924 units.

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
        description="How far the grid reaches from the origin, in Hammer units",
        default=128.0, min=16.0, max=4096.0, subtype="DISTANCE")
    spacing: FloatProperty(
        name="Square",
        description="One square of the grid, in Hammer units (Hammer's own grid is 16).\n\n"
                    "THIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE",
        default=16.0, min=1.0, max=1024.0, subtype="DISTANCE")
    line_width: FloatProperty(
        name="Line Width",
        description="How thick a line is, in Hammer units.\n\n"
                    "THIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE",
        default=0.35, min=0.01, max=16.0, subtype="DISTANCE")
    markers: BoolProperty(
        name="Scale Markers",
        description="An origin empty and a TF2 Scout height marker "
                    f"({hammer_grid.SCOUT_HEIGHT:.4g} units)",
        default=False)
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
        col.prop(self, "spacing")
        col.prop(self, "line_width")
        col.prop(self, "markers")
        col.separator()
        col.prop(self, "set_units")
        col.prop(self, "hide_in_render")

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=340)

    def execute(self, context):
        try:
            obj, info = hammer_grid.build_lines(
                extent=self.extent, spacing=self.spacing, width=self.line_width,
                markers=self.markers, set_units=self.set_units,
                hide_in_render=self.hide_in_render)
        except Exception as exc:
            self.report({"ERROR"}, f"Could not paint the grid: {exc}")
            print(f"{TAG}  FAILED: {exc}")
            return {"CANCELLED"}

        span = int(self.extent * 2)
        self.report(
            {"INFO"},
            f"{span} x {span} HU grid · {self.spacing:g} HU squares"
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
#  where the house camera aims (a Scout's middle) - frame_camera() keeps the same angle for any effect
CAMERA_AIM = (0.0, 0.0, 40.0)


def frame_camera(context, center, box):
    """3.0.0: the house camera's angle, pulled back until the box fits the frame. `box` = (width, depth, up, down)
    in Hammer units around `center` (the effect's control point). Returns the camera - made, or moved."""
    import math
    from mathutils import Vector
    w, d, up, down = (float(v) for v in box)
    h = up + down
    target = Vector(center) + Vector((0.0, 0.0, (up - down) * 0.5))
    radius = max(8.0, 0.5 * math.sqrt(w * w + d * d + h * h))
    cam = bpy.data.objects.get(CAMERA_NAME)
    if cam is None or cam.type != "CAMERA":
        cam = bpy.data.objects.new(CAMERA_NAME, bpy.data.cameras.new(CAMERA_NAME))
    if cam.name not in context.scene.collection.objects:
        try:
            context.scene.collection.objects.link(cam)
        except Exception:
            pass
    r = context.scene.render
    aspect = (r.resolution_y * r.pixel_aspect_y) / max(1.0, r.resolution_x * r.pixel_aspect_x)
    cam.data.lens = CAMERA_LENS
    half = math.atan((cam.data.sensor_width * 0.5 * min(1.0, aspect)) / cam.data.lens)
    dist = radius / math.sin(half) * 1.08
    direction = (Vector(CAMERA_LOCATION) - Vector(CAMERA_AIM)).normalized()
    cam.location = target + direction * dist
    cam.rotation_mode = "XYZ"
    cam.rotation_euler = (target - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_start = max(0.1, dist / 2000.0)
    cam.data.clip_end = max(10000.0, dist * 6.0)
    context.scene.camera = cam
    print(f"{TAG}  camera framed on a {w:.0f} x {d:.0f} x {h:.0f} HU effect, {dist:.0f} HU away")
    return cam


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
