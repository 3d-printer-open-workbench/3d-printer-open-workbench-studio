"""Geometry engine shared by all modes: area -> elevation grid -> layer outlines -> printable parts."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import manifold3d as m3
import numpy as np
from shapely import affinity, contains_xy, prepare
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import polygonize, unary_union

from . import data
from .data import BBox
from .geom import (Projection, fit_text, heightfield, line_seed, marker_shape, max_under, outline, polys, prism, river_shape,
                   sample_grid, to_mesh)
from .job import Job
from .modes import LAYER_ORDER, ROAD_WIDTH_M, SELECTORS, default_classify, get_mode

# mm above the terrain surface for draped (inlaid-on-top) layers
DRAPE = {"green": 0.3, "forest": 0.7, "rocks": 0.5, "water": 0.4, "streams": 0.4, "sea": 0.4, "paths": 0.5, "roads": 0.6, "rail": 0.8, "route": 1.6}
MIN_W = {"roads": 0.8, "paths": 0.6, "rail": 0.8, "water": 0.8, "streams": 0.7, "rocks": 0.8, "route": 1.2}
RIVER_W_M = {"river": 25, "stream": 6}  # drawn width when OSM has no width tag
MIN_FEATURE = 0.7     # mm: narrower buildings / patches are dropped (they would not print)
AREA_LIMIT_KM2 = {"buildings": 30, "roads": 600, "paths": 150, "green": 800, "forest": 800, "ruins": 100, "water": 20000, "rail": 5000,
                  "rocks": 2000, "streams": 3000}
TEXT_H = 0.8          # embossed caption height
MARKER_H = 2.5        # markers stand above the surface
CAPTION_BAND = 16.0   # caption band depth (mm)


@dataclass
class Part:
    name: str           # e.g. terrain, terrain_2, roads, route, frame, text
    role: str           # colour role (layer key)
    color: str
    solid: m3.Manifold


@dataclass
class Model:
    job: Job
    proj: Projection
    bbox: BBox
    xs: np.ndarray
    ys: np.ndarray
    elev: np.ndarray            # m, grid
    z: np.ndarray               # mm, terrain top
    outline: Polygon
    footprint: Polygon          # outline + frame + caption band
    layers: dict = field(default_factory=dict)      # layer -> shapely geometry (mm)
    parts: list = field(default_factory=list)       # [Part]
    route_mm: list = field(default_factory=list)    # [LineString]
    route_name: str = ""
    stats: dict = field(default_factory=dict)
    z_exag: float = 1.0
    caption: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)


def _log(progress, msg):
    if progress:
        progress(msg)


# --------------------------------------------------------------------------- area
def resolve_area(job: Job, warnings: list) -> tuple[BBox, list, str, list]:
    """(bbox, route segments [(lat, lon, ele)], name, place markers)."""
    mode = get_mode(job.mode)
    segs: list = []
    name = job.title
    if mode.area_source == "route":
        if job.gpx:
            name0, segs = data.parse_gpx(job.gpx)
        else:
            name0, lines = data.osm_route(job.osm_relation)
            segs = [[(a, b, None) for a, b in ln] for ln in lines]
        name = name or name0
        la = np.array([p[0] for s in segs for p in s])
        lo = np.array([p[1] for s in segs for p in s])
        bb = BBox(la.min(), lo.min(), la.max(), lo.max()).expand(job.margin_pct / 100.0)
        if job.area_fixed and job.lat is not None and job.lon is not None:
            bb = BBox.around(job.lat, job.lon, job.width_km, job.height_km)  # area adjusted by hand on the map
    else:
        lat, lon = job.lat, job.lon
        if lat is None or lon is None:
            hits = data.geocode(job.place)
            if not hits:
                raise data.DataError(f"Yer bulunamadı: {job.place}")
            lat, lon = hits[0]["lat"], hits[0]["lon"]
            name = name or job.place.split(",")[0].strip()
        bb = BBox.around(lat, lon, job.width_km, job.height_km)
    # equal-aspect shapes need a square area
    if job.shape != "rect":
        w, h = bb.size_m()
        c = bb.center
        side = max(w, h) / 1000
        bb = BBox.around(c[0], c[1], side, side)
    return bb, segs, name or "Harita", []


def frame_geometry(job: Job, S: Polygon, caption: bool):
    """(frame ring + caption band, caption band rect or None)."""
    fw = job.frame_mm
    x0, y0, x1, y1 = S.bounds
    ring = S.buffer(fw, join_style="mitre" if job.shape in ("rect", "square", "octagon", "hexagon") else "round").difference(S)
    band = None
    if caption:
        if job.shape in ("rect", "square"):
            band = box(x0 - fw, y0 - fw - CAPTION_BAND, x1 + fw, y0 - fw + 0.01)
        else:
            # curved outlines: a rounded label plate overlapping the bottom of the map
            w = (x1 - x0) * 0.62
            cx = (x0 + x1) / 2
            band = box(cx - w / 2, y0 - fw - CAPTION_BAND * 0.6, cx + w / 2, y0 - fw + CAPTION_BAND * 0.4).buffer(-3).buffer(3)
        ring = unary_union([ring, band])
    return ring, band


# --------------------------------------------------------------------------- OSM -> mm geometry
def _width_m(v) -> float | None:
    """OSM width tag ("12", "12 m", "12.5") -> metres; None when missing or not a plain number."""
    try:
        return float(str(v).lower().replace("m", "").replace(",", ".").strip()) if v else None
    except ValueError:
        return None


def _elements_to_shapes(elements, proj: Projection):
    """Yield (tags, geometry) with polygons for closed areas / multipolygons and lines otherwise."""
    for e in elements:
        tags = e.get("tags", {})
        if e["type"] == "way" and e.get("geometry"):
            pts = [proj.mm(g["lat"], g["lon"]) for g in e["geometry"]]
            if len(pts) < 2:
                continue
            closed = pts[0] == pts[-1] and len(pts) >= 4
            area_like = closed and not tags.get("railway") and not (tags.get("highway") and tags.get("area") != "yes") and tags.get("waterway") not in ("river", "canal", "stream") \
                and tags.get("historic") != "citywalls"
            if area_like:
                p = Polygon(pts).buffer(0)
                if not p.is_empty:
                    yield tags, p
            else:
                yield tags, LineString(pts)
        elif e["type"] == "relation" and e.get("members"):
            outer, inner = [], []
            for mbr in e["members"]:
                if mbr.get("type") != "way" or not mbr.get("geometry"):
                    continue
                ln = LineString([proj.mm(g["lat"], g["lon"]) for g in mbr["geometry"]])
                (inner if mbr.get("role") == "inner" else outer).append(ln)
            if not outer:
                continue
            o = unary_union(list(polygonize(unary_union(outer))))
            if inner:
                o = o.difference(unary_union(list(polygonize(unary_union(inner)))))
            if not o.is_empty:
                yield tags, o


def _complete_relations(els: list[dict], warnings: list, limit: int = 25) -> list[dict]:
    """Area relations (forest, park, lake) whose outer ring is not closed in the download (the main OSM
    API only returns the members' nodes inside the box) are re-fetched whole, so big forests are not lost."""
    from shapely import line_merge
    from shapely.geometry import MultiLineString

    area_keys = ("landuse", "natural", "leisure", "water", "waterway")
    todo = []
    for e in els:
        if e["type"] != "relation" or not any(k in e.get("tags", {}) for k in area_keys):
            continue
        outer = [[(g["lon"], g["lat"]) for g in m["geometry"]] for m in e.get("members", [])
                 if m.get("type") == "way" and m.get("role") != "inner" and len(m.get("geometry") or []) > 1]
        if not outer:
            todo.append(e)
            continue
        merged = line_merge(MultiLineString(outer))
        if any(not g.is_ring for g in getattr(merged, "geoms", [merged])):
            todo.append(e)
    if not todo:
        return els
    fixed = {}
    for e in todo[:limit]:
        try:
            fixed[e["id"]] = data.osm_relation_full(e["id"])
        except data.DataError:
            pass
    if len(todo) > limit:
        warnings.append(f"{len(todo) - limit} büyük alan (orman/park) eksik kalmış olabilir.")
    return [fixed.get(e["id"], e) if e["type"] == "relation" else e for e in els]


def _building_height_m(tags: dict) -> float:
    for k in ("height", "building:height"):
        v = tags.get(k)
        if v:
            try:
                return float(str(v).split()[0].replace(",", "."))
            except ValueError:
                pass
    lv = tags.get("building:levels")
    if lv:
        try:
            return float(lv) * 3.2 + 1.5
        except ValueError:
            pass
    return 9.0


def collect_layers(job: Job, model: Model, progress=None) -> None:
    mode = get_mode(job.mode)
    L = job.layers
    km2 = (model.bbox.size_m()[0] / 1000) * (model.bbox.size_m()[1] / 1000)
    want = []
    road_scale = mode.theme(job.theme).road_scale
    for lay in ("buildings", "roads", "rail", "paths", "water", "streams", "green", "forest", "rocks", "ruins"):
        if L.get(lay):
            if km2 > AREA_LIMIT_KM2[lay]:
                model.warnings.append(f"{lay}: alan çok büyük ({km2:.0f} km²), bu katman atlandı (sınır {AREA_LIMIT_KM2[lay]} km²).")
                continue
            want.append(lay)
    sel = {s for lay in want for s in SELECTORS[lay]}
    if L.get("sea") and km2 <= 20000:  # real coastline instead of the 30 m elevation raster
        sel |= {'way["natural"="coastline"]', 'way["man_made"~"^(pier|breakwater|groyne)$"]'}
    sel = sorted(sel)
    coast_lines: list[LineString] = []
    islands: list[Polygon] = []
    piers: list = []
    k = model.proj.mm_per_m
    buckets = {lay: [] for lay in want}
    heights: list[tuple[Polygon, float]] = []
    if sel:
        _log(progress, "OpenStreetMap verisi alınıyor…")
        try:
            els = data.osm_features(model.bbox.expand(0.02), sel)
        except data.DataError as e:
            model.warnings.append(str(e))
            els = []
        classify = mode.classify or default_classify
        els = _complete_relations(els, model.warnings)
        for tags, g in _elements_to_shapes(els, model.proj):
            if tags.get("natural") == "coastline":
                (coast_lines if g.geom_type == "LineString" else islands).append(g if g.geom_type == "LineString" else g)
                continue
            if tags.get("man_made") in ("pier", "breakwater", "groyne"):
                piers.append(g.buffer(max(4 * k, 0.8) / 2) if g.geom_type == "LineString" else g)
                if not tags.get("highway"):
                    continue
            lay = classify(tags)
            if lay not in buckets:
                continue
            if lay == "rail" and g.geom_type == "LineString":
                w = max((5 if tags.get("railway") == "tram" else 7) * k, MIN_W["rail"])
                buckets[lay].append(g.buffer(w / 2, cap_style="flat"))
            elif lay in ("roads", "paths") and g.geom_type == "LineString":
                w = max(ROAD_WIDTH_M.get(tags.get("highway", ""), 6) * k * road_scale, MIN_W[lay])
                buckets[lay].append(g.buffer(w / 2, cap_style="round"))
            elif lay in ("water", "streams") and g.geom_type == "LineString":
                ww = tags.get("waterway")
                real = _width_m(tags.get("width")) or RIVER_W_M.get(ww, 8)
                base = max(real * k, MIN_W[lay])
                if ww in ("river", "stream"):  # natural rivers widen downstream and swell / narrow along the way
                    buckets[lay].append(river_shape(g, base, line_seed(g), min_w=MIN_W[lay]))
                else:  # canals keep their width
                    buckets[lay].append(g.buffer(base / 2))
            elif lay == "rocks" and g.geom_type == "LineString":  # cliffs: a printable band
                buckets[lay].append(g.buffer(MIN_W["rocks"] / 2))
            elif lay == "ruins" and g.geom_type == "LineString":
                buckets[lay].append(g.buffer(max(3 * k, 0.6) / 2))
            elif lay == "buildings" and g.geom_type != "LineString":
                heights.append((g, _building_height_m(tags)))
            elif g.geom_type != "LineString":
                buckets[lay].append(g)
    inner = model.outline.buffer(-0.4)
    for lay, items in buckets.items():
        if lay == "buildings":
            continue
        if items:
            g = unary_union(items).intersection(inner)
            if lay in ("green", "forest", "water", "rocks"):  # drop specks that cannot be printed
                g = unary_union([p for p in polys(g.buffer(-MIN_FEATURE / 2).buffer(MIN_FEATURE / 2)) if p.area > 1.0])
            model.layers[lay] = g
    if heights:
        model.layers["buildings"] = [(g.intersection(inner), h) for g, h in heights if g.intersects(inner)]
    # sea: from the OSM coastline when there is one, else from the elevation grid
    sea_done = False
    if L.get("sea") and (coast_lines or islands):
        region = box(float(model.xs[0]), float(model.ys[0]), float(model.xs[-1]), float(model.ys[-1]))
        sea = coast_sea(coast_lines, islands, region, sea_mask(model.elev).mean())
        if piers:
            sea = sea.difference(unary_union(piers))
        sea = unary_union([p for p in polys(sea) if p.area > 2.0])
        if not sea.is_empty:
            model.layers["sea"] = sea.intersection(inner)
        sea_done = True
    if L.get("sea") and not sea_done:
        mask = sea_mask(model.elev)
        if mask.mean() > 0.01:
            sea = _mask_polygons(model.xs, model.ys, mask)
            d = 30.0 * model.proj.mm_per_m  # DEM cell in mm: smooth the staircase edge of the raster mask
            sea = unary_union([p for p in polys(sea) if p.area > 4.0]).simplify(d * 0.6).buffer(d * 0.4).buffer(-d * 0.4)
            if not sea.is_empty:
                model.layers["sea"] = sea.intersection(inner)
    # nothing but piers/bridges sits in the sea: clip land layers to the coast and flatten the sea floor
    sea = model.layers.get("sea")
    if sea is not None and not sea.is_empty:
        for lay in ("roads", "paths", "rail", "green", "forest", "rocks", "streams"):
            if model.layers.get(lay) is not None:
                model.layers[lay] = model.layers[lay].difference(sea.buffer(-0.05))
        if model.layers.get("buildings"):
            model.layers["buildings"] = [(g, h) for g, h in model.layers["buildings"] if not sea.contains(g.representative_point())]
        X, Y = np.meshgrid(model.xs, model.ys)
        under = contains_xy(sea.buffer(1.0), X, Y)
        model.z[under] = job.base_mm
    # route
    if L.get("route") and model.route_mm:
        w = job.route_width_mm
        if model.proj.scale > 150_000 and w > 1.8:  # whole long-distance trails: many branches, keep the line lighter
            w = 1.8
        model.layers["route"] = unary_union([ln.buffer(w / 2, cap_style="round", join_style="round") for ln in model.route_mm]).intersection(inner)


def coast_sea(lines: list, islands: list, region: Polygon, dem_sea_fraction: float):
    """Sea polygon inside ``region`` from OSM coastline ways (land is on the left of a coastline's direction)."""
    import shapely
    from shapely.geometry import MultiLineString

    sea = Polygon()
    if lines:
        merged = shapely.line_merge(MultiLineString([list(g.coords) for g in lines]), directed=True)
        segs = [g for g in getattr(merged, "geoms", [merged]) if g.length > 0]
        clipped = unary_union([g.intersection(region.buffer(1)) for g in segs])
        faces = list(polygonize(unary_union([region.exterior, clipped])))
        sea_faces = []
        for f in faces:
            f = f.intersection(region)
            if f.is_empty or f.area < 0.5:
                continue
            rp = f.representative_point()
            ln = min(segs, key=lambda g: g.distance(rp))
            d = ln.project(rp)
            a = ln.interpolate(max(d - 0.05, 0.0))
            b = ln.interpolate(min(d + 0.05, ln.length))
            cross = (b.x - a.x) * (rp.y - a.y) - (b.y - a.y) * (rp.x - a.x)
            if cross < 0:  # right of the coastline = water
                sea_faces.append(f)
        sea = unary_union(sea_faces) if sea_faces else Polygon()
    elif islands and dem_sea_fraction > 0.3:
        sea = region  # only islands in view: everything around them is sea
    if islands:
        sea = sea.difference(unary_union(islands))
    return sea


def sea_mask(elev: np.ndarray) -> np.ndarray:
    """Sea = sea-level cells (Copernicus writes 0 on the ocean) connected to the area edge.
    Inland lowland / wetland at ~0 m that does not reach the edge stays land."""
    from scipy.ndimage import label

    low = elev <= 0.05
    lab, n = label(low)
    if n == 0:
        return low
    edge = np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]])
    keep = np.isin(lab, edge[edge > 0])
    sizes = np.bincount(lab.ravel())
    big = np.isin(lab, np.nonzero(sizes > 0.005 * lab.size)[0])
    return keep & big & low


