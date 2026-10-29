# =============================================================================
# operators/op_particle_import.py  -  "import a .pcf like in SFM"
# =============================================================================
#
# THE UI (mirrors SFM's "Choose Particle System" dialog)
# Particle System Definition File:  [ path        ] [ Browse... ]
# Particle System Definition:       [ dropdown v  ]
# Start Time / Emission Duration / Particle System Lifetime
# [ OK ] [ Cancel ]
#
# one set of settings, TWO surfaces:
# * File > Import > Source Engine Assets (.PCF)  -> pops it as a dialog
# * 3D View sidebar > Particle Import            -> the same fields inline
# That is why the settings live on scene.htp instead of on the operator: a
# Panel cannot draw operator properties, and these five fields are not worth
# maintaining twice
#
# WHERE THINGS LAND
# __HoovyTools__ /  <system name> /  <the anchor empty>
# Every particle gets its OWN collection, because a system is never just one
# object - control points, emitters and helper empties all belong to it and
# need to move/hide/delete as a unit
# =============================================================================

import bpy
from pathlib import Path
from bpy.types import Operator, PropertyGroup
from bpy.props import (StringProperty, FloatProperty, EnumProperty,
                       BoolProperty, PointerProperty, IntProperty)
from bpy_extras.io_utils import ImportHelper

from . import op_prefs
from ..tools import pcf, htlog
from ..icons import tab_items


TAG = "[HT_PARTICLE]"
ROOT_COLLECTION = "__HoovyTools__"

# parsed-file stash. Module level because Blender EnumProperty item callbacks
# must return a stable Python object (rebuild it per call and the strings get
# garbage-collected mid-draw, which crashes Blender)
_STASH = {"path": "", "picker": [], "counts": {}, "enum_items": [],
          "hierarchy": None, "cp": {}}

_NO_SYSTEMS = [("__none__", "(no systems - pick a .pcf file)", "")]

# Source units -> metres. 1 Hammer unit = 0.75 inch = 0.01905 m, which is the
# factor you want when an SFM effect has to sit next to a real-scale model.
SCALE_SOURCE = 0.01905

# editors whose horizontal axis IS time, so the mouse X maps to a frame
_TIMELINE_AREAS = {"TIMELINE", "DOPESHEET_EDITOR", "GRAPH_EDITOR",
                   "NLA_EDITOR", "SEQUENCE_EDITOR"}


def _clear_stash():
    _STASH.update({"path": "", "picker": [], "counts": {},
                   "enum_items": list(_NO_SYSTEMS), "hierarchy": None,
                   "cp": {}})


def frame_under_mouse(context, event):
    """The frame the mouse is hovering, if it is over a time-based editor.

    Works for the Timeline, Dope Sheet, Graph Editor, NLA and Sequencer -
    they all put time on X, so region_to_view() gives the frame directly.
    Returns None when the pointer is somewhere else, and the caller falls
    back to 0."""
    if event is None:
        return None
    mx, my = event.mouse_x, event.mouse_y
    for area in context.screen.areas:
        if area.type not in _TIMELINE_AREAS:
            continue
        if not (area.x <= mx < area.x + area.width
                and area.y <= my < area.y + area.height):
            continue
        for region in area.regions:
            if region.type != "WINDOW":
                continue
            if not (region.x <= mx < region.x + region.width
                    and region.y <= my < region.y + region.height):
                continue
            try:
                frame, _y = region.view2d.region_to_view(mx - region.x,
                                                         my - region.y)
                return float(frame)
            except Exception:
                return None
    return None


def seconds_per_frame(scene):
    fps = scene.render.fps / scene.render.fps_base
    return (1.0 / fps) if fps else 0.0


def read_hint(path, exc=None):
    """3.0.0: what to try, from what the file looks like - the common reasons a .pcf will not read."""
    try:
        size = Path(path).stat().st_size
        head = Path(path).open("rb").read(64)
    except Exception:
        return "the file cannot be opened - is it still there, and not open in another program?"
    if size < 200:
        return ("the file is %d bytes - a .pcf with no particle systems in it (SFM writes 140 bytes for an "
                "empty one); open it in SFM's particle editor to check" % size)
    if not head.lstrip().startswith(b"<!-- dmx"):
        return "it does not start with a DMX header - is it really a particle file, or a renamed one?"
    if isinstance(exc, (ValueError, KeyError, IndexError)):
        return ("it is a DMX file this reader trips over - if SFM's particle editor opens it, press PRINT HELP "
                "(Dev tab) and send the .txt")
    return "open it in SFM's particle editor; if SFM loads it, press PRINT HELP (Dev tab) and send the .txt"


def load_pcf_into_stash(path_str):
    """Parse a .pcf into the stash. Returns an error string, or None on OK.

    3.0.0: every error names the file - its full path, its size, the stage, the exception and where in the
    add-on it happened (tools/htlog.failure) - and is kept for PRINT HELP."""
    if not path_str:
        _clear_stash()
        return "No file given."
    path = Path(bpy.path.abspath(path_str))
    if not path.is_file():
        _clear_stash()
        return htlog.failure("The .pcf is not there", pcf=path, stage="opening the file",
                             hint="it was moved, renamed or is on a drive that is not connected - browse to it "
                                  "again")
    try:
        dm = pcf.load_pcf(path)
        hierarchy = pcf.build_hierarchy(dm)
    except Exception as exc:
        _clear_stash()
        return htlog.failure("Could not read the .pcf", pcf=path, exc=exc,
                             stage="reading the particle file (DMX)", hint=read_hint(path, exc))

    picker = pcf.flatten_for_picker(hierarchy)
    if not picker:
        _clear_stash()
        return htlog.failure("No particle systems in the .pcf", pcf=path, stage="listing its systems",
                             hint=read_hint(path))

    _STASH["path"] = str(path)
    _STASH["picker"] = picker
    _STASH["counts"] = {n: len(k) for n, k in hierarchy["children"].items()}
    _STASH["hierarchy"] = hierarchy
    _STASH["cp"] = {}
    _rebuild_enum_items()
    print(f"{TAG}  {path.name}: {len(hierarchy['order'])} system(s), "
          f"{len(hierarchy['roots'])} root(s)")
    return None


