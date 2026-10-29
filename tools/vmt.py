# =============================================================================
#  tools/vmt.py  -  read a .vmt, find the .vtf
# =============================================================================
#
#  A .pcf names a MATERIAL, not a texture. The chain is:
#
#      system's `material`  ->  .vmt  ->  $basetexture  ->  .vtf
#
#  so nothing can be imported until this link exists.
#
#  VMT IS NOT A FORMAT, IT IS A HABIT. Everything below is a real thing found
#  in real files, and a parser that assumes any of them is unnecessary breaks
#  on somebody's material:
#
#      "$basetexture" "path"      $basetexture "path"      basetexture path
#      $BASETEXTURE "path"        "$BaseTexture"  "path"
#      // comment   # comment   /* block */
#      backslashes, forward slashes, a leading "materials/", no extension
#      nested blocks (Proxies), duplicate keys, values like "[0.8 2.5 5]"
#
#  So: case-insensitive, quote-optional, `$`-optional on names we recognise,
#  and comments stripped OUTSIDE quotes (a path can contain //, and a texture
#  called `some//thing` is not a comment).
#
#  bpy-free on purpose - pure text, testable without Blender.
#
#  This is the reader the importer uses. The full standalone reporter lives in
#  __Developer/Parser - VMT and goes further: it keeps line numbers, blocks,
#  duplicates and warnings. This one answers the two questions the importer
#  actually asks - what shader, and which texture.
# =============================================================================

from pathlib import Path


# Names that are textures. Used both to classify and to recognise a key that
# an author wrote without its '$'.
TEXTURE_KEYS = (
    "$basetexture", "$basetexture2", "$bumpmap", "$normalmap", "$dudvmap",
    "$detail", "$selfillummask", "$envmapmask", "$refracttexture",
)

# Which parameter carries the image that MATTERS, per shader. A Refract
# particle has no $basetexture at all - its picture is a normal map - so
# asking every shader for $basetexture finds nothing and reports "no texture"
# for a material that has one.
PRIMARY_BY_SHADER = {
    "refract": ("$normalmap", "$bumpmap", "$dudvmap"),
    "spritecard": ("$basetexture",),
    "sprite": ("$basetexture",),
    "unlitgeneric": ("$basetexture",),
    "vertexlitgeneric": ("$basetexture",),
    "lightmappedgeneric": ("$basetexture",),
    "modulate": ("$basetexture",),
    "water": ("$normalmap", "$basetexture"),
}

_KNOWN = set(TEXTURE_KEYS) | {
    "$overbrightfactor", "$additive", "$addoverblend", "$addself",
    "$blendframes", "$translucent", "$alpha", "$color", "$nofog",
    "$refractamount", "$refracttint", "$bluramount", "$forcerefract",
    "$vertexcolor", "$vertexalpha", "$vertexcolormodulate",
    "$depthblend", "$depthblendscale", "$startfadesize", "$endfadesize",
    "$vertexfogamount", "$powerfunction", "$spline", "$splinetype",
    "$maxsize", "$minsize", "$sequence_blend_mode",
}

# The keys whose picture is DATA, not colour. A Refract material's image is a
# normal map: import it Non-Color and drive a warp with it, never show it.
NORMAL_KEYS = ("$normalmap", "$bumpmap", "$dudvmap")


def strip_comments(text):
    """Remove // # and /* */ - but never inside a quoted string.

    A texture path can legitimately contain `//`, and stripping it there
    silently truncates the path to nothing."""
    out = []
    i, n = 0, len(text)
    quote = line_c = block_c = False
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if line_c:
            if c == "\n":
                out.append(c)
                line_c = False
            i += 1
        elif block_c:
            if c == "*" and nxt == "/":
                block_c = False
                i += 2
            else:
                if c == "\n":
                    out.append(c)
                i += 1
        elif quote:
            out.append(c)
            if c == '"':
                quote = False
            i += 1
        elif c == '"':
            quote = True
            out.append(c)
            i += 1
        elif c == "/" and nxt == "/":
            line_c = True
            i += 2
        elif c == "/" and nxt == "*":
            block_c = True
            i += 2
        elif c == "#":
            line_c = True
            i += 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _tokens(text):
    """Quoted strings, braces, and bare words."""
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "{}":
            out.append(c)
            i += 1
        elif c == '"':
            i += 1
            start = i
            while i < n and text[i] != '"':
                i += 1
            out.append(text[start:i])
            i += 1
        else:
            start = i
            while i < n and not text[i].isspace() and text[i] not in "{}":
                i += 1
            out.append(text[start:i])
    return out


def canonical(key):
    """`BaseTexture`, `$BASETEXTURE` and `basetexture` are one parameter.

    A leading '$' is added back only for names we recognise - inventing one
    for an unknown key would turn a typo into a plausible-looking parameter."""
    low = str(key).strip().lower()
    if low.startswith("$"):
        return low
    return "$" + low if "$" + low in _KNOWN else low


