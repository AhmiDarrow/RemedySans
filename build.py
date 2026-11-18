#!/usr/bin/env python3
"""
Build Remedy Sans from source/remedy-sans.strokes.

    pip install fonttools brotli skia-pathops
    python build.py
    python check.py

The strokes file is the only source for the characters. Each stroke is expanded
to a filled outline with round caps and round joins, then overlaps are removed
so the glyph is one clean outline. Five weights are built from the one drawing by stroke weight: Light
2.1, Semilight 2.55, Regular 3.0, Semibold 3.6 and Bold 4.3
on the 24-unit grid. That grid is the em square (unitsPerEm 1000).
"""
from __future__ import annotations

import io
import math
import shutil
import subprocess
import sys
from pathlib import Path

import pathops
from fontTools.agl import UV2AGL
from fontTools.fontBuilder import FontBuilder
from fontTools.misc.roundTools import otRound
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.cu2quPen import Cu2QuPen
from fontTools.pens.reverseContourPen import ReverseContourPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont, newTable
from fontTools.ttLib.tables.O_S_2f_2 import Panose
from fontTools.ttLib.tables.ttProgram import Program

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "source" / "remedy-sans.strokes"
OUT = ROOT / "fonts"

FAMILY = "Remedy Sans"
FILE_STEM = "RemedySans"
VERSION = "1.200"
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

class Style:
    """One weight of the family."""

    def __init__(self, name: str, stroke: float, weight_class: int, panose: int):
        self.name = name                # style name: Light, Semilight, Regular, Semibold, Bold
        self.stroke = stroke            # stroke weight in grid units
        self.weight_class = weight_class
        self.panose = panose
        self.ribbi = name in ("Regular", "Bold")


# The same steps between weights as Remedy Sans UI, scaled to this font's
# own Regular-to-Bold distance.
STYLES = [
    Style("Light", 2.1, 300, 3),
    Style("Semilight", 2.55, 350, 4),
    Style("Regular", 3.0, 400, 5),
    Style("Semibold", 3.6, 600, 7),
    Style("Bold", 4.3, 700, 8),
]
WEIGHTS = {s.name.lower(): s.stroke for s in STYLES}

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


# Space between a mark and the stroke it sits on, in grid units. The stroke's
# own weight is added on top, so the white gap is the same in both weights.
MARK_GAP = 1.0
MARK_KINDS = ("above", "below", "attach")


def code(token: str, n: int) -> int:
    """A character code: decimal (65) or U+0041."""
    try:
        if token.upper().startswith("U+"):
            return int(token[2:], 16)
        return int(token)
    except ValueError:
        raise ValueError(f"line {n}: bad character code {token!r}") from None


def _point(token: str, n: int) -> tuple[float, float]:
    parts = token.split(",")
    if len(parts) != 2:
        raise ValueError(f"line {n}: expected x,y, got {token!r}")
    return float(parts[0]), float(parts[1])


class Glyph:
    """One character of the stroke file, before marks are placed."""

    def __init__(self, cp: int, advance: float | None, line: int):
        self.cp = cp
        self.advance = advance
        self.line = line
        self.items: list = []           # drawing commands, ("use", ...), ("put", ...)
        self.anchors: dict[str, tuple[float, float]] = {}


class Mark:
    """An accent drawn once and placed on many letters."""

    def __init__(self, name: str, anchor: str, kind: str, line: int):
        self.name = name
        self.anchor = anchor
        self.kind = kind
        self.line = line
        self.items: list = []


