
import colorsys
import hashlib
import json
import os
import random
import re
import shutil
import time

#3.0.1 ENSURE PIL: a missing or broken Pillow no longer stops the whole add-on loading (this module is imported
#when the add-on registers). The names stay None until need_pil() finds - or installs - a Pillow that works
try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
except Exception:                                             # missing, or built for another Python
    Image = ImageChops = ImageDraw = ImageFilter = ImageFont = None


def need_pil(install=True, log=print):
    """(works, message): Pillow ready for the cards - installed or repaired first when it is missing or broken
    (tools/pil_ensure.py), then bound here and in pcf_icons. Never raises."""
    global Image, ImageChops, ImageDraw, ImageFilter, ImageFont
    if Image is not None:
        return True, ""
    from . import pil_ensure
    ok, msg = pil_ensure.ensure(install=install, log=log)
    if not ok:
        return False, msg
    try:
        from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
        from . import pcf_icons
        pcf_icons.bind_pil()
    except Exception as exc:
        return False, "Pillow installed but not loaded: %s: %s" % (type(exc).__name__, exc)
    return True, msg


def _require_pil():
    """need_pil(), raising when Pillow cannot be had - for the functions that draw."""
    ok, msg = need_pil()
    if not ok:
        raise RuntimeError("PCF Preview needs Pillow (PIL): " + msg)


CARD = 2048
WINFONTS = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
FONT_FILES = ("bahnschrift.ttf", "segoeui.ttf", "arial.ttf")
ACRONYMS = {"hd", "sd", "hdr", "4k", "8k", "vr", "fx", "sfx", "vfx", "hl2", "tf2",
            "sfm", "lod", "ui", "cp", "dx", "fps", "lcm"}
#0.26.3: words with their own capitals ("(hoovytube)" -> "(HoovyTube)")
BRANDS = {"hoovytube": "HoovyTube", "skibidipack": "SkibidiPack"}

INK = (244, 229, 198)          # the cream of the titles, description and path
INK_DIM = (178, 182, 190)      # the second title on a neutral chip
FRAME = (234, 214, 178)        # the thin outer border w/o a folder colour
STEEL = ((86, 91, 103), (38, 41, 49))      #the neutral plate (a grey effect)

CARD_EXTS = (".png", ".jpg", ".jpeg", ".webp")
JPG_QUALITY = 92
SETTINGS_SUFFIX = " (preview settings).json"
COLORS_FILE = "_preview colors.json"
DEFAULT_ICON_DIR = r"C:\Icons\SFM\Particles"
DEFAULT_EXCLUDE = ("___Developer___", "__Developer__")

# what the button / a folder run / a settings file can choose. None or "auto"
# = let the automation decide.
STYLE_KEYS = ("title", "subtitle", "description", "title_color", "folder_color", "format",
              "bars", "bar_alpha")
JOB_KEYS = ("moment", "system", "grid", "view_yaw", "view_pitch", "zoom", "cp0_yaw", "res",
            "max_particles")
DEFAULT_STYLE = {"title": None, "subtitle": None, "description": None,
                 "title_color": "auto", "folder_color": "auto", "format": "png",
                 "bars": "glass", "bar_alpha": None}
FONT_VARIATION = "SemiCondensed"


# ── the name -> titles ───────────────────────────────────────────────────────

def _title_case(text):
    out = []
    for part in re.split(r"(\s+|-|_)", text):
        if not part.strip() or part in ("-", "_"):
            out.append(part)
            continue
        # brackets stay where they are; the word inside them is what gets cased
        lead, core, trail = re.match(r"^([(\[]*)(.*?)([)\]]*)$", part).groups()
        low = core.lower()
        if not core:
            out.append(part)
        elif low in ACRONYMS:
            out.append(lead + core.upper() + trail)
        elif low in BRANDS:
            out.append(lead + BRANDS[low] + trail)
        elif core[0].isdigit():
            out.append(part)
        else:
            out.append(lead + core[0].upper() + core[1:] + trail)
    return "".join(out)


def card_stem(pcf_path):
    """The card's name stem: the .pcf's, minus a variant letter trailing the
    brackets ("thruster downwash loop (hd) a" -> "thruster downwash loop (hd)")."""
    stem = os.path.splitext(os.path.basename(pcf_path))[0].strip()
    return re.sub(r"\)\s+[A-Za-z]$", ")", stem)


def titles_from_name(pcf_path):
    """-> (main title, second title or None), read off the file name."""
    stem = card_stem(pcf_path)
    m = re.search(r"\(([^()]*)\)", stem)
    if m:
        main, sub = stem[:m.start()], "(" + _title_case(m.group(1).strip()) + ")"
        # 0.26.3: a name that STARTS with its bracket ("(add) - industrial
        # sparks flashing smoke") has its title after it - before, the card
        # showed the raw file name
        if not main.strip().strip("_- "):
            main = stem[m.end():]
    else:
        main, sub = stem, None
    main = main.strip().strip("_- ").strip()
    return _title_case(main) or stem, sub


def pack_paths(pcf_path):
    """-> (pack folder, the folder below it or None): the folders under
    `particles\\`. Outside a particles tree, the .pcf's own folder."""
    parts = os.path.normpath(os.path.abspath(pcf_path)).split(os.sep)
    low = [p.lower() for p in parts]
    if "particles" in low:
        i = len(low) - 1 - low[::-1].index("particles")
        folders = parts[i + 1:-1]
        if folders:
            return folders[0], (folders[1] if len(folders) > 1 else None)
    return (parts[-2] if len(parts) > 1 else ""), None


def card_path(pcf_path, versioned=True, fmt="png"):
    """`<name> (preview).<fmt>` beside the .pcf; if taken and versioned, the
    first free " v2", " v3" ... - a card is never written over. Unversioned
    returns the plain name whether or not it exists (the caller checks)."""
    ext = "." + str(fmt or "png").lower().lstrip(".")
    base = os.path.join(os.path.dirname(os.path.abspath(pcf_path)),
                        card_stem(pcf_path) + " (preview)")
    if not versioned or not os.path.exists(base + ext):
        return base + ext
    n = 2
    while os.path.exists(f"{base} v{n}{ext}"):
        n += 1
    return f"{base} v{n}{ext}"


def existing_card(pcf_path):
    """the user's card for this .pcf, if one exists (.png / .jpg / .webp)."""
    base = os.path.join(os.path.dirname(os.path.abspath(pcf_path)),
                        card_stem(pcf_path) + " (preview)")
    for ext in CARD_EXTS:
        if os.path.exists(base + ext):
            return base + ext
    return None


def settings_path(pcf_path):
    """The per-effect override file: `<name> (preview settings).json` beside the .pcf."""
    return os.path.join(os.path.dirname(os.path.abspath(pcf_path)), card_stem(pcf_path) + SETTINGS_SUFFIX)


def load_overrides(pcf_path):
    """{key: value} from the effect's settings file, or {} - a broken file is reported, never fatal."""
    p = settings_path(pcf_path)
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8-sig") as f:
            data = json.load(f)
        return {k: v for k, v in data.items() if k in STYLE_KEYS + JOB_KEYS and v not in (None, "")}
    except (OSError, ValueError) as exc:
        print(f"[HT_PREVIEW]  ignoring {p}: {exc}")
        return {}


# ── colour ───────────────────────────────────────────────────────────────────

def hex_rgb(value):
    v = str(value).strip().lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", v):
        raise ValueError(f"not a #rrggbb colour: {value!r}")
    return tuple(int(v[i:i + 2], 16) for i in (0, 2, 4))


def rgb_hex(rgb):
    return "#%02x%02x%02x" % tuple(int(round(c)) for c in rgb[:3])


def hsv_rgb(h, s, v):
    return tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(h % 1.0, max(0, min(1, s)), max(0, min(1, v))))


def shade(rgb, s=None, v=None, s_mul=None):
    """The same hue at another saturation / brightness (0..1 each)."""
    h, s0, v0 = colorsys.rgb_to_hsv(*(c / 255.0 for c in rgb[:3]))
    if s_mul is not None:
        s0 *= s_mul
    return hsv_rgb(h, s0 if s is None else s, v0 if v is None else v)