def _rebuild_enum_items():
    items = []
    for name, depth in _STASH["picker"]:
        indent = "    " * depth + ("|- " if depth else "")
        n = _STASH["counts"].get(name, 0)
        tag = f"   [{n} {'child' if n == 1 else 'children'}]" if n else ""
        items.append((name, f"{indent}{name}{tag}",
                      f"{n} direct children" if n else "no children"))
    _STASH["enum_items"] = items or list(_NO_SYSTEMS)


def _system_enum_items(self, context):
    # must return the same cached list object each call - never rebuild here
    return _STASH["enum_items"] or _NO_SYSTEMS


def _select_first_system(props):
    items = _STASH["enum_items"]
    if items and items[0][0] != "__none__":
        try:
            props.system = items[0][0]
        except Exception:
            pass


def _on_path_edited(self, context):
    """Typed or pasted a path - parse it immediately, same as Browse."""
    if not self.definition_file:
        return
    if str(Path(bpy.path.abspath(self.definition_file))) == _STASH["path"]:
        return                       # already parsed (invoke() re-syncs this)
    err = load_pcf_into_stash(self.definition_file)
    if err:
        print(f"{TAG}  {err}")
    _select_first_system(self)


# =============================================================================
# Settings live on the Scene so the panel and the dialog share them
# =============================================================================

# 3.0.0: set while the playhead handler / a preset writes a field, so the field's own update can tell "you typed
# it" (switch the automatic off) from "it was set for you" (leave it on)
_AUTO = {"on": False}


def _start_time_edited(self, _context):
    if not _AUTO["on"] and self.follow_playhead:
        self.follow_playhead = False


def _time_scale_edited(self, _context):
    if not _AUTO["on"] and self.match_blend:
        self.match_blend = False


def blend_time_scale(scene):
    """Match .blend: the scene's frame rate over SFM's 24."""
    fps = scene.render.fps / (scene.render.fps_base or 1.0)
    return fps / 24.0

class HTP_Props(PropertyGroup):
    # NOTE: deliberately NO subtype="FILE_PATH". That subtype makes Blender
    # draw its own little folder button, which sat right next to our SFM-style
    # "Browse..." and looked like a duplicated control
    definition_file: StringProperty(
        name="Particle System Definition File",
        description="Path to the .pcf holding the particle system definitions",
        update=_on_path_edited,
    )
    system: EnumProperty(
        name="Particle System Definition",
        description="Which system to import - children are indented under "
                    "their parent, parents show their child count",
        items=_system_enum_items,
    )
    start_time: FloatProperty(
        name="Start Time", description="When the system starts, in seconds. Follows the playhead while the "
                                       "clock beside it is on - typing a value switches that off",
        default=0.0, min=0.0, precision=4, update=_start_time_edited,
    )
    follow_playhead: BoolProperty(
        name="Follow Playhead",
        description="Start Time follows the timeline: scrub, and the effect will start where the playhead is.\n\n"
                    "THIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE",
        default=True,
    )
    match_blend: BoolProperty(
        name="Match .blend",
        description="Time Scale from this .blend's frame rate (fps / 24) - read again when you build, so changing "
                    "the scene's frame rate later is followed.\n\nTHIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN "
                    "EXPERIMENTAL STAGE",
        default=True,
    )
    developer_mode: BoolProperty(
        name="Developer Mode",
        description="Show the extras for whoever works ON the add-on - the folder of each tool's Text Editor "
                    "version (under Create PCF Preview and Calculate Size). It changes what the panel shows, never "
                    "what a tool does.\n\nTHIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE",
        default=False,
    )
    emission_duration: FloatProperty(
        name="Emission Duration",
        description="How long the system emits new particles, in seconds",
        default=5.0, min=0.0,
    )
    lifetime: FloatProperty(
        name="Particle System Lifetime",
        description="Total time the system stays alive, in seconds",
        default=5.0, min=0.0,
    )
    scale: FloatProperty(
        name="Scale",
        description="Size multiplier for the imported effect. 1 keeps Source "
                    "units; 0.01905 converts them to metres (1 Hammer unit = "
                    "0.75 inch). Not applied yet - UI only",
        default=1.0, min=0.000001, precision=5,
    )
    time_scale: FloatProperty(
        name="Time Scale",
        description="How fast the effect plays: 1 is the authored speed, "
                    "0.5 half, 0 frozen. The FPS presets set FPS/24 (SFM's "
                    "timeline is 24 FPS) so one rendered frame carries one "
                    "SFM frame's worth of effect-time at your scene's frame "
                    "rate. Applied to every system the build creates; "
                    "editable afterwards per system under the modifier's "
                    "SYSTEM PROPERTIES",
        default=1.0, min=0.0, update=_time_scale_edited,
    )
    active_tab: EnumProperty(
        name="Tab",
        items=tab_items,
        # dynamic enums require a numeric default; 0 is the existing Import ID.
        default=0,
    )
    props_show_disabled: BoolProperty(
        name="Show Disabled",
        description="Also list operators whose toggle is off - imports "
                    "switch off everything the .pcf does not author, so "
                    "this reveals the full catalogue",
        default=False,
    )
    # Blender keeps a collapsible panel's open/closed state per idname and
    # offers no API to close one - so "Minimize All" bumps this generation
    # counter instead: fresh idnames, fresh (closed) defaults. Hidden,
    # because it's a mechanism, not a setting
    props_fold_gen: IntProperty(default=0, options={"HIDDEN"})
    # `vtf_preview_sphere` USED TO LIVE HERE as a panel checkbox you had to
    # find and set BEFORE pressing Import. It is a choice about the import
    # you are making right now, so it is now a property of the import
    # operators themselves and appears in the file browser, next to the file
    # it applies to


def props(context):
    return getattr(context.scene, "htp", None)


