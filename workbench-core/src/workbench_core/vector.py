"""Vector cut paths: the outlines of a product as SVG (Inkscape, LightBurn, vinyl cutters) and DXF (laser / CNC).

Every item is one layer: (name, "#RRGGBB", shapely geometry in mm). Outlines are closed rings at 1:1 scale in mm;
holes are their own rings (cutters treat every closed ring as a cut). Lines (e.g. an LED strip path) stay open paths. DXF is plain R12 (POLYLINE / VERTEX), read by
every CAM program; no extra dependency."""
from __future__ import annotations

import re
from pathlib import Path
from xml.sax.saxutils import escape

from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

Item = tuple[str, str, BaseGeometry]


def _polys(g: BaseGeometry) -> list[Polygon]:
    if g is None or g.is_empty:
        return []
    if isinstance(g, Polygon):
        return [g]
    if isinstance(g, MultiPolygon):
        return list(g.geoms)
    return [p for sub in getattr(g, "geoms", []) for p in _polys(sub)]


def rings(g: BaseGeometry, tol: float = 0.01) -> list[list[tuple[float, float]]]:
    """Closed rings (outer and holes) of ``g``, simplified to ``tol`` mm, without the repeated last point."""
    out = []
    for p in _polys(g):
        p = p.simplify(tol) if tol else p
        for r in [p.exterior, *p.interiors]:
            c = list(r.coords)[:-1]
            if len(c) >= 3:
                out.append([(float(x), float(y)) for x, y in c])
    return out


def paths(g: BaseGeometry, tol: float = 0.01) -> list[tuple[list[tuple[float, float]], bool]]:
    """(points, closed) for every ring of the polygons and every line of ``g``."""
    out = [(r, True) for r in rings(g, tol)]
    lines = [g] if g.geom_type == "LineString" else [s for s in getattr(g, "geoms", []) if s.geom_type == "LineString"]
    for ln in lines:
        c = [(float(x), float(y)) for x, y in (ln.simplify(tol) if tol else ln).coords]
        if len(c) >= 2:
            out.append((c, False))
    return out


def part_outlines(parts, name=lambda p: p.name, color=lambda p: p.color, mesh=lambda p: p.mesh) -> list[Item]:
    """Top-view silhouettes of mesh parts (one layer per part). Parts whose silhouette equals an earlier one (a face
    layer on its body) are skipped."""
    from .geometry import mesh_footprint

    items: list[Item] = []
    for p in parts:
        g = mesh_footprint(mesh(p))
        if g.is_empty or any(abs(g.area - h.area) < 1e-3 and g.symmetric_difference(h).area < 0.01 for _, _, h in items):
            continue
        items.append((name(p), color(p), g))
    return items


def _bounds(items: list[Item]):
    xs, ys = [], []
    for _, _, g in items:
        if not g.is_empty:
            x0, y0, x1, y1 = g.bounds
            xs += [x0, x1]
            ys += [y0, y1]
    return (min(xs), min(ys), max(xs), max(ys)) if xs else (0.0, 0.0, 1.0, 1.0)


def _stroke(color: str) -> str:
    c = (color or "#000000").upper()
    return "#9A9A9A" if c in ("#FFFFFF", "#FFF") else c  # white would vanish on the cutter's white canvas


def write_svg(items: list[Item], path: Path | str, margin: float = 5.0, title: str = "") -> Path:
    """One <g> per layer (Inkscape layers), y up like the model, units mm (width/height in mm, 1 user unit = 1 mm)."""
    x0, y0, x1, y1 = _bounds(items)
    w, h = x1 - x0 + 2 * margin, y1 - y0 + 2 * margin

    def tx(x, y):
        return x - x0 + margin, (y1 - y) + margin  # flip y: SVG y grows downwards

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
           f'width="{w:.3f}mm" height="{h:.3f}mm" viewBox="0 0 {w:.3f} {h:.3f}">']
    if title:
        out.append(f"<title>{escape(title)}</title>")
    for name, color, g in items:
        d = []
        for r, closed in paths(g):
            pts = [tx(x, y) for x, y in r]
            d.append("M" + " L".join(f"{x:.3f},{y:.3f}" for x, y in pts) + (" Z" if closed else ""))
        if not d:
            continue
        lid = re.sub(r"[^A-Za-z0-9_-]", "_", name)
        out.append(f'<g id="{lid}" inkscape:groupmode="layer" inkscape:label="{escape(name)}">'
                   f'<path d="{" ".join(d)}" fill="none" fill-rule="evenodd" stroke="{_stroke(color)}" stroke-width="0.1"/></g>')
    out.append("</svg>")
    p = Path(path)
    p.write_text("\n".join(out), encoding="utf-8")
    return p


