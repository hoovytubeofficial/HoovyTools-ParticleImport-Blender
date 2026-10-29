
import importlib
import json
import math
import sys
import time
import traceback

import addon_utils
import bpy
from mathutils import Vector

VIEW = Vector((0.583, -0.813, 0.0)).normalized()
# With the GROUND GRID the camera looks down 15 degrees - level, the ground
# plane is seen edge-on and the grid collapses into a line
VIEW_GRID = Vector((0.583 * math.cos(math.radians(15)), -0.813 * math.cos(math.radians(15)),
                    -math.sin(math.radians(15)))).normalized()
SAMPLES = (0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.4, 2.0, 2.8)
FPS = 24
GRID_STEPS = (4, 8, 16, 32, 64, 128, 256, 512, 1024)     # Hammer units
# 0.26.4: the most particles one system may hold IN A PREVIEW. The Episode 78
# lasers emit 1,000,000 a second into a cap of 1,000,000, pre-rolled 10 s: a
# million glow sprites stacked on the 300 points of a beam. Every probe render
# took longer than the last and Blender died after ~8 minutes. The stack is
# saturated long before a million, so a preview caps it; only those two of the
# 1,941 library effects ever pass 20,000 (every other system peaks at 10,000 or
# less in a preview; huge CAPS are common - 100,000,000 on the Episode 77
# jetpacks - huge EMISSION is not). 100,000 still took 17 minutes an effect
PREVIEW_MAX_PARTICLES = 20000
MAXP = "Max Particles [SFM: max_particles]"     # the system modifier's input (ras_system.MAXP)


def _modifier_input(mod, ident):
    """A geometry-nodes modifier input: (getter, setter). Blender 5.2 keeps them
    at mod.properties.inputs.<identifier>.value (op_ras._set_input's route);
    the 4.x subscript mod[identifier] is the fallback."""
    try:
        slot = getattr(mod.properties.inputs, ident)
        return (lambda: slot.value), (lambda v: setattr(slot, "value", v))
    except Exception:
        return (lambda: mod[ident]), (lambda v: mod.__setitem__(ident, v))


def _cap_population(cap):
    """Lower every system modifier's Max Particles to `cap` where it is above.
    -> [(system, the file's value), ...] for what was capped. Max Particles
    gates EMISSION, so the effect simply stops spawning at the ceiling."""
    capped = []
    for o in bpy.data.objects:
        if not o.get("htp_system"):
            continue
        for mod in o.modifiers:
            if mod.type != "NODES" or mod.node_group is None:
                continue
            for it in mod.node_group.interface.items_tree:
                if getattr(it, "item_type", "") != "SOCKET" or it.in_out != "INPUT" or it.name != MAXP:
                    continue
                get, put = _modifier_input(mod, it.identifier)
                try:
                    v = get()
                except Exception:
                    continue
                if v > cap:
                    put(type(v)(cap))
                    o.update_tag()
                    capped.append((o.get("htp_system"), v))
    return capped


def _view(job):
    """The editor's view direction, turned by the job's view_yaw (degrees
    about Z) and tilted down by view_pitch (default 15 with the ground
    grid, level without) - VIEW and VIEW_GRID when nothing is set."""
    pitch = job.get("view_pitch")
    pitch = (15.0 if job.get("grid") else 0.0) if pitch in (None, "") else float(pitch)
    yaw = math.radians(float(job.get("view_yaw") or 0.0))
    x = VIEW.x * math.cos(yaw) - VIEW.y * math.sin(yaw)
    y = VIEW.x * math.sin(yaw) + VIEW.y * math.cos(yaw)
    p = math.radians(pitch)
    return Vector((x * math.cos(p), y * math.cos(p), -math.sin(p))).normalized()


def _draws(name, h, pb, seen):
    """Does this system, or anything below it, draw? A container (no renderer,
    nothing to run) and a system without a material (an invisible driver) do
    not; their children might."""
    if name in seen or name not in h["systems"]:
        return False
    seen.add(name)
    p = pb.plan(h["systems"][name])
    if not p["container"] and p.get("material"):
        return True
    return any(_draws(c, h, pb, seen) for c in h["children"].get(name, []))


def _pick_root(addon, pcf_path):
    """0.26.2: the first ROOT THAT DRAWS - named roots first, marker roots
    ("_moreOnPatreon...", "___byHoovyTube___") only after them. The first named
    root can be all containers and drivers, and its card came out empty."""
    pcf = importlib.import_module(addon + ".tools.pcf")
    pb = importlib.import_module(addon + ".tools.pcf_build")
    h = pcf.build_hierarchy(pcf.load_pcf(pcf_path))
    roots = h["roots"]
    named = [r for r in roots if not str(r).startswith("_")]
    for group in (named, roots):
        for r in group:
            try:
                if _draws(r, h, pb, set()):
                    return r
            except Exception:
                continue
    return named[0] if named else (roots[0] if roots else None)