def parse(text):
    """-> (shader, {canonical key: value}). Last occurrence of a key wins.

    Nested blocks (Proxies and friends) are walked but their keys are NOT
    merged into the root: a Proxy's `$basetexture` names the parameter it
    animates, not the material's texture, and hoisting it overwrites the real
    one with the string "$basetexture"."""
    toks = _tokens(strip_comments(text.lstrip("﻿")))
    if not toks:
        return "", {}

    shader = toks[0].strip().lower()
    values = {}
    depth = 0
    i = 1 if toks[0] not in "{}" else 0
    while i < len(toks):
        t = toks[i]
        if t == "{":
            depth += 1
            i += 1
        elif t == "}":
            depth -= 1
            i += 1
        elif i + 1 < len(toks) and toks[i + 1] == "{":
            depth += 1
            i += 2                      # a named block: skip its name too
        else:
            if i + 1 < len(toks):
                if depth <= 1:          # root level only
                    values[canonical(t)] = toks[i + 1]
                i += 2
            else:
                i += 1
    return shader, values


def parse_file(path):
    p = Path(path)
    return parse(p.read_text(encoding="utf-8", errors="replace"))


def primary_texture(shader, values):
    """The texture reference that matters for this shader, or None."""
    for key in PRIMARY_BY_SHADER.get(shader, ("$basetexture",)):
        if values.get(key):
            return key, values[key]
    for key in TEXTURE_KEYS:
        if values.get(key):
            return key, values[key]
    return None, None


def texture_relpath(raw):
    """A VMT texture reference -> `sub/dir/name.vtf`, ready to join to a root.

    Backslashes, a leading `materials/`, a missing extension and a leading
    slash are all normal and all have to go."""
    v = str(raw).strip().strip('"').replace("\\", "/")
    while v.startswith("./"):
        v = v[2:]
    v = v.lstrip("/")
    if v.lower().startswith("materials/"):
        v = v[len("materials/"):]
    if not v.lower().endswith(".vtf"):
        v += ".vtf"
    return v


def find_vmt(material_ref, roots):
    """Locate the .vmt a .pcf asked for, under any materials root."""
    rel = str(material_ref).strip().strip('"').replace("\\", "/").lstrip("/")
    if rel.lower().startswith("materials/"):
        rel = rel[len("materials/"):]
    if not rel.lower().endswith(".vmt"):
        rel += ".vmt"
    for root in roots:
        cand = Path(root) / rel
        if cand.is_file():
            return cand
    return None


def resolve_path(vmt_path, roots):
    """The same chain as `resolve`, but for a .vmt PICKED OFF DISK.

    `resolve` starts from the material reference written inside a .pcf and has
    to go looking for the file. When someone browses to the .vmt themselves
    there is nothing to look for, and insisting on a search root would refuse
    to open a perfectly good material sitting outside the SFM tree.

    ⚠️ A .vmt names its texture RELATIVE TO A MATERIALS ROOT, so the search
    roots are still needed for the second half of the chain. If none of them
    has it, the file sitting NEXT TO the .vmt is tried - which is where a
    material handed over on its own almost always keeps its texture."""
    vmt_path = Path(vmt_path)
    out = {"vmt": vmt_path, "shader": "", "values": {}, "texture_key": None,
           "texture_ref": None, "vtf": None}
    try:
        shader, values = parse_file(vmt_path)
    except Exception as exc:
        print(f"[HT_VMT]  could not read {vmt_path}: {exc}")
        return out
    out["shader"], out["values"] = shader, values
    key, ref = primary_texture(shader, values)
    out["texture_key"], out["texture_ref"] = key, ref
    if not ref:
        return out
    rel = texture_relpath(ref)
    for root in roots:
        cand = Path(root) / rel
        if cand.is_file():
            out["vtf"] = cand
            return out
    beside = vmt_path.parent / Path(rel).name
    if beside.is_file():
        out["vtf"] = beside
    return out


def resolve(material_ref, roots):
    """The whole chain in one call.

    -> dict(vmt, shader, values, texture_key, texture_ref, vtf)
    Every field is None or empty rather than raising, because half a chain is
    still worth reporting: knowing the .vmt was found but its .vtf was not is
    a different problem from not finding the material at all."""
    out = {"vmt": None, "shader": "", "values": {}, "texture_key": None,
           "texture_ref": None, "vtf": None}
    vmt = find_vmt(material_ref, roots)
    if vmt is None:
        return out
    out["vmt"] = vmt
    try:
        shader, values = parse_file(vmt)
    except Exception as exc:
        print(f"[HT_VMT]  could not read {vmt}: {exc}")
        return out
    out["shader"], out["values"] = shader, values
    key, ref = primary_texture(shader, values)
    out["texture_key"], out["texture_ref"] = key, ref
    if ref:
        rel = texture_relpath(ref)
        for root in roots:
            cand = Path(root) / rel
            if cand.is_file():
                out["vtf"] = cand
                break
    return out


