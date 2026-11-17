"""Geometry helpers (mm): projection, model outlines, heightfield solids, prisms and text outlines."""
from __future__ import annotations

import math
from dataclasses import dataclass

import manifold3d as m3
import numpy as np
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import unary_union
from workbench_core.fonts import resolve_font, with_weight
from workbench_core.shapes import shape_polygon
from workbench_core.text2d import text_outline


SHAPES = {"rect": "Dikdörtgen", "square": "Kare", "circle": "Daire", "octagon": "Sekizgen",
          "hexagon": "Altıgen", "heart": "Kalp"}


@dataclass(frozen=True)
class Projection:
    """Local equirectangular projection: (lat, lon) -> model mm with (0, 0) at the area centre."""
    lat0: float
    lon0: float
    mm_per_m: float

    def m(self, lat, lon):
        x = (np.asarray(lon) - self.lon0) * 111320.0 * math.cos(math.radians(self.lat0))
        y = (np.asarray(lat) - self.lat0) * 110540.0
        return x, y

    def mm(self, lat, lon):
        x, y = self.m(lat, lon)
        return x * self.mm_per_m, y * self.mm_per_m

    def inv(self, x_mm, y_mm):
        lon = self.lon0 + np.asarray(x_mm) / self.mm_per_m / (111320.0 * math.cos(math.radians(self.lat0)))
        lat = self.lat0 + np.asarray(y_mm) / self.mm_per_m / 110540.0
        return lat, lon

    @property
    def scale(self) -> int:
        """Map scale denominator (1:N)."""
        return int(round(1000.0 / self.mm_per_m))


def outline(shape: str, w: float, h: float) -> Polygon:
    """Model footprint centred on the origin (w x h mm bounding box): sharp corners, fine curves (shared shapes)."""
    return shape_polygon(shape, w, h, rounded=False, segments={"heart": 400, "circle": 128}.get(shape))


def polys(g) -> list[Polygon]:
    """Flatten any shapely geometry into its polygons."""
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for sub in getattr(g, "geoms", []) for p in polys(sub)]


def cross_section(g, min_area: float = 0.02) -> m3.CrossSection | None:
    rings = []
    # a 0.01 mm mitred grow fuses shapes that only touch at a corner or edge (those would
    # become non-manifold edges in the mesh); far below printer resolution
    if g is not None and not g.is_empty:
        g = g.buffer(0.01, join_style="mitre", mitre_limit=2.0)
    for p in polys(g):
        if p.area < min_area:
            continue
        p = p.simplify(0.02)
        rings.append(np.asarray(p.exterior.coords)[:-1])
        rings += [np.asarray(i.coords)[:-1] for i in p.interiors]
    if not rings:
        return None
    return m3.CrossSection(rings, m3.FillRule.EvenOdd)


def prism(g, z0: float, z1: float) -> m3.Manifold:
    cs = cross_section(g)
    if cs is None or z1 <= z0:
        return m3.Manifold()
    return cs.extrude(z1 - z0).translate([0, 0, z0])


def heightfield(xs: np.ndarray, ys: np.ndarray, z: np.ndarray, z0: float = 0.0) -> m3.Manifold:
    """Closed solid between z0 and the surface z[row, col] over the grid xs (cols) x ys (rows)."""
    ny, nx = z.shape
    X, Y = np.meshgrid(xs, ys)
    n = nx * ny
    idx = np.arange(n).reshape(ny, nx)
    v = np.vstack([np.c_[X.ravel(), Y.ravel(), z.ravel()], np.c_[X.ravel(), Y.ravel(), np.full(n, z0)]])
    a, b = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
    c, d = idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
    f = [np.c_[a, b, c], np.c_[a, c, d], np.c_[a + n, c + n, b + n], np.c_[a + n, d + n, c + n]]

    def wall(e, flip):
        p, q = e[:-1], e[1:]
        t1, t2 = np.c_[p, q, q + n], np.c_[p, q + n, p + n]
        if flip:
            t1, t2 = t1[:, [0, 2, 1]], t2[:, [0, 2, 1]]
        f.extend([t1, t2])

    wall(idx[0, :], True)
    wall(idx[-1, :], False)
    wall(idx[:, 0], False)
    wall(idx[:, -1], True)
    mf = m3.Manifold(m3.Mesh(v.astype(np.float32), np.vstack(f).astype(np.uint32)))
    if mf.status() != m3.Error.NoError or mf.is_empty():
        raise RuntimeError(f"heightfield is not manifold: {mf.status()}")
    return mf


def sample_grid(xs: np.ndarray, ys: np.ndarray, z: np.ndarray, x, y) -> np.ndarray:
    """Bilinear sample of the grid at points (mm)."""
    from scipy.ndimage import map_coordinates

    dx, dy = xs[1] - xs[0], ys[1] - ys[0]
    return map_coordinates(z, [(np.asarray(y) - ys[0]) / dy, (np.asarray(x) - xs[0]) / dx], order=1, mode="nearest")


