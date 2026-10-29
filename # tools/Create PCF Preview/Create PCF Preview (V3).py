# =============================================================================
#  Create PCF Preview (V3)
#  The Text Editor version of  Source Particle Import > Tools > PCF Preview
#  (4.1 Create PCF Preview and 4.2 Process Entire Folder).
#  V3 (3.0.0): the add-on's new name and place; the script itself is V2's.
# =============================================================================
#
#  WHAT IT DOES: renders each .pcf the way SFM's particle editor shows it and
#  draws the preview card around it - titles from the file name in the
#  effect's own colour, the path in the pack folder's colour - saved beside
#  the .pcf as "<name> (preview).png" (or .jpg). An existing card is never
#  overwritten and never re-rendered by a folder run.
#
#  HOW: set the values below, press Run Script (Alt+P). It calls the add-on's
#  own buttons, so the window stays usable and Esc cancels.
#    PROCESS_ENTIRE_FOLDER = True   every .pcf under FOLDER, recursively, then
#                                   an orb icon for each folder directly in it
#    PROCESS_ENTIRE_FOLDER = False  just PCF_FILE (or every .pcf directly in
#                                   its folder with WHOLE_FOLDER = True)
#
#  OVERRIDES: anything left at None / "" is automatic. Per effect, a
#  "<name> (preview settings).json" beside the .pcf beats everything here, e.g.
#      {"title": "Hbomb 500", "subtitle": "(arcs glow)", "title_color": "#ff8a2a",
#       "moment": 1.2, "view_yaw": 30, "zoom": 1.3}
#
#  Needs the Source Particle Import add-on (0.26.0 or newer) enabled.
#
#  THIS FEATURE WAS ADDED IN VERSION 0.26.0 AND IS IN EXPERIMENTAL STAGE.
# =============================================================================

PROCESS_ENTIRE_FOLDER = True
FOLDER = r"C:\Program Files (x86)\Steam\steamapps\common\SourceFilmmaker\game\usermod\particles"
SKIP_FOLDERS = "___Developer___, __Developer__"   # names skipped at any depth
WORKERS = 3                 # worker Blenders at once
FOLDER_ICONS = True         # an orb icon for each folder directly in FOLDER
APPLY_ICONS = "BARE"        # BARE (only folders without an icon), ALL (replace, backed up), NONE
ICON_FOLDER = r"C:\Icons\SFM\Particles"
KEEP_FREE_GB = 1.5          # stop before the cards' drive gets fuller than this

PCF_FILE = r""              # for PROCESS_ENTIRE_FOLDER = False
WHOLE_FOLDER = False        # ... every .pcf directly in PCF_FILE's folder
DESCRIPTION = ""            # one effect only

CARD_FORMAT = "JPG"         # PNG or JPG
GROUND_GRID = True
MOMENT = 0.0                # seconds; 0 = each effect's brightest moment
SECOND_PATH_LINE = False
TITLE = ""                  # "" = from the file name
TAG = None                  # None = from the name, "" = no tag, "text" = custom
TITLE_COLOR = "AUTO"        # AUTO (the particle's hue), FOLDER, NEUTRAL, or "#rrggbb"
FOLDER_COLOR = "AUTO"       # AUTO (the pack's designated colour), NEUTRAL, or "#rrggbb"
VIEW_TURN = 0.0             # degrees around the effect
VIEW_TILT = -1.0            # degrees down; -1 = automatic
ZOOM = 1.0                  # above 1 = closer

# -----------------------------------------------------------------------------

import bpy


def _colour(value, key):
    v = str(value or "AUTO").strip()
    if v.startswith("#") and len(v) == 7:
        return {key + "_mode": "CUSTOM", key: tuple(int(v[i:i + 2], 16) / 255.0 for i in (1, 3, 5))}
    return {key + "_mode": v.upper()}


def main():
    choices = {"title_text": TITLE, "card_format": CARD_FORMAT.upper(), "icon_dir": ICON_FOLDER,
               "view_yaw": VIEW_TURN, "view_pitch": VIEW_TILT, "zoom": ZOOM}
    if TAG is None:
        choices["tag_mode"] = "AUTO"
    elif TAG == "":
        choices["tag_mode"] = "NONE"
    else:
        choices.update(tag_mode="CUSTOM", tag_text=TAG)
    choices.update(_colour(TITLE_COLOR, "title_color"))
    choices.update(_colour(FOLDER_COLOR, "folder_color"))
    if PROCESS_ENTIRE_FOLDER:
        bpy.ops.htp.process_pcf_folder(
            "EXEC_DEFAULT", folder=FOLDER, exclude=SKIP_FOLDERS, workers=WORKERS,
            ground_grid=GROUND_GRID, moment=MOMENT, include_sub_folder=SECOND_PATH_LINE,
            folder_icons=FOLDER_ICONS, apply_icons=APPLY_ICONS, guard_gb=KEEP_FREE_GB, **choices)
    else:
        bpy.ops.htp.create_pcf_preview(
            "EXEC_DEFAULT", pcf_path=PCF_FILE, whole_folder=WHOLE_FOLDER, description=DESCRIPTION,
            ground_grid=GROUND_GRID, moment=MOMENT, include_sub_folder=SECOND_PATH_LINE, **choices)


main()
