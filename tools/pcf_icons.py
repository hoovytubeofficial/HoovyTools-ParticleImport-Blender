# =============================================================================
#  tools/pcf_icons.py  -  FOLDER ICONS for particle packs  (bpy-free)
# =============================================================================
#
#  A SIMPLIFIED ICO STUDIO. HoovyTube's own icon maker
#  (Ico Studio V5) fills a shape with a
#  picture, shades it with the shape's own light and tints the rim. The pack
#  folders under usermod\particles already wear its glass ORB - so a pack icon
#  here is that orb (images/preview/preview_orb.png, taken out of Ico Studio V5
#  unchanged), filled with the pack's best particle render, its rim in the
#  pack's designated colour. No badges, labels or ratings: just the orb.
#
#      orb_icon(face, rim)        the 512 px master          (Ico Studio render())
#      save_ico(img, path)        16, 24, 32, 48, 64, 128, 256 px in one .ico
#      icon_assignment(folder)    what desktop.ini already points at, if anything
#      assign_folder_icon(...)    set it - the old desktop.ini and attributes are
#                                 saved first (Ico Studio's backup, byte for byte)
#      restore_folder_icon(json)  put a folder back exactly as the backup says
#      make_folder_icons(...)     PROCESS ENTIRE FOLDER's last step: one icon per
#                                 folder DIRECTLY under the processed folder (the
#                                 cap: particles\<pack> gets one, particles\<pack>
#                                 \<sub> does not); applied only to folders that
#                                 have no icon yet unless told otherwise
#
#  NEVER OVERWRITES: an icon name that is taken gets " v2", " v3" ...
# =============================================================================

import configparser
import base64
import hashlib
import json
import os
import re

from PIL import Image, ImageOps

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ORB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images", "preview", "preview_orb.png")
CARD_PICTURE = (0.054, 0.23, 0.946, 0.80)     # where the effect sits on a card (fractions)


# ── the icon ─────────────────────────────────────────────────────────────────

def orb_icon(face, rim_rgb=None, size=512, bevel=1.0, rim_strength=0.8, shape_scale=0.97, zoom=1.0):
    """Ico Studio V5's render() with its circle overlay and rim mode Color: the
    face fills the orb edge to edge, the orb's own light shades it (glass
    highlight, dark edge), and the rim takes `rim_rgb` (silver when None)."""
    import numpy as np
    overlay = Image.open(ORB).convert("RGBA")
    box = overlay.getchannel("A").point(lambda v: 255 if v > 24 else 0).getbbox()
    ov = ImageOps.contain(overlay.crop(box), (round(size * shape_scale), round(size * shape_scale)), Image.LANCZOS)
    w, h = ov.size
    src = face.convert("RGBA")
    scale = max(w / src.width, h / src.height) * zoom
    sw, sh = max(w, round(src.width * scale)), max(h, round(src.height * scale))
    art = src.resize((sw, sh), Image.LANCZOS)
    left, top = round((sw - w) / 2), round((sh - h) / 2)
    art = art.crop((left, top, left + w, top + h))
    art = Image.alpha_composite(Image.new("RGBA", (w, h), (35, 38, 44, 255)), art)
    base = np.asarray(art.convert("RGB"), dtype=np.float32) / 255
    lum = np.asarray(ov.convert("L"), dtype=np.float32) / 255
    alpha = np.asarray(ov.getchannel("A"))
    solid = alpha > 240
    neutral = float(np.median(lum[solid])) if np.any(solid) else 0.65
    neutral = max(0.01, min(0.99, neutral))
    dark = np.minimum(1, lum / neutral)[:, :, None]
    light = np.clip((lum - neutral) / (1 - neutral), 0, 1)[:, :, None]
    shaded = 1 - (1 - base * dark) * (1 - light)
    shaded = np.clip(base + (shaded - base) * bevel, 0, 1)
    tint = rim_rgb or (230, 232, 237)
    delta = np.abs(lum - neutral)
    spread = max(float(np.quantile(delta[solid], 0.98)), 0.12) if np.any(solid) else 0.12
    weight = np.clip((delta - 0.018) / spread, 0, 1) * rim_strength
    bezel = lum[:, :, None] * np.array(tint[:3], dtype=np.float32)[None, None, :] / 255
    shaded = shaded * (1 - weight[:, :, None]) + bezel * weight[:, :, None]
    out = Image.fromarray(np.uint8(np.clip(shaded * 255, 0, 255))).convert("RGBA")
    out.putalpha(ov.getchannel("A"))
    canvas = Image.new("RGBA", (size, size))
    canvas.alpha_composite(out, ((size - w) // 2, (size - h) // 2))
    return canvas


def save_ico(img, path):
    img.save(path, sizes=[(s, s) for s in ICO_SIZES])
    return path


def safe_icon_stem(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(name))
    name = re.sub(r"\s+", " ", name).strip(" .")[:120] or "Particles"
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])", name):
        name = "_" + name
    return name


