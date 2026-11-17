"""Multi-colour 3MF export for OrcaSlicer (mm).

Layout follows what OrcaSlicer's own writer (``bbs_3mf.cpp``) produces and its reader
accepts (verified by reading the source, see DECISIONS.md):

    [Content_Types].xml, _rels/.rels
    3D/3dmodel.model                 sub-object per part (mesh) + one object per assembly
                                     unit made of <components>; <build> items
    Metadata/model_settings.config   per object: name, extruder (+ infill overrides);
                                     per <part id=sub-object id>: name, matrix, extruder;
                                     <plate> blocks with <model_instance> entries
    Metadata/project_settings.config JSON: filament_colour / filament_type /
                                     filament_settings_id (one entry per filament slot)

Each plate of a multi-plate job is positioned at Orca's plate origin
(column * 1.2 * bed_x, -row * 1.2 * bed_y), with the 250 x 250 packing centred on the
256 x 256 Centauri Carbon bed.
"""
from __future__ import annotations

import json
import math
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr
import xml.etree.ElementTree as ET

import numpy as np
import trimesh

from .split import Plate, SplitPiece, SplitResult, plate_meshes

BED_XY = (256.0, 256.0)  # Elegoo Centauri Carbon
PLATE_GAP_FACTOR = 1.2  # Orca LOGICAL_PART_PLATE_GAP = 1/5
TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "orca_project_settings.json"
TOWER_W = 40.0  # prime tower width written to the project (mm)
IDENT = "1 0 0 0 1 0 0 0 1 0 0 0"

CT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="png" ContentType="image/png"/>
 <Default Extension="json" ContentType="application/json"/>
</Types>"""

RELS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"""


@dataclass
class ObjectSpec:
    name: str
    plate: int
    pieces: list[tuple[SplitPiece, trimesh.Trimesh]]  # meshes in plate coordinates
    infill: str | None = None


def plate_origin(index: int, n_plates: int, bed: tuple[float, float] = BED_XY) -> tuple[float, float]:
    cols = max(1, math.ceil(math.sqrt(n_plates)))
    row, col = divmod(index, cols)
    return col * bed[0] * PLATE_GAP_FACTOR, -row * bed[1] * PLATE_GAP_FACTOR


def project_settings(
    colors: list[str], tower_xy: tuple[float, float] | None = None, n_plates: int = 1, infill_percent: int = 10
) -> dict:
    """Full OrcaSlicer project settings (Elegoo Centauri Carbon) sized for ``len(colors)`` filaments.

    OrcaSlicer segfaults on a project_settings.config whose filament vectors disagree in length, so
    the complete exported template is resized instead of writing a partial file.
    """
    raw = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    p = dict(raw["settings"])
    n = len(colors)
    for k in raw["per_filament"]:
        v = p.get(k)
        if isinstance(v, list) and len(v) == 1:
            p[k] = v * n
    ig = p.get("inherits_group")
    if isinstance(ig, list) and len(ig) >= 3:  # [print, filament x n, printer]: Orca warns on any other length
        p["inherits_group"] = [ig[0]] + [ig[1]] * n + [ig[-1]]
    p["filament_colour"] = [c.upper() for c in colors]
    p["filament_map"] = ["1"] * n
    p["filament_self_index"] = [str(i + 1) for i in range(n)]
    p["flush_volumes_matrix"] = ["0" if i == j else "280" for i in range(n) for j in range(n)]
    p["flush_volumes_vector"] = ["140"] * (2 * n)
    p["prime_tower_width"] = f"{TOWER_W:g}"
    if tower_xy is not None:
        # one entry per plate (plate-local coordinates)
        p["wipe_tower_x"] = [f"{tower_xy[0]:g}"] * n_plates
        p["wipe_tower_y"] = [f"{tower_xy[1]:g}"] * n_plates
    p["skirt_loops"] = "0"  # a skirt around a 245 mm letter would leave the 256 mm bed
    p["sparse_infill_density"] = f"{infill_percent}%"
    p["sparse_infill_pattern"] = "gyroid"
    return p


# Elegoo Centauri Carbon: bed_exclude_area is the 10 x 20 mm front-right corner of the 256 bed.
EXCLUDE_MM = (246.0, 0.0, 10.0, 20.0)
TOWER_DEPTH = 30.0  # kept free for the prime tower (sliced 2-colour tower: ~47 x 18 mm incl. brim)


def plate_reserved(multicolour: bool, bed: tuple[float, float] = BED_XY, pack_extent: float = 250.0):
    """(always-free rectangles, rectangles free only on multi-colour plates, tower position) in packing / bed coordinates."""
    off = ((bed[0] - pack_extent) / 2, (bed[1] - pack_extent) / 2)
    ex, ey, ew, eh = EXCLUDE_MM
    reserved = [(ex - off[0] - 1, ey - off[1] - 1, ew + 2, eh + 2)]
    mixed: list = []
    tower = None
    if multicolour:
        tw, td = TOWER_W + 8.0, TOWER_DEPTH
        tx, ty = bed[0] - 2.0 - tw, bed[1] - 2.0 - td
        mixed.append((tx - off[0], ty - off[1], bed[0] - tx, bed[1] - ty))
        tower = (tx + 4.0, ty + 4.0)
    return reserved, mixed, tower