def _aci(color: str) -> int:
    """Nearest AutoCAD colour index among the basic ones (1 red .. 7 black/white, 8 grey)."""
    c = (color or "#000000").lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    table = {1: (255, 0, 0), 2: (255, 255, 0), 3: (0, 255, 0), 4: (0, 255, 255), 5: (0, 0, 255), 6: (255, 0, 255),
             7: (0, 0, 0), 8: (128, 128, 128), 9: (192, 192, 192)}
    if min(r, g, b) > 230:
        return 9
    return min(table, key=lambda k: sum((a - q) ** 2 for a, q in zip((r, g, b), table[k])))


def write_dxf(items: list[Item], path: Path | str) -> Path:
    """DXF R12, one layer per item, closed POLYLINEs in mm."""
    def pair(code, val):
        return f"{code}\n{val}\n"

    names = []
    for name, _, _ in items:
        n = re.sub(r"[^A-Za-z0-9_-]", "_", name)[:31] or "LAYER"
        while n in names:
            n = n[:28] + f"_{len(names)}"
        names.append(n)
    s = pair(0, "SECTION") + pair(2, "HEADER") + pair(9, "$ACADVER") + pair(1, "AC1009") + pair(9, "$INSUNITS") + pair(70, 4)
    s += pair(0, "ENDSEC") + pair(0, "SECTION") + pair(2, "TABLES") + pair(0, "TABLE") + pair(2, "LAYER") + pair(70, len(items))
    for n, (_, color, _) in zip(names, items):
        s += pair(0, "LAYER") + pair(2, n) + pair(70, 0) + pair(62, _aci(color)) + pair(6, "CONTINUOUS")
    s += pair(0, "ENDTAB") + pair(0, "ENDSEC") + pair(0, "SECTION") + pair(2, "ENTITIES")
    for n, (_, _, g) in zip(names, items):
        for r, closed in paths(g):
            s += pair(0, "POLYLINE") + pair(8, n) + pair(66, 1) + pair(70, 1 if closed else 0)
            for x, y in r:
                s += pair(0, "VERTEX") + pair(8, n) + pair(10, f"{x:.4f}") + pair(20, f"{y:.4f}")
            s += pair(0, "SEQEND") + pair(8, n)
    s += pair(0, "ENDSEC") + pair(0, "EOF")
    p = Path(path)
    p.write_text(s, encoding="ascii")
    return p


def read_dxf_rings(path: Path | str) -> dict[str, list[list[tuple[float, float]]]]:
    """Minimal reader for the files written above (tests / round trips): layer -> rings."""
    lines = Path(path).read_text(encoding="ascii").splitlines()
    pairs = list(zip(lines[0::2], lines[1::2]))
    out: dict[str, list] = {}
    cur, layer, x = None, None, None
    for code, val in pairs:
        code = code.strip()
        if code == "0":
            if val == "POLYLINE":
                cur, layer = [], None
            elif val == "SEQEND" and cur is not None:
                out.setdefault(layer, []).append(cur)
                cur = None
        elif code == "8" and cur is not None and layer is None:
            layer = val
        elif code == "10" and cur is not None:
            x = float(val)
        elif code == "20" and cur is not None:
            cur.append((x, float(val)))
    return out


def export_cut_paths(items: list[Item], out_dir: Path | str, stem: str = "kesim", title: str = "") -> dict[str, Path]:
    """Write ``<stem>.svg`` and ``<stem>.dxf`` into ``out_dir``."""
    d = Path(out_dir)
    d.mkdir(parents=True, exist_ok=True)
    return {"svg": write_svg(items, d / f"{stem}.svg", title=title), "dxf": write_dxf(items, d / f"{stem}.dxf")}
