"""Thermoform geometry: outline clean-up, dome height field, press molds (female + male), back plate and glued rim.

Frames: the *ornament frame* is how the finished ornament is seen (dome up, readable). The sheet is formed convex side
down in the female cavity and flipped afterwards, so the female cavity is the ornament rotated 180 deg about X; the male
mold is printed plug-up, which (flipped onto the female) brings it back to the ornament frame.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import shapely
import trimesh
from scipy import ndimage, sparse
from scipy.interpolate import RegularGridInterpolator
from scipy.sparse.linalg import spsolve
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import polylabel, unary_union

from . import core
from .sheets import Sheet

RX = np.diag([1.0, -1.0, -1.0, 1.0])  # 180 deg about X: female frame <-> ornament frame
EPS = 0.6  # solids reach this far below z=0 so booleans never meet coplanar faces


def _largest(g) -> tuple[Polygon, int]:
    polys = [p for p in getattr(g, "geoms", [g]) if isinstance(p, Polygon) and not p.is_empty]
    if not polys:
        raise ValueError("Şekil boş kaldı; daha büyük bir boyut ya da başka bir şekil deneyin.")
    polys.sort(key=lambda p: p.area, reverse=True)
    return polys[0], len(polys) - 1


def solid_outline(geom, bridge_mm: float = 0.0) -> tuple[Polygon, list[str]]:
    """One hole-free silhouette: pieces are merged with ``bridge_mm`` (bubble lettering), stray bits dropped."""
    warnings = []
    g = unary_union(geom)
    if bridge_mm > 0:
        g = g.buffer(bridge_mm, quad_segs=16)
    poly, dropped = _largest(g)
    if dropped:
        warnings.append(f"Şekil tek parça değil: en büyük parça kullanıldı, {dropped} küçük parça atıldı.")
    return Polygon(poly.exterior), warnings


def clean_outline(poly: Polygon, sheet: Sheet, depth: float) -> tuple[Polygon, list[str]]:
    """Round every corner to the sheet's minimum radius, flag thin necks and too-deep draws."""
    warnings = []
    r = sheet.min_radius_mm
    a0 = poly.area
    g = poly.buffer(-r, quad_segs=16).buffer(r, quad_segs=16)  # convex corners
    g = g.buffer(r, quad_segs=16).buffer(-r, quad_segs=16)  # concave corners (where the sheet tears or webs)
    g, dropped = _largest(g)
    g = Polygon(g.exterior)
    if dropped:
        warnings.append(f"{2 * r:g} mm'den ince kısımlar levhada oluşmaz; {dropped} parça atıldı.")
    if abs(g.area - a0) / a0 > 0.03:
        warnings.append(f"Keskin köşeler {r:g} mm yarıçapa yuvarlatıldı (alan %{abs(g.area - a0) / a0 * 100:.0f} değişti).")
    neck = max(4 * r, 8.0)
    opened = g.buffer(-neck / 2, quad_segs=8).buffer(neck / 2, quad_segs=8)
    if isinstance(opened, MultiPolygon) or opened.is_empty:
        lost, _ = _largest(g.difference(opened))
        c = lost.representative_point()
        warnings.append(f"Şeklin {neck:g} mm'den dar bir boynu var (x={c.x:.0f}, y={c.y:.0f} mm civarı): levha orada "
                        "yırtılabilir ya da kırışabilir. Şekli kalınlaştırın.")
    inr = polylabel(g, tolerance=0.2).distance(g.exterior)
    if depth > sheet.max_draw * 2 * inr:
        warnings.append(f"Kubbe {depth:g} mm bu şekil için derin: {sheet.label} en çok ~{sheet.max_draw * 2 * inr:.0f} mm "
                        "çekilebilir, fazlası levhayı inceltir ya da yırtar.")
    return g, warnings


