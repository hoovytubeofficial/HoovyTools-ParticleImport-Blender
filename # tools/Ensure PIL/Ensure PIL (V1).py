# =============================================================================
# Ensure PIL (V1)
# The Text Editor version of  Source Particle Import > Tools > 4.3 Ensure PIL
# (Source Particle Import 3.0.1). Needs nothing else - it works even when an
# add-on can't load bc of a broken Pillow
# =============================================================================
#
# WHAT IT does: makes Pillow (PIL) work in this Blender. Blender brings no
# Pillow of its own, and a Pillow put there by another Python (another
# Blender, a system Python, "Load Previous Settings") fails with
# can't import name '_imaging' from 'PIL'
# because its compiled part was built for another Python version. This
# installs Pillow with this Blender's own Python, so it always fits: over the
# broken copy, else into Blender's site-packages, else into your user
# scripts\modules folder. Needs the internet once (about 7 MB from PyPI)
#
# HOW: open it in Blender's Text Editor, press Run Script (Alt+P). It prints
# what it found and did (Window > Toggle System Console), and the last line
# says whether Pillow works now. No restart needed.
#
# this feature was added in version 3.0.1 and is in experimental stage.
# =============================================================================

INSTALL = True              # false = only say whether Pillow works, change nothing

# -----------------------------------------------------------------------------

import importlib
import importlib.util
import os
import subprocess
import sys
import sysconfig
import tempfile

import bpy


def purge():
    for name in [n for n in list(sys.modules) if n == "PIL" or n.startswith("PIL.")]:
        sys.modules.pop(name, None)
    importlib.invalidate_caches()


def status():
    """(works, version, the PIL folder, the error) - PIL.Image imported and a pixel made: the real test"""
    try:
        spec = importlib.util.find_spec("PIL")
    except Exception:
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


def run(args):
    env = {k: v for k, v in os.environ.items()
           if k.upper() not in ("PYTHONPATH", "PYTHONHOME", "PIP_TARGET", "PIP_PREFIX", "PIP_USER")}
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
                           timeout=300, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as exc:
        return False, str(exc)
    return r.returncode == 0, ((r.stdout or "") + "\n" + (r.stderr or "")).strip()


def writable(folder):
    try:
        os.makedirs(folder, exist_ok=True)
        fd, probe = tempfile.mkstemp(prefix=".pil_write_", dir=folder)
        os.close(fd)
        os.remove(probe)
        return True
    except OSError:
        return False


def main():
    ok, ver, where, err = status()
    if ok:
        print("ENSURE PIL: Pillow %s works (%s)" % (ver, where))
        return
    print("ENSURE PIL: %s%s" % (err, ("  (found in %s)" % where) if where else ""))
    if not INSTALL:
        return
    py = sys.executable
    user_mods = bpy.utils.user_resource("SCRIPTS", path="modules", create=True)
    order = []
    for d in ((os.path.dirname(where) if where else None), sysconfig.get_paths().get("purelib"), user_mods):
        if d and os.path.normcase(d) not in [os.path.normcase(x) for x in order]:
            order.append(d)
    if not run([py, "-m", "pip", "--version"])[0]:
        print("ENSURE PIL: adding pip with ensurepip")
        if not run([py, "-m", "ensurepip", "--upgrade"])[0]:
            run([py, "-m", "ensurepip", "--upgrade", "--user"])
    for tgt in order:
        if not writable(tgt):
            print("ENSURE PIL: cannot write to %s - next" % tgt)
            continue
        print("ENSURE PIL: installing Pillow into %s ..." % tgt)
        done, out = run([py, "-m", "pip", "install", "--upgrade", "--no-input", "--disable-pip-version-check",
                         "--no-warn-script-location", "--retries", "2", "--timeout", "30",
                         "--target", tgt, "Pillow"])
        if not done:
            print("ENSURE PIL: pip failed there:\n" + out[-1500:])
            continue
        purge()
        here = [os.path.normcase(p) for p in sys.path]
        if order[0] != tgt and where:                  # a broken copy it could not replace: go ahead of it
            sys.path[:] = [tgt] + [p for p in sys.path if os.path.normcase(p) != os.path.normcase(tgt)]
        elif os.path.normcase(tgt) not in here:
            sys.path.append(tgt)                       # this session; Blender adds it itself from now on
        ok, ver, where2, err = status()
        if ok:
            print("ENSURE PIL: Pillow %s works now (%s)" % (ver, where2))
            if where and order[0] != tgt:
                print("ENSURE PIL: a broken copy is still in %s - delete that PIL folder with Blender closed"
                      % os.path.dirname(where))
            return
        print("ENSURE PIL: installed in %s but it still does not load: %s" % (tgt, err))
    print('ENSURE PIL: FAILED. By hand, in a Command Prompt:\n    "%s" -m pip install --upgrade --target "%s" Pillow'
          % (py, user_mods))


main()
