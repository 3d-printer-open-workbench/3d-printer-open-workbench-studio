"""Ornaments: a seeded six-fold snowflake (every seed is a different flake) with an optional centre text, or a
photo lithophane (thickness follows the photo's darkness; it shows the picture against light) in a frame. Both
hang from a reinforced eye."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageOps
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box
from shapely.ops import unary_union

from .. import core, estimate, flat
from ..shapes import shape_polygon
from .base import BuildResult, Generator, Param, Part

LITHO_RES = 0.2  # mm per height-field cell
LITHO_ORCA = {"sparse_infill_density": "100%", "layer_height": "0.12"}


def snowflake(size: float, seed: int, arm_w: float) -> Polygon:
    """Six identical, mirror-symmetric arms; branch positions / lengths / tips from ``seed``."""
    rng = np.random.default_rng(seed)
    R = size / 2 - arm_w
    arm = [LineString([(0, 0), (0, R)])]
    n = int(rng.integers(2, 5))
    ts = np.sort(rng.uniform(0.25, 0.85, n))
    for t in ts:
        L = R * rng.uniform(0.18, 0.42) * (1.1 - t)
        ang = math.radians(rng.choice([45, 60, 60, 70]))
        y = t * R
        tip = (L * math.sin(ang), y + L * math.cos(ang))
        arm.append(LineString([(0, y), tip]))
        if rng.random() < 0.5:  # small twig on the branch
            s = L * 0.45
            mid = (tip[0] * 0.55, y + (tip[1] - y) * 0.55)
            arm.append(LineString([mid, (mid[0] + s * math.sin(ang - 1.0), mid[1] + s * math.cos(ang - 1.0))]))
    g = unary_union([a.buffer(arm_w / 2, cap_style=1, quad_segs=8) for a in arm])
    if rng.random() < 0.6:  # diamond tip
        d = arm_w * rng.uniform(1.4, 2.2)
        g = g.union(Polygon([(0, R - d), (d * 0.7, R), (0, R + d), (-d * 0.7, R)]))
    one = unary_union([g, affinity.scale(g, -1, 1, origin=(0, 0))])
    flake = unary_union([affinity.rotate(one, 60 * k, origin=(0, 0)) for k in range(6)])
    hub = Point(0, 0).buffer(R * rng.uniform(0.12, 0.22), quad_segs=6 if rng.random() < 0.5 else 24)
    return unary_union([flake, hub]).buffer(0.2).buffer(-0.2)


def _heightfield_mesh(h: np.ndarray, x0: float, y0: float, res: float) -> trimesh.Trimesh:
    """Closed slab: top surface z = h (rows = y, cols = x), flat bottom at z = 0."""
    ny, nx = h.shape
    xs, ys = x0 + np.arange(nx) * res, y0 + np.arange(ny) * res
    X, Y = np.meshgrid(xs, ys)
    top = np.c_[X.ravel(), Y.ravel(), h.ravel()]
    bot = np.c_[X.ravel(), Y.ravel(), np.zeros(h.size)]
    V = np.vstack([top, bot])
    idx = np.arange(h.size).reshape(ny, nx)
    a, b, c, d = idx[:-1, :-1], idx[:-1, 1:], idx[1:, 1:], idx[1:, :-1]
    F = [np.c_[a.ravel(), b.ravel(), c.ravel()], np.c_[a.ravel(), c.ravel(), d.ravel()]]
    o = h.size
    F += [np.c_[a.ravel() + o, c.ravel() + o, b.ravel() + o], np.c_[a.ravel() + o, d.ravel() + o, c.ravel() + o]]
    ring = list(idx[0, :]) + list(idx[1:, -1]) + list(idx[-1, -2::-1]) + list(idx[-2:0:-1, 0])  # boundary, CCW
    for i in range(len(ring)):
        p, q = ring[i], ring[(i + 1) % len(ring)]
        F += [np.array([[p, p + o, q]]), np.array([[q, p + o, q + o]])]
    m = trimesh.Trimesh(V, np.vstack(F), process=True)
    if m.volume < 0:
        m.invert()
    return m


def lithophane(path: str, outline: Polygon, t_min: float, t_max: float, gamma: float) -> trimesh.Trimesh:
    """Photo height field cropped to ``outline`` (cover fit): dark = thick."""
    x0, y0, x1, y1 = outline.bounds
    nx, ny = int(math.ceil((x1 - x0) / LITHO_RES)) + 1, int(math.ceil((y1 - y0) / LITHO_RES)) + 1
    im = ImageOps.exif_transpose(Image.open(path)).convert("L")
    im = ImageOps.fit(im, (nx, ny), Image.LANCZOS)  # cover crop, centred
    lum = np.asarray(im, dtype=float)[::-1] / 255.0  # image row 0 = top -> y max
    h = t_min + (t_max - t_min) * (1.0 - lum) ** gamma
    slab = _heightfield_mesh(h, x0, y0, LITHO_RES)
    return core.to_trimesh(core.from_trimesh(slab) ^ core.extrude(outline, -1.0, t_max + 1.0))


def build(v: dict) -> BuildResult:
    w: list[str] = []
    c = core.norm_hex(v["color"])
    notes = []
    meta: dict = {}
    if v["kind"] == "snowflake":
        g = snowflake(v["size_mm"], v["seed"], v["arm_mm"])
        txt = v["text"].strip()
        layers_top = []
        if txt:
            hub = Point(0, 0).buffer(v["size_mm"] * 0.16, quad_segs=6)
            g = g.union(hub)
            tg, _ = flat.fit_text(txt, v["font"], hub.buffer(-1.2), v["size_mm"] * 0.28, w, "Orta yazı")
            layers_top = [("text", "Orta yazı", tg, v["thick_mm"], v["thick_mm"] + 0.6, core.norm_hex(v["text_color"]))]
        top_y = g.bounds[3]  # eye on the top arm tip
        eye = Point(0, top_y + 2.5).buffer(4.2, quad_segs=24)
        hole = Point(0, top_y + 2.5).buffer(2.0, quad_segs=24)
        g = unary_union([g, eye, box(-1.6, top_y - 3, 1.6, top_y + 1)])
        parts = flat.layer_parts([("flake", "Kar tanesi", g, 0.0, v["thick_mm"], c)] + layers_top, "ornament", cuts=hole)
        notes.append(f"Kar tanesi #{v['seed']}: her numara farklı bir desen. Ø{v['size_mm']:g} mm, {v['thick_mm']:g} mm.")
    else:
        if not v["photo"] or not Path(v["photo"]).is_file():
            raise ValueError("Litofan için fotoğraf seçin (JPG / PNG).")
        W = v["size_mm"]
        outline = shape_polygon(v["shape"], W) if v["shape"] != "rect" else box(-W / 2, -W * 0.375, W / 2, W * 0.375).buffer(-2).buffer(2)
        frame_w = 3.0
        pic = outline.buffer(-frame_w, quad_segs=12)
        litho = lithophane(v["photo"], pic, v["t_min"], v["t_max"], v["gamma"])
        ft = v["t_max"] + 0.6
        frame = core.extrude(outline.difference(pic.buffer(-0.01)), 0.0, ft)
        top_y = outline.bounds[3]
        eye = core.extrude(Point(0, top_y + 2.5).buffer(4.5, quad_segs=24).union(box(-2, top_y - 2, 2, top_y + 1)), 0.0, ft)
        eye = eye - core.extrude(Point(0, top_y + 2.5).buffer(2.0, quad_segs=24), -1, ft + 1)
        solid = core.union_all([core.from_trimesh(litho), frame, eye])
        mesh = core.to_trimesh(solid)
        e = estimate.part_estimate(mesh, "PLA", "solid")  # 100 % infill, 0.12 mm layers
        parts = [Part("lithophane", "Litofan", mesh, c, "PLA", {"group": "litho", "batch": "litho", "orca": LITHO_ORCA,
                                                               "grams": e.grams, "minutes": e.minutes, "cost_try": e.try_})]
        notes += ["Litofan beyaz PLA ile basılır ve ışığa tutulunca görünür (lamba, pencere, LED mum). Koyu yerler kalın, açık yerler ince.",
                  "model.3mf'te bu nesneye %100 dolgu ve 0.12 mm katman ayarlı (ayrı tabla). Fotoğraf kontrastlı ve yüz büyük olsun."]
        meta["size_mm"] = [round(x, 1) for x in mesh.extents]
    for p in parts:
        p.meta["count"] = v["count"]
    notes.insert(0, f"~{sum(p.meta['grams'] for p in parts):.0f} g ≈ {sum(p.meta['cost_try'] for p in parts):.0f} TL / adet.")
    notes.append("Asmak için ip ya da kurdele: üstteki halkadan geçirin.")
    return BuildResult(parts, w, meta, notes)


GENERATOR = Generator(
    key="ornament", label="Kar tanesi / fotoğraf süsü", group="Yılbaşı",
    description="Her numarası farklı kar tanesi (ortasına yıl ya da isim) ya da fotoğraftan litofan süs: ışığa tutunca fotoğraf görünür.",
    params=[
        Param("kind", "Tür", "choice", "snowflake", options=[("snowflake", "Kar tanesi"), ("photo", "Fotoğraf (litofan)")], section="Süs"),
        Param("size_mm", "Boyut", "number", 80, min=30, max=200, step=1, unit="mm", section="Süs"),
        Param("seed", "Desen numarası", "int", 7, min=1, max=9999, section="Kar tanesi", show_if={"kind": "snowflake"}),
        Param("arm_mm", "Kol kalınlığı", "number", 3.0, min=1.6, max=8, step=0.2, unit="mm", section="Kar tanesi", show_if={"kind": "snowflake"}),
        Param("thick_mm", "Kalınlık", "number", 2.4, min=1.2, max=6, step=0.2, unit="mm", section="Kar tanesi", show_if={"kind": "snowflake"}),
        Param("text", "Orta yazı", "text", "", section="Kar tanesi", show_if={"kind": "snowflake"}, help="ör. 2026"),
        Param("font", "Yazı tipi", "font", "Righteous", section="Kar tanesi", show_if={"kind": "snowflake"}),
        Param("text_color", "Yazı rengi", "color", "#3E7CB1", section="Kar tanesi", show_if={"kind": "snowflake"}),
        Param("photo", "Fotoğraf", "file", "", section="Litofan", show_if={"kind": "photo"}, help="JPG / PNG"),
        Param("shape", "Şekil", "choice", "circle", options=[("circle", "Daire"), ("heart", "Kalp"), ("rect", "Dikdörtgen"), ("hexagon", "Altıgen"),
                                                              ("star", "Yıldız")], section="Litofan", show_if={"kind": "photo"}),
        Param("t_min", "En ince", "number", 0.8, min=0.4, max=2, step=0.1, unit="mm", section="Litofan", show_if={"kind": "photo"}),
        Param("t_max", "En kalın", "number", 3.0, min=1.5, max=6, step=0.1, unit="mm", section="Litofan", show_if={"kind": "photo"}),
        Param("gamma", "Kontrast", "number", 1.0, min=0.5, max=2.5, step=0.1, section="Litofan", show_if={"kind": "photo"},
              help="1'den büyük: koyular daha belirgin"),
        Param("color", "Renk", "color", "#FFFFFF", section="Baskı"),
        Param("count", "Adet", "int", 1, min=1, max=12, section="Baskı"),
    ],
    build=build,
)
