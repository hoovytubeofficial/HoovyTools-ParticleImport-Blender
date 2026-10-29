# =============================================================================
#  icons.py  -  custom icons, loaded the way HoovyTools does it
# =============================================================================
#
#  Drop a 32x32 PNG into images/icons/<key>.png and add its key below. Use
#  icon_id("key", "FALLBACK") in any layout call:
#
#      row.operator("htp.thing", text="Thing", **icon_id("thing", "DOT"))
#
#  Missing files are not an error - the Blender fallback icon is used and a
#  line is printed, so a half-finished icon set never breaks the UI.
# =============================================================================

from pathlib import Path

import bpy.utils.previews


ICONS_DIR = Path(__file__).parent / "images" / "icons"

ICON_KEYS = (
    "particle_import",
    "tab_properties",
    #  The green HoovyTools crowbar keeps File > Import in the same family.
    "source_engine",
    "hammer_grid",
    "vtf_import",
    "vtf_sprite",
    "vmt_import",
    "vmt_sprite",
    "render_animated_sprites",
    "render_rope",
    "render_trail",
    "house_camera",
    "proxy_view",
    "copy_support",
    "node_to_code",
    "developer",
    #  The PROPERTIES tab's section icons - see ICON_FILES below for where
    #  their pictures actually come from.
    "sys_properties",
    "sys_properties_renderer",
    "sys_properties_operator",
    "sys_properties_initializer",
    "sys_properties_emitter",
    "sys_properties_children",
    "sys_properties_forcegenerator",
    "sys_properties_constraint",
    "sys_properties_non_sfm",
    #  3.0.0: the Tools ribbons that had none, the Dev tab, the status symbols
    "pcf_preview",
    "process_folder",
    "particle_size",
    "developer_tab",
    "sec_wiring",
    "print_help",
    "print_behavior",
    "log_folder",
    "logs",
    "status_ok",
    "status_warn",
    "status_bad",
    "dev_config",
    "developer_mode",
    #  3.0.0: BUILD THIS SYSTEM
    "build_system",
)

ICON_FILES = {
    "particle_import": ("particle_import_red.png", "particle_import.png"),
    "tab_properties": ("properties_red.png", "sys_properties.png"),
    "developer": ("developer_red.png", "developer.png"),
    "sys_properties": (
        "properties/properties_system_properties.png", "sys_properties.png"),
    "sys_properties_renderer": (
        "properties/properties_renderer.png", "sys_properties_renderer.png"),
    "sys_properties_operator": (
        "properties/properties_operator.png", "sys_properties_operator.png"),
    "sys_properties_initializer": (
        "properties/properties_initializer.png",
        "sys_properties_initializer.png"),
    "sys_properties_emitter": (
        "properties/properties_emitter.png", "sys_properties_emitter.png"),
    "sys_properties_children": (
        "properties/properties_children.png", "sys_properties_children.png"),
    "sys_properties_forcegenerator": (
        "properties/properties_force_generator.png",
        "sys_properties_forcegenerator.png"),
    "sys_properties_constraint": (
        "properties/properties_constraint.png",
        "sys_properties_constraint.png"),
    #  The Control Points header wears the control-points icon; the key name
    #  predates the hand-drawn set and is not worth breaking callers over.
    "sys_properties_non_sfm": (
        "properties/properties_control_points.png",
        "sys_properties_non_sfm.png"),
}

