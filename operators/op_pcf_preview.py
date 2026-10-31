
import json
import os
import tempfile
import time

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty, IntProperty, StringProperty
from bpy.types import Operator

from ..tools import pcf_icons, pcf_preview
from . import op_particle_import as pi
from . import op_prefs

ADDON = __package__.split(".")[0]
ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER = os.path.join(ADDON_DIR, "tools", "preview_worker.py")
TOOL_DIR = os.path.join(ADDON_DIR, "# tools", "Create PCF Preview")
EXPERIMENTAL = "THIS FEATURE WAS ADDED IN VERSION 0.25.0 AND IS IN EXPERIMENTAL STAGE."
NEW = "THIS FEATURE WAS ADDED IN VERSION 0.26.0 AND IS IN EXPERIMENTAL STAGE."
NEW3 = "THIS FEATURE WAS ADDED IN VERSION 0.26.3 AND IS IN EXPERIMENTAL STAGE."


def _scripts_dir():
    """The `scripts` folder this add-on lives in (.../scripts/addons/<it>), so
    the worker Blender loads this very copy."""
    addons = os.path.dirname(ADDON_DIR)
    return os.path.dirname(addons) if os.path.basename(addons).lower() == "addons" else ""


def _worker_prefs():
    p = op_prefs.prefs()
    out = {}
    for key in ("sfm_usermod",):
        v = getattr(p, key, "") if p is not None else ""
        if v:
            out[key] = bpy.path.abspath(v)
    return out


def _particles_folder():
    try:
        usermod = op_prefs.find_usermod()
    except Exception:
        usermod = None
    return os.path.join(str(usermod), "particles") if usermod else ""


def _hex(c):
    return pcf_preview.rgb_hex(tuple(max(0.0, min(1.0, v)) * 255.0 for v in c[:3]))


# ── the choices both buttons share ───────────────────────────────────────────

