"""Text -> 2D geometry (shapely polygons, mm).

Pipeline: HarfBuzz shaping (kerning, Turkish glyphs) -> fontTools outlines
flattened adaptively -> nonzero-winding polygons -> per-line layout -> scaling.

Conventions:
* Output coordinates are in mm, y up, ink bounding box starts at (0, 0).
* Mode A (``flat``) is scaled so the ink bbox width equals ``width_mm``.
* Mode B (``letters``) is scaled so the font's cap height equals ``cap_height_mm``
  (cap height = OS/2.sCapHeight, falling back to the height of "H").
* ``line_spacing`` 1.0 means a baseline pitch of 1.4 x cap height.
* ``tracking`` is extra advance after each glyph as a fraction of the em.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

from fontTools.pens.basePen import BasePen
from fontTools.ttLib import TTFont
from shapely import affinity
import numpy as np
from shapely.geometry import LinearRing, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union
from shapely.validation import make_valid

from .fonts import ResolvedFont, load_ttfont, missing_glyphs

Mode = Literal["flat", "letters"]

MIN_FEATURE_MM = {"flat": 2.0, "letters": 3.0}
MAX_LETTERS_CHARS = 30
LINE_PITCH_CAP_FACTOR = 1.4
CURVE_TOL_EM = 1e-4  # flattening tolerance as a fraction of the em


# --------------------------------------------------------------------------- #
# Outline extraction
# --------------------------------------------------------------------------- #
class _FlattenPen(BasePen):
    """Pen that flattens curves into polylines (font units)."""

    def __init__(self, glyph_set, tol: float):
        super().__init__(glyph_set)
        self.tol = tol
        self.contours: list[list[tuple[float, float]]] = []
        self._cur: list[tuple[float, float]] = []

    def _moveTo(self, pt):
        self._cur = [pt]

    def _lineTo(self, pt):
        self._cur.append(pt)

    def _qCurveToOne(self, p1, p2):
        p0 = self._getCurrentPoint()
        dev = math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1])
        n = max(2, min(64, math.ceil(math.sqrt(dev / (4 * self.tol)))))
        for i in range(1, n + 1):
            t = i / n
            a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
            self._cur.append((a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]))

    def _curveToOne(self, p1, p2, p3):
        p0 = self._getCurrentPoint()
        d1 = math.hypot(p0[0] - 2 * p1[0] + p2[0], p0[1] - 2 * p1[1] + p2[1])
        d2 = math.hypot(p1[0] - 2 * p2[0] + p3[0], p1[1] - 2 * p2[1] + p3[1])
        n = max(2, min(64, math.ceil(math.sqrt(0.75 * max(d1, d2) / self.tol))))
        for i in range(1, n + 1):
            t = i / n
            a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t**3
            self._cur.append(
                (
                    a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                    a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1],
                )
            )

    def _closePath(self):
        if len(self._cur) >= 3:
            self.contours.append(self._cur)
        self._cur = []

    _endPath = _closePath


def _signed_area(pts: list[tuple[float, float]]) -> float:
    s = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        s += x0 * y1 - x1 * y0
    return s / 2


def _winding(contour: np.ndarray, pt: tuple[float, float]) -> int:
    """Winding number of a closed contour around ``pt`` (crossing-number with direction)."""
    x0, y0 = contour[:, 0], contour[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    px, py = pt
    up = (y0 <= py) & (y1 > py)
    down = (y0 > py) & (y1 <= py)
    cross = (x1 - x0) * (py - y0) - (px - x0) * (y1 - y0)
    return int(np.sum(up & (cross > 0)) - np.sum(down & (cross < 0)))


def contours_to_geometry(contours: list[list[tuple[float, float]]]) -> BaseGeometry:
    """True nonzero-winding fill of the contours (overlapping contours, as in variable fonts,
    must stay filled where the winding numbers add up). The contours are noded, split into
    faces, and a face is ink when its winding number is not zero."""
    contours = [c for c in contours if len(c) >= 3 and abs(_signed_area(c)) > 1e-9]
    if not contours:
        return Polygon()
    arrs = [np.asarray(c, dtype=float) for c in contours]
    noded = unary_union([LinearRing(c) for c in contours])
    faces = list(polygonize(noded))
    ink = []
    for f in faces:
        pt = f.representative_point()
        if sum(_winding(a, (pt.x, pt.y)) for a in arrs) != 0:
            ink.append(f)
    return _polys_only(unary_union(ink)) if ink else Polygon()


def _polys_only(geom: BaseGeometry) -> BaseGeometry:
    """Drop non-areal parts (lines/points) that boolean ops can leave behind."""
    if geom.is_empty:
        return Polygon()
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    polys = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon) and not g.is_empty]
    return unary_union(polys) if polys else Polygon()


@lru_cache(maxsize=8)
def _hb_font(path: str, axes: tuple[tuple[str, float], ...]):
    import uharfbuzz as hb

    from .fonts import _load_ttfont

    font = _load_ttfont(path, axes)
    buf = io.BytesIO()
    font.save(buf)
    face = hb.Face(buf.getvalue())
    return hb.Font(face)


def font_cap_height(font: TTFont) -> float:
    """Cap height in font units (OS/2.sCapHeight, else height of 'H')."""
    os2 = font["OS/2"] if "OS/2" in font else None
    cap = getattr(os2, "sCapHeight", 0) if os2 is not None else 0
    if cap and cap > 0:
        return float(cap)
    cmap = font.getBestCmap()
    gs = font.getGlyphSet()
    pen = _FlattenPen(gs, font["head"].unitsPerEm * CURVE_TOL_EM)
    gs[cmap[ord("H")]].draw(pen)
    ys = [y for c in pen.contours for _, y in c]
    return float(max(ys))


# --------------------------------------------------------------------------- #
# Layout
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class PlacedGlyph:
    char: str
    line: int
    geometry: BaseGeometry  # mm, final coordinates


@dataclass(frozen=True)
class Piece:
    """A connected group of glyphs (one physical part)."""

    text: str
    geometry: BaseGeometry  # Polygon or MultiPolygon (e.g. a letter plus its dots)
    glyph_indices: tuple[int, ...]


@dataclass
class TextResult:
    text: str
    mode: str
    geometry: BaseGeometry  # union of everything, mm, bbox min at (0, 0)
    glyphs: list[PlacedGlyph]
    pieces: list[Piece]
    scale: float  # mm per font unit
    cap_height_mm: float
    baseline_y: float  # y of first line baseline (mm)
    width_mm: float
    height_mm: float
    lines: list[str]
    warnings: list[str] = field(default_factory=list)
    line_baselines: list[float] = field(default_factory=list)  # y of each line's baseline (mm)


def _shape_line(font: TTFont, hbfont, line: str, tracking_units: float, language: str | None = None):
    """Return [(char_index, glyph_name, x, y)] and the line advance width (font units).

    ``language`` (BCP 47, e.g. "tr") selects the font's ``locl`` forms, e.g. dotted small-cap i in Cinzel.
    """
    import uharfbuzz as hb

    buf = hb.Buffer()
    buf.add_str(line)
    buf.guess_segment_properties()
    if language:
        buf.language = language
    hb.shape(hbfont, buf, {"kern": True, "liga": False})
    order = font.getGlyphOrder()
    out = []
    x = 0.0
    n = len(buf.glyph_infos)
    for i, (info, pos) in enumerate(zip(buf.glyph_infos, buf.glyph_positions)):
        out.append((info.cluster, order[info.codepoint], info.codepoint, x + pos.x_offset, pos.y_offset))
        x += pos.x_advance + (tracking_units if i < n - 1 else 0.0)
    return out, x


def _group_glyphs(glyphs: list[PlacedGlyph]) -> list[Piece]:
    """Connected components of glyphs that overlap or touch."""
    n = len(glyphs)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if glyphs[i].geometry.intersects(glyphs[j].geometry):
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    pieces = []
    for idx in sorted(groups.values(), key=lambda g: g[0]):
        geom = unary_union([glyphs[i].geometry for i in idx])
        pieces.append(Piece("".join(glyphs[i].char for i in idx), _polys_only(geom), tuple(idx)))
    return pieces


def thin_regions(geometry: BaseGeometry, min_width_mm: float) -> list[BaseGeometry]:
    """Regions of ``geometry`` thinner than ``min_width_mm``.

    Morphological opening removes everything narrower than ``min_width_mm``. Residue
    within 2.5 r of the surviving body is ignored: it is just corner/terminal tapering
    (every sharp tip is "thin" at its very end), not a thin stroke. What remains are
    thin strokes/hairlines of real length and isolated thin glyphs.
    """
    r = min_width_mm / 2.0
    opened = geometry.buffer(-r, join_style="round").buffer(r, join_style="round")
    residue = _polys_only(geometry.difference(opened.buffer(1e-6)))
    if not opened.is_empty:
        residue = _polys_only(residue.difference(opened.buffer(2.5 * r, join_style="round")))
    parts = list(getattr(residue, "geoms", [residue]))
    return [p for p in parts if not p.is_empty and p.area > 4.0 * r * r]


def build_text(
    text: str,
    font: ResolvedFont,
    mode: Mode = "flat",
    *,
    width_mm: float | None = None,
    cap_height_mm: float | None = None,
    tracking: float = 0.0,
    line_spacing: float = 1.0,
    align: Literal["left", "center", "right"] = "center",
    min_feature_mm: float | None = None,
    language: str | None = None,
) -> TextResult:
    """Lay out ``text`` and return mm geometry. See module docstring for conventions."""
    if mode not in ("flat", "letters"):
        raise ValueError(f"unknown mode {mode!r}")
    if not text or not text.strip():
        raise ValueError("text is empty")
    warnings: list[str] = list(font.warnings)

    lines = [ln.rstrip() for ln in text.split("\n")]
    lines = [ln for ln in lines if ln.strip()]
    if mode == "letters":
        if len(lines) > 1:
            warnings.append("Letters mode supports a single line; lines were joined with a space.")
            lines = [" ".join(ln.strip() for ln in lines)]
        if len(lines[0]) > MAX_LETTERS_CHARS:
            raise ValueError(f"Letters mode supports at most {MAX_LETTERS_CHARS} characters")
        if cap_height_mm is None:
            raise ValueError("letters mode requires cap_height_mm")
    else:
        if len(lines) > 2:
            warnings.append(f"Flat mode is designed for 1-2 lines; got {len(lines)} lines.")
        if width_mm is None:
            raise ValueError("flat mode requires width_mm")

    ttfont = load_ttfont(font)
    upem = ttfont["head"].unitsPerEm
    missing = missing_glyphs(ttfont, "".join(lines))
    if missing:
        warnings.append(
            f"Font '{font.spec.name}' has no glyph for: {' '.join(missing)} (these characters are skipped)."
        )
    cap_units = font_cap_height(ttfont)
    pitch = line_spacing * LINE_PITCH_CAP_FACTOR * cap_units
    tol = upem * CURVE_TOL_EM
    hbfont = _hb_font(str(font.path), font.spec.axes)
    glyph_set = ttfont.getGlyphSet()
    shape_cache: dict[str, BaseGeometry] = {}

    def glyph_geom(name: str) -> BaseGeometry:
        if name not in shape_cache:
            pen = _FlattenPen(glyph_set, tol)
            glyph_set[name].draw(pen)
            shape_cache[name] = contours_to_geometry(pen.contours)
        return shape_cache[name]

    cmap = ttfont.getBestCmap()
    placed: list[tuple[str, int, BaseGeometry]] = []  # (char, line, geometry in font units)
    shaped = [
        _shape_line(ttfont, hbfont, ln, tracking * upem, language) for ln in lines
    ]
    max_adv = max(adv for _, adv in shaped)
    for li, (items, adv) in enumerate(shaped):
        if align == "left":
            x0 = 0.0
        elif align == "right":
            x0 = max_adv - adv
        else:
            x0 = (max_adv - adv) / 2
        y0 = -li * pitch
        for cluster, gname, gid, gx, gy in items:
            ch = lines[li][cluster]
            if gid == 0 or ord(ch) not in cmap:
                continue  # missing glyph: skipped (warned above)
            geom = glyph_geom(gname)
            if geom.is_empty:
                continue  # whitespace
            placed.append((ch, li, affinity.translate(geom, x0 + gx, y0 + gy)))
    if not placed:
        raise ValueError("no drawable glyphs in text")

    union_units = unary_union([g for _, _, g in placed])
    minx, miny, maxx, maxy = union_units.bounds
    ink_w = maxx - minx
    scale = (width_mm / ink_w) if mode == "flat" else (cap_height_mm / cap_units)

    def finish(g: BaseGeometry) -> BaseGeometry:
        g = affinity.translate(g, -minx, -miny)
        return affinity.scale(g, scale, scale, origin=(0, 0))

    glyphs = [PlacedGlyph(ch, li, finish(g)) for ch, li, g in placed]
    geometry = _polys_only(finish(union_units))
    pieces = _group_glyphs(glyphs)
    b = geometry.bounds

    result = TextResult(
        text="\n".join(lines),
        mode=mode,
        geometry=geometry,
        glyphs=glyphs,
        pieces=pieces,
        scale=scale,
        cap_height_mm=cap_units * scale,
        baseline_y=-miny * scale,
        width_mm=b[2] - b[0],
        height_mm=b[3] - b[1],
        lines=lines,
        warnings=warnings,
        line_baselines=[(-li * pitch - miny) * scale for li in range(len(lines))],
    )
    limit = MIN_FEATURE_MM[mode] if min_feature_mm is None else min_feature_mm
    thin = thin_regions(geometry, limit)
    if thin:
        cx, cy = thin[0].centroid.x, thin[0].centroid.y
        warnings.append(
            f"{len(thin)} feature(s) thinner than {limit:.1f} mm at this size "
            f"(e.g. near x={cx:.0f} mm, y={cy:.0f} mm); they may print poorly or break."
        )
    return result


def text_outline(text: str, font: ResolvedFont, *, width_mm: float | None = None, cap_height_mm: float | None = None,
                 min_feature_mm: float | None = None, language: str | None = None):
    """Flat text outline (bbox min at 0,0) ``width_mm`` wide, or with capitals ``cap_height_mm`` tall; returns
    (geometry, warnings). One line or two (``\\n``)."""
    if width_mm is None:
        probe = build_text(text, font, "flat", width_mm=100.0, min_feature_mm=0.0, language=language)
        width_mm = 100.0 * cap_height_mm / probe.cap_height_mm
    res = build_text(text, font, "flat", width_mm=width_mm, min_feature_mm=min_feature_mm, language=language)
    return res.geometry, list(res.warnings)


def stretch_x(layout: TextResult, k: float) -> TextResult:
    """Scale every glyph, piece and the union geometry by ``k`` along X (about x=0); Y is unchanged.

    Used for a fixed letter width: positions scale with the glyphs, so spacing stays proportional."""
    from dataclasses import replace

    if k <= 0:
        raise ValueError("stretch factor must be > 0")
    sx = lambda g: affinity.scale(g, xfact=k, yfact=1.0, origin=(0, 0))  # noqa: E731
    return replace(
        layout,
        geometry=sx(layout.geometry),
        glyphs=[replace(g, geometry=sx(g.geometry)) for g in layout.glyphs],
        pieces=[replace(p, geometry=sx(p.geometry)) for p in layout.pieces],
        width_mm=layout.width_mm * k,
    )