# Share artwork where the meaning is the same. Prefer the multicolor set
# with repaired alpha; retain the red set and original art as fallbacks.
_ICON_ART_FILES = {
    "particle_import": "particle_import",
    "tab_properties": "tab_properties",
    "developer": "developer",
    "source_engine": "source_engine",
    "render_animated_sprites": "render_animated_sprites",
    "render_rope": "render_rope",
    "render_trail": "render_trail",
    "node_to_code": "node_to_code",
    "vtf_import": "vtf_import",
    "vtf_sprite": "vtf_sprite",
    "vmt_import": "vmt_import",
    "vmt_sprite": "vmt_sprite",
    "hammer_grid": "hammer_grid",
    "house_camera": "house_camera",
    "proxy_view": "proxy_view",
    "copy_support": "copy_support",
    "sys_properties": "tab_properties",
    "sys_properties_renderer": "render_animated_sprites",
    "sys_properties_operator": "node_to_code",
    "sys_properties_initializer": "sys_properties_initializer",
    "sys_properties_emitter": "particle_import",
    "sys_properties_children": "node_to_code",
    "sys_properties_forcegenerator": "sys_properties_forcegenerator",
    "sys_properties_constraint": "sys_properties_constraint",
    "sys_properties_non_sfm": "sys_properties_non_sfm",
}
for _key, _art in _ICON_ART_FILES.items():
    ICON_FILES[_key] = (f"{_art}_color_v3.png", f"{_art}_red_v2.png") + ICON_FILES.get(
        _key, (f"{_key}.png",))

_pcoll = None

# prop_enum reads custom preview IDs from its EnumProperty items. Keep each
# list alive for Blender's string references, including across icon reloads.
# Saved tab numbers stay 0/1/3 so existing scenes keep their selected tab; 3.0.0 adds Tools as 4 (the old
# Developer tab's tools) - a scene saved on Developer (1) now opens the new Dev tab.
_tab_item_cache = {}


def tab_items(_self, _context):
    specs = (
        ("IMPORT", "Particle Import",
         "Import an SFM/Source particle system from a .pcf",
         "particle_import", "PARTICLES", 0),
        ("DEV", "Developer",
         "Wiring, Behavior Report and Credits - is everything found, and "
         "PRINT HELP: the one .txt to send when something goes wrong",
         "developer_tab", "CONSOLE", 1),
        ("PROPS", "System Properties",
         "Every variable of the selected system, organised by SFM "
         "section - click a built mesh and edit it here instead of "
         "digging through the modifier",
         "tab_properties", "PROPERTIES", 3),
        ("TOOLS", "Tools",
         "Every tool, numbered: build a renderer by hand, look at textures, "
         "set the scale, preview cards, the size of an effect, share it, "
         "proxy view. A tool's name runs it; its arrow unfolds its variables",
         "developer", "TOOL_SETTINGS", 4),
    )
    values = tuple(_pcoll[key].icon_id if _pcoll is not None and key in _pcoll
                   else fallback
                   for _, _, _, key, fallback, _ in specs)
    if values not in _tab_item_cache:
        _tab_item_cache[values] = [
            (identifier, label, description, icon, number)
            for (identifier, label, description, _, _, number), icon
            in zip(specs, values)
        ]
    return _tab_item_cache[values]


def load():
    global _pcoll
    if _pcoll is not None:
        return
    _pcoll = bpy.utils.previews.new()
    if not ICONS_DIR.is_dir():
        print(f"[HT_PARTICLE]  images/icons not found at {ICONS_DIR}")
        return
    for key in ICON_KEYS:
        candidates = ICON_FILES.get(key, (f"{key}.png",))
        path = next((ICONS_DIR / c for c in candidates
                     if (ICONS_DIR / c).exists()), None)
        if path is not None:
            try:
                preview = _pcoll.load(key, str(path), "IMAGE")
                tuple(preview.icon_size)
            except Exception as exc:
                print(f"[HT_PARTICLE]  icon {key}: {exc}")
        else:
            print(f"[HT_PARTICLE]  icon missing: {key} "
                  f"(looked for {', '.join(candidates)})")


def unload():
    global _pcoll
    if _pcoll is not None:
        bpy.utils.previews.remove(_pcoll)
        _pcoll = None


def icon_id(key, fallback="NONE"):
    """Returns a kwargs dict, so it drops straight into a layout call."""
    if _pcoll is not None and key in _pcoll:
        return {"icon_value": _pcoll[key].icon_id}
    return {"icon": fallback}