def _mask_polygons(xs, ys, mask: np.ndarray):
    from rasterio import features
    from rasterio.transform import Affine

    dx, dy = xs[1] - xs[0], ys[1] - ys[0]
    tr = Affine(dx, 0, xs[0] - dx / 2, 0, dy, ys[0] - dy / 2)
    from shapely.geometry import shape as shp

    out = [shp(g) for g, v in features.shapes(mask.astype(np.uint8), mask=mask, transform=tr) if v == 1]
    return unary_union(out) if out else Polygon()


# --------------------------------------------------------------------------- main build
def build_model(job: Job, progress=None, coarse: bool = False) -> Model:
    job = job.resolved()
    warnings: list[str] = []
    if job.split and job.size_mm > 234 and job.base_mm < 4.0:
        job.base_mm = 4.0  # room for the alignment-pin holes of a tiled model
        warnings.append("Parçalı model: pim delikleri için taban 4 mm'ye çıkarıldı.")
    _log(progress, "Alan belirleniyor…")
    bb, segs, name, _ = resolve_area(job, warnings)
    w_m, h_m = bb.size_m()
    k = job.size_mm / max(w_m, h_m)
    W, H = w_m * k, h_m * k
    c = bb.center
    proj = Projection(c[0], c[1], k)
    S = outline(job.shape, W, H)

    # grid
    # grid: finer than the nozzle is wasted, and so is sampling the 30 m DEM much finer than ~1/3 of its spacing
    dem_mm = 30.0 * k
    res = job.res_mm or float(np.clip(max(max(W, H) / 520.0, dem_mm / 3.0), 0.35, 1.5))
    if coarse:  # fast on-screen preview
        res = max(res, max(W, H) / 200.0)
    nx, ny = int(math.ceil(W / res)) + 3, int(math.ceil(H / res)) + 3
    xs = (np.arange(nx) - (nx - 1) / 2) * res
    ys = (np.arange(ny) - (ny - 1) / 2) * res
    X, Y = np.meshgrid(xs, ys)
    lat, lon = proj.inv(X, Y)
    need_dem = job.layers.get("terrain") or job.layers.get("sea") or job.layers.get("route")
    m_per_cell = res / k
    dem_res = 90 if m_per_cell > 75 else 30
    if need_dem:
        _log(progress, f"Yükseklik verisi (Copernicus {dem_res} m) alınıyor…")
        elev = data.sample_elevation(lat, lon, dem_res)
        smooth_m = get_mode(job.mode).defaults.get("dem_smooth_m", 0)
        if smooth_m:
            # Copernicus is a surface model (roofs, trees): smooth it so city ground does not look lumpy
            from scipy.ndimage import gaussian_filter

            elev = gaussian_filter(elev, sigma=max(1.0, smooth_m / m_per_cell), mode="nearest")
    else:
        elev = np.zeros_like(X)
    land = elev[elev > 0.5]
    e_base = 0.0 if sea_mask(elev).any() or not land.size else float(land.min()) - 2.0
    relief_m = float(max((elev.max() - e_base), 1.0))
    z_exag = job.z_exag
    if job.layers.get("terrain") and z_exag == 0:
        target = float(np.clip(0.12 * job.size_mm, 10, 35))
        z_exag = round(float(np.clip(target / (relief_m * k), 1.0, 25.0)), 1)
    if not job.layers.get("terrain"):
        z_rel = np.zeros_like(elev)
        z_exag = 0.0
    else:
        z_rel = np.clip(elev - e_base, 0, None) * k * z_exag
    if job.z_max_mm:
        z_rel = np.minimum(z_rel, job.z_max_mm)
    Z = job.base_mm + z_rel

    model = Model(job, proj, bb, xs, ys, elev, Z, S, S, route_name=name, z_exag=z_exag, warnings=warnings)

    # route in mm + stats
    if segs:
        model.route_mm = []
        for s in segs:
            x, y = proj.mm([p[0] for p in s], [p[1] for p in s])
            if len(x) > 1:
                model.route_mm.append(LineString(np.c_[x, y]).simplify(0.1))
        model.stats = data.route_stats(segs, elev=lambda a, b: data.sample_elevation(np.asarray(a), np.asarray(b), 30))
        model.stats["_profile_src"] = segs
        if job.osm_relation and not job.gpx:
            model.warnings.append("OSM rotası alternatif kolları da içerebilir: km ve tırmanış tüm kolların toplamıdır. "
                                  "Gerekirse alt satırı elle yazın.")

    collect_layers(job, model, progress)
    _log(progress, "Parçalar oluşturuluyor…")
    make_parts(job, model)
    return model


