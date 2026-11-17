"""PDF outputs: the 1:1 sheet template (tiled on A4) and the Turkish assembly guide (reportlab, DejaVu for Turkish)."""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Image, ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from shapely.geometry import Polygon

from .generators import BuildResult, SheetLayout

MARGIN = 10.0  # unprintable page margin (mm)
FOOT = 24.0  # bottom strip for page label + scale bar (mm)
OVERLAP = 10.0  # shared strip between neighbouring tiles (mm)
PAD = 8.0  # paper around the blank (mm)
FONT, BOLD = "DejaVuSans", "DejaVuSans-Bold"


def fonts() -> tuple[str, str]:
    try:
        import matplotlib

        d = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        for name, f in ((FONT, "DejaVuSans.ttf"), (BOLD, "DejaVuSans-Bold.ttf")):
            if name not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(name, str(d / f)))
        return FONT, BOLD
    except Exception:  # pragma: no cover - Helvetica has no Turkish glyphs, but the PDF still works
        return "Helvetica", "Helvetica-Bold"


# --------------------------------------------------------------------------- sheet template
def _tiles(w: float, h: float, pw: float, ph: float) -> tuple[list[float], list[float]]:
    """Tile origins along x and y so (w, h) is covered by (pw, ph) windows overlapping by OVERLAP."""
    def axis(total, win):
        n = 1 if total <= win else math.ceil((total - OVERLAP) / (win - OVERLAP))
        return [i * (win - OVERLAP) for i in range(n)]
    return axis(w, pw), axis(h, ph)


def _rings(g) -> list:
    polys = [g] if isinstance(g, Polygon) else list(getattr(g, "geoms", []))
    return [r for p in polys for r in [p.exterior, *p.interiors]]