def _instances(dg):
    pts = []
    for inst in dg.object_instances:
        if not inst.is_instance:
            continue
        ob = inst.object
        if ob.type != "MESH":
            continue
        m = inst.matrix_world
        r = max(m.to_scale()) * 0.5
        pts.append((m.translation.copy(), r))
    return pts


def _mass(dg):
    """Visible mass right now: alpha x radius^2 over every particle, read off
    the point clouds the renderers instance from."""
    total = 0.0
    for o in bpy.data.objects:
        if not o.get("htp_system"):
            continue
        try:
            gs = o.evaluated_get(dg).evaluated_geometry()
            pc = gs.instances_pointcloud() if gs.instance_references() else gs.pointcloud
        except Exception:
            continue
        if pc is None:
            continue
        rad = pc.attributes.get("sprite_radius")
        alp = pc.attributes.get("sprite_alpha")
        if rad is None:
            continue
        n = len(pc.points)
        rs = [0.0] * n
        rad.data.foreach_get("value", rs)
        al = [1.0] * n
        if alp is not None:
            alp.data.foreach_get("value", al)
        total += sum(a * r * r for a, r in zip(al, rs))
    return total


def _light(png):
    """Total light on screen in a small render (sum of luminance, 0..1 per
    pixel) - what the eye reads as 'how much effect is there'."""
    try:
        from PIL import Image
        im = Image.open(png).convert("L")
        hist = im.histogram()
        return sum(i * n for i, n in enumerate(hist)) / 255.0
    except Exception:
        img = bpy.data.images.load(png)
        px = list(img.pixels)
        bpy.data.images.remove(img)
        return sum(px[0::4]) + sum(px[1::4]) + sum(px[2::4])


def _frame_camera(cam, pts, view=VIEW, zoom=1.0):
    """Aim along `view` so the particles fill the frame. -> (centre, radius)
    or None when there is nothing to frame."""
    if not pts:
        return None
    def pct(vals, q):
        s = sorted(vals)
        return s[min(len(s) - 1, max(0, int(round(q * (len(s) - 1)))))]
    lo = Vector([pct([p[i] - r for p, r in pts], 0.03) for i in range(3)])
    hi = Vector([pct([p[i] + r for p, r in pts], 0.97) for i in range(3)])
    centre = (lo + hi) / 2
    radius = max((hi - lo).length / 2, 4.0)
    dist = radius / math.tan(cam.data.angle / 2) * 1.08 / max(0.05, float(zoom or 1.0))
    cam.location = centre - view * dist
    cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_start = max(0.1, dist / 1000.0)
    cam.data.clip_end = dist * 20.0 + 10000.0
    return centre, radius


def _ground_grid(cam, centre, radius, res):
    """A thin grid on the effect's ground (z = 0 at its origin) - where it sits
    against terrain. Lines are thin quads (edges do not render), about a pixel
    wide where the effect is, spaced in round Hammer units (8, 16, 32 ...) so
    the squares mean something, faded out with distance from the effect."""
    import bmesh
    spacing = min(GRID_STEPS, key=lambda s: abs(math.log(s / max(radius / 3.0, 1.0))))
    extent = max(radius * 2.6, spacing * 4)
    n = int(extent / spacing) + 1
    dist = (cam.location - Vector((centre.x, centre.y, 0.0))).length
    width = 2.0 * dist * math.tan(cam.data.angle / 2) / res * 1.3
    cx = round(centre.x / spacing) * spacing
    cy = round(centre.y / spacing) * spacing
    bm = bmesh.new()
    for i in range(-n, n + 1):
        x, y = cx + i * spacing, cy + i * spacing
        for a, b, c, d in (((x - width / 2, cy - extent), (x + width / 2, cy - extent),
                            (x + width / 2, cy + extent), (x - width / 2, cy + extent)),
                           ((cx - extent, y - width / 2), (cx + extent, y - width / 2),
                            (cx + extent, y + width / 2), (cx - extent, y + width / 2))):
            bm.faces.new([bm.verts.new((p[0], p[1], 0.0)) for p in (a, b, c, d)])
    me = bpy.data.meshes.new("preview ground grid")
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new("preview ground grid", me)
    bpy.context.scene.collection.objects.link(ob)
    #emission, faded to black with distance from the effect - on black,
    #fading to black is fading out, and an opaque grid needs no sorting
    mat = bpy.data.materials.new("preview ground grid")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    off = nt.nodes.new("ShaderNodeVectorMath")
    off.operation = "SUBTRACT"
    off.inputs[1].default_value = (cx, cy, 0.0)
    nt.links.new(geo.outputs["Position"], off.inputs[0])
    ln = nt.nodes.new("ShaderNodeVectorMath")
    ln.operation = "LENGTH"
    nt.links.new(off.outputs[0], ln.inputs[0])
    fade = nt.nodes.new("ShaderNodeMapRange")
    fade.interpolation_type = "SMOOTHSTEP"
    fade.inputs[1].default_value = extent * 0.35
    fade.inputs[2].default_value = extent
    fade.inputs[3].default_value = 0.11
    fade.inputs[4].default_value = 0.0
    nt.links.new(ln.outputs["Value"], fade.inputs[0])
    em = nt.nodes.new("ShaderNodeEmission")
    em.inputs["Color"].default_value = (0.62, 0.68, 0.80, 1.0)
    nt.links.new(fade.outputs[0], em.inputs["Strength"])
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(em.outputs[0], out.inputs["Surface"])
    me.materials.append(mat)
    return spacing