class Source:
    """The parsed stroke file: glyphs in file order and the marks they use."""

    def __init__(self, glyphs: list[Glyph], marks: dict[str, Mark]):
        self.glyphs = glyphs
        self.by_cp = {g.cp: g for g in glyphs}
        self.marks = marks
        for g in glyphs:
            self.advance(g.cp)          # resolve now so errors show at load
            self.anchors(g.cp)

    def advance(self, cp: int, _seen=()) -> float:
        g = self._get(cp, _seen)
        if g.advance is not None:
            return g.advance
        for item in g.items:
            if item[0] == "use":
                return self.advance(item[1], _seen + (cp,))
        raise ValueError(f"line {g.line}: U+{cp:04X} has no adv= and uses no other glyph")

    def anchors(self, cp: int, _seen=()) -> dict[str, tuple[float, float]]:
        g = self._get(cp, _seen)
        out: dict[str, tuple[float, float]] = {}
        for item in g.items:
            if item[0] == "use":
                _, other, dx, dy = item
                for name, (x, y) in self.anchors(other, _seen + (cp,)).items():
                    out.setdefault(name, (x + dx, y + dy))
        out.update(g.anchors)
        return out

    def _get(self, cp: int, seen) -> Glyph:
        if cp in seen:
            raise ValueError(f"U+{cp:04X} uses itself")
        if cp not in self.by_cp:
            raise ValueError(f"U+{cp:04X} is used but never drawn")
        return self.by_cp[cp]

    def commands(self, cp: int, weight: float, _seen=()) -> list:
        """Flat drawing commands for one weight, with every mark in place."""
        g = self._get(cp, _seen)
        out: list = []
        for item in g.items:
            if item[0] == "use":
                _, other, dx, dy = item
                out += [shift(c, dx, dy) for c in self.commands(other, weight, _seen + (cp,))]
            elif item[0] == "put":
                _, name, x, y, touch = item
                out += self.place(name, x, y, weight, touch)
            else:
                out.append(item)
        return out

    def place(self, name: str, x: float, y: float, weight: float, touch: bool = False) -> list:
        mark = self.marks.get(name)
        if mark is None:
            raise ValueError(f"mark {name!r} is used but never drawn")
        dy = 0.0
        if not touch and mark.kind == "above":
            dy = weight + MARK_GAP
        elif not touch and mark.kind == "below":
            dy = -(weight + MARK_GAP)
        return [shift(c, x, y + dy) for c in mark.items]

    def mark_parts(self, cp: int, weight: float) -> tuple[list, list]:
        """(base commands, mark commands) of a composite, for collision checks."""
        g = self.by_cp[cp]
        base: list = []
        marks: list = []
        for item in g.items:
            if item[0] == "put" and not item[4] and self.marks[item[1]].kind != "attach":
                marks += self.place(item[1], item[2], item[3], weight)
            elif item[0] == "use":
                base += [shift(c, item[2], item[3]) for c in self.commands(item[1], weight)]
            elif item[0] == "put":
                base += self.place(item[1], item[2], item[3], weight, item[4])
            else:
                base.append(item)
        return base, marks

    def is_composite(self, cp: int) -> bool:
        g = self.by_cp[cp]
        return any(i[0] == "put" and not i[4] and self.marks[i[1]].kind != "attach" for i in g.items)


def shift(cmd, dx: float, dy: float):
    kind = cmd[0]
    if kind == "L":
        return ("L", cmd[1] + dx, cmd[2] + dy, cmd[3] + dx, cmd[4] + dy)
    if kind == "A":
        return ("A", cmd[1] + dx, cmd[2] + dy, *cmd[3:])
    if kind == "Q":
        return ("Q", cmd[1] + dx, cmd[2] + dy, cmd[3] + dx, cmd[4] + dy, cmd[5] + dx, cmd[6] + dy)
    if kind == "D":
        return ("D", cmd[1] + dx, cmd[2] + dy)
    if kind == "F":
        return ("F", *[(x + dx, y + dy) for x, y in cmd[1:]])
    raise ValueError(f"unknown command {kind}")


def _drawing(kind: str, rest: str, n: int, raw: str):
    if kind == "F":
        pts = [_point(t, n) for t in rest.split()]
        if len(pts) < 3:
            raise ValueError(f"line {n}: F needs at least three points: {raw!r}")
        return ("F", *pts)
    nums = [float(t) for t in rest.replace(",", " ").split()]
    if kind == "L" and len(nums) == 4:
        return ("L", *nums)
    if kind == "A" and len(nums) == 6:
        return ("A", *nums)
    if kind == "Q" and len(nums) == 6:
        return ("Q", *nums)
    if kind == "D" and len(nums) == 2:
        return ("D", *nums)
    raise ValueError(f"line {n}: bad command {raw!r}")