def dominant_colour(render, min_strength=0.12):
    """The effect's own colour: (rgb, info) or (None, info) for a grey effect.

    Every lit pixel votes for its hue, weighted by brightness squared and by how
    saturated it is - so the glowing core of a fireball outvotes the dim smoke
    around it, and a white-hot centre (no hue) votes for nothing. The winning
    10-degree bin is refined to the weighted mean hue around it. Below
    `min_strength` (the share of light that is coloured at all) the effect is
    called grey and keeps the neutral plates."""
    _require_pil()                                             # 3.0.1 ensure pil
    import numpy as np
    im = render.convert("RGB") if hasattr(render, "convert") else Image.open(render).convert("RGB")
    im.thumbnail((256, 256))
    a = np.asarray(im, dtype=np.float32) / 255.0
    mx, mn = a.max(axis=2), a.min(axis=2)
    d = np.maximum(mx - mn, 1e-6)
    s = np.where(mx > 1e-6, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    h = np.where(mx == r, ((g - b) / d) % 6.0, np.where(mx == g, (b - r) / d + 2.0, (r - g) / d + 4.0)) / 6.0
    w_all = (mx ** 2) * (mx > 0.08)
    w = w_all * np.clip((s - 0.15) / 0.35, 0.0, 1.0)
    total = float(w_all.sum())
    if total <= 0:
        return None, {"strength": 0.0}
    strength = float(w.sum() / total)
    if strength < min_strength:
        return None, {"strength": round(strength, 3)}
    bins = 36
    idx = np.minimum((h * bins).astype(int), bins - 1)
    hist = np.bincount(idx.ravel(), weights=w.ravel(), minlength=bins)
    smooth = hist + 0.5 * (np.roll(hist, 1) + np.roll(hist, -1))
    centre = (int(np.argmax(smooth)) + 0.5) / bins
    dh = ((h - centre + 0.5) % 1.0) - 0.5
    near = w * (np.abs(dh) < 1.5 / bins)
    hue = (centre + float((dh * near).sum() / max(float(near.sum()), 1e-9))) % 1.0
    sat = float((s * near).sum() / max(float(near.sum()), 1e-9))
    rgb = hsv_rgb(hue, 0.55 + 0.35 * min(1.0, sat), 0.82)
    return rgb, {"strength": round(strength, 3), "hue": round(hue * 360.0, 1), "sat": round(sat, 3)}


FOLDER_RULES = (
    (("titan", "nuke", "nukes", "bomb", "bombs", "explosion", "explosions", "explode", "blast"), 24, 0.85),
    (("fire", "flame", "flames", "burn", "inferno", "lava"), 16, 0.88),
    (("spark", "sparks", "ember", "embers"), 42, 0.88),
    (("bullet", "bullets", "impact", "impacts", "weapon", "weapons", "gun", "guns"), 48, 0.68),
    (("artillery", "military"), 72, 0.55),
    (("demolish", "destruction", "debris", "rubble"), 12, 0.62),
    (("electricity", "electric", "lightning", "zeus", "thunder", "arc", "arcs", "plasma"), 192, 0.85),
    (("water", "rain", "splash", "liquid", "ocean"), 212, 0.80),
    (("wind", "air", "gust", "gusts"), 170, 0.62),
    (("downwash", "downwashes"), 34, 0.52),
    (("smoke", "dust", "fog", "mist", "steam"), 218, 0.32),
    (("environment", "nature", "weather"), 128, 0.58),
    (("magic", "aura", "arcane", "spell", "spells"), 282, 0.72),
    (("scifi", "space"), 256, 0.72),
    (("thruster", "thrusters", "jet", "jets", "engine"), 202, 0.68),
    (("beam", "beams"), 300, 0.72),
    (("laser", "lasers"), 350, 0.80),
    (("warp", "warps", "portal", "portals"), 240, 0.72),
    (("skibidi",), 325, 0.66),
    (("tf2", "fortress"), 4, 0.80),
    (("premium", "gold"), 46, 0.80),
    (("cinematic", "movie", "film"), 40, 0.74),
    (("physics",), 30, 0.60),
    (("action",), 8, 0.70),
)


def _words(text):
    t = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(text))
    return [w for w in re.split(r"[^a-z0-9]+", t.lower()) if w]


def auto_folder_colour(name, taken=()):
    """-> rgb for a pack folder: its rule's hue. Two packs of one family (fire,
    explosions, titan impacts are all orange) stay in that family - a twin is
    told apart by a small hue step or a lighter / darker shade, never pushed
    into another colour. `taken` = [(hue degrees, value 0..1)] already used."""
    stripped = re.sub(r"(?i)^[_\s]*hoovy\s*tube[_\s-]*", "", str(name)).strip(" _-")
    segments = [s for s in re.split(r"\s+-\s+|_+", stripped) if s.strip()] or [stripped]
    hue = sat = None
    for seg in reversed(segments):
        words = set(_words(seg))
        for rule_words, h, s in FOLDER_RULES:
            if words.intersection(rule_words):
                hue, sat = h, s
                break
        if hue is not None:
            break
    if hue is None:
        seed = int(hashlib.sha256(str(name).lower().encode("utf-8")).hexdigest()[:8], 16)
        hue, sat = (seed * 137.508) % 360.0, 0.62
    for dh, v in ((0, 0.80), (7, 0.80), (-7, 0.80), (0, 0.66), (0, 0.92), (7, 0.66), (-7, 0.92),
                  (14, 0.80), (-14, 0.80), (14, 0.66), (-14, 0.92)):
        h2 = (hue + dh) % 360.0
        if all(not (min(abs(h2 - th), 360 - abs(h2 - th)) < 4.5 and abs(v - tv) < 0.07) for th, tv in taken):
            return hsv_rgb(h2 / 360.0, sat, v)
    return hsv_rgb(hue / 360.0, sat, 0.80)


class FolderColours:
    """The designated colour of every pack folder, kept in `_preview colors.json`.

    An entry is written ONCE, the first time a folder is seen, and read back
    every run after - so a pack's colour never wanders, and an edited value
    (any "#rrggbb") is respected. Nothing else in the file is ever changed."""

    def __init__(self, path=None):
        self.path = path
        self.map = {}
        self.added = []
        if path and os.path.isfile(path):
            try:
                with open(path, encoding="utf-8-sig") as f:
                    self.map = {str(k): str(v) for k, v in json.load(f).items()}
            except (OSError, ValueError) as exc:
                print(f"[HT_PREVIEW]  {path} unreadable ({exc}) - using automatic colours, not saving")
                self.path = None

    def _taken(self):
        out = []
        for v in self.map.values():
            try:
                h, _s, val = colorsys.rgb_to_hsv(*(c / 255.0 for c in hex_rgb(v)))
                out.append((h * 360.0, val))
            except ValueError:
                pass
        return out

    def get(self, folder_name):
        if not folder_name:
            return None
        if folder_name in self.map:
            try:
                return hex_rgb(self.map[folder_name])
            except ValueError:
                return auto_folder_colour(folder_name)
        rgb = auto_folder_colour(folder_name, self._taken())
        self.map[folder_name] = rgb_hex(rgb)
        self.added.append(folder_name)
        return rgb

    def save(self):
        if not self.path or not self.added:
            return None
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(dict(sorted(self.map.items(), key=lambda kv: kv[0].lower())), f, indent=1)
        os.replace(tmp, self.path)
        self.added = []
        return self.path


def resolve_colours(style, render, folder_name, colours=None):
    """-> (title rgb or None, folder rgb or None, info) from the style's choices:
    title_color "auto" (the effect's hue) / "folder" / "neutral" / "#rrggbb";
    folder_color "auto" (designated) / "neutral" / "#rrggbb"."""
    info = {}
    fc = str(style.get("folder_color") or "auto").strip().lower()
    if fc == "auto":
        folder = colours.get(folder_name) if colours is not None else (
            auto_folder_colour(folder_name) if folder_name else None)
    elif fc in ("neutral", "none", "off"):
        folder = None
    else:
        folder = hex_rgb(fc)
    tc = str(style.get("title_color") or "auto").strip().lower()
    if tc == "auto":
        title, info = dominant_colour(render) if render is not None else (None, {})
    elif tc == "folder":
        title = folder
    elif tc in ("neutral", "none", "off"):
        title = None
    else:
        title = hex_rgb(tc)
    return title, folder, info


# ── drawing ──────────────────────────────────────────────────────────────────

def _font(size, variation=None):
    variation = variation or FONT_VARIATION
    for name in FONT_FILES:
        path = os.path.join(WINFONTS, name)
        if not os.path.exists(path):
            continue
        try:
            f = ImageFont.truetype(path, int(size))
            if name == "bahnschrift.ttf":
                try:
                    f.set_variation_by_name(variation)
                except Exception:
                    pass
            return f
        except Exception:
            continue
    return ImageFont.load_default()


