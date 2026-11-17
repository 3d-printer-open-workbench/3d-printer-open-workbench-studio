"""2D -> 3D bodies (mm).

Wall orientation (used for all construction): x right, y up, back of the object at
z = 0, face toward +z. Each :class:`Part` also carries the transform to *print
orientation*: Mode A prints face-up (identity), Mode B prints face-down (rotate 180
degrees about X so the smooth face sits on the plate, back at the top).

STL export writes parts in print orientation, each moved to the origin
(min corner = 0,0,0), ready for any slicer.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import numpy as np
import trimesh
from manifold3d import CrossSection, FillRule, Manifold
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .fonts import ResolvedFont
from .text2d import TextResult, _polys_only, build_text

BED_MM = 250.0
MAX_LETTER_MM = 250.0  # one letter fits 250 x 250 x 250 mm (Centauri Carbon 256 mm build volume)
MAX_COLORS = 4
FACE_LAYER_MM = 0.6
DEFAULT_COLORS = ("#222222", "#F5F5F5", "#C0392B", "#2980B9")
RECOMMENDED_INFILL = "10% gyroid"
SHELL_BACK_CONTACT_MIN = 0.40
SHELL_MIN_CAP_MM = 60.0

FlatStyle = Literal["single", "two_tone", "backplate"]


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
@dataclass
class Part:
    name: str
    role: str  # body | face | plate | glyphs | letter | letter_face
    mesh_wall: trimesh.Trimesh  # wall orientation, assembled position
    color: str  # hex
    extruder: int  # 1..4
    print_transform: np.ndarray = field(default_factory=lambda: np.eye(4))
    meta: dict = field(default_factory=dict)  # e.g. detached_pieces (wall coordinates, mm)
    group: str = ""  # parts of one physical assembly share a group (split/pack together)

    @property
    def mesh(self) -> trimesh.Trimesh:
        """Mesh in print orientation, assembled position."""
        m = self.mesh_wall.copy()
        m.apply_transform(self.print_transform)
        return m


@dataclass
class Model:
    mode: str
    parts: list[Part]
    width_mm: float
    height_mm: float
    depth_mm: float
    warnings: list[str]
    meta: dict
    layout: TextResult | None = None

    @property
    def colors(self) -> list[str]:
        out: list[str] = []
        for p in self.parts:
            if p.color not in out:
                out.append(p.color)
        return out


# --------------------------------------------------------------------------- #
# Manifold helpers
# --------------------------------------------------------------------------- #
def _loops(geom: BaseGeometry) -> list[np.ndarray]:
    polys = [geom] if isinstance(geom, Polygon) else list(getattr(geom, "geoms", []))
    loops: list[np.ndarray] = []
    for p in polys:
        if p.is_empty:
            continue
        loops.append(np.asarray(p.exterior.coords)[:-1])
        loops.extend(np.asarray(r.coords)[:-1] for r in p.interiors)
    return loops


def clean_for_extrusion(geom: BaseGeometry, eps: float = 0.01) -> BaseGeometry:
    """Simplify and morphologically close by ``eps`` mm so pinch points (a contour
    touching itself at a vertex) cannot become non-manifold edges after STL export."""
    g = geom.simplify(0.005, preserve_topology=True)
    g = g.buffer(eps, quad_segs=4, join_style="round").buffer(-eps, quad_segs=4, join_style="round")
    return g.simplify(0.002, preserve_topology=True)


def extrude(geom: BaseGeometry, z0: float, z1: float) -> Manifold:
    """Extrude a (Multi)Polygon between z0 and z1."""
    if z1 <= z0:
        raise ValueError("extrude requires z1 > z0")
    loops = _loops(clean_for_extrusion(geom))
    if not loops:
        return Manifold()
    cs = CrossSection(loops, FillRule.EvenOdd)
    return Manifold.extrude(cs, z1 - z0).translate((0.0, 0.0, z0))


def to_trimesh(m: Manifold) -> trimesh.Trimesh:
    mesh = m.to_mesh64() if hasattr(m, "to_mesh64") else m.to_mesh()
    tm = trimesh.Trimesh(
        vertices=np.asarray(mesh.vert_properties, dtype=float)[:, :3],
        faces=np.asarray(mesh.tri_verts, dtype=np.int64),
        process=False,
    )
    return tm


def from_trimesh(mesh: trimesh.Trimesh) -> Manifold:
    from manifold3d import Mesh

    return Manifold(
        Mesh(
            vert_properties=np.asarray(mesh.vertices, dtype=np.float32),
            tri_verts=np.asarray(mesh.faces, dtype=np.uint32),
        )
    )


def cylinder(radius: float, height: float, axis: str, center: tuple[float, float, float]) -> Manifold:
    """Cylinder of ``height`` centred on ``center`` along x, y or z."""
    cyl = Manifold.cylinder(height, radius, radius, 48, True)  # along z, centred
    if axis == "x":
        cyl = cyl.rotate((0.0, 90.0, 0.0))
    elif axis == "y":
        cyl = cyl.rotate((-90.0, 0.0, 0.0))
    return cyl.translate(center)


def mesh_footprint(mesh: trimesh.Trimesh) -> BaseGeometry:
    """XY silhouette of a mesh as a shapely geometry (even-odd over projected loops)."""
    result: BaseGeometry | None = None
    for loop in from_trimesh(mesh).project().to_polygons():
        pg = Polygon(loop).buffer(0)
        result = pg if result is None else result.symmetric_difference(pg)
    return result if result is not None else Polygon()


def union_all(items: list[Manifold]) -> Manifold:
    return Manifold.batch_boolean(items, 0) if len(items) > 1 else items[0]  # 0 = Add


def is_part_valid(mesh: trimesh.Trimesh) -> bool:
    return bool(mesh.is_watertight and mesh.is_winding_consistent and mesh.volume > 0)


def fits_bed(mesh: trimesh.Trimesh, limit: float = BED_MM) -> bool:
    return bool(np.all(mesh.extents <= limit + 1e-6))


def back_contact_ratio(mesh_wall: trimesh.Trimesh, silhouette_area: float) -> float:
    """Area of downward-facing flat faces at z=0 divided by the silhouette area."""
    n = mesh_wall.face_normals
    tri = mesh_wall.triangles
    flat = (n[:, 2] < -0.999) & (np.abs(tri[:, :, 2]).max(axis=1) < 1e-6)
    return float(mesh_wall.area_faces[flat].sum() / silhouette_area)


def _ascii_name(s: str) -> str:
    base = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    base = re.sub(r"[^A-Za-z0-9]+", "", base)
    return base or "x"


# --------------------------------------------------------------------------- #
# Colors
# --------------------------------------------------------------------------- #
def _assign_extruders(colors: list[str]) -> dict[str, int]:
    distinct: list[str] = []
    for c in colors:
        if c not in distinct:
            distinct.append(c)
    if len(distinct) > MAX_COLORS:
        raise ValueError(f"At most {MAX_COLORS} colors are supported, got {len(distinct)}")
    return {c: i + 1 for i, c in enumerate(distinct)}


def _norm_color(c: str) -> str:
    c = c.strip()
    return c.upper() if c.startswith("#") else c


# --------------------------------------------------------------------------- #
# Mode A
# --------------------------------------------------------------------------- #
def plate_outline(geom: BaseGeometry, offset: float) -> BaseGeometry:
    """Solid backing-plate silhouette: glyph union offset outward, interior holes filled."""
    grown = geom.buffer(offset, quad_segs=16, join_style="round")
    polys = [grown] if isinstance(grown, Polygon) else list(grown.geoms)
    return unary_union([Polygon(p.exterior) for p in polys])


def _normalize(geoms: list[BaseGeometry]) -> tuple[list[BaseGeometry], float, float, float, float]:
    minx = min(g.bounds[0] for g in geoms)
    miny = min(g.bounds[1] for g in geoms)
    maxx = max(g.bounds[2] for g in geoms)
    maxy = max(g.bounds[3] for g in geoms)
    return [affinity.translate(g, -minx, -miny) for g in geoms], maxx - minx, maxy - miny, minx, miny


def _offset_geom(g: BaseGeometry, offset_mm: float) -> BaseGeometry:
    if not offset_mm or abs(offset_mm) < 1e-6:
        return g
    out = _polys_only(g.buffer(float(offset_mm), quad_segs=16, join_style="round"))
    return g if out.is_empty else out


def build_flat(
    layout: TextResult,
    *,
    thickness: float = 5.0,
    style: FlatStyle = "single",
    colors: list[str] | None = None,
    plate_offset: float = 6.0,
    plate_thickness: float = 3.0,
    face_layer: float = FACE_LAYER_MM,
    split_letters: bool = False,
    stroke_offset_mm: float = 0.0,
) -> Model:
    """Mode A bodies from a text layout. ``thickness`` is the sign thickness (1-50 mm); for ``backplate``
    it is the glyph thickness on top of the plate (total = thickness + plate_thickness); up to 250 mm (printer Z).
    When ``split_letters=True`` (for ``single`` or ``two_tone``), each letter is built as its own
    separate Part (``letter_01_P``, ``letter_02_r``, ...) so STL export and 3MF plate packing happen
    letter-by-letter while keeping the assembled wall coordinates for ``template.pdf`` and renders."""
    if not (1.0 <= float(thickness) <= MAX_LETTER_MM):
        raise ValueError(f"thickness must be between 1 and {MAX_LETTER_MM:.0f} mm")
    if style not in ("single", "two_tone", "backplate"):
        raise ValueError(f"unknown style {style!r}")
    cols = [_norm_color(c) for c in (colors or DEFAULT_COLORS)]
    need = 1 if style == "single" else 2
    if len(cols) < need:
        raise ValueError(f"style {style!r} needs {need} colors")
    cols = cols[:need]
    ext = _assign_extruders(cols)
    warnings = list(layout.warnings)
    T = float(thickness)
    text = _offset_geom(layout.geometry, stroke_offset_mm)

    if split_letters and style in ("single", "two_tone") and layout.pieces:
        pieces = layout.pieces
        joint_info: list[dict] = []
        if any(len(p.glyph_indices) > 1 for p in pieces):
            from .joints import split_joined

            pieces, js, jw = split_joined(layout)
            warnings += jw
            joint_info = [j.info() for j in js]
        geoms, w, h, _, _ = _normalize([_offset_geom(p.geometry, stroke_offset_mm) for p in pieces])
        parts: list[Part] = []
        for i, (piece, g) in enumerate(zip(pieces, geoms), start=1):
            stem = f"letter_{i:02d}_{_ascii_name(piece.text)}"
            detached = detached_pieces(g)
            pmeta = {"detached_pieces": detached} if detached else {}
            if style == "single":
                mesh = to_trimesh(extrude(g, 0.0, T))
                parts.append(Part(stem, "letter", mesh, cols[0], ext[cols[0]], meta=pmeta, group=stem))
            else:
                bmesh = to_trimesh(extrude(g, 0.0, T - face_layer))
                fmesh = to_trimesh(extrude(g, T - face_layer, T))
                parts.append(Part(f"{stem}_body", "body", bmesh, cols[0], ext[cols[0]], meta=pmeta, group=stem))
                parts.append(Part(f"{stem}_face", "face", fmesh, cols[1], ext[cols[1]], meta=dict(pmeta), group=stem))
        meta = {"style": style, "thickness": T, "split_letters": True}
        if joint_info:
            meta["joints"] = joint_info
        model = Model("flat", parts, w, h, T, warnings, meta, layout)
        _check_bed(model)
        return model

    specs: list[tuple[str, str, BaseGeometry, float, float, str]] = []  # name, role, geom, z0, z1, color
    if style == "single":
        specs.append(("body", "body", text, 0.0, T, cols[0]))
    elif style == "two_tone":
        specs.append(("body", "body", text, 0.0, T - face_layer, cols[0]))
        specs.append(("face", "face", text, T - face_layer, T, cols[1]))
    else:
        plate = plate_outline(text, plate_offset)
        specs.append(("plate", "plate", plate, 0.0, plate_thickness, cols[0]))
        specs.append(("glyphs", "glyphs", text, plate_thickness, plate_thickness + T, cols[1]))
    geoms, w, h, _, _ = _normalize([s[2] for s in specs])
    parts = []
    for (name, role, _g, z0, z1, color), g in zip(specs, geoms):
        mesh = to_trimesh(extrude(g, z0, z1))
        parts.append(Part(name, role, mesh, color, ext[color], group="sign"))
    total = T + plate_thickness if style == "backplate" else T
    model = Model("flat", parts, w, h, total, warnings, {"style": style, "thickness": T}, layout)
    _check_bed(model)
    return model


def build_logo_flat(logo, *, thickness: float = 5.0) -> Model:
    """Mode A from a logo: every color region becomes a separate full-thickness body."""
    if not (1.0 <= float(thickness) <= MAX_LETTER_MM):
        raise ValueError(f"thickness must be between 1 and {MAX_LETTER_MM:.0f} mm")
    colors = []
    for r in logo.regions:
        if r.color not in colors:
            colors.append(r.color)
    ext = _assign_extruders(colors)
    geoms, w, h, _, _ = _normalize([r.geometry for r in logo.regions])
    parts = []
    for i, (r, g) in enumerate(zip(logo.regions, geoms), start=1):
        mesh = to_trimesh(extrude(g, 0.0, float(thickness)))
        pname = r.name or f"region_{i}_{r.color[1:]}"
        parts.append(Part(pname, "text" if r.name == "text" else "logo", mesh, r.color, ext[r.color], group="sign"))
    model = Model(
        "flat", parts, w, h, float(thickness), list(logo.warnings),
        {"style": "logo", "thickness": float(thickness), "logo_source": logo.source}, None,
    )
    _check_bed(model)
    return model


# --------------------------------------------------------------------------- #
# Mode B
# --------------------------------------------------------------------------- #
def shell_cavity(
    geom: BaseGeometry, wall: float, target_contact: float = 0.45, rib_width: float | None = None
) -> BaseGeometry:
    """2D footprint of the hollow behind the face: interior (inset by ``wall``) minus ribs.

    Ribs form an orthogonal grid whose spacing is tightened until wall+ribs cover at
    least ``target_contact`` of the silhouette (flat back area for tape). Empty if the
    letter is too thin to hollow (then it stays solid).
    """
    rib_width = rib_width or wall
    interior = geom.buffer(-wall, join_style="round")
    if interior.is_empty:
        return Polygon()
    minx, miny, maxx, maxy = geom.bounds
    ring_area = geom.area - interior.area
    cavity = interior
    spacing = 40.0
    while spacing >= rib_width * 2.5:
        lines = []
        x = minx + spacing / 2
        while x < maxx:
            lines.append(box(x - rib_width / 2, miny, x + rib_width / 2, maxy))
            x += spacing
        y = miny + spacing / 2
        while y < maxy:
            lines.append(box(minx, y - rib_width / 2, maxx, y + rib_width / 2))
            y += spacing
        ribs = interior.intersection(unary_union(lines))
        cavity = interior.difference(ribs)
        if (ring_area + ribs.area) / geom.area >= target_contact:
            break
        spacing *= 0.8
    # opening by eps removes pinch points where two cavity cells touch at a vertex
    eps = 0.01
    cavity = cavity.buffer(-eps, quad_segs=4).buffer(eps, quad_segs=4)
    return _polys_only(cavity)


def detached_pieces(geom: BaseGeometry) -> list[dict]:
    """Solids of a letter that are disconnected from its main body (dots, accents,
    cedillas). Wall coordinates in mm; the main body is the largest polygon."""
    polys = [geom] if isinstance(geom, Polygon) else sorted(geom.geoms, key=lambda p: -p.area)
    out = []
    for p in polys[1:]:
        out.append(
            {
                "centroid": [round(p.centroid.x, 3), round(p.centroid.y, 3)],
                "bounds": [round(v, 3) for v in p.bounds],
                "area": round(p.area, 3),
            }
        )
    return out


def build_letters(
    layout: TextResult,
    *,
    depth: float = 30.0,
    colors: list[str] | None = None,
    face_color: str | None = None,
    open_back_shell: bool = False,
    wall: float = 2.4,
    shell_face: float = 2.0,
    face_layer: float = FACE_LAYER_MM,
    joints: str = "none",
    stroke_offset_mm: float = 0.0,
) -> Model:
    """Mode B bodies: one part per connected letter group (plus a face layer part if
    ``face_color`` is given). Solid by default; ``open_back_shell`` hollows the back.
    ``joints="puzzle"``: joined (script) letters are cut apart where they join, one part per letter, with a jigsaw
    lock at each cut (workbench_core.joints); "none" keeps a joined word as one part."""
    if joints not in ("none", "puzzle"):
        raise ValueError("joints must be 'none' or 'puzzle'")
    if not (2.0 <= float(depth) <= MAX_LETTER_MM):
        raise ValueError(f"depth must be between 2 and {MAX_LETTER_MM:.0f} mm")
    D = float(depth)
    n_glyphs = len(layout.glyphs)
    cols = [_norm_color(c) for c in (colors or [DEFAULT_COLORS[0]])]
    if len(cols) > MAX_COLORS:
        raise ValueError(f"at most {MAX_COLORS} letter colours (filament slots)")
    cols = [cols[i % len(cols)] for i in range(n_glyphs)]  # fewer colours than letters: cycle them in order
    face = _norm_color(face_color) if face_color else None
    ext = _assign_extruders(cols + ([face] if face else []))
    warnings = list(layout.warnings)
    if open_back_shell and layout.cap_height_mm < SHELL_MIN_CAP_MM:
        warnings.append(
            f"open_back_shell needs cap height >= {SHELL_MIN_CAP_MM:.0f} mm; building solid letters instead."
        )
        open_back_shell = False
    elif open_back_shell and layout.cap_height_mm < 100:
        warnings.append("open_back_shell is intended for large letters (cap height >= 100 mm).")

    pieces = layout.pieces
    joint_info: list[dict] = []
    if joints == "puzzle" and any(len(p.glyph_indices) > 1 for p in pieces):
        from .joints import split_joined

        pieces, js, jw = split_joined(layout)
        warnings += jw
        joint_info = [j.info() for j in js]
    geoms, w, h, _, _ = _normalize([_offset_geom(p.geometry, stroke_offset_mm) for p in pieces])  # keeps assembled positions

    flip = np.array(
        [[1, 0, 0, 0], [0, -1, 0, h], [0, 0, -1, D], [0, 0, 0, 1]], dtype=float
    )  # rotate 180 deg about X: face (z=D) lands on the plate (z=0)
    parts: list[Part] = []
    contact: dict[str, float] = {}
    for i, (piece, g) in enumerate(zip(pieces, geoms), start=1):
        color = cols[piece.glyph_indices[0]]
        stem = f"letter_{i:02d}_{_ascii_name(piece.text)}"
        face_h = face_layer if face else 0.0
        z_top_body = D - face_h
        if open_back_shell:
            slab_z0 = D - shell_face
            body = extrude(g, 0.0, z_top_body)
            cavity = shell_cavity(g, wall)
            if not cavity.is_empty:
                body = body - extrude(cavity, -1.0, slab_z0)
        else:
            body = extrude(g, 0.0, z_top_body)
        mesh = to_trimesh(body)
        detached = detached_pieces(g)
        pmeta = {"detached_pieces": detached} if detached else {}
        parts.append(Part(f"{stem}_body" if face else stem, "letter", mesh, color, ext[color], flip, pmeta, stem))
        if open_back_shell:
            contact[stem] = back_contact_ratio(mesh, g.area)
        if face:
            fm = to_trimesh(extrude(g, z_top_body, D))
            parts.append(Part(f"{stem}_face", "letter_face", fm, face, ext[face], flip, dict(pmeta), stem))
    meta = {
        "depth": D,
        "construction": "open_back_shell" if open_back_shell else "solid",
        "print_orientation": "face_down",
        "recommended_infill": RECOMMENDED_INFILL,
        "cap_height_mm": layout.cap_height_mm,
        "metric": "cap height = OS/2 sCapHeight (fallback: height of 'H')",
    }
    if open_back_shell:
        meta.update(wall=wall, face=shell_face, back_contact=contact)
    if joint_info:
        meta["joints"] = joint_info
    model = Model("letters", parts, w, h, D, warnings, meta, layout)
    _check_bed(model)
    return model


def _check_bed(model: Model) -> None:
    for p in model.parts:
        if not fits_bed(p.mesh):
            ex = p.mesh.extents
            model.warnings.append(
                f"Part '{p.name}' is {ex[0]:.0f}x{ex[1]:.0f}x{ex[2]:.0f} mm and exceeds the "
                f"{BED_MM:.0f} mm bed; it will be split into pinned pieces (oversize_policy=split)."
            )


# --------------------------------------------------------------------------- #
# High level + export
# --------------------------------------------------------------------------- #
def _make_flat(
    text: str,
    font: ResolvedFont,
    width_mm: float,
    *,
    thickness: float = 5.0,
    style: FlatStyle = "single",
    plate_offset: float = 6.0,
    tracking: float = 0.0,
    line_spacing: float = 1.0,
    mounting: list[str] | None = None,
    keyhole_boss: bool = False,
    language: str | None = None,
    **kwargs,
) -> Model:
    """Text -> Mode A model whose *overall* width (incl. backplate) is ``width_mm``."""
    from .mounting import apply_mounting, connect_flat_layout, normalize_mounting

    mounting = normalize_mounting(mounting)
    text_w = width_mm - 2 * plate_offset if style == "backplate" else width_mm
    if text_w <= 0:
        raise ValueError("width too small for backplate offset")
    layout = build_text(text, font, "flat", width_mm=text_w, tracking=tracking, line_spacing=line_spacing, language=language)
    if "connector_bar" in mounting:
        layout = connect_flat_layout(layout)
        kwargs["split_letters"] = False
    model = build_flat(layout, thickness=thickness, style=style, plate_offset=plate_offset, **kwargs)
    model.meta["keyhole_boss"] = bool(keyhole_boss)
    return apply_mounting(model, mounting)


def _make_letters(
    text: str,
    font: ResolvedFont,
    cap_height_mm: float,
    *,
    depth: float = 30.0,
    tracking: float = 0.0,
    mounting: list[str] | None = None,
    language: str | None = None,
    letter_width_mm: float | None = None,
    fit_box: bool = False,
    **kwargs,
) -> Model:
    """Text -> Mode B model; ``cap_height_mm`` must be 20..400 (2-40 cm).
    ``letter_width_mm`` (optional): the widest letter is stretched/condensed to this width (X only);
    every letter gets the same X factor so the word keeps its rhythm. None/0 = the font's own proportions.
    ``fit_box=True``: ``cap_height_mm`` is the height of the TALLEST letter (i-dot, Ş cedilla, ascenders
    included), so no letter exceeds the requested height."""
    from .mounting import apply_mounting, normalize_mounting
    from .text2d import stretch_x

    mounting = normalize_mounting(mounting)
    if not 20 <= cap_height_mm <= 400:
        raise ValueError("letter height must be between 2 and 40 cm")
    layout = build_text(text, font, "letters", cap_height_mm=cap_height_mm, tracking=tracking, language=language)
    if fit_box:
        tallest = max((g.geometry.bounds[3] - g.geometry.bounds[1]) for g in layout.glyphs)
        if tallest > 0 and abs(tallest - cap_height_mm) > 0.05:
            cap = cap_height_mm * cap_height_mm / tallest
            layout = build_text(text, font, "letters", cap_height_mm=cap, tracking=tracking, language=language)
    if letter_width_mm:
        if not 5.0 <= float(letter_width_mm) <= MAX_LETTER_MM:
            raise ValueError(f"letter width must be between 5 and {MAX_LETTER_MM:.0f} mm")
        widest = max((g.geometry.bounds[2] - g.geometry.bounds[0]) for g in layout.glyphs)
        if widest > 0:
            layout = stretch_x(layout, float(letter_width_mm) / widest)
    model = build_letters(layout, depth=depth, **kwargs)
    return apply_mounting(model, mounting)


def export_stl(model: Model, out_dir: Path | str) -> list[Path]:
    """Write each part as binary STL in print orientation, min corner at the origin."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for p in model.parts:
        m = p.mesh
        m.apply_translation(-m.bounds[0])
        path = out / f"{p.name}.stl"
        m.export(path)
        paths.append(path)
    return paths


