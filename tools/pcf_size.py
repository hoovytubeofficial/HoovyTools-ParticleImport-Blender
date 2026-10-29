
import math
from pathlib import Path

from . import pcf

UNIT_M = 0.01905                     # one Hammer unit in metres (0.75 inch)
DRAG_FPS = 30.0                      # Source applies drag per 1/30 s
DEFAULT_LIFETIME = 1.0               # no Lifetime Random: the estimate assumes one second, and says so


def _ops(sysdef):
    """[(functionName, element)] for every ENABLED operator of a system, in file order."""
    out = []
    for key in pcf._CP_SUBELEMENT_KEYS:
        for op in (sysdef.get(key) or []):
            try:
                fn = str(op.get("functionName") or "").strip()
                enabled = op.get("operator enabled")
            except Exception:
                continue
            if fn and (enabled is None or bool(enabled)):
                out.append((fn, op))
    return out


def _f(op, attr, default=0.0):
    try:
        v = op.get(attr)
        return default if v is None else float(v)
    except Exception:
        return default


def _v(op, attr, default=(0.0, 0.0, 0.0)):
    try:
        v = op.get(attr)
        if v is None:
            return tuple(default)
        parts = [float(c) for c in v]
        return tuple((parts + [0.0, 0.0, 0.0])[:3])
    except Exception:
        return tuple(default)


def _drag_time(lifetime, drag):
    """Seconds of FULL speed the particle travels: integral of (1 - drag)^(30 t) over its life."""
    if lifetime <= 0:
        return 0.0
    if drag <= 0:
        return lifetime
    if drag >= 1:
        return 0.0
    k = -DRAG_FPS * math.log(1.0 - drag)
    return (1.0 - math.exp(-k * lifetime)) / k


class _Box:
    """Half-extents around the control point: x and y both ways, z up and z down."""

    def __init__(self, x=0.0, y=0.0, up=0.0, down=0.0):
        self.x, self.y, self.up, self.down = x, y, up, down

    def grow(self, x=0.0, y=0.0, up=0.0, down=0.0):
        return _Box(self.x + x, self.y + y, self.up + up, self.down + down)

    def union(self, o):
        return _Box(max(self.x, o.x), max(self.y, o.y), max(self.up, o.up), max(self.down, o.down))

    def size(self):
        return (2 * self.x, 2 * self.y, self.up + self.down)

    def as_dict(self):
        w, d, h = self.size()
        return {"width": w, "depth": d, "height": h, "up": self.up, "down": self.down}


def _spawn(fn_ops):
    """The spawn region (a _Box) and the notes on where it came from."""
    box, notes = _Box(), []
    cps = []
    for fn, op in fn_ops:
        f = fn.lower()
        if f == "position within sphere random":
            d = _f(op, "distance_max")
            bx, by, bz = _v(op, "distance_bias", (1.0, 1.0, 1.0))
            if d:
                box = box.union(_Box(abs(d * bx), abs(d * by), abs(d * bz), abs(d * bz)))
                notes.append("sphere %g" % d)
        elif f == "position within box random":
            lo, hi = _v(op, "min"), _v(op, "max")
            box = box.union(_Box(max(abs(lo[0]), abs(hi[0])), max(abs(lo[1]), abs(hi[1])),
                                 max(0.0, hi[2], lo[2]), max(0.0, -lo[2], -hi[2])))
            notes.append("box %s..%s" % (tuple(round(c, 1) for c in lo), tuple(round(c, 1) for c in hi)))
        elif f == "set control point positions":
            for attr in ("First Control Point Location", "Second Control Point Location",
                         "Third Control Point Location", "Fourth Control Point Location"):
                p = _v(op, attr)
                if any(p):
                    cps.append(p)
        elif f.startswith("position along path"):
            notes.append("path between control points")
    for p in cps:
        box = box.union(_Box(abs(p[0]), abs(p[1]), max(0.0, p[2]), max(0.0, -p[2])))
    if cps:
        notes.append("%d control point offset(s)" % len(cps))
    for fn, op in fn_ops:
        if fn.lower() == "position modify offset random":
            lo, hi = _v(op, "offset min"), _v(op, "offset max")
            box = box.grow(max(abs(lo[0]), abs(hi[0])), max(abs(lo[1]), abs(hi[1])),
                           max(0.0, hi[2], lo[2]), max(0.0, -lo[2], -hi[2]))
            notes.append("offset %s..%s" % (tuple(round(c, 1) for c in lo), tuple(round(c, 1) for c in hi)))
    return box, notes


