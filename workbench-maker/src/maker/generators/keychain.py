"""Keychains: name (bubble outline around the text), shape + name, logo + name; optional edge line, key ring eye on the
left or top, hidden NFC tag pocket (the print pauses so the tag can be dropped in). Colours are stacked layers."""
from __future__ import annotations

from pathlib import Path

from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from .. import core, flat
from ..shapes import SHAPES_TR, shape_polygon
from .base import BuildResult, Generator, Param

RIM_MM = 1.2  # edge line width


def _centre(g):
    x0, y0, x1, y1 = g.bounds
    return affinity.translate(g, -(x0 + x1) / 2, -(y0 + y1) / 2)


def build(v: dict) -> BuildResult:
    w: list[str] = []
    t, r = v["base_mm"], v["relief_mm"]
    tc, bc = core.norm_hex(v["text_color"]), core.norm_hex(v["base_color"])
    top: list[tuple] = []  # (name, label, geometry, colour)
    style = v["style"]
    if style == "name":
        if not v["text"].strip():
            raise ValueError("Anahtarlık için bir isim yazın.")
        g = _centre(flat.text(v["text"], v["font"], w, width_mm=v["width_mm"]))
        top.append(("text", "Yazı", g, tc))
        outline = flat.bubble(g, v["border_mm"])
    elif style == "shape":
        outline = shape_polygon(v["shape"], v["width_mm"])
        if v["text"].strip():
            g, _ = flat.fit_text(v["text"], v["font"], outline.buffer(-max(v["border_mm"], 1.5)), v["width_mm"] * v["text_pct"] / 100, w)
            top.append(("text", "Yazı", g, tc))
    else:
        if not v["logo"] or not Path(v["logo"]).is_file():
            raise ValueError("Logo için dosya seçin (SVG, PNG ya da JPG).")
        logo = core.load_logo(v["logo"], v["width_mm"], v["logo_colors"])
        w += logo.warnings
        lx, ly = logo.width_mm / 2, logo.height_mm / 2
        regs = [(core.norm_hex(rg.color), affinity.translate(rg.geometry, -lx, -ly)) for rg in logo.regions]
        for i, (c, g) in enumerate(regs):
            top.append((f"logo_{i + 1}", f"Logo rengi {i + 1}", g, c))
        if v["text"].strip():
            g = _centre(flat.text(v["text"], v["font"], w, width_mm=v["width_mm"] * v["text_pct"] / 100))
            g = affinity.translate(g, 0, -ly - 2.0 - (g.bounds[3] - g.bounds[1]) / 2)
            top.append(("text", "Yazı", g, tc))
        outline = flat.bubble(unary_union([g for _, _, g, _ in top]), v["border_mm"])
    if v["rim"]:
        top.append(("rim", "Kenar çizgisi", outline.difference(outline.buffer(-RIM_MM, quad_segs=12)), tc))
    if v["nfc"] and flat.nfc_pocket(outline, v["nfc_d"], v["nfc_t"], []) is None:
        # too narrow (e.g. a name): add a round tag medallion on the left, overlapping the outline
        d = v["nfc_d"] + 0.5 + 2 * 2.5
        x0, y0, x1, y1 = outline.bounds
        disc = Point(x0 - d / 2 + v["border_mm"] + 2.0, (y0 + y1) / 2).buffer(d / 2, quad_segs=32)
        outline = Polygon(unary_union([outline, disc]).buffer(1.5, quad_segs=12).buffer(-1.5, quad_segs=12).exterior)
        if v["rim"]:
            top[-1] = ("rim", "Kenar çizgisi", outline.difference(outline.buffer(-RIM_MM, quad_segs=12)), tc)
        top.append(("nfc_icon", "NFC işareti", flat.waves(disc.centroid.coords[0], d * 0.42, 1.4, -90), tc))
        ring_at = disc.centroid.x if v["ring"] == "top" else disc.centroid.y
    else:
        ring_at = None
    outline, hole = flat.ring_tab(outline, v["ring"], v["hole_mm"], at=ring_at)
    notes: list[str] = []
    pocket = None
    if v["nfc"]:
        pocket = flat.nfc_pocket(outline, v["nfc_d"], v["nfc_t"], w, keep_out=hole)
        if pocket is not None:
            need = round(pocket.z1 + flat.NFC_ROOF, 2)
            if t < need:
                w.append(f"NFC yuvası için taban kalınlığı {t:g} → {need:g} mm yapıldı.")
                t = need
            notes.append(f"NFC: baskı Z={pocket.pause_z:g} mm'de duraklar (model.3mf'te hazır). Ø{v['nfc_d']:g} mm etiketi yuvaya koyun, "
                         "yazıcıdan devam edin; üstü kapanır. Etiketi önce telefonla yazıp deneyin (NTAG213/215).")
    layers = [("base", "Taban", outline, 0.0, t, bc)] + [(n, lb, g, t, t + r, c) for n, lb, g, c in top]
    parts = flat.layer_parts(layers, "keychain", cuts=hole, pocket=pocket)
    colors = list(dict.fromkeys(p.color for p in parts))
    if len(colors) > 4:
        raise ValueError(f"{len(colors)} renk var; CANVAS en çok 4 filament alır. Logo renk sayısını azaltın.")
    for p in parts:
        p.meta["count"] = v["count"]
    grams = sum(p.meta["grams"] for p in parts)
    cost = sum(p.meta["cost_try"] for p in parts)
    x0, y0, x1, y1 = outline.bounds
    notes.insert(0, f"Anahtarlık {x1 - x0:.0f} × {y1 - y0:.0f} × {t + r:.1f} mm, ~{grams:.1f} g ≈ {cost:.1f} TL / adet ({v['count']} adet).")
    if len(colors) > 1:
        notes.append(f"{len(colors)} renk üst üste katman: her renk bir öncekinin üstünden başlar, CANVAS adet başına değil "
                     f"tabla başına {len(colors) - 1} kez filament değiştirir (az atık).")
    meta = {"size_mm": [round(x1 - x0, 1), round(y1 - y0, 1), round(t + r, 1)], "colors": colors, "grams_each": round(grams, 1)}
    return BuildResult(parts, w, meta, notes)