class _CardChoices:
    title_text: StringProperty(
        name="Title", default="",
        description="The main title. Empty = read off the file name (everything before the first "
                    "brackets). " + NEW)
    tag_mode: EnumProperty(
        name="Tag", default="AUTO",
        items=(("AUTO", "From the Name", "The first ( ) group of the file name"),
               ("CUSTOM", "Custom", "The text in Tag Text, in brackets"),
               ("NONE", "No Tag", "No bracketed tag under the title")),
        description="The bracketed tag under the title. " + NEW)
    tag_text: StringProperty(name="Tag Text", default="",
                             description="Used when Tag is Custom; brackets are added. " + NEW)
    title_color_mode: EnumProperty(
        name="Title Colour", default="AUTO",
        items=(("AUTO", "Particle Hue", "The effect's dominant colour, read off its render "
                                        "(a grey effect keeps the neutral steel)"),
               ("FOLDER", "Folder Colour", "The pack folder's designated colour"),
               ("NEUTRAL", "Neutral", "The 0.25.0 steel plates"),
               ("CUSTOM", "Custom", "The colour picked below")),
        description="What colours the title band and the tag. " + NEW)
    title_color: FloatVectorProperty(name="Custom Title Colour", subtype="COLOR_GAMMA", size=3,
                                     min=0.0, max=1.0, default=(0.95, 0.45, 0.10),
                                     description="Used when Title Colour is Custom. " + NEW)
    folder_color_mode: EnumProperty(
        name="Folder Colour", default="AUTO",
        items=(("AUTO", "Designated", "The pack's own colour, kept in _preview colors.json in "
                                      "the icon folder (edit it there to change a pack)"),
               ("NEUTRAL", "Neutral", "The 0.25.0 steel path band and cream frame"),
               ("CUSTOM", "Custom", "The colour picked below")),
        description="What colours the path band and the frame. " + NEW)
    folder_color: FloatVectorProperty(name="Custom Folder Colour", subtype="COLOR_GAMMA", size=3,
                                      min=0.0, max=1.0, default=(0.85, 0.50, 0.15),
                                      description="Used when Folder Colour is Custom. " + NEW)
    view_yaw: FloatProperty(name="View Turn", default=0.0, soft_min=-180.0, soft_max=180.0,
                            description="Degrees to turn the camera around the effect from the "
                                        "particle editor's side. " + NEW)
    view_pitch: FloatProperty(name="View Tilt", default=-1.0, min=-1.0, max=89.0,
                              description="Degrees the camera looks down. -1 = automatic (15 with "
                                          "the ground grid, level without). " + NEW)
    zoom: FloatProperty(name="Zoom", default=1.0, min=0.25, max=4.0,
                        description="Above 1 moves closer than the automatic framing, below 1 "
                                    "further away. " + NEW)
    bars: EnumProperty(
        name="Bars", default="GLASS",
        items=(("GLASS", "Glass", "Translucent bars over a full-bleed picture - frosted, tinted, lit from "
                                  "behind, with bright edges that fade toward the ends"),
               ("SOLID", "Solid", "The 0.26.2 opaque plates, the picture boxed between them")),
        description="How the title, tag and path bars are drawn. " + NEW3)
    bar_alpha: FloatProperty(name="Bar Alpha", default=0.70, min=0.0, max=1.0, subtype="FACTOR",
                             description="How much of a glass bar is tint: 0 clear glass, 1 solid "
                                         "colour. " + NEW3)
    icon_dir: StringProperty(name="Icon Folder", subtype="DIR_PATH",
                             default=pcf_preview.DEFAULT_ICON_DIR,
                             description="Where folder .ico files and _preview colors.json (the "
                                         "packs' designated colours) live. " + NEW)

    def _style(self):
        style = {"title": self.title_text.strip() or None,
                 "subtitle": None if self.tag_mode == "AUTO" else
                 ("" if self.tag_mode == "NONE" else "(" + self.tag_text.strip().strip("()") + ")"),
                 "title_color": {"AUTO": "auto", "FOLDER": "folder", "NEUTRAL": "neutral"}.get(
                     self.title_color_mode) or _hex(self.title_color),
                 "folder_color": {"AUTO": "auto", "NEUTRAL": "neutral"}.get(
                     self.folder_color_mode) or _hex(self.folder_color),
                 "format": self.card_format.lower(),
                 "bars": self.bars.lower(), "bar_alpha": self.bar_alpha}
        return style

    def _view(self):
        return {"view_yaw": self.view_yaw or None,
                "view_pitch": None if self.view_pitch < 0 else self.view_pitch,
                "zoom": None if abs(self.zoom - 1.0) < 1e-6 else self.zoom}

    def _colours(self):
        d = bpy.path.abspath(self.icon_dir) if self.icon_dir else ""
        return pcf_preview.FolderColours(os.path.join(d, pcf_preview.COLORS_FILE) if d else None)

    def _draw_choices(self, col):
        box = col.box()
        box.prop(self, "title_text")
        row = box.row(align=True)
        row.prop(self, "tag_mode")
        if self.tag_mode == "CUSTOM":
            row.prop(self, "tag_text", text="")
        row = box.row(align=True)
        row.prop(self, "title_color_mode")
        if self.title_color_mode == "CUSTOM":
            row.prop(self, "title_color", text="")
        row = box.row(align=True)
        row.prop(self, "folder_color_mode")
        if self.folder_color_mode == "CUSTOM":
            row.prop(self, "folder_color", text="")
        row = box.row(align=True)
        row.prop(self, "view_yaw")
        row.prop(self, "view_pitch")
        row.prop(self, "zoom")
        row = box.row(align=True)
        row.prop(self, "bars", expand=True)
        if self.bars == "GLASS":
            row.prop(self, "bar_alpha")
        box.prop(self, "card_format", expand=True)
        box.prop(self, "icon_dir")