def centred(poly: Polygon) -> Polygon:
    x0, y0, x1, y1 = poly.bounds
    return affinity.translate(poly, -(x0 + x1) / 2, -(y0 + y1) / 2)


PROFILES_TR = {"pillow": "Yastık", "flat": "Düz üst + pah", "stepped": "Basamaklı", "dome": "Kubbe (küre)"}


@dataclass
class Relief:
    """Text / logo formed into the shell: raised (+) or sunk (-) by ``height_mm``, 45 deg flanks."""
    geometry: object  # shapely geometry, ornament frame
    height_mm: float
    raised: bool = True


def _lipschitz(h: np.ndarray, slope: float, cell: float) -> np.ndarray:
    """Largest field below ``h`` whose slope never exceeds ``slope`` (min over q of h(q) + slope*|p-q|).
    Iterated small-disc erosion: exact up to the disc's polygonal approximation of distance."""
    k = 3
    dy, dx = np.mgrid[-k:k + 1, -k:k + 1] * cell
    r = np.hypot(dx, dy)
    fp = r <= k * cell + 1e-9
    cone = -slope * r
    for _ in range(int(np.ceil(h.max() / (slope * k * cell))) + 2):
        nh = ndimage.grey_erosion(h, footprint=fp, structure=cone, mode="constant", cval=0.0)
        if np.allclose(nh, h, atol=1e-6):
            break
        h = nh
    return h


