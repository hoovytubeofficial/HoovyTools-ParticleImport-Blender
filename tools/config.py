
import json
from pathlib import Path

KEYS = ("sfm_usermod", "pcf_dir", "texture_dir", "trail_dir", "fancy_layouts", "viewport_facing", "log_to_file",
        "feedback")
ABOUT = ("Source Particle Import settings. Edit, save, then Dev > Wiring > Reload Config (or restart Blender). "
         "An empty folder = found by itself. feedback: POPUP, REPORT or QUIET.")
#  set while the file is being applied, so the preferences' update callbacks do not write it back mid-way
_BUSY = {"on": False}


def path():
    return Path(__file__).resolve().parent.parent / "_config" / "config.json"


def payload(prefs):
    data = {"_about": ABOUT}
    for k in KEYS:
        data[k] = getattr(prefs, k)
    return data


def write(prefs):
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload(prefs), indent=2) + "\n", encoding="utf-8")
    return p


def save(prefs):
    """Every preference's update calls this: keep the file in step - once it exists, never while applying it."""
    if _BUSY["on"] or prefs is None:
        return
    try:
        if path().is_file():
            write(prefs)
    except OSError:
        pass


def apply(prefs):
    """The file's values into the preferences. (keys applied, problems) - never raises."""
    p = path()
    if prefs is None or not p.is_file():
        return [], []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], ["%s: %s" % (p.name, exc)]
    if not isinstance(data, dict):
        return [], ["%s is not a { ... } object" % p.name]
    done, bad = [], []
    _BUSY["on"] = True
    try:
        for k in KEYS:
            if k not in data:
                continue
            value, now = data[k], getattr(prefs, k)
            if isinstance(now, bool) and not isinstance(value, bool):
                bad.append("%s wants true or false" % k)
                continue
            if isinstance(now, str) and not isinstance(value, str):
                bad.append("%s wants text in quotes" % k)
                continue
            try:
                if value != now:
                    setattr(prefs, k, value)
                done.append(k)
            except (TypeError, ValueError) as exc:               # an Errors value that does not exist
                bad.append("%s: %s" % (k, exc))
    finally:
        _BUSY["on"] = False
    return done, bad
