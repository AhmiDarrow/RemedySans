#!/usr/bin/env python3
"""
Build Remedy Sans from source/remedy-sans.strokes.

    pip install fonttools brotli skia-pathops
    python build.py
    python check.py

The strokes file is the only source for the characters. Each stroke is expanded
to a filled outline with round caps and round joins, then overlaps are removed
so the glyph is one clean outline. Regular is weight 3.0 and Bold is weight 4.3
on the 24-unit grid. That grid is the em square (unitsPerEm 1000).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pathops
from fontTools.agl import UV2AGL
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.roundTools import otRound
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import newTable
from fontTools.ttLib.tables.O_S_2f_2 import Panose
from fontTools.ttLib.tables.ttProgram import Program

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source" / "remedy-sans.strokes"
OUT = ROOT / "fonts"

FAMILY = "Remedy Sans"
VERSION = "1.000"
COPYRIGHT = "Copyright 2026 Ahmi Darrow"
DESIGNER = "Ahmi Darrow"
VENDOR_URL = "https://github.com/AhmiDarrow/RemedySans"
DESIGNER_URL = "https://github.com/AhmiDarrow"
LICENSE_URL = "http://scripts.sil.org/OFL"
LICENSE = (
    "This Font Software is licensed under the SIL Open Font License, Version 1.1. "
    "This license is available with a FAQ at: https://openfontlicense.org"
)

# The strokes live on a 24-unit grid. One em is that grid.
UPM = 1000
GRID = 24.0
SCALE = UPM / GRID

ASCENDER = 21.0
DESCENDER = -6.0
CAP_HEIGHT = 20.0
X_HEIGHT = 14.0

WEIGHTS = {"regular": 3.0, "bold": 4.3}

# Generated .notdef box, not part of the strokes file. A rounded frame.
NOTDEF_ADV = 16.0
NOTDEF = [
    ("L", 3.0, 1.0, 13.0, 1.0),
    ("L", 13.0, 1.0, 13.0, 19.0),
    ("L", 13.0, 19.0, 3.0, 19.0),
    ("L", 3.0, 19.0, 3.0, 1.0),
]


def fu(v: float) -> int:
    """Design units to font units, half away from zero."""
    scaled = v * SCALE
    if scaled >= 0:
        return int(math.floor(scaled + 0.5))
    return -int(math.floor(-scaled + 0.5))


def parse(path: Path = SOURCE) -> list[tuple[int, float, list]]:
    """Return [(codepoint, advance, commands)] in file order."""
    glyphs: list[tuple[int, float, list]] = []
    current: list | None = None
    seen: set[int] = set()

    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("glyph"):
            parts = line.split()
            if len(parts) != 3 or not parts[2].startswith("adv="):
                raise ValueError(f"line {n}: expected 'glyph <code> adv=<units>', got {raw!r}")
            cp = int(parts[1])
            if cp in seen:
                raise ValueError(f"line {n}: U+{cp:04X} defined twice")
            seen.add(cp)
            current = []
            glyphs.append((cp, float(parts[2][4:]), current))
            continue
        if current is None:
            raise ValueError(f"line {n}: command before any glyph")
        kind = line[0]
        nums = [float(t) for t in line[1:].replace(",", " ").split()]
        if kind == "L" and len(nums) == 4:
            current.append(("L", *nums))
        elif kind == "A" and len(nums) == 6:
            current.append(("A", *nums))
        elif kind == "Q" and len(nums) == 6:
            current.append(("Q", *nums))
        elif kind == "D" and len(nums) == 2:
            current.append(("D", *nums))
        else:
            raise ValueError(f"line {n}: bad command {raw!r}")

    expected = list(range(32, 127))
    got = [cp for cp, _, _ in glyphs]
    if got != expected:
        raise ValueError(f"expected U+0020..U+007E in order, got {got[:8]}... ({len(got)} glyphs)")
    return glyphs


def _arc_cubic(cx, cy, rx, ry, a0_deg, a1_deg):
    """One cubic approximating an elliptical arc of at most 90 degrees.

    Angles are degrees counter-clockwise from +x. The sweep may be negative.
    Endpoints are exact; only the handles are approximate.
    """
    p0 = math.radians(a0_deg)
    p1 = math.radians(a1_deg)
    theta = p1 - p0
    k = (4.0 / 3.0) * math.tan(theta / 4.0)

    def at(a):
        return (cx + rx * math.cos(a), cy + ry * math.sin(a))

    s = at(p0)
    e = at(p1)
    c1 = (s[0] + k * (-rx * math.sin(p0)), s[1] + k * (ry * math.cos(p0)))
    c2 = (e[0] - k * (-rx * math.sin(p1)), e[1] - k * (ry * math.cos(p1)))
    return s, c1, c2, e


def _add_arc(path, cx, cy, rx, ry, a0, a1) -> None:
    sweep = a1 - a0
    if abs(sweep) < 1e-9 or rx <= 0 or ry <= 0:
        return
    closed = abs(abs(sweep) - 360.0) <= 1e-4
    pieces = max(1, math.ceil(abs(sweep) / 90.0 - 1e-9))
    cubics = []
    for i in range(pieces):
        t0 = a0 + sweep * i / pieces
        t1 = a0 + sweep * (i + 1) / pieces
        cubics.append(_arc_cubic(cx, cy, rx, ry, t0, t1))
    sx, sy = cubics[0][0]
    path.moveTo(sx * SCALE, sy * SCALE)
    last = len(cubics) - 1
    for i, (_, c1, c2, end) in enumerate(cubics):
        if closed and i == last:
            end = (sx, sy)
        path.cubicTo(c1[0] * SCALE, c1[1] * SCALE, c2[0] * SCALE, c2[1] * SCALE, end[0] * SCALE, end[1] * SCALE)
    if closed:
        path.close()


def _add_commands(center, dots, commands, weight: float) -> tuple[bool, bool]:
    """Add centerlines to `center` and filled dots to `dots`."""
    has_center = False
    has_dots = False
    radius = weight / 2.0
    for cmd in commands:
        kind = cmd[0]
        if kind == "L":
            _, x0, y0, x1, y1 = cmd
            if math.hypot(x1 - x0, y1 - y0) < 1e-6:
                _add_arc(dots, x0, y0, radius, radius, 0, 360)
                has_dots = True
                continue
            center.moveTo(x0 * SCALE, y0 * SCALE)
            center.lineTo(x1 * SCALE, y1 * SCALE)
            has_center = True
        elif kind == "Q":
            _, x0, y0, cx, cy, x1, y1 = cmd
            center.moveTo(x0 * SCALE, y0 * SCALE)
            center.quadTo(cx * SCALE, cy * SCALE, x1 * SCALE, y1 * SCALE)
            has_center = True
        elif kind == "A":
            _, cx, cy, rx, ry, a0, a1 = cmd
            _add_arc(center, cx, cy, rx, ry, a0, a1)
            has_center = True
        elif kind == "D":
            _, x, y = cmd
            _add_arc(dots, x, y, radius, radius, 0, 360)
            has_dots = True
        else:
            raise ValueError(f"unknown command {kind}")
    return has_center, has_dots


def _round_path(path):
    out = pathops.Path()
    for verb, points in path:
        out.add(verb, *((otRound(x), otRound(y)) for x, y in points))
    return out


def _contours(path):
    """Split a path into one Path per contour."""
    parts = []
    current = None
    for verb, points in path:
        name = verb.name
        if name == "MOVE":
            if current is not None:
                parts.append(current)
            current = pathops.Path()
            current.moveTo(*points[0])
        elif name == "LINE":
            current.lineTo(*points[0])
        elif name == "QUAD":
            current.quadTo(points[0][0], points[0][1], points[1][0], points[1][1])
        elif name == "CUBIC":
            current.cubicTo(
                points[0][0], points[0][1],
                points[1][0], points[1][1],
                points[2][0], points[2][1],
            )
        elif name == "CLOSE":
            current.close()
        else:
            raise RuntimeError(f"unexpected path verb {name}")
    if current is not None:
        parts.append(current)
    return parts


def _drop_slivers(path, weight: float, name: str):
    """Drop hairline contours left where strokes barely miss or graze.

    A real stroke is `weight` wide, and a real counter is much wider than a
    filament. The only filament in this face is a few units wide.
    """
    limit = weight * SCALE * 0.2
    parts = _contours(path)
    kept = []
    for part in parts:
        x0, y0, x1, y1 = part.bounds
        if min(x1 - x0, y1 - y0) < limit:
            continue
        kept.append(part)
    if len(kept) == len(parts):
        return path
    if not kept:
        raise RuntimeError(f"every contour of {name} was a sliver")
    out = pathops.Path()
    for part in kept:
        out.addPath(part)
    return out


def _union_clean(path, name: str, weight: float):
    """Drop overlaps. Round and retry if skia-pathops refuses float coordinates.

    clockwise=True puts outer contours in the TrueType direction.
    """
    path.convertConicsToQuads(0.5)
    try:
        cleaned = pathops.simplify(path, clockwise=True)
    except pathops.PathOpsError:
        path = _round_path(path)
        path.convertConicsToQuads(0.5)
        try:
            cleaned = pathops.simplify(path, clockwise=True)
        except pathops.PathOpsError as exc:
            raise RuntimeError(f"could not remove overlaps from {name}") from exc
    cleaned.convertConicsToQuads(0.5)
    return _drop_slivers(cleaned, weight, name)


def outline(commands, weight: float, name: str):
    """Stroked, overlap-free path in font units. None if there is no ink."""
    if not commands:
        return None
    center = pathops.Path()
    dots = pathops.Path()
    has_center, has_dots = _add_commands(center, dots, commands, weight)
    if has_center:
        center.stroke(
            weight * SCALE,
            pathops.LineCap.ROUND_CAP,
            pathops.LineJoin.ROUND_JOIN,
            4.0,
        )
        # Round caps are conics. pathops.op rejects that verb.
        center.convertConicsToQuads(0.5)
    if has_center and has_dots:
        path = pathops.op(center, dots, pathops.PathOp.UNION)
    elif has_center:
        path = center
    elif has_dots:
        path = dots
    else:
        return None
    return _union_clean(path, name, weight)


def _dedupe_contour(points, flags):
    """Drop zero-length segments created when a curve rounds onto itself.

    An off-curve point that lands on the following on-curve point is replaced
    by that on-curve point, which turns a collapsed quadratic into a line.
    """
    kept_p: list[tuple[int, int]] = []
    kept_f: list[int] = []
    for point, flag in zip(points, flags):
        point = (int(point[0]), int(point[1]))
        if not kept_p:
            kept_p.append(point)
            kept_f.append(flag)
            continue
        if point == kept_p[-1]:
            if (flag & 1) and not (kept_f[-1] & 1):
                kept_f[-1] = flag
            continue
        kept_p.append(point)
        kept_f.append(flag)
    if len(kept_p) >= 2 and kept_p[0] == kept_p[-1]:
        if (kept_f[-1] & 1) and not (kept_f[0] & 1):
            kept_f[0] = kept_f[-1]
        kept_p.pop()
        kept_f.pop()
    start = next((i for i, flag in enumerate(kept_f) if flag & 1), None)
    if start is None or len(kept_p) < 3:
        return [], []
    if start:
        kept_p = kept_p[start:] + kept_p[:start]
        kept_f = kept_f[start:] + kept_f[:start]
    return kept_p, kept_f


def _draw_contour(pen, points, flags) -> None:
    pen.moveTo(points[0])
    index = 1
    count = len(points)
    while index < count:
        if flags[index] & 1:
            pen.lineTo(points[index])
            index += 1
            continue
        offs = []
        while index < count and not (flags[index] & 1):
            offs.append(points[index])
            index += 1
        end = points[index] if index < count else points[0]
        pen.qCurveTo(*offs, end)
        if index < count:
            index += 1
    pen.closePath()


def _clean_glyph(glyph):
    """Remove zero-length lines and curves left by coordinate rounding."""
    if glyph.numberOfContours <= 0:
        return glyph
    coords, ends, flags = glyph.getCoordinates(None)
    pen = TTGlyphPen(None)
    begin = 0
    kept = 0
    for end in ends:
        points = [coords[i] for i in range(begin, end + 1)]
        contour_flags = [flags[i] for i in range(begin, end + 1)]
        begin = end + 1
        points, contour_flags = _dedupe_contour(points, contour_flags)
        if not points:
            continue
        _draw_contour(pen, points, contour_flags)
        kept += 1
    if kept == 0:
        raise RuntimeError("glyph outline collapsed while removing zero-length segments")
    cleaned = pen.glyph()
    cleaned.recalcBounds(glyfTable=None)
    return cleaned


def glyph_from_path(path) -> tuple[object, int]:
    """TrueType glyph and its xMin (the left sidebearing)."""
    # Cubics left over from arc and dot approximations become quadratics.
    sink = TTGlyphPen(None)
    path.draw(Cu2QuPen(sink, max_err=1.0, reverse_direction=False))
    glyph = _clean_glyph(sink.glyph())
    return glyph, int(glyph.xMin)


def build_weight(weight_name: str, glyphs) -> tuple[object, int, int]:
    """Return (TTFont, yMin, yMax) for one weight. Vertical metrics are filled later."""
    weight = WEIGHTS[weight_name]
    is_bold = weight_name == "bold"
    style = "Bold" if is_bold else "Regular"
    ps = f"RemedySans-{style}"

    order = [".notdef"]
    cmap: dict[int, str] = {}
    glyf = {}
    metrics = {}

    def add(name: str, commands, advance: float) -> None:
        path = outline(commands, weight, name)
        if path is None:
            pen = TTGlyphPen(None)
            glyf[name] = pen.glyph()
            metrics[name] = (fu(advance), 0)
            return
        glyph, lsb = glyph_from_path(path)
        glyf[name] = glyph
        metrics[name] = (fu(advance), lsb)

    add(".notdef", NOTDEF, NOTDEF_ADV)
    for cp, advance, commands in glyphs:
        name = UV2AGL.get(cp, f"uni{cp:04X}")
        if name in glyf:
            raise ValueError(f"duplicate glyph name {name}")
        order.append(name)
        cmap[cp] = name
        add(name, commands, advance)
    # U+00A0 shares the space glyph. The strokes file has no separate drawing for it.
    cmap[0x00A0] = cmap[0x0020]

    ink = [g for g in glyf.values() if g.numberOfContours]
    y_min = min(int(g.yMin) for g in ink)
    y_max = max(int(g.yMax) for g in ink)

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyf)
    fb.setupHorizontalMetrics(metrics)
    # Placeholders; main() sets the family line box once both weights exist.
    fb.setupHorizontalHeader(ascent=fu(ASCENDER), descent=fu(DESCENDER), lineGap=0)
    full = FAMILY if not is_bold else f"{FAMILY} {style}"
    fb.setupNameTable(
        {
            "copyright": COPYRIGHT,
            "familyName": FAMILY,
            "styleName": style,
            "uniqueFontIdentifier": f"{FAMILY} {style} {VERSION}",
            "fullName": full,
            "version": f"Version {VERSION}",
            "psName": ps,
            "manufacturer": DESIGNER,
            "designer": DESIGNER,
            "description": "Remedy Sans is the typeface of RemedyOS.",
            "vendorURL": VENDOR_URL,
            "designerURL": DESIGNER_URL,
            "licenseDescription": LICENSE,
            "licenseInfoURL": LICENSE_URL,
            "sampleText": "Remedy Sans is the typeface of RemedyOS.",
        }
    )
    panose = Panose()
    panose.bFamilyType = 2          # Latin text
    panose.bSerifStyle = 11         # normal sans
    panose.bWeight = 8 if is_bold else 5  # bold / book, matching the weight class
    panose.bProportion = 3          # modern
    panose.bContrast = 2            # none: the stroke is one width
    panose.bStrokeVariation = 1     # no fit
    panose.bArmStyle = 2            # straight arms, horizontal
    panose.bLetterForm = 2          # normal, contact
    panose.bMidline = 2             # standard, trimmed
    panose.bXHeight = 4             # constant, large
    fb.setupOS2(
        version=4,
        usWeightClass=700 if is_bold else 400,
        usWidthClass=5,
        fsType=0,
        sFamilyClass=(8 << 8) | 5,  # sans, geometric
        panose=panose,
        achVendID="AHMI",
        fsSelection=(0x20 if is_bold else 0x40) | 0x80,  # bold/regular + USE_TYPO_METRICS
        usFirstCharIndex=min(cmap),
        usLastCharIndex=max(cmap),
        sTypoAscender=fu(ASCENDER),
        sTypoDescender=fu(DESCENDER),
        sTypoLineGap=0,
        usWinAscent=max(fu(ASCENDER), y_max),
        usWinDescent=max(-fu(DESCENDER), -y_min),
        sxHeight=int(fb.font["glyf"]["x"].yMax),
        sCapHeight=int(fb.font["glyf"]["H"].yMax),
        yStrikeoutSize=fu(weight),
        yStrikeoutPosition=fu(X_HEIGHT / 2),
        usDefaultChar=0,
        usBreakChar=32,
        usMaxContext=0,
    )
    fb.font["OS/2"].recalcCodePageRanges(fb.font)
    # One underline for the family. It matches the Regular stroke.
    fb.setupPost(
        underlinePosition=fu(-1.5),
        underlineThickness=fu(WEIGHTS["regular"]),
        isFixedPitch=0,
    )
    fb.font["head"].macStyle = 1 if is_bold else 0
    fb.font["head"].fontRevision = 1.0

    # Windows names only. Platform 1 (Mac) records are obsolete.
    fb.font["name"].names = [rec for rec in fb.font["name"].names if rec.platformID != 1]

    gasp = newTable("gasp")
    gasp.version = 1
    gasp.gaspRange = {0xFFFF: 0x000A}  # grayscale, no gridfit (the font is unhinted)
    fb.font["gasp"] = gasp

    # Unhinted, but dropout control is on so thin strokes still cover a pixel.
    prep = newTable("prep")
    prep.program = Program()
    prep.program.fromBytecode(bytes((0xB8, 0x01, 0xFF, 0x85, 0xB0, 0x04, 0x8D)))
    fb.font["prep"] = prep
    fb.font["maxp"].maxStackElements = max(fb.font["maxp"].maxStackElements, 1)

    return fb.font, y_min, y_max


def apply_family_metrics(fonts: dict[str, object], bounds: dict[str, tuple[int, int]]) -> None:
    """One line box for both weights, tall enough that no glyph is clipped."""
    y_min = min(b[0] for b in bounds.values())
    y_max = max(b[1] for b in bounds.values())
    typo_asc = max(fu(ASCENDER), y_max)
    typo_desc = min(fu(DESCENDER), y_min)
    win_asc = y_max
    win_desc = -y_min
    for font in fonts.values():
        font["hhea"].ascent = typo_asc
        font["hhea"].descent = typo_desc
        font["hhea"].lineGap = 0
        os2 = font["OS/2"]
        os2.sTypoAscender = typo_asc
        os2.sTypoDescender = typo_desc
        os2.sTypoLineGap = 0
        os2.usWinAscent = win_asc
        os2.usWinDescent = win_desc


def save_font(font, style: str) -> Path:
    OUT.mkdir(exist_ok=True)
    ttf = OUT / f"RemedySans-{style}.ttf"
    font.flavor = None
    font.save(ttf)
    font.flavor = "woff2"
    font.save(ttf.with_suffix(".woff2"))
    font.flavor = None
    return ttf


def main() -> int:
    glyphs = parse()
    fonts = {}
    bounds = {}
    for weight_name in ("regular", "bold"):
        font, y_min, y_max = build_weight(weight_name, glyphs)
        fonts[weight_name] = font
        bounds[weight_name] = (y_min, y_max)
    apply_family_metrics(fonts, bounds)
    for weight_name, font in fonts.items():
        style = "Bold" if weight_name == "bold" else "Regular"
        path = save_font(font, style)
        print(
            f"built {path.relative_to(ROOT)} and .woff2 "
            f"({len(glyphs)} characters, weight {WEIGHTS[weight_name]})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