def _fmt(v: float) -> str:
    return repr(round(float(v), 6))


def _mesh_xml(mesh: trimesh.Trimesh, offset: np.ndarray) -> str:
    v = mesh.vertices + offset
    lines = ["   <mesh>", "    <vertices>"]
    lines += [f'     <vertex x="{_fmt(x)}" y="{_fmt(y)}" z="{_fmt(z)}"/>' for x, y, z in v]
    lines += ["    </vertices>", "    <triangles>"]
    lines += [f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.faces]
    lines += ["    </triangles>", "   </mesh>"]
    return "\n".join(lines)


def build_objects(
    result: SplitResult, plates: list[Plate], infill_for: dict[str, str] | None = None
) -> list[ObjectSpec]:
    """One object per assembly unit (pieces sharing group+cell), in plate order."""
    infill_for = infill_for or {}
    objs: list[ObjectSpec] = []
    for pi, items in enumerate(plate_meshes(result, plates)):
        units: dict[tuple[str, tuple[int, int]], list] = {}
        for pc, mesh in items:
            units.setdefault((pc.group, pc.cell), []).append((pc, mesh))
        for (group, cell), pcs in units.items():
            name = group if cell == (0, 0) and len(pcs) == 1 and pcs[0][0].name == pcs[0][0].part.name else None
            if name is None:
                # group + cell suffix of the first piece, e.g. letter_01_A_p1of2 / sign_p1of2
                first = pcs[0][0].name
                part = pcs[0][0].part.name
                suffix = first[len(part):] if first.startswith(part) else ""
                name = f"{group}{suffix}"
            objs.append(ObjectSpec(name, pi, pcs, infill_for.get(group)))
    return objs


def write_3mf(
    path: str | Path,
    objects: list[ObjectSpec],
    n_plates: int,
    filament_colors: list[str],
    *,
    title: str = "Workbench",
    meta: dict | None = None,
    bed: tuple[float, float] = BED_XY,
    pack_extent: float = 250.0,
    tower_xy: tuple[float, float] | None = None,
    infill_percent: int = 10,
    settings: dict | None = None,
    plate_names: list[str] | None = None,
) -> Path:
    """Write ``objects`` (meshes already in plate coordinates) as an Orca-compatible 3MF.

    ``settings``: extra project settings (e.g. wall loops, shell layers) applied over the template;
    ``plate_names``: a name per plate (shown in Orca's plate list)."""
    path = Path(path)
    centre = ((bed[0] - pack_extent) / 2, (bed[1] - pack_extent) / 2)
    n_fil = max(len(filament_colors), max(p.part.extruder for o in objects for p, _ in o.pieces))
    colors = list(filament_colors) + ["#FFFFFF"] * (n_fil - len(filament_colors))

    sub_xml: list[str] = []
    main_xml: list[str] = []
    cfg_objects: list[str] = []
    build: list[str] = []
    plate_inst: dict[int, list[tuple[int, int]]] = {}
    next_id = 1
    sub_ids: list[list[int]] = []
    for o in objects:
        ids = []
        for _ in o.pieces:
            ids.append(next_id)
            next_id += 1
        sub_ids.append(ids)
    main_id0 = next_id

    for oi, o in enumerate(objects):
        ox, oy = plate_origin(o.plate, n_plates, bed)
        allv = np.vstack([m.vertices for _, m in o.pieces])
        lo, hi = allv.min(axis=0), allv.max(axis=0)
        # object-local frame: XY centred on the unit, z kept (bottom on the plate)
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        local = np.array([-cx, -cy, 0.0])
        gx, gy = ox + centre[0] + cx, oy + centre[1] + cy
        for (pc, mesh), sid in zip(o.pieces, sub_ids[oi]):
            sub_xml.append(f'  <object id="{sid}" type="model">\n{_mesh_xml(mesh, local)}\n  </object>')
        mid = main_id0 + oi
        comps = "\n".join(f'    <component objectid="{sid}" transform="{IDENT}"/>' for sid in sub_ids[oi])
        main_xml.append(
            f'  <object id="{mid}" name={quoteattr(o.name)} type="model">\n   <components>\n{comps}\n   </components>\n  </object>'
        )
        build.append(f' <item objectid="{mid}" transform="1 0 0 0 1 0 0 0 1 {_fmt(gx)} {_fmt(gy)} 0" printable="1"/>')
        plate_inst.setdefault(o.plate, []).append((mid, oi))

        first_ext = o.pieces[0][0].part.extruder
        c = [f'  <object id="{mid}">', f'    <metadata key="name" value={quoteattr(o.name)}/>',
             f'    <metadata key="extruder" value="{first_ext}"/>']
        if o.infill:
            c.append('    <metadata key="sparse_infill_density" value="10%"/>')
            c.append('    <metadata key="sparse_infill_pattern" value="gyroid"/>')
        for (pc, mesh), sid in zip(o.pieces, sub_ids[oi]):
            part = pc.part
            c += [
                f'    <part id="{sid}" subtype="normal_part">',
                f'      <metadata key="name" value={quoteattr(pc.name)}/>',
                f'      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>',
                f'      <metadata key="extruder" value="{part.extruder}"/>',
                '      <mesh_stat edges_fixed="0" degenerate_facets="0" facets_removed="0" facets_reversed="0" backwards_edges="0"/>',
                "    </part>",
            ]
        c.append("  </object>")
        cfg_objects.append("\n".join(c))

    plates_xml = []
    for pi in range(n_plates):
        lines = [
            "  <plate>",
            f'    <metadata key="plater_id" value="{pi + 1}"/>',
            f'    <metadata key="plater_name" value={quoteattr((plate_names or [])[pi] if pi < len(plate_names or []) else "")}/>',
            '    <metadata key="locked" value="false"/>',
        ]
        for mid, oi in plate_inst.get(pi, []):
            lines += [
                "    <model_instance>",
                f'      <metadata key="object_id" value="{mid}"/>',
                '      <metadata key="instance_id" value="0"/>',
                f'      <metadata key="identify_id" value="{1000 + oi}"/>',
                "    </model_instance>",
            ]
        lines.append("  </plate>")
        plates_xml.append("\n".join(lines))

    extra = "".join(
        f' <metadata name={quoteattr("Workbench:" + k)}>{escape(str(v))}</metadata>\n' for k, v in (meta or {}).items()
    )
    model_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02" '
        'xmlns:BambuStudio="http://schemas.bambulab.com/package/2021">\n'
        ' <metadata name="Application">BambuStudio-02.06.00.51</metadata>\n'
        ' <metadata name="OrcaSlicer">2.4.2</metadata>\n'
        ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n'
        f' <metadata name="Title">{escape(title)}</metadata>\n'
        f"{extra}"
        " <resources>\n" + "\n".join(sub_xml + main_xml) + "\n </resources>\n"
        " <build>\n" + "\n".join(build) + "\n </build>\n</model>\n"
    )
    config_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<config>\n' + "\n".join(cfg_objects + plates_xml) + "\n</config>\n"
    project = project_settings(colors, tower_xy, n_plates, infill_percent) | dict(settings or {})
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CT_XML)
        z.writestr("_rels/.rels", RELS_XML)
        z.writestr("3D/3dmodel.model", model_xml)
        z.writestr("Metadata/model_settings.config", config_xml)
        z.writestr("Metadata/project_settings.config", json.dumps(project, indent=2))
    return path


