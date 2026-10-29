
import bpy
from bpy.types import Panel

from ..icons import icon_id
from . import op_particle_import as pi
from . import op_prefs


# =============================================================================
#  Section help - the Guide, cut up and delivered where it applies
# =============================================================================
#  One operator, one topic string per section. The docstring cannot be the
#  documentation here because the text depends on WHICH (?) you are hovering,
#  so description() composes the tooltip per topic - and clicking pops the
#  same lines up for reading at leisure. Texts are short on purpose: a
#  section's help says what the section IS; each button's own tooltip still
#  carries the full story of that button.

_HELP = {
    "IMPORT": ("Particle Import", (
        "SFM particle effects, rebuilt as Blender",
        "geometry nodes you can actually edit.",
        "",
        "1. Browse to a .pcf and pick a system",
        "2. Set start time, duration, lifetime",
        "3. Build. Everything lands in its own",
        "   collection under __HoovyTools__",
        "",
        "A .pcf describes the system; .vtf sheets",
        "hold the artwork. Both are read directly -",
        "no VTFEdit, no external converters.")),
    "DEV": ("Developer Tools", (
        "The pipeline, in order:",
        "",
        "1. Hammer Unit Grid   fix the scale first",
        "2. Import VTF         see the texture",
        "3. VTF + Sprite       prove the sheet cuts",
        "4. Create a renderer  build the system",
        "5. Node to Code       hand it to someone",
        "",
        "Hover any button - its tooltip is the",
        "full documentation.")),
    "PROPS": ("System Properties", (
        "The modifier, re-hung in the sidebar.",
        "Click a built system's mesh and every",
        "variable appears here, organised by",
        "SFM's own sections.",
        "",
        "Only ENABLED operators are listed -",
        "imports switch off everything the file",
        "does not author. The eye reveals the",
        "whole catalogue, [+] enables more.")),
    "CREATE": ("Create Renderer System", (
        "Build a system by hand, one button per",
        "SFM renderer:",
        "",
        "Animated Sprites   camera-facing cards -",
        "                   the standard particle",
        "Rope               one continuous ribbon",
        "                   through every particle",
        "Sprite Trail       cards stretched along",
        "                   their velocity - sparks",
        "",
        "Feed them a .vmt for the real material,",
        "or a bare .vtf for an honest neutral one.")),
    "SHARE": ("Share What You Made", (
        "Node to Code turns what you built back",
        "into a runnable Python script, so it",
        "travels as one file. Four flavours:",
        "",
        "Geometry Nodes   the whole effect -",
        "  select its object first",
        "Shader Nodes     one material only -",
        "  select an object wearing it",
        "",
        "'with textures' embeds the sprite",
        "sheets in the script (bigger, runs",
        "anywhere); 'no textures' stays small",
        "and references images by name.")),
    "IMPORTS": ("Imports", (
        "Texture on the LEFT, material on the",
        "RIGHT - the same job with and without",
        "the .vmt step.",
        "",
        "VTF        decode a texture and look at it",
        "VMT        the material: $additive and",
        "           $overbrightfactor decide how a",
        "           sprite burns, and neither is",
        "           guessable from the pixels",
        "+ Sprite   also cut the sheet and prove",
        "           its sequences play")),
    "SCALE": ("Set Scale", (
        "Internal particle space is HAMMER UNITS:",
        "1 Blender unit = 1 SFM unit, Scale 1.0.",
        "",
        "Paint the Hammer grid and build against",
        "the Scout at 81.69 units - no guessing.",
        "Metres (0.01905 per unit) are a DISPLAY",
        "choice, made once, by whoever is looking.",
        "",
        "Create Camera drops in the camera the",
        "sprites turn toward.")),
    "PERFORMANCE": ("Performance", (
        "Proxy View swaps every built system's",
        "cards for tenth-size flat-colour quads -",
        "each system wearing its own colour - and",
        "ropes keep their ribbon but drop the",
        "sheet shader. Motion and timing stay",
        "readable at a fraction of the draw cost.")),
    "SUPPORT": ("Support", (
        "Having a problem? ONE CLICK copies a",
        "paste-ready report: add-on + Blender",
        "versions, what was imported, how many",
        "systems built, and every console line",
        "HoovyTools printed this session - the",
        "SKIPPED / FALLBACK / missing-file lines",
        "that explain most problems.",
        "",
        "Paste it (Ctrl+V) in the Discord and",
        "troubleshooting skips ten questions.")),
    "SYSTEM PROPERTIES": ("System Properties", (
        "The whole system's dials: Scale, Seed,",
        "Time Scale, and this system's own",
        "Proxy View switch.")),
    "CONTROL POINTS": ("Control Points", (
        "SFM drives effects with numbered empties.",
        "Operators refer to them as CP0..CPn -",
        "move the empty and whatever was told to",
        "follow it comes along. One shared set",
        "per imported effect, parented to the host.")),
    "RENDERER": ("Renderer", (
        "How a particle is DRAWN - card, rope or",
        "streak - and what it turns toward.")),
    "OPERATOR": ("Operator", (
        "Changes every frame of a particle's life:",
        "movement, fades, spins, decay.")),
    "INITIALIZER": ("Initializer", (
        "Decided ONCE, at birth: lifetime, radius,",
        "colour, roll, where it starts.")),
    "EMITTER": ("Emitter", (
        "WHEN particles are born, and how many.",)),
    "CHILDREN": ("Children", (
        "Effects spawning effects: a child system",
        "rides this one's particles.")),
    "FORCE GENERATOR": ("Force Generator", (
        "Pushes particles around every frame:",
        "gravity, wind, random shoves.")),
    "CONSTRAINT": ("Constraint", (
        "Stops particles going places - the leash",
        "that clamps position, every frame, inside",
        "the simulation.")),
}