class Dome:
    """Dome over an outline, shaped by a profile, limited to the mold draft angle, optionally with relief.

    pillow: Poisson 'inflation' u (lap u = -1, u = 0 on the edge), z = depth * (1 - (1 - u/umax)^1.5)
    dome: z = depth * sqrt(u/umax) (a hemisphere for a circle; its vertical rim is cut back by the draft limit)
    flat / stepped: from the distance to the edge, 45 deg flanks, softened by ``soften_mm``.
    """

    def __init__(self, outline: Polygon, depth: float, cell: float | None = None, *, profile: str = "pillow",
                 draft_deg: float = 5.0, steps: int = 3, soften_mm: float = 1.0, relief: Relief | None = None):
        if profile not in PROFILES_TR:
            raise ValueError(f"bilinmeyen kubbe profili: {profile}")
        self.outline, self.depth, self.profile, self.draft_deg = outline, depth, profile, draft_deg
        x0, y0, x1, y1 = outline.bounds
        c = self.cell = cell or max(0.35, max(x1 - x0, y1 - y0) / 220)
        self.xs = np.arange(x0 - 2 * c, x1 + 3 * c, c)
        self.ys = np.arange(y0 - 2 * c, y1 + 3 * c, c)
        X, Y = np.meshgrid(self.xs, self.ys)
        inside = shapely.contains_xy(outline, X, Y)
        if profile in ("pillow", "dome"):
            t = self._poisson(inside, c)
            h = depth * ((1 - (1 - t) ** 1.5) if profile == "pillow" else np.sqrt(t))
        else:
            d = np.maximum(ndimage.distance_transform_edt(inside) * c - c / 2, 0)
            if profile == "flat":
                h = np.minimum(d, depth)
            else:
                n = max(2, steps)
                rise = depth / n
                tread = max(3.0, (d.max() - depth) / n)  # spread the terraces over the shape
                h = sum(np.clip(d - i * (rise + tread), 0, rise) for i in range(n))
            if soften_mm > 0:
                h = ndimage.gaussian_filter(h, soften_mm / c / (2 if profile == "stepped" else 1)) * inside
            h *= depth / max(h.max(), 1e-9) if profile == "stepped" else 1.0
        if relief is not None:
            rin = shapely.contains_xy(relief.geometry, X, Y) & inside
            dr = np.maximum(ndimage.distance_transform_edt(rin) * c - c / 2, 0)
            h = h + (1 if relief.raised else -1) * np.minimum(dr, relief.height_mm)
            h = np.maximum(h, 0)
        self.slope_max = np.tan(np.radians(90 - draft_deg))
        h = _lipschitz(h * inside, self.slope_max, c)
        self.grid_h = h
        gy, gx = np.gradient(h, c)
        self._h = RegularGridInterpolator((self.ys, self.xs), h, bounds_error=False, fill_value=0.0)
        self._s2 = RegularGridInterpolator((self.ys, self.xs), gx ** 2 + gy ** 2, bounds_error=False, fill_value=0.0)
        self._offsets: dict = {}

    @staticmethod
    def _poisson(inside: np.ndarray, c: float) -> np.ndarray:
        n = int(inside.sum())
        idx = -np.ones(inside.shape, dtype=np.int64)
        idx[inside] = np.arange(n)
        rows, cols = [np.arange(n)], [np.arange(n)]
        vals = [np.full(n, 4.0)]
        iy, ix = np.nonzero(inside)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            j = idx[iy + dy, ix + dx]  # the grid has a 2-cell border, so no wrap-around
            ok = j >= 0
            rows.append(idx[iy, ix][ok]), cols.append(j[ok]), vals.append(np.full(ok.sum(), -1.0))
        A = sparse.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))
        u = np.zeros(inside.shape)
        u[inside] = spsolve(A, np.full(n, c * c))
        return u / u.max()

    @property
    def max_height(self) -> float:
        return float(self.grid_h.max())

    def steepest_wall_deg(self) -> float:
        """Steepest dome wall, degrees from horizontal (90 = vertical)."""
        gy, gx = np.gradient(self.grid_h, self.cell)
        return float(np.degrees(np.arctan(np.sqrt(gx ** 2 + gy ** 2).max())))

    def height(self, xy: np.ndarray) -> np.ndarray:
        """Dome height at points (N,2); exactly 0 on and outside the outline."""
        h = self._h(xy[:, ::-1])
        d = shapely.distance(self.outline.exterior, shapely.points(xy))
        inside = shapely.contains_xy(self.outline, xy[:, 0], xy[:, 1])
        return np.where(inside, np.minimum(h * np.clip(d / (1.5 * self.cell), 0, 1), self.slope_max * d), 0.0)

    def offset_height(self, xy: np.ndarray, gap: float) -> np.ndarray:
        """Male plug height: the surface exactly ``gap`` mm away from the dome (ball erosion of the height field, so the
        offset also holds at the cavity rim and in valleys), measured from a base plane ``gap`` mm above z=0."""
        key = round(gap, 4)
        if key not in self._offsets:
            c = min(self.cell, gap / 3)
            xs = np.arange(self.xs[0], self.xs[-1] + c / 2, c)
            ys = np.arange(self.ys[0], self.ys[-1] + c / 2, c)
            X, Y = np.meshgrid(xs, ys)
            h = self.height(np.c_[X.ravel(), Y.ravel()]).reshape(X.shape)
            k = int(np.ceil(gap / c))
            dy, dx = np.mgrid[-k:k + 1, -k:k + 1] * c
            r2 = dx ** 2 + dy ** 2
            ball = np.sqrt(np.clip(gap * gap - r2, 0, None))
            er = ndimage.grey_erosion(h, footprint=r2 <= gap * gap, structure=ball, mode="constant", cval=0.0)
            self._offsets[key] = RegularGridInterpolator((ys, xs), er + gap, bounds_error=False, fill_value=0.0)
        return self._offsets[key](xy[:, ::-1])

    def slope2(self, xy: np.ndarray) -> np.ndarray:
        """Squared gradient of the dome (grid gradient; the edge taper band is ~1 cell and ignored)."""
        return self._s2(xy[:, ::-1])

    def peaks(self, max_n: int = 4) -> list[tuple[float, float]]:
        """Local maxima of the dome (vent positions), highest first."""
        h = self.grid_h
        size = max(3, int(round(8 / self.cell)))
        pk = (h == ndimage.maximum_filter(h, size=size)) & (h > 0.5 * h.max())
        iy, ix = np.nonzero(pk)
        order = np.argsort(-h[iy, ix])
        out: list[tuple[float, float]] = []
        for k in order:
            p = (float(self.xs[ix[k]]), float(self.ys[iy[k]]))
            if all(np.hypot(p[0] - q[0], p[1] - q[1]) > 20 for q in out):
                out.append(p)
            if len(out) == max_n:
                break
        return out