class _Runner:
    """Starts a Batch, watches it from a timer (or to the end, headless)."""
    _batch = None
    _timer = None
    _t0 = 0.0

    def _run(self, context):
        if bpy.app.background or context.window_manager is None or context.window is None:
            progress = self._batch.run(progress_path=os.path.join(self._batch.work, "progress.json"))
            return self._done(context, progress)
        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0, window=context.window)
        wm.modal_handler_add(self)
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC":
            self._batch.cancel()
            self._cleanup(context)
            p = self._batch.poll()
            self.report({"WARNING"}, f"PCF preview cancelled - {p['made']} card(s) made")
            return {"CANCELLED"}
        if event.type != "TIMER":
            return {"PASS_THROUGH"}
        p = self._batch.poll()
        try:
            context.workspace.status_text_set(
                f"PCF previews  {p['finished']}/{p['total']}  ({p['made']} made, {p['failed']} failed, "
                f"{p['workers']} workers, {int(p['elapsed'])} s)  -  Esc cancels")
        except Exception:
            pass
        if not p["done"]:
            return {"PASS_THROUGH"}
        self._cleanup(context)
        return self._done(context, p)

    def _cleanup(self, context):
        try:
            context.window_manager.event_timer_remove(self._timer)
        except Exception:
            pass
        try:
            context.workspace.status_text_set(None)
        except Exception:
            pass


def _pillow_ready(op):
    """3.0.1 ENSURE PIL: the cards and icons need Pillow - installed or repaired here when it is missing or broken
    (a progress bar while pip runs). Else the reason and the hand command, and nothing starts."""
    if pcf_preview.Image is not None:
        return True
    from ..tools import progress
    with progress.job("Source Particle Import - Ensure PIL"):
        progress.note("Installing Pillow (PIL) for this Blender - about 7 MB from PyPI")
        ok, msg = pcf_preview.need_pil()
    try:
        from . import op_dev
        op_dev.wiring(bpy.context, force=True)                 # the Preview Cards row says what happened
    except Exception:
        pass
    if not ok:
        op.report({"ERROR"}, msg)
        return False
    print(f"[HT_PIL]  {msg}")
    return True


def _work_dir():
    return os.path.join(bpy.app.tempdir or tempfile.gettempdir(), "htp_preview_%d" % int(time.time() * 1000))


#── Create PCF Preview ───────────────────────────────────────────────────────

