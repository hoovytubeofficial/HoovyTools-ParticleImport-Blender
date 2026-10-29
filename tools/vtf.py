# =============================================================================
#  _textures/vtf.py  -  decode a Source .vtf to RGBA pixels  (no bpy)
# =============================================================================
#
#  Clean-room decode of the formats particle sprites actually ship in, so we
#  never have to shell out to VTFEdit or lean on Source IO at runtime.
#
#  VTF LAYOUT, in plain words
#  -------------------------
#    [ header ][ (7.3+) resource dictionary ][ low-res thumbnail ][ image data ]
#
#  Image data is stored SMALLEST MIP FIRST. So mip 0 - the full-size image we
#  actually want - sits at the END of the block. For each mip the order is
#  frame -> face -> z-slice.
#
#  Supported: DXT1 (BC1), DXT3 (BC2), DXT5 (BC3), and the uncompressed
#  8-bit-per-channel layouts. Everything else raises with a clear message.
#
#  Output is a float RGBA numpy array shaped (height, width, 4), top row first.
# =============================================================================

import struct

try:
    import numpy as np
except ImportError:                     # Blender always ships numpy
    np = None


# name, bits-per-pixel (0 = block compressed)
IMAGE_FORMATS = {
    0: ("RGBA8888", 32), 1: ("ABGR8888", 32), 2: ("RGB888", 24), 3: ("BGR888", 24),
    4: ("RGB565", 16), 5: ("I8", 8), 6: ("IA88", 16), 7: ("P8", 8), 8: ("A8", 8),
    9: ("RGB888_BLUESCREEN", 24), 10: ("BGR888_BLUESCREEN", 24), 11: ("ARGB8888", 32),
    12: ("BGRA8888", 32), 13: ("DXT1", 4), 14: ("DXT3", 8), 15: ("DXT5", 8),
    16: ("BGRX8888", 32), 17: ("BGR565", 16), 18: ("BGRX5551", 16), 19: ("BGRA4444", 16),
    20: ("DXT1_ONEBITALPHA", 4), 21: ("BGRA5551", 16), 22: ("UV88", 16),
    23: ("UVWQ8888", 32), 24: ("RGBA16161616F", 64), 25: ("RGBA16161616", 64),
    26: ("UVLX8888", 32), -1: ("NONE", 0),
}

FLAG_NORMAL = 0x00000080
FLAG_SRGB = 0x00000040

RES_LOWRES = b"\x01\x00\x00"
RES_HIGHRES = b"\x30\x00\x00"
RES_SHEET = b"\x10\x00\x00"

_BLOCK8 = {"DXT1", "DXT1_ONEBITALPHA"}
_BLOCK16 = {"DXT3", "DXT5"}


def fmt_name(i):
    return IMAGE_FORMATS.get(i, (f"UNKNOWN({i})", 0))[0]


def image_size(w, h, fmt_id):
    """Bytes one image of this format occupies at w x h."""
    name = fmt_name(fmt_id)
    if name in _BLOCK8:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 8
    if name in _BLOCK16:
        return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
    bpp = IMAGE_FORMATS.get(fmt_id, ("", 0))[1]
    return (w * h * bpp) // 8


# ── header ───────────────────────────────────────────────────────────────────

def parse_header(data):
    if len(data) < 64 or data[:4] != b"VTF\x00":
        raise ValueError("not a VTF file (bad signature)")
    major, minor, header_size = struct.unpack_from("<3I", data, 4)
    width, height = struct.unpack_from("<2H", data, 16)
    flags, = struct.unpack_from("<I", data, 20)
    frames, first_frame = struct.unpack_from("<2H", data, 24)
    # NOTE the padding: reflectivity ends at 44, then 4 bytes of padding, so
    # bumpmapScale is at 48 - NOT 44. Getting this wrong shifts every field
    # after it and the format id reads back as a float bit pattern.
    reflect = struct.unpack_from("<3f", data, 32)
    bump, = struct.unpack_from("<f", data, 48)
    hi_fmt, = struct.unpack_from("<I", data, 52)
    mip_count = data[56]
    lo_fmt, = struct.unpack_from("<i", data, 57)
    lo_w, lo_h = data[61], data[62]

    h = {
        "version": (major, minor), "header_size": header_size,
        "width": width, "height": height, "flags": flags,
        "frames": frames, "first_frame": first_frame,
        "reflectivity": reflect, "bump_scale": bump,
        "high_res_format": hi_fmt, "mip_count": mip_count,
        "low_res_format": lo_fmt, "low_res_width": lo_w, "low_res_height": lo_h,
        "depth": 1, "num_resources": 0,
    }
    if (major, minor) >= (7, 2) and len(data) >= 65:
        h["depth"], = struct.unpack_from("<H", data, 63)
        if h["depth"] == 0:
            h["depth"] = 1
    if (major, minor) >= (7, 3) and len(data) >= 75:
        h["num_resources"], = struct.unpack_from("<I", data, 68)
    return h