def write_sheet_pdf(layout: SheetLayout, path: Path | str) -> dict:
    """1:1 template: blank rectangle (cut line), dome footprints (dashed) and trim lines, tiled on A4 when needed."""
    font, bold = fonts()
    sw, sh = layout.size_mm
    W, H = sw + 2 * PAD, sh + 2 * PAD  # drawing in template coords: blank lower-left at (PAD, PAD)
    ox, oy = PAD + sw / 2, PAD + sh / 2  # layout origin (sheet centre) in template coords
    best = None
    for pw_, ph_ in (A4, A4[::-1]):
        pw, ph = pw_ / mm, ph_ / mm
        xs, ys = _tiles(W, H, pw - 2 * MARGIN, ph - 2 * MARGIN - FOOT)
        if best is None or len(xs) * len(ys) < best[0]:
            best = (len(xs) * len(ys), (pw_, ph_), xs, ys)
    _, page, xs, ys = best
    pw, ph = page[0] / mm, page[1] / mm
    win_w, win_h = pw - 2 * MARGIN, ph - 2 * MARGIN - FOOT
    c = canvas.Canvas(str(path), pagesize=page)
    c.setTitle(layout.title or "Levha şablonu")
    n = len(xs) * len(ys)
    k = 0
    for j, ty in enumerate(reversed(ys)):  # top row first
        for i, tx in enumerate(xs):
            k += 1
            c.saveState()
            p = c.beginPath()
            p.rect(MARGIN * mm, (MARGIN + FOOT) * mm, win_w * mm, win_h * mm)
            c.clipPath(p, stroke=0)
            c.translate((MARGIN - tx) * mm, (MARGIN + FOOT - ty) * mm)
            # blank (cut line)
            c.setStrokeColor(colors.black)
            c.setLineWidth(0.6)
            c.setDash()
            c.rect(PAD * mm, PAD * mm, sw * mm, sh * mm)
            for cx, cy in ((PAD, PAD), (PAD + sw, PAD), (PAD, PAD + sh), (PAD + sw, PAD + sh)):  # crop marks
                c.line((cx - 5) * mm, cy * mm, (cx + 5) * mm, cy * mm)
                c.line(cx * mm, (cy - 5) * mm, cx * mm, (cy + 5) * mm)
            # dome footprints (dashed) and trim lines (solid red)
            for geoms, col, dash, lw in ((layout.shapes, colors.grey, (3, 2), 0.4), (layout.trims, colors.red, None, 0.6)):
                c.setStrokeColor(col)
                c.setLineWidth(lw)
                c.setDash(*dash) if dash else c.setDash()
                for g in geoms:
                    for ring in _rings(g):
                        pts = list(ring.coords)
                        path_ = c.beginPath()
                        path_.moveTo((pts[0][0] + ox) * mm, (pts[0][1] + oy) * mm)
                        for x, y in pts[1:]:
                            path_.lineTo((x + ox) * mm, (y + oy) * mm)
                        path_.close()
                        c.drawPath(path_, stroke=1, fill=0)
            c.setDash()
            c.setFillColor(colors.black)
            c.setFont(font, 7)
            c.drawString((PAD + 2) * mm, (PAD + sh + 1.5) * mm, f"Levha kesim çizgisi {sw:.0f} × {sh:.0f} mm")
            c.restoreState()
            # page frame: overlap guides + alignment crosses at the window corners
            c.setStrokeColor(colors.lightgrey)
            c.setLineWidth(0.3)
            c.rect(MARGIN * mm, (MARGIN + FOOT) * mm, win_w * mm, win_h * mm)
            if n > 1:
                c.setDash(1, 2)
                if i > 0:
                    c.line((MARGIN + OVERLAP) * mm, (MARGIN + FOOT) * mm, (MARGIN + OVERLAP) * mm, (ph - MARGIN) * mm)
                if j < len(ys) - 1:
                    c.line(MARGIN * mm, (MARGIN + FOOT + OVERLAP) * mm, (pw - MARGIN) * mm, (MARGIN + FOOT + OVERLAP) * mm)
                c.setDash()
            # footer: label, scale bar, legend
            c.setFillColor(colors.black)
            c.setFont(bold, 8)
            label = f"{layout.title}  —  sayfa {k}/{n}" + (f" (satır {j + 1}, sütun {i + 1})" if n > 1 else "")
            c.drawString(MARGIN * mm, (MARGIN + FOOT - 5) * mm, label)
            c.setFont(font, 6.5)
            legend = ["%100 ölçekte yazdırın (sayfaya sığdır KAPALI).",
                      "Siyah: levha kesimi · Kırmızı: biçimlendirmeden sonra kesim · Kesikli gri: kubbe"
                      + (" · Noktalı: 10 mm bindirme payı (sayfaları buradan üst üste yapıştırın)" if n > 1 else "")]
            for li, line in enumerate(legend + layout.lines):
                c.drawString(MARGIN * mm, (MARGIN + FOOT - 9 - 3.2 * li) * mm, line)
            bx, by = pw - MARGIN - 52, MARGIN + FOOT - 7
            c.setLineWidth(0.6)
            c.setStrokeColor(colors.black)
            c.line(bx * mm, by * mm, (bx + 50) * mm, by * mm)
            for t in range(0, 51, 10):
                c.line((bx + t) * mm, by * mm, (bx + t) * mm, (by + (2.5 if t % 50 == 0 else 1.5)) * mm)
            c.drawString(bx * mm, (by + 3) * mm, "50 mm — cetvelle kontrol edin")
            c.showPage()
    c.save()
    return {"pages": n, "page": "A4" if page == A4 else "A4 yatay", "size_mm": [round(sw), round(sh)]}


