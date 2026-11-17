"""Photo frame (photo slides into a pocket from the top, face-up print: the border over the pocket is a short 3 mm
overhang) with raised caption on the bottom border, standing in a desk stand; or a simple slot stand for a photo /
card with a raised name on top."""
from __future__ import annotations

from shapely import affinity
from shapely.geometry import box

from .. import core, estimate, flat
from .base import BuildResult, Generator, Param, Part

SIZES = {"10x15": (100.0, 150.0), "9x13": (89.0, 127.0), "13x18": (130.0, 180.0), "polaroid": (54.0, 86.0), "kart": (55.0, 85.0)}
BACK_T, POCKET_T, FRONT_T = 1.2, 0.8, 1.2
OVERLAP = 3.0  # border over the photo edge


def _part(name: str, label: str, mesh, color: str, **meta) -> Part:
    e = estimate.part_estimate(mesh, "PLA", "flat")
    return Part(name, label, mesh, color, "PLA", {"group": "stand", "grams": e.grams, "minutes": e.minutes, "cost_try": e.try_, **meta})


def build(v: dict) -> BuildResult:
    w: list[str] = []
    pw, ph = SIZES[v["size"]]
    if v["landscape"]:
        pw, ph = ph, pw
    bc, tc = core.norm_hex(v["color"]), core.norm_hex(v["text_color"])
    notes = []
    if v["kind"] == "frame":
        b = v["border_mm"]
        cap = v["caption"].strip()
        extra = v["caption_mm"] + 6 if cap else 0.0
        W, H = pw + 2 * b, ph + 2 * b + extra
        outer = box(-W / 2, -H / 2, W / 2, H / 2).buffer(-3, quad_segs=8).buffer(3, quad_segs=8)
        py0 = -H / 2 + b + extra
        pocket = box(-pw / 2 - 0.4, py0 - 0.4, pw / 2 + 0.4, H / 2 + 1)  # open at the top edge
        window = box(-pw / 2 + OVERLAP, py0 + OVERLAP, pw / 2 - OVERLAP, py0 + ph - OVERLAP)
        t = BACK_T + POCKET_T + FRONT_T
        back = outer.difference(window) if v["back"] == "open" else outer  # open back: ~half the filament
        layers = [("back", "Arka", back, 0.0, BACK_T, bc),
                  ("rim", "Çerçeve", outer.difference(pocket), BACK_T - 0.01, BACK_T + POCKET_T, bc),
                  ("front", "Ön çerçeve", outer.difference(window), BACK_T + POCKET_T - 0.01, t, bc)]
        if cap:
            g, _ = flat.fit_text(cap, v["font"], box(-W / 2 + b, -H / 2 + 3, W / 2 - b, py0 - 2), W * 0.7, w, "Alt yazı")
            layers.append(("caption", "Alt yazı", g, t, t + v["relief_mm"], tc))
        parts = flat.layer_parts(layers, "frame")
        frame_parts = list(parts)
        sm, _ = flat.slot_stand(W, t + (v["relief_mm"] if cap else 0), 78.0, 0.3, depth=30.0, height=12.0)
        stand_col = core.norm_hex(v["stand_color"])
        sm_placed = sm.copy()
        sm_placed.apply_translation([0, -H / 2 - 25 - sm_placed.bounds[1][1], 0])
        parts.append(_part("stand", "Masa standı", sm_placed, stand_col, batch="stand"))
        parts.extend(flat.stand_preview_parts(frame_parts, sm, stand_col, -H / 2, t + (v["relief_mm"] if cap else 0), 78.0))
        notes += [f"Çerçeve {W:.0f} × {H:.0f} mm, {pw:g} × {ph:g} mm fotoğraf için; fotoğrafı üst kenardaki aralıktan kaydırın.",
                  f"Ön çerçeve fotoğrafın {OVERLAP:g} mm üstüne biner (kısa çıkıntı, destek gerekmez). Stand ayrı basılır."]
    else:
        W = pw * 0.9
        sm, L = flat.slot_stand(W * 2, 1.0, 80.0, 0.25, depth=34.0, height=14.0)
        parts = [_part("stand", "Fotoğraf standı", sm, bc)]
        txt = v["caption"].strip()
        if txt:  # raised on the top, in front of the slot
            g, _ = flat.fit_text(txt, v["font"], box(-L / 2 + 2, -15, L / 2 - 2, -6), L * 0.9, w, "Yazı")
            top = sm.bounds[1][2]
            parts.append(_part("text", "Yazı", flat.slab(g, top - 0.01, top + v["relief_mm"]), tc))
        notes.append(f"Yuva 1.5 mm: fotoğraf, kartpostal ya da {v['size']} baskı dik durur (80°).")
    for p in parts:
        p.meta["count"] = v["count"]
    notes.insert(0, f"~{sum(p.meta.get('grams', 0.0) for p in parts if p.printable):.0f} g ≈ {sum(p.meta.get('cost_try', 0.0) for p in parts if p.printable):.0f} TL / adet.")
    return BuildResult(parts, w, {}, notes)


GENERATOR = Generator(
    key="photo_stand", label="Fotoğraf çerçevesi / standı", group="Hediyelik",
    description="Önden kaydırmalı fotoğraf çerçevesi (alt yazılı, masa standlı) ya da yazılı fotoğraf / kart standı.",
    params=[
        Param("kind", "Tür", "choice", "frame", options=[("frame", "Çerçeve"), ("stand", "Yuvalı stand")], section="Fotoğraf"),
        Param("size", "Fotoğraf boyu", "choice", "10x15", options=[("10x15", "10 × 15"), ("9x13", "9 × 13"), ("13x18", "13 × 18"),
                                                                   ("polaroid", "Polaroid (5.4 × 8.6)"), ("kart", "Kart")], section="Fotoğraf"),
        Param("landscape", "Yatay", "bool", False, section="Fotoğraf"),
        Param("border_mm", "Çerçeve kenarı", "number", 10, min=5, max=30, step=1, unit="mm", section="Fotoğraf", show_if={"kind": "frame"}),
        Param("back", "Arka yüz", "choice", "closed", options=[("closed", "Dolu"), ("open", "Açık (az filament)")], section="Fotoğraf",
              show_if={"kind": "frame"}, help="Açık: fotoğraf iki yandan 3 mm kenarla tutulur"),
        Param("caption", "Yazı", "text", "Sevgiyle", section="Yazı"),
        Param("font", "Yazı tipi", "font", "Pacifico", section="Yazı"),
        Param("caption_mm", "Yazı alanı", "number", 14, min=6, max=40, step=1, unit="mm", section="Yazı", show_if={"kind": "frame"}),
        Param("relief_mm", "Kabartma", "number", 0.8, min=0.4, max=2, step=0.2, unit="mm", section="Yazı"),
        Param("color", "Renk", "color", "#C9A27E", section="Renk"),
        Param("text_color", "Yazı rengi", "color", "#FFFFFF", section="Renk"),
        Param("stand_color", "Stand rengi", "color", "#C9A27E", section="Renk", show_if={"kind": "frame"}),
        Param("count", "Adet", "int", 1, min=1, max=4, section="Baskı"),
    ],
    build=build,
)