class HTP_OT_CreatePcfPreview(_CardChoices, _Runner, Operator):
    # the docstring is the tooltip - and the rules for the card
    """Make the preview card for the .pcf chosen in the Import tab.

The effect is rendered the way SFM's particle editor shows it - pure black,
the editor's side of the camera, control point 0 turned the way the editor
turns it - at its brightest moment (or the one you set). A separate Blender
does the render, so this file is never touched. Then the card is drawn
around it, all of it read off the file's name and folder:

  MAIN TITLE     the name before the first ( )   burst ground blast
  SECOND TITLE   the first ( ) group             (HD)
  DESCRIPTION    optional, up to three lines
  PATH           the pack folder under particles, optionally the folder below
  GROUND GRID    a thin grid on the effect's ground, where it meets terrain
  COLOURS        the title takes the effect's own hue, the path band the
                 pack folder's designated colour (0.26.0)

Saved beside the .pcf as "<name> (preview).png", never over an existing card
(a taken name gets v2, v3 ...). Whole Folder makes a card for every .pcf in
that folder that does not have one yet.

THIS FEATURE WAS ADDED IN VERSION 0.25.0 AND IS IN EXPERIMENTAL STAGE"""
    bl_idname = "htp.create_pcf_preview"
    bl_label = "Create PCF Preview"
    bl_options = {"REGISTER"}

    description: StringProperty(
        name="Description",
        description="Optional text under the picture, up to three lines. Empty = "
                    "no description bar. " + EXPERIMENTAL,
        default="")
    include_sub_folder: BoolProperty(
        name="Second Path Line",
        description="Also write the folder below the pack folder (e.g. Burst 02 "
                    "Ground) as a second line under the path. " + EXPERIMENTAL,
        default=False)
    whole_folder: BoolProperty(
        name="Whole Folder",
        description="A card for every .pcf in this file's folder that has none "
                    "yet - the description is left out. " + EXPERIMENTAL,
        default=False)
    ground_grid: BoolProperty(
        name="Ground Grid",
        description="A thin grid on the effect's ground (z = 0 at its origin), so the card "
                    "shows where the effect sits against terrain. The camera looks a little "
                    "down to see it. " + EXPERIMENTAL,
        default=True)
    moment: FloatProperty(
        name="Moment",
        description="Seconds into the effect to show. 0 = the brightest moment, "
                    "found by rendering several. " + EXPERIMENTAL,
        default=0.0, min=0.0, soft_max=10.0, precision=2)
    card_format: EnumProperty(
        name="Card Format", default="PNG",
        items=(("PNG", "PNG", "Lossless, about 1-4 MB a card"),
               ("JPG", "JPG", "About half a megabyte a card - for big folders and a full drive")),
        description="The card's file type. " + NEW)
    pcf_path: StringProperty(
        name=".pcf", description="The .pcf to preview. Empty = the Import tab's file",
        default="", subtype="FILE_PATH", options={"SKIP_SAVE"})
    system: StringProperty(options={"HIDDEN", "SKIP_SAVE"})
    out_dir: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    #── choosing what to render ──────────────────────────────────────────
    def _files_and_system(self, context):
        p = pi.props(context)
        chosen = bpy.path.abspath(self.pcf_path) if self.pcf_path else \
            (bpy.path.abspath(p.definition_file) if p and p.definition_file else "")
        if not chosen or not os.path.isfile(chosen):
            return None, None, "Choose a .pcf in the Import tab first"
        if self.whole_folder:
            files = pcf_preview.folder_pcfs(os.path.dirname(chosen))
            if not files:
                return None, None, "Every .pcf in that folder already has a card"
            return files, None, ""
        system = self.system
        if not system and p is not None and not self.pcf_path:
            try:
                system = p.system if p.system not in ("", "__none__") else ""
            except Exception:
                system = ""
        return [chosen], (system or None), ""

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=480)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "description")
        col.prop(self, "include_sub_folder")
        col.prop(self, "ground_grid")
        col.prop(self, "moment")
        col.prop(self, "whole_folder")
        self._draw_choices(col)

    def execute(self, context):
        files, system, why = self._files_and_system(context)
        if not files:
            self.report({"ERROR"}, why)
            return {"CANCELLED"}
        if not _pillow_ready(self):
            return {"CANCELLED"}
        style = self._style()
        if system:
            style["system"] = system
        self._batch = pcf_preview.Batch(
            bpy.app.binary_path, _scripts_dir(), ADDON, WORKER, files, _work_dir(),
            workers=1 if len(files) == 1 else 3, prefs=_worker_prefs(), grid=self.ground_grid,
            moment=self.moment, view=self._view(), style=style, colours=self._colours(),
            include_sub_folder=self.include_sub_folder, description=self.description or None,
            out_dir=self.out_dir or None, keep_renders=False).start()
        return self._run(context)

    def _done(self, context, p):
        made = [r["card"] for r in self._batch.results.values() if r.get("ok")]
        for r in self._batch.results.values():
            print(f"[HT_PREVIEW]  {os.path.basename(r['pcf'])} -> "
                  f"{r['card'] if r.get('ok') else 'FAILED: ' + str(r.get('note'))}")
        if not made:
            note = next(iter(self._batch.results.values()), {}).get("note", "nothing rendered")
            self.report({"ERROR"}, f"No card made - see the console ({note})")
            return {"CANCELLED"}
        if len(made) == 1:
            self.report({"INFO"}, f"Card saved: {made[0]}")
        else:
            self.report({"INFO"}, f"{len(made)} cards saved beside their .pcf files"
                        + (f", {p['failed']} failed" if p["failed"] else ""))
        return {"FINISHED"}