class HTP_OT_SectionHelp(bpy.types.Operator):
    #  NO static docstring on purpose - description() below is the tooltip,
    #  composed per topic, so hovering a (?) already explains its section.
    bl_idname = "htp.section_help"
    bl_label = "What is this section?"
    bl_options = {"INTERNAL"}

    topic: bpy.props.StringProperty(options={"HIDDEN"})

    @classmethod
    def description(cls, context, properties):
        title, lines = _HELP.get(properties.topic, ("", ()))
        body = "\n".join(ln for ln in lines)
        return f"{title}.\n\n{body}" if title else "What is this section?"

    def execute(self, context):
        title, lines = _HELP.get(self.topic, (self.topic, ()))
        #  🔴 popup_menu with NO WINDOW is a hard CRASH (EXCEPTION_ACCESS_
        #  VIOLATION), not an error - background/headless runs must skip it.
        if bpy.app.background or context.window is None:
            print(f"[HT_PARTICLE]  {title}: " + " ".join(lines))
            return {"FINISHED"}
        def draw(menu, _context):
            col = menu.layout.column()
            col.scale_y = 0.9
            for ln in lines:
                col.label(text=ln)
        context.window_manager.popup_menu(draw, title=title, icon="HELP")
        return {"FINISHED"}


class HTP_PT_Main(Panel):
    bl_label = "HoovyTools Particle Import"
    bl_idname = "HTP_PT_main"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Particle Import"

    def draw(self, context):
        layout = self.layout
        p = pi.props(context)
        if p is None:
            layout.label(text="Add-on properties not registered", icon="ERROR")
            return
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.prop_enum(p, "active_tab", "IMPORT", text="Import")
        row.prop_enum(p, "active_tab", "PROPS", text="Properties")
        dev = row.row(align=True)
        dev.ui_units_x = 1.8
        dev.prop_enum(p, "active_tab", "DEV", text="")
        #  The (?) explains whichever tab is open - the Guide tab's job,
        #  delivered in place.
        row.operator("htp.section_help", text="",
                     icon="QUESTION").topic = p.active_tab or "IMPORT"
        layout.separator()
        #  .get with a fallback: a file saved on the removed Guide tab reads
        #  back an empty enum value, and a KeyError at draw time would blank
        #  the whole panel.
        {"IMPORT": self._import,
         "DEV": self._developer,
         "PROPS": self._properties}.get(
            p.active_tab, self._import)(layout, context, p)

    #  A section header with its own (?) - the label takes the flexible
    #  width, so the help lands at the row's right edge. emboss=False keeps
    #  it a quiet glyph instead of another button-shaped button.
    @staticmethod
    def _head(box, text, topic, **icon):
        row = box.row()
        row.label(text=text, **icon)
        row.operator("htp.section_help", text="", icon="QUESTION",
                     emboss=False).topic = topic

    # ── Import ───────────────────────────────────────────────────────────
    def _import(self, layout, context, p):
        # Playhead now lives ON the Start Time field, inside draw_import_ui.
        #  ONE Build button, and it is drawn inside draw_import_ui. A second
        #  full-width "Build This System" used to sit here, wired to the old
        #  place-an-anchor operator - a duplicate control that crashed while
        #  the real one worked.
        pi.draw_import_ui(layout, context, compact=True)

    def _developer(self, layout, context, p):
        box = layout.box()
        self._head(box, "CREATE RENDERER SYSTEM", "CREATE",
                   **icon_id("render_animated_sprites", "PARTICLES"))
        col = box.column(align=True)
        col.scale_y = 1.4
        col.operator("htp.create_ras", text="Render Animated Sprites",
                     **icon_id("render_animated_sprites", "PARTICLES"))
        col.operator("htp.create_rope", text="Render Rope",
                     icon="OUTLINER_OB_CURVE")
        col.operator("htp.create_trail", text="Render Sprite Trail",
                     icon="TRACKING")

        box = layout.box()
        self._head(box, "SHARE WHAT YOU MADE", "SHARE",
                   **icon_id("node_to_code", "NODETREE"))
        #  FOUR flavours, each doing exactly one thing - geometry vs shader,
        #  textures embedded vs referenced. No options to misread.
        col = box.column(align=True)
        col.scale_y = 1.2
        col.label(text="Geometry Nodes (select the effect's object):")
        col.operator("htp.ntc_geo_tex", text="Geo Nodes (with textures)",
                     **icon_id("node_to_code", "TEXT"))
        col.operator("htp.ntc_geo_notex", text="Geo Nodes (no textures)",
                     icon="NODETREE")
        col.separator()
        col.label(text="Shader Nodes (select an object wearing it):")
        col.operator("htp.ntc_mat_tex", text="Shader Nodes (with textures)",
                     icon="MATERIAL")
        col.operator("htp.ntc_mat_notex", text="Shader Nodes (no textures)",
                     icon="NODE_MATERIAL")

        #  TEXTURE ON THE LEFT, MATERIAL ON THE RIGHT. The .vmt parser has
        #  been doing real work inside .pcf imports for a while with no way to
        #  watch it - these two columns are the same job with and without the
        #  material step, which makes the difference something you can see
        #  rather than something you have to be told.
        box = layout.box()
        self._head(box, "IMPORTS", "IMPORTS", **icon_id("vtf_import", "IMPORT"))
        split = box.split(factor=0.5, align=True)
        left = split.column(align=True)
        left.scale_y = 1.2
        left.operator("htp.import_vtf", text="VTF",
                      **icon_id("vtf_import", "IMPORT"))
        left.operator("htp.import_vtf_sprite", text="VTF + Sprite",
                      **icon_id("vtf_sprite", "SEQUENCE"))
        right = split.column(align=True)
        right.scale_y = 1.2
        right.operator("htp.import_vmt", text="VMT",
                       **icon_id("vmt_import", "MATERIAL"))
        right.operator("htp.import_vmt_sprite", text="VMT + Sprite",
                       **icon_id("vmt_sprite", "SHADING_TEXTURE"))

        box = layout.box()
        self._head(box, "SET SCALE", "SCALE",
                   **icon_id("hammer_grid", "FIXED_SIZE"))
        col = box.column(align=True)
        col.scale_y = 1.2
        col.operator("htp.hammer_grid", text="Hammer Unit Grid",
                     **icon_id("hammer_grid", "GRID"))
        #  No "Remove Grid" button - deleting the grid object by hand is
        #  faster than finding a button for it, and the panel gets a row back.
        col.separator()
        col.operator("htp.house_camera", text="Create Camera",
                     icon="OUTLINER_OB_CAMERA")

        box = layout.box()
        self._head(box, "PERFORMANCE", "PERFORMANCE", icon="MOD_DECIM")
        col = box.column(align=True)
        col.scale_y = 1.2
        col.operator("htp.proxy_view", text="Proxy View (Low GPU)",
                     icon="MESH_PLANE")

        #  SUPPORT lives at the BOTTOM on purpose: it is the last resort, and
        #  the last thing the eye passes on the way out of the panel.
        box = layout.box()
        self._head(box, "SUPPORT", "SUPPORT", icon="HELP")
        col = box.column(align=True)
        col.scale_y = 1.2
        col.operator("htp.copy_support", text="Copy Console Output",
                     icon="COPYDOWN")

        usermod = op_prefs.find_usermod()
        row = layout.row()
        if usermod is None:
            row.label(text="SFM install not found", icon="ERROR")
        else:
            row.label(text="SFM found", icon="CHECKMARK")
        #  The gear opens this add-on's preferences - where the preferred
        #  paths live, including the fix for "not found" above.
        row.operator("htp.open_prefs", text="", icon="PREFERENCES",
                     emboss=False)

    # ── Properties ───────────────────────────────────────────────────────
    #
    #  THE MODIFIER, RE-HUNG IN THE SIDEBAR. Click a built system's mesh and
    #  every variable appears here, organised by SFM section exactly like the
    #  screenshot that asked for it: System Properties at the top, then
    #  Renderer / Operator / Initializer / Emitter / Children / Force
    #  Generator / Constraint, each with its palette icon (the same _HUES
    #  the node groups are painted with). Only ENABLED operators are listed
    #  - imports switch off everything the file does not author, so what you
    #  see is what the effect actually runs; "Show Disabled" reveals the
    #  whole catalogue. Empty sections stay visible but greyed, so the
    #  anatomy always reads the same.
    #
    #  DRAW-TIME RULE STILL APPLIES: this reads and draws, never mutates.

    _SECTIONS = (("RENDERER", "sys_properties_renderer"),
                 ("OPERATOR", "sys_properties_operator"),
                 ("INITIALIZER", "sys_properties_initializer"),
                 ("EMITTER", "sys_properties_emitter"),
                 ("CHILDREN", "sys_properties_children"),
                 ("FORCE GENERATOR", "sys_properties_forcegenerator"),
                 ("CONSTRAINT", "sys_properties_constraint"))

    @staticmethod
    def _system_modifier(obj):
        """The geometry-nodes modifier that IS a built particle system."""
        for m in getattr(obj, "modifiers", []) or []:
            ng = getattr(m, "node_group", None)
            if ng is None:
                continue
            for it in ng.interface.items_tree:
                if getattr(it, "item_type", "") == "PANEL" \
                        and it.name == "SYSTEM PROPERTIES":
                    return m
        return None

    @staticmethod
    def _input_of(mod, identifier):
        try:
            return getattr(mod.properties.inputs, identifier)
        except Exception:
            return None

    @classmethod
    def _draw_socket(cls, col, mod, item):
        inp = cls._input_of(mod, item.identifier)
        # the bracketed SFM tag is for the importer; humans get the short half
        text = item.name.split(" [SFM:")[0]
        if inp is None:
            col.label(text=text, icon="ERROR")
        else:
            col.prop(inp, "value", text=text)

    def _properties(self, layout, context, p):
        obj = context.active_object
        mod = self._system_modifier(obj) if obj is not None else None
        if mod is None:
            box = layout.box()
            box.label(text="Select a built particle system",
                      **icon_id("sys_properties", "PROPERTIES"))
            col = box.column()
            col.scale_y = 0.8
            col.label(text="Click the mesh of an imported or")
            col.label(text="hand-built system and its variables")
            col.label(text="appear here, section by section.")
            return
        ng = mod.node_group

        # ── walk the interface once: section -> sockets + sub-panels ─────
        top_sockets = {}          # top panel name -> [socket items]
        sub_panels = {}           # top panel name -> [(panel item, [sockets])]
        panel_home = {}           # panel item pointer -> its socket list
        for it in ng.interface.items_tree:
            kind = getattr(it, "item_type", "")
            parent = getattr(it, "parent", None)
            p_name = getattr(parent, "name", "") if parent else ""
            if kind == "PANEL":
                if p_name:            # an operator panel inside a section
                    entry = (it, [])
                    sub_panels.setdefault(p_name, []).append(entry)
                    panel_home[it.name + "//" + p_name] = entry[1]
                else:
                    top_sockets.setdefault(it.name, [])
            elif kind == "SOCKET" and it.in_out == "INPUT" \
                    and getattr(it, "socket_type", "") != "NodeSocketGeometry":
                if not parent or not p_name:
                    continue
                gp = getattr(parent, "parent", None)
                gp_name = getattr(gp, "name", "") if gp else ""
                if gp_name:           # socket inside an operator sub-panel
                    home = panel_home.get(p_name + "//" + gp_name)
                    if home is not None:
                        home.append(it)
                else:                 # socket directly in a section panel
                    top_sockets.setdefault(p_name, []).append(it)

        row = layout.row(align=True)
        row.label(text=obj.name, **icon_id("sys_properties", "PROPERTIES"))
        row.operator("htp.props_minimize_all", text="", icon="AREA_JOIN")
        row.prop(p, "props_show_disabled", text="", icon="HIDE_OFF",
                 toggle=True)

        #  Every panel id carries the fold GENERATION: Minimize All bumps it,
        #  the ids change, and every panel starts over closed. Blender offers
        #  no other way to close a layout.panel from code.
        gen = f"htp_pp{p.props_fold_gen}_"
        minimized = p.props_fold_gen > 0

        # ── System Properties + Control Points up top ────────────────────
        hdr, body = layout.panel(gen + "sys", default_closed=minimized)
        hdr.label(text="System Properties",
                  **icon_id("sys_properties", "PROPERTIES"))
        hdr.operator("htp.section_help", text="", icon="QUESTION",
                     emboss=False).topic = "SYSTEM PROPERTIES"
        if body is not None:
            col = body.box().column()
            for it in top_sockets.get("SYSTEM PROPERTIES", []):
                self._draw_socket(col, mod, it)
        hdr, body = layout.panel(gen + "cp", default_closed=True)
        hdr.label(text="Control Points",
                  **icon_id("sys_properties_non_sfm", "EMPTY_AXIS"))
        hdr.operator("htp.section_help", text="", icon="QUESTION",
                     emboss=False).topic = "CONTROL POINTS"
        if body is not None:
            col = body.box().column()
            for it in top_sockets.get("CONTROL POINTS", []):
                self._draw_socket(col, mod, it)

        # ── the SFM sections, in the screenshot's order ──────────────────
        #  VISUAL GRAMMAR: a SECTION is a flat header row - icon, TITLE, its
        #  [+] - while every OPERATOR inside it is a boxed CARD. Two shapes,
        #  two meanings, readable without measuring any indentation.
        for section, icon_key in self._SECTIONS:
            entries = sub_panels.get(section, [])
            shown = []
            for panel_item, sockets in entries:
                #  the panel's ENABLE toggle is the socket named like it
                toggle = next((s for s in sockets
                               if s.name == panel_item.name), None)
                on = True
                if toggle is not None:
                    inp = self._input_of(mod, toggle.identifier)
                    on = bool(getattr(inp, "value", True))
                if on or p.props_show_disabled:
                    shown.append((panel_item, sockets, toggle, on))

            hdr, body = layout.panel(gen + section.replace(" ", "_"),
                                     default_closed=minimized or not shown)
            hrow = hdr.row(align=True)
            lab = hrow.row()
            lab.enabled = bool(shown)
            lab.label(text=section.title(), **icon_id(icon_key, "NODETREE"))
            hrow.operator("htp.section_help", text="", icon="QUESTION",
                          emboss=False).topic = section
            #  the ADD button stays live even when the section is empty -
            #  an empty section is exactly where you want to add something
            add = hrow.operator("htp.props_add_operator", text="",
                                icon="ADD")
            add.section = section
            if body is None:
                continue
            if not shown:
                sub = body.column()
                sub.enabled = False
                sub.label(text="nothing active", icon="BLANK1")
                continue
            for panel_item, sockets, toggle, on in shown:
                card = body.box()
                sh, sb = card.panel(
                    gen + section + "_" + panel_item.name,
                    default_closed=True)
                srow = sh.row()
                if toggle is not None:
                    inp = self._input_of(mod, toggle.identifier)
                    if inp is not None:
                        srow.prop(inp, "value", text="")
                srow.label(text=panel_item.name)
                if sb is None:
                    continue
                col = sb.column()
                col.enabled = on
                for s in sockets:
                    if toggle is not None and s == toggle:
                        continue
                    self._draw_socket(col, mod, s)

    #  The Guide tab's draw method lived here. Its prose now ships through
    #  _HELP at the top of this file, one section at a time.