def _caption_text(job: Job, model: Model) -> tuple[str, str]:
    title = job.title or model.route_name
    sub = job.subtitle
    if not sub and model.stats:
        st = model.stats
        bits = [f"{st['length_km']:.1f} km".replace(".", ",")]
        if st.get("ascent_m"):
            bits.append(f"+{st['ascent_m']:,} m".replace(",", "."))
        if job.duration:
            bits.append(job.duration)
        if st.get("max_m") is not None:
            bits.append(f"zirve {st['max_m']:,} m".replace(",", "."))
        sub = "  ·  ".join(bits)
    if not sub and not model.stats:
        la, lo = model.bbox.center
        sub = f"{abs(la):.4f}° {'K' if la >= 0 else 'G'}  {abs(lo):.4f}° {'D' if lo >= 0 else 'B'}"
    return title, sub


def _profile_shape(model: Model, w: float, h: float):
    """Filled elevation-profile silhouette w x h mm centred at the origin."""
    segs = model.stats.get("_profile_src")
    if not segs:
        return Polygon()
    pts = [p for s in segs for p in s]
    a = np.array([(p[0], p[1]) for p in pts])
    e = np.array([p[2] if p[2] is not None else np.nan for p in pts], dtype=float)
    if np.isnan(e).any():
        e = np.where(np.isnan(e), data.sample_elevation(a[:, 0], a[:, 1], 30), e)
    la = np.radians(a[:, 0])
    d = np.r_[0, np.cumsum(6371000 * np.hypot(np.diff(la), np.radians(np.diff(a[:, 1])) * np.cos(la[1:])))]
    if d[-1] <= 0:
        return Polygon()
    xs = np.linspace(0, d[-1], 160)
    es = np.interp(xs, d, e)
    es = np.convolve(es, np.ones(5) / 5, mode="same")
    lo, hi = es.min(), es.max()
    yy = (es - lo) / max(hi - lo, 1) * (h * 0.85) + h * 0.15
    xx = xs / d[-1] * w
    poly = Polygon([(0, 0), *zip(xx, yy), (w, 0)]).buffer(0)
    return affinity.translate(poly, -w / 2, -h / 2)


