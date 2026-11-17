#!/usr/bin/env python3
"""Regenerate fonts/metrics.json, fonts/REPORT.md, fonts/specimens/<id>.png and catalog.png."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import matplotlib
from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import Polygon

from kaligraf.fontinfo import SAMPLE, TURKISH, write_metrics
from kaligraf.fonts import DEFAULT_FONTS_DIR, load_registry, resolve_font
from kaligraf.text2d import build_text

CAT_TR = {"basic": "Temel", "print": "Matbaa / Düz yazı", "cursive": "El yazısı"}
DEJAVU = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
DEJAVU_B = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf"


def draw_geometry(draw: ImageDraw.ImageDraw, geom, box: tuple[int, int, int, int], fill=(20, 20, 20)) -> None:
    """Fit ``geom`` (mm, y up) into ``box`` (x0, y0, x1, y1) and fill it."""
    x0, y0, x1, y1 = box
    minx, miny, maxx, maxy = geom.bounds
    k = min((x1 - x0) / (maxx - minx), (y1 - y0) / (maxy - miny))
    ox = x0 + ((x1 - x0) - (maxx - minx) * k) / 2
    oy = y0 + ((y1 - y0) - (maxy - miny) * k) / 2

    def pt(x, y):
        return (ox + (x - minx) * k, oy + (maxy - y) * k)

    polys = list(getattr(geom, "geoms", [geom]))
    for p in polys:
        if not isinstance(p, Polygon) or p.is_empty:
            continue
        draw.polygon([pt(*c) for c in p.exterior.coords], fill=fill)
        for h in p.interiors:
            draw.polygon([pt(*c) for c in h.coords], fill=(255, 255, 255))


def specimen(font_id: str, fonts_dir: Path, size=(1000, 260)) -> Image.Image:
    rf = resolve_font(font_id, fonts_dir)
    g = build_text(SAMPLE, rf, "flat", width_mm=400.0).geometry
    img = Image.new("RGB", size, "white")
    draw_geometry(ImageDraw.Draw(img), g, (40, 30, size[0] - 40, size[1] - 30))
    return img


def main() -> None:
    fonts_dir = Path(DEFAULT_FONTS_DIR)
    spec_dir = fonts_dir / "specimens"
    spec_dir.mkdir(exist_ok=True)
    reg = load_registry(fonts_dir)
    metrics = write_metrics(fonts_dir)

    order = [s for c in CAT_TR for s in reg.values() if s.category == c]
    imgs = {}
    for s in order:
        imgs[s.id] = specimen(s.id, fonts_dir)
        imgs[s.id].save(spec_dir / f"{s.id}.png")

    # report
    lines = [
        "# Yazı Tipi Raporu", "",
        f"Örnek metin: **{SAMPLE}** (en küçük boyut hesabı ve örnek görseller bu metinle). Türkçe karakter kontrolü ayrı bir sütundur: `{TURKISH}`.", "",
        "En küçük boyut: ince çizgi kontrolünün (A modu 2 mm, B modu 3 mm) örnek metinde geçtiği en küçük "
        "büyük harf (cap) yüksekliği, cm (0,5 cm adımla yukarı yuvarlanır). Metin uzunluğundan bağımsızdır; "
        "düz tabelada genişlik, metne göre bu yüksekliğe çevrilerek karşılaştırılır. `yok` = 40 cm'ye kadar bile geçmiyor.", "",
    ]
    n = 0
    for c, title in CAT_TR.items():
        lines += [f"## {title}", "", "| No | Yazı tipi | Lisans | Türkçe | Eksik | En küçük harf yüksekliği, düz tabela (A) | En küçük harf yüksekliği, 3D harf (B) |",
                  "|---|---|---|---|---|---|---|"]
        for s in [s for s in reg.values() if s.category == c]:
            n += 1
            m = metrics[s.id]
            f = lambda v: "yok" if v is None else f"{v:g} cm"
            lines.append(f"| {n} | {s.name} | {s.license.upper()} | {'tam' if m['turkish_ok'] else 'eksik'} | "
                         f"{' '.join(m['turkish_missing']) or '-'} | {f(m['min_cap_flat_cm'])} | {f(m['min_cap_letters_cm'])} |")
        lines.append("")
    (fonts_dir / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")

    # catalog sheet: numbered grid, 2 columns
    cols, cw, ch, pad, head = 2, 1000, 300, 30, 150
    rows = (len(order) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cw + (cols + 1) * pad, head + rows * (ch + pad) + pad), "white")
    d = ImageDraw.Draw(sheet)
    d.text((pad, 40), "Yazı Tipini Seçin", font=ImageFont.truetype(str(DEJAVU_B), 64), fill=(20, 20, 20))
    d.text((pad, 115), f"Örnek: {SAMPLE}", font=ImageFont.truetype(str(DEJAVU), 26), fill=(90, 90, 90))
    lab = ImageFont.truetype(str(DEJAVU_B), 30)
    for i, s in enumerate(order):
        r, c = divmod(i, cols)
        x, y = pad + c * (cw + pad), head + r * (ch + pad)
        d.rectangle([x, y, x + cw, y + ch], outline=(200, 200, 200), width=2)
        sheet.paste(imgs[s.id].resize((cw - 20, int((cw - 20) * 260 / 1000))), (x + 10, y + 6))
        d.text((x + 16, y + ch - 44), f"{i + 1}. {s.name}", font=lab, fill=(20, 20, 20))
    sheet.save(spec_dir / "catalog.png")
    print(f"{len(order)} fonts, report and specimens written to {fonts_dir}")


if __name__ == "__main__":
    main()