# --------------------------------------------------------------------------- #
# Reader used by tests / sanity checks
# --------------------------------------------------------------------------- #
def inspect_3mf(path: str | Path) -> dict:
    """Re-open a 3MF written by :func:`write_3mf` and summarise it."""
    ns = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        model = ET.fromstring(z.read("3D/3dmodel.model"))
        cfg = ET.fromstring(z.read("Metadata/model_settings.config"))
        proj = json.loads(z.read("Metadata/project_settings.config"))
    meshes = {}
    mains = {}
    for obj in model.findall("m:resources/m:object", ns):
        oid = int(obj.get("id"))
        mesh = obj.find("m:mesh", ns)
        if mesh is not None:
            v = np.array([[float(x.get(a)) for a in "xyz"] for x in mesh.findall("m:vertices/m:vertex", ns)])
            f = np.array([[int(t.get(a)) for a in ("v1", "v2", "v3")] for t in mesh.findall("m:triangles/m:triangle", ns)])
            meshes[oid] = trimesh.Trimesh(v, f, process=False)
        else:
            mains[oid] = [int(c.get("objectid")) for c in obj.findall("m:components/m:component", ns)]
    build = {int(i.get("objectid")): i.get("transform") for i in model.findall("m:build/m:item", ns)}
    objects = []
    for o in cfg.findall("object"):
        oid = int(o.get("id"))
        meta = {m.get("key"): m.get("value") for m in o.findall("metadata")}
        parts = []
        for p in o.findall("part"):
            pm = {m.get("key"): m.get("value") for m in p.findall("metadata")}
            sid = int(p.get("id"))
            parts.append({"id": sid, "name": pm["name"], "extruder": int(pm["extruder"]), "mesh": meshes[sid]})
        objects.append({"id": oid, "name": meta["name"], "extruder": int(meta["extruder"]), "meta": meta,
                        "parts": parts, "components": mains[oid], "transform": build[oid]})
    plates = []
    for p in cfg.findall("plate"):
        pm = {m.get("key"): m.get("value") for m in p.findall("metadata")}
        inst = [int({m.get("key"): m.get("value") for m in mi.findall("metadata")}["object_id"]) for mi in p.findall("model_instance")]
        plates.append({"id": int(pm["plater_id"]), "objects": inst})
    return {"files": names, "objects": objects, "plates": plates, "project": proj}
