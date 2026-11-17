"""Baking tools: cutter blades (flange on the bed, thin cutting edge up), stamps with a relief and a blind socket for
a push-in handle (long handle = ejector that pushes the dough out of the cutter), outline sources.

Cutters and stamps are printed face up and turned over to use, so everything is designed in the cookie's frame (as
the cookie is seen from above) and then mirrored as a whole with ``mirror`` into the print frame.

Food contact: printed parts have layer crevices; the notes tell the user to use a food-safe filament, wash by hand
and keep them for dry dough (cookies, fondant), not for wet or raw-meat use."""
from __future__ import annotations

from pathlib import Path

from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import polylabel, unary_union

from . import core, estimate, flat
from .generators.base import Part
from .shapes import shape_polygon

BRIDGE_MM = 3.0  # text / logo pieces merged into one cookie silhouette
EDGE_MM = 0.8  # cutting edge wall (two 0.4 mm lines)
EDGE_H = 3.0  # height of the thin edge at the top
SOCKET_D = 8.0  # handle peg
SOCKET_DEPTH = 2.0
PEG_CLEAR = 0.15  # radial, press fit
STAMP_CLEAR = 0.8  # stamp / ejector plate inside the cutter, per side

FOOD_NOTES = [
    "Gıda teması: gıdaya uygun filament kullanın (PLA/PETG'nin gıdaya uygun sertifikalı olanları), elde ılık suyla yıkayın; "
    "bulaşık makinesi PLA'yı eğer. Katman aralarında hamur kalabilir: kuru hamur (kurabiye, şeker hamuru) için kullanın, "
    "çiğ et ya da ıslak gıdada kullanmayın. İsterseniz hamurla kalıp arasına streç film koyun.",
]


def outline_from(v: dict, width: float) -> tuple[Polygon, list[str], object]:
    """Silhouette ``width`` mm wide from v['source'] (shape / text / logo), hole-free, centred; plus the text / logo
    geometry it was made from (same position; None for shapes)."""
    if v["source"] == "shape":
        return shape_polygon(v["shape"], width), [], None
    inner = width - 2 * BRIDGE_MM
    if v["source"] == "text":
        if not v["text"].strip():
            raise ValueError("Kesici silüeti için bir yazı girin.")
        g, warnings = core.text_geometry(v["text"], v["font"], width_mm=inner)
    else:
        if not v["logo"] or not Path(v["logo"]).is_file():
            raise ValueError("Logo / görsel dosyası seçin (SVG, PNG ya da JPG).")
        logo = core.load_logo(v["logo"], inner)
        g, warnings = [r.geometry for r in logo.regions], list(logo.warnings)
    g = unary_union(g)
    poly = flat.bubble(g, BRIDGE_MM)  # bubble letters: every piece kept (i dots, accents)
    x0, y0, x1, y1 = poly.bounds
    dx, dy = -(x0 + x1) / 2, -(y0 + y1) / 2
    return affinity.translate(poly, dx, dy), warnings, affinity.translate(g, dx, dy)


def check_dough(outline: Polygon, warnings: list[str], neck: float = 6.0) -> Polygon:
    """Round very sharp inner corners (dough tears there) and warn about narrow parts that will not release."""
    g = outline.buffer(1.0, quad_segs=12).buffer(-1.0, quad_segs=12)
    g = Polygon(g.exterior) if g.geom_type == "Polygon" else Polygon(max(g.geoms, key=lambda q: q.area).exterior)
    opened = g.buffer(-neck / 2).buffer(neck / 2)
    if g.area - opened.area > 0.03 * g.area:
        warnings.append(f"{neck:g} mm'den dar bölgeler var: hamur oradan kopabilir ya da kesiciden çıkmayabilir. Şekli büyütün.")
    return g


def cutter_blade(inside: Polygon, height: float, wall: float, flange_w: float, flange_t: float, *, inner_walls=None):
    """Blade around ``inside`` (the cut line): flange on the bed, ``wall`` thick, the top EDGE_H mm only EDGE_MM thick
    (cutting edge, printed up). ``inner_walls``: extra dividing walls (grid cutters), same profile."""
    def ring(w):
        r = inside.buffer(w, quad_segs=12, join_style=1).difference(inside)
        if inner_walls is not None:
            r = r.union(inner_walls(w))
        return r

    parts = [core.extrude(inside.buffer(wall + flange_w, quad_segs=12).difference(inside), 0.0, flange_t),
             core.extrude(ring(wall), 0.0, height - EDGE_H),
             core.extrude(ring(EDGE_MM), height - EDGE_H - 0.01, height)]
    if inner_walls is not None:
        parts.append(core.extrude(inner_walls(wall), 0.0, flange_t))
    return core.union_all(parts)


