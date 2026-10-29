
import builtins
import sys
import threading
import time
import traceback
from pathlib import Path

MARK = "[Source Particle Import]"
PACKAGE = (__package__ or "").split(".")[0]
__print_wrapper__ = True             # read by every print wrapper in the family

MAX_LINES = 4000
LOG_KEEP = 20
LOG_STEM = "Source Particle Import_"
HISTORY_KEEP = 80

_buf = []
_history = []
_orig_print = None
_on = False
_lock = threading.Lock()
_log_path = None
_log_failed = False
_CONSOLES = None


# ── where the log goes ────────────────────────────────────────────────────

def addon_root():
    return Path(__file__).resolve().parent.parent


def logs_dir(create=True):
    """_Logs inside the add-on; Blender's config folder when the add-on folder is read-only."""
    candidates = [addon_root() / "_Logs"]
    try:
        import bpy
        candidates.append(Path(bpy.utils.user_resource("CONFIG", path="Source Particle Import")) / "Logs")
    except Exception:
        pass
    for d in candidates:
        try:
            if create:
                d.mkdir(parents=True, exist_ok=True)
            if d.is_dir():
                return d
        except Exception:
            continue
    return None


def log_path():
    """This Blender session's log file (made on first use), or None when no folder can be written."""
    global _log_path, _log_failed
    if _log_path is not None or _log_failed:
        return _log_path
    d = logs_dir()
    if d is None:
        _log_failed = True
        return None
    try:
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        p = d / (LOG_STEM + stamp + ".log")
        p.write_text("=" * 78 + "\n  Source Particle Import log - %s\n" % stamp + "=" * 78 + "\n\n",
                     encoding="utf-8")
        _log_path = p
        old = sorted(d.glob(LOG_STEM + "*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in old[LOG_KEEP:]:
            try:
                f.unlink()
            except Exception:
                pass
    except Exception:
        _log_failed = True
    return _log_path


def _log_write(text):
    if not _log_enabled():
        return
    p = log_path()
    if p is None:
        return
    try:
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(text if text.endswith("\n") else text + "\n")
    except Exception:
        pass


#  Set from the preferences (op_prefs pushes it on register and on every change) - print can be called from the
#  preview workers' reader threads, where reading bpy is not safe.
SETTINGS = {"log_to_file": True}


def _log_enabled():
    return bool(SETTINGS.get("log_to_file", True))


# ── the print wrapper ─────────────────────────────────────────────────────

def _consoles():
    global _CONSOLES
    if _CONSOLES is None:
        _CONSOLES = {id(s) for s in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__) if s is not None}
    return _CONSOLES


def _caller_is_mine():
    f = sys._getframe(1)
    while f is not None and f.f_globals.get("__print_wrapper__"):
        f = f.f_back
    name = f.f_globals.get("__name__", "") if f is not None else ""
    return name == PACKAGE or name.startswith(PACKAGE + ".")


def mark_text(text):
    return "\n".join((MARK + " " + ln) if ln.strip() else ln for ln in str(text).split("\n"))


def _tee(*args, **kwargs):
    prev = _orig_print or builtins.__dict__.get("print")
    try:
        target = kwargs.get("file")
        if _on and (target is None or id(target) in _consoles()) and _caller_is_mine():
            sep = kwargs.get("sep")
            text = (" " if sep is None else str(sep)).join(str(a) for a in args)
            marked = mark_text(text)
            rest = {k: v for k, v in kwargs.items() if k != "sep"}
            prev(marked, **rest)
            _keep(marked)
            return None
    except Exception:
        pass
    return prev(*args, **kwargs)


def _keep(marked):
    stamp = time.strftime("%H:%M:%S")
    with _lock:
        for ln in marked.split("\n"):
            if ln.strip():
                _buf.append(ln)
        if len(_buf) > MAX_LINES:
            del _buf[:len(_buf) - MAX_LINES]
        _log_write("\n".join("[%s] %s" % (stamp, ln) for ln in marked.split("\n") if ln.strip()))


def start():
    """Wrap print (once) and switch marking on."""
    global _orig_print, _on
    if _orig_print is None:
        _orig_print = builtins.print
        builtins.print = _tee
    _on = True


def stop():
    """Marking off. Unwraps when nothing wrapped print after us; otherwise stays chained as a pass-through."""
    global _orig_print, _on
    _on = False
    if _orig_print is not None and builtins.print is _tee:
        builtins.print = _orig_print
        _orig_print = None


def lines():
    with _lock:
        return list(_buf)


def clear():
    with _lock:
        del _buf[:]


# ── what happened: events and failures ────────────────────────────────────

def history():
    with _lock:
        return list(_history)


def event(level, title, body=(), pcf=None):
    """Remember one thing that happened (PRINT HELP lists them) and print it."""
    item = {"t": time.strftime("%H:%M:%S"), "level": level, "title": title,
            "lines": [str(b) for b in body], "pcf": str(pcf) if pcf else ""}
    with _lock:
        _history.append(item)
        if len(_history) > HISTORY_KEEP:
            del _history[:len(_history) - HISTORY_KEEP]
    tag = {"ERROR": "FAILED ", "WARNING": "WARNING ", "INFO": ""}.get(level, "")
    print("[HT_REPORT]  %s%s" % (tag, title))
    for ln in item["lines"]:
        print("[HT_REPORT]      %s" % ln)
    return item


def _where(exc):
    """'tools/datamodel.py line 832, in load' - the deepest frame inside this add-on, else the deepest at all."""
    tb = traceback.extract_tb(exc.__traceback__) if exc is not None and exc.__traceback__ else []
    root = str(addon_root()).lower()
    mine = [f for f in tb if str(f.filename).lower().startswith(root)]
    f = (mine or tb or [None])[-1]
    if f is None:
        return ""
    try:
        rel = Path(f.filename).resolve().relative_to(addon_root()).as_posix()
    except Exception:
        rel = Path(f.filename).name
    return "%s line %s, in %s" % (rel, f.lineno, f.name)


def failure(title, pcf=None, system=None, exc=None, stage=None, hint=None, extra=()):
    """The detailed error. Prints it marked, logs it with the traceback, keeps it for PRINT HELP, and returns
    the one line for the status bar - which always names the .pcf."""
    pcf_path = Path(pcf) if pcf else None
    body = []
    if pcf_path is not None:
        body.append("file    : %s" % pcf_path)
        try:
            body.append("size    : %s bytes%s" % (format(pcf_path.stat().st_size, ","),
                                                  "" if pcf_path.is_file() else " (missing)"))
        except Exception:
            body.append("size    : (the file is not there)")
    if system:
        body.append("system  : %s" % system)
    if stage:
        body.append("stage   : %s" % stage)
    if exc is not None:
        body.append("error   : %s: %s" % (type(exc).__name__, exc))
        where = _where(exc)
        if where:
            body.append("where   : %s" % where)
    body += list(extra)
    if hint:
        body.append("try     : %s" % hint)
    item = event("ERROR", title, body, pcf=pcf_path)
    if exc is not None and exc.__traceback__ is not None:
        tb_lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
        item["traceback"] = "".join(tb_lines).splitlines()
        _log_write("\n".join("           " + ln for ln in item["traceback"]))
    short = title
    if pcf_path is not None:
        short += " - %s" % pcf_path.name
    if system:
        short += " / %s" % system
    if exc is not None:
        short += " - %s: %s" % (type(exc).__name__, str(exc)[:160])
    return short + "  (Dev > Print Help writes the details to a .txt)"


def popup_failure(context, title, lines):
    """The error as a popup when Feedback is Popup - never in the background (a popup with no window crashes)."""
    try:
        import bpy
        if bpy.app.background or context is None or getattr(context, "window", None) is None:
            return
        prefs = bpy.context.preferences.addons[PACKAGE].preferences
        if getattr(prefs, "feedback", "POPUP") != "POPUP":
            return

        def draw(menu, _ctx):
            col = menu.layout.column(align=True)
            for ln in lines[:24]:
                col.label(text=str(ln)[:120])
            menu.layout.separator()
            menu.layout.operator("htp.print_help", text="Print Help (.txt)", icon="HELP")

        context.window_manager.popup_menu(draw, title=title, icon="ERROR")
    except Exception:
        pass