def draw_import_ui(layout, context, compact=False, in_dialog=False):
    """The SFM-style settings block. Shared by the dialog and the sidebar.

    in_dialog matters for Browse: Blender cannot nest a file browser inside a
    dialog, so the dialog has to close, browse, and re-open itself. From the
    sidebar there is no dialog to restore."""
    p = props(context)
    if p is None:
        layout.label(text="Add-on properties not registered", icon="ERROR")
        return

    from ..icons import icon_id
    box = layout.box()
    col = box.column()
    col.label(text="Particle System Definition File:")
    row = col.row(align=True)
    row.prop(p, "definition_file", text="")
    browse = row.operator(HTP_OT_BrowsePCF.bl_idname, text="Browse...",
                          icon="FILEBROWSER")
    browse.reopen_dialog = in_dialog
    col.label(text="Particle System Definition:")
    sub = col.row()
    sub.enabled = bool(_STASH["picker"])
    sub.prop(p, "system", text="")

    box = layout.box()
    col = box.column(align=True)
    if compact:
        row = col.row(align=True)
        row.prop(p, "start_time")
        # the clock is the switch: on, Start Time follows the playhead while you scrub
        row.prop(p, "follow_playhead", text="", icon="TIME", toggle=True)
        col.prop(p, "emission_duration")
        col.prop(p, "lifetime")
    else:
        split = col.split(factor=0.45)
        left, right = split.column(align=True), split.column(align=True)
        left.label(text="Start Time:")
        row = right.row(align=True)
        row.prop(p, "start_time", text="")
        row.prop(p, "follow_playhead", text="", icon="TIME", toggle=True)
        for label, key in (("Emission Duration:", "emission_duration"),
                           ("Particle System Lifetime:", "lifetime")):
            left.label(text=label)
            right.prop(p, key, text="")

    box = layout.box()
    col = box.column(align=True)
    col.label(text="Scale:")
    row = col.row(align=True)
    one = row.operator(HTP_OT_SetScale.bl_idname, text="1",
                       depress=abs(p.scale - 1.0) < 1e-9)
    one.value = 1.0
    src = row.operator(HTP_OT_SetScale.bl_idname, text="0.01905",
                       depress=abs(p.scale - SCALE_SOURCE) < 1e-9)
    src.value = SCALE_SOURCE
    col.prop(p, "scale", text="")
    col.separator()
    # Time Scale: Match .blend (the default - fps / 24, read at build time) or a preset "my scene runs at N FPS",
    # each FPS / 24 because SFM's timeline is 24 FPS. The field takes any value by hand.
    col.label(text="Time Scale:")
    split = col.split(factor=0.5, align=True)
    m = split.operator(HTP_OT_SetTimeScale.bl_idname, text="Match .blend", depress=p.match_blend)
    m.value = -1.0
    row = split.row(align=True)
    for fps in (24, 30, 60):
        v = fps / 24.0
        b = row.operator(HTP_OT_SetTimeScale.bl_idname, text=f"{fps}",
                         depress=(not p.match_blend) and abs(p.time_scale - v) < 1e-9)
        b.value = v
    col.prop(p, "time_scale", text="")

    # THE BUTTON THAT BUILDS IT - big, with its own icon (3.0.0). NOT IN THE DIALOG: the dialog's confirm button
    # is "Build This System" already
    if not in_dialog:
        row = layout.row()
        row.scale_y = 2.2
        row.enabled = bool(_STASH["picker"]) \
            and p.system not in ("", "__none__")
        row.operator(HTP_OT_BuildParticleSystem.bl_idname,
                     text="BUILD THIS SYSTEM", **icon_id("build_system", "PARTICLES"))


# =============================================================================
# Placing the system
# =============================================================================

def set_system_socket(obj, socket_name, value):
    """Set one named modifier input on a built system. Returns True if set.

    Shared by the importer (Start Time -> Time Offset) and the api module -
    the socket names in SYSTEM PROPERTIES are the stable surface other code
    is allowed to reach for."""
    for m in getattr(obj, "modifiers", []):
        ng = getattr(m, "node_group", None)
        if ng is None:
            continue
        for it in ng.interface.items_tree:
            if getattr(it, "item_type", "") == "SOCKET" \
                    and it.in_out == "INPUT" and it.name == socket_name:
                try:
                    getattr(m.properties.inputs, it.identifier).value = value
                    return True
                except Exception:
                    try:
                        m[it.identifier] = value
                        return True
                    except Exception:
                        return False
    return False


def _unique_collection_name(base):
    if base not in bpy.data.collections:
        return base
    i = 1
    while f"{base}.{i:03d}" in bpy.data.collections:
        i += 1
    return f"{base}.{i:03d}"


def particle_collection(context, system_name):
    """__HoovyTools__ / <system name>, created if missing.

    Each particle gets its own collection: a system is never one object once
    control points and helpers arrive, and they must move/hide/delete as one."""
    scene_root = context.scene.collection
    root = bpy.data.collections.get(ROOT_COLLECTION)
    if root is None:
        root = bpy.data.collections.new(ROOT_COLLECTION)
    if root.name not in scene_root.children:
        try:
            scene_root.children.link(root)
        except Exception:
            pass

    sub = bpy.data.collections.new(_unique_collection_name(system_name))
    root.children.link(sub)
    return sub


# =============================================================================
# building what was parsed
# =============================================================================
#
# one OBJECT PER SYSTEM, parent first, children pointed at it
#
# 🔴 DEPENDENCIES RUN PARENT -> CHILD and NEVER BACK. A child reads its
# parent's particles through Object Info, which makes the depsgraph evaluate
# the parent first for free. A parent reading a child would be a CYCLE, and
# Blender answers a cycle with empty geometry and no error worth the name.
#
# Depth-first, so the parent object exists before anything points at it.

def _material_roots():
    """Every `materials` folder worth looking in, most specific first."""
    roots = []
    usermod = op_prefs.find_usermod()
    if usermod is not None:
        game = usermod.parent
        for rel in ("usermod/materials", "tf/materials", "hl2/materials",
                    "workshop/materials", "unpack/materials"):
            d = game / Path(rel)
            if d.is_dir():
                roots.append(d)
    return roots


# BUNDLED FALLBACK MATERIALS - "usable particles when a material fucks up"
# A system whose material is AUTHORED but doesn't resolve on this machine
# (missing .vmt, missing .vtf - somebody else's pack, an unmounted game) used
# to become an invisible driver: correct motion, nothing to look at. These
# three generics ship inside the add-on (~140 KB) so that case draws
# SOMETHING plausible instead - per renderer:
# animated sprites -> glow_a          (soft additive glow)
# sprite trail     -> __sparks_hd_a   (spark streak sheet)
# rope             -> beam_b/beam_bm  (additive beam)
# A system with NO material at all keeps the invisible driver: SFM draws
# nothing for those on purpose (they are motion carriers for children)
_FALLBACK_VMT = {"ANIMATED_SPRITES": "glow_a.vmt",
                 "SPRITE_TRAIL": "__sparks_hd_a.vmt",
                 "ROPE": "beam_b.vmt"}
_fallback_cache = {}


