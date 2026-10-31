# =============================================================================
# tools/pil_ensure.py  -  ENSURE PIL: a Pillow that works in THIS Blender
# =============================================================================


#why IT BREAKS: Blender ships its own Python and no Pillow. Pillow's heart is
#one compiled file built for ONE Python version (_imaging.cp311-win_amd64.pyd
#is Python 3.11 only). A Pillow put there by another Python - pip --target
#run from a system Python, a folder copied from another Blender, "Load
#Previous Settings" carrying scripts\modules over to a Blender with a newer
#Python - still imports as `PIL`, then `from PIL import Image` dies on that
#file: "cannot import name '_imaging'". So the test here is the real one -
#PIL.Image imported and a pixel made. A bare `import PIL` passes on a broken
#copy (the old Preview Cards wiring row did exactly that).
#
#what ENSURE does when Pillow is missing or broken: runs this Blender's own
#Python (sys.executable) to pip-install Pillow - so the compiled file always
#matches - into the first of:
#the folder the broken copy sits in, replacing it (--target --upgrade),
#Blender's own site-packages, when it can be written to,
#your user scripts\modules folder (always writable; Blender reads it)
#pip itself comes from Python's own ensurepip when a Blender lacks it. Then
#the half-imported copy is dropped from memory and Pillow imported again -
#no restart. Nothing is deleted beyond what pip's own replace does
#
#NEEDS THE INTERNET the first time (PyPI, about 7 MB). When anything fails it
#says why, and the message carries the one command that does it by hand
#bpy-free except where a Blender path is asked for (user_modules).
# =============================================================================

import importlib
import importlib.util
import os
import subprocess
import sys
import sysconfig
import tempfile

PACKAGE = "Pillow"
PIP_EXTRA = []              # extra pip arguments for every install (the tests: --no-index --find-links <folder>)
TIMEOUT = 300               # secs pip may take
TAG = "[HT_PIL]"
#the environment pip runs in, minus what points it at another Python or forces another target
_DROP_ENV = ("PYTHONPATH", "PYTHONHOME", "PIP_TARGET", "PIP_PREFIX", "PIP_USER", "PIP_REQUIRE_VIRTUALENV")


def _say(log, text):
    try:
        log("%s  %s" % (TAG, text))
    except Exception:
        pass


def _norm(path):
    return os.path.normcase(os.path.abspath(path)) if path else ""


def purge():
    """Forget every PIL module this Python has (half) imported, so the next import reads the disk again."""
    for name in [n for n in list(sys.modules) if n == "PIL" or n.startswith("PIL.")]:
        sys.modules.pop(name, None)
    importlib.invalidate_caches()


def status():
    """(works, version or None, the PIL folder found or None, the error or None).

    The REAL test: PIL.Image imported (that loads the compiled _imaging) and one pixel made. A broken copy is
    forgotten again afterwards, so a repair can load the new one in the same session."""
    try:
        spec = importlib.util.find_spec("PIL")
    except Exception:                                          # a finder that raises = nothing to import
        spec = None
    where = os.path.dirname(spec.origin) if spec is not None and spec.origin else None
    if spec is None:
        return False, None, None, "Pillow (PIL) is not installed in this Blender's Python"
    try:
        import PIL
        from PIL import Image
        Image.new("RGB", (1, 1)).getpixel((0, 0))
        return True, getattr(PIL, "__version__", "?"), os.path.dirname(PIL.__file__), None
    except Exception as exc:
        purge()
        return False, None, where, "%s: %s" % (type(exc).__name__, exc)


def why(err, where):
    """One line for a wiring row or an error report: what is wrong with Pillow here."""
    if where:
        return "the Pillow in %s does not load (%s) - it was installed for another Python" % (where, err)
    return "Pillow (PIL) is not installed in this Blender's Python"


def python_exe():
    """This Blender's own Python. sys.executable is it since Blender 2.92; before that it was Blender itself."""
    exe = sys.executable or ""
    if os.path.basename(exe).lower().startswith("blender"):
        try:
            import bpy
            exe = getattr(bpy.app, "binary_path_python", "") or exe
        except Exception:
            pass
    return exe


def site_packages():
    try:
        return sysconfig.get_paths()["purelib"]
    except Exception:
        return None


def user_modules(create=True):
    """Your user scripts\\modules folder for this Blender version (made if missing, unless create=False), or None
    outside Blender."""
    try:
        import bpy
        return bpy.utils.user_resource("SCRIPTS", path="modules", create=create)
    except Exception:
        return None


def writable(folder):
    """Can a file be made in `folder` (made if missing)? Asked for real - permissions on Windows lie."""
    try:
        os.makedirs(folder, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".htp_write_", dir=folder)
        os.close(fd)
        os.remove(probe)
        return True
    except OSError:
        return False