def _heightfield_solid(outline: Polygon, top, bottom: float, seg: float) -> trimesh.Trimesh:
    """Solid over ``outline`` from z=bottom up to z=top(xy) (top must stay above bottom)."""
    m = core.extrude(outline, 0.0, 1.0).refine_to_length(seg)

    def warp(v):
        v = np.array(v, dtype=np.float64)
        zt = top(v[:, :2])
        v[:, 2] = bottom + v[:, 2] * (zt - bottom)
        return v

    return core.to_trimesh(m.warp_batch(warp))


def _rounded_rect(w: float, h: float, r: float = 6.0) -> Polygon:
    return box(-w / 2 + r, -h / 2 + r, w / 2 - r, h / 2 - r).buffer(r, quad_segs=12)


@dataclass
class MoldSet:
    female: trimesh.Trimesh
    male: trimesh.Trimesh
    sheet_size_mm: tuple[float, float]
    block_mm: tuple[float, float]
    gap_mm: float
    female_top_z: float
    male_base_mm: float
    vents: list[tuple[float, float]]
    offsets: list[tuple[float, float]] = field(default_factory=lambda: [(0.0, 0.0)])


CLAMP_MM = 10.0  # flat sheet border around the shape (held by hand / clamps)
PIN_ZONE_MM = 10.0  # block border outside the sheet, carries the alignment pins
PIN_D, PIN_CLEAR = 6.0, 0.5
FLOOR_MM, MALE_BASE_MM = 3.0, 4.0
PLATE_MM = 2.4  # economy molds: thin plate that only carries the pins
ARM_W = 10.0
VENT_D = 1.5