def load(path: Path = SOURCE) -> Source:
    """Parse the stroke file. See its header for the commands."""
    glyphs: list[Glyph] = []
    marks: dict[str, Mark] = {}
    current = None
    seen: set[int] = set()
    composites: list[tuple[Glyph, int, list[str], int]] = []

    for n, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        word, _, rest = line.partition(" ")
        rest = rest.strip()
        if word == "glyph":
            # glyph <code> [adv=<units>] [= <base> + <mark> + ...]
            tokens = rest.split()
            if not tokens:
                raise ValueError(f"line {n}: expected 'glyph <code> adv=<units>', got {raw!r}")
            cp = code(tokens.pop(0), n)
            advance = None
            if tokens and tokens[0].startswith("adv="):
                advance = float(tokens.pop(0)[4:])
            recipe: list[str] = []
            if tokens:
                if tokens[0] != "=" or len(tokens) < 2 or tokens[2::2] != ["+"] * len(tokens[2::2]):
                    raise ValueError(f"line {n}: expected 'glyph <code> = <base> + <mark>', got {raw!r}")
                recipe = tokens[1::2]
            elif advance is None:
                raise ValueError(f"line {n}: glyph needs adv= or '= <base>': {raw!r}")
            if cp in seen:
                raise ValueError(f"line {n}: U+{cp:04X} defined twice")
            seen.add(cp)
            current = Glyph(cp, advance, n)
            glyphs.append(current)
            if recipe:
                composites.append((current, code(recipe[0], n), recipe[1:], n))
            continue
        if word == "mark":
            parts = rest.split()
            if len(parts) != 3 or parts[2] not in MARK_KINDS:
                raise ValueError(f"line {n}: expected 'mark <name> <anchor> above|below|attach'")
            if parts[0] in marks:
                raise ValueError(f"line {n}: mark {parts[0]} defined twice")
            current = Mark(parts[0], parts[1], parts[2], n)
            marks[current.name] = current
            continue
        if current is None:
            raise ValueError(f"line {n}: command before any glyph")
        if word == "anchor":
            parts = rest.split()
            if not isinstance(current, Glyph) or len(parts) != 2:
                raise ValueError(f"line {n}: expected 'anchor <name> x,y' inside a glyph")
            current.anchors[parts[0]] = _point(parts[1], n)
        elif word == "use":
            parts = rest.split()
            if not isinstance(current, Glyph) or len(parts) not in (1, 2):
                raise ValueError(f"line {n}: expected 'use <code> [dx,dy]' inside a glyph")
            dx, dy = _point(parts[1], n) if len(parts) == 2 else (0.0, 0.0)
            current.items.append(("use", code(parts[0], n), dx, dy))
        elif word == "put":
            parts = rest.split()
            touch = parts[-1] == "touch"
            if touch:
                parts = parts[:-1]
            if not isinstance(current, Glyph) or len(parts) != 2:
                raise ValueError(f"line {n}: expected 'put <mark> x,y [touch]' inside a glyph")
            x, y = _point(parts[1], n)
            current.items.append(("put", parts[0], x, y, touch))
        elif word in ("L", "A", "Q", "D", "F"):
            current.items.append(_drawing(word, rest, n, raw))
        else:
            raise ValueError(f"line {n}: bad command {raw!r}")

    # 'glyph X = base + mark': the base's strokes, then each mark on its anchor.
    by_cp = {g.cp: g for g in glyphs}
    tmp = Source.__new__(Source)
    tmp.glyphs, tmp.by_cp, tmp.marks = glyphs, by_cp, marks
    # Two passes: every composite first becomes a copy of its base, so a mark
    # can find the anchors of a base that is itself a copy (Cyrillic Е = E).
    for g, base, names, n in composites:
        if base not in by_cp:
            raise ValueError(f"line {n}: base U+{base:04X} is never drawn")
        g.items.insert(0, ("use", base, 0.0, 0.0))
    for g, base, names, n in composites:
        prefix = []
        anchors = tmp.anchors(base)
        for name in names:
            mark = marks.get(name)
            if mark is None:
                raise ValueError(f"line {n}: unknown mark {name!r}")
            if mark.anchor not in anchors:
                raise ValueError(f"line {n}: U+{base:04X} has no '{mark.anchor}' anchor for {name}")
            x, y = anchors[mark.anchor]
            prefix.append(("put", name, x, y, False))
        g.items[1:1] = prefix

    return Source(glyphs, marks)