def parse_resources(data, header):
    """7.3+ resource dictionary -> {tag: offset}."""
    if header["version"] < (7, 3) or not header["num_resources"]:
        return {}
    out = {}
    pos = 80
    for _ in range(header["num_resources"]):
        if pos + 8 > len(data):
            break
        tag = data[pos:pos + 3]
        offset, = struct.unpack_from("<I", data, pos + 4)
        out[tag] = offset
        pos += 8
    return out


def image_data_start(data, header, resources):
    """Byte offset of the high-res image block."""
    if RES_HIGHRES in resources:
        return resources[RES_HIGHRES]
    start = header["header_size"]
    if header["low_res_format"] not in (-1, 0xFFFFFFFF) and header["low_res_width"]:
        start += image_size(header["low_res_width"], header["low_res_height"],
                            header["low_res_format"])
    return start


def mip0_offset(header, start):
    """Mip 0 is stored LAST (smallest first), so skip every smaller mip."""
    w, h = header["width"], header["height"]
    fmt = header["high_res_format"]
    slices = max(1, header["frames"]) * max(1, header["depth"])
    faces = 1
    skip = 0
    for level in range(header["mip_count"] - 1, 0, -1):
        mw, mh = max(1, w >> level), max(1, h >> level)
        skip += image_size(mw, mh, fmt) * slices * faces
    return start + skip


# ── block decoders (vectorised) ──────────────────────────────────────────────

