"""
tools/progress.py - a live progress bar while Build This System runs  (3.0.0)
=============================================================================

The same overlay SFM Session Importer draws (its core/Progress.py, carried here - add-ons do not import each other):
a flat bar at the bottom of every 3D viewport, the line in the status bar and the busy-cursor percentage, repainted
from inside the blocking build with wm.redraw_timer at most every PUMP_INTERVAL seconds. Headless it does nothing.

    with progress.job("Source Particle Import - Building fire", phase_total=0):
        progress.update(i, n, item="fire-smoke")
"""

import time

import bpy

try:
    import blf
    import gpu
    from gpu_extras.batch import batch_for_shader
except Exception:                                             # pragma: no cover
    blf = gpu = batch_for_shader = None


PUMP_INTERVAL = 0.15        # seconds between forced repaints
BAR_W_MAX = 560             # overlay width cap, px
GREEN = (0.42, 0.78, 0.34, 1.0)      # the family's session-import green
TRACK = (0.30, 0.30, 0.33, 1.0)
BACK = (0.09, 0.09, 0.11, 0.90)
EDGE = (1.0, 1.0, 1.0, 0.07)

_S = {
    "on": False,
    "title": "",
    "phase": "",
    "item": "",
    "frac": None,        # 0..1 inside the phase, None = indeterminate
    "phase_no": 0,
    "phase_total": 0,
    "t0": 0.0,
    "last_pump": 0.0,
    "handle": None,
    "wm": None,
}


def _window():
    try:
        wm = bpy.context.window_manager
        return wm.windows[0] if wm and wm.windows else None
    except Exception:
        return None


def active():
    return _S["on"]


def begin(title, phase_total=0):
    """Start a job. Safe to call when one is already running (re-titles)."""
    if bpy.app.background or blf is None or _window() is None:
        return False
    _S.update(title=title, phase="", item="", frac=None,
              phase_no=0, phase_total=int(phase_total or 0),
              t0=time.monotonic(), last_pump=0.0, on=True)
    if _S["handle"] is None:
        try:
            _S["handle"] = bpy.types.SpaceView3D.draw_handler_add(
                _draw, (), 'WINDOW', 'POST_PIXEL')
        except Exception:
            _S["handle"] = None
    try:
        _S["wm"] = bpy.context.window_manager
        _S["wm"].progress_begin(0, 100)
    except Exception:
        _S["wm"] = None
    _pump(force=True)
    return True


def phase(label, number=None):
    """A new stage of the job ('Models', 'Animation'...)."""
    if not _S["on"]:
        return
    _S["phase"] = str(label)
    _S["item"] = ""
    _S["frac"] = None
    if number is not None:
        _S["phase_no"] = int(number)
    else:
        _S["phase_no"] += 1
    _pump(force=True)


def update(i=None, n=None, item=""):
    """Progress inside the current phase; i/n may be unknown."""
    if not _S["on"]:
        return
    if item:
        _S["item"] = str(item)
    if n and n > 0 and i is not None:
        _S["frac"] = max(0.0, min(1.0, float(i) / float(n)))
        if item:
            _S["item"] = f"{i}/{n}  {item}"
        else:
            _S["item"] = f"{i}/{n}"
    _pump()


def note(text):
    """A sub-line with no fraction (e.g. 'Converting DMX to TEX...')."""
    if not _S["on"]:
        return
    _S["item"] = str(text)
    _S["frac"] = None
    _pump(force=True)


def end():
    if not _S["on"]:
        return
    _S["on"] = False
    if _S["handle"] is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_S["handle"], 'WINDOW')
        except Exception:
            pass
        _S["handle"] = None
    if _S["wm"] is not None:
        try:
            _S["wm"].progress_end()
        except Exception:
            pass
        _S["wm"] = None
    try:
        for ws in bpy.data.workspaces:
            ws.status_text_set(None)
    except Exception:
        pass
    _redraw()


class job:
    """`with Progress.job("Import Models"):` around an operator's work."""

    def __init__(self, title, phase_total=0):
        self.title = title
        self.phase_total = phase_total
        self.owner = False

    def __enter__(self):
        #  A nested job (a step operator called by the one-click) must not
        #  steal or end the outer bar.
        if not _S["on"]:
            self.owner = begin(self.title, self.phase_total)
        return self

    def __exit__(self, *_exc):
        if self.owner:
            end()
        return False