def system_numbers(sysdef):
    """Everything the estimate reads from one system, with the engine's defaults where the file is silent."""
    ops = _ops(sysdef)
    names = [fn.lower() for fn, _op in ops]
    n = {"renderer": "", "radius": (0.0, 0.0), "radius_scale": 1.0, "lifetime": (0.0, 0.0),
         "lifetime_set": False, "speed_radial": 0.0, "speed_local_min": (0.0, 0.0, 0.0),
         "speed_local_max": (0.0, 0.0, 0.0), "gravity": (0.0, 0.0, 0.0), "drag": 0.0,
         "jitter": [], "trail": 0.0, "trail_cap": None, "from_parent": False,
         "emit_rate": 0.0, "emit_count": 0.0, "max_particles": None, "operators": len(ops)}
    for fn, op in ops:
        f = fn.lower()
        if f.startswith("render") and not n["renderer"]:
            n["renderer"] = fn
        if f == "render_sprite_trail":
            #  the FINISHED trail is clamped to this many units (Trail Length Random is seconds of travel)
            n["trail_cap"] = _f(op, "max length", 2048.0)
        elif f == "radius random":
            n["radius"] = (max(n["radius"][0], _f(op, "radius_min", 8.0)), max(n["radius"][1], _f(op, "radius_max", 16.0)))
        elif f == "radius scale":
            n["radius_scale"] *= max(abs(_f(op, "radius_start_scale", 1.0)), abs(_f(op, "radius_end_scale", 1.0)))
        elif f == "lifetime random":
            n["lifetime"] = (_f(op, "lifetime_min", 1.0), _f(op, "lifetime_max", 2.0))
            n["lifetime_set"] = True
        elif f == "position within sphere random":
            bx, by, bz = _v(op, "distance_bias", (1.0, 1.0, 1.0))
            n["speed_radial"] = max(n["speed_radial"], abs(_f(op, "speed_max")) * max(abs(bx), abs(by), abs(bz)))
            lo = _v(op, "speed_in_local_coordinate_system_min")
            hi = _v(op, "speed_in_local_coordinate_system_max")
            n["speed_local_min"] = tuple(min(a, b, c) for a, b, c in zip(n["speed_local_min"], lo, hi))
            n["speed_local_max"] = tuple(max(a, b, c) for a, b, c in zip(n["speed_local_max"], lo, hi))
        elif f == "velocity random":
            n["speed_radial"] = max(n["speed_radial"], abs(_f(op, "random_speed_max")))
            lo = _v(op, "speed_in_local_coordinate_system_min")
            hi = _v(op, "speed_in_local_coordinate_system_max")
            n["speed_local_min"] = tuple(min(a, b, c) for a, b, c in zip(n["speed_local_min"], lo, hi))
            n["speed_local_max"] = tuple(max(a, b, c) for a, b, c in zip(n["speed_local_max"], lo, hi))
        elif f == "initial velocity noise":
            lo, hi = _v(op, "output minimum"), _v(op, "output maximum")
            n["speed_local_min"] = tuple(min(a, b, c) for a, b, c in zip(n["speed_local_min"], lo, hi))
            n["speed_local_max"] = tuple(max(a, b, c) for a, b, c in zip(n["speed_local_max"], lo, hi))
        elif f == "movement basic":
            g = _v(op, "gravity")
            n["gravity"] = tuple(a + b for a, b in zip(n["gravity"], g))
            n["drag"] = max(n["drag"], min(1.0, max(0.0, _f(op, "drag"))))
        elif f == "random force":
            lo, hi = _v(op, "min force"), _v(op, "max force")
            window = _f(op, "operator end fadeout", 0.0)
            n["jitter"].append((tuple(max(abs(a), abs(b)) for a, b in zip(lo, hi)),
                                window if window > 0 else float("inf")))
        elif f == "trail length random":
            n["trail"] = max(n["trail"], _f(op, "length_max", 0.5))
        elif f == "position from parent particles":
            n["from_parent"] = True
        elif f == "emit continuously":
            n["emit_rate"] = max(n["emit_rate"], _f(op, "emission_rate", 100.0))
        elif f == "emit instantaneously":
            n["emit_count"] += _f(op, "num_to_emit", 100.0)
    if n["radius"] == (0.0, 0.0):
        try:
            r = sysdef.get("radius")
        except Exception:
            r = None
        r = 5.0 if r is None else float(r)
        n["radius"] = (r, r)
    if not n["lifetime_set"]:
        n["lifetime"] = (DEFAULT_LIFETIME, DEFAULT_LIFETIME)
    try:
        mp = sysdef.get("max_particles")
        n["max_particles"] = None if mp is None else int(mp)
    except Exception:
        pass
    n["spawn_box"], n["spawn_notes"] = _spawn(ops)
    n["has_spawn_ops"] = any(x.startswith("position") for x in names)
    return n