# ── Process Entire Folder ────────────────────────────────────────────────────

class HTP_OT_ProcessPcfFolder(_CardChoices, _Runner, Operator):
    """Cards for every .pcf under a folder, then an icon for each folder in it.

Walks the folder and everything below it. Every effect WITHOUT a card gets
one (an existing card is never touched, never re-rendered), several worker
Blenders at once on your GPU. Then each folder DIRECTLY inside the one you
picked gets an orb icon (.ico) made from its best render, in the folder's
designated colour - picking "particles" gives every pack an icon, but not
the folders inside a pack.

Icons land in the Icon Folder. A folder that already shows an icon keeps it
unless you choose otherwise (the old desktop.ini is backed up first).
Stops by itself before the drive with the cards gets too full.

THIS FEATURE WAS ADDED IN VERSION 0.26.0 AND IS IN EXPERIMENTAL STAGE"""
    bl_idname = "htp.process_pcf_folder"
    bl_label = "Process Entire Folder"
    bl_options = {"REGISTER"}

    folder: StringProperty(name="Folder", subtype="DIR_PATH", default="",
                           description="The folder to process, with everything below it. Empty = "
                                       "the SFM particles folder. " + NEW)
    exclude: StringProperty(name="Skip Folders", default=", ".join(pcf_preview.DEFAULT_EXCLUDE),
                            description="Folder names (comma separated) skipped at any depth - "
                                        "their effects get no cards and no icon. " + NEW)
    workers: IntProperty(name="Workers", default=3, min=1, max=8,
                         description="Worker Blenders rendering at the same time. " + NEW)
    ground_grid: BoolProperty(name="Ground Grid", default=True,
                              description="The thin ground grid under every effect. " + NEW)
    moment: FloatProperty(name="Moment", default=0.0, min=0.0, soft_max=10.0, precision=2,
                          description="Seconds into every effect. 0 = each one's brightest "
                                      "moment. " + NEW)
    include_sub_folder: BoolProperty(name="Second Path Line", default=False,
                                     description="Also write the folder below the pack folder on "
                                                 "every card. " + NEW)
    card_format: EnumProperty(
        name="Card Format", default="JPG",
        items=(("PNG", "PNG", "Lossless, about 1-4 MB a card"),
               ("JPG", "JPG", "About half a megabyte a card - for big folders and a full drive")),
        description="The cards' file type. " + NEW)
    folder_icons: BoolProperty(name="Folder Icons", default=True,
                               description="An orb .ico for every folder directly inside the "
                                           "processed one. " + NEW)
    apply_icons: EnumProperty(
        name="Apply Icons", default="BARE",
        items=(("BARE", "Only Bare Folders", "Set the icon only on folders that show none yet"),
               ("ALL", "Replace Existing", "Set it on every folder (its old desktop.ini is backed "
                                           "up in the icon folder's _backups)"),
               ("NONE", "Only Write .ico", "Write the icon files, change no folder")),
        description="Which folders get their new icon set. " + NEW)
    guard_gb: FloatProperty(name="Keep Free (GB)", default=1.5, min=0.2, soft_max=20.0,
                            description="Stop before the drive the cards go on has less free space "
                                        "than this. " + NEW)
    work_dir: StringProperty(options={"HIDDEN", "SKIP_SAVE"})

    def invoke(self, context, event):
        if not self.folder:
            self.folder = _particles_folder()
        return context.window_manager.invoke_props_dialog(self, width=520)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "folder")
        col.prop(self, "exclude")
        row = col.row(align=True)
        row.prop(self, "workers")
        row.prop(self, "guard_gb")
        col.prop(self, "ground_grid")
        col.prop(self, "moment")
        col.prop(self, "include_sub_folder")
        row = col.row(align=True)
        row.prop(self, "folder_icons")
        sub = row.row(align=True)
        sub.enabled = self.folder_icons
        sub.prop(self, "apply_icons", text="")
        self._draw_choices(col)

    def _exclude(self):
        return tuple(x.strip() for x in self.exclude.split(",") if x.strip())

    def execute(self, context):
        root = bpy.path.abspath(self.folder) if self.folder else _particles_folder()
        if not root or not os.path.isdir(root):
            self.report({"ERROR"}, f"Not a folder: {root or '(none - set the SFM path in Preferences)'}")
            return {"CANCELLED"}
        self._root = root
        if not _pillow_ready(self):
            return {"CANCELLED"}
        files, counts = pcf_preview.collect_pcfs(root, self._exclude(), skip_carded=True)
        print(f"[HT_PREVIEW]  {root}: {len(files)} effect(s) need a card; {counts['carded']} already "
              f"have one, {counts['excluded_folders']} folder(s) skipped")
        work = bpy.path.abspath(self.work_dir) if self.work_dir else _work_dir()
        self._colours_map = self._colours()
        self._batch = pcf_preview.Batch(
            bpy.app.binary_path, _scripts_dir(), ADDON, WORKER, files, work,
            workers=self.workers, prefs=_worker_prefs(), grid=self.ground_grid, moment=self.moment,
            view=self._view(), style=self._style(), colours=self._colours_map,
            include_sub_folder=self.include_sub_folder, guard_free_gb=self.guard_gb).start()
        return self._run(context)

    def _done(self, context, p):
        icons = []
        if self.folder_icons and not self._batch.stopped:
            icon_dir = bpy.path.abspath(self.icon_dir) or pcf_preview.DEFAULT_ICON_DIR
            icons = pcf_icons.make_folder_icons(
                self._root, list(self._batch.results.values()), icon_dir, self._colours_map,
                self._exclude(), apply_bare=self.apply_icons == "BARE", apply_all=self.apply_icons == "ALL")
        report = {"root": self._root, "progress": p, "cards": list(self._batch.results.values()),
                  "icons": icons}
        path = os.path.join(self._batch.work, "report.json")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=1)
        except OSError:
            path = None
        applied = sum(1 for r in icons if r.get("applied"))
        msg = (f"{p['made']} card(s) made, {p['failed']} failed; {sum(1 for r in icons if r.get('icon'))} "
               f"folder icon(s), {applied} applied")
        if self._batch.stopped:
            msg += f" - STOPPED: {self._batch.stopped}"
        print(f"[HT_PREVIEW]  {msg}  (report: {path})")
        self.report({"WARNING"} if self._batch.stopped else {"INFO"}, msg)
        return {"FINISHED"}