def _plate(img, box, top=STEEL[0], bottom=STEEL[1], alpha=235, fade=0, seed=1,
           edge_light=(150, 158, 175, 170), edge_dark=(10, 11, 14, 220)):
    """A metal plate: vertical gradient, faint brushed grain, a light top edge
    and a dark bottom edge; `fade` dissolves the left and right ends."""
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    rng = random.Random(seed)
    column = Image.new("RGBA", (1, h))
    px = column.load()
    for y in range(h):
        t = y / max(1, h - 1)
        grain = rng.uniform(-4.0, 4.0)
        c = tuple(int(max(0, min(255, top[i] + (bottom[i] - top[i]) * t + grain)))
                  for i in range(3))
        px[0, y] = c + (alpha,)
    plate = column.resize((w, h), Image.NEAREST)
    d = ImageDraw.Draw(plate)
    lw = max(2, h // 60)
    d.line([(0, lw // 2), (w, lw // 2)], fill=edge_light, width=lw)
    d.line([(0, h - 1 - lw // 2), (w, h - 1 - lw // 2)], fill=edge_dark, width=lw)
    if fade > 0:
        ramp = Image.new("L", (w, h), 255)
        rd = ImageDraw.Draw(ramp)
        f = min(fade, w // 2)
        for x in range(f):
            v = int(255 * (0.35 + 0.65 * (x / f)))
            rd.line([(x, 0), (x, h)], fill=v)
            rd.line([(w - 1 - x, 0), (w - 1 - x, h)], fill=v)
        plate.putalpha(ImageChops.multiply(plate.getchannel("A"), ramp))
    img.alpha_composite(plate, (x0, y0))


def _coloured_plate(img, box, rgb, alpha=235, fade=0, seed=1, dark=False):
    """A plate in a colour: the band (bright, like the user's title bars), or
    with `dark` a near-black chip that only carries the colour in its edges."""
    if dark:
        top, bottom = shade(rgb, v=0.24, s_mul=0.85), shade(rgb, v=0.07, s_mul=0.6)
        light = shade(rgb, s_mul=0.75, v=0.95) + (190,)
        lower = shade(rgb, s_mul=0.75, v=0.70) + (170,)
    else:
        x0, y0, x1, y1 = (int(v) for v in box)
        pad = max(4, (y1 - y0) // 4)
        halo = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(halo).rectangle([x0, y0 - pad // 3, x1, y1 + pad // 3], fill=shade(rgb, v=0.95) + (120,))
        img.alpha_composite(halo.filter(ImageFilter.GaussianBlur(pad)))
        top, bottom = shade(rgb, v=0.88), shade(rgb, v=0.56)
        light = shade(rgb, s_mul=0.45, v=1.0) + (235,)
        lower = shade(rgb, s_mul=0.6, v=1.0) + (200,)
    _plate(img, box, top, bottom, alpha, fade, seed, edge_light=light, edge_dark=lower)


def _text(img, xy_center, text, font, fill, glow=None, shadow=True):
    """Centred text with a soft glow and a drop shadow."""
    d = ImageDraw.Draw(img)
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    w, h = r - l, b - t
    x = int(xy_center[0] - w / 2 - l)
    y = int(xy_center[1] - h / 2 - t)
    if glow:
        lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(lay).text((x, y), text, font=font, fill=glow)
        lay = lay.filter(ImageFilter.GaussianBlur(max(2, font.size // 10)))
        img.alpha_composite(lay)
    if shadow:
        lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        off = max(2, font.size // 40)
        ImageDraw.Draw(lay).text((x + off, y + off), text, font=font, fill=(0, 0, 0, 170))
        img.alpha_composite(lay.filter(ImageFilter.GaussianBlur(max(1, off))))
    lay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(lay).text((x, y), text, font=font, fill=tuple(fill[:3]) + (255,))
    img.alpha_composite(lay)
    return w, h


_MEASURE = None


def _measure():
    """A scratch surface to measure text on - made on first use. 3.0.1 ENSURE PIL: made at import, it needed Pillow
    before the add-on had even loaded, so a missing or broken Pillow took the whole add-on down with it."""
    global _MEASURE
    if _MEASURE is None:
        _MEASURE = ImageDraw.Draw(Image.new("L", (8, 8)))
    return _MEASURE


def _fit(text, size, min_size, width):
    """The biggest font from `size` down to `min_size` that keeps `text` within
    `width` - or None when even `min_size` is too wide (0.26.1: 157 of the
    library's titles ran off the card at the one fixed size)."""
    s = int(size)
    while True:
        f = _font(s)
        if _measure().textlength(text, font=f) <= width:
            return f
        if s <= int(min_size):
            return None
        s = max(int(min_size), int(s * 0.95))


def _split_two(text):
    """Two lines, cut at the space / underscore / dash nearest the middle."""
    mid = len(text) / 2.0
    cuts = [i for i, ch in enumerate(text) if ch in " _-"]
    if not cuts:
        i = max(1, int(mid))
        return text[:i], text[i:]
    i = min(cuts, key=lambda c: abs(c - mid))
    return (text[:i].rstrip(" _-") or text[:i]), (text[i + 1:].lstrip(" _-") or text[i + 1:])


def _wrap(text, font, width, max_lines=3):
    d = ImageDraw.Draw(Image.new("L", (8, 8)))
    lines = []
    for para in str(text).splitlines() or [""]:
        cur = ""
        for word in para.split():
            trial = (cur + " " + word).strip()
            if d.textlength(trial, font=font) <= width or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    lines = [ln for ln in lines if ln.strip()]
    return lines[:max_lines]


def visible_crop(render, keep=0.985, margin=0.08, ref=None):
    """The render cropped to where its LIGHT is, plus a margin - the card shows
    the effect, not the black around it. The box holds `keep` of the total
    light, so a few faint stray specks far out do not shrink the effect.
    `ref` (same size): measure the light there instead - the effect without
    the ground grid, so the grid never decides the crop."""
    rgb = render.convert("RGB")
    src = (ref if ref is not None and ref.size == rgb.size else rgb).convert("RGB")
    try:
        import numpy as np
        lum = np.asarray(src.convert("L"), dtype=np.float64)
        lum[lum < 4] = 0.0
        total = lum.sum()
        if total <= 0:
            return rgb
        cut = (1.0 - keep) / 2.0

        def span(profile):
            c = np.cumsum(profile) / total
            return int(np.searchsorted(c, cut)), int(np.searchsorted(c, 1.0 - cut)) + 1

        x0, x1 = span(lum.sum(axis=0))
        y0, y1 = span(lum.sum(axis=1))
    except ImportError:
        box = src.convert("L").point(lambda v: 255 if v > 6 else 0).getbbox()
        if not box:
            return rgb
        x0, y0, x1, y1 = box
    side = max(x1 - x0, y1 - y0, 8)
    half = side / 2 * (1.0 + 2 * margin)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return rgb.crop((int(cx - half), int(cy - half), int(cx + half), int(cy + half)))


def light_score(render):
    """Mean luminance 0..1 of a render - how much effect there is to look at."""
    _require_pil()                                             # 3.0.1 ensure pil
    im = render.convert("L") if hasattr(render, "convert") else Image.open(render).convert("L")
    im.thumbnail((256, 256))
    hist = im.histogram()
    n = max(1, sum(hist))
    return sum(i * c for i, c in enumerate(hist)) / (255.0 * n)


GLASS_ALPHA = 0.70
GLASS_NEUTRAL = (126, 134, 150)      # the bar colour with no colour (a grey effect, neutral)


def _smooth(t):
    import numpy as np
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _ramp(w, fade, floor):
    """Alpha across a bar: `floor` at both ends, 1 once `fade` px in."""
    import numpy as np
    x = np.arange(w, dtype=np.float32)
    d = np.minimum(x, w - 1 - x)
    if fade <= 0:
        return np.ones(w, np.float32)
    return floor + (1.0 - floor) * _smooth(d / float(fade))


def _rgba(rgb_arr, a_arr, seed=7):
    """float RGB (h, w, 3) 0..255 + alpha (h, w) 0..1 -> RGBA image, dithered
    by half a level so a gradient never bands in a JPG."""
    import numpy as np
    h, w = a_arr.shape
    noise = np.random.default_rng(seed).random((h, w, 1), dtype=np.float32) - 0.5
    rgb = np.clip(rgb_arr + noise, 0, 255).astype(np.uint8)
    a = np.clip(a_arr * 255.0 + noise[:, :, 0], 0, 255).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, a]), "RGBA")


def _glow_layer(size, paint, rgba, radius):
    """A soft glow: paint(draw, fill) draws the shape; the colour is the glow
    colour EVERYWHERE and only the alpha is blurred (no grey fringe)."""
    rgb = tuple(rgba[:3])
    lay = Image.new("RGBA", size, rgb + (0,))
    paint(ImageDraw.Draw(lay), rgb + (int(rgba[3]) if len(rgba) > 3 else 255,))
    out = Image.new("RGBA", size, rgb + (0,))
    out.putalpha(lay.getchannel("A").filter(ImageFilter.GaussianBlur(radius)))
    return out


def _glass_bar(img, box, rgb, alpha=GLASS_ALPHA, fade=0, dark=False, frost=0, edge_w=3, halo=True):
    """A translucent bar on `img` (RGBA, changed in place): the picture behind
    frosted, a tint in `rgb` lit from behind and faintly brushed, a sheen on
    top, bright edges top and bottom fading toward the ends, a soft halo.
    `dark` = the near-black chip that carries its colour in the edges."""
    import numpy as np
    x0, y0, x1, y1 = (int(v) for v in box)
    w, h = max(1, x1 - x0), max(1, y1 - y0)
    rgb = tuple(rgb or GLASS_NEUTRAL)
    ramp = _ramp(w, fade, 0.55)[None, :]
    edge_ramp = _ramp(w, int(fade * 1.6) if fade else 0, 0.25)[None, :]
    pad = max(10, h // 2)
    if halo:
        blur = pad * 0.5
        m = int(pad // 3 + 3 * blur) + 2
        hl = Image.new("RGBA", (w, h + 2 * m), shade(rgb, v=1.0) + (0,))
        ha = np.zeros((h + 2 * m, w), np.float32)
        ha[m - pad // 3:m + h + pad // 3, :] = 0.14 if dark else 0.26
        ha *= edge_ramp
        hl.putalpha(Image.fromarray((ha * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(blur)))
        top = y0 - m
        img.alpha_composite(hl, (x0, max(0, top)), (0, max(0, -top)))
    if frost > 0:
        img.paste(img.crop((x0, y0, x1, y1)).filter(ImageFilter.GaussianBlur(frost)), (x0, y0))
    yy = np.linspace(0.0, 1.0, h, dtype=np.float32)[:, None]
    xx = np.linspace(-1.0, 1.0, w, dtype=np.float32)[None, :]
    bell = (0.58 + 0.42 * np.exp(-(xx / 0.55) ** 2))[:, :, None]          # lit from behind
    rows = 1.0 + (np.random.default_rng(11).random((h, 1, 1), dtype=np.float32) - 0.5) * 0.07  # brushed
    if dark:
        top_c, bot_c = shade(rgb, v=0.30, s_mul=0.9), shade(rgb, v=0.07, s_mul=0.7)
        a_top, a_bot = alpha * 1.05, alpha * 1.15
    else:
        top_c, bot_c = shade(rgb, v=0.70, s_mul=0.95), shade(rgb, v=0.30, s_mul=0.95)
        a_top, a_bot = alpha * 0.95, alpha * 1.05
    top_c, bot_c = np.array(top_c, np.float32), np.array(bot_c, np.float32)
    col = (top_c[None, None, :] + (bot_c - top_c)[None, None, :] * yy[:, :, None]) * bell * rows
    sheen = np.array(shade(rgb, v=1.0, s_mul=0.35), np.float32)
    sh = (0.10 if dark else 0.22) * _smooth(1.0 - yy / 0.42)
    col = col + (sheen - col) * sh[:, :, None]
    a = (a_top + (a_bot - a_top) * yy) * ramp
    img.alpha_composite(_rgba(np.broadcast_to(col, (h, w, 3)).copy(), np.clip(a, 0, 1)), (x0, y0))
    ew = max(2, int(edge_w))
    for yline, c, strength in ((y0, shade(rgb, s_mul=0.55, v=1.0), 1.0),
                               (y1 - ew, shade(rgb, s_mul=0.70, v=0.80 if dark else 0.88), 0.85)):
        g = Image.new("RGBA", (w, ew * 9), c + (0,))
        ga = np.zeros((ew * 9, w), np.float32)
        ga[ew * 4:ew * 5, :] = 1.0
        ga = np.asarray(Image.fromarray((ga * 255).astype(np.uint8)).filter(
            ImageFilter.GaussianBlur(ew * 1.6)), np.float32) / 255.0 * 1.9
        g.putalpha(Image.fromarray((np.clip(np.clip(ga, 0, 1) * edge_ramp * 0.55 * strength, 0, 1) * 255
                                    ).astype(np.uint8)))
        img.alpha_composite(g, (x0, max(0, yline - ew * 4)))
        line = (np.zeros((ew, w), np.float32) + 0.95 * strength) * edge_ramp
        img.alpha_composite(_rgba(np.broadcast_to(np.array(c, np.float32), (ew, w, 3)).copy(), line), (x0, yline))


def _glass_text(img, center, text, font, fill, glow=None, shadow=True):
    """Centred text drawn on its own small layer: a wide soft bloom and a tight
    halo (one blur reads as a smudge), a blurred drop shadow, crisp ink."""
    d = ImageDraw.Draw(img)
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    w, h = r - l, b - t
    x = int(round(center[0] - w / 2 - l))
    y = int(round(center[1] - h / 2 - t))
    m = max(12, font.size)
    bx0, by0 = max(0, x + l - m), max(0, y + t - m)
    bx1, by1 = min(img.width, x + r + m), min(img.height, y + b + m)
    size = (bx1 - bx0, by1 - by0)
    ox, oy = x - bx0, y - by0
    if glow:
        ga = glow[3] if len(glow) > 3 else 255
        for rgba, radius in ((tuple(glow[:3]) + (int(ga * 0.55),), max(3, font.size // 4)),
                             (tuple(glow[:3]) + (int(ga),), max(2, font.size // 12))):
            img.alpha_composite(_glow_layer(size, lambda dd, f: dd.text((ox, oy), text, font=font, fill=f),
                                            rgba, radius), (bx0, by0))
    if shadow:
        off = max(2, font.size // 36)
        img.alpha_composite(_glow_layer(size, lambda dd, f: dd.text((ox + off, oy + off), text, font=font,
                                                                    fill=f), (0, 0, 0, 185), max(1, off)),
                            (bx0, by0))
    lay = Image.new("RGBA", size, tuple(fill[:3]) + (0,))
    ImageDraw.Draw(lay).text((ox, oy), text, font=font, fill=tuple(fill[:3]) + (255,))
    img.alpha_composite(lay, (bx0, by0))
    return w, h


def light_box(render, keep=0.985, margin=0.08, ref=None):
    """The square (x0, y0, x1, y1) around where the render's LIGHT is, in its
    own pixels - it may run past the render's edges. visible_crop's box."""
    import numpy as np
    src = (ref if ref is not None and ref.size == render.size else render).convert("L")
    lum = np.asarray(src, dtype=np.float64)
    lum[lum < 4] = 0.0
    total = lum.sum()
    if total <= 0:
        return (0, 0, render.width, render.height)
    cut = (1.0 - keep) / 2.0

    def span(profile):
        c = np.cumsum(profile) / total
        return int(np.searchsorted(c, cut)), int(np.searchsorted(c, 1.0 - cut)) + 1

    x0, x1 = span(lum.sum(axis=0))
    y0, y1 = span(lum.sum(axis=1))
    side = max(x1 - x0, y1 - y0, 8)
    half = side / 2 * (1.0 + 2 * margin)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return (cx - half, cy - half, cx + half, cy + half)


def _place_picture(card, render, region, ref=None, feather=0.06):
    """The render FULL-BLEED: scaled so its light box fills `region`, the rest
    of it carrying on under the bars to the card's edge. Only the part that
    lands on the card is resized; the render's own border is feathered."""
    import numpy as np
    render = render.convert("RGB")
    bx0, by0, bx1, by1 = light_box(render, ref=ref)
    rx0, ry0, rx1, ry1 = region
    k = min((rx1 - rx0) / (bx1 - bx0), (ry1 - ry0) / (by1 - by0))
    ox = (rx0 + rx1) / 2 - (bx0 + bx1) / 2 * k
    oy = (ry0 + ry1) / 2 - (by0 + by1) / 2 * k
    W, H = card.size
    sx0, sy0 = max(0.0, -ox / k), max(0.0, -oy / k)
    sx1, sy1 = min(render.width, (W - ox) / k), min(render.height, (H - oy) / k)
    if sx1 - sx0 < 2 or sy1 - sy0 < 2:
        return
    crop = render.crop((int(sx0), int(sy0), int(np.ceil(sx1)), int(np.ceil(sy1))))
    dx, dy = int(round(ox + int(sx0) * k)), int(round(oy + int(sy0) * k))
    pw, ph = max(1, int(round(crop.width * k))), max(1, int(round(crop.height * k)))
    pic = crop.resize((pw, ph), Image.LANCZOS)
    e = max(4, int(min(render.width, render.height) * k * feather))
    yy, xx = np.mgrid[0:ph, 0:pw].astype(np.float32)
    inside = np.minimum(np.minimum(xx + dx - ox, ox + render.width * k - (xx + dx)),
                        np.minimum(yy + dy - oy, oy + render.height * k - (yy + dy)))
    card.paste(pic, (dx, dy), Image.fromarray((_smooth(inside / e) * 255).astype(np.uint8)))


def _vignette(card, strength=0.62, inner=0.52):
    """Darker toward the card's edges: the effect reads first, the bars sit on
    darker picture."""
    import numpy as np
    W, H = card.size
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt((((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) * 0.85)
    k = 1.0 - strength * _smooth((r - inner) / (1.25 - inner))
    a = np.asarray(card, np.float32).copy()
    a[:, :, :3] *= k[:, :, None]
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), card.mode)


def _compose_glass(render, title, subtitle=None, description=None, path_main=None, path_sub=None,
                   size=CARD, crop_ref=None, title_rgb=None, folder_rgb=None, bar_alpha=None):
    """The 0.26.3 card: the picture full-bleed, glass bars over it."""
    if isinstance(render, str):
        render = Image.open(render)
    if isinstance(crop_ref, str):
        crop_ref = Image.open(crop_ref) if os.path.exists(crop_ref) else None
    S = size / CARD
    alpha = GLASS_ALPHA if bar_alpha in (None, "", "auto") else max(0.0, min(1.0, float(bar_alpha)))

    def s(v):
        return int(round(v * S))

    trgb = tuple(title_rgb) if title_rgb else None
    frgb = tuple(folder_rgb) if folder_rgb else None
    frame = shade(frgb, s_mul=0.45, v=0.95) if frgb else FRAME

    # the bars sit where they always did, so the effect's light lands between them
    title_box = (s(22), s(84), size - s(22), s(270))
    chip_box, f_sub = None, None
    img_top = title_box[3] + s(24)
    if subtitle:
        f_sub = _fit(subtitle, s(112), s(56), size - s(560)) or _font(s(56))
        cw = max(s(680), int(_measure().textlength(subtitle, font=f_sub) + s(400)))
        chip_box = (size // 2 - cw // 2, s(298), size // 2 + cw // 2, s(452))
        img_top = chip_box[3] + s(20)
    foot_h = s(220) if path_sub else s(144)
    foot = (s(22), size - s(82) - foot_h, size - s(22), size - s(82))
    img_bottom = foot[1] - s(40) if path_main else size - s(110)
    desc_box, desc_lines, f_desc = None, [], None
    if description:
        f_desc = _font(s(88))
        desc_lines = _wrap(description, f_desc, s(1500))
        if desc_lines:
            dh = s(70) + s(106) * len(desc_lines)
            desc_box = (s(96), foot[1] - s(44) - dh, size - s(96), foot[1] - s(44))
            img_bottom = desc_box[1] - s(24)

    img = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    _place_picture(img, render, (s(110), img_top, size - s(110), img_bottom), ref=crop_ref)
    img = _vignette(img)

    _glass_bar(img, title_box, trgb, alpha, fade=s(260), frost=s(5), edge_w=s(4))
    tglow = (shade(trgb, s_mul=0.6, v=1.0) if trgb else (240, 196, 130)) + (150,)
    inner = (title_box[2] - title_box[0]) - s(120)
    tcx, tcy = (title_box[0] + title_box[2]) / 2, (title_box[1] + title_box[3]) / 2 + s(4)
    f_title = _fit(title, s(166), s(104), inner)
    if f_title is not None:
        _glass_text(img, (tcx, tcy), title, f_title, INK, glow=tglow)
    else:
        a, b = _split_two(title)
        fa = _fit(a, s(92), s(44), inner) or _font(s(44))
        fb = _fit(b, s(92), s(44), inner) or _font(s(44))
        f2 = fa if fa.size <= fb.size else fb
        half = f2.size * 0.52
        _glass_text(img, (tcx, tcy - half), a, f2, INK, glow=tglow)
        _glass_text(img, (tcx, tcy + half), b, f2, INK, glow=tglow)
    if chip_box:
        _glass_bar(img, chip_box, trgb, min(1.0, alpha + 0.12), fade=s(150), dark=True, frost=s(4),
                   edge_w=s(3))
        if trgb:
            sub_ink, sub_glow = shade(trgb, s_mul=0.38, v=1.0), shade(trgb, s_mul=0.8, v=1.0) + (120,)
        else:
            sub_ink, sub_glow = INK_DIM, (200, 205, 215, 70)
        _glass_text(img, (size / 2, (chip_box[1] + chip_box[3]) / 2 + s(3)), subtitle, f_sub, sub_ink,
                    glow=sub_glow)
    if desc_box:
        _glass_bar(img, desc_box, None, min(1.0, alpha + 0.1), fade=s(180), dark=True, frost=s(4),
                   edge_w=s(2), halo=False)
        y = desc_box[1] + s(35) + s(106) / 2
        for ln in desc_lines:
            _glass_text(img, (size / 2, y), ln, f_desc, INK, glow=(240, 196, 130, 80))
            y += s(106)
    if path_main:
        _glass_bar(img, foot, frgb, alpha, fade=s(260), frost=s(5), edge_w=s(4))
        pglow = (shade(frgb, s_mul=0.6, v=1.0) if frgb else (240, 196, 130)) + (110,)
        sub_path_ink = shade(frgb, s_mul=0.3, v=0.92) if frgb else INK_DIM
        pw = (foot[2] - foot[0]) - s(120)
        f_path = _fit(path_main, s(86), s(48), pw) or _font(s(48))
        if path_sub:
            _glass_text(img, (size / 2, foot[1] + s(72)), path_main, f_path, INK, glow=pglow)
            _glass_text(img, (size / 2, foot[1] + s(160)), path_sub,
                        _fit(path_sub, s(66), s(40), pw) or _font(s(40)), sub_path_ink)
        else:
            _glass_text(img, (size / 2, (foot[1] + foot[3]) / 2 + s(2)), path_main, f_path, INK, glow=pglow)

    #the frame: a thin line in the folder colour with a soft glow either side
    img.alpha_composite(_glow_layer((size, size), lambda d, f: d.rectangle([0, 0, size - 1, size - 1],
                                                                           outline=f, width=s(10)),
                                    frame + (200,), s(14)))
    ImageDraw.Draw(img).rectangle([0, 0, size - 1, size - 1], outline=frame + (255,), width=s(6))
    return img.convert("RGB")


def compose_card(render, title, subtitle=None, description=None, path_main=None,
                 path_sub=None, size=CARD, crop_ref=None, title_rgb=None, folder_rgb=None,
                 bar_alpha=None, bars="glass"):
    """The card as an RGB image. `render` is a PIL image (or a path) of the
    effect on black. `title_rgb` colours the title band and the tag chip (None
    = neutral), `folder_rgb` the path band and the frame (None = cream).
    `bars` "glass" (0.26.3, translucent over a full-bleed picture, `bar_alpha`
    0..1) or "solid" (the 0.26.2 card)."""
    _require_pil()                                             # 3.0.1 ensure pil
    if str(bars or "glass").lower() == "solid":
        return _compose_solid(render, title, subtitle, description, path_main, path_sub, size, crop_ref,
                              title_rgb=title_rgb, folder_rgb=folder_rgb)
    return _compose_glass(render, title, subtitle, description, path_main, path_sub, size, crop_ref,
                          title_rgb=title_rgb, folder_rgb=folder_rgb, bar_alpha=bar_alpha)


def _compose_solid(render, title, subtitle=None, description=None, path_main=None,
                   path_sub=None, size=CARD, crop_ref=None, title_rgb=None, folder_rgb=None):
    """The 0.26.2 card (bars "solid"): opaque plates, the picture boxed between
    them. `title_rgb` colours the title band and the tag chip (None = neutral
    steel), `folder_rgb` the path band and the frame (None = cream)."""
    if isinstance(render, str):
        render = Image.open(render)
    if isinstance(crop_ref, str):
        crop_ref = Image.open(crop_ref) if os.path.exists(crop_ref) else None
    S = size / CARD

    def s(v):
        return int(round(v * S))

    frame = shade(folder_rgb, s_mul=0.45, v=0.95) if folder_rgb else FRAME
    #pure black inside, like the renders - anything else shows the picture's edge
    img = Image.new("RGBA", (size, size), (0, 0, 0, 255))
    # the frame: a thin border with a dark vignette just inside it
    vign = Image.new("L", (size, size), 0)
    vd = ImageDraw.Draw(vign)
    for i in range(s(70)):
        vd.rectangle([i, i, size - 1 - i, size - 1 - i], outline=int(150 * (1 - i / s(70)) ** 2))
    dark = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    dark.putalpha(vign)
    glow_frame = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(glow_frame).rectangle([0, 0, size - 1, size - 1], outline=frame + (255,), width=s(8))
    img.alpha_composite(glow_frame.filter(ImageFilter.GaussianBlur(s(16))))
    img.alpha_composite(glow_frame.filter(ImageFilter.GaussianBlur(s(5))))
    img.alpha_composite(dark)
    ImageDraw.Draw(img).rectangle([0, 0, size - 1, size - 1], outline=frame + (255,), width=s(11))

    # the bands, top to bottom
    title_box = (s(22), s(84), size - s(22), s(270))
    if title_rgb:
        _coloured_plate(img, title_box, title_rgb, fade=s(220), seed=3)
        tglow = shade(title_rgb, s_mul=0.6, v=1.0) + (140,)
    else:
        _plate(img, title_box, fade=s(220), seed=3)
        tglow = (240, 196, 130, 120)
    # the title FITS its band: smaller for a long name, two lines for a very long one
    inner = (title_box[2] - title_box[0]) - s(120)
    tcx, tcy = (title_box[0] + title_box[2]) / 2, (title_box[1] + title_box[3]) / 2 + s(4)
    f_title = _fit(title, s(166), s(104), inner)
    if f_title is not None:
        _text(img, (tcx, tcy), title, f_title, INK, glow=tglow)
    else:
        a, b = _split_two(title)
        fa = _fit(a, s(92), s(44), inner) or _font(s(44))
        fb = _fit(b, s(92), s(44), inner) or _font(s(44))
        f2 = fa if fa.size <= fb.size else fb
        half = f2.size * 0.52
        _text(img, (tcx, tcy - half), a, f2, INK, glow=tglow)
        _text(img, (tcx, tcy + half), b, f2, INK, glow=tglow)
    img_top = title_box[3] + s(24)
    if subtitle:
        f_sub = _fit(subtitle, s(112), s(56), size - s(560)) or _font(s(56))
        tw = ImageDraw.Draw(img).textlength(subtitle, font=f_sub)
        cw = max(s(680), int(tw + s(400)))
        chip = (size // 2 - cw // 2, s(298), size // 2 + cw // 2, s(452))
        if title_rgb:
            _coloured_plate(img, chip, title_rgb, alpha=225, fade=s(120), seed=5, dark=True)
            sub_ink, sub_glow = shade(title_rgb, s_mul=0.38, v=1.0), shade(title_rgb, s_mul=0.8, v=1.0) + (110,)
        else:
            _plate(img, chip, top=(62, 66, 76), bottom=(26, 28, 34), alpha=225, fade=s(120), seed=5)
            sub_ink, sub_glow = INK_DIM, (200, 205, 215, 60)
        _text(img, (size / 2, (chip[1] + chip[3]) / 2 + s(3)), subtitle, f_sub, sub_ink, glow=sub_glow)
        img_top = chip[3] + s(20)

    foot_h = s(220) if path_sub else s(144)
    foot = (s(22), size - s(82) - foot_h, size - s(22), size - s(82))
    img_bottom = foot[1] - s(40)
    if description:
        f_desc = _font(s(88))
        lines = _wrap(description, f_desc, s(1500))
        if lines:
            line_h = s(106)
            dh = s(70) + line_h * len(lines)
            desc = (s(96), foot[1] - s(44) - dh, size - s(96), foot[1] - s(44))
            _plate(img, desc, top=(52, 56, 66), bottom=(24, 26, 32), alpha=215, fade=s(160), seed=7)
            y = desc[1] + s(35) + line_h / 2
            for ln in lines:
                _text(img, (size / 2, y), ln, f_desc, INK, glow=(240, 196, 130, 70))
                y += line_h
            img_bottom = desc[1] - s(24)
    if path_main:
        if folder_rgb:
            _coloured_plate(img, foot, folder_rgb, fade=s(220), seed=9)
            pglow, sub_path_ink = shade(folder_rgb, s_mul=0.6, v=1.0) + (90,), shade(folder_rgb, s_mul=0.3, v=0.92)
        else:
            _plate(img, foot, fade=s(220), seed=9)
            pglow, sub_path_ink = (240, 196, 130, 70), INK_DIM
        pw = (foot[2] - foot[0]) - s(120)
        f_path = _fit(path_main, s(86), s(48), pw) or _font(s(48))
        if path_sub:
            _text(img, (size / 2, foot[1] + s(72)), path_main, f_path, INK, glow=pglow)
            _text(img, (size / 2, foot[1] + s(160)), path_sub, _fit(path_sub, s(66), s(40), pw) or _font(s(40)),
                  sub_path_ink)
        else:
            _text(img, (size / 2, (foot[1] + foot[3]) / 2 + s(2)), path_main, f_path, INK, glow=pglow)
    else:
        img_bottom = size - s(110)

    # the render, fitted into what is left, on black
    region = (s(110), img_top, size - s(110), img_bottom)
    rw, rh = region[2] - region[0], region[3] - region[1]
    if rw > 10 and rh > 10:
        pic = visible_crop(render, ref=crop_ref)
        k = min(rw / pic.width, rh / pic.height)
        pic = pic.resize((max(1, int(pic.width * k)), max(1, int(pic.height * k))), Image.LANCZOS)
        # soft edges so the picture melts into the card's black
        mask = Image.new("L", pic.size, 255)
        md = ImageDraw.Draw(mask)
        e = max(2, min(pic.size) // 12)
        for i in range(e):
            md.rectangle([i, i, pic.width - 1 - i, pic.height - 1 - i], outline=int(255 * i / e))
        px = region[0] + (rw - pic.width) // 2
        py = region[1] + (rh - pic.height) // 2
        base = img.crop((px, py, px + pic.width, py + pic.height))
        img.paste(Image.composite(pic.convert("RGBA"), base, mask), (px, py))
    return img.convert("RGB")


def save_card(card, out):
    """PNG or JPG by the extension. JPG keeps a full card around half a megabyte."""
    if out.lower().endswith((".jpg", ".jpeg")):
        card.save(out, quality=JPG_QUALITY, subsampling=0, optimize=True)
    else:
        card.save(out)
    return out


def make_card(pcf_path, render, description=None, include_sub_folder=False,
              out_path=None, size=CARD, crop_ref=None, style=None, colours=None, info=None):
    """Name -> titles, folders -> path, render -> picture and colours; saves the
    card and returns its path. `out_path` None = `<name> (preview).<format>`
    beside the .pcf, versioned so nothing is overwritten. `style` (DEFAULT_STYLE
    keys) is the caller's choice; the effect's settings file beats it."""
    _require_pil()                                             # 3.0.1 ensure pil
    st = dict(DEFAULT_STYLE)
    st.update({k: v for k, v in (style or {}).items() if v is not None})
    st.update({k: v for k, v in load_overrides(pcf_path).items() if k in STYLE_KEYS})
    title, subtitle = titles_from_name(pcf_path)
    if st.get("title"):
        title = str(st["title"])
    if st.get("subtitle") is not None:
        subtitle = str(st["subtitle"]) or None
    if st.get("description") is not None:
        description = str(st["description"]) or None
    main, sub = pack_paths(pcf_path)
    ref = crop_ref if crop_ref is not None else render
    if isinstance(ref, str):
        ref = Image.open(ref) if os.path.exists(ref) else None
    title_rgb, folder_rgb, cinfo = resolve_colours(st, ref, main, colours)
    card = compose_card(render, title, subtitle, description, main,
                        sub if include_sub_folder else None, size, crop_ref,
                        title_rgb=title_rgb, folder_rgb=folder_rgb,
                        bar_alpha=st.get("bar_alpha"), bars=st.get("bars") or "glass")
    out = out_path or card_path(pcf_path, versioned=True, fmt=st.get("format") or "png")
    save_card(card, out)
    if info is not None:
        info.update(cinfo)
        info.update({"title_rgb": rgb_hex(title_rgb) if title_rgb else None,
                     "folder_rgb": rgb_hex(folder_rgb) if folder_rgb else None})
    return out


# ── which files ──────────────────────────────────────────────────────────────

def folder_pcfs(folder, skip_carded=True):
    """Every .pcf directly in `folder` that needs a card: minus those that
    already have one when skip_carded, and ONE
    per card name - "... (hd) a" and "... (hd)" share a card, so the one
    without the letter is rendered."""
    by_card = {}
    for name in sorted(os.listdir(folder)):
        p = os.path.join(folder, name)
        if not (name.lower().endswith(".pcf") and os.path.isfile(p)):
            continue
        if skip_carded and existing_card(p):
            continue
        key = card_stem(p).lower()
        plain = os.path.splitext(name)[0].strip().lower() == key
        if key not in by_card or plain:
            by_card[key] = p
    return [by_card[k] for k in sorted(by_card)]


def excluded(name, exclude=DEFAULT_EXCLUDE):
    low = name.strip().lower()
    return any(low == str(x).strip().lower() for x in exclude if str(x).strip())


def collect_pcfs(root, exclude=DEFAULT_EXCLUDE, skip_carded=True):
    """PROCESS ENTIRE FOLDER: every .pcf under `root`, recursively, that needs a
    card - excluded folder names skipped at any depth, one per card name per
    folder, carded effects left alone. -> (files, skipped counts)."""
    files, counts = [], {"carded": 0, "excluded_folders": 0, "variants": 0}
    for dp, dn, fn in os.walk(root):
        keep = []
        for d in sorted(dn, key=str.lower):
            if excluded(d, exclude):
                counts["excluded_folders"] += 1
            else:
                keep.append(d)
        dn[:] = keep
        pcfs = [f for f in fn if f.lower().endswith(".pcf")]
        if not pcfs:
            continue
        mine = folder_pcfs(dp, skip_carded=skip_carded)
        stems = {card_stem(os.path.join(dp, f)).lower() for f in pcfs}
        carded = sum(1 for s in stems if existing_card(os.path.join(dp, s + ".pcf")))
        counts["carded"] += carded if skip_carded else 0
        counts["variants"] += len(pcfs) - len(stems)
        files += mine
    return files, counts


def top_folder(path, root):
    """The folder directly under `root` that holds `path`, or None if `path` sits in root itself."""
    rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    parts = rel.split(os.sep)
    return os.path.join(os.path.abspath(root), parts[0]) if len(parts) > 1 else None


# ── the worker Blender(s) ────────────────────────────────────────────────────

def make_jobs(pcf_paths, work_dir, system=None, moment=0.0, res=1400, grid=True, view=None, start=0):
    """One render job per .pcf; the effect's settings file wins over the defaults."""
    jobs = []
    for i, pcf in enumerate(pcf_paths):
        ov = load_overrides(pcf)
        job = {"pcf": pcf, "system": system if len(pcf_paths) == 1 else None,
               "out": os.path.join(work_dir, "render_%05d.png" % (start + i)),
               "time": float(moment) if moment and moment > 0 else None, "res": int(res),
               "grid": bool(grid)}
        job.update({k: v for k, v in (view or {}).items() if v is not None})
        if ov.get("moment") not in (None, ""):
            job["time"] = float(ov["moment"]) if float(ov["moment"]) > 0 else None
        for key in ("system", "grid", "view_yaw", "view_pitch", "zoom", "cp0_yaw", "res", "max_particles"):
            if key in ov:
                job[key] = ov[key]
        jobs.append(job)
    return jobs


def start_worker(blender, scripts_dir, addon, worker, pcf_paths, work_dir, system=None,
                 moment=0.0, res=1400, prefs=None, grid=True, view=None, jobs=None, tag=""):
    """Start ONE worker Blender for all the files (one startup, not one per
    file). -> (Popen, job dict). The worker writes `result.json` after every
    file, so progress can be read while it runs."""
    import subprocess
    os.makedirs(work_dir, exist_ok=True)
    if jobs is None:
        jobs = make_jobs(pcf_paths, work_dir, system, moment, res, grid, view)
    spec = {"addon": addon, "result": os.path.join(work_dir, "result%s.json" % tag), "jobs": jobs,
            "prefs": prefs or {}}
    job_path = os.path.join(work_dir, "job%s.json" % tag)
    with open(job_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=1)
    env = dict(os.environ)
    if scripts_dir:
        env["BLENDER_USER_SCRIPTS"] = scripts_dir     # the same copy of this add-on
    log = open(os.path.join(work_dir, "worker%s.log" % tag), "w", encoding="utf-8")
    proc = subprocess.Popen([blender, "-b", "--factory-startup", "-P", worker, "--", job_path],
                            stdout=log, stderr=subprocess.STDOUT, env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    proc._htp_log = log
    return proc, spec


def worker_results(spec):
    try:
        with open(spec["result"], encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


def finish_cards(spec, description="", include_sub_folder=False, out_dir=None, style=None, colours=None):
    """Compose a card for every render the worker made. -> [(pcf, card or
    None, note)]. Single file: the description goes on; a folder run leaves
    it out (it describes one effect)."""
    done = []
    results = {r.get("pcf"): r for r in worker_results(spec)}
    single = len(spec["jobs"]) == 1
    for job in spec["jobs"]:
        r = results.get(job["pcf"])
        if not r or not r.get("ok") or not os.path.exists(job["out"]):
            done.append((job["pcf"], None, (r or {}).get("error", "the worker did not render it")))
            continue
        out = None
        st = dict(style or {})
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            out = os.path.join(out_dir, os.path.basename(
                card_path(job["pcf"], versioned=False, fmt=st.get("format") or "png")))
        card = make_card(job["pcf"], job["out"], description if single else None,
                         include_sub_folder, out_path=out, crop_ref=r.get("plain"), style=st, colours=colours)
        done.append((job["pcf"], card, "%s at %.2f s" % (r.get("system"), r.get("time", 0.0))))
    if colours is not None:
        colours.save()
    return done


class Batch:
    """PROCESS ENTIRE FOLDER: several worker Blenders at once, cards as the
    renders land, a crashed worker replaced, the disk watched.

        b = Batch(blender, scripts_dir, addon, worker, files, work_dir, workers=3, ...)
        b.start()
        while not b.poll()["done"]: time.sleep(2)     # or b.run()

    NON-DESTRUCTIVE BY CONSTRUCTION: cards are only ever written to names that
    do not exist yet (card_path), the file list comes from collect_pcfs
    (carded effects skipped), and the run STOPS before the card drive drops
    under `guard_free_gb`. Renders are temporary: each is shrunk to a 512 px
    FACE (for the folder icons) and deleted once its card is saved."""

    def __init__(self, blender, scripts_dir, addon, worker, pcf_paths, work_dir, workers=3,
                 prefs=None, grid=True, moment=0.0, res=1400, view=None, style=None,
                 colours=None, include_sub_folder=False, description=None, out_dir=None,
                 guard_free_gb=1.5, keep_renders=False, log=print, max_restarts=200, stall_minutes=15.0):
        self.args = (blender, scripts_dir, addon, worker)
        self.files = list(pcf_paths)
        self.work = work_dir
        self.n = max(1, int(workers))
        self.prefs, self.grid, self.moment, self.res, self.view = prefs or {}, grid, moment, res, view or {}
        self.style, self.colours = dict(style or {}), colours
        self.sub, self.description, self.out_dir = include_sub_folder, description, out_dir
        self.guard = float(guard_free_gb)
        self.keep = keep_renders
        self.log = log
        self.max_restarts = max_restarts
        #0.26.2: a worker that reports nothing for this long is stopped - one
        #pathological effect (the library run had one take 8 minutes and die)
        #must not hold a worker all night. It then counts as a crash below
        self.stall = float(stall_minutes or 0) * 60.0
        self.slots = []            # [{"proc", "spec", "jobs", "seen", "last"}]
        self.results = {}          # pcf -> dict
        self.queue = []
        self.restarts = 0
        self.stopped = None
        self.started = None
        self.faces = os.path.join(work_dir, "faces")

    # one worker = one Blender over a slice of the files
    def _launch(self, jobs):
        tag = "_%03d" % (len(self.slots) + 1)
        proc, spec = start_worker(*self.args, [j["pcf"] for j in jobs], self.work,
                                  prefs=self.prefs, jobs=jobs, tag=tag)
        self.slots.append({"proc": proc, "spec": spec, "jobs": jobs, "seen": set(), "tag": tag,
                           "last": time.time()})

    def start(self):
        os.makedirs(self.faces, exist_ok=True)
        jobs = make_jobs(self.files, self.work, None, self.moment, self.res, self.grid, self.view)
        self.started = time.time()
        if len(jobs) == 1 and self.style.get("system"):
            jobs[0]["system"] = self.style["system"]
        for k in range(min(self.n, len(jobs))):
            self._launch(jobs[k::self.n])
        self.log(f"[HT_PREVIEW]  {len(jobs)} effect(s), {len(self.slots)} worker Blender(s) - {self.work}")
        return self

    def _card(self, job, r):
        rec = {"pcf": job["pcf"], "ok": False, "card": None, "note": r.get("error", "not rendered"),
               "system": r.get("system"), "time": r.get("time"), "light": r.get("light")}
        if not r.get("ok") or not os.path.exists(job["out"]):
            return rec
        st = dict(self.style)
        out = None
        if self.out_dir:
            os.makedirs(self.out_dir, exist_ok=True)
            out = os.path.join(self.out_dir, os.path.basename(
                card_path(job["pcf"], versioned=False, fmt=st.get("format") or "png")))
            if os.path.exists(out):
                base, ext = os.path.splitext(out)
                n = 2
                while os.path.exists(f"{base} v{n}{ext}"):
                    n += 1
                out = f"{base} v{n}{ext}"
        target_dir = os.path.dirname(out or card_path(job["pcf"], versioned=False))
        free_gb = shutil.disk_usage(target_dir).free / 1e9
        if free_gb < self.guard:
            self.stopped = f"only {free_gb:.2f} GB free on the card drive (guard {self.guard:g} GB)"
            rec["note"] = "not saved: " + self.stopped
            return rec
        plain = r.get("plain") or job["out"]
        info = {}
        single = len(self.files) == 1
        card = make_card(job["pcf"], job["out"], self.description if single else None, self.sub,
                         out_path=out, crop_ref=plain if os.path.exists(plain) else None,
                         style=st, colours=self.colours, info=info)
        rec.update({"ok": True, "card": card, "note": "%s at %.2f s" % (r.get("system"), r.get("time") or 0.0),
                    "colour": info})
        try:
            src = Image.open(plain if os.path.exists(plain) else job["out"])
            face = visible_crop(src, keep=0.95, margin=0.06)
            face.thumbnail((512, 512), Image.LANCZOS)
            fpath = os.path.join(self.faces, "face_%s.jpg" % hashlib.sha1(job["pcf"].lower().encode()).hexdigest()[:12])
            face.save(fpath, quality=90)
            rec["face"] = fpath
            if rec.get("light") is None:
                rec["light"] = light_score(src)
            rec["strength"] = info.get("strength", 0.0)
        except Exception as exc:
            rec["face_error"] = str(exc)
        if self.keep == "jpg":
            #0.26.3: KEPT as JPGs beside the run (about 0.5 MB each), so a new
            #card look is a recompose, not another night of rendering
            try:
                kd = os.path.join(self.work, "renders")
                os.makedirs(kd, exist_ok=True)
                tag = hashlib.sha1(job["pcf"].lower().encode()).hexdigest()[:12]
                kept = {}
                for key, p in (("render", job["out"]), ("plain", r.get("plain"))):
                    if p and os.path.exists(p):
                        q = os.path.join(kd, "%s %s.jpg" % (tag, key))
                        Image.open(p).convert("RGB").save(q, quality=95, subsampling=0)
                        kept[key] = q
                rec["renders"] = kept
            except Exception as exc:
                rec["keep_error"] = str(exc)
        if self.keep is not True:
            for p in {job["out"], r.get("plain")}:
                try:
                    if p and os.path.exists(p):
                        os.remove(p)
                except OSError:
                    pass
        return rec

    def poll(self):
        """Non-blocking: collect finished renders, make their cards, replace
        crashed workers. -> progress dict (done when every file is accounted for)."""
        for slot in self.slots:
            if slot.get("closed"):
                continue
            by_pcf = {r.get("pcf"): r for r in worker_results(slot["spec"])}
            for job in slot["jobs"]:
                if job["pcf"] in slot["seen"] or job["pcf"] not in by_pcf:
                    continue
                slot["seen"].add(job["pcf"])
                slot["last"] = time.time()
                if self.stopped:
                    self.results[job["pcf"]] = {"pcf": job["pcf"], "ok": False, "card": None,
                                                "note": "not saved: " + self.stopped}
                    continue
                self.results[job["pcf"]] = rec = self._card(job, by_pcf[job["pcf"]])
                self.log(f"[HT_PREVIEW]  {len(self.results)}/{len(self.files)}  "
                         f"{os.path.basename(job['pcf'])} -> {rec['card'] or 'FAILED: ' + str(rec['note'])}")
            if slot["proc"].poll() is None:
                if self.stall and time.time() - slot.get("last", time.time()) > self.stall:
                    self.log(f"[HT_PREVIEW]  worker {slot['tag']} silent for {self.stall / 60:g} min - stopped")
                    try:
                        slot["proc"].kill()
                        slot["proc"].wait(timeout=30)
                    except Exception:
                        pass
                if slot["proc"].poll() is None:
                    continue
            # the worker is gone: everything it never reported is either the
            # file it died on (failed) or still to do (a new worker takes it)
            slot["closed"] = True
            try:
                slot["proc"]._htp_log.close()
            except Exception:
                pass
            left = [j for j in slot["jobs"] if j["pcf"] not in slot["seen"]]
            if not left:
                continue
            culprit = left[0]
            self.results[culprit["pcf"]] = {"pcf": culprit["pcf"], "ok": False, "card": None,
                                            "note": f"the worker Blender exited on this file (code {slot['proc'].returncode})"}
            self.log(f"[HT_PREVIEW]  worker {slot['tag']} stopped on {os.path.basename(culprit['pcf'])}")
            if left[1:] and not self.stopped and self.restarts < self.max_restarts:
                self.restarts += 1
                self._launch(left[1:])
            else:
                for j in left[1:]:
                    self.results[j["pcf"]] = {"pcf": j["pcf"], "ok": False, "card": None,
                                              "note": self.stopped or "not rendered (worker restarts used up)"}
        if self.stopped:
            self.cancel(quiet=True)
        if self.colours is not None:
            self.colours.save()
        live = sum(1 for s in self.slots if not s.get("closed"))
        done = (live == 0) and len(self.results) >= len(self.files)
        if live == 0 and not done:
            for pcf in self.files:
                self.results.setdefault(pcf, {"pcf": pcf, "ok": False, "card": None, "note": "not rendered"})
            done = True
        made = sum(1 for r in self.results.values() if r.get("ok"))
        return {"done": done, "total": len(self.files), "finished": len(self.results), "made": made,
                "failed": len(self.results) - made, "workers": live, "restarts": self.restarts,
                "elapsed": time.time() - (self.started or time.time()), "stopped": self.stopped}

    def run(self, sleep=2.0, progress_path=None):
        """Blocking loop for scripts and headless runs."""
        while True:
            p = self.poll()
            if progress_path:
                try:
                    with open(progress_path, "w", encoding="utf-8") as f:
                        json.dump(p, f)
                except OSError:
                    pass
            if p["done"]:
                return p
            time.sleep(sleep)

    def cancel(self, quiet=False):
        for slot in self.slots:
            if slot["proc"].poll() is None:
                try:
                    slot["proc"].kill()
                except Exception:
                    pass
        if not quiet:
            self.stopped = self.stopped or "cancelled"