class HTP_OT_PropsMinimizeAll(bpy.types.Operator):
    """Fold every section and operator card in this tab at once.

A big system opens a lot of panels, and Blender remembers each one's
open/closed state separately with no "close them all" of its own - this
button is that. One click and every section header and every operator
card starts over closed, so you can breathe and reopen just the part you
are working on.

(Blender offers no API to close a panel, so this quietly regenerates the
panel ids instead - which is also why everything springs closed rather
than animating shut.)"""
    bl_idname = "htp.props_minimize_all"
    bl_label = "Minimize All"
    bl_options = {"REGISTER", "INTERNAL"}

    def execute(self, context):
        p = pi.props(context)
        if p is not None:
            p.props_fold_gen += 1
        for area in context.screen.areas:
            area.tag_redraw()
        return {"FINISHED"}


#  The search popup's enum items MUST stay referenced from Python or Blender
#  garbage-collects the strings mid-draw. Module-level on purpose.
_ADD_ITEMS = [("__none__", "(nothing to add)", "")]


class HTP_OT_PropsAddOperator(bpy.types.Operator):
    """Add (enable) an operator from this section's catalogue.

Every SFM operator the build knows already has a panel on the modifier -
an import just switches OFF the ones the .pcf never authored, so what you
see running is exactly what the file wrote. Adding is therefore enabling:
this opens a search list of everything in this section that is currently
off; pick one and its toggle turns on with its authored defaults, ready
to tune.

Nothing is created or wired at this moment - the graph was always there -
so enabling is instant, and switching the toggle back off is the whole
undo. "Show Disabled" (the eye, top right) is the browsing version of the
same idea: it reveals every off operator in place instead of adding one"""
    bl_idname = "htp.props_add_operator"
    bl_label = "Add Operator"
    bl_options = {"REGISTER", "UNDO"}
    bl_property = "choice"

    section: bpy.props.StringProperty(options={"HIDDEN"})

    def _items(self, context):
        global _ADD_ITEMS
        items = []
        obj = getattr(context, "active_object", None)
        mod = HTP_PT_Main._system_modifier(obj) if obj else None
        if mod is not None:
            ng = mod.node_group
            toggles = {}
            for it in ng.interface.items_tree:
                if getattr(it, "item_type", "") != "SOCKET" \
                        or it.in_out != "INPUT":
                    continue
                parent = getattr(it, "parent", None)
                gp = getattr(parent, "parent", None) if parent else None
                if parent is not None and it.name == getattr(parent, "name", "") \
                        and getattr(gp, "name", "") == self.section:
                    toggles[it.name] = it.identifier
            for name, ident in sorted(toggles.items()):
                try:
                    on = getattr(mod.properties.inputs, ident).value
                except Exception:
                    continue
                if not on:
                    items.append((name, name, "enable this operator"))
        _ADD_ITEMS = items or [("__none__",
                                "(everything here is already enabled)", "")]
        return _ADD_ITEMS

    choice: bpy.props.EnumProperty(items=_items)

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {"FINISHED"}

    def execute(self, context):
        if self.choice == "__none__":
            return {"CANCELLED"}
        obj = context.active_object
        if obj is None or not pi.set_system_socket(obj, self.choice, True):
            self.report({"ERROR"}, f"could not enable {self.choice!r}")
            return {"CANCELLED"}
        self.report({"INFO"}, f"{self.choice} enabled")
        for area in context.screen.areas:
            area.tag_redraw()
        return {"FINISHED"}


