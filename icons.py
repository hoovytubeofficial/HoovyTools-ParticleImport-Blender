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
    "source_engine",
    "hammer_grid",
    "vtf_import",
    "vtf_sprite",
    "vmt_import",
    "vmt_sprite",
    "render_animated_sprites",
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
)

ICON_FILES = {
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

_pcoll = None


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
                _pcoll.load(key, str(path), "IMAGE")
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
