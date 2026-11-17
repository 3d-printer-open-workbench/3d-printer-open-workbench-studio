"""QR plaques: WiFi, Google review, WhatsApp, Instagram/TikTok, web link, phone, text. Rounded plate, dark QR modules
raised on a light plate (one filament change), title above / caption below, optional icon (WiFi waves, review stars),
mount: none, two screw holes, magnet pockets or a separate angled stand."""
from __future__ import annotations

import numpy as np
from shapely import affinity
from shapely.geometry import box
from shapely.ops import unary_union

from .. import core, estimate, flat, qr
from ..shapes import shape_polygon
from .base import BuildResult, Generator, Param, Part

PAD = 5.0  # plate edge to content
GAP = 3.0  # between title / QR / caption
STAND_ANGLE = 75.0  # plaque lean from horizontal in the stand
STAND_CLEAR = 0.3  # slot clearance per side

DEFAULT_TITLE = {"wifi": "WiFi", "review": "Bizi değerlendirin", "whatsapp": "WhatsApp", "instagram": "Instagram",
                 "tiktok": "TikTok", "url": "", "phone": "Bizi arayın", "text": ""}


def _icon(kind: str, centre, size: float, stroke: float):
    if kind == "wifi":
        return flat.waves(centre, size, stroke)
    if kind == "review":  # five stars in a row
        s = size * 0.9
        return unary_union([affinity.translate(shape_polygon("star", s), centre[0] + (i - 2) * s * 1.1, centre[1]) for i in range(5)])
    return None


def _line(s: str, font: str, height: float, max_w: float, warnings: list[str], what: str):
    """One text block ``height`` mm capitals (narrowed to ``max_w``), thin strokes thickened."""
    own: list[str] = []
    g = flat.text(s, font, own, height_mm=height)
    if g.bounds[2] - g.bounds[0] > max_w:
        own = []
        g = flat.text(s, font, own, width_mm=max_w)
    g = flat.thicken(g, own, what)
    warnings += [x for x in own if x not in warnings]
    return g