# --------------------------------------------------------------------------- #
# Oversize policy
# --------------------------------------------------------------------------- #
OVERSIZE_POLICIES = ("split", "limit")


def _check_policy(policy: str) -> None:
    if policy not in OVERSIZE_POLICIES:
        raise ValueError(f"oversize_policy must be one of {OVERSIZE_POLICIES}, got {policy!r}")


def _footprint_extents(model: Model) -> list[tuple[float, float]]:
    """Print-orientation XY extents of each group (rail segments excluded: they are
    generated <= 245 mm)."""
    groups: dict[str, list[np.ndarray]] = {}
    for p in model.parts:
        if p.role == "rail":
            continue
        b = p.mesh.bounds
        groups.setdefault(p.group or p.name, []).append(b)
    out = []
    for bs in groups.values():
        lo = np.min([b[0] for b in bs], axis=0)
        hi = np.max([b[1] for b in bs], axis=0)
        out.append((float(hi[0] - lo[0]), float(hi[1] - lo[1])))
    return out


def fits_without_split(model: Model, bed: float = BED_MM) -> bool:
    return all(w <= bed + 1e-6 and h <= bed + 1e-6 for w, h in _footprint_extents(model))


def max_no_split_size(model: Model, size_mm: float, plate_offset: float = 6.0, bed: float = BED_MM) -> float:
    """Largest requested size (Mode A overall width / Mode B cap height, mm) at which every
    part still fits bed x bed, estimated from ``model`` built at ``size_mm``."""
    ext = _footprint_extents(model)
    if model.mode == "letters" or model.meta.get("split_letters"):
        r = max(max(w, h) for w, h in ext) / bed
        return size_mm / r
    w, h = ext[0]
    if model.meta.get("style") == "backplate":
        o2 = 2 * plate_offset
        k = min((bed - o2) / (w - o2), (bed - o2) / (h - o2))  # text scale factor
        return (w - o2) * k + o2
    return size_mm * min(bed / w, bed / h)


