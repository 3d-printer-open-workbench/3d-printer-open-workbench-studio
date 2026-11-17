#!/usr/bin/env python3
"""Per-category catalog images for the store: 2000x2000 and 1080x1350 (4:5), numbers match catalog.png.

Writes fonts/specimens/catalog_{1_temel,2_print,3_el_yazisi}{,_4x5}.png
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image, ImageDraw, ImageFont

from font_report import CAT_TR, DEJAVU, DEJAVU_B, draw_geometry
from kaligraf.fontinfo import SAMPLE
from kaligraf.fonts import DEFAULT_FONTS_DIR, load_registry, resolve_font
from kaligraf.text2d import build_text

PAGES = [
    ("catalog_1_temel", "basic", "Temel Yazı Tipleri"),
    ("catalog_2_print", "print", "Düz Yazı Tipleri"),
    ("catalog_3_el_yazisi", "cursive", "El Yazısı Yazı Tipleri"),
]
INK = (20, 20, 20)


def _sample(font_id: str, fonts_dir: Path):
    rf = resolve_font(font_id, fonts_dir)
    r = build_text(SAMPLE, rf, "flat", width_mm=400.0)
    return r.geometry, r.cap_height_mm


def render_page(items, numbers, title, size, fonts_dir, cols=2):
    """items: font specs; returns (image, [cap height px per font])."""
    W, H = size
    u = W / 2000.0
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    mx = int(70 * u)
    d.text((mx, int(50 * u)), title, font=ImageFont.truetype(str(DEJAVU_B), int(88 * u)), fill=INK)
    d.text((mx, int(160 * u)), "Portalin", font=ImageFont.truetype(str(DEJAVU), int(40 * u)), fill=(110, 110, 110))
    d.line([(mx, int(225 * u)), (W - mx, int(225 * u))], fill=(210, 210, 210), width=max(1, int(3 * u)))
    foot_h = int(80 * u)
    d.text((W // 2, H - int(45 * u)), "Numarayı sipariş notuna yazın", font=ImageFont.truetype(str(DEJAVU_B), int(44 * u)),
           fill=INK, anchor="mm")
    top, bottom = int(250 * u), H - foot_h - int(10 * u)
    rows = -(-len(items) // cols)
    gap = int(18 * u)
    cw = (W - 2 * mx - (cols - 1) * gap) // cols
    ch = (bottom - top - (rows - 1) * gap) // rows
    name_font = ImageFont.truetype(str(DEJAVU_B), max(12, int(min(34 * u, ch * 0.2))))
    caps = []
    for i, (spec, num) in enumerate(zip(items, numbers)):
        r, c = divmod(i, cols)
        x, y = mx + c * (cw + gap), top + r * (ch + gap)
        d.rectangle([x, y, x + cw, y + ch], outline=(200, 200, 200), width=max(1, int(2 * u)))
        strip = int(max(name_font.size * 1.5, 30 * u))
        geom, cap_mm = _sample(spec.id, fonts_dir)
        pad = int(26 * u)
        box = (x + pad, y + int(10 * u), x + cw - pad, y + ch - strip)
        minx, miny, maxx, maxy = geom.bounds
        k = min((box[2] - box[0]) / (maxx - minx), (box[3] - box[1]) / (maxy - miny))
        caps.append(cap_mm * k)
        draw_geometry(d, geom, box, fill=INK)
        # number badge + name under the sample
        rad = strip // 2 - 2
        cx, cy = x + pad + rad, y + ch - strip // 2 - 2
        d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=INK)
        d.text((cx, cy), str(num), font=ImageFont.truetype(str(DEJAVU_B), int(rad * 1.1)), fill="white", anchor="mm")
        d.text((cx + rad + int(14 * u), cy), spec.name, font=name_font, fill=INK, anchor="lm")
    return img, caps


def main(out_dir: Path | None = None) -> dict:
    fonts_dir = Path(DEFAULT_FONTS_DIR)
    out = out_dir or fonts_dir / "specimens"
    reg = load_registry(fonts_dir)
    order = [s for c in CAT_TR for s in reg.values() if s.category == c]
    number = {s.id: i + 1 for i, s in enumerate(order)}
    report = {}
    for name, cat, title in PAGES:
        items = [s for s in order if s.category == cat]
        nums = [number[s.id] for s in items]
        for suffix, size in (("", (2000, 2000)), ("_4x5", (1080, 1350))):
            img, caps = render_page(items, nums, title, size, fonts_dir)
            img.save(out / f"{name}{suffix}.png")
            report[name + suffix] = (min(caps) / size[0], len(items))
    return report


if __name__ == "__main__":
    for k, (frac, n) in main().items():
        print(f"{k}: {n} fonts, min cap height {frac * 100:.1f}% of width")