def max_under(xs, ys, z, poly) -> float:
    """Highest grid value inside (or, for tiny polygons, around) ``poly``."""
    from shapely import contains_xy

    x0, y0, x1, y1 = poly.bounds
    ci = np.nonzero((xs >= x0 - 1e-9) & (xs <= x1 + 1e-9))[0]
    ri = np.nonzero((ys >= y0 - 1e-9) & (ys <= y1 + 1e-9))[0]
    if len(ci) and len(ri):
        X, Y = np.meshgrid(xs[ci], ys[ri])
        m = contains_xy(poly, X, Y)
        if m.any():
            return float(z[np.ix_(ri, ci)][m].max())
    c = poly.representative_point()
    return float(sample_grid(xs, ys, z, [c.x], [c.y])[0])


def to_mesh(mf: m3.Manifold):
    import trimesh

    mm = mf.to_mesh()
    return trimesh.Trimesh(np.asarray(mm.vert_properties)[:, :3], np.asarray(mm.tri_verts), process=False)


# --------------------------------------------------------------------------- text



def text_shape(text: str, height_mm: float, font: str | None = None):
    """Outline of ``text`` with capitals ``height_mm`` tall (Montserrat Bold by default), bottom-left at the origin.
    The shared text engine: kerning, Turkish letters, the same fonts as every Workbench program."""
    if not text.strip():
        return Polygon()
    f = resolve_font(font) if font else with_weight(resolve_font("Montserrat"), 700)
    g, _ = text_outline(text, f, cap_height_mm=height_mm, min_feature_mm=0.0, language="tr")
    return g


def fit_text(text: str, box_w: float, box_h: float, font=None):
    """Text scaled to fit inside box_w x box_h, centred at the origin."""
    g = text_shape(text, box_h, font)
    if g.is_empty:
        return g
    x0, y0, x1, y1 = g.bounds
    k = min(1.0, box_w / max(x1 - x0, 1e-6), box_h / max(y1 - y0, 1e-6))
    g = affinity.scale(g, k, k, origin=(0, 0))
    x0, y0, x1, y1 = g.bounds
    return affinity.translate(g, -(x0 + x1) / 2, -(y0 + y1) / 2)


# --------------------------------------------------------------------------- markers
def marker_shape(kind: str, size: float) -> Polygon:
    """Pin / heart / star / dot outline (size = height in mm), anchored so the tip/centre is at the origin."""
    if kind == "heart":
        return outline("heart", size * 1.1, size)
    if kind == "star":
        pts = []
        for i in range(10):
            r = size / 2 if i % 2 == 0 else size / 5
            a = math.pi / 2 + i * math.pi / 5
            pts.append((r * math.cos(a), r * math.sin(a)))
        return Polygon(pts)
    if kind == "pin":
        head = Point(0, size * 0.62).buffer(size * 0.36, 48)
        tip = Polygon([(-size * 0.3, size * 0.45), (size * 0.3, size * 0.45), (0, 0)])
        hole = Point(0, size * 0.62).buffer(size * 0.14, 32)
        return unary_union([head, tip]).difference(hole)
    return Point(0, 0).buffer(size / 2, 48)


def line_poly(coords, width: float):
    return LineString(coords).buffer(width / 2, cap_style="round", join_style="round")


def river_shape(line: LineString, base_w: float, seed: int = 0, *, growth: float = 0.55, wobble: float = 0.3,
                min_w: float = 0.8) -> Polygon:
    """A river that looks like one: it widens downstream (OSM waterways are drawn in the flow direction) and keeps
    swelling and narrowing along its course. ``base_w``: width (mm) at the source; at the mouth it is ``1 + growth``
    times wider, and ``wobble`` adds smooth +- variation (wavelength ~6-14 river widths, fixed per ``seed`` so the
    same river is always drawn the same). Never narrower than ``min_w`` (printable)."""
    length = line.length
    if length <= 0:
        return Polygon()
    step = max(base_w * 0.6, 0.4)
    n = max(2, int(math.ceil(length / step)) + 1)
    s = np.linspace(0.0, length, n)
    rng = np.random.default_rng(seed)
    lam = base_w * rng.uniform(6, 14, 3)  # three smooth waves, phases from the seed
    ph = rng.uniform(0, 2 * math.pi, 3)
    w = sum(np.sin(2 * math.pi * s / lam[i] + ph[i]) for i in range(3)) / 3  # -1..1, mostly within +-0.6
    f = (1 + growth * s / length) * (1 + wobble * w)
    widths = np.maximum(base_w * f, min_w)
    pts = [line.interpolate(d) for d in s]
    discs = [p.buffer(r / 2, quad_segs=8) for p, r in zip(pts, widths)]
    pieces = [unary_union([a, b]).convex_hull for a, b in zip(discs[:-1], discs[1:])]  # tapered segment between samples
    return unary_union(pieces)


def line_seed(line: LineString) -> int:
    """Stable seed from a line's geometry (same river -> same wobble)."""
    c = line.coords
    return int(abs(hash((round(c[0][0], 2), round(c[0][1], 2), round(c[-1][0], 2), round(c[-1][1], 2), len(c)))) % (2 ** 31))