def _fallback_chain(renderer):
    """Resolve a bundled fallback material -> the same chain dict
    vmt_tool.resolve returns, or None if the bundle is missing."""
    key = (renderer or "ANIMATED_SPRITES").upper()
    name = _FALLBACK_VMT.get(key, "glow_a.vmt")
    if name in _fallback_cache:
        return _fallback_cache[name]
    from ..tools import vmt as vmt_tool
    mdir = Path(__file__).resolve().parent.parent / "materials"
    chain = None
    try:
        vmt_path = mdir / name
        if vmt_path.is_file():
            c = vmt_tool.resolve_path(vmt_path, [mdir])
            if c.get("vtf"):
                chain = c
    except Exception as exc:
        print(f"{TAG}  fallback material {name}: {exc}")
    _fallback_cache[name] = chain
    return chain


def subtree_control_points(name, hierarchy, seen=None):
    """The control points a WHOLE effect needs: (count, referenced indices).

    🔴 COUNTED ONCE, FOR THE TREE. A control point is a property of the effect,
    not of one system in it - a child that reads CP2 means the effect's CP2,
    the same empty its parent reads. Counting per system produced one stack of
    empties per system, all at the same place, none of them shared, and moving
    the effect meant dragging every stack.

    The count is the HIGHEST any system asks for, because the numbering has to
    stay dense: a system wanting CP5 needs 0..5 to exist even if nothing reads
    3 and 4. The referenced set is the union, and it only marks which ones
    matter in the outliner."""
    from ..tools import pcf_build

    seen = seen if seen is not None else set()
    if name in seen:
        return 1, set()
    seen.add(name)
    sysdef = hierarchy["systems"].get(name)
    if sysdef is None:
        return 1, set()
    plan = pcf_build.plan(sysdef)
    count = max(1, int(plan.get("cp_count", 1)))
    used = set(plan.get("cp_indices") or ())
    for child in hierarchy["children"].get(name, []):
        c_count, c_used = subtree_control_points(child, hierarchy, seen)
        count = max(count, c_count)
        used |= c_used
    return count, used


def material_key(material):
    """One spelling per material: case, slashes, a `materials/` prefix and
    the `.vmt` extension all vary between files that mean the same .vmt."""
    k = str(material).strip().lower().replace("\\", "/")
    while "//" in k:
        k = k.replace("//", "/")
    if k.startswith("materials/"):
        k = k[len("materials/"):]
    if k.endswith(".vmt"):
        k = k[:-4]
    return k


def sprite_material_users(name, hierarchy, counts=None, path=()):
    """0.24.2: how many render_animated_sprites systems in this effect draw
    with each material. SFM draws a sprite system TWICE when its material is
    shared with another sprite system in the effect, once otherwise (measured,
    calibration kits 1 and 3). Counts every INSTANCE - a definition spawned by
    two parents is two live systems."""
    from ..tools import pcf_build

    counts = counts if counts is not None else {}
    if name in path:
        return counts
    sysdef = hierarchy["systems"].get(name)
    if sysdef is None:
        return counts
    plan = pcf_build.plan(sysdef)
    if (plan.get("renderer") or "").upper() == "ANIMATED_SPRITES" \
            and not plan.get("container") and plan.get("material"):
        key = material_key(plan["material"])
        counts[key] = counts.get(key, 0) + 1
    for child in hierarchy["children"].get(name, []):
        sprite_material_users(child, hierarchy, counts, path + (name,))
    return counts


# (Set Control Point Positions is handled PER SYSTEM inside
# build_system_tree - each authoring system gets its own override empties,
# because sibling systems legally author DIFFERENT offsets for the same CP.)