FALLBACK = {"rocks": "buildings", "streams": "water", "forest": "green", "rail": "roads", "paths": "roads", "ruins": "buildings", "sea": "water", "water": "sea", "markers": "route", "text": "frame"}


def _color(col: dict, role: str) -> str:
    """Colour of a role; roles a theme does not define borrow a related one (paths -> roads, ...)."""
    if role in col:
        return col[role]
    if role in FALLBACK and FALLBACK[role] in col:
        return col[FALLBACK[role]]
    return col.get("terrain", "#FFFFFF")


def make_parts(job: Job, model: Model) -> None:
    S, Z, xs, ys = model.outline, model.z, model.xs, model.ys
    col = job.colors
    L = job.layers
    big = float(Z.max()) + 40
    clip = prism(S, -1, big)
    T = heightfield(xs, ys, Z) ^ clip
    parts: list[Part] = []
    G = model.layers

    # priority: a higher layer removes its footprint from all lower ones
    taken = Polygon()
    bldg = G.get("buildings") or []
    bfoot = unary_union([g for g, _ in bldg]) if bldg else Polygon()
    marker_geoms: list[tuple[Polygon, str]] = []  # (outline, colour)
    if L.get("markers"):
        size = max(4.0, min(10.0, job.size_mm * 0.04))
        mcol = _color(col, "markers")
        if model.route_mm and job.route_endpoints:
            s0, s1 = model.route_mm[0].coords[0], model.route_mm[-1].coords[-1]
            marker_geoms.append((Point(s0).buffer(size * 0.35, 32), mcol))
            marker_geoms.append((affinity.translate(marker_shape("star", size), *s1), mcol))
        for m in job.markers:
            x, y = model.proj.mm(m.lat, m.lon)
            if S.contains(Point(x, y)):
                c = m.color.upper() if (m.color or "").startswith("#") and len(m.color) == 7 else mcol
                marker_geoms.append((affinity.translate(marker_shape(m.kind or job.marker_kind, size), float(x), float(y)), c))
    mfoot = unary_union([g for g, _ in marker_geoms]) if marker_geoms else Polygon()

    order = [l for l in reversed(LAYER_ORDER)]  # highest first
    for lay in order:
        if lay == "buildings":
            taken = taken.union(bfoot)
            continue
        if lay == "markers":
            taken = taken.union(mfoot)
            continue
        g = G.get(lay)
        if g is None or g.is_empty:
            continue
        g = g.difference(taken)
        G[lay] = g
        taken = taken.union(g)

    # draped layers
    for lay in ("green", "forest", "rocks", "water", "streams", "sea", "paths", "roads", "rail", "route"):
        g = G.get(lay)
        if g is None or g.is_empty or not L.get(lay, False):
            continue
        shell = (heightfield(xs, ys, Z + DRAPE[lay]) ^ prism(g, -1, big)) - T
        if not shell.is_empty():
            parts.append(Part(lay, lay, _color(col, lay), shell))

    # ruins: small = solid +1.6 mm, large courtyards = 1.4 mm walls + low floor
    g = G.get("ruins")
    if g is not None and not g.is_empty and L.get("ruins"):
        small, ring, floor = [], [], []
        for p in polys(g):
            if p.area > 150:
                inner = p.buffer(-1.4)
                ring.append(p.difference(inner))
                floor.append(inner)
            else:
                small.append(p.buffer(0.15))
        solid_g = unary_union(small + ring)
        sol = (heightfield(xs, ys, Z + 1.8) ^ prism(solid_g, -1, big))
        if floor:
            sol = sol + (heightfield(xs, ys, Z + 0.5) ^ prism(unary_union(floor), -1, big))
        sol = sol - T
        if not sol.is_empty():
            parts.append(Part("ruins", "ruins", _color(col, "ruins"), sol))

    # buildings: flat roofs, grouped by roof height
    if bldg and L.get("buildings"):
        k = model.proj.mm_per_m
        groups: dict[float, list] = {}
        for p, h_m in bldg:
            for q in polys(p):
                if q.area < 0.5:
                    continue
                mrr = q.minimum_rotated_rectangle
                if mrr.geom_type == "Polygon":
                    c = np.asarray(mrr.exterior.coords)
                    if min(np.hypot(*(c[1] - c[0])), np.hypot(*(c[2] - c[1]))) < MIN_FEATURE:
                        continue
                bs = job.building_scale or float(np.clip(2.5 / (10.0 * k), 1.0, 4.0))
                top = max_under(xs, ys, Z, q) + max(h_m * k * bs, 0.8)
                groups.setdefault(round(top / 0.2) * 0.2, []).append(q)
        sol = m3.Manifold()
        for top, ps in groups.items():
            sol = sol + prism(unary_union(ps), 0, top)
        sol = (sol ^ clip) - T
        if not sol.is_empty():
            parts.append(Part("buildings", "buildings", _color(col, "buildings"), sol))

    # markers
    if marker_geoms:
        by_color: dict[str, m3.Manifold] = {}
        for mg, c in marker_geoms:
            top = max_under(xs, ys, Z + 1.0, mg) + MARKER_H
            by_color[c] = by_color.get(c, m3.Manifold()) + prism(mg.intersection(S.buffer(-0.4)), 0, top)
        allm = m3.Manifold()
        for c in by_color:  # earlier colours win where two markers overlap
            by_color[c] = by_color[c] - T - allm
            allm = allm + by_color[c]
        # markers cut into anything below them
        parts = [Part(p.name, p.role, p.color, p.solid - allm) for p in parts]
        for i, (c, sol) in enumerate(by_color.items()):
            if not sol.is_empty():
                parts.append(Part("markers" if i == 0 else f"markers_{i + 1}", "markers", c, sol))

    # terrain (optionally colour-banded by elevation)
    mode = get_mode(job.mode)
    bands = mode.theme(job.theme).bands if L.get("terrain") else []
    if job.colors.get("terrain") != mode.theme(job.theme).colors.get("terrain"):
        bands = []  # a custom terrain colour switches the theme bands off
    if bands and len(bands) > 1:
        e_base = 0.0 if sea_mask(model.elev).any() or not (model.elev > 0.5).any() else float(model.elev[model.elev > 0.5].min()) - 2.0
        cuts = []
        for e0, c_ in bands[1:]:
            zc = job.base_mm + (e0 - e_base) * model.proj.mm_per_m * model.z_exag
            if job.base_mm + 0.6 < zc < float(Z.max()) - 0.4:
                cuts.append((zc, c_))
        lo_z, lo_c = -1.0, bands[0][1]
        for i, (zc, c_) in enumerate(cuts + [(big, None)]):
            slab = T ^ m3.Manifold.cube([4000, 4000, zc - lo_z]).translate([-2000, -2000, lo_z])
            if not slab.is_empty():
                parts.append(Part("terrain" if i == 0 else f"terrain_{i + 1}", "terrain" if i == 0 else f"band{i}", lo_c, slab))
            lo_z, lo_c = zc, c_
    else:
        parts.append(Part("terrain", "terrain", col.get("terrain", "#FFFFFF"), T))

    # frame + caption
    footprint = S
    if L.get("frame") or L.get("caption"):
        ring, band = frame_geometry(job, S, bool(L.get("caption")))
        fh = job.base_mm + (2.0 if L.get("terrain") else 1.2)
        F = prism(ring, 0, fh)
        footprint = S.union(ring)
        texts = []
        if band is not None:
            title, sub = _caption_text(job, model)
            bx0, by0, bx1, by1 = band.bounds
            bw, bh = bx1 - bx0, by1 - by0
            cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
            prof_w = bw * 0.28 if (L.get("profile") and model.stats.get("_profile_src")) else 0
            tw = bw - prof_w - 6
            tx = bx0 + 3 + tw / 2
            if sub:
                t1 = fit_text(title, tw, bh * 0.36, job.font or None)
                t2 = fit_text(sub, tw, bh * 0.22, job.font or None)
                texts += [affinity.translate(t1, tx, cy + bh * 0.17), affinity.translate(t2, tx, cy - bh * 0.22)]
            else:
                texts.append(affinity.translate(fit_text(title, tw, bh * 0.45, job.font or None), tx, cy))
            if prof_w:
                pr = _profile_shape(model, prof_w - 4, bh * 0.7)
                texts.append(affinity.translate(pr, bx1 - prof_w / 2 - 1, cy))
            model.caption = {"title": title, "subtitle": sub}
        tg = unary_union([t for t in texts if not t.is_empty]) if texts else Polygon()
        if not tg.is_empty:
            tg = tg.intersection(ring.buffer(-0.5))
            parts.append(Part("text", "text", _color(col, "text"), prism(tg, fh - 0.01, fh + TEXT_H)))
        parts.append(Part("frame", "frame", col.get("frame", col.get("terrain", "#FFFFFF")), F))
        if band is not None and band.intersects(S):
            # the label plate covers part of the map: cut everything else away under it
            under = prism(band.intersection(S), -1, big)
            parts = [p if p.role in ("frame", "text") else Part(p.name, p.role, p.color, p.solid - under) for p in parts]
            F2 = prism(band.intersection(S), 0, fh)
            parts = [Part(p.name, p.role, p.color, p.solid + F2) if p.role == "frame" else p for p in parts]

    model.footprint = footprint

    # wall mount: keyhole slot in the bottom, near the top edge
    if job.wall_mount:
        if job.base_mm < 4:
            model.warnings.append("Duvar askısı için taban en az 4 mm olmalı; askı eklenmedi.")
        else:
            x0, y0, x1, y1 = footprint.bounds
            kx, ky = (x0 + x1) / 2, y1 - 22
            slot = unary_union([Point(kx, ky).buffer(4.2, 32), box(kx - 2.1, ky, kx + 2.1, ky + 9), Point(kx, ky + 9).buffer(2.1, 24)])
            hole = prism(slot, -1, 2.6)
            parts = [Part(p.name, p.role, p.color, p.solid - hole) if p.role in ("terrain", "frame") else p for p in parts]

    model.parts = [p for p in parts if not p.solid.is_empty()]