# --------------------------------------------------------------------------- assembly guide
def write_assembly_pdf(res: BuildResult, data: dict, path: Path | str, render: Path | None = None,
                       title: str = "", plates: list[dict] | None = None) -> Path:
    font, bold = fonts()
    st = {
        "h1": ParagraphStyle("h1", fontName=bold, fontSize=17, leading=21, spaceAfter=4),
        "h2": ParagraphStyle("h2", fontName=bold, fontSize=12, leading=15, spaceBefore=10, spaceAfter=4),
        "p": ParagraphStyle("p", fontName=font, fontSize=9, leading=12.5),
        "s": ParagraphStyle("s", fontName=font, fontSize=7.5, leading=10, textColor=colors.grey),
        "w": ParagraphStyle("w", fontName=font, fontSize=9, leading=12.5, textColor=colors.HexColor("#9A3412")),
    }
    esc = lambda s: str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm,
                            bottomMargin=14 * mm, title=title or data.get("name", ""), author="Workbench - Maker")
    flow = [Paragraph(esc(title or data.get("name", "")), st["h1"]),
            Paragraph(f"Workbench - Maker · {esc(data.get('generator', ''))} · {date.today():%d.%m.%Y}", st["s"]), Spacer(1, 4 * mm)]
    if render and Path(render).is_file():
        from PIL import Image as PILImage

        with PILImage.open(render) as im:
            w, h = im.size
        iw = 120 * mm
        flow.append(Image(str(render), width=iw, height=iw * h / w))
    flow.append(Paragraph("Parçalar", st["h2"]))
    rows = [["Parça", "Malzeme", "Adet", "Ölçü (mm)", "Filament", "Süre", "Tutar"]]
    tot_g, tot_min, tot_try = 0.0, 0.0, 0.0
    for p in res.parts:
        n = int(p.meta.get("count", 1) or 1)
        x, y, z = p.mesh.extents
        if not p.printable:
            rows.append([Paragraph(esc(p.label), st["p"]), p.material, "", f"{x:.0f}×{y:.0f}×{z:.0f}", "basılmaz", "", ""])
            continue
        g, m, t = p.meta.get("grams"), p.meta.get("minutes"), p.meta.get("cost_try")
        if g is not None:
            tot_g += g * n
            tot_min += (m or 0) * n
            tot_try += (t or 0) * n
        rows.append([Paragraph(esc(p.label), st["p"]), p.material, str(n), f"{x:.0f}×{y:.0f}×{z:.0f}",
                     f"{g:.0f} g" if g is not None else "", f"{m / 60:.1f} sa" if m else "", f"{t:.1f} TL" if t is not None else ""])
    if tot_g:
        rows.append(["Toplam", "", "", "", f"{tot_g:.0f} g", f"{tot_min / 60:.1f} sa", f"{tot_try:.0f} TL"])
    tbl = Table(rows, colWidths=[52 * mm, 18 * mm, 11 * mm, 27 * mm, 20 * mm, 16 * mm, 20 * mm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), font, 8.5), ("FONT", (0, 0), (-1, 0), bold, 8.5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black), ("LINEABOVE", (0, -1), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F4")]),
    ]))
    flow.append(tbl)
    flow.append(Paragraph("Süre ve gram kaba tahmindir (±%30); dilimlenmiş G-code varsa aşağıdaki baskı tablaları bölümüne bakın. "
                          "Fiyatlar costs.yaml'daki varsayımlardır.", st["s"]))
    if plates:
        flow.append(Paragraph("Baskı tablaları (model.3mf)", st["h2"]))
        prow = [["Tabla", "Malzeme", "Parçalar", "Filament", "Süre"]]
        for i, pl in enumerate(plates, 1):
            prow.append([str(i), pl["material"], Paragraph(esc(", ".join(pl["objects"])), st["p"]),
                         f"{pl['grams']:.0f} g" if pl.get("grams") is not None else "—", pl.get("time", "—")])
        pt = Table(prow, colWidths=[14 * mm, 18 * mm, 92 * mm, 20 * mm, 22 * mm], repeatRows=1)
        pt.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), font, 8.5), ("FONT", (0, 0), (-1, 0), bold, 8.5),
                                ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        flow.append(pt)
    flow += [PageBreak(), Paragraph("Yapım adımları", st["h2"])]
    if res.notes:
        flow.append(ListFlowable([ListItem(Paragraph(esc(s), st["p"]), leftIndent=12) for s in res.notes],
                                 bulletType="1", bulletFontName=font, bulletFontSize=9, leftIndent=14))
    if res.warnings:
        flow.append(Paragraph("Uyarılar", st["h2"]))
        flow += [Paragraph("• " + esc(w), st["w"]) for w in res.warnings]
    if data.get("params"):
        flow.append(Paragraph("Ayarlar", st["h2"]))
        flow.append(Paragraph(esc(", ".join(f"{k}={v}" for k, v in data["params"].items() if v not in ("", None))), st["s"]))
    doc.build(flow)
    return Path(path)