def build_system_tree(context, name, hierarchy, parent_host=None,
                      collection=None, depth=0, made=None, log=None,
                      used=None, root=None, cps=None, outline_parent=None,
                      name_prefix=None, mat_users=None):
    """Build one system and, depth-first, everything it spawns.

    ⚠️ ONE DEFINITION CAN BE SPAWNED BY SEVERAL PARENTS, and each of those is
    a separate live system - the Ground Fire effect hangs the same `-smoke`
    and `-glow` off two different fires. Reusing the system NAME for the host
    object would make the second occurrence overwrite the first, so a repeat
    gets `#2`, `#3` and its own node group."""
    from ..tools import pcf_build, control_points, vmt as vmt_tool
    from .op_ras import build_ras

    made = made if made is not None else []
    log = log if log is not None else []
    used = used if used is not None else {}

    # WHAT THIS INSTANCE IS CALLED, as opposed to what the DEFINITION is
    # called. Everything this add-on re-finds by name is built from `prefix`,
    # so two instances of one definition cannot land on each other's objects
    # See api.build_effect's note - a post-hoc rename can't fix this,
    # because each lookup happens at its own moment inside the build
    prefix = name_prefix or name
    sysdef = hierarchy["systems"].get(name)
    if sysdef is None:
        log.append(f"{'  ' * depth}!! '{name}' is not in this file")
        return made, log
    # 0.24.2: which sprite materials this effect shares, counted once at the
    # top of the tree and handed down (decides each system's Draws).
    if mat_users is None:
        mat_users = sprite_material_users(name, hierarchy)

    # ── the effect's one control empty and one set of control points ─────
    # Made here, at the top of the recursion, and handed to every system
    # below. See tools/control_points.py for why this isn't per system
    if root is None:
        cp_count, cp_used = subtree_control_points(name, hierarchy)
        root = control_points.effect_root(
            f"{prefix} · CONTROL", collection=collection,
            location=context.scene.cursor.location)
        cps = control_points.spawn(prefix, cp_count, root=root,
                                   collection=collection,
                                   indices=sorted(cp_used))
        made.append(root)
        log.append(f"{'  ' * depth}{prefix} · CONTROL   "
                   f"{control_points.describe(cp_count, sorted(cp_used))}, "
                   f"shared by the whole effect")

    used[name] = used.get(name, 0) + 1
    unique = name if used[name] == 1 else f"{name}#{used[name]}"
    _BUILD["i"] += 1
    try:
        from ..tools import progress
        progress.update(_BUILD["i"], max(_BUILD["n"], _BUILD["i"]), item=unique)
    except Exception:
        pass
    # per-system objects are re-found by name too (container anchors, control
    # point overrides). Namespace them to the instance for the same reason.
    uname = unique if not name_prefix else f"{name_prefix} · {unique}"

    plan = pcf_build.plan(sysdef)
    log.extend(pcf_build.describe_plan(("  " * depth) + unique, plan))

    #── Set Control Point Positions, PER SYSTEM ──────────────────────────
    #🔴 in SFM every SYSTEM OWNS its own CONTROL POINT ARRAY, and this
    #operator re-asserts offsets into it constantly - it is how the
    #cinematic smoke places five puffs: each SIBLING system authors
    #DIFFERENT CP1..CP3 offsets. One shared set per effect can't hold
    #five different CP1s (first-wins collapsed all the puffs onto one
    #arrangement), so a system that authors placements gets its own
    #override empties for exactly those indices. They are parented to
    #the effect root, so "track an offset from the parent CP" happens by
    #construction - move the effect and they come along - and they stay
    #yours to grab or animate. Children inherit the overridden array,
    #which is SFM's parent -> child CP propagation.
    placements = plan.get("cp_placements") or {}
    cp_head, cp_world = plan.get("cp_frame") or (0, False)
    my_cps = cps
    if placements and cps:
        my_cps = list(cps)
        placed = []
        for idx in sorted(placements):
            if not (0 <= idx < len(my_cps)):
                continue
            em_name = f"{uname} · CP{idx}"
            em = bpy.data.objects.get(em_name)
            if em is None or em.type != "EMPTY":
                em = bpy.data.objects.new(em_name, None)
            em.empty_display_type = "PLAIN_AXES"
            em.empty_display_size = control_points.cp_display_size(idx)
            em["htp_control_point"] = idx
            em["htp_cp_override_for"] = unique
            if collection is not None:
                for c in list(em.users_collection):
                    c.objects.unlink(em)
                collection.objects.link(em)
            if root is not None:
                # 🔴 0.26.3: the offsets are in the head control point's frame.
                # Source transforms them by that CP's matrix, so a beam's far
                # end turns with CP0 - parked under the effect's TRANSFORM,
                # the oscillator jet's glow beam ran sideways the moment the
                # preview turned CP0 by 90. The empty hangs off the head CP
                # (still under TRANSFORM, so one grab moves everything);
                # "Set positions in world space" keeps the TRANSFORM itself.
                head_obj = None
                if not cp_world and 0 <= cp_head < len(cps):
                    head_obj = cps[cp_head]
                if head_obj is None or head_obj is em:
                    head_obj = control_points.find_transform(root) or root
                em.parent = head_obj
                em.matrix_parent_inverse.identity()
            em.location = placements[idx]
            made.append(em)
            my_cps[idx] = em
            placed.append(idx)
        if placed:
            log.append(f"{'  ' * depth}  Set Control Point Positions   "
                       f"CP{placed} are {unique}'s OWN empties at the "
                       f"authored offsets in CP{cp_head}'s frame"
                       f"{' (world space)' if cp_world else ''}")
    cps = my_cps

    # A container holds children and draws nothing. Give it an anchor empty so
    # the children have something to hang off, and move on
    if plan.get("container"):
        anchor = bpy.data.objects.get(uname)
        if anchor is None or anchor.type != "EMPTY":
            anchor = bpy.data.objects.new(uname, None)
        anchor.empty_display_type = "SPHERE"
        anchor.empty_display_size = 16.0
        anchor["htp_system"] = name
        anchor["htp_container"] = True
        control_points.attach(anchor, outline_parent or root)
        if collection is not None:
            for c in list(anchor.users_collection):
                c.objects.unlink(anchor)
            collection.objects.link(anchor)
        elif anchor.name not in context.scene.collection.objects:
            context.scene.collection.objects.link(anchor)
        made.append(anchor)
        for child in hierarchy["children"].get(name, []):
            build_system_tree(context, child, hierarchy, parent_host=None,
                              collection=collection, depth=depth + 1,
                              made=made, log=log, used=used,
                              root=root, cps=cps, outline_parent=anchor,
                              name_prefix=name_prefix, mat_users=mat_users)
        return made, log

    #material -> .vmt -> $basetexture -> .vtf
    chain = {"vtf": None, "shader": "", "values": {}}
    if plan["material"]:
        chain = vmt_tool.resolve(plan["material"], _material_roots())
        if chain["vmt"] is None:
            log.append(f"      !! no .vmt found for {plan['material']}")
        elif chain["vtf"] is None:
            log.append(f"      !! {chain['vmt'].name}: shader "
                       f"{chain['shader']!r}, texture "
                       f"{chain['texture_ref']!r} not on disk")
        else:
            log.append(f"      texture       {chain['vtf'].name}  "
                       f"(shader {chain['shader']}, overbright "
                       f"{vmt_tool.overbright(chain['values']):g})")
    #A system whose texture does not resolve is no LONGER skipped - the old
    #early return dropped its whole child subtree with it (a material-less
    #"circling" driver took its beam child down; one missing .vtf erased a
    #whole fire layer). Two cases now:
    #- material AUTHORED but broken on this machine -> a bundled FALLBACK
    #generic (glow / spark sheet / beam, by renderer), so the user gets
    #usable particles instead of holes;
    #- NO material authored -> an INVISIBLE DRIVER (SFM draws nothing for
    #those on purpose - they are motion carriers), children still ride.
    driver = False
    if chain["vtf"] is None:
        if plan["material"]:
            fb = _fallback_chain(plan["renderer"])
            if fb is not None:
                chain = fb
                log.append(f"      FALLBACK material - "
                           f"{Path(fb['vmt']).name} stands in for the "
                           f"unresolved {plan['material']!r}")
            else:
                driver = True
                log.append("      DRIVER (texture unresolved, no fallback "
                           "bundle); invisible, children ride it")
        else:
            driver = True
            log.append("      DRIVER (no material - a motion carrier); "
                       "invisible, children ride it")

    # 0.24.2: A SPRITECARD MATERIAL ON A TRAIL DRAWS nothing IN SFM - measured
    # twice (calibration kits 2 and 4: blend, $additive and $addoverblend on
    # flat and ramp textures, not one pixel, while UnlitGeneric trails beside
    # them drew). Built as an invisible driver, so its children still ride it
    if not driver and (plan.get("renderer") or "").upper() == "SPRITE_TRAIL" \
            and str(chain.get("shader") or "").strip().lower() == "spritecard":
        driver = True
        log.append("      DRAWS NOTHING  a SpriteCard material on a trail - SFM "
                   "does not draw it (measured); invisible, children ride it")

    # The material FAMILY, decided once in tools/vmt.py: a Refract material
    # imports as a WARP - its picture is a normal map that bends what renders
    # behind the cards, not an emissive sprite. (A driver has no picture.)
    warp = None
    if not driver and vmt_tool.material_class(
            chain["shader"], chain.get("texture_key")) == "WARP":
        warp = vmt_tool.warp_params(chain["values"])
        log.append(f"      WARP material  $refractamount "
                   f"{warp['refract_amount']:g}, $bluramount "
                   f"{warp['blur_amount']:g}")

    #0.24.2: TWO DRAWS ONLY FOR A SHARED SPRITE MATERIAL (measured)
    n_draws = 1
    if (plan.get("renderer") or "").upper() == "ANIMATED_SPRITES" \
            and plan["material"]:
        sharers = mat_users.get(material_key(plan["material"]), 0)
        if sharers >= 2:
            n_draws = 2
            log.append(f"      drawn twice   {sharers} sprite systems in this "
                       f"effect use this material - SFM draws each twice")

    try:
        host, info = build_ras(
            context, None if driver else chain["vtf"], plan["values"],
            emitter="SIMULATION", renderer=plan["renderer"],
            cp_count=plan["cp_count"], stack=plan["stack"],
            parent=parent_host,
            # The SFM system name, NAMESPACED TO this INSTANCE.
            #
            # `unique` alone is unique within one .pcf - which is all it
            # needed to be while one effect was built at a time. It is not
            # unique across two INSTANCES of the same effect, and build_ras
            # re-finds its host by this name (see its own comment a few lines
            # above the lookup). So the second fire found the first fire's
            # host meshes and took them: the first effect kept its CONTROL,
            # its TRANSFORM and its control points, and lost every mesh that
            # carries the geometry nodes.
            #
            # Same failure the comment at that lookup already describes for
            # siblings, one level up - across instances rather than within
            # a file
            host_name=uname,
            overbright=vmt_tool.overbright(chain["values"]),
            additive=vmt_tool.is_additive(chain["values"]),
            blend=vmt_tool.blend_mode(chain["values"]),
            warp=warp,
            # The effect's own control empty and its ONE shared set of
            # control points - not a fresh stack per system.
            root=root, cps=cps, collection=collection, draws=n_draws)
    except Exception as exc:
        log.append(f"      FAILED to build: {type(exc).__name__}: {exc}")
        htlog.failure("Could not build a system", pcf=_STASH.get("path") or None, system=name, exc=exc,
                      stage="building its geometry nodes (renderer %s, material %s)"
                            % (plan.get("renderer") or "?", plan.get("material") or "none"),
                      hint="the rest of the effect still builds; press PRINT HELP (Dev tab) and send the .txt")
        return made, log

    host["htp_system"] = name
    host["htp_pcf_path"] = _STASH.get("path", "")
    host["htp_dropped"] = len(plan["ignored"])
    made.append(host)
    if collection is not None:
        for c in list(host.users_collection):
            c.objects.unlink(host)
        collection.objects.link(host)
    # the OUTLINER MIRRORS the SFM TREE. A child system's mesh is parented
    # to its parent's mesh (everything sits at the shared origin, so this
    # changes structure, not transforms) - the effect reads as the
    # hierarchy it actually is instead of a flat pile under the root
    if outline_parent is not None:
        control_points.attach(host, outline_parent)

    for child in hierarchy["children"].get(name, []):
        build_system_tree(context, child, hierarchy, parent_host=host,
                          collection=collection, depth=depth + 1,
                          made=made, log=log, used=used,
                          root=root, cps=cps, outline_parent=host,
                          name_prefix=name_prefix, mat_users=mat_users)
    return made, log