def mirror(g):
    """Cookie frame -> print frame (the printed tool is turned over to use)."""
    return None if g is None else affinity.scale(g, -1, 1, origin=(0, 0))


def stamp_plate(plate: Polygon, relief, thick: float, relief_h: float, warnings: list[str], socket: bool = True):
    """Plate (bed side = back, with the handle socket) and the relief raised on top (print frame).
    Returns (plate manifold, relief manifold or None, socket made)."""
    base = core.extrude(plate, 0.0, thick)
    if socket:
        c = polylabel(plate, tolerance=0.3)
        if plate.buffer(-2.0).contains(Point(c.x, c.y).buffer(SOCKET_D / 2 + PEG_CLEAR)):
            base = base - core.extrude(Point(c.x, c.y).buffer(SOCKET_D / 2 + PEG_CLEAR, quad_segs=24), -0.01, SOCKET_DEPTH)
        else:
            warnings.append("Damga sap yuvası için çok küçük; sap eklenmedi.")
            socket = False
    rel = None
    if relief is not None and not relief.is_empty:
        rel = core.extrude(relief, thick - 0.01, thick + relief_h)
    return base, rel, socket


def handle(length: float, grip_d: float = 24.0):
    """Push-in handle printed grip-down: disc + column + peg (fits the stamp's socket)."""
    col = min(14.0, grip_d * 0.6)
    return core.union_all([
        core.extrude(Point(0, 0).buffer(grip_d / 2, quad_segs=32), 0.0, 3.0),
        core.extrude(Point(0, 0).buffer(col / 2, quad_segs=32), 2.99, 3.0 + length),
        core.extrude(Point(0, 0).buffer(SOCKET_D / 2 - PEG_CLEAR, quad_segs=24), 2.99 + length, 3.0 + length + SOCKET_DEPTH - 0.2),
    ])


def relief_from(v: dict, plate: Polygon, warnings: list[str], pct_key: str = "stamp_pct", own=None):
    """Stamp relief in the cookie frame: text, logo or the shape's contour line; None for 'none'. ``own``: the cutter's
    own text silhouette source, used as is when the stamp repeats the cutter text (letters sit exactly in their bubble)."""
    kind = v["stamp"]
    if kind == "none":
        return None
    if kind == "text" and own is not None and v.get("source") == "text" and v["stamp_text"].strip() in ("", v["text"].strip()):
        return flat.thicken(own, warnings, "Damga yazısı", plate.buffer(-0.5))
    region = plate.buffer(-2.0)
    x0, _, x1, _ = plate.bounds
    width = (x1 - x0) * v[pct_key] / 100
    if kind == "contour":
        return plate.buffer(-2.0).difference(plate.buffer(-3.2))
    if kind == "text":
        if not v["stamp_text"].strip() and v.get("source") == "text":
            v = {**v, "stamp_text": v["text"]}  # name cookie: the name on the cookie too
        if not v["stamp_text"].strip():
            raise ValueError("Damga için bir yazı girin.")
        g, _ = flat.fit_text(v["stamp_text"], v["stamp_font"], region, width, warnings, "Damga yazısı")
    else:
        if not v["stamp_logo"] or not Path(v["stamp_logo"]).is_file():
            raise ValueError("Damga logosu için dosya seçin (SVG, PNG ya da JPG).")
        logo = core.load_logo(v["stamp_logo"], width, 1)
        warnings += logo.warnings
        g = affinity.translate(unary_union([r.geometry for r in logo.regions]), -logo.width_mm / 2, -logo.height_mm / 2)
        g, _ = flat.fit_geometry(g, region, warnings, "Damga logosu")
    return g


def part(name: str, label: str, solid, color: str, material: str, **meta) -> Part:
    mesh = core.to_trimesh(solid)
    e = estimate.part_estimate(mesh, material, "flat")
    return Part(name, label, mesh, color, material, {"grams": e.grams, "minutes": e.minutes, "cost_try": e.try_, **meta})
