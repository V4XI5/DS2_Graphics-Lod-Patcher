import atexit
import hashlib
import math
import os
import struct
import tempfile

import vaxis_core as core

CORE = 'cache:package/package.00.00.core'
FONTS = {
    'neon': (CORE, 1523762868, 265246, '4bd94c02e013e44cfe587a109346d9e86e3a9c9d'),
    'mono': (CORE, 1524137443, 197544, '6e845aa15cced317df5b89311d72cc6162fb88f1'),
}
SCALE = 2
UNITS_PER_EM = 1000 * SCALE
FR_PRIVATE = 0x10

_registered = []


class _Reader:
    def __init__(self, buf):
        self.buf, self.pos = buf, 0

    def take(self, n):
        out = self.buf[self.pos:self.pos + n]
        if len(out) != n:
            raise ValueError('font data ends early')
        self.pos += n
        return out

    def u32(self):
        return struct.unpack('<I', self.take(4))[0]


def parse(buf):
    r = _Reader(buf)
    r.take(16)
    n = r.u32()
    name = r.take(n + 4)[4:].decode('utf-8') if n else ''
    height, ascent, descent, em = struct.unpack('<4f', r.take(16))
    glyphs = []
    for _ in range(r.u32()):
        advance, code = struct.unpack('<fI', r.take(8))
        r.take(32)
        contours = []
        for _ in range(r.u32()):
            cmds = r.take(r.u32())
            count = r.u32()
            pts = struct.unpack(f'<{count * 2}f', r.take(count * 8))
            contours.append((cmds, list(zip(pts[0::2], pts[1::2]))))
        glyphs.append((code, advance, contours))
    return {'name': name, 'ascent': ascent, 'descent': descent, 'cap': em, 'glyphs': glyphs}


def contour_points(cmds, pts):
    out = [(pts[0][0], pts[0][1], True)]
    i = 1
    for c in cmds:
        if c & 0x40:
            k = c & 0x3f
            out += [(x, y, False) for x, y in pts[i:i + k - 1]]
            out.append((pts[i + k - 1][0], pts[i + k - 1][1], True))
            i += k
        else:
            out += [(x, y, True) for x, y in pts[i:i + c]]
            i += c
    if i != len(pts) or len(out) != len(pts):
        raise ValueError('glyph commands do not match the point count')
    if len(out) > 1 and out[-1] == out[0]:
        out.pop()
    return out


def _checksum(data):
    data += bytes(-len(data) % 4)
    return sum(struct.unpack(f'>{len(data) // 4}I', data)) & 0xffffffff


def _glyph(contours):
    if not contours:
        return b'', (0, 0, 0, 0), 0
    xs = [p[0] for c in contours for p in c]
    ys = [p[1] for c in contours for p in c]
    box = (min(xs), min(ys), max(xs), max(ys))
    out = bytearray(struct.pack('>h4h', len(contours), *box))
    end = -1
    for c in contours:
        end += len(c)
        out += struct.pack('>H', end)
    out += struct.pack('>H', 0)
    points = [p for c in contours for p in c]
    out += bytes(1 if on else 0 for _, _, on in points)
    for axis in (0, 1):
        last = 0
        for p in points:
            out += struct.pack('>h', p[axis] - last)
            last = p[axis]
    out += bytes(-len(out) % 4)
    return bytes(out), box, len(points)


def _name_table(family):
    names = {1: family, 2: 'Regular', 3: f'VAXIS: {family}', 4: family, 5: 'Version 1.000',
             6: ''.join(ch for ch in family if ch.isalnum())}
    records, strings = bytearray(), bytearray()
    for nid, text in sorted(names.items()):
        raw = text.encode('utf-16-be')
        records += struct.pack('>6H', 3, 1, 0x409, nid, len(raw), len(strings))
        strings += raw
    return struct.pack('>3H', 0, len(names), 6 + len(records)) + records + strings


def _cmap(codes):
    segments = []
    for gid, code in enumerate(codes, 1):
        if segments and code == segments[-1][1] + 1 and gid - code == segments[-1][2]:
            segments[-1][1] = code
        else:
            segments.append([code, code, gid - code])
    segments.append([0xffff, 0xffff, 1])
    n = len(segments)
    power = 2 ** int(math.log2(n))
    sub = struct.pack('>7H', 4, 16 + 8 * n, 0, 2 * n, 2 * power, int(math.log2(n)), 2 * n - 2 * power)
    sub += struct.pack(f'>{n}H', *(s[1] for s in segments)) + struct.pack('>H', 0)
    sub += struct.pack(f'>{n}H', *(s[0] for s in segments))
    sub += struct.pack(f'>{n}H', *(s[2] & 0xffff for s in segments))
    sub += struct.pack(f'>{n}H', *([0] * n))
    return struct.pack('>2H', 0, 1) + struct.pack('>2HI', 3, 1, 12) + sub