def _unpack565(c):
    r = ((c >> 11) & 0x1F).astype(np.uint16)
    g = ((c >> 5) & 0x3F).astype(np.uint16)
    b = (c & 0x1F).astype(np.uint16)
    return (r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31


def _bc1_colors(blocks, force_four_color):
    """blocks: (N,8) uint8. Returns rgb (N,4,3) uint8 and alpha (N,4) uint8."""
    c0 = blocks[:, 0].astype(np.uint16) | (blocks[:, 1].astype(np.uint16) << 8)
    c1 = blocks[:, 2].astype(np.uint16) | (blocks[:, 3].astype(np.uint16) << 8)
    r0, g0, b0 = _unpack565(c0)
    r1, g1, b1 = _unpack565(c1)

    n = blocks.shape[0]
    rgb = np.zeros((n, 4, 3), dtype=np.uint16)
    alpha = np.full((n, 4), 255, dtype=np.uint8)
    rgb[:, 0] = np.stack([r0, g0, b0], axis=-1)
    rgb[:, 1] = np.stack([r1, g1, b1], axis=-1)

    four = np.ones(n, dtype=bool) if force_four_color else (c0 > c1)
    # 4-colour mode: 2/3 + 1/3 blends
    rgb[four, 2] = (2 * rgb[four, 0] + rgb[four, 1] + 1) // 3
    rgb[four, 3] = (rgb[four, 0] + 2 * rgb[four, 1] + 1) // 3
    # 3-colour mode: midpoint, then transparent black
    three = ~four
    rgb[three, 2] = (rgb[three, 0] + rgb[three, 1]) // 2
    rgb[three, 3] = 0
    alpha[three, 3] = 0
    return rgb.astype(np.uint8), alpha


def _bc_indices_2bit(blocks):
    """blocks: (N,8) uint8, bytes 4..7 hold 16 2-bit indices."""
    bits = (blocks[:, 4].astype(np.uint32)
            | (blocks[:, 5].astype(np.uint32) << 8)
            | (blocks[:, 6].astype(np.uint32) << 16)
            | (blocks[:, 7].astype(np.uint32) << 24))
    shifts = np.arange(16, dtype=np.uint32) * 2
    return ((bits[:, None] >> shifts[None, :]) & 0x3).astype(np.uint8)


def _bc3_alpha(blocks):
    """blocks: (N,16) uint8, first 8 bytes are the BC3/BC4 alpha block."""
    a0 = blocks[:, 0].astype(np.uint16)
    a1 = blocks[:, 1].astype(np.uint16)
    n = blocks.shape[0]
    lut = np.zeros((n, 8), dtype=np.uint16)
    lut[:, 0], lut[:, 1] = a0, a1
    eight = a0 > a1
    idx = np.arange(1, 6, dtype=np.uint16)
    # 8-alpha mode: six interpolated values
    lut[eight, 2:7] = (((7 - idx)[None, :] * a0[eight, None]
                        + idx[None, :] * a1[eight, None]) + 3) // 7
    lut[eight, 7] = (a0[eight] + 6 * a1[eight] + 3) // 7
    # 6-alpha mode: four interpolated values, then 0 and 255
    six = ~eight
    idx4 = np.arange(1, 5, dtype=np.uint16)
    lut[six, 2:6] = (((5 - idx4)[None, :] * a0[six, None]
                      + idx4[None, :] * a1[six, None]) + 2) // 5
    lut[six, 6] = 0
    lut[six, 7] = 255

    bits = np.zeros(n, dtype=np.uint64)
    for i in range(6):
        bits |= blocks[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    shifts = (np.arange(16, dtype=np.uint64) * np.uint64(3))
    sel = ((bits[:, None] >> shifts[None, :]) & np.uint64(0x7)).astype(np.uint8)
    return np.take_along_axis(lut, sel.astype(np.intp), axis=1).astype(np.uint8)


def _blocks_to_image(rgb, alpha, idx, w, h):
    """Scatter 4x4 blocks back into a (h,w,4) uint8 image."""
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    px = np.take_along_axis(rgb, idx[:, :, None].astype(np.intp).repeat(3, axis=2), axis=1)
    pa = np.take_along_axis(alpha, idx.astype(np.intp), axis=1) if alpha.shape[1] == 4 else alpha
    block = np.concatenate([px, pa[:, :, None]], axis=2)          # (N,16,4)
    block = block.reshape(bh, bw, 4, 4, 4)                        # by,bx,py,px,c
    img = block.transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return img[:h, :w, :]


def _decode_dxt(raw, w, h, name):
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    n = bw * bh
    if name in _BLOCK8:
        blocks = np.frombuffer(raw, dtype=np.uint8, count=n * 8).reshape(n, 8)
        rgb, a4 = _bc1_colors(blocks, force_four_color=False)
        idx = _bc_indices_2bit(blocks)
        alpha = np.take_along_axis(a4, idx.astype(np.intp), axis=1)
        return _blocks_to_image(rgb, alpha, idx, w, h)

    blocks = np.frombuffer(raw, dtype=np.uint8, count=n * 16).reshape(n, 16)
    colour = blocks[:, 8:16]
    rgb, _ = _bc1_colors(colour, force_four_color=True)
    idx = _bc_indices_2bit(colour)
    if name == "DXT5":
        alpha = _bc3_alpha(blocks)
    else:                                    # DXT3: 4 bits per pixel, explicit
        raw_a = blocks[:, 0:8]
        nib = np.zeros((blocks.shape[0], 16), dtype=np.uint8)
        nib[:, 0::2] = raw_a & 0x0F
        nib[:, 1::2] = (raw_a >> 4) & 0x0F
        alpha = (nib * 17).astype(np.uint8)
    return _blocks_to_image(rgb, alpha, idx, w, h)


_UNCOMPRESSED = {
    "RGBA8888": (4, (0, 1, 2, 3)), "ABGR8888": (4, (3, 2, 1, 0)),
    "ARGB8888": (4, (1, 2, 3, 0)), "BGRA8888": (4, (2, 1, 0, 3)),
    "BGRX8888": (4, (2, 1, 0, None)), "UVLX8888": (4, (0, 1, 2, None)),
    "RGB888": (3, (0, 1, 2, None)), "BGR888": (3, (2, 1, 0, None)),
    "RGB888_BLUESCREEN": (3, (0, 1, 2, None)),
    "BGR888_BLUESCREEN": (3, (2, 1, 0, None)),
    "I8": (1, (0, 0, 0, None)), "A8": (1, (None, None, None, 0)),
    "IA88": (2, (0, 0, 0, 1)),
}


def _decode_uncompressed(raw, w, h, name):
    stride, order = _UNCOMPRESSED[name]
    flat = np.frombuffer(raw, dtype=np.uint8, count=w * h * stride)
    src = flat.reshape(h, w, stride)
    out = np.empty((h, w, 4), dtype=np.uint8)
    for ch, pick in enumerate(order):
        out[:, :, ch] = 255 if pick is None else src[:, :, pick]
    return out


# ── sprite sheet / sequence table (resource tag 0x10) ────────────────────────
#
#  THIS is the "how do I split the sheet" data, and it is the ONLY reliable
#  answer - a sheet is NOT guaranteed to be a tidy grid you can eyeball.
#
#  LAYOUT (verified byte-exact against real TF2 sheets):
#      uint32  byte_length              (= len(resource) - 4)
#      uint32  version                  (1 in every TF2 file seen)
#      uint32  sequence_count
#      per sequence:
#          uint32 sequence_id
#          uint32 clamp                 (1 = clamp/play once, 0 = loop)
#          uint32 frame_count
#          float  total_time            (sum of the frame durations)
#          per frame:
#              float duration
#              4 x (float u0, v0, u1, v1)     <- FOUR samples, not one
#
#  The four samples are the spritecard's four texture slots. In practice all
#  four are identical, so sample 0 IS the frame rect.
#
#  GOTCHA that cost us an afternoon: the old reader used
#      samples_per_frame = 4 if version == 0 else 1
#  which is BACKWARDS for version 1 - it desynced after frame 0 and reported
#  "PARSE INCOMPLETE". With 4 samples per frame both test files consume their
#  resource to the exact byte.
#
#  UV -> PIXELS:  x0 = u0 * width,  y0 = v0 * height   (v runs DOWN from the
#  TOP of the image). Rects carry a half-texel inset (0.0002 ~ 0.5/2048) so
#  neighbouring frames cannot bleed in - round to the nearest pixel.
# =============================================================================

def parse_sheet(raw):
    """Parse a SHEET resource. Returns a dict, or None if unparseable.

    {'version', 'sequence_count', 'complete', 'bytes_used', 'bytes_total',
     'sequences': [{'id', 'loops', 'frame_count', 'total_time',
                    'frames': [{'duration', 'uv': (u0,v0,u1,v1),
                                'samples': [...4 rects...]}]}]}
    """
    if not raw or len(raw) < 12:
        return None
    off = 0
    prefix, = struct.unpack_from("<I", raw, 0)
    if prefix == len(raw) - 4:
        off = 4                       # length-prefixed resource
    version, count = struct.unpack_from("<2I", raw, off)
    off += 8

    sequences = []
    complete = True
    try:
        for _ in range(count):
            sid, clamp, n_frames = struct.unpack_from("<3I", raw, off)
            total_time, = struct.unpack_from("<f", raw, off + 12)
            off += 16
            frames = []
            for _f in range(n_frames):
                duration, = struct.unpack_from("<f", raw, off)
                off += 4
                samples = []
                for _s in range(4):
                    samples.append(struct.unpack_from("<4f", raw, off))
                    off += 16
                frames.append({"duration": duration, "uv": samples[0],
                               "samples": samples})
            sequences.append({"id": sid, "loops": not bool(clamp),
                              "frame_count": n_frames, "total_time": total_time,
                              "frames": frames})
    except struct.error:
        complete = False

    return {"version": version, "sequence_count": count,
            "sequences": sequences, "complete": complete,
            "bytes_used": off, "bytes_total": len(raw)}


def get_sheet(path_or_bytes):
    """Read just the sprite-sheet table from a .vtf. None if it has none."""
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = bytes(path_or_bytes)
    else:
        with open(path_or_bytes, "rb") as fh:
            data = fh.read()
    header = parse_header(data)
    if header["version"] < (7, 3) or not header["num_resources"]:
        return None

    entries = []
    pos = 80
    for _ in range(header["num_resources"]):
        if pos + 8 > len(data):
            break
        tag, flag = data[pos:pos + 3], data[pos + 3]
        offset, = struct.unpack_from("<I", data, pos + 4)
        entries.append((tag, flag, offset))
        pos += 8
    # A resource block runs until the next block starts.
    pointed = sorted([e for e in entries if not (e[1] & 0x02)], key=lambda e: e[2])
    starts = [e[2] for e in pointed] + [len(data)]
    end_of = {pointed[i][2]: starts[i + 1] for i in range(len(pointed))}

    for tag, flag, offset in entries:
        if tag == RES_SHEET and not (flag & 0x02):
            return parse_sheet(data[offset:end_of.get(offset, len(data))])
    return None


def frame_rect(sheet, sequence_index, frame_index, width, height):
    """Pixel rect (x0, y0, x1, y1) of one frame. y counts DOWN from the top.

    This is the whole point of the sheet table: "which part of the image is
    frame F of sequence S" has an exact answer, with no grid guessing."""
    seq = sheet["sequences"][sequence_index]
    u0, v0, u1, v1 = seq["frames"][frame_index]["uv"]
    return (int(round(u0 * width)), int(round(v0 * height)),
            int(round(u1 * width)), int(round(v1 * height)))


def sheet_grid(sheet, width, height):
    """Best-effort (cols, rows, tile_w, tile_h) inferred from the frame rects.

    Geo-node sprite lookup usually wants a grid rather than a rect table.
    Returns None when frames are NOT uniformly sized - then you must use the
    per-frame rects instead of pretending it is a grid."""
    if not sheet or not sheet["sequences"]:
        return None
    frames = [f for s in sheet["sequences"] for f in s["frames"]]
    if not frames:
        return None
    u0, v0, u1, v1 = frames[0]["uv"]
    tw, th = (u1 - u0) * width, (v1 - v0) * height
    if tw <= 0 or th <= 0:
        return None
    for f in frames:
        a, b, c, d = f["uv"]
        if abs((c - a) * width - tw) > 1.5 or abs((d - b) * height - th) > 1.5:
            return None                      # non-uniform: rect table only
    # Report the tile PITCH, not the inset rect: frame rects are shrunk by a
    # half texel each side, so a 128px tile measures ~127 and would mislead.
    cols, rows = int(round(width / tw)), int(round(height / th))
    if cols < 1 or rows < 1:
        return None
    return (cols, rows, width // cols, height // rows)


def write_png(path, rgba_u8):
    """Write an (h, w, 4) uint8 array as a PNG, byte for byte.

    We hand-roll this instead of using Image.save() so no colour-management
    transform touches the data on the way out - the bytes we decoded are the
    bytes that land in the file."""
    import struct as _struct
    import zlib
    h, w = rgba_u8.shape[0], rgba_u8.shape[1]
    arr = np.ascontiguousarray(rgba_u8, dtype=np.uint8)
    # PNG wants a filter byte (0 = None) in front of every scanline.
    raw = np.zeros((h, w * 4 + 1), dtype=np.uint8)
    raw[:, 1:] = arr.reshape(h, w * 4)

    def chunk(tag, data):
        body = tag + data
        return (_struct.pack(">I", len(data)) + body
                + _struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", _struct.pack(">2I5B", w, h, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw.tobytes(), 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as fh:
        fh.write(png)
    return path


def decode_u8(path_or_bytes):
    """Same as decode() but returns the raw (h, w, 4) uint8 array."""
    px, info = decode(path_or_bytes)
    return (px * 255.0 + 0.5).astype(np.uint8), info


def decode(path_or_bytes):
    """Decode a VTF's largest mip. Returns (rgba_float_array, info_dict).

    rgba is float32 (h, w, 4) in 0..1, top row first."""
    if np is None:
        raise RuntimeError("numpy is unavailable - cannot decode VTF pixels")
    if isinstance(path_or_bytes, (bytes, bytearray)):
        data = bytes(path_or_bytes)
    else:
        with open(path_or_bytes, "rb") as fh:
            data = fh.read()

    header = parse_header(data)
    resources = parse_resources(data, header)
    start = image_data_start(data, header, resources)
    offset = mip0_offset(header, start)

    w, h = header["width"], header["height"]
    fmt_id = header["high_res_format"]
    name = fmt_name(fmt_id)
    need = image_size(w, h, fmt_id)
    if offset + need > len(data):
        raise ValueError(
            f"image data runs past end of file (need {need} bytes at {offset}, "
            f"file is {len(data)}) - format {name} may be misread")
    raw = data[offset:offset + need]

    if name in _BLOCK8 or name in _BLOCK16:
        rgba8 = _decode_dxt(raw, w, h, name)
    elif name in _UNCOMPRESSED:
        rgba8 = _decode_uncompressed(raw, w, h, name)
    else:
        raise NotImplementedError(
            f"VTF format {name} is not decodable yet (supported: DXT1/3/5 and "
            f"the 8-bit-per-channel layouts)")

    info = {
        "width": w, "height": h, "format": name,
        "version": f"{header['version'][0]}.{header['version'][1]}",
        "frames": header["frames"], "mipmaps": header["mip_count"],
        "flags": header["flags"],
        "is_normal": bool(header["flags"] & FLAG_NORMAL),
        "srgb": bool(header["flags"] & FLAG_SRGB),
        "has_sheet": RES_SHEET in resources,
    }
    return (rgba8.astype(np.float32) / 255.0), info