def overbright(values, default=1.0):
    """$overbrightfactor as a plain multiplier. 1 = normal, 2 = twice as hot.

    Glow sprites lean on this constantly, and dropping it is why an imported
    flare looks flat next to the same material in SFM."""
    raw = values.get("$overbrightfactor")
    if raw is None:
        return default
    try:
        return float(str(raw).strip().strip('"'))
    except ValueError:
        return default


def is_additive(values):
    for key in ("$additive", "$addoverblend"):
        raw = values.get(key)
        if raw is None:
            continue
        try:
            if float(str(raw).strip().strip('"')) != 0.0:
                return True
        except ValueError:
            pass
    return False


def blend_mode(values):
    """How SpriteCard composites this material - MEASURED, not guessed (0.24.0).

    Measured 2026-10-28 in SFM's particle editor with a calibration kit: a
    grey ramp (colour left -> right) x alpha ramp (top -> bottom) drawn once
    per blend flag on pure black, then every pixel fitted - 1 to 3 grey
    levels RMS on all 16 tiles. Everything happens in LINEAR light (sRGB in,
    sRGB out), the colour is clamped to 1 before it is blended:

        blend         no flag          colour x alpha       OVER the frame
        additive      $additive 1      colour x alpha       ADDED to the frame
        addoverblend  $addoverblend 1  colour (NOT x alpha) + (1 - alpha) frame
        addself       $addself k       colour x (1+k) x alpha + (1 - alpha) frame

    🔴 $addoverblend IS NOT ADDITIVE. `is_additive` lumped the two together,
    so the shader threw the texture's alpha away and used brightness as
    opacity - and most smoke is $addoverblend, so dark smoke went see-through.

    Precedence when several flags are set (only single flags were measured):
    $addself, then $addoverblend, then $additive."""
    def num(key):
        raw = values.get(key)
        if raw is None:
            return 0.0
        try:
            return float(str(raw).strip().strip('"'))
        except ValueError:
            return 0.0
    k = num("$addself")
    if k != 0.0:
        mode = "addself"
    elif num("$addoverblend") != 0.0:
        mode = "addoverblend"
    elif num("$additive") != 0.0:
        mode = "additive"
    else:
        mode = "blend"
    return {"mode": mode, "addself": k, "overbright": overbright(values)}


# ── shader classes ───────────────────────────────────────────────────────────
#
#  Real particle materials come in TWO families, and they need different
#  Blender materials, not different numbers in the same one:
#
#      SPRITE   spritecard / sprite / unlitgeneric ... - the picture IS the
#               particle. Emissive card, $overbrightfactor, $additive.
#      WARP     refract - the picture is a NORMAL MAP and the particle is a
#               distortion: it bends whatever renders behind it. Heat haze,
#               shockwaves, droplets. It has no $basetexture at all.
#
#  Everything that reads a .vmt asks THIS module which family it landed in, so
#  the decision is made once, here, instead of once per operator.

def material_class(shader, texture_key=None):
    """'WARP' or 'SPRITE'.

    Refract is a warp by definition. Any other shader whose primary picture
    turned out to be a normal map (water, a modder's custom shader) is warped
    too - the deciding fact is what the image IS, not what the shader is
    called."""
    if str(shader).strip().lower() == "refract":
        return "WARP"
    if texture_key in NORMAL_KEYS:
        return "WARP"
    return "SPRITE"


def _float(raw, default):
    try:
        return float(str(raw).strip().strip('"'))
    except (TypeError, ValueError):
        return default


def vector(raw):
    """'[0.8 2.5 5]' or '{255 128 0}' -> list of floats, else None.

    ⚠️ THE BRACKET IS THE UNIT. VMT writes colours both ways: [ ] carries
    0..1 floats, { } carries 0..255 bytes. Treating them the same makes a
    white tint 255x too hot."""
    if raw is None:
        return None
    v = str(raw).strip().strip('"').strip()
    if len(v) < 2 or (v[0], v[-1]) not in {("[", "]"), ("{", "}")}:
        return None
    try:
        nums = [float(p) for p in v[1:-1].replace(",", " ").split()]
    except ValueError:
        return None
    if v[0] == "{":
        nums = [n / 255.0 for n in nums]
    return nums


def warp_params(values):
    """What a Refract material tells the warp builder.

    -> dict(refract_amount, blur_amount, tint)

    $refractamount scales the normal map's X/Y deviation - it is NOT an IOR,
    and its sign matters (negative reverses the warp). Source's default is
    0.2, used only when a material never says."""
    tint = (1.0, 1.0, 1.0, 1.0)
    vec = vector(values.get("$refracttint"))
    if vec:
        rgb = (vec + [vec[-1]] * 3)[:3]
        tint = (rgb[0], rgb[1], rgb[2], 1.0)
    return {
        "refract_amount": _float(values.get("$refractamount"), 0.2),
        "blur_amount": _float(values.get("$bluramount"), 0.0),
        "tint": tint,
    }