def ico_path(icon_dir, folder_name):
    """`<icon dir>\\<folder name>.ico`, or the first free " v2", " v3" ..."""
    base = os.path.join(icon_dir, safe_icon_stem(folder_name))
    if not os.path.exists(base + ".ico"):
        return base + ".ico"
    n = 2
    while os.path.exists(f"{base} v{n}.ico"):
        n += 1
    return f"{base} v{n}.ico"


def face_score(face, strength=0.0):
    """How good a face is for an icon (0.26.2). Light alone picked full-frame
    white / cyan flashes and one black card on the library run, so: some
    light (sqrt of the mean), STRUCTURE (the spread of luminance), colour
    helps, and a frame that is mostly blown-out white scores near nothing."""
    import numpy as np
    im = face.convert("RGB") if hasattr(face, "convert") else Image.open(face).convert("RGB")
    im.thumbnail((256, 256))
    rgb = np.asarray(im, dtype=np.float32) / 255.0
    lum = rgb.mean(axis=2)
    mean, spread = float(lum.mean()), float(lum.std())
    #  clipped in ANY channel - a full-frame yellow or pink flash never turns
    #  white, but it is just as flat
    clipped = float((rgb.max(axis=2) > 0.94).mean())
    flat = max(0.05, 1.0 - 2.5 * max(0.0, clipped - 0.12))
    return (mean ** 0.5) * (0.1 + spread / 0.2) * (0.6 + float(strength or 0.0)) * flat


def face_from_card(card):
    """The effect out of an existing card: the picture
    region, then cropped to where its light is."""
    from . import pcf_preview
    im = Image.open(card).convert("RGB")
    w, h = im.size
    x0, y0, x1, y1 = CARD_PICTURE
    region = im.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
    return pcf_preview.visible_crop(region, keep=0.95, margin=0.04)


# ── desktop.ini (carried from Ico Studio V5, unchanged in behaviour) ─────────

def icon_assignment(folder):
    """None when the folder has no icon set; else {'valid', 'reference', 'path', 'reason'}."""
    ini = os.path.join(folder, "desktop.ini")
    if not os.path.isfile(ini):
        return None
    raw = open(ini, "rb").read()
    enc = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    try:
        body = raw.decode(enc)
    except UnicodeError:
        body = raw.decode("mbcs" if os.name == "nt" else "latin1")
    parser = configparser.RawConfigParser(strict=False)
    parser.optionxform = str
    try:
        parser.read_string(body)
    except configparser.Error:
        return {"valid": False, "reason": "Unreadable desktop.ini"}
    section = next((s for s in parser.sections() if s.casefold() == ".shellclassinfo"), None)
    if not section:
        return None
    opts = {k.casefold(): v for k, v in parser.items(section)}
    reference = opts.get("iconresource") or opts.get("iconfile")
    if not reference:
        return None
    reference = re.sub(r",\s*-?\d+\s*$", "", reference).strip().strip('"')
    target = os.path.expandvars(reference)
    if not os.path.isabs(target):
        target = os.path.join(folder, target)
    return {"valid": os.path.isfile(target), "reference": reference, "path": target,
            "reason": "Assigned icon" if os.path.isfile(target) else "Missing assigned icon file"}