def targets(broken_in=None):
    """Where to install, in order: over the broken copy, Blender's site-packages, your user modules folder. Only named
    here - writable() makes a folder when pip is about to use it."""
    out = []
    for d in (broken_in, site_packages(), user_modules(create=False)):
        if d and _norm(d) not in [_norm(x) for x in out]:
            out.append(d)
    return out


def _run(args):
    """(exit code 0, the output) - pip in a hidden window, never on Blender's console."""
    env = {k: v for k, v in os.environ.items() if k.upper() not in _DROP_ENV}
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                           timeout=TIMEOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return False, "timed out after %d s" % TIMEOUT
    except OSError as exc:
        return False, "could not start %s: %s" % (args[0], exc)
    return r.returncode == 0, ((r.stdout or "") + "\n" + (r.stderr or "")).strip()


def _last(out):
    """The line of pip's output that says what went wrong (its ERROR line, else the last one)."""
    lines = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    errs = [ln for ln in lines if ln.upper().startswith("ERROR")]
    return (errs[-1] if errs else (lines[-1] if lines else "no output"))[:300]


def _ensure_pip(py, log):
    """(pip works, why not). A Blender without pip gets it from Python's own bundled ensurepip - no download."""
    ok, _out = _run([py, "-m", "pip", "--version"])
    if ok:
        return True, ""
    _say(log, "this Blender's Python has no pip - adding it with ensurepip")
    for extra in ([], ["--user"]):
        ok, out = _run([py, "-m", "ensurepip", "--upgrade"] + extra)
        if ok and _run([py, "-m", "pip", "--version"])[0]:
            return True, ""
    return False, "pip could not be added to this Blender's Python (%s)" % _last(out)


def manual_command(py=None, target=None):
    """The command that does it by hand (Command Prompt), for the message when the automatic way fails."""
    py = py or python_exe()
    target = target or user_modules(create=False) or site_packages() or ""     #a wiring row only names it
    return '"%s" -m pip install --upgrade --target "%s" %s' % (py, target, PACKAGE)


def ensure(install=True, log=print, target_dirs=None):
    """(works, message). Working already: (True, "Pillow x works (folder)"). Missing or broken and `install`: pip
    installs Pillow with this Blender's Python (the header says where), drops the old copy from memory, imports it
    again and says what happened. `target_dirs` replaces the folder order (the tests). Never raises."""
    try:
        ok, ver, where, err = status()
        if ok:
            return True, "Pillow %s works (%s)" % (ver, where)
        if not install:
            return False, why(err, where)
        py = python_exe()
        broken_dir = os.path.dirname(where) if where else None     # the folder holding the broken PIL folder
        order = list(target_dirs) if target_dirs else targets(broken_dir)
        _say(log, "%s - installing %s with %s" % (why(err, where), PACKAGE, py))
        pip_ok, pip_why = _ensure_pip(py, log)
        if not pip_ok:
            return False, "%s. By hand: %s" % (pip_why, manual_command(py, order[-1] if order else None))
        tried = []
        for tgt in order:
            if not writable(tgt):
                tried.append("%s: cannot write there" % tgt)
                continue
            _say(log, "pip install --upgrade --target %s %s" % (tgt, PACKAGE))
            ran, out = _run([py, "-m", "pip", "install", "--upgrade", "--no-input", "--disable-pip-version-check",
                             "--no-warn-script-location", "--retries", "2", "--timeout", "30",
                             "--target", tgt, PACKAGE] + list(PIP_EXTRA))
            if not ran:
                tried.append("%s: %s" % (tgt, _last(out)))
                _say(log, "pip failed: %s" % _last(out))
                continue
            purge()
            if broken_dir and _norm(broken_dir) != _norm(tgt):
                # a broken copy it could not replace is still on the path: the new one goes ahead of it
                sys.path[:] = [tgt] + [p for p in sys.path if _norm(p) != _norm(tgt)]
            elif _norm(tgt) not in [_norm(p) for p in sys.path]:
                sys.path.append(tgt)                           # this session; Blender adds it itself from now on
            ok, ver, where, err = status()
            if ok:
                msg = "Pillow %s installed in %s" % (ver, tgt)
                if broken_dir and _norm(broken_dir) != _norm(tgt):
                    msg += (" - a broken copy is still in %s (it could not be replaced): delete its PIL folder "
                            "with Blender closed, or it can load first when Blender starts again" % broken_dir)
                _say(log, msg)
                return True, msg
            tried.append("%s: installed, but it still does not load (%s)" % (tgt, err))
        detail = "; ".join(tried) or "no folder to install into"
        return False, "Pillow could not be installed (%s). By hand: %s" % (
            detail, manual_command(py, order[-1] if order else None))
    except Exception as exc:                                   # ENSURE never takes the add-on down with it
        return False, "ENSURE PIL failed: %s: %s" % (type(exc).__name__, exc)
