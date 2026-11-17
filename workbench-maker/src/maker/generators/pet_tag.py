"""Pet tag: bone / round / heart / hexagon / shield, pet name raised on the front, phone either raised under the name or
engraved (mirrored) into the back, optional second back line; reinforced eye on top for an S-hook or split ring."""
from __future__ import annotations

import numpy as np
from shapely import affinity
from shapely.geometry import Point, Polygon, box
from shapely.ops import unary_union

from .. import core, flat
from ..shapes import shape_polygon
from .base import BuildResult, Generator, Param

ENGRAVE_MM = 0.6  # back text depth (3 layers)
SHAPES = {"bone": "Kemik", "circle": "Daire", "heart": "Kalp", "hexagon": "Altıgen", "shield": "Kalkan"}


def tag_outline(kind: str, width: float) -> Polygon:
    if kind == "bone":
        h = width * 0.55
        r = h * 0.3
        knobs = [Point(sx * (width / 2 - r), sy * (h / 2 - r)).buffer(r, quad_segs=24) for sx in (-1, 1) for sy in (-1, 1)]
        g = unary_union(knobs + [box(-width / 2 + r, -h * 0.34, width / 2 - r, h * 0.34)])
        return Polygon(g.buffer(1.2, quad_segs=12).buffer(-1.2, quad_segs=12).exterior)
    if kind == "shield":
        t = np.linspace(0, np.pi, 40)
        bottom = np.c_[0.5 * np.cos(t + np.pi), -0.15 - 0.55 * np.sin(t)]  # rounded point
        g = Polygon([(-0.5, 0.5), (0.5, 0.5)] + [tuple(p) for p in bottom[::-1]]).buffer(0.06, quad_segs=12)
        g = affinity.translate(g, -(g.bounds[0] + g.bounds[2]) / 2, -(g.bounds[1] + g.bounds[3]) / 2)
        return affinity.scale(g, width / (g.bounds[2] - g.bounds[0]), width / (g.bounds[2] - g.bounds[0]), origin=(0, 0))
    return shape_polygon(kind, width)


def build(v: dict) -> BuildResult:
    w: list[str] = []
    if not v["name"].strip():
        raise ValueError("Künye için hayvanın adını yazın.")
    t, r = v["base_mm"], v["relief_mm"]
    bc, tc = core.norm_hex(v["base_color"]), core.norm_hex(v["text_color"])
    outline = tag_outline(v["shape"], v["width_mm"])
    inner = outline.buffer(-max(1.6, v["width_mm"] * 0.06))
    x0, y0, x1, y1 = inner.bounds
    front_phone = v["phone"].strip() and v["phone_side"] == "front"
    split = y0 + (y1 - y0) * 0.38 if front_phone else None
    top = []
    name_region = flat.band(inner, split + 1.0, y1) if front_phone else inner
    centre = Point(0, (split + 1.0 + y1) / 2 if front_phone else 0) if v["shape"] == "bone" else None  # not in a knob
    g, _ = flat.fit_text(v["name"], v["font"], name_region, (x1 - x0) * 0.9, w, "İsim", centre)
    top.append(("name", "İsim", g, tc))
    if front_phone:
        centre = Point(0, (y0 + split - 1.0) / 2) if v["shape"] == "bone" else None
        g, _ = flat.fit_text(v["phone"], v["phone_font"], flat.band(inner, y0, split - 1.0), (x1 - x0) * 0.8, w, "Telefon", centre)
        top.append(("phone", "Telefon", g, tc))
    outline, hole = flat.ring_tab(outline, "top", v["hole_mm"], wall=2.8)
    layers = [("tag", "Künye", outline, 0.0, t, bc)] + [(n, lb, g, t, t + r, c) for n, lb, g, c in top]
    parts = flat.layer_parts(layers, "pet_tag", material=v["material"], cuts=hole)
    back = [s for s in ([v["phone"]] if v["phone"].strip() and not front_phone else []) + [v["back_text"]] if s.strip()]
    if back:
        lines = "\n".join(back[:2])
        g, _ = flat.fit_text(lines, v["phone_font"], inner.difference(hole.buffer(1.5)), (x1 - x0) * 0.85, w, "Arka yazı",
                             Point(0, 0) if v["shape"] == "bone" else None)
        g = affinity.scale(g, -1, 1, origin=(0, 0))  # mirrored: reads correctly when the tag is turned over
        base = parts[0]
        base.mesh = core.to_trimesh(core.from_trimesh(base.mesh) - core.extrude(g, -0.01, ENGRAVE_MM))
        base.label += " (arkada kazıma yazı)"
    for p in parts:
        p.meta["count"] = v["count"]
    grams = sum(p.meta["grams"] for p in parts)
    bx0, by0, bx1, by1 = outline.bounds
    notes = [f"Künye {bx1 - bx0:.0f} × {by1 - by0:.0f} × {t + r:.1f} mm, ~{grams:.1f} g ≈ {sum(p.meta['cost_try'] for p in parts):.1f} TL / adet."]
    if back:
        notes.append(f"Arka yazı tabana {ENGRAVE_MM:g} mm gömülü ve aynalı (tablaya bakan yüz); ilk katman düzgün olsun diye tablayı temizleyin.")
    notes.append("Halka için S-kanca ya da Ø15–20 mm çelik halka kullanın.")
    if v["material"] == "PLA":
        notes.append("PLA güneşte ve sıcak arabada yumuşayabilir; sürekli dışarıda olan hayvanlar için malzemeyi PETG seçin.")
    return BuildResult(parts, w, {"size_mm": [round(bx1 - bx0, 1), round(by1 - by0, 1), round(t + r, 1)]}, notes)