def _kernel():
    import ctypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
    kernel.GetFileAttributesW.restype = ctypes.c_uint32
    kernel.SetFileAttributesW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32]
    kernel.SetFileAttributesW.restype = ctypes.c_int

    def attrs(p):
        result = kernel.GetFileAttributesW(str(p))
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result

    def setattrs(p, v):
        if not kernel.SetFileAttributesW(str(p), v):
            raise ctypes.WinError(ctypes.get_last_error())
    return attrs, setattrs


def _notify(folder):
    import ctypes
    shell = ctypes.WinDLL("shell32")
    shell.SHChangeNotify(0x00002000, 0x0005, ctypes.c_wchar_p(str(folder)), None)
    shell.SHChangeNotify(0x00001000, 0x0005, ctypes.c_wchar_p(str(os.path.dirname(folder))), None)


def assign_folder_icon(folder, icon, backup_dir):
    """Point the folder's desktop.ini at `icon`. The folder's attributes and
    the old desktop.ini bytes (or its absence) go to a backup JSON first.
    -> the backup path (what restore_folder_icon needs)."""
    if os.name != "nt":
        raise ValueError("Assigning folder icons requires Windows.")
    attrs, setattrs = _kernel()
    folder, icon = os.path.abspath(folder), os.path.abspath(icon)
    ini = os.path.join(folder, "desktop.ini")
    old_folder_attrs = attrs(folder)
    old_ini_attrs = attrs(ini) if os.path.exists(ini) else None
    old = open(ini, "rb").read() if os.path.exists(ini) else None
    os.makedirs(backup_dir, exist_ok=True)
    backup = os.path.join(backup_dir, hashlib.sha256(folder.encode()).hexdigest()[:16] + ".json")
    with open(backup, "w", encoding="utf-8") as f:
        json.dump({"folder": folder, "icon": icon, "folder_attributes": old_folder_attrs,
                   "ini_attributes": old_ini_attrs,
                   "desktop_ini_base64": base64.b64encode(old).decode() if old is not None else None}, f, indent=2)
    body = ""
    if old is not None:
        enc = "utf-16" if old.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        try:
            body = old.decode(enc)
        except UnicodeError:
            body = old.decode("mbcs")
    out, inside, found = [], False, False
    for line in body.splitlines():
        if re.match(r"^\s*\[.*\]\s*$", line):
            inside = line.strip().casefold() == "[.shellclassinfo]"
            out.append(line)
            if inside:
                out.append("IconResource=" + icon + ",0")
                found = True
        elif inside and re.match(r"^\s*(IconResource|IconFile|IconIndex)\s*=", line, re.I):
            continue
        else:
            out.append(line)
    if not found:
        out.extend(["", "[.ShellClassInfo]", "IconResource=" + icon + ",0"])
    try:
        if old_ini_attrs is not None:
            setattrs(ini, (old_ini_attrs & ~7) or 128)
        with open(ini, "w", encoding="utf-16", newline="") as f:
            f.write("\r\n".join(out) + "\r\n")
        setattrs(ini, ((old_ini_attrs or 0) | 2 | 4) & ~1)
        setattrs(folder, old_folder_attrs | 1)
        _notify(folder)
    except Exception:
        if os.path.exists(ini):
            setattrs(ini, (attrs(ini) & ~7) or 128)
        if old is None:
            os.remove(ini)
        else:
            with open(ini, "wb") as f:
                f.write(old)
            setattrs(ini, old_ini_attrs)
        setattrs(folder, old_folder_attrs)
        raise
    return backup


