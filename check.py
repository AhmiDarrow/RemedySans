#!/usr/bin/env python3
"""
Check the built Remedy Sans files against source/remedy-sans.strokes.

    python check.py

A missing font is a failure. Build first with build.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pathops
from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

import build

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "fonts"
STYLES = tuple(st.name for st in build.STYLES)
WEIGHT_CLASS = {st.name: st.weight_class for st in build.STYLES}


def _span(a: int, b: int) -> list[int]:
    return list(range(a, b + 1))


# Every character FreeSpeak needs, in every weight (its TARGET.md).
TARGET = set(
    _span(0x0020, 0x007E)
    + _span(0x00A0, 0x00FF)
    + _span(0x0100, 0x017F)
    + [0x0192, 0x0218, 0x0219, 0x021A, 0x021B]
    + [0x02C6, 0x02C7] + _span(0x02D8, 0x02DD)
    + [0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2015, 0x2018, 0x2019, 0x201A,
       0x201C, 0x201D, 0x201E, 0x2020, 0x2021, 0x2022, 0x2026, 0x2030, 0x2032,
       0x2033, 0x2039, 0x203A, 0x203C, 0x2044]
    + [0x2007, 0x2008, 0x2009, 0x200A, 0x202F]
    + [0x20AC, 0x20B9, 0x20BD, 0x20BA, 0x20A9, 0x20AA, 0x20AB, 0x20B1, 0x20B4, 0x20B8, 0x20BF]
    + [0x2122, 0x2116]
    + _span(0x2190, 0x2195) + [0x21E7]
    + [0x2212, 0x221E, 0x221A, 0x2248, 0x2260, 0x2264, 0x2265]
    + [0x25FB, 0x25B2, 0x25BC, 0x25BA, 0x25C4] + _span(0x23F4, 0x23F7)
    + [0x2713, 0x2717, 0x25CF, 0x25CB]
    + [0x0386] + _span(0x0388, 0x038A) + [0x038C] + _span(0x038E, 0x03A1) + _span(0x03A3, 0x03CE)
    + _span(0x0400, 0x045F) + _span(0x0490, 0x0493)
    + [0x049A, 0x049B, 0x04A2, 0x04A3, 0x04AE, 0x04AF, 0x04B0, 0x04B1, 0x04BA, 0x04BB,
       0x04D8, 0x04D9, 0x04E8, 0x04E9]
)

# Characters that are empty glyphs, and the advance each must have (grid units).
# None means "the advance of this other character".
SPACES = {
    0x0020: 7,
    0x00A0: 7,
    0x2007: ("digit", 0x0030),  # figure space: one digit
    0x2008: ("same", 0x002E),   # punctuation space: one period
    0x2009: 5,                  # thin space: one fifth of the em
    0x200A: 2,                  # hair space
    0x202F: 5,                  # narrow no-break space: as thin
}

# These counters are closed circles in the stroke source, so each weight
# keeps a hole. The number is the contour count (outer plus holes).
HOLES = {
    "O": 2,
    "o": 2,
    "zero": 2,
    "Q": 2,
    "eight": 3,
    "degree": 2,
    "Aring": 3,
    "aring": 4,
    "Theta": 3,
    "theta": 3,
    "uni0444": 3,
    "uni04E8": 3,
    "infinity": 3,
    "copyright": 3,
    "circle": 2,
    "uni25FB": 2,
}

# The line spacing of 1.000, kept in every later version (font units).
LINE_1000 = {"ascent": 1048, "descent": -340, "lineGap": 0}

# Filled shapes: one solid contour, no hole.
SOLID = ("bullet", "H18533", "triagup", "triagdn", "triagrt", "triaglf",
         "uni23F4", "uni23F5", "uni23F6", "uni23F7")


class AreaPen(BasePen):
    def __init__(self):
        super().__init__(None)
        self.areas: list[float] = []
        self._pts: list[tuple[float, float]] = []

    def _moveTo(self, pt):
        self._pts = [(pt[0], pt[1])]

    def _lineTo(self, pt):
        self._pts.append((pt[0], pt[1]))

    def _curveToOne(self, _c1, _c2, pt):
        self._pts.append((pt[0], pt[1]))

    def _qCurveToOne(self, _control, pt):
        self._pts.append((pt[0], pt[1]))

    def _closePath(self):
        area = 0.0
        pts = self._pts
        for i, (x1, y1) in enumerate(pts):
            x2, y2 = pts[(i + 1) % len(pts)]
            area += x1 * y2 - x2 * y1
        self.areas.append(area / 2.0)

    def _endPath(self):
        self._closePath()


def fail(message: str) -> None:
    print(f"fail: {message}", file=sys.stderr)
    raise SystemExit(1)


def zero_length_segments(font, glyph_name: str) -> bool:
    """True when two consecutive on-curve points are the same point."""
    glyph = font["glyf"][glyph_name]
    if glyph.numberOfContours <= 0:
        return False
    coords, ends, flags = glyph.getCoordinates(None)
    start = 0
    for end in ends:
        on = []
        for i in range(start, end + 1):
            if flags[i] & 1:
                on.append((int(coords[i][0]), int(coords[i][1])))
        for i, point in enumerate(on):
            if len(on) > 1 and point == on[(i + 1) % len(on)]:
                return True
        start = end + 1
    return False


def check_font(font, style: str, src: build.Source) -> None:
    cmap = font.getBestCmap()
    drawn = {g.cp for g in src.glyphs}
    if set(cmap) != drawn | {0x00A0}:
        extra = sorted(set(cmap) ^ (drawn | {0x00A0}))
        fail(f"{style} cmap differs from the stroke source at {[hex(c) for c in extra[:8]]}")
    missing = sorted(TARGET - set(cmap))
    if missing:
        fail(f"{style} is missing {len(missing)} target characters: {[hex(c) for c in missing[:12]]}")
    if cmap[0x00A0] != cmap[0x0020]:
        fail(f"{style} no-break space does not use the space glyph")
    if len(font.getGlyphOrder()) != len(src.glyphs) + 1:
        fail(f"{style} has {len(font.getGlyphOrder())} glyphs, expected {len(src.glyphs) + 1}")

    glyf = font["glyf"]
    hmtx = font["hmtx"]
    for g in src.glyphs:
        name = cmap[g.cp]
        width, lsb = hmtx[name]
        advance = src.advance(g.cp)
        if width != build.fu(advance):
            fail(f"{style} {name} advance {width} != {build.fu(advance)}")
        glyph = glyf[name]
        if g.cp in SPACES:
            if glyph.numberOfContours != 0 or lsb != 0:
                fail(f"{style} {name} is a space but has an outline")
        elif glyph.numberOfContours <= 0:
            fail(f"{style} {name} (U+{g.cp:04X}) has no outline")
        elif lsb != int(glyph.xMin):
            fail(f"{style} {name} lsb {lsb} != xMin {glyph.xMin}")

    for cp, want in SPACES.items():
        width = hmtx[cmap[cp]][0]
        if isinstance(want, tuple):
            want_units = hmtx[cmap[want[1]]][0]
        else:
            want_units = build.fu(want)
        if width != want_units:
            fail(f"{style} U+{cp:04X} space is {width} wide, expected {want_units}")

    for name, contours in HOLES.items():
        count = glyf[name].numberOfContours
        if count != contours:
            fail(f"{style} {name} has {count} contours, expected {contours}")
        pen = AreaPen()
        glyf[name].draw(pen, glyf)
        signs = {1 if area > 0 else -1 for area in pen.areas if abs(area) > 1}
        if signs != {1, -1}:
            fail(f"{style} {name} contours do not wind as a hole ({pen.areas})")
    for name in SOLID:
        if glyf[name].numberOfContours != 1:
            fail(f"{style} {name} should be one solid shape, has {glyf[name].numberOfContours} contours")

    for name in font.getGlyphOrder():
        if zero_length_segments(font, name):
            fail(f"{style} {name} has a zero-length segment")

    # Line spacing stays as in 1.000: hhea and typo metrics are fixed, and
    # USE_TYPO_METRICS tells renderers to use the typo values.
    hhea = font["hhea"]
    os2 = font["OS/2"]
    line = {
        "hhea.ascent": (hhea.ascent, LINE_1000["ascent"]),
        "hhea.descent": (hhea.descent, LINE_1000["descent"]),
        "hhea.lineGap": (hhea.lineGap, LINE_1000["lineGap"]),
        "OS/2.sTypoAscender": (os2.sTypoAscender, LINE_1000["ascent"]),
        "OS/2.sTypoDescender": (os2.sTypoDescender, LINE_1000["descent"]),
        "OS/2.sTypoLineGap": (os2.sTypoLineGap, LINE_1000["lineGap"]),
    }
    for field, (got, want) in line.items():
        if got != want:
            fail(f"{style} {field} is {got}, expected the 1.000 value {want}")
    if not os2.fsSelection & 0x80:
        fail(f"{style} USE_TYPO_METRICS is not set")

    # usWin metrics cover every glyph, so Windows never clips one (accents on
    # capitals may rise above the hhea ascent, as in most fonts).
    for name in font.getGlyphOrder():
        glyph = glyf[name]
        if glyph.numberOfContours <= 0:
            continue
        if glyph.yMax > os2.usWinAscent:
            fail(f"{style} {name} top {glyph.yMax} is above usWinAscent {os2.usWinAscent}")
        if -glyph.yMin > os2.usWinDescent:
            fail(f"{style} {name} bottom {glyph.yMin} is below usWinDescent {os2.usWinDescent}")

    name_ids = {
        rec.nameID: rec.toUnicode()
        for rec in font["name"].names
        if rec.platformID == 3
    }
    if {1, 2, 4, 5, 6} - set(name_ids):
        fail(f"{style} name table is missing an id")
    ribbi = style in ("Regular", "Bold")
    want_family = build.FAMILY if ribbi else f"{build.FAMILY} {style}"
    want_sub = style if ribbi else "Regular"
    if name_ids[1] != want_family:
        fail(f"{style} family name is {name_ids[1]!r}")
    if name_ids[2] != want_sub:
        fail(f"{style} style name is {name_ids[2]!r}")
    if not ribbi and (name_ids.get(16) != build.FAMILY or name_ids.get(17) != style):
        fail(f"{style} typographic family/subfamily is {name_ids.get(16)!r}/{name_ids.get(17)!r}")
    if name_ids[5] != f"Version {build.VERSION}":
        fail(f"{style} version string is {name_ids[5]!r}")
    if any(rec.platformID == 1 for rec in font["name"].names):
        fail(f"{style} still has Mac name records")

    if os2.fsType != 0:
        fail(f"{style} fsType is {os2.fsType}, expected 0")
    expect_weight = WEIGHT_CLASS[style]
    if os2.usWeightClass != expect_weight:
        fail(f"{style} weight class {os2.usWeightClass}")
    if font["head"].unitsPerEm != build.UPM:
        fail(f"{style} unitsPerEm {font['head'].unitsPerEm}")
    if b"\xb8\x01\xff\x85\xb0\x04\x8d" not in font["prep"].program.getBytecode():
        fail(f"{style} prep table is missing smart dropout control")

    # Round-trip through fontTools.
    from io import BytesIO

    buf = BytesIO()
    font.save(buf)
    again = TTFont(buf)
    if again.getGlyphOrder() != font.getGlyphOrder():
        fail(f"{style} did not round-trip")


def check_mark_clearance(src: build.Source) -> int:
    """No mark placed above or below a letter may touch that letter's ink."""
    checked = 0
    for g in src.glyphs:
        if not src.is_composite(g.cp):
            continue
        for weight_name, weight in build.WEIGHTS.items():
            base, marks = src.mark_parts(g.cp, weight)
            if not base:
                continue  # a spacing accent on its own
            base_path = build.outline(base, weight, f"U+{g.cp:04X} base")
            mark_path = build.outline(marks, weight, f"U+{g.cp:04X} marks")
            both = pathops.op(base_path, mark_path, pathops.PathOp.INTERSECTION)
            if len(list(both)):
                fail(f"U+{g.cp:04X} {weight_name}: a mark touches its letter")
            checked += 1
    return checked