GENERATOR = Generator(
    key="pet_tag", label="Evcil hayvan künyesi", group="Evcil hayvan",
    description="Kemik, daire, kalp, altıgen ya da kalkan künye: önde kabartma isim, telefon önde ya da arkada kazıma, üstte güçlü halka.",
    params=[
        Param("shape", "Şekil", "choice", "bone", options=list(SHAPES.items()), section="Künye"),
        Param("width_mm", "Genişlik", "number", 45, min=25, max=70, step=1, unit="mm", section="Künye"),
        Param("name", "İsim", "text", "Pamuk", section="Yazı"),
        Param("font", "İsim yazı tipi", "font", "Righteous", section="Yazı"),
        Param("phone", "Telefon", "text", "0532 123 45 67", section="Yazı"),
        Param("phone_side", "Telefon yeri", "choice", "back", options=[("back", "Arkada (kazıma)"), ("front", "Önde (kabartma)")], section="Yazı"),
        Param("back_text", "Arka ek satır", "text", "", section="Yazı", help="ör. 'Bulursanız arayın'"),
        Param("phone_font", "Telefon yazı tipi", "font", "Righteous", section="Yazı"),
        Param("base_color", "Künye rengi", "color", "#E0453A", section="Renk ve kalınlık"),
        Param("text_color", "Yazı rengi", "color", "#FFFFFF", section="Renk ve kalınlık"),
        Param("material", "Malzeme", "choice", "PLA", options=[("PLA", "PLA"), ("PETG", "PETG (dış mekân)")], section="Renk ve kalınlık"),
        Param("base_mm", "Kalınlık", "number", 3, min=2, max=5, step=0.2, unit="mm", section="Renk ve kalınlık"),
        Param("relief_mm", "Kabartma", "number", 0.8, min=0.4, max=2, step=0.2, unit="mm", section="Renk ve kalınlık"),
        Param("hole_mm", "Halka deliği", "number", 4.5, min=3, max=7, step=0.5, unit="mm", section="Renk ve kalınlık"),
        Param("count", "Adet", "int", 1, min=1, max=40, section="Baskı"),
    ],
    build=build,
)
