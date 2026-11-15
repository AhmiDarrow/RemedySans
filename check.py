#!/usr/bin/env python3
"""
Check the built Remedy Sans files against source/remedy-sans.strokes.

    python check.py

A missing font is a failure. Build first with build.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont

import build

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "fonts"
STYLES = ("Regular", "Bold")

# These counters are closed circles in the stroke source, so each weight
# keeps a hole. The number is the contour count (outer plus holes).
HOLES = {
    "O": 2,
    "o": 2,
    "zero": 2,
    "Q": 2,
    "eight": 3,
}


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
            if point == on[(i + 1) % len(on)]:
                return True
        start = end + 1
    return False


def check_font(font, style: str, strokes) -> None:
    cmap = font.getBestCmap()
    if set(cmap) != set(range(32, 127)) | {0x00A0}:
        fail(f"{style} cmap is {sorted(cmap)[:8]}... ({len(cmap)} entries)")
    if cmap[0x00A0] != cmap[0x0020]:
        fail(f"{style} no-break space does not use the space glyph")
    if len(font.getGlyphOrder()) != 96:
        fail(f"{style} has {len(font.getGlyphOrder())} glyphs, expected 96")

    glyf = font["glyf"]
    hmtx = font["hmtx"]
    for cp, advance, commands in strokes:
        name = cmap[cp]
        width, lsb = hmtx[name]
        if width != build.fu(advance):
            fail(f"{style} {name} advance {width} != {build.fu(advance)}")
        glyph = glyf[name]
        if commands:
            if glyph.numberOfContours <= 0:
                fail(f"{style} {name} has no outline")
            if lsb != int(glyph.xMin):
                fail(f"{style} {name} lsb {lsb} != xMin {glyph.xMin}")
        else:
            if glyph.numberOfContours != 0:
                fail(f"{style} space is not empty")
            if width != build.fu(7) or lsb != 0:
                fail(f"{style} space metrics {width}, {lsb}")

    for name, contours in HOLES.items():
        count = glyf[name].numberOfContours
        if count != contours:
            fail(f"{style} {name} has {count} contours, expected {contours}")
        pen = AreaPen()
        glyf[name].draw(pen, glyf)
        signs = {1 if area > 0 else -1 for area in pen.areas if abs(area) > 1}
        if signs != {1, -1}:
            fail(f"{style} {name} contours do not wind as a hole ({pen.areas})")

    for name in font.getGlyphOrder():
        if zero_length_segments(font, name):
            fail(f"{style} {name} has a zero-length segment")

    name_ids = {
        rec.nameID: rec.toUnicode()
        for rec in font["name"].names
        if rec.platformID == 3
    }
    if {1, 2, 4, 6} - set(name_ids):
        fail(f"{style} name table is missing an id")
    if name_ids[1] != "Remedy Sans":
        fail(f"{style} family name is {name_ids[1]!r}")
    if name_ids[2] != style:
        fail(f"{style} style name is {name_ids[2]!r}")
    if any(rec.platformID == 1 for rec in font["name"].names):
        fail(f"{style} still has Mac name records")

    os2 = font["OS/2"]
    if os2.fsType != 0:
        fail(f"{style} fsType is {os2.fsType}, expected 0")
    expect_weight = 700 if style == "Bold" else 400
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


def main() -> int:
    strokes = build.parse()
    if [cp for cp, _, _ in strokes] != list(range(32, 127)):
        fail("stroke source is not U+0020..U+007E in order")

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
        check_font(loaded[style], style, strokes)

    regular = loaded["Regular"]
    bold = loaded["Bold"]
    for table, attr in (("hhea", "ascent"), ("hhea", "descent"), ("hhea", "lineGap")):
        if getattr(regular[table], attr) != getattr(bold[table], attr):
            fail(f"family {table}.{attr} differs")
    for attr in ("sTypoAscender", "sTypoDescender", "sTypoLineGap", "usWinAscent", "usWinDescent"):
        if getattr(regular["OS/2"], attr) != getattr(bold["OS/2"], attr):
            fail(f"family OS/2.{attr} differs")
    if regular["post"].underlineThickness != bold["post"].underlineThickness:
        fail("underline thickness differs between weights")

    # Digits share one advance, taken from the stroke file.
    digit_width = build.fu(16)
    for style, font in loaded.items():
        cmap = font.getBestCmap()
        widths = {font["hmtx"][cmap[cp]][0] for cp in range(48, 58)}
        if widths != {digit_width}:
            fail(f"{style} digits are not tabular ({widths})")

    print(
        f"ok: {len(strokes)} characters, U+0020..U+007E, "
        f"plus U+00A0 on the space glyph, Regular and Bold"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