def jobbed(title, phase_total=0):
    """Decorator form of `job` - wraps a whole step function so the six
    green step operators get the bar for free, and the one-click (which
    already owns a bar when it calls them) nests without stealing it."""
    import functools

    def deco(fn):
        @functools.wraps(fn)
        def wrapped(*args, **kwargs):
            with job(title, phase_total):
                return fn(*args, **kwargs)
        return wrapped
    return deco


# ---------------------------------------------------------------------------
#  The pump - status text, cursor %, and the forced repaint
# ---------------------------------------------------------------------------

def _overall():
    """One number for the whole job, for the cursor % and the bar fill."""
    frac = _S["frac"] if _S["frac"] is not None else 0.0
    if _S["phase_total"] > 0 and _S["phase_no"] > 0:
        done = min(_S["phase_no"], _S["phase_total"]) - 1
        return (done + frac) / float(_S["phase_total"])
    return frac


def _pump(force=False):
    now = time.monotonic()
    if not force and (now - _S["last_pump"]) < PUMP_INTERVAL:
        return
    _S["last_pump"] = now
    line = " - ".join(x for x in (_S["title"], _S["phase"], _S["item"]) if x)
    try:
        bpy.context.workspace.status_text_set(line[:180])
    except Exception:
        pass
    if _S["wm"] is not None:
        try:
            _S["wm"].progress_update(int(_overall() * 100))
        except Exception:
            pass
    _redraw()


def _redraw():
    if bpy.app.background:
        return
    try:
        #  Repaint and SWAP every window right now. The one call that makes
        #  a blocking pipeline visibly alive.
        bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
    except Exception:
        pass


# ---------------------------------------------------------------------------
#  The overlay
# ---------------------------------------------------------------------------

def _rect(shader, x, y, w, h, color):
    batch = batch_for_shader(shader, 'TRIS', {"pos": (
        (x, y), (x + w, y), (x + w, y + h),
        (x, y), (x + w, y + h), (x, y + h))})
    shader.uniform_float("color", color)
    batch.draw(shader)


def _draw():
    if not _S["on"] or gpu is None:
        return
    try:
        region = bpy.context.region
        if region is None:
            return
        width = min(BAR_W_MAX, region.width - 120)
        if width < 220:
            return
        x = (region.width - width) * 0.5
        y = 28.0
        height = 64.0
        pad = 14.0

        shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        _rect(shader, x, y, width, height, BACK)
        _rect(shader, x, y + height - 1, width, 1, EDGE)

        #  The bar: a 5 px track with the overall fill; a sweeping segment
        #  when the phase cannot count itself.
        bx, by, bw, bh = x + pad, y + 12.0, width - 2 * pad, 5.0
        _rect(shader, bx, by, bw, bh, TRACK)
        if _S["frac"] is None and _S["phase_total"] <= 0:
            sweep = 0.28
            t = (time.monotonic() - _S["t0"]) * 0.45 % (1.0 + sweep) - sweep
            lo = max(0.0, t)
            hi = min(1.0, t + sweep)
            if hi > lo:
                _rect(shader, bx + bw * lo, by, bw * (hi - lo), bh, GREEN)
        else:
            _rect(shader, bx, by, bw * _overall(), bh, GREEN)
        gpu.state.blend_set('NONE')

        elapsed = int(time.monotonic() - _S["t0"])
        clock = f"{elapsed // 60:02d}:{elapsed % 60:02d}"
        font = 0
        blf.enable(font, blf.SHADOW)
        blf.shadow(font, 3, 0.0, 0.0, 0.0, 0.8)

        blf.size(font, 13)
        blf.color(font, 0.95, 0.95, 0.95, 1.0)
        blf.position(font, x + pad, y + height - 22.0, 0)
        blf.draw(font, _S["title"])
        cw = blf.dimensions(font, clock)[0]
        blf.position(font, x + width - pad - cw, y + height - 22.0, 0)
        blf.color(font, 0.75, 0.75, 0.75, 1.0)
        blf.draw(font, clock)

        blf.size(font, 11)
        blf.color(font, 0.78, 0.85, 0.74, 1.0)
        sub = " - ".join(s for s in (_S["phase"], _S["item"]) if s)
        blf.position(font, x + pad, y + 24.0, 0)
        blf.draw(font, sub[:110])
        blf.disable(font, blf.SHADOW)
    except Exception:
        #  A progress bar must never take the viewport down. Disarm.
        _S["on"] = False