def render_one(addon, job, prefs=None):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable(addon, default_set=True, persistent=False)
    # a factory-startup Blender has no saved preferences - take over the ones
    # the effect needs (the SFM install the materials are found in)
    for key, value in (prefs or {}).items():
        try:
            setattr(bpy.context.preferences.addons[addon].preferences, key, value)
        except Exception:
            pass
    api = importlib.import_module(addon + ".api")
    sc = bpy.context.scene
    sc.render.fps = FPS
    # the camera first: cards face the camera found at build time
    cam = bpy.data.objects.new("preview camera", bpy.data.cameras.new("preview camera"))
    sc.collection.objects.link(cam)
    cam.data.lens = 50
    cam.location = -VIEW * 600.0
    cam.rotation_euler = (-cam.location).to_track_quat("-Z", "Y").to_euler()
    sc.camera = cam

    system = job.get("system")
    if not system:
        system = _pick_root(addon, job["pcf"])
    if not system:
        raise RuntimeError("no system in this .pcf")
    api.build_effect(bpy.context, job["pcf"], system=system, start_time=0.0, time_scale=1.0)
    for o in bpy.data.objects:
        if o.get("htp_control_point") == 0:
            o.rotation_euler.z += math.radians(float(job.get("cp0_yaw", job.get("yaw", 90.0))))
    capped = _cap_population(int(job.get("max_particles") or PREVIEW_MAX_PARTICLES))

    sc.render.engine = "BLENDER_EEVEE"
    sc.render.film_transparent = False
    world = bpy.data.worlds.new("black")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0, 0, 0, 1)
    sc.world = world
    sc.view_settings.view_transform = "Standard"
    sc.view_settings.look = "None"
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGB"
    sc.render.resolution_percentage = 100

    # step the simulation forward once, remembering where everything is
    wanted = job.get("time")
    times = [float(wanted)] if wanted not in (None, "", -1, -1.0) else list(SAMPLES)
    last = max(1, int(round(max(times) * FPS)) + 1)
    sc.frame_start, sc.frame_end = 1, last
    targets = {max(1, int(round(t * FPS)) + 1): t for t in times}
    seen = {}
    for f in range(1, last + 1):
        sc.frame_set(f)
        if f in targets:
            seen[f] = _instances(bpy.context.evaluated_depsgraph_get())

    # the brightest sample, rendered small through one camera that sees them all
    f_best = next(iter(targets))
    if len(targets) > 1:
        _frame_camera(cam, [p for pts in seen.values() for p in pts], _view(job))
        sc.render.resolution_x = sc.render.resolution_y = 160
        probe = job["out"] + ".probe.png"
        best = None
        for f in sorted(targets):
            if not seen.get(f):
                continue
            sc.frame_set(f)
            sc.render.filepath = probe
            bpy.ops.render.render(write_still=True)
            score = _light(probe)
            if best is None or score > best[0] * 1.02:
                best = (score, f)
        if best is not None:
            f_best = best[1]
        try:
            import os
            os.remove(probe)
        except OSError:
            pass
    t_best = targets[f_best]
    sc.frame_set(f_best)          #the simulation replays from its cache
    grid = bool(job.get("grid"))
    framed = _frame_camera(cam, _instances(bpy.context.evaluated_depsgraph_get()),
                           _view(job), job.get("zoom") or 1.0)

    res = int(job.get("res", 1400))
    sc.render.resolution_x = sc.render.resolution_y = res
    result = {"ok": True, "system": system, "time": t_best, "frame": f_best,
              "framed": framed is not None, "out": job["out"]}
    if capped:
        result["capped"] = capped
    if grid and framed is not None:
        # the effect alone first: the card crops to its light, so the grid
        # (which lights the whole floor) never shrinks the effect on the card
        plain = job["out"] + ".plain.png"
        sc.render.filepath = plain
        bpy.ops.render.render(write_still=True)
        result["plain"] = plain
        result["grid_spacing"] = _ground_grid(cam, framed[0], framed[1], res)
    sc.render.filepath = job["out"]
    bpy.ops.render.render(write_still=True)
    result.setdefault("plain", job["out"])
    return result


def main():
    path = sys.argv[sys.argv.index("--") + 1]
    spec = json.load(open(path, encoding="utf-8"))
    results = []
    for job in spec["jobs"]:
        t0 = time.time()
        try:
            r = render_one(spec["addon"], job, spec.get("prefs"))
        except Exception as exc:
            traceback.print_exc()
            r = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        r["pcf"] = job["pcf"]
        r["seconds"] = round(time.time() - t0, 2)
        results.append(r)
        print("[HT_PREVIEW]", json.dumps(r), flush=True)
        json.dump(results, open(spec["result"], "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
