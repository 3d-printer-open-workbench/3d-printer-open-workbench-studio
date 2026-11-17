"""1:1 wall mounting template (PDF), tiled on A4 with overlap and alignment marks.

Everything is drawn in wall coordinates (mm, x right, y up, origin at the lower-left of the
sign's bounding box). Marks: part outlines, centre line and level line, keyholes, holes,
detached accent/dot positions, connector rail and (Mode A) bed-split cut lines.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from shapely.geometry import MultiPolygon, Polygon
from shapely.ops import unary_union

from .geometry import Model, mesh_footprint

MARGIN = 10.0  # unprintable page margin (mm)
OVERLAP = 12.0  # shared strip between neighbouring tiles (mm)
PAD = 20.0  # room around the sign for level / centre marks (mm)
FONT = "DejaVuSans"


def _register_font() -> str:
    try:
        import matplotlib

        ttf = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans.ttf"
        if FONT not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(FONT, str(ttf)))
        return FONT
    except Exception:  # pragma: no cover - falls back to Helvetica (no Turkish glyphs)
        return "Helvetica"


def _polys(g) -> list[Polygon]:
    if g.is_empty:
        return []
    return [g] if isinstance(g, Polygon) else [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]


def sign_footprints(model: Model) -> tuple[list[tuple[str, object]], tuple[float, float]]:
    """(part name, footprint) for every visible part and the lower-left corner of the sign."""
    foots = []
    for p in model.parts:
        if p.role in ("rail", "boss"):
            continue
        foots.append((p.name, mesh_footprint(p.mesh_wall)))
    allg = unary_union([f for _, f in foots])
    minx, miny, _, _ = allg.bounds
    return foots, (minx, miny)


def template_geometry(model: Model, split_cuts: dict | None = None) -> dict:
    """Everything the template draws, in template coordinates (sign lower-left at (PAD, PAD))."""
    foots, (ox, oy) = sign_footprints(model)
    sx, sy = PAD - ox, PAD - oy

    def sh(x, y):
        return (x + sx, y + sy)

    outline = unary_union([f for _, f in foots]).simplify(0.05)
    minx, miny, maxx, maxy = outline.bounds
    info = model.meta.get("mounting", {})
    marks: dict = {
        "outline": [(_translate(p, sx, sy)) for p in _polys(outline)],
        "bounds": (minx + sx, miny + sy, maxx + sx, maxy + sy),
        "keyholes": [], "holes": [], "detached": [], "rail": None, "cuts": [], "boss": [],
    }
    for k in info.get("keyholes", []):
        marks["keyholes"].append(sh(k["x"], k["y"]))
        if k.get("boss"):
            bx, by, bd = k["boss"]
            marks["boss"].append((*sh(bx, by), bd))
    for h in info.get("holes", []):
        marks["holes"].append((*sh(h["x"], h["y"]), h.get("diameter", 3.0)))
    for p in model.parts:
        for d in p.meta.get("detached_pieces", []):
            x0, y0, x1, y1 = d["bounds"]
            a, b = sh(x0, y0)
            c, e = sh(x1, y1)
            marks["detached"].append((a, b, c, e))
    r = info.get("rail")
    if r:
        x0, x1 = sh(r["x_min"], 0)[0], sh(r["x_max"], 0)[0]
        yc = sh(0, r["y_center"])[1]
        marks["rail"] = (x0, yc - r["width"] / 2, x1, yc + r["width"] / 2, [sh(c, 0)[0] for c in r.get("cuts", []) if isinstance(c, (int, float))])
    parts_by_group: dict[str, list] = {}
    for p in model.parts:
        parts_by_group.setdefault(p.group or p.name, []).append(p)
    for gname, cuts in (split_cuts or {}).items():
        gb = unary_union([mesh_footprint(p.mesh_wall) for p in parts_by_group.get(gname, [])]).bounds
        for x in cuts.get("x", []):
            marks["cuts"].append(("x", x + sx, gb[1] + sy, gb[3] + sy))
        for y in cuts.get("y", []):
            marks["cuts"].append(("y", y + sy, gb[0] + sx, gb[2] + sx))
    marks["size"] = (maxx - minx + 2 * PAD, maxy - miny + 2 * PAD)
    return marks


def _translate(p: Polygon, dx: float, dy: float) -> Polygon:
    from shapely import affinity

    return affinity.translate(p, dx, dy)


def _draw_poly(c: canvas.Canvas, p: Polygon, **kw) -> None:
    path = c.beginPath()
    for ring in [p.exterior, *p.interiors]:
        pts = list(ring.coords)
        path.moveTo(pts[0][0] * mm, pts[0][1] * mm)
        for x, y in pts[1:]:
            path.lineTo(x * mm, y * mm)
        path.close()
    c.drawPath(path, **kw)


def _draw_marks(c: canvas.Canvas, m: dict, font: str) -> None:
    """Draw the template content at 1:1 (canvas already translated so 1 unit = 1 mm via mm scale)."""
    x0, y0, x1, y1 = m["bounds"]
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    # outlines
    c.setLineWidth(0.6)
    c.setStrokeColorRGB(0, 0, 0)
    c.setFillColorRGB(0.93, 0.93, 0.93)
    for p in m["outline"]:
        _draw_poly(c, p, stroke=1, fill=1, fillMode=0)
    # centre line (vertical) and level line (horizontal through the mounting point, else the centre)
    c.setStrokeColorRGB(0.1, 0.3, 0.75)
    c.setLineWidth(0.5)
    c.setDash(6, 3)
    ymark = m["keyholes"][0][1] if m["keyholes"] else (m["holes"][0][1] if m["holes"] else cy)
    ext = 14
    c.line(cx * mm, (y0 - ext) * mm, cx * mm, (y1 + ext) * mm)
    c.line((x0 - ext) * mm, ymark * mm, (x1 + ext) * mm, ymark * mm)
    c.setDash()
    c.setFont(font, 7)
    c.setFillColorRGB(0.1, 0.3, 0.75)
    c.drawString((cx + 1.5) * mm, (y1 + ext - 4) * mm, "ORTA ÇİZGİ")
    c.drawString((x0 - ext + 1) * mm, (ymark + 1.5) * mm, "SEVİYE ÇİZGİSİ (su terazisi)")
    # detached accents / dots
    c.setStrokeColorRGB(0.8, 0.4, 0.0)
    c.setLineWidth(0.4)
    c.setDash(1.5, 1.5)
    for a, b, d, e in m["detached"]:
        c.rect((a - 1) * mm, (b - 1) * mm, (d - a + 2) * mm, (e - b + 2) * mm, stroke=1, fill=0)
    c.setDash()
    if m["detached"]:
        a, b, d, e = m["detached"][0]
        c.setFillColorRGB(0.8, 0.4, 0.0)
        c.setFont(font, 6)
        c.drawString((a - 1) * mm, (e + 2.5) * mm, "ayrı nokta/aksan")
    # rail
    if m["rail"]:
        rx0, ry0, rx1, ry1, _ = m["rail"]
        c.setStrokeColorRGB(0.4, 0.4, 0.4)
        c.setDash(4, 2)
        c.rect(rx0 * mm, ry0 * mm, (rx1 - rx0) * mm, (ry1 - ry0) * mm, stroke=1, fill=0)
        c.setDash()
        c.setFont(font, 6)
        c.setFillColorRGB(0.3, 0.3, 0.3)
        c.drawString((rx0 + 1) * mm, (ry1 + 1) * mm, "bağlantı çubuğu (arkada)")
    # boss
    for bx, by, bd in m["boss"]:
        c.setStrokeColorRGB(0.4, 0.4, 0.4)
        c.setDash(2, 2)
        c.circle(bx * mm, by * mm, bd / 2 * mm, stroke=1, fill=0)
        c.setDash()
    # keyholes
    c.setStrokeColorRGB(0.85, 0.1, 0.1)
    c.setLineWidth(0.5)
    for x, y in m["keyholes"]:
        c.circle(x * mm, y * mm, 4 * mm, stroke=1, fill=0)  # head Ø8
        c.line((x - 7) * mm, y * mm, (x + 7) * mm, y * mm)
        c.line(x * mm, (y - 7) * mm, x * mm, (y + 7) * mm)
        c.setFont(font, 6)
        c.setFillColorRGB(0.85, 0.1, 0.1)
        c.drawString((x + 5) * mm, (y + 5) * mm, "ANAHTAR DELİĞİ: vida/çivi merkezi")
    for x, y, d in m["holes"]:
        c.circle(x * mm, y * mm, d / 2 * mm, stroke=1, fill=0)
        c.line((x - 5) * mm, y * mm, (x + 5) * mm, y * mm)
        c.line(x * mm, (y - 5) * mm, x * mm, (y + 5) * mm)
        c.setFont(font, 6)
        c.setFillColorRGB(0.85, 0.1, 0.1)
        c.drawString((x + 4) * mm, (y + 4) * mm, f"delik Ø{d:g}")
    # split cut lines
    c.setStrokeColorRGB(0.0, 0.55, 0.2)
    c.setLineWidth(0.7)
    c.setDash(8, 3)
    c.setFont(font, 6)
    for axis, pos, a, b in m["cuts"]:
        if axis == "x":
            c.line(pos * mm, (a - 4) * mm, pos * mm, (b + 4) * mm)
            c.setFillColorRGB(0.0, 0.55, 0.2)
            c.drawString((pos + 1) * mm, (b + 4.5) * mm, "KESİM / BİRLEŞİM")
        else:
            c.line((a - 4) * mm, pos * mm, (b + 4) * mm, pos * mm)
            c.setFillColorRGB(0.0, 0.55, 0.2)
            c.drawString((a - 3) * mm, (pos + 1.5) * mm, "KESİM / BİRLEŞİM")
    c.setDash()


def _tiles(w: float, h: float, pw: float, ph: float) -> tuple[list[float], list[float]]:
    step_x, step_y = pw - OVERLAP, ph - OVERLAP
    nx = max(1, math.ceil((w - OVERLAP) / step_x))
    ny = max(1, math.ceil((h - OVERLAP) / step_y))
    return [i * step_x for i in range(nx)], [j * step_y for j in range(ny)]


def write_template_pdf(model: Model, out_path: str | Path, split_cuts: dict | None = None, title: str = "") -> dict:
    """Write ``template.pdf``; returns {"pages", "tiles": (nx, ny), "orientation"}."""
    marks = template_geometry(model, split_cuts)
    W, H = marks["size"]
    font = _register_font()
    best = None
    for orient, (pw_pt, ph_pt) in (("portrait", A4), ("landscape", (A4[1], A4[0]))):
        pw, ph = pw_pt / mm - 2 * MARGIN, ph_pt / mm - 2 * MARGIN
        xs, ys = _tiles(W, H, pw, ph)
        key = len(xs) * len(ys)
        if best is None or key < best[0]:
            best = (key, orient, pw_pt, ph_pt, pw, ph, xs, ys)
    _, orient, pw_pt, ph_pt, pw, ph, xs, ys = best
    c = canvas.Canvas(str(out_path), pagesize=(pw_pt, ph_pt))
    c.setTitle(f"Duvar şablonu {title}".strip())
    n_pages = len(xs) * len(ys)

    # overview page (scaled), with the tile grid
    c.setFont(font, 12)
    c.drawString(MARGIN * mm, ph_pt - 14 * mm, f"Duvar şablonu {title}".strip())
    c.setFont(font, 8)
    c.drawString(MARGIN * mm, ph_pt - 20 * mm,
                 f"Genel görünüm (ölçekli, 1:1 DEĞİL). Sayfa sayısı: {n_pages}. Yazdırırken ölçek %100 / 'gerçek boyut' seçin, 'sayfaya sığdır' kapalı olsun.")
    gw, gh = max(W, xs[-1] + pw), max(H, ys[-1] + ph)
    k = min((pw_pt - 2 * MARGIN * mm) / (gw * mm), (ph_pt - 40 * mm) / (gh * mm), 1.0)
    c.saveState()
    c.translate(MARGIN * mm, 18 * mm)
    c.scale(k, k)
    _draw_marks(c, marks, font)
    c.setStrokeColorRGB(0.5, 0.5, 0.5)
    c.setLineWidth(0.3 / k)
    for j, y in enumerate(ys):
        for i, x in enumerate(xs):
            c.rect(x * mm, y * mm, pw * mm, ph * mm, stroke=1, fill=0)
            c.setFont(font, 14 / k)
            c.setFillColorRGB(0.5, 0.5, 0.5)
            c.drawString((x + 3) * mm, (y + ph - 8) * mm, f"{len(ys) - j}-{i + 1}")
    c.restoreState()
    c.showPage()

    # 1:1 tiles, top row first
    for jr, j in enumerate(range(len(ys) - 1, -1, -1)):
        for i, x in enumerate(xs):
            y = ys[j]
            c.saveState()
            c.translate(MARGIN * mm, MARGIN * mm)
            p = c.beginPath()
            p.rect(0, 0, pw * mm, ph * mm)
            c.clipPath(p, stroke=0, fill=0)
            c.translate(-x * mm, -y * mm)
            _draw_marks(c, marks, font)
            c.restoreState()
            _tile_frame(c, font, i, j, len(xs), len(ys), pw, ph, pw_pt, ph_pt)
            c.showPage()
    c.save()
    return {"pages": n_pages + 1, "tiles": (len(xs), len(ys)), "orientation": orient, "size_mm": (W, H)}


def _tile_frame(c, font, i, j, nx, ny, pw, ph, pw_pt, ph_pt) -> None:
    """Page frame: alignment crosses in the overlap corners, labels, 50 mm scale check."""
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.4)
    ox, oy = MARGIN * mm, MARGIN * mm
    c.rect(ox, oy, pw * mm, ph * mm, stroke=1, fill=0)
    # crosses at the four inner corners of the overlap strips
    for cx in (OVERLAP, pw - OVERLAP):
        for cy in (OVERLAP, ph - OVERLAP):
            X, Y = ox + cx * mm, oy + cy * mm
            c.line(X - 4 * mm, Y, X + 4 * mm, Y)
            c.line(X, Y - 4 * mm, X, Y + 4 * mm)
    c.setFont(font, 8)
    row, col = ny - j, i + 1
    c.drawString(ox + 2 * mm, pw_pt * 0 + oy + ph * mm + 2 * mm, f"Sayfa {row}-{col}  ({row} = yukarıdan satır, {col} = soldan sütun)")
    if col < nx:
        c.drawRightString(ox + pw * mm - 1 * mm, oy + ph * mm / 2, f"→ {row}-{col + 1} ile birleştir")
    if col > 1:
        c.drawString(ox + 1 * mm, oy + ph * mm / 2 + 4 * mm, f"← {row}-{col - 1}")
    if j > 0:
        c.drawCentredString(ox + pw * mm / 2, oy + 2 * mm, f"↓ {row + 1}-{col} ile birleştir")
    if row > 1:
        c.drawCentredString(ox + pw * mm / 2, oy + ph * mm - 4 * mm, f"↑ {row - 1}-{col}")
    # 50 mm scale bar (must measure 50 mm when printed at 100%)
    c.setLineWidth(1)
    c.line(ox + 20 * mm, oy + 8 * mm, ox + 70 * mm, oy + 8 * mm)
    c.line(ox + 20 * mm, oy + 6 * mm, ox + 20 * mm, oy + 10 * mm)
    c.line(ox + 70 * mm, oy + 6 * mm, ox + 70 * mm, oy + 10 * mm)
    c.setFont(font, 7)
    c.drawString(ox + 72 * mm, oy + 7 * mm, "50 mm (ölçek kontrolü)")