def build_ttf(font, family, mono=False):
    s = lambda v: int(round(v * SCALE))
    by_code = {}
    for g in font['glyphs']:
        if 0x20 <= g[0] < 0xffff:
            by_code.setdefault(g[0], g)
    glyphs = [by_code[c] for c in sorted(by_code)]
    ascent, descent = s(font['ascent']), s(font['descent'])
    notdef_w = s(font['cap'] * 0.75)
    w, h, t = notdef_w // 8, s(font['cap']), max(s(font['cap']) // 14, 1)
    notdef = [[(w, 0, True), (w, h, True), (notdef_w - w, h, True), (notdef_w - w, 0, True)],
              [(w + t, t, True), (notdef_w - w - t, t, True), (notdef_w - w - t, h - t, True), (w + t, h - t, True)]]
    entries = [(notdef_w, notdef)]
    for code, advance, contours in glyphs:
        entries.append((s(advance), [[(s(x), s(y), on) for x, y, on in contour_points(cmds, pts)]
                                     for cmds, pts in contours]))
    glyf, loca, hmtx = bytearray(), [], bytearray()
    inked, max_points, max_contours = [], 0, 0
    for advance, contours in entries:
        data, box, npoints = _glyph(contours)
        loca.append(len(glyf))
        glyf += data
        hmtx += struct.pack('>Hh', advance, box[0])
        if contours:
            inked.append((advance, box))
        max_points, max_contours = max(max_points, npoints), max(max_contours, len(contours))
    loca.append(len(glyf))
    x_min, y_min = min(b[0] for _, b in inked), min(b[1] for _, b in inked)
    x_max, y_max = max(b[2] for _, b in inked), max(b[3] for _, b in inked)
    min_rsb = min(a - b[2] for a, b in inked)
    advances = [e[0] for e in entries]
    codes = [g[0] for g in glyphs]

    head = struct.pack('>4I2H2q4h2H3h', 0x10000, 0x10000, 0, 0x5f0f3cf5, 0x0009, UNITS_PER_EM, 0, 0,
                       x_min, y_min, x_max, y_max, 0, 8, 2, 1, 0)
    hhea = struct.pack('>I3hH3h3h4hhH', 0x10000, ascent, -descent, 0, max(advances), x_min, min_rsb,
                       x_max, 1, 0, 0, 0, 0, 0, 0, 0, len(entries))
    maxp = struct.pack('>I14H', 0x10000, len(entries), max_points, max_contours, 0, 0, 2, 0, 0, 0, 0, 0, 0, 0, 0)
    ranges = 0b111 | (1 << 7 if any(0x370 <= c < 0x400 for c in codes) else 0) | \
        (1 << 9 if any(0x400 <= c < 0x530 for c in codes) else 0)
    pages = 0b11 | (1 << 2 if any(0x400 <= c < 0x530 for c in codes) else 0) | \
        (1 << 3 if any(0x370 <= c < 0x400 for c in codes) else 0)
    avg = int(sum(advances) / len(advances))
    os2 = struct.pack('>H2h2H11h10s4I4s3H3h2H2I2h3H', 4, avg, 400, 5, 0,
                      s(325), s(350), 0, s(70), s(325), s(350), 0, s(350), s(50), s(250), 0,
                      bytes(10), ranges, 0, 0, 0, b'VXIS', 0x0040, min(codes), min(max(codes), 0xffff),
                      ascent, -descent, 0, max(ascent, y_max), max(descent, -y_min), pages, 0,
                      s(font['cap'] * 0.72), s(font['cap']), 0, 0x20, 2)
    post = struct.pack('>Ii2hI4I', 0x30000, 0, -s(75), s(50), 1 if mono else 0, 0, 0, 0, 0)
    tables = {
        b'OS/2': os2, b'cmap': _cmap(codes), b'glyf': bytes(glyf), b'head': head, b'hhea': hhea,
        b'hmtx': bytes(hmtx), b'loca': struct.pack(f'>{len(loca)}I', *loca), b'maxp': maxp,
        b'name': _name_table(family), b'post': post,
    }
    n = len(tables)
    power = 2 ** int(math.log2(n))
    out = bytearray(struct.pack('>I4H', 0x10000, n, 16 * power, int(math.log2(n)), 16 * n - 16 * power))
    offset = 12 + 16 * n
    body = bytearray()
    head_at = 0
    for tag in sorted(tables):
        data = tables[tag]
        if tag == b'head':
            head_at = offset + len(body)
        out += struct.pack('>4s3I', tag, _checksum(data), offset + len(body), len(data))
        body += data + bytes(-len(data) % 4)
    font_bytes = out + body
    struct.pack_into('>I', font_bytes, head_at + 8, (0xb1b0afba - _checksum(bytes(font_bytes))) & 0xffffffff)
    return bytes(font_bytes)


def _register(data, name):
    import ctypes
    folder = tempfile.mkdtemp(prefix='vaxis_fonts_')
    path = os.path.join(folder, name + '.ttf')
    with open(path, 'wb') as f:
        f.write(data)
    if not ctypes.windll.gdi32.AddFontResourceExW(ctypes.c_wchar_p(path), FR_PRIVATE, 0):
        raise OSError('Windows did not accept the font')
    _registered.append((path, folder))


@atexit.register
def _cleanup():
    import ctypes
    while _registered:
        path, folder = _registered.pop()
        try:
            ctypes.windll.gdi32.RemoveFontResourceExW(ctypes.c_wchar_p(path), FR_PRIVATE, 0)
            os.remove(path)
            os.rmdir(folder)
        except OSError:
            pass


def load(game, families=None):
    families = dict(families or {})
    if os.name != 'nt' or not game:
        return families
    for key, (archive, offset, size, digest) in FONTS.items():
        if key in families:
            continue
        try:
            raw = core.read_range(game, archive, offset, size)
            if hashlib.sha1(raw).hexdigest() != digest:
                continue
            font = parse(raw)
            family = font['name']
            _register(build_ttf(font, family, mono=key == 'mono'), key)
            families[key] = family
        except (core.PatchError, OSError, ValueError, struct.error):
            continue
    return families