_BUILD = {"i": 0, "n": 0}


def subtree_names(name, hierarchy, seen=None):
    """Every system a build of `name` makes, itself first (a definition reached twice counts twice, as it builds)."""
    seen = seen if seen is not None else []
    seen.append(name)
    for child in hierarchy["children"].get(name, []):
        if seen.count(child) < 8:
            subtree_names(child, hierarchy, seen)
    return seen


def auto_camera(context, pcf_file, system, center):
    """3.0.0: no camera in the scene -> one framed on the effect's estimated size (tools/pcf_size). The note, or ""."""
    if any(o.type == "CAMERA" for o in context.scene.objects):
        return ""
    try:
        from ..tools import pcf_size
        from .op_grid import frame_camera
        res = pcf_size.estimate(pcf_file, system)
        t = res["total"]
        cam = frame_camera(context, center, (t["width"], t["depth"], t["up"], t["down"]))
        return ("no camera was in the scene - '%s' frames it (the effect is about %d x %d x %d units)"
                % (cam.name, round(t["width"]), round(t["depth"]), round(t["height"])))
    except Exception as exc:
        print(f"{TAG}  automatic camera skipped: {type(exc).__name__}: {exc}")
        return ""


def _tell(context, title, lines):
    """A short popup for what the import did by itself - never in the background, never when Errors is Console."""
    if bpy.app.background or getattr(context, "window", None) is None or op_prefs.feedback() == "QUIET":
        return

    def draw(menu, _ctx):
        col = menu.layout.column(align=True)
        for ln in lines:
            col.label(text=ln)

    try:
        context.window_manager.popup_menu(draw, title=title, icon="OUTLINER_OB_CAMERA")
    except Exception:
        pass


from bpy.app.handlers import persistent


@persistent
def _follow_playhead(scene, _depsgraph=None):
    """3.0.0: Start Time follows the timeline while the clock is on."""
    p = getattr(scene, "htp", None)
    if p is None or not p.follow_playhead:
        return
    t = scene.frame_current * seconds_per_frame(scene)
    if abs(p.start_time - t) > 1e-6:
        _AUTO["on"] = True
        try:
            p.start_time = t
        finally:
            _AUTO["on"] = False