GENERATOR = Generator(
    key="keychain", label="Anahtarlık", group="Anahtarlık",
    description="İsim, hazır şekil ya da logo anahtarlık: renkli üst katman, kenar çizgisi, sol ya da üst halka, isteğe bağlı gizli NFC yuvası.",
    params=[
        Param("style", "Tür", "choice", "name", options=[("name", "İsim"), ("shape", "Şekil + isim"), ("logo", "Logo + isim")], section="Tasarım"),
        Param("text", "Yazı", "text", "Ayşe", section="Tasarım"),
        Param("font", "Yazı tipi", "font", "Righteous", section="Tasarım"),
        Param("shape", "Şekil", "choice", "heart", options=list(SHAPES_TR.items()), section="Tasarım", show_if={"style": "shape"}),
        Param("logo", "Logo dosyası", "file", "", section="Tasarım", show_if={"style": "logo"}, help="SVG, PNG ya da JPG"),
        Param("logo_colors", "Logo renk sayısı", "int", 2, min=1, max=3, section="Tasarım", show_if={"style": "logo"}),
        Param("width_mm", "Genişlik", "number", 55, min=20, max=120, step=1, unit="mm", section="Tasarım",
              help="İsimde yazının, şekilde şeklin, logoda logonun genişliği"),
        Param("text_pct", "Yazı genişliği", "int", 70, min=20, max=95, unit="%", section="Tasarım", show_if={"style": ["shape", "logo"]}),
        Param("border_mm", "Kenar payı", "number", 3, min=1.5, max=8, step=0.5, unit="mm", section="Tasarım"),
        Param("rim", "Kenar çizgisi", "bool", False, section="Tasarım", help="Kenarda yazı renginde ince çizgi"),
        Param("base_color", "Taban rengi", "color", "#1F6FB2", section="Renk ve kalınlık"),
        Param("text_color", "Yazı rengi", "color", "#FFFFFF", section="Renk ve kalınlık", help="Taban rengiyle aynıysa tek renk basılır"),
        Param("base_mm", "Taban kalınlığı", "number", 3, min=1.6, max=6, step=0.2, unit="mm", section="Renk ve kalınlık"),
        Param("relief_mm", "Kabartma", "number", 1.0, min=0.4, max=3, step=0.2, unit="mm", section="Renk ve kalınlık"),
        Param("ring", "Halka yeri", "choice", "left", options=[("left", "Sol"), ("top", "Üst")], section="Halka"),
        Param("hole_mm", "Halka deliği", "number", 5, min=3, max=8, step=0.5, unit="mm", section="Halka"),
        Param("nfc", "NFC yuvası", "bool", False, section="NFC", help="Tabanın içinde gizli yuva; baskı etiketi koymanız için durur"),
        Param("nfc_d", "Etiket çapı", "number", 25, min=10, max=35, step=0.5, unit="mm", section="NFC", show_if={"nfc": True}),
        Param("nfc_t", "Etiket kalınlığı", "number", 0.6, min=0.2, max=2, step=0.1, unit="mm", section="NFC", show_if={"nfc": True}),
        Param("count", "Adet", "int", 1, min=1, max=40, section="Baskı"),
    ],
    build=build,
)