def cavity_layout(outline: Polygon, n: int, flange_mm: float) -> tuple[list[tuple[float, float]], int]:
    """Offsets for up to ``n`` copies of the shape on one sheet/mold (cut lines never touch), most compact grid that
    fits the bed with the sheet border and pin zone; returns (offsets centred on 0, copies that fit)."""
    x0, y0, x1, y1 = outline.bounds
    w, h = x1 - x0, y1 - y0
    pitch_x, pitch_y = w + 2 * flange_mm + 3, h + 2 * flange_mm + 3
    border = 2 * (CLAMP_MM + PIN_ZONE_MM)
    for k in range(n, 0, -1):
        best = None
        for cols in range(1, k + 1):
            rows = -(-k // cols)
            bw = w + (cols - 1) * pitch_x + border
            bh = h + (rows - 1) * pitch_y + border
            if bw <= core.BED_MM and bh <= core.BED_MM and (best is None or max(bw, bh) < best[0]):
                best = (max(bw, bh), cols, rows)
        if best:
            _, cols, rows = best
            offs = [((i % cols - (cols - 1) / 2) * pitch_x, ((rows - 1) / 2 - i // cols) * pitch_y) for i in range(k)]
            return offs, k
    return [(0.0, 0.0)], 1


def _footprint(outlines: list[Polygon], bw: float, bh: float, pins, economy: bool) -> Polygon:
    """Full rounded block, or (economy) collars around the shapes plus arms out to the pins."""
    rect = _rounded_rect(bw, bh)
    if not economy:
        return rect
    collar = unary_union([o.buffer(CLAMP_MM + 1.0, quad_segs=16) for o in outlines])  # 1 mm ledge: walls never coincide
    c = collar.centroid
    arms = [shapely.LineString([(c.x, c.y), p]).buffer(ARM_W / 2) for p in pins]
    pads = [Point(p).buffer(PIN_D / 2 + 4, quad_segs=16) for p in pins]
    return unary_union([collar, *arms, *pads]).intersection(rect).buffer(1.5, quad_segs=8).buffer(-1.5, quad_segs=8)


def _moved(mesh: trimesh.Trimesh, offs) -> list[trimesh.Trimesh]:
    out = []
    for dx, dy in offs:
        m = mesh.copy()
        m.apply_translation([dx, dy, 0])
        out.append(m)
    return out


def _mold_frame(dome: Dome, offs):
    """Shared sizes: copies' outlines (ornament frame), sheet size, block size, pin positions."""
    outlines = [affinity.translate(dome.outline, dx, dy) for dx, dy in offs]
    x0, y0, x1, y1 = unary_union(outlines).bounds
    sw, sh = x1 - x0 + 2 * CLAMP_MM, y1 - y0 + 2 * CLAMP_MM
    bw, bh = sw + 2 * PIN_ZONE_MM, sh + 2 * PIN_ZONE_MM
    pins = [(sx * (bw / 2 - PIN_ZONE_MM / 2 - 1), sy * (bh / 2 - PIN_ZONE_MM / 2 - 1)) for sx in (-1, 1) for sy in (-1, 1)]
    return outlines, (sw, sh), (bw, bh), pins


def press_molds(dome: Dome, sheet: Sheet, economy: bool = True, offsets=None) -> MoldSet:
    """Female (cavities, alignment pins, vent holes) and male (plugs on a base with pin holes), print orientation.

    offsets: positions of the copies (multi-cavity, see ``cavity_layout``); default one cavity at the origin.
    economy: the full-height block shrinks to collars ``CLAMP_MM`` around the shapes (where the sheet is clamped) on a
    thin pin plate, and both molds lose the corners between the arms: ~35-45 % less filament, same forming surfaces.
    """
    offs = list(offsets or [(0.0, 0.0)])
    outlines, (sw, sh), (bw, bh), pins = _mold_frame(dome, offs)
    g = sheet.mold_gap_mm
    hf = dome.max_height + FLOOR_MM
    seg = max(0.6, dome.cell * 1.6)
    foot = _footprint(outlines, bw, bh, pins, economy)
    mirror = lambda geom: affinity.scale(geom, 1, -1, origin=(0, 0))  # ornament frame -> female frame

    # female: block minus the domes (rotated into the female frame), plus pins, minus vents
    cavity = _heightfield_solid(dome.outline, dome.height, -EPS, seg)
    cavities = _moved(cavity, offs)
    for c in cavities:
        c.apply_transform(RX)
        c.apply_translation([0, 0, hf])
    if economy:
        collar = unary_union([o.buffer(CLAMP_MM, quad_segs=16) for o in outlines])
        block = core.union_all([core.extrude(mirror(foot), 0.0, PLATE_MM), core.extrude(mirror(collar), 0.0, hf)])
        pin_z0 = PLATE_MM
    else:
        block, pin_z0 = core.extrude(mirror(foot), 0.0, hf), hf
    pin_top = hf + g + MALE_BASE_MM - 0.5
    pin_solids = [core.cylinder(PIN_D / 2, pin_top - pin_z0 + 0.2, "z", (x, y, (pin_top + pin_z0 - 0.2) / 2)) for x, y in pins]
    female = core.union_all([block, *pin_solids]) - core.union_all([core.from_trimesh(c) for c in cavities])
    peaks = dome.peaks()
    hp = dome.height(np.array(peaks)) if peaks else []
    vents, holes = [], []
    for dx, dy in offs:
        for (px, py), h in zip(peaks, hp):
            v = (px + dx, -(py + dy))  # female frame
            vents.append(v)
            holes.append(core.cylinder(VENT_D / 2, hf - h + 2, "z", (v[0], v[1], (hf - h + 1) / 2 - 1)))
    if holes:
        female = female - core.union_all(holes)

    # male: base (pin holes) + plugs = dome offset inwards by the sheet gap, printed plug-up (ornament frame)
    base = core.extrude(foot, 0.0, MALE_BASE_MM)
    pin_holes = [core.cylinder((PIN_D + PIN_CLEAR) / 2, MALE_BASE_MM + 2, "z", (x, y, MALE_BASE_MM / 2)) for x, y in pins]
    plug = _heightfield_solid(dome.outline, lambda xy: np.maximum(dome.offset_height(xy, g), -EPS / 2), -EPS, seg)
    plug.apply_translation([0, 0, MALE_BASE_MM])
    plugs = [core.from_trimesh(m) for m in _moved(plug, offs)]
    male = core.union_all([base, *plugs]) - core.union_all(pin_holes)
    return MoldSet(core.to_trimesh(female), core.to_trimesh(male), (sw, sh), (bw, bh), g, hf, MALE_BASE_MM, vents, offs)


def male_in_use(molds: MoldSet) -> trimesh.Trimesh:
    """The male mold placed on the female as when pressing fully (base face ``gap`` above the female top)."""
    m = molds.male.copy()
    m.apply_transform(RX)
    m.apply_translation([0, 0, molds.female_top_z + molds.gap_mm + molds.male_base_mm])
    return m


def relief_warnings(geom, sheet: Sheet, height_mm: float) -> list[str]:
    """Relief details the sheet cannot follow: lines narrower than two mold gaps (+ flanks) and too-low relief."""
    warnings = []
    w = 2 * sheet.mold_gap_mm + 0.6
    lost = geom.difference(geom.buffer(-w / 2, quad_segs=8).buffer(w / 2, quad_segs=8)).area
    if lost > 0.03 * geom.area:
        warnings.append(f"Kabartmada {w:.1f} mm'den ince çizgiler var (kabartmanın yaklaşık %{lost / geom.area * 100:.0f} kadarı); "
                        f"{sheet.label} levha bunlara girmez, silik çıkar. Kabartmayı büyütün ya da kalın bir yazı tipi seçin.")
    if height_mm < 2 * sheet.thickness_mm:
        warnings.append(f"Kabartma yüksekliği {height_mm:g} mm, levha kalınlığının iki katından az; belirgin çıkmayabilir.")
    return warnings


def cavity_draft(molds: MoldSet, dome: Dome) -> tuple[float, int]:
    """(draft, undercuts) of the female cavity, measured on the mesh against the pull direction (+z).

    draft: degrees of the steepest cavity wall away from vertical (0.5th percentile, rim band of 2 grid cells excluded:
    there the wall meets the flat top). undercuts: cavity faces facing downwards (anywhere, rim included)."""
    f = molds.female
    c, n = f.triangles_center, f.face_normals
    of = affinity.scale(unary_union([affinity.translate(dome.outline, dx, dy) for dx, dy in molds.offsets]), 1, -1, origin=(0, 0))
    sel = shapely.contains_xy(of, c[:, 0], c[:, 1]) & (c[:, 2] > 0.5 * FLOOR_MM) & (c[:, 2] < molds.female_top_z - 0.02)
    for vx, vy in molds.vents:
        sel &= np.hypot(c[:, 0] - vx, c[:, 1] - vy) > 2 * VENT_D
    if not sel.any():
        return 90.0, 0
    undercuts = int((n[sel, 2] < -1e-6).sum())
    core_sel = sel & shapely.contains_xy(of.buffer(-2 * dome.cell), c[:, 0], c[:, 1])
    draft = np.degrees(np.arcsin(np.clip(n[core_sel, 2], -1, 1)))
    return float(np.percentile(draft, 0.5)) if len(draft) else 90.0, undercuts