class HTP_OT_BuildParticleSystem(Operator):
    """Build the chosen particle system for real.

Reads the .pcf definition and stands the whole effect up in the scene:
ONE object per system (a child system is its own object, born on its
parent's particles), the materials resolved through the .vmt chain, one
shared control-point rig for the entire effect, and a geometry-nodes
modifier organised by SFM section - every value the file authored, on a
socket you can edit.

Everything the importer cannot translate is REPORTED in the console,
never dropped silently; a warning on this button afterwards means go read
that list. Systems using the simulation emitter need playback from
frame 1 - a simulation cannot be scrubbed backwards into.

A bar shows the build system by system. A scene with no camera gets one,
framed on the effect's estimated size, and a note says so.

THIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE"""
    bl_idname = "htp.build_particle_system"
    bl_label = "Build Particle System"
    bl_options = {"REGISTER", "UNDO"}

    include_children: BoolProperty(
        name="Include Children",
        description="Build the whole tree. A child is its own object, born "
                    "on its parent's particles",
        default=True)

    def execute(self, context):
        p = props(context)
        hierarchy = _STASH.get("hierarchy")
        if not hierarchy or p is None or p.system in ("", "__none__"):
            self.report({"ERROR"}, "Pick a .pcf file and a system first.")
            return {"CANCELLED"}

        pcf_file = _STASH.get("path") or bpy.path.abspath(p.definition_file)
        print(f"{TAG}  building '{p.system}' from {pcf_file}")
        if p.match_blend:
            _AUTO["on"] = True
            try:
                p.time_scale = blend_time_scale(context.scene)
            finally:
                _AUTO["on"] = False
        cursor = context.scene.cursor.location.copy()
        coll = particle_collection(context, p.system)
        from ..tools import progress
        tree = hierarchy if self.include_children else dict(hierarchy, children=dict(
            hierarchy["children"], **{p.system: []}))
        _BUILD.update(i=0, n=len(subtree_names(p.system, tree)))
        with progress.job("Source Particle Import - Building %s" % p.system, phase_total=0):
            progress.phase("%s - %d system(s)" % (Path(pcf_file).name, _BUILD["n"]))
            made, log = build_system_tree(context, p.system, tree, collection=coll)

        print(f"{TAG}  " + "=" * 62)
        for line in log:
            print(f"{TAG}{line}")
        print(f"{TAG}  " + "=" * 62)

        problems = [ln.strip() for ln in log if "FAILED" in ln or "!!" in ln]
        if not made:
            msg = htlog.failure("Nothing could be built", pcf=pcf_file, system=p.system,
                                stage="building the effect", extra=["what the build said:"] +
                                ["  " + ln for ln in problems[:12]],
                                hint="the lines above name the system and the file each problem came from")
            self.report({"ERROR"}, msg)
            htlog.popup_failure(context, "Nothing could be built from %s" % Path(pcf_file).name,
                                [msg] + problems[:12])
            return {"CANCELLED"}
        if problems:
            htlog.event("WARNING", "Built '%s' from %s with %d problem(s)" % (p.system, Path(pcf_file).name,
                                                                             len(problems)),
                        ["file    : %s" % pcf_file] + problems[:20], pcf=pcf_file)

        # the DIALOG'S START TIME FINALLY DRIVES SOMETHING: it lands on
        # every system's "Time Offset" socket, so the whole effect begins
        # at that second of the scene - at any frame rate, since the graph
        # runs on Scene Time's secs. It stays editable per system in
        # the modifier's SYSTEM PROPERTIES afterwards
        if p.start_time:
            n_set = sum(1 for o in made
                        if set_system_socket(o, "Time Offset",
                                             float(p.start_time)))
            if n_set:
                print(f"{TAG}  start time {p.start_time:g}s -> Time Offset "
                      f"on {n_set} system(s)")
        if abs(p.time_scale - 1.0) > 1e-9:
            n_set = sum(1 for o in made
                        if set_system_socket(o, "Time Scale",
                                             float(p.time_scale)))
            if n_set:
                print(f"{TAG}  time scale {p.time_scale:g} -> "
                      f"{n_set} system(s)")

        dropped = sum(int(o.get("htp_dropped", 0)) for o in made)
        msg = (f"Built {len(made)} system(s) from '{p.system}' "
               f"· play from frame 1")
        cam_note = auto_camera(context, pcf_file, p.system, cursor)
        if cam_note:
            msg += " · " + cam_note
            from ..tools import htlog
            htlog.event("INFO", "Imported '%s' and created a camera" % p.system, [cam_note], pcf=pcf_file)
            _tell(context, "Particle imported, camera created",
                  ["'%s' is in the scene." % p.system, cam_note])
        if dropped:
            # say it out loud. An import that quietly drops a third of the
            # authoring looks identical to one that worked.
            self.report({"WARNING"},
                        msg + f" · {dropped} attributes NOT translated "
                              f"(console lists them)")
        else:
            self.report({"INFO"}, msg)

        for o in context.selected_objects:
            o.select_set(False)
        made[0].select_set(True)
        context.view_layer.objects.active = made[0]
        return {"FINISHED"}


class HTP_OT_SetScale(Operator):
    """Set the import scale to a preset.

1 keeps Source units - 1 Blender Unit = 1 Hammer unit, which is what every
operator value in the graphs is authored in, so it is the setting that
never needs a conversion anywhere. 0.01905 shrinks the finished effect to
metres (1 Hammer unit = 0.75 inch) for standing it next to a human-scale
character - a DISPLAY choice only, nothing internal changes.

If you are unsure, keep 1 and paint the Hammer Unit Grid from the
Developer tab: a Scout stands 81.69 units tall on it, which makes every
size readable at a glance"""
    bl_idname = "htp.set_scale"
    bl_label = "Set Scale"
    bl_options = {"REGISTER", "INTERNAL", "UNDO"}

    value: FloatProperty(default=1.0)

    def execute(self, context):
        p = props(context)
        if p is not None:
            p.scale = self.value
        return {"FINISHED"}


