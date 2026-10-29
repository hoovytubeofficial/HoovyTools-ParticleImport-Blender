# =============================================================================
#  tools/htlog.py  -  remember what HoovyTools printed, so users can SEND it
# =============================================================================
#
#  Blender's console cannot be read back after the fact, so troubleshooting
#  used to mean teaching every user to open the system console, scroll, and
#  screenshot. Instead: print() is tee'd (started at addon register), and any
#  line carrying a HoovyTools tag is kept in a ring buffer. "Copy Console
#  Output" then hands the user a paste-ready report.
#
#  Deliberately narrow: only tagged lines are stored (other add-ons' chatter
#  is not), the buffer is capped, and the original print is always called
#  first - if the tee ever fails it fails silent and the console still works.
# =============================================================================

import builtins

TAGS = ("[HT_", "[HoovyTools", "[GN export]", "[VTF_SPLIT]")
MAX_LINES = 4000

_buf = []
_orig_print = None


def _tee(*args, **kwargs):
    _orig_print(*args, **kwargs)
    try:
        s = " ".join(str(a) for a in args)
        if any(t in s for t in TAGS):
            _buf.append(s)
            if len(_buf) > MAX_LINES:
                del _buf[:len(_buf) - MAX_LINES]
    except Exception:
        pass


def start():
    """Install the tee. Idempotent; never wraps twice."""
    global _orig_print
    if _orig_print is None:
        _orig_print = builtins.print
        builtins.print = _tee


def stop():
    global _orig_print
    if _orig_print is not None:
        builtins.print = _orig_print
        _orig_print = None


def lines():
    return list(_buf)


def clear():
    del _buf[:]