def restore_folder_icon(backup_json):
    """Undo assign_folder_icon from its backup: the old desktop.ini bytes and
    attributes come back (or the desktop.ini it created goes again)."""
    attrs, setattrs = _kernel()
    with open(backup_json, encoding="utf-8") as f:
        b = json.load(f)
    folder = b["folder"]
    ini = os.path.join(folder, "desktop.ini")
    if os.path.exists(ini):
        setattrs(ini, (attrs(ini) & ~7) or 128)
    if b.get("desktop_ini_base64") is None:
        if os.path.exists(ini):
            os.remove(ini)
    else:
        with open(ini, "wb") as f:
            f.write(base64.b64decode(b["desktop_ini_base64"]))
        if b.get("ini_attributes") is not None:
            setattrs(ini, b["ini_attributes"])
    setattrs(folder, b["folder_attributes"])
    _notify(folder)
    return folder


# ── PROCESS ENTIRE FOLDER: one icon per pack ─────────────────────────────────

def _inside(path, folder):
    a, b = os.path.normcase(os.path.abspath(path)), os.path.normcase(os.path.abspath(folder))
    return a.startswith(b.rstrip("\\/") + os.sep)


def _walk(folder, exclude):
    from . import pcf_preview
    for dp, dn, fn in os.walk(folder):
        dn[:] = sorted((d for d in dn if not pcf_preview.excluded(d, exclude)), key=str.lower)
        yield dp, fn


def make_folder_icons(root, results, icon_dir, colours=None, exclude=None, apply_bare=True,
                      apply_all=False, log=print):
    """One orb icon per folder DIRECTLY under `root` (the depth cap). Its face
    is the folder's best render from this run (most light, colour helps),
    else one of the folder's existing cards. Applied to the folder only when
    it has no icon yet (`apply_bare`), or always with `apply_all` (backed up).
    -> [report rows]."""
    from . import pcf_preview
    exclude = pcf_preview.DEFAULT_EXCLUDE if exclude is None else exclude
    os.makedirs(icon_dir, exist_ok=True)
    backups = os.path.join(icon_dir, "_backups")
    report = []
    for name in sorted(os.listdir(root), key=str.lower):
        folder = os.path.join(root, name)
        if not os.path.isdir(folder) or pcf_preview.excluded(name, exclude):
            continue
        row = {"folder": folder, "icon": None, "applied": False, "note": ""}
        pcfs, cards = 0, []
        for dp, fn in _walk(folder, exclude):
            for f in fn:
                low = f.lower()
                if low.endswith(".pcf"):
                    pcfs += 1
                elif re.search(r"\(preview\)( v\d+)?\.(png|jpe?g|webp)$", low):
                    cards.append(os.path.join(dp, f))
        if not pcfs:
            row["note"] = "no .pcf inside - no icon"
            report.append(row)
            continue
        mine = [r for r in results if r.get("face") and os.path.exists(r["face"]) and _inside(r["pcf"], folder)]
        face = None
        if mine:
            best = max(mine, key=lambda r: face_score(r["face"], r.get("strength")))
            face, row["face_from"] = Image.open(best["face"]), best["pcf"]
        elif cards:
            scored = []
            for pick in sorted(cards, key=str.lower):
                try:
                    f = face_from_card(pick)
                    scored.append((face_score(f), pick, f))
                except Exception as exc:
                    row["note"] = f"could not read {pick}: {exc}"
            if scored:
                _s, pick, face = max(scored, key=lambda t: t[0])
                row["face_from"] = pick
        if face is None:
            row["note"] = row["note"] or "nothing to show (no render and no card)"
            report.append(row)
            continue
        rim = colours.get(name) if colours is not None else None
        path = ico_path(icon_dir, name)
        save_ico(orb_icon(face, rim_rgb=rim), path)
        row["icon"] = path
        assignment = icon_assignment(folder)
        row["had_icon"] = assignment
        if apply_all or (apply_bare and assignment is None):
            try:
                row["backup"] = assign_folder_icon(folder, path, backups)
                row["applied"] = True
            except Exception as exc:
                row["note"] = f"icon written, not applied: {exc}"
        else:
            row["note"] = "icon written; the folder keeps its current icon"
        log(f"[HT_PREVIEW]  icon {os.path.basename(path)}"
            + ("  -> applied to the folder" if row["applied"] else f"  ({row['note']})"))
        report.append(row)
    if colours is not None:
        colours.save()
    return report
