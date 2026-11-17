"""Demo generator: a flat plate in a basic shape with optional raised text. Proves the T0 pipeline."""
from __future__ import annotations

from shapely import affinity
from shapely.ops import polylabel

from .. import core
from ..shapes import SHAPES_TR, shape_polygon
from .base import BuildResult, Generator, Param, Part


def build(v: dict) -> BuildResult:
    outline = shape_polygon(v["shape"], v["width_mm"])
    warnings: list[str] = []
    base = core.to_trimesh(core.extrude(outline, 0.0, v["thickness_mm"]))
    parts = [Part("plate", "Plaka", base, v["color"])]
    if v["text"].strip():
        x0, y0, x1, y1 = outline.bounds
        g, w = core.text_geometry(v["text"], v["font"], width_mm=(x1 - x0) * v["text_pct"] / 100)
        warnings += w
        inner = outline.buffer(-1.5)
        c = polylabel(outline, tolerance=0.5)  # visual centre (e.g. the wide upper part of a heart), not the bbox centre
        gx0, gy0, gx1, gy1 = g.bounds
        g = affinity.translate(g, c.x - (gx0 + gx1) / 2, c.y - (gy0 + gy1) / 2)
        k = 1.0
        while not inner.contains(g) and k > 0.3:  # shrink the text until it fits inside the shape
            g = affinity.scale(g, 0.95, 0.95, origin=c)
            k *= 0.95
        if not inner.contains(g):
            warnings.append("Yazı bu şekle sığmıyor; daha kısa bir yazı ya da daha büyük bir şekil seçin.")
        elif k < 0.999:
            warnings.append(f"Yazı şekle sığsın diye %{round(k * 100)} oranında küçültüldü.")
            _, w2 = core.text_geometry(v["text"], v["font"], width_mm=(x1 - x0) * v["text_pct"] / 100 * k)
            warnings += [x for x in w2 if x not in warnings]
        t = v["thickness_mm"]
        parts.append(Part("text", "Yazı", core.to_trimesh(core.extrude(g, t, t + v["relief_mm"])), v["text_color"]))
    return BuildResult(parts, warnings, {"outline_mm": [round(x, 1) for x in outline.bounds]})


GENERATOR = Generator(
    key="plate", label="Şekil plakası (deneme)", group="Deneme",
    description="Hazır şekilde düz plaka ve üstünde kabartma yazı. Altyapıyı (form → 3B → dosyalar) denemek için.",
    params=[
        Param("shape", "Şekil", "choice", "heart", options=list(SHAPES_TR.items()), section="Şekil"),
        Param("width_mm", "Genişlik", "number", 80, min=20, max=250, step=1, unit="mm", section="Şekil"),
        Param("thickness_mm", "Kalınlık", "number", 3, min=1, max=20, step=0.2, unit="mm", section="Şekil"),
        Param("color", "Plaka rengi", "color", "#C8664A", section="Şekil"),
        Param("text", "Yazı", "text", "Ayşe", section="Yazı"),
        Param("font", "Yazı tipi", "font", "Righteous", section="Yazı"),
        Param("text_pct", "Yazı genişliği", "int", 60, min=20, max=90, unit="%", help="Şekil genişliğine göre", section="Yazı"),
        Param("relief_mm", "Kabartma", "number", 1.0, min=0.4, max=5, step=0.2, unit="mm", section="Yazı"),
        Param("text_color", "Yazı rengi", "color", "#FFFFFF", section="Yazı"),
    ],
    build=build,
)