def build(v: dict) -> BuildResult:
    w: list[str] = []
    kind = v["kind"]
    data = qr.payload(kind, v)
    ecc = "h" if v["ecc"] == "h" else "m"
    W, t, r = v["width_mm"], v["base_mm"], v["relief_mm"]
    _, n = qr.modules_polygon(data, 1.0, ecc)
    module = (W - 2 * PAD) / (n + 2 * qr.QUIET_MODULES)  # the quiet zone is part of the QR block
    qsize = module * n
    modules, _ = qr.modules_polygon(data, qsize, ecc)
    if module < qr.MIN_MODULE_MM:
        w.append(f"QR karesi {module:.2f} mm: {qr.MIN_MODULE_MM} mm'nin altında telefon zor okur. Plaketi büyütün ya da daha kısa bir "
                 "içerik/bağlantı kullanın.")
    pc, bc = core.norm_hex(v["qr_color"]), core.norm_hex(v["base_color"])
    if flat.luminance(pc) > flat.luminance(bc) - 0.35:
        w.append("QR rengi tabandan yeterince koyu değil: koyu kareler açık zemin üstünde olmalı, yoksa birçok telefon okumaz.")
    tc = core.norm_hex(v["text_color"])
    title = v["title"] if v["title"] != "auto" else DEFAULT_TITLE.get(kind, "")
    caption = v["caption"]
    if v["caption"] == "auto":
        caption = {"wifi": f"Ağ: {v['ssid']}" + (f"\nŞifre: {v['password']}" if v["show_password"] and v["password"] else ""),
                   "instagram": "@" + v["user"].lstrip("@"), "tiktok": "@" + v["user"].lstrip("@"),
                   "whatsapp": v["phone"], "phone": v["phone"]}.get(kind, "")
    tw = W - 2 * PAD
    items: list[tuple[str, object]] = []  # top to bottom
    icon_h = v["title_mm"] * 1.15
    if v["icon"]:
        ic = _icon(kind, (0, 0), icon_h, max(1.2, icon_h * 0.13))
        if ic is not None:
            items.append(("icon", ic))
    if title.strip():
        items.append(("title", _line(title, v["font"], v["title_mm"], tw, w, "Başlık")))
    quiet = qr.QUIET_MODULES * module
    items.append(("qr", box(-qsize / 2 - quiet, -qsize / 2 - quiet, qsize / 2 + quiet, qsize / 2 + quiet)))
    if caption.strip():
        items.append(("caption", _line(caption, v["font"], v["caption_mm"], tw, w, "Alt yazı")))
    heights = [it[1].bounds[3] - it[1].bounds[1] for it in items]
    extra_bot = 8.0 if v["mount"] == "stand" else 0.0
    H = sum(heights) + GAP * (len(items) - 1) + 2 * PAD + extra_bot
    y = H / 2 - PAD
    top = []
    for (name, g), h in zip(items, heights):
        x0, y0, x1, y1 = g.bounds
        g = affinity.translate(g, -(x0 + x1) / 2, y - y1)
        if name == "qr":
            cy = (g.bounds[1] + g.bounds[3]) / 2
            top.append(("qr", "QR kod", affinity.translate(modules, 0, cy), pc))
        else:
            label = {"icon": "Simge", "title": "Başlık", "caption": "Alt yazı"}[name]
            top.append((name, label, g, tc))
        y -= h + GAP
    top.sort(key=lambda it: it[0] != "qr")  # merged same-colour part is named after the QR
    plate = box(-W / 2, -H / 2, W / 2, H / 2).buffer(-v["corner_mm"], quad_segs=12).buffer(v["corner_mm"], quad_segs=12)
    cuts = None
    notes = []
    mount = v["mount"]
    if mount == "holes":
        hx, hy = W / 2 - 4.5, H / 2 - 4.5
        cuts = unary_union([affinity.translate(box(-0.01, -0.01, 0.01, 0.01).buffer(2.0, quad_segs=16), sx * hx, hy) for sx in (-1, 1)])
        if any(g.intersects(cuts.buffer(1.0)) for _, _, g, _ in top):
            w.append("Vida delikleri yazıya/simgeye çok yakın; plaketi büyütün ya da başlığı küçültün.")
        notes.append("Montaj: üst köşelerde 2 × Ø4 mm delik (3–3.5 mm vida, dübel).")
    layers = [("plate", "Plaket", plate, 0.0, t, bc)] + [(n_, lb, g, t, t + r, c) for n_, lb, g, c in top]
    parts = flat.layer_parts(layers, "plaque", cuts=cuts)
    if mount == "magnet":
        mag = unary_union([affinity.translate(box(0, 0, 0, 0).buffer(v["magnet_d"] / 2 + 0.15, quad_segs=24), sx * W / 4, H / 4)
                           for sx in (-1, 1)])
        depth = min(v["magnet_t"] + 0.2, t - 0.8)
        base = parts[0]
        base.mesh = core.to_trimesh(core.from_trimesh(base.mesh) - core.extrude(mag, 0.0, depth))
        notes.append(f"Montaj: arkada 2 × Ø{v['magnet_d']:g}×{v['magnet_t']:g} mm mıknatıs yuvası; mıknatısları yapıştırın (tutkal/CA).")
    if mount == "stand":
        sm, L = flat.slot_stand(W, t, STAND_ANGLE, STAND_CLEAR)
        e = estimate.part_estimate(sm, "PLA", "flat")
        stand_col = core.norm_hex(v["stand_color"])
        plaque_parts = list(parts)
        parts.append(Part("stand", "Masa standı", _place_stand(sm, plate), stand_col, "PLA",
                          {"group": "stand", "batch": "stand", "grams": e.grams, "minutes": e.minutes, "cost_try": e.try_}))
        parts.extend(flat.stand_preview_parts(plaque_parts, sm, stand_col, plate.bounds[1], t, STAND_ANGLE))
        notes.append(f"Stand ayrı basılır; plaket yuvaya {STAND_ANGLE:.0f}° eğimle oturur (yuva {t + 2 * STAND_CLEAR:.1f} mm).")
    for p in parts:
        p.meta["count"] = v["count"]
    grams = sum(p.meta.get("grams", 0.0) for p in parts if p.printable)
    cost = sum(p.meta.get("cost_try", 0.0) for p in parts if p.printable)
    notes.insert(0, f"Plaket {W:.0f} × {H:.0f} × {t + r:.1f} mm, QR {qsize:.0f} mm ({n}×{n} kare, kare {module:.2f} mm), ~{grams:.0f} g ≈ {cost:.0f} TL / adet.")
    notes.append("QR içeriği: " + data)
    notes.append("Satmadan önce basılı plaketi birkaç farklı telefonla okutun.")
    if kind == "review":
        notes.append("Yorum bağlantısı: Google Business Profile → 'Yorum iste' bağlantısını kopyalayın ya da Place ID girin.")
    meta = {"qr_data": data, "qr_modules": n, "module_mm": round(module, 3), "size_mm": [W, round(H, 1), round(t + r, 1)]}
    return BuildResult(parts, w, meta, notes)