class HTP_OT_OpenPreviewTool(Operator):
    """Open the folder holding the Text Editor version of Create PCF Preview.

"Create PCF Preview (V3).py" does the same jobs from Blender's Text Editor:
one .pcf, a folder, or PROCESS ENTIRE FOLDER with its icons - set the
values at the top, press Run Script.

THIS FEATURE WAS ADDED IN VERSION 0.25.0 AND IS IN EXPERIMENTAL STAGE"""
    bl_idname = "htp.open_preview_tool"
    bl_label = "Open Create PCF Preview Tool Folder"
    bl_options = {"REGISTER"}

    def execute(self, context):
        if not os.path.isdir(TOOL_DIR):
            self.report({"ERROR"}, f"Missing: {TOOL_DIR}")
            return {"CANCELLED"}
        if bpy.app.background:
            print(f"[HT_PREVIEW]  tool folder: {TOOL_DIR}")
            return {"FINISHED"}
        try:
            os.startfile(TOOL_DIR)
        except Exception as exc:
            bpy.ops.wm.path_open(filepath=TOOL_DIR)
            print(f"[HT_PREVIEW]  startfile failed ({exc}); used path_open")
        return {"FINISHED"}


CLASSES = (HTP_OT_CreatePcfPreview, HTP_OT_ProcessPcfFolder, HTP_OT_OpenPreviewTool)
