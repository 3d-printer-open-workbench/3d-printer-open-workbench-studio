"""Textured roller sleeve: a tube that slides over a dowel / pipe, with a seamless raised pattern (repeated text,
hearts, stars, dots, diamonds, waves or a logo) for cookie dough, fondant or clay. Printed upright; the relief is a
height field with 45 deg flanks, so it needs no support. Text is mirrored so the rolled imprint reads right."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image, ImageDraw
from scipy.ndimage import distance_transform_edt
from shapely import affinity
from shapely.geometry import LineString, Point, box
from shapely.ops import unary_union

from .. import baking, core, flat
from ..shapes import shape_polygon
from .base import BuildResult, Generator, Param

RES = 0.3  # height field cell (mm)
END_MM = 3.0  # plain band at each end


def _tiles(v: dict, C: float, L: float, warnings: list[str]):
    """Pattern polygons in the unwrapped plane (u along the circumference 0..C, v along the length 0..L), seamless in u."""
    kind, s = v["pattern"], v["size_mm"]
    span = L - 2 * END_MM
    if kind == "text":
        if not v["text"].strip():
            raise ValueError("Desen yazısını girin.")
        g = flat.text(v["text"], v["font"], warnings, height_mm=s)
        g = affinity.scale(g, -1, 1, origin=(0, 0))  # mirrored
        unit = g
        uw, uh = g.bounds[2] - g.bounds[0] + s * 1.2, g.bounds[3] - g.bounds[1] + s * 0.8
    elif kind == "logo":
        if not v["logo"] or not Path(v["logo"]).is_file():
            raise ValueError("Logo dosyası seçin (SVG, PNG ya da JPG).")
        logo = core.load_logo(v["logo"], s, 1)
        warnings += logo.warnings
        unit = affinity.scale(unary_union([r.geometry for r in logo.regions]), -1, 1, origin=(0, 0))
        uw, uh = logo.width_mm + s * 0.4, logo.height_mm + s * 0.4
    elif kind in ("hearts", "stars"):
        unit = shape_polygon("heart" if kind == "hearts" else "star", s)
        uw = uh = s * 1.6
    elif kind == "dots":
        unit = Point(0, 0).buffer(s / 2, quad_segs=16)
        uw = uh = s * 2.0
    elif kind == "diamonds":  # raised lattice lines at +-45 deg
        n_u = max(2, round(C / s))
        p = C / n_u
        lines = []
        for k in range(-2 * n_u, 4 * n_u):
            lines.append(LineString([(k * p, 0), (k * p + L, L)]))
            lines.append(LineString([(k * p, 0), (k * p - L, L)]))
        return unary_union(lines).buffer(v["line_mm"] / 2, cap_style=2).intersection(box(-C, END_MM, 2 * C, L - END_MM)), n_u
    elif kind == "waves":
        n_u = max(1, round(C / (2 * s)))
        p = C / n_u
        u = np.linspace(-C, 2 * C, 1200)
        lines = [LineString(np.c_[u, y + s * 0.35 * np.sin(2 * np.pi * u / p)]) for y in np.arange(END_MM + s / 2, L - END_MM, s * 0.8)]
        return unary_union(lines).buffer(v["line_mm"] / 2), n_u
    else:
        raise ValueError(f"bilinmeyen desen: {kind}")
    n_u = max(1, math.floor(C / uw))
    pu = C / n_u
    rows = max(1, math.floor(span / uh))
    pv = span / rows
    x0, y0, x1, y1 = unit.bounds
    unit = affinity.translate(unit, -(x0 + x1) / 2, -(y0 + y1) / 2)
    out = []
    for r in range(rows):
        off = pu / 2 if r % 2 else 0.0  # staggered rows
        for k in range(-1, n_u + 1):
            out.append(affinity.translate(unit, k * pu + off + pu / 2, END_MM + (r + 0.5) * pv))
    if n_u * (unit.bounds[2] - unit.bounds[0]) > C:
        warnings.append("Desen çevreye sığmıyor; boyutu küçültün ya da çapı büyütün.")
    return unary_union(out), n_u


def height_field(pattern, C: float, L: float, relief: float) -> np.ndarray:
    """Relief height (Nu x Nv) from the pattern: 45 deg flanks (distance inside the shape), periodic in u."""
    nu, nv = int(math.ceil(C / RES)), int(math.ceil(L / RES))
    du, dv = C / nu, L / nv
    im = Image.new("L", (nu, nv), 0)
    d = ImageDraw.Draw(im)
    for g in getattr(pattern, "geoms", [pattern]):
        if g.is_empty or g.geom_type != "Polygon":
            continue
        for sh in (-C, 0.0, C):
            d.polygon([((x + sh) / du, y / dv) for x, y in g.exterior.coords], fill=1)
            for ring in g.interiors:
                d.polygon([((x + sh) / du, y / dv) for x, y in ring.coords], fill=0)
    mask = np.array(im, dtype=bool).T  # (nu, nv)
    big = np.concatenate([mask, mask, mask], axis=0)
    dist = distance_transform_edt(big, sampling=(du, dv))[nu:2 * nu]
    h = np.minimum(dist, relief)
    h[:, : int(END_MM / dv)] = 0.0
    h[:, nv - int(END_MM / dv):] = 0.0
    return h


def sleeve_mesh(h: np.ndarray, R: float, r_in: float, L: float) -> trimesh.Trimesh:
    """Closed tube: outer radius R + h (Nu x Nv grid, z 0..L), plain inner bore r_in."""
    nu, nv = h.shape
    hh = np.concatenate([h, h[:, -1:]], axis=1)  # nv + 1 rings so z reaches L
    a = np.arange(nu) * 2 * np.pi / nu
    z = np.linspace(0, L, nv + 1)
    rr = R + hh
    outer = np.stack([rr * np.cos(a)[:, None], rr * np.sin(a)[:, None], np.broadcast_to(z, rr.shape)], axis=-1).reshape(-1, 3)
    inner = np.stack([np.repeat((r_in * np.cos(a))[:, None], 2, 1), np.repeat((r_in * np.sin(a))[:, None], 2, 1),
                      np.broadcast_to([0.0, L], (nu, 2))], axis=-1).reshape(-1, 3)
    V = np.vstack([outer, inner])
    m = nv + 1
    i = np.arange(nu)[:, None]
    j = np.arange(nv)[None, :]
    i1 = (i + 1) % nu
    A, B, Cc, D = i * m + j, i1 * m + j, i1 * m + j + 1, i * m + j + 1
    faces = [np.stack([A, B, Cc], -1).reshape(-1, 3), np.stack([A, Cc, D], -1).reshape(-1, 3)]
    o0 = nu * m
    ii = np.arange(nu)
    in0, in1 = o0 + ii * 2, o0 + ((ii + 1) % nu) * 2  # inner rings: z=0 at +0, z=L at +1
    faces += [np.c_[in0, in0 + 1, in1 + 1], np.c_[in0, in1 + 1, in1]]  # bore, facing the axis
    ob0, ob1 = ii * m, ((ii + 1) % nu) * m  # outer ring z=0
    faces += [np.c_[ob0, in1, ob1], np.c_[ob0, in0, in1]]  # bottom
    ot0, ot1 = ii * m + nv, ((ii + 1) % nu) * m + nv
    faces += [np.c_[ot0, ot1, in1 + 1], np.c_[ot0, in1 + 1, in0 + 1]]  # top
    mesh = trimesh.Trimesh(V, np.vstack(faces), process=False)
    if mesh.volume < 0:
        mesh.invert()
    return mesh


def build(v: dict) -> BuildResult:
    w: list[str] = []
    L = v["length_mm"]
    r_in = v["bore_mm"] / 2 + 0.2
    R = r_in + v["wall_mm"]
    C = 2 * math.pi * R
    pattern, n_u = _tiles(v, C, L, w)
    h = height_field(pattern, C, L, v["relief_mm"])
    if h.max() < v["relief_mm"] * 0.8:
        w.append("Desen çizgileri kabartmaya göre ince: tam yüksekliğe ulaşmıyor. Desen boyutunu ya da çizgi kalınlığını artırın.")
    mesh = sleeve_mesh(h, R, r_in, L)
    p = baking.part("sleeve", "Merdane kılıfı", core.from_trimesh(mesh), core.norm_hex(v["color"]), v["material"])
    p.meta["count"] = v["count"]
    notes = [f"Kılıf Ø{2 * R:.0f} (desen dahil Ø{2 * (R + v['relief_mm']):.0f}) × {L:g} mm, iç çap {2 * r_in:.1f} mm "
             f"(Ø{v['bore_mm']:g} mm boru / çubuk için), çevrede {n_u} tekrar, ~{p.meta['grams']:.0f} g ≈ {p.meta['cost_try']:.0f} TL.",
             "Dik basılır, destek gerekmez (desen kenarları 45°). Bir oklava / PVC boru / ahşap çubuğa geçirin; hamuru açtıktan sonra "
             "tek seferde, eşit bastırarak yuvarlayın."]
    if v["pattern"] in ("text", "logo"):
        notes.append("Yazı / logo aynalı: hamurda doğru okunur.")
    notes += baking.FOOD_NOTES
    return BuildResult([p], w, {"outer_mm": round(2 * R, 1), "repeats": n_u}, notes)


GENERATOR = Generator(
    key="roller", label="Desenli merdane", group="Mutfak",
    description="Oklava / boruya geçen desenli kılıf: tekrar eden yazı, kalp, yıldız, nokta, baklava, dalga ya da logo; kurabiye, şeker hamuru, kil.",
    params=[
        Param("pattern", "Desen", "choice", "hearts", options=[("hearts", "Kalp"), ("stars", "Yıldız"), ("dots", "Nokta"), ("diamonds", "Baklava"),
                                                                ("waves", "Dalga"), ("text", "Yazı"), ("logo", "Logo")], section="Desen"),
        Param("text", "Yazı", "text", "Workbench", section="Desen", show_if={"pattern": "text"}),
        Param("font", "Yazı tipi", "font", "Righteous", section="Desen", show_if={"pattern": "text"}),
        Param("logo", "Logo", "file", "", section="Desen", show_if={"pattern": "logo"}, help="SVG, PNG ya da JPG (tek renk)"),
        Param("size_mm", "Desen boyu", "number", 12, min=4, max=40, step=0.5, unit="mm", section="Desen"),
        Param("line_mm", "Çizgi kalınlığı", "number", 2.0, min=1.0, max=5, step=0.2, unit="mm", section="Desen", show_if={"pattern": ["diamonds", "waves"]}),
        Param("relief_mm", "Kabartma", "number", 1.5, min=0.6, max=3, step=0.1, unit="mm", section="Desen"),
        Param("bore_mm", "Çubuk çapı", "number", 25, min=10, max=60, step=0.5, unit="mm", section="Kılıf", help="Geçireceğiniz oklava / boru çapı"),
        Param("wall_mm", "Duvar", "number", 3, min=2, max=8, step=0.5, unit="mm", section="Kılıf"),
        Param("length_mm", "Uzunluk", "number", 120, min=40, max=240, step=5, unit="mm", section="Kılıf"),
        Param("material", "Malzeme", "choice", "PLA", options=[("PLA", "PLA"), ("PETG", "PETG")], section="Baskı"),
        Param("color", "Renk", "color", "#C8664A", section="Baskı"),
        Param("count", "Adet", "int", 1, min=1, max=4, section="Baskı"),
    ],
    build=build,
)