def _particle_cloud(n, start):
    """Where the particle CENTRES can be: the spawn region grown by travel and fall."""
    life = max(n["lifetime"])
    t_eff = _drag_time(life, n["drag"])
    radial = n["speed_radial"]
    lo, hi = n["speed_local_min"], n["speed_local_max"]
    jx = jy = jz = 0.0
    for a, window in n["jitter"]:
        k = math.sqrt(min(life, window) / (3.0 * DRAG_FPS))      # random walk of 1/30 s pushes
        jx, jy, jz = jx + a[0] * k, jy + a[1] * k, jz + a[2] * k
    vx = radial + max(abs(lo[0]), abs(hi[0])) + jx
    vy = radial + max(abs(lo[1]), abs(hi[1])) + jy
    v_up = radial + max(0.0, hi[2]) + jz
    v_down = radial + max(0.0, -lo[2]) + jz
    #  acceleration: 1/2 a t^2 without drag; with drag the particle tends to a terminal speed, a*t_eff each second
    fall_t = 0.5 * life * t_eff
    g = n["gravity"]
    ax, ay = abs(g[0]), abs(g[1])
    a_up, a_down = max(0.0, g[2]), max(0.0, -g[2])
    return start.grow(vx * t_eff + ax * fall_t, vy * t_eff + ay * fall_t,
                      v_up * t_eff + a_up * fall_t, v_down * t_eff + a_down * fall_t), {
        "life": life, "travel_time": t_eff, "speed": max(vx, vy, v_up, v_down)}