class HTP_OT_ProxyView(bpy.types.Operator):
    """Swap every built system's cards for cheap flat stand-ins - and back.

The sheet material (texture sample, emission, alpha blending) is most of
what a few thousand overlapping particles cost the viewport. Proxy View
replaces each card with a TENTH-size quad in a flat untextured colour:
you still see where every particle is and what the motion does, at a
fraction of the draw cost - a low-GPU way to work on timing and movement,
then toggle back for the real look before judging colour or glow.

Every system wears its OWN colour, hashed from its renderer - so a scene
of proxied effects reads like Solid shading's Random mode and you can
tell whose particles are whose. Ropes and trails join in too: a trail
thins to a quarter width but keeps its full stretch, and a rope keeps its
ribbon but drops the sheet shader for the flat colour.

One click flips ALL built systems at once (it reads the first system's
state and inverts it everywhere). Each system also carries its own
"Proxy View" switch under SYSTEM PROPERTIES for mixing - one heavy effect
proxied while the one you are tuning stays real"""
    bl_idname = "htp.proxy_view"
    bl_label = "Proxy View (Low GPU)"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        hosts = [o for o in bpy.data.objects
                 if HTP_PT_Main._system_modifier(o) is not None]
        if not hosts:
            self.report({"ERROR"}, "No built particle systems in this file")
            return {"CANCELLED"}
        #  The first system's state decides the direction, so mixed states
        #  converge instead of flapping.
        mod = HTP_PT_Main._system_modifier(hosts[0])
        current = False
        for it in mod.node_group.interface.items_tree:
            if getattr(it, "item_type", "") == "SOCKET" \
                    and it.name == "Proxy View":
                inp = HTP_PT_Main._input_of(mod, it.identifier)
                current = bool(getattr(inp, "value", False))
                break
        target = not current
        n = 0
        for o in hosts:
            if pi.set_system_socket(o, "Proxy View", target):
                n += 1
                o.update_tag()
        context.view_layer.update()
        for area in context.screen.areas:
            area.tag_redraw()
        if n == 0:
            self.report({"ERROR"}, "No system has a Proxy View switch - "
                        "rebuild them with this add-on version first")
            return {"CANCELLED"}
        self.report({"INFO"}, f"Proxy view {'ON' if target else 'OFF'} "
                              f"across {n} system(s)")
        return {"FINISHED"}


CLASSES = (HTP_OT_SectionHelp, HTP_PT_Main, HTP_OT_PropsMinimizeAll,
           HTP_OT_PropsAddOperator, HTP_OT_ProxyView)