def _place_stand(mesh, plate):
    m = mesh.copy()
    x0, y0, _, _ = plate.bounds
    m.apply_translation([-m.bounds[0][0] + plate.bounds[0], y0 - 10 - m.bounds[1][1], -m.bounds[0][2]])
    return m


GENERATOR = Generator(
    key="qr_plaque", label="QR plaket", group="QR kod",
    description="WiFi, Google yorum, WhatsApp, Instagram/TikTok, web, telefon QR plaketi: başlık, alt yazı, simge; vida, mıknatıs ya da masa standı.",
    params=[
        Param("kind", "QR türü", "choice", "wifi", options=list(qr.KINDS.items()), section="İçerik"),
        Param("ssid", "Ağ adı (SSID)", "text", "Workbench", section="İçerik", show_if={"kind": "wifi"}),
        Param("password", "Şifre", "text", "", section="İçerik", show_if={"kind": "wifi"}),
        Param("security", "Güvenlik", "choice", "WPA", options=[("WPA", "WPA/WPA2/WPA3"), ("WEP", "WEP"), ("nopass", "Şifresiz")],
              section="İçerik", show_if={"kind": "wifi"}),
        Param("hidden", "Gizli ağ", "bool", False, section="İçerik", show_if={"kind": "wifi"}),
        Param("show_password", "Şifreyi plakete yaz", "bool", False, section="İçerik", show_if={"kind": "wifi"}),
        Param("link", "Bağlantı / Place ID", "text", "", section="İçerik", show_if={"kind": ["review", "url"]}),
        Param("phone", "Telefon", "text", "", section="İçerik", show_if={"kind": ["whatsapp", "phone"]}),
        Param("message", "Hazır mesaj", "text", "", section="İçerik", show_if={"kind": "whatsapp"}),
        Param("user", "Kullanıcı adı", "text", "", section="İçerik", show_if={"kind": ["instagram", "tiktok"]}),
        Param("text", "Metin", "text", "", section="İçerik", show_if={"kind": "text"}),
        Param("ecc", "Hata düzeltme", "choice", "m", options=[("m", "Orta (%15)"), ("h", "Yüksek (%30)")], section="İçerik",
              help="Yüksek: çizilmeye dayanıklı ama QR daha sık kareli"),
        Param("title", "Başlık", "text", "auto", section="Yazı", help="'auto' = türe göre (ör. WiFi); boş = yok"),
        Param("caption", "Alt yazı", "text", "auto", section="Yazı", help="'auto' = ağ adı / kullanıcı adı / numara; boş = yok"),
        Param("icon", "Simge", "bool", True, section="Yazı", help="WiFi dalgaları, yorumda 5 yıldız"),
        Param("font", "Yazı tipi", "font", "Righteous", section="Yazı"),
        Param("title_mm", "Başlık yüksekliği", "number", 7, min=4, max=20, step=0.5, unit="mm", section="Yazı"),
        Param("caption_mm", "Alt yazı yüksekliği", "number", 5, min=3, max=12, step=0.5, unit="mm", section="Yazı"),
        Param("width_mm", "Genişlik", "number", 90, min=50, max=200, step=1, unit="mm", section="Plaket"),
        Param("corner_mm", "Köşe yuvarlaklığı", "number", 6, min=0.5, max=20, step=0.5, unit="mm", section="Plaket"),
        Param("base_mm", "Kalınlık", "number", 2.6, min=2, max=6, step=0.2, unit="mm", section="Plaket"),
        Param("relief_mm", "Kabartma", "number", 0.8, min=0.4, max=2, step=0.2, unit="mm", section="Plaket"),
        Param("base_color", "Zemin rengi", "color", "#FFFFFF", section="Renk"),
        Param("qr_color", "QR rengi", "color", "#111111", section="Renk"),
        Param("text_color", "Yazı rengi", "color", "#111111", section="Renk", help="QR rengiyle aynıysa 2 renk yeter"),
        Param("mount", "Montaj", "choice", "stand", options=[("none", "Yok"), ("stand", "Masa standı"), ("holes", "Vida delikleri"),
                                                              ("magnet", "Mıknatıs yuvası")], section="Montaj"),
        Param("stand_color", "Stand rengi", "color", "#111111", section="Montaj", show_if={"mount": "stand"}),
        Param("magnet_d", "Mıknatıs çapı", "number", 10, min=5, max=20, step=0.5, unit="mm", section="Montaj", show_if={"mount": "magnet"}),
        Param("magnet_t", "Mıknatıs kalınlığı", "number", 2, min=1, max=4, step=0.5, unit="mm", section="Montaj", show_if={"mount": "magnet"}),
        Param("count", "Adet", "int", 1, min=1, max=20, section="Baskı"),
    ],
    build=build,
)