def estimate(pcf_path, system=None, include_children=True):
    """The estimate for one system's tree (system=None: every root in the file).

    -> {"pcf": path, "systems": [row, ...], "effects": {root: {...box...}}, "total": {...box...}, "notes": [...]}
    Each row: name, depth, parent, renderer, radius, lifetime, speed, travel, spawn, cloud, box (with the card).
    Raises whatever the .pcf reader raises for a file it cannot read."""
    path = Path(pcf_path)
    dm = pcf.load_pcf(path)
    h = pcf.build_hierarchy(dm)
    if system is not None and system not in h["systems"]:
        raise ValueError("%r is not a system in %s - it has: %s" % (system, path.name, ", ".join(h["roots"][:8])))
    roots = [system] if system is not None else list(h["roots"])
    rows, effects = [], {}

    def walk(name, depth, parent_cloud, parent, seen):
        if name in seen:
            return _Box()
        seen = seen | {name}
        n = system_numbers(h["systems"][name])
        start = n["spawn_box"]
        if n["from_parent"] and parent_cloud is not None:
            start = parent_cloud.union(start) if not n["has_spawn_ops"] else parent_cloud.grow(
                start.x, start.y, start.up, start.down)
        cloud, motion = _particle_cloud(n, start)
        r = max(n["radius"]) * n["radius_scale"]
        trail = 0.0
        if n["renderer"].lower() == "render_sprite_trail":
            #  speed x seconds, clamped by the renderer; a trail without Trail Length Random is 0.1 s long
            trail = min(motion["speed"] * (n["trail"] or 0.1), n["trail_cap"] if n["trail_cap"] is not None else 2048.0)
        box = cloud.grow(r + trail, r + trail, r + trail, r + trail)
        rows.append({"name": name, "depth": depth, "parent": parent, "renderer": n["renderer"] or "(none)",
                     "radius": (n["radius"][0] * n["radius_scale"], r), "lifetime": n["lifetime"],
                     "lifetime_set": n["lifetime_set"], "speed": motion["speed"], "travel_time": motion["travel_time"],
                     "gravity": n["gravity"], "drag": n["drag"], "trail": trail,
                     "spawn": start.as_dict(), "spawn_notes": n["spawn_notes"], "from_parent": n["from_parent"],
                     "cloud": cloud.as_dict(), "box": box.as_dict(),
                     "max_particles": n["max_particles"], "emit_rate": n["emit_rate"], "emit_count": n["emit_count"]})
        total = box
        if include_children:
            for child in h["children"].get(name, []):
                total = total.union(walk(child, depth + 1, cloud, name, seen))
        return total

    total = _Box()
    for root in roots:
        b = walk(root, 0, None, None, frozenset())
        effects[root] = b.as_dict()
        total = total.union(b)
    notes = []
    if any(not r["lifetime_set"] for r in rows):
        notes.append("systems without Lifetime Random are counted at %g s" % DEFAULT_LIFETIME)
    return {"pcf": str(path), "system": system, "systems": rows, "effects": effects, "total": total.as_dict(),
            "notes": notes}


def fmt_size(d, metres=True):
    """'W x D x H u (a x b x c m)'"""
    w, dd, hh = d["width"], d["depth"], d["height"]
    s = "%s x %s x %s u" % (_n(w), _n(dd), _n(hh))
    if metres:
        s += "  (%s x %s x %s m)" % (_n(w * UNIT_M, 2), _n(dd * UNIT_M, 2), _n(hh * UNIT_M, 2))
    return s


def _n(x, digits=0):
    return ("%%.%df" % digits) % x if digits else "%d" % round(x)


def report_lines(result):
    """The estimate as text: the effect first, then one line per system (indented by depth)."""
    p = Path(result["pcf"])
    L = ["%s%s" % (p.name, ("  -  " + result["system"]) if result["system"] else "  -  every root system"),
         "  size  %s   (width x depth x height)" % fmt_size(result["total"]),
         "  height above the control point %s u, below %s u" % (_n(result["total"]["up"]), _n(result["total"]["down"]))]
    if len(result["effects"]) > 1:
        for root, d in result["effects"].items():
            L.append("  effect %-32s %s" % (root[:32], fmt_size(d, metres=False)))
    L.append("")
    for r in result["systems"]:
        pad = "  " * (r["depth"] + 1)
        L.append("%s%s  [%s]" % (pad, r["name"], r["renderer"]))
        L.append("%s  box %s | radius %s-%s | life %s-%s s%s | speed %s u/s | drag %s%s%s" % (
            pad, fmt_size(r["box"], metres=False), _n(r["radius"][0], 1), _n(r["radius"][1], 1),
            _n(r["lifetime"][0], 2), _n(r["lifetime"][1], 2), "" if r["lifetime_set"] else " (assumed)",
            _n(r["speed"]), _n(r["drag"], 2),
            (" | gravity %s" % (tuple(round(c) for c in r["gravity"]),)) if any(r["gravity"]) else "",
            " | on parent particles" if r["from_parent"] else ""))
        if r["spawn_notes"]:
            L.append("%s  spawn: %s" % (pad, ", ".join(r["spawn_notes"])))
    for note in result["notes"]:
        L.append("  note: " + note)
    return L