def parse(path: Path = SOURCE) -> list[tuple[int, float, list]]:
    """[(codepoint, advance, commands at Regular weight)] in file order."""
    src = load(path)
    w = WEIGHTS["regular"]
    return [(g.cp, src.advance(g.cp), src.commands(g.cp, w)) for g in src.glyphs]


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
        elif kind == "F":
            # Filled polygon: the inside is solid, and the edges are stroked
            # like any other line so the corners stay round.
            pts = cmd[1:]
            dots.moveTo(pts[0][0] * SCALE, pts[0][1] * SCALE)
            for x, y in pts[1:]:
                dots.lineTo(x * SCALE, y * SCALE)
            dots.close()
            for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
                center.moveTo(x0 * SCALE, y0 * SCALE)
                center.lineTo(x1 * SCALE, y1 * SCALE)
            has_center = has_dots = True
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
    if len(kept_p) < 3:
        return [], []
    start = next((i for i, flag in enumerate(kept_f) if flag & 1), None)
    if start is None:
        # Every point is off-curve: a valid closed quadratic spline (small
        # circles come out of Cu2Qu this way). Keep it as it is.
        return kept_p, kept_f
    if start:
        kept_p = kept_p[start:] + kept_p[:start]
        kept_f = kept_f[start:] + kept_f[:start]
    return kept_p, kept_f


def _draw_contour(pen, points, flags) -> None:
    if not any(flag & 1 for flag in flags):
        pen.qCurveTo(*points, None)
        pen.closePath()
        return
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


def glyph_name(cp: int) -> str:
    return UV2AGL.get(cp, f"uni{cp:04X}")


