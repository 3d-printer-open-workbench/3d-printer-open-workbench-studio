"""Logo (SVG / PNG / JPG) -> colored 2D regions (shapely, mm).

* SVG: filled shapes (paths, rects, circles, ...) with transforms applied, curves
  flattened; shapes grouped by fill color; paint order respected (later shapes cover
  earlier ones), so regions are disjoint.
* Raster: background removed (alpha channel, else the dominant border color, flood
  filled from the border), k-means colour quantisation to <= 4 colors, speck cleanup,
  each colour mask traced with potrace.
Output is scaled to the requested width (ink bbox width) with bbox min at (0, 0), y up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

from .text2d import MIN_FEATURE_MM, _polys_only, contours_to_geometry, thin_regions

MAX_LOGO_COLORS = 4
MIN_RASTER_WIDTH_PX = 800
MAX_WORK_PX = 1200  # raster is downscaled to this longest side before processing
SPECK_MM = 0.6  # components smaller than this (equivalent diameter) are cleaned up


@dataclass
class LogoRegion:
    color: str  # "#RRGGBB"
    geometry: BaseGeometry  # mm
    name: str = ""  # e.g. "text" for the text region of a logo+text sign


@dataclass
class LogoResult:
    regions: list[LogoRegion]
    width_mm: float
    height_mm: float
    source: str  # "svg" | "raster"
    warnings: list[str] = field(default_factory=list)
    source_px: tuple[int, int] | None = None


def scale_logo(logo: "LogoResult", factor: float) -> "LogoResult":
    """Uniformly scale a logo (bbox min stays at the origin)."""
    regs = [LogoRegion(r.color, affinity.scale(r.geometry, factor, factor, origin=(0, 0)), r.name) for r in logo.regions]
    return LogoResult(regs, logo.width_mm * factor, logo.height_mm * factor, logo.source, list(logo.warnings), logo.source_px)


def compose_logo_text(
    logo: "LogoResult",
    text_geometry: BaseGeometry,
    text_color: str,
    width_mm: float,
    layout: str = "logo_above",
    gap_mm: float = 10.0,
    logo_share: float = 0.5,
    text_builder=None,
) -> "LogoResult":
    """Combine a logo and text into one flat layout of overall width ``width_mm``.

    * ``logo_above``: text spans the full width; the logo (``logo_share`` of the width) is
      centred above it, ``gap_mm`` apart.
    * ``logo_left``: logo as high as the text, left of it, ``gap_mm`` apart.
    ``text_builder(width_mm) -> geometry`` rebuilds the text at a given width (needed for
    ``logo_left``, where the text width follows from the total width).
    """
    if layout not in ("logo_above", "logo_left"):
        raise ValueError("logo layout must be 'logo_above' or 'logo_left'")
    aspect = logo.width_mm / logo.height_mm
    if layout == "logo_above":
        tg = text_builder(width_mm) if text_builder else text_geometry
        tb = tg.bounds
        th = tb[3] - tb[1]
        lw = logo_share * width_mm
        lg = scale_logo(logo, lw / logo.width_mm)
        tg = affinity.translate(tg, -tb[0], -tb[1])
        lx, ly = (width_mm - lw) / 2, th + gap_mm
        tx = 0.0
    else:
        ref = text_builder(100.0)
        rb = ref.bounds
        r_t = (rb[3] - rb[1]) / (rb[2] - rb[0])
        k = r_t * aspect
        t_w = (width_mm - gap_mm) / (1 + k)
        if t_w <= 0:
            raise ValueError("width too small for logo_left layout")
        tg = text_builder(t_w)
        tb = tg.bounds
        th = tb[3] - tb[1]
        lg = scale_logo(logo, th / logo.height_mm)
        tg = affinity.translate(tg, -tb[0], -tb[1])
        lx, ly = 0.0, 0.0
        tx = lg.width_mm + gap_mm
    regions = [
        LogoRegion(r.color, affinity.translate(r.geometry, lx, ly), r.name) for r in lg.regions
    ]
    regions.append(LogoRegion(text_color, affinity.translate(tg, tx, 0.0), "text"))
    allg = unary_union([r.geometry for r in regions])
    b = allg.bounds
    return LogoResult(regions, b[2] - b[0], b[3] - b[1], logo.source, list(logo.warnings), logo.source_px)


def _hex(rgb) -> str:
    r, g, b = (int(round(max(0, min(255, v)))) for v in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _finish(
    regions: list[tuple[str, BaseGeometry]],
    width_mm: float,
    source: str,
    warnings: list[str],
    source_px=None,
    min_feature_mm: float = MIN_FEATURE_MM["flat"],
) -> LogoResult:
    regions = [(c, _polys_only(g)) for c, g in regions if not g.is_empty]
    if not regions:
        raise ValueError("logo has no filled regions")
    allg = unary_union([g for _, g in regions])
    minx, miny, maxx, maxy = allg.bounds
    s = width_mm / (maxx - minx)

    def fin(g):
        g = affinity.translate(g, -minx, -miny)
        return _polys_only(affinity.scale(g, s, s, origin=(0, 0)).simplify(0.01, preserve_topology=True))

    out = [LogoRegion(c, fin(g)) for c, g in regions]
    out = [r for r in out if not r.geometry.is_empty]
    out.sort(key=lambda r: -r.geometry.area)
    for r in out:
        thin = thin_regions(r.geometry, min_feature_mm)
        small = [p for p in getattr(r.geometry, "geoms", [r.geometry]) if p.area < (min_feature_mm / 2) ** 2 * math.pi * 0.5]
        if thin or small:
            warnings.append(
                f"Color {r.color}: {len(thin)} thin and {len(small)} tiny feature(s) below "
                f"{min_feature_mm:.1f} mm at this size; they may print poorly."
            )
    b = unary_union([r.geometry for r in out]).bounds
    return LogoResult(out, b[2] - b[0], b[3] - b[1], source, warnings, source_px)


# --------------------------------------------------------------------------- #
# SVG
# --------------------------------------------------------------------------- #
def _flatten_subpaths(path, samples: int = 24) -> list[list[tuple[float, float]]]:
    from svgelements import Close, CubicBezier, Line, Move, QuadraticBezier, Arc

    subs: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    for seg in path.segments():
        if isinstance(seg, Move):
            if len(cur) >= 3:
                subs.append(cur)
            cur = [(seg.end.x, seg.end.y)]
        elif isinstance(seg, Close):
            if len(cur) >= 3:
                subs.append(cur)
            cur = []
        elif isinstance(seg, Line):
            if not cur:
                cur = [(seg.start.x, seg.start.y)]
            cur.append((seg.end.x, seg.end.y))
        elif isinstance(seg, (CubicBezier, QuadraticBezier, Arc)):
            if not cur:
                cur = [(seg.start.x, seg.start.y)]
            for i in range(1, samples + 1):
                p = seg.point(i / samples)
                cur.append((p.x, p.y))
    if len(cur) >= 3:
        subs.append(cur)
    return subs


def _shape_geometry(subs, even_odd: bool) -> BaseGeometry:
    if not subs:
        return Polygon()
    if even_odd:
        g: BaseGeometry | None = None
        for c in subs:
            pg = Polygon(c)
            if not pg.is_valid:
                pg = make_valid(pg)
            g = pg if g is None else g.symmetric_difference(pg)
        return _polys_only(g)
    return contours_to_geometry(subs)


def logo_from_svg(path: str | Path, width_mm: float, n_colors: int = MAX_LOGO_COLORS) -> LogoResult:
    from svgelements import SVG, Path as SPath, Shape

    n_colors = _clamp_colors(n_colors, [])
    warnings: list[str] = []
    svg = SVG.parse(str(path), reify=True)
    layers: list[tuple[tuple[int, int, int], BaseGeometry]] = []
    stroke_only = 0
    for el in svg.elements():
        if not isinstance(el, Shape):
            continue
        fill = el.fill
        if fill is None or fill.value is None or getattr(fill, "alpha", 255) == 0:
            if el.stroke is not None and el.stroke.value is not None:
                stroke_only += 1
            continue
        if isinstance(el, SPath):
            p = el
        else:
            try:
                p = SPath(el)
            except Exception:
                continue
        even_odd = str(el.values.get("fill-rule", "nonzero")).lower() == "evenodd"
        subs = _flatten_subpaths(p)
        g = _shape_geometry(subs, even_odd)
        if g.is_empty:
            continue
        layers.append(((int(fill.red), int(fill.green), int(fill.blue)), g))
    if stroke_only:
        warnings.append(f"{stroke_only} stroke-only shape(s) ignored (convert strokes to outlines in the SVG).")
    if not layers:
        raise ValueError("SVG contains no filled shapes")

    # near-white full-bleed background rectangle -> drop
    allg = unary_union([g for _, g in layers])
    ab = allg.bounds
    kept = []
    for col, g in layers:
        gb = g.bounds
        full = all(abs(a - b) < 1e-6 * max(1, abs(b)) + 1e-9 for a, b in zip(gb, ab))
        if full and min(col) >= 245 and len(layers) > 1 and g.area > 0.9 * Polygon.from_bounds(*ab).area:
            warnings.append("White full-size background shape removed.")
            continue
        kept.append((col, g))
    layers = kept

    # reduce to <= n_colors by clustering fill colors (area weighted)
    colors = {}
    for col, g in layers:
        colors.setdefault(col, 0.0)
        colors[col] += g.area
    mapping = {c: c for c in colors}
    if len(colors) > n_colors:
        cols = list(colors)
        data = np.array(cols, np.float32)
        weights = np.array([colors[c] for c in cols])
        centers = _weighted_kmeans(data, weights, n_colors)
        mapping = {c: tuple(int(v) for v in centers[int(np.argmin(((centers - np.array(c)) ** 2).sum(1)))]) for c in cols}
        warnings.append(f"SVG has {len(colors)} distinct colors; merged to {n_colors}.")

    # paint order: later layers cover earlier ones
    regions: dict[tuple[int, int, int], BaseGeometry] = {}
    covered: BaseGeometry | None = None
    for col, g in reversed(layers):
        visible = g if covered is None else g.difference(covered)
        covered = g if covered is None else covered.union(g)
        c = mapping[col]
        regions[c] = unary_union([regions[c], visible]) if c in regions else visible
    flipped = [(_hex(c), affinity.scale(g, 1, -1, origin=(0, 0))) for c, g in regions.items()]
    return _finish(flipped, width_mm, "svg", warnings)


def _weighted_kmeans(data: np.ndarray, weights: np.ndarray, k: int, iters: int = 30) -> np.ndarray:
    order = np.argsort(-weights)
    centers = data[order[:k]].copy()
    for _ in range(iters):
        d = ((data[:, None, :] - centers[None]) ** 2).sum(2)
        lab = d.argmin(1)
        for j in range(k):
            m = lab == j
            if m.any():
                centers[j] = (data[m] * weights[m, None]).sum(0) / weights[m].sum()
    return centers


def _clamp_colors(n: int, warnings: list[str]) -> int:
    if n < 1:
        raise ValueError("n_colors must be >= 1")
    if n > MAX_LOGO_COLORS:
        warnings.append(f"n_colors reduced from {n} to {MAX_LOGO_COLORS} (CANVAS supports 4 filaments).")
        return MAX_LOGO_COLORS
    return n


# --------------------------------------------------------------------------- #
# Raster
# --------------------------------------------------------------------------- #
def _foreground_mask(bgr: np.ndarray, alpha: np.ndarray | None, warnings: list[str]) -> np.ndarray:
    h, w = bgr.shape[:2]
    if alpha is not None and (alpha < 250).mean() > 0.01:
        return alpha > 127
    # dominant border colour, flood-filled from the border
    t = max(2, int(0.02 * min(h, w)))
    border = np.concatenate(
        [bgr[:t].reshape(-1, 3), bgr[-t:].reshape(-1, 3), bgr[:, :t].reshape(-1, 3), bgr[:, -t:].reshape(-1, 3)]
    )
    q = (border // 16).astype(np.int32)
    keys = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    vals, counts = np.unique(keys, return_counts=True)
    dom = border[keys == vals[counts.argmax()]].mean(axis=0)
    close = (np.linalg.norm(bgr.astype(np.float32) - dom, axis=2) < 40).astype(np.uint8)
    n, lab = cv2.connectedComponents(close, connectivity=4)
    edge_labels = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(edge_labels))
    if bg.mean() < 0.02:
        warnings.append("No clear background color found; using the whole image.")
    return ~bg


def _clean_mask(mask: np.ndarray, min_px: int) -> np.ndarray:
    """Remove specks and fill pin-holes smaller than ``min_px`` pixels."""
    m = mask.astype(np.uint8)
    for invert in (False, True):
        src = (1 - m) if invert else m
        n, lab, stats, _ = cv2.connectedComponentsWithStats(src, connectivity=8)
        small = np.isin(lab, [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] < min_px])
        if invert:
            m[small] = 1
        else:
            m[small] = 0
    return m.astype(bool)


def _trace(mask: np.ndarray, turd: int) -> BaseGeometry:
    import potrace

    h = mask.shape[0]
    curves = potrace.Bitmap(~mask).trace(turdsize=turd, alphamax=1.0, opticurve=True, opttolerance=0.2)
    g: BaseGeometry | None = None
    for c in curves:
        pts = [(c.start_point.x, c.start_point.y)]
        for s in c.segments:
            p0 = pts[-1]
            if s.is_corner:
                pts.append((s.c.x, s.c.y))
                pts.append((s.end_point.x, s.end_point.y))
            else:
                p1, p2, p3 = (s.c1.x, s.c1.y), (s.c2.x, s.c2.y), (s.end_point.x, s.end_point.y)
                for i in range(1, 11):
                    t = i / 10
                    a, b, cc, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t**3
                    pts.append(
                        (
                            a * p0[0] + b * p1[0] + cc * p2[0] + d * p3[0],
                            a * p0[1] + b * p1[1] + cc * p2[1] + d * p3[1],
                        )
                    )
        if len(pts) < 4:
            continue
        pg = Polygon([(x, h - y) for x, y in pts])  # flip to y up
        if not pg.is_valid:
            pg = make_valid(pg)
        g = pg if g is None else g.symmetric_difference(pg)  # even-odd nesting (holes)
    return _polys_only(g) if g is not None else Polygon()


def logo_from_raster(
    path: str | Path, width_mm: float, n_colors: int = MAX_LOGO_COLORS
) -> LogoResult:
    warnings: list[str] = []
    n_colors = _clamp_colors(n_colors, warnings)
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"cannot read image {path}")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    alpha = None
    if img.shape[2] == 4:
        alpha = img[:, :, 3]
        img = img[:, :, :3]
    if img.dtype != np.uint8:
        img = cv2.convertScaleAbs(img, alpha=255.0 / np.iinfo(img.dtype).max)
    src_h, src_w = img.shape[:2]
    if src_w < MIN_RASTER_WIDTH_PX:
        warnings.append(
            f"Low resolution: image is {src_w} px wide (< {MIN_RASTER_WIDTH_PX}); edges may look rough. Use a larger file or an SVG."
        )
    scale = min(1.0, MAX_WORK_PX / max(src_h, src_w))
    if scale < 1.0:
        size = (int(src_w * scale), int(src_h * scale))
        img = cv2.resize(img, size, interpolation=cv2.INTER_AREA)
        if alpha is not None:
            alpha = cv2.resize(alpha, size, interpolation=cv2.INTER_AREA)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    fg = _foreground_mask(img, alpha, warnings)
    if not fg.any():
        raise ValueError("image has no foreground after background removal")
    # remove specks (dust, JPEG noise) from the foreground before measuring its bbox
    ys, xs = np.where(fg)
    rough_w = xs.max() + 1 - xs.min()
    fg = _clean_mask(fg, max(12, int(math.pi * (SPECK_MM / 2 / (width_mm / rough_w)) ** 2)))
    if not fg.any():
        raise ValueError("image has no foreground after speck removal")
    ys, xs = np.where(fg)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    img, fg = img[y0:y1, x0:x1], fg[y0:y1, x0:x1]
    h, w = fg.shape
    mm_per_px = width_mm / w
    min_px = max(12, int(math.pi * (SPECK_MM / 2 / mm_per_px) ** 2))

    # Colour quantisation. Pixels on colour transitions (anti-aliasing, alpha edges) are
    # unreliable: fit k-means only on flat-colour pixels and give the transition pixels the
    # label of their nearest flat pixel, so no sliver "edge colours" appear.
    from scipy import ndimage

    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    kernel = np.ones((3, 3), np.uint8)
    grad = np.max(cv2.dilate(lab, kernel) - cv2.erode(lab, kernel), axis=2)
    fg_core = cv2.erode(fg.astype(np.uint8), kernel, iterations=2).astype(bool)
    reliable = fg_core & (grad < 25)
    if reliable.sum() < 50:
        reliable = fg_core if fg_core.any() else fg
    pix = lab[reliable]
    sample = pix if len(pix) <= 60000 else pix[np.random.default_rng(0).choice(len(pix), 60000, replace=False)]
    k = min(n_colors, max(1, len(np.unique(sample.astype(np.int32), axis=0))))
    if k == 1:
        centers = sample.mean(axis=0, keepdims=True)
    else:
        cv2.setRNGSeed(1234)
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.5)
        _, _, centers = cv2.kmeans(sample, k, None, crit, 4, cv2.KMEANS_PP_CENTERS)
    # merge near-identical centers (e.g. shades of one colour)
    merged: list[np.ndarray] = []
    for c in centers:
        if all(np.linalg.norm(c - m) > 18 for m in merged):
            merged.append(c)
    centers = np.array(merged, np.float32)
    d = ((lab[:, :, None, :] - centers[None, None]) ** 2).sum(3)
    labels = d.argmin(2).astype(np.uint8)
    idx = ndimage.distance_transform_edt(~reliable, return_distances=False, return_indices=True)
    labels = labels[idx[0], idx[1]]
    labels[~fg] = 255
    labels = cv2.medianBlur(labels, 5)
    labels[~fg] = 255

    rgb_centers = cv2.cvtColor(centers.reshape(1, -1, 3).astype(np.uint8), cv2.COLOR_LAB2RGB).reshape(-1, 3)
    regions = []
    for i in range(len(centers)):
        mask = _clean_mask(labels == i, min_px)
        if not mask.any():
            continue
        g = _trace(mask, turd=max(2, min_px // 2))
        if not g.is_empty:
            g = affinity.scale(g, mm_per_px, mm_per_px, origin=(0, 0))
            regions.append((_hex(rgb_centers[i]), g))
    # make regions disjoint (trace overlap at shared edges)
    disjoint, covered = [], None
    for col, g in sorted(regions, key=lambda t: -t[1].area):
        g2 = g if covered is None else g.difference(covered)
        covered = g if covered is None else covered.union(g)
        disjoint.append((col, g2))
    return _finish(disjoint, width_mm, "raster", warnings, (src_w, src_h))


def load_logo(path: str | Path, width_mm: float, n_colors: int = MAX_LOGO_COLORS) -> LogoResult:
    """Load SVG / PNG / JPG and return colored regions scaled to ``width_mm``."""
    ext = Path(path).suffix.lower()
    if ext == ".svg":
        return logo_from_svg(path, width_mm, n_colors)
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
        return logo_from_raster(path, width_mm, n_colors)
    raise ValueError(f"unsupported logo format {ext!r} (use SVG, PNG or JPG)")