def main() -> int:
    src = build.load()
    if [g.cp for g in src.glyphs[:95]] != list(range(32, 127)):
        fail("stroke source does not start with U+0020..U+007E in order")

    loaded = {}
    for style in STYLES:
        for ext in (".ttf", ".woff2"):
            path = FONTS / f"RemedySans-{style}{ext}"
            if not path.is_file():
                fail(f"missing {path.name}")
            font = TTFont(path)
            if ext == ".ttf":
                loaded[style] = font
            else:
                if font.getGlyphOrder() != loaded[style].getGlyphOrder():
                    fail(f"{style} woff2 glyph order differs from the ttf")
        check_font(loaded[style], style, src)

    regular = loaded["Regular"]
    for other_style, other in loaded.items():
        for table, attr in (("hhea", "ascent"), ("hhea", "descent"), ("hhea", "lineGap")):
            if getattr(regular[table], attr) != getattr(other[table], attr):
                fail(f"family {table}.{attr} differs in {other_style}")
        for attr in ("sTypoAscender", "sTypoDescender", "sTypoLineGap", "usWinAscent", "usWinDescent"):
            if getattr(regular["OS/2"], attr) != getattr(other["OS/2"], attr):
                fail(f"family OS/2.{attr} differs in {other_style}")
        if regular["post"].underlineThickness != other["post"].underlineThickness:
            fail(f"underline thickness differs in {other_style}")
        if regular.getGlyphOrder() != other.getGlyphOrder():
            fail(f"{other_style} has a different glyph set from Regular")

    # Digits share one advance, taken from the stroke file.
    digit_width = build.fu(16)
    for style, font in loaded.items():
        cmap = font.getBestCmap()
        widths = {font["hmtx"][cmap[cp]][0] for cp in range(48, 58)}
        if widths != {digit_width}:
            fail(f"{style} digits are not tabular ({widths})")

    clear = check_mark_clearance(src)

    print(
        f"ok: {len(src.glyphs)} characters from the stroke source plus U+00A0 on the space glyph, "
        f"all {len(TARGET)} target characters, Light, Semilight, Regular, Semibold and Bold; "
        f"{clear} accent placements clear of their letters"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