def build_weight(st: Style, src: Source) -> tuple[object, int, int]:
    """Return (TTFont, yMin, yMax) for one weight. Vertical metrics are filled later."""
    weight = st.stroke
    is_bold = st.name == "Bold"
    style = st.name
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
    for g in src.glyphs:
        name = glyph_name(g.cp)
        if name in glyf:
            raise ValueError(f"duplicate glyph name {name}")
        order.append(name)
        cmap[g.cp] = name
        add(name, src.commands(g.cp, weight), src.advance(g.cp))
    # U+00A0 shares the space glyph unless the strokes file draws it.
    cmap.setdefault(0x00A0, cmap[0x0020])

    ink = [g for g in glyf.values() if g.numberOfContours]
    y_min = min(int(g.yMin) for g in ink)
    y_max = max(int(g.yMax) for g in ink)

    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyf)
    fb.setupHorizontalMetrics(metrics)
    # Placeholders; main() sets the family line box once every weight exists.
    fb.setupHorizontalHeader(ascent=fu(ASCENDER), descent=fu(DESCENDER), lineGap=0)
    # Regular and Bold are one style-linked family. The other weights are
    # families of their own for old apps, and all five share the typographic
    # family name.
    if st.ribbi:
        family, subfamily = FAMILY, style
        full = FAMILY if style == "Regular" else f"{FAMILY} {style}"
    else:
        family, subfamily = f"{FAMILY} {style}", "Regular"
        full = f"{FAMILY} {style}"
    fb.setupNameTable(
        {
            "copyright": COPYRIGHT,
            "familyName": family,
            "styleName": subfamily,
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
    if not st.ribbi:
        fb.font["name"].setName(FAMILY, 16, 3, 1, 0x409)
        fb.font["name"].setName(style, 17, 3, 1, 0x409)
    panose = Panose()
    panose.bFamilyType = 2          # Latin text
    panose.bSerifStyle = 11         # normal sans
    panose.bWeight = st.panose      # matches the weight class
    panose.bProportion = 3          # modern
    panose.bContrast = 2            # none: the stroke is one width
    panose.bStrokeVariation = 1     # no fit
    panose.bArmStyle = 2            # straight arms, horizontal
    panose.bLetterForm = 2          # normal, contact
    panose.bMidline = 2             # standard, trimmed
    panose.bXHeight = 4             # constant, large
    fb.setupOS2(
        version=4,
        usWeightClass=st.weight_class,
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
    fb.font["head"].fontRevision = float(VERSION)

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


# Line spacing, fixed at the 1.000 values (the ink of Basic Latin in Bold).
# Accents on capitals may rise above it, as in most fonts; usWin covers them.
LINE_ASCENT = 1048
LINE_DESCENT = -340


def apply_family_metrics(fonts: dict[str, object], bounds: dict[str, tuple[int, int]]) -> None:
    """One line box for every weight: hhea and typo give the line spacing,
    usWin covers every glyph so Windows never clips one."""
    y_min = min(b[0] for b in bounds.values())
    y_max = max(b[1] for b in bounds.values())
    typo_asc = LINE_ASCENT
    typo_desc = LINE_DESCENT
    win_asc = max(y_max, LINE_ASCENT)
    win_desc = max(-y_min, -LINE_DESCENT)
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


def _ink(font, ch: str):
    """(yMin, yMax) of a character's outline."""
    glyphs = font.getGlyphSet()
    pen = BoundsPen(glyphs)
    glyphs[font.getBestCmap()[ord(ch)]].draw(pen)
    return otRound(pen.bounds[1]), otRound(pen.bounds[3])


def _zones(pairs):
    """Sorted, non-overlapping alignment zones as a flat list."""
    merged = []
    for lo, hi in sorted((min(a, b), max(a, b)) for a, b in pairs):
        if merged and lo <= merged[-1][1] + 3:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return [v for z in merged for v in z]


def _otf_from(font, weight: float):
    """A CFF (.otf) copy of a built TrueType font: same glyphs, metrics, names and cmap.
    Alignment zones and stems come from the font's own ink, for otfautohint."""
    buf = io.BytesIO()
    font.save(buf)
    buf.seek(0)
    f = TTFont(buf)
    glyphs = f.getGlyphSet()
    widths = f["hmtx"].metrics
    charstrings = {}
    for name in f.getGlyphOrder():
        pen = T2CharStringPen(widths[name][0], glyphs)
        glyphs[name].draw(ReverseContourPen(pen))
        charstrings[name] = pen.getCharString()
    base = [_ink(f, "x")[0], _ink(f, "o")[0]]
    xh = [_ink(f, "x")[1], _ink(f, "o")[1]]
    cap = [_ink(f, "H")[1], _ink(f, "O")[1]]
    asc = [_ink(f, "d")[1], _ink(f, "d")[1]]
    desc = [_ink(f, "p")[0], _ink(f, "p")[0]]
    blues = _zones([base, xh, cap, asc])
    stem = otRound(weight * SCALE)
    for tag in ("glyf", "loca", "gasp", "prep", "fpgm", "cvt "):
        if tag in f:
            del f[tag]
    f.sfntVersion = "OTTO"
    fb = FontBuilder(font=f)
    names = f["name"]
    fb.setupCFF(
        names.getDebugName(6),
        {
            "FullName": names.getDebugName(4),
            "FamilyName": names.getDebugName(1),
            "Weight": names.getDebugName(2),
            "version": VERSION,
            "Notice": COPYRIGHT,
        },
        charstrings,
        {"BlueValues": blues, "OtherBlues": _zones([desc]), "StdHW": stem, "StdVW": stem},
    )
    fb.setupMaxp()
    f["post"].formatType = 3.0
    return f


def _ttfautohint(font) -> bytes:
    """The TrueType font hinted by ttfautohint, stems snapped to whole pixels."""
    import ttfautohint
    from ttfautohint.options import StemWidthMode

    buf = io.BytesIO()
    for tag in ("gasp", "prep", "fpgm", "cvt "):
        if tag in font:
            del font[tag]
    font.flavor = None
    font.save(buf)
    return ttfautohint.ttfautohint(
        in_buffer=buf.getvalue(),
        no_info=True,
        gray_stem_width_mode=StemWidthMode.STRONG,
        gdi_cleartype_stem_width_mode=StemWidthMode.STRONG,
        dw_cleartype_stem_width_mode=StemWidthMode.STRONG,
    )


def save_font(font, style: str) -> Path:
    """Write the hinted .ttf and .woff2, and the hinted .otf."""
    OUT.mkdir(exist_ok=True)
    stem = OUT / f"{FILE_STEM}-{style}"
    weight = WEIGHTS[style.lower()]

    otf = stem.with_suffix(".otf")
    _otf_from(font, weight).save(otf)
    hinter = shutil.which("otfautohint")
    if hinter is None:
        raise SystemExit("otfautohint not found: pip install afdko")
    subprocess.run([hinter, str(otf)], check=True, capture_output=True)

    hinted = _ttfautohint(font)
    ttf = stem.with_suffix(".ttf")
    ttf.write_bytes(hinted)
    web = TTFont(io.BytesIO(hinted))
    web.flavor = "woff2"
    web.save(stem.with_suffix(".woff2"))
    return ttf


def main() -> int:
    src = load()
    fonts = {}
    bounds = {}
    for st in STYLES:
        font, y_min, y_max = build_weight(st, src)
        fonts[st.name] = font
        bounds[st.name] = (y_min, y_max)
    apply_family_metrics(fonts, bounds)
    for st in STYLES:
        path = save_font(fonts[st.name], st.name)
        print(
            f"built {path.relative_to(ROOT)}, .woff2 and .otf "
            f"({len(src.glyphs)} characters, weight {st.stroke})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