def _with_policy(build, size_mm: float, policy: str, label: str, plate_offset: float = 6.0) -> Model:
    _check_policy(policy)
    model = build(size_mm)
    mx = max_no_split_size(model, size_mm, plate_offset)
    applied = size_mm
    if policy == "limit" and not fits_without_split(model):
        applied = mx * 0.9995
        for _ in range(8):
            model = build(applied)
            if fits_without_split(model):
                break
            applied *= 0.995
        model.warnings.insert(
            0,
            f"oversize_policy=limit: requested {label} {size_mm / 10:.1f} cm does not fit the "
            f"{BED_MM:.0f} mm bed; applied {applied / 10:.1f} cm (max without splitting "
            f"{mx / 10:.1f} cm).",
        )
    model.meta.update(
        oversize_policy=policy,
        size_requested_mm=size_mm,
        size_applied_mm=applied,
        max_no_split_size_mm=mx,
    )
    return model


def make_flat(text: str, font: ResolvedFont, width_mm: float, *, oversize_policy: str = "split", **kwargs) -> Model:
    """Mode A. ``oversize_policy``: "split" (cut big parts, see split.py) or "limit"
    (clamp the overall width so every part fits the bed)."""
    off = kwargs.get("plate_offset", 6.0)
    return _with_policy(lambda w: _make_flat(text, font, w, **kwargs), width_mm, oversize_policy, "width", off)