class HTP_OT_SetTimeScale(Operator):
    """Match the effect's clock to your scene's frame rate.

Pick the button for the FPS your scene actually runs at and the Time Scale
is set to FPS / 24 - SFM's timeline runs at 24 FPS, so this keeps one
rendered frame carrying exactly one SFM frame's worth of effect-time:

    24 FPS -> 1.0 (the authored speed)
    30 FPS -> 1.25      60 FPS -> 2.5

The field below still takes any value by hand: 0.5 is half-speed slow
motion, 0 freezes the effect entirely. Whatever you set here lands on every
system the next build creates, and stays editable per system afterwards
under the modifier's SYSTEM PROPERTIES"""
    bl_idname = "htp.set_time_scale"
    bl_label = "Set Time Scale"
    bl_options = {"REGISTER", "INTERNAL", "UNDO"}

    value: FloatProperty(default=1.0)

    @classmethod
    def description(cls, context, properties):
        if properties.value < 0:
            return ("Time Scale from this .blend's frame rate (fps / 24), read again at every build - change the "
                    "scene's frame rate later and the effect follows.\n\n"
                    "THIS FEATURE WAS ADDED IN VERSION 3.0.0 AND IS IN EXPERIMENTAL STAGE")
        return cls.__doc__

    def execute(self, context):
        p = props(context)
        if p is not None and self.value < 0:
            # 3.0.0: Match .blend
            _AUTO["on"] = True
            try:
                p.match_blend = True
                p.time_scale = blend_time_scale(context.scene)
            finally:
                _AUTO["on"] = False
            return {"FINISHED"}
        if p is not None:
            p.match_blend = False
            _AUTO["on"] = True
            try:
                p.time_scale = self.value
            finally:
                _AUTO["on"] = False
        return {"FINISHED"}


class HTP_OT_UsePlayhead(Operator):
    """Copy the playhead's position into Start Time.

Reads the current frame, converts it to seconds at your scene's frame
rate, and writes it into the Start Time field - so the effect begins
exactly where you are parked in the timeline instead of at 0.

Start Time drives every built system's "Time Offset" socket: the whole
effect holds still until that second of the scene and then plays from its
own zero. It stays editable per system afterwards under the modifier's
SYSTEM PROPERTIES"""
    bl_idname = "htp.use_playhead"
    bl_label = "Use Playhead"
    bl_options = {"REGISTER", "INTERNAL", "UNDO"}

    def execute(self, context):
        p = props(context)
        if p is not None:
            p.start_time = context.scene.frame_current * seconds_per_frame(
                context.scene)
        return {"FINISHED"}


class HTP_OT_ChooseParticleSystem(Operator):
    """Import a Source/SFM particle system from a .pcf, dialog first.

Opens the SFM-style import window: pick the .pcf, pick which system in it
(children indent under their parents), set Start Time / Scale / Time
Scale, and press Build This System.

Two conveniences worth knowing: trigger this while your mouse hovers a
timeline, dope sheet or graph editor and Start Time is pre-filled from
the frame under the pointer; and the same settings block lives in the
sidebar's Particle Import tab, so the dialog is optional - either place
builds the identical effect"""
    bl_idname = "htp.choose_particle_system"
    bl_label = "Choose Particle System"
    bl_options = {"REGISTER", "UNDO"}

    def invoke(self, context, event):
        p = props(context)
        if p is not None:
            # Start Time follows the MOUSE: hover a timeline / dope sheet /
            # graph editor when you trigger the import and the effect starts
            # exactly there. Pointer anywhere else -> 0, and you type your own
            frame = frame_under_mouse(context, event)
            if frame is None:
                p.start_time = 0.0
            else:
                p.start_time = max(0.0, frame * seconds_per_frame(context.scene))
                print(f"{TAG}  start time picked from timeline: "
                      f"frame {frame:.2f} -> {p.start_time:.4f}s")
        return context.window_manager.invoke_props_dialog(
            self, width=440, confirm_text="Build This System")

    def draw(self, context):
        draw_import_ui(self.layout, context, in_dialog=True)

    def execute(self, context):
        #the DIALOG'S CONFIRM RUNS the REAL BUILD. This used to place a bare
        #anchor empty instead - a leftover from before the builder existed -
        #and it crashed the moment control_points.spawn() changed signature
        #One button label, one behaviour: "Build This System" builds it.
        return bpy.ops.htp.build_particle_system("EXEC_DEFAULT")


class HTP_OT_BrowsePCF(Operator, ImportHelper):
    """Browse for a .pcf particle definition file.

Opens the file browser in your SFM install's particles folder, so real
effects are one click away. The moment a file is picked it is parsed and
the system dropdown fills with everything inside it - a .pcf is a whole
LIBRARY of systems, not one effect, which is why choosing the file and
choosing the system are two separate steps.

Typing or pasting a path into the field does the same parse without the
browser"""
    bl_idname = "htp.browse_pcf"
    bl_label = "Browse for .pcf"
    bl_options = {"REGISTER", "INTERNAL"}

    filename_ext = ".pcf"
    filter_glob: StringProperty(default="*.pcf", options={"HIDDEN"})
    reopen_dialog: BoolProperty(default=False, options={"SKIP_SAVE", "HIDDEN"})

    def invoke(self, context, event):
        if not self.filepath:
            start = op_prefs.particles_dir()
            if start is not None:
                self.filepath = str(start) + "\\"
                print(f"{TAG}  PCF browser starting at {start}")
        return super().invoke(context, event)

    def execute(self, context):
        err = load_pcf_into_stash(self.filepath)
        p = props(context)
        if p is not None:
            p.definition_file = self.filepath   # re-parse is guarded
            _select_first_system(p)
        if err:
            self.report({"ERROR"}, err)
        if self.reopen_dialog:
            bpy.ops.htp.choose_particle_system("INVOKE_DEFAULT")
        return {"FINISHED"}


def menu_func(self, context):
    # straight into the FILE BROWSER, like every other File > Import entry.
    # It used to open the settings dialog first - whose only useful button at
    # that point was Browse - then close it for the browser, then re-open it:
    # three windows for one decision. Now the browser comes first and the
    # settings dialog appears ONCE, already loaded with the picked .pcf
    # (The sidebar flow is unchanged - it has no dialog to juggle.)
    # The crowbar is HoovyTools' own Source Engine icon, so the two add-ons
    # read as one family in this menu
    from ..icons import icon_id
    op = self.layout.operator(HTP_OT_BrowsePCF.bl_idname,
                              text="Source Engine (.pcf)",
                              **icon_id("source_engine", "PARTICLES"))
    op.reopen_dialog = True


CLASSES = (HTP_Props, HTP_OT_SetScale, HTP_OT_SetTimeScale,
           HTP_OT_UsePlayhead, HTP_OT_BrowsePCF,
           HTP_OT_BuildParticleSystem, HTP_OT_ChooseParticleSystem)


def register():
    bpy.types.Scene.htp = PointerProperty(type=HTP_Props)
    _clear_stash()
    if _follow_playhead not in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.append(_follow_playhead)


def unregister():
    if _follow_playhead in bpy.app.handlers.frame_change_post:
        bpy.app.handlers.frame_change_post.remove(_follow_playhead)
    del bpy.types.Scene.htp