def _make_logo_flat(
    path, width_mm: float, *, thickness: float = 5.0, n_colors: int = 4, mounting: list[str] | None = None
) -> Model:
    from .logo2d import load_logo
    from .mounting import apply_mounting, normalize_mounting

    mounting = normalize_mounting(mounting)
    model = build_logo_flat(load_logo(path, width_mm, n_colors), thickness=thickness)
    if "connector_bar" in mounting:
        model.warnings.append("connector_bar is not applicable to logos (regions are already joined by the artwork).")
        mounting = [m for m in mounting if m != "connector_bar"]
    return apply_mounting(model, mounting)


def _make_logo_text_flat(
    path, text: str, font: ResolvedFont, width_mm: float, *, thickness: float = 5.0, n_colors: int = 4,
    layout: str = "logo_above", gap_mm: float = 10.0, logo_share: float = 0.5,
    text_color: str = DEFAULT_COLORS[0], tracking: float = 0.0, line_spacing: float = 1.0,
    mounting: list[str] | None = None, language: str | None = None,
) -> Model:
    from .logo2d import compose_logo_text, load_logo
    from .mounting import apply_mounting, normalize_mounting

    mounting = normalize_mounting(mounting)
    warnings: list[str] = []
    text_color = _norm_color(text_color)
    n = min(n_colors, MAX_COLORS - 1)
    if n < n_colors:
        warnings.append(f"logo reduced to {n} colors so the text color fits the 4-filament limit.")
    logo = load_logo(path, 100.0, n)
    cache: dict[float, TextResult] = {}

    def text_geom(w: float):
        lay = build_text(text, font, "flat", width_mm=w, tracking=tracking, line_spacing=line_spacing, language=language)
        cache[round(w, 6)] = lay
        return lay.geometry

    combo = compose_logo_text(logo, None, text_color, width_mm, layout, gap_mm, logo_share, text_geom)
    model = build_logo_flat(combo, thickness=thickness)
    for w in list(cache.values())[-1].warnings:  # final text width only
        if w not in warnings:
            warnings.append(w)
    model.warnings = warnings + model.warnings
    model.meta["style"] = "logo_text"
    if "connector_bar" in mounting:
        model.warnings.append("connector_bar is not applicable to logo signs.")
        mounting = [m for m in mounting if m != "connector_bar"]
    return apply_mounting(model, mounting)


def make_logo_flat(path, width_mm: float, *, oversize_policy: str = "split", text: str = "", font=None, **kwargs) -> Model:
    """Mode A from an SVG/PNG/JPG logo (one body per color, <= ``n_colors`` colors),
    optionally combined with ``text`` (needs ``font``; see ``layout``/``gap_mm``)."""
    if text:
        if font is None:
            raise ValueError("text + logo needs a font")
        return _with_policy(
            lambda w: _make_logo_text_flat(path, text, font, w, **kwargs), width_mm, oversize_policy, "width"
        )
    for k in ("layout", "gap_mm", "logo_share", "text_color", "tracking", "line_spacing", "language"):
        kwargs.pop(k, None)
    return _with_policy(lambda w: _make_logo_flat(path, w, **kwargs), width_mm, oversize_policy, "width")


def make_letters(
    text: str, font: ResolvedFont, cap_height_mm: float, *, oversize_policy: str = "split", **kwargs
) -> Model:
    """Mode B. ``oversize_policy``: "split" or "limit" (clamp the cap height)."""
    return _with_policy(
        lambda c: _make_letters(text, font, c, **kwargs), cap_height_mm, oversize_policy, "letter height"
    )
