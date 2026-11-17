"""The only bridge to the shared Workbench engine ``workbench_core`` (extracted from Kaligraf in S1).

Generators import geometry/text/logo/colour/prompt helpers from here, never from ``workbench_core`` or ``kaligraf``
directly, so the engine can move again (S2: Open Workbench Studio) without touching them.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import quoteattr

import numpy as np
from manifold3d import CrossSection, Manifold

from workbench_core.colorlib import PALETTE, norm_hex
from workbench_core.estimate import LAYER_H, load_printer, part_volume_split
from workbench_core.export3mf import ObjectSpec, inspect_3mf, plate_reserved, write_3mf
from workbench_core.fonts import FontError, ResolvedFont, load_registry, resolve_font
from workbench_core.geometry import (
    BED_MM,
    clean_for_extrusion,
    cylinder,
    extrude,
    from_trimesh,
    is_part_valid,
    to_trimesh,
    union_all,
)
from workbench_core.logo2d import LogoResult
from workbench_core.logo2d import load_logo as _load_logo
from workbench_core.render import AMBIENT, DIFFUSE, LIGHT, SUPERSAMPLE, Z_UP, render_meshes, view_rotation, write_glb
from workbench_core.render import _hex as hex_rgb
from workbench_core.render import _raster as raster
from workbench_core.text2d import TextResult, build_text, text_outline, thin_regions
from workbench_core import prompt as prompt_tools
from workbench_core.app import enter_work_dir, port_busy_message, port_state
from workbench_core.shapes import shape_polygon
from workbench_core import slicer as shared_slicer  # noqa: F401
from workbench_core.slicer import available as slicer_available, gcode_stats, slice_3mf  # noqa: F401
from workbench_core.vector import export_cut_paths, part_outlines  # noqa: F401
from workbench_core.webapp import Jobs, editor_app, output_links

__all__ = [
    "AMBIENT", "BED_MM", "LAYER_H", "load_printer", "part_volume_split", "DIFFUSE", "FontError", "LIGHT", "SUPERSAMPLE", "hex_rgb", "raster", "tr_warning", "tr_warnings", "LogoResult", "ResolvedFont", "TextResult", "build_text", "clean_for_extrusion", "cylinder",
    "extrude", "font_names", "from_trimesh", "is_part_valid", "load_logo", "norm_hex", "resolve_font", "text_geometry",
    "text_baselines", "Z_UP", "render_meshes", "view_rotation", "write_glb", "Jobs", "editor_app", "output_links", "shape_polygon", "PALETTE", "enter_work_dir", "port_busy_message", "port_state", "prompt_tools", "thin_regions", "to_trimesh", "twist_extrude", "union_all", "write_plates_3mf", "inspect_3mf", "plate_reserved", "export_cut_paths", "part_outlines", "slicer_available", "gcode_stats", "slice_3mf", "shared_slicer",
]


def font_names() -> list[str]:
    """Display names of the fonts in Kaligraf's registry (files may still be missing)."""
    return [s.name for s in load_registry().values()]


def text_geometry(text: str, font: str, width_mm: float | None = None, cap_height_mm: float | None = None,
                  min_feature_mm: float | None = None):
    """Text outline in mm (bbox min at 0,0) and its warnings (strokes thinner than ``min_feature_mm``, Kaligraf: 2 mm).
    Give ``width_mm`` or ``cap_height_mm`` (height of a capital H)."""
    g, w = text_outline(text, resolve_font(font), width_mm=width_mm, cap_height_mm=cap_height_mm, min_feature_mm=min_feature_mm)
    return g, tr_warnings(w)


def text_baselines(text: str, font: str, width_mm: float) -> tuple[list[float], float]:
    """Baseline y of each line (same frame as text_geometry at this width) and the cap height, in mm."""
    res = build_text(text, resolve_font(font), "flat", width_mm=width_mm, min_feature_mm=0.0)
    return list(res.line_baselines), res.cap_height_mm


# Kaligraf's warnings are English; Maker's UI is Turkish. Unknown messages pass through unchanged.
_TR = [
    (r"(\d+) feature\(s\) thinner than ([\d.]+) mm at this size \(e\.g\. near x=(-?\d+) mm, y=(-?\d+) mm\); they may print poorly or break\.",
     "{0} yerde çizgi {1} mm'den ince (ör. x={2} mm, y={3} mm civarı); kötü basılabilir ya da kırılabilir. Boyutu büyütün ya da daha kalın bir yazı tipi seçin."),
    (r"Font '(.+)' has no glyph for: (.+) \(these characters are skipped\)\.", "'{0}' yazı tipinde şu karakterler yok, atlandı: {1}"),
    (r"Font '(.+)' is (\w+)/unlicensed in the registry: make sure you hold a commercial license before selling products made with it\.",
     "'{0}' yazı tipi lisanslı değil ({1}): bu yazı tipiyle yapılan ürünü satmadan önce ticari lisans alın."),
    (r"Flat mode is designed for 1-2 lines; got (\d+) lines\.", "Düz model 1–2 satır için tasarlandı; {0} satır var."),
    (r"Letters mode supports a single line; lines were joined with a space\.", "Harf modu tek satır destekler; satırlar boşlukla birleştirildi."),
    (r"(\d+) stroke-only shape\(s\) ignored \(convert strokes to outlines in the SVG\)\.", "{0} yalnızca çizgi (stroke) olan şekil atlandı; SVG'de çizgileri dış hatta çevirin."),
    (r"White full-size background shape removed\.", "Tam boy beyaz arka plan şekli kaldırıldı."),
    (r"SVG has (\d+) distinct colors; merged to (\d+)\.", "SVG'de {0} farklı renk var; {1} renge indirildi."),
    (r"n_colors reduced from (\d+) to (\d+) \(CANVAS supports 4 filaments\)\.", "Renk sayısı {0}'dan {1}'e indirildi (CANVAS en çok 4 filament)."),
    (r"No clear background color found; using the whole image\.", "Belirgin bir arka plan rengi bulunamadı; görselin tamamı kullanıldı."),
    (r"Low resolution: image is (\d+) px wide \(< (\d+)\); edges may look rough\. Use a larger file or an SVG\.",
     "Düşük çözünürlük: görsel {0} px genişliğinde (< {1}); kenarlar pürüzlü olabilir. Daha büyük bir dosya ya da SVG kullanın."),
    (r"Color (#[0-9A-Fa-f]{6}): (\d+) thin and (\d+) tiny feature\(s\) below ([\d.]+) mm at this size; they may print poorly\.",
     "{0} renginde {3} mm altında {1} ince ve {2} küçük parça var; kötü basılabilir."),
]
_TR = [(re.compile(p), t) for p, t in _TR]


def tr_warning(msg: str) -> str:
    for rx, tmpl in _TR:
        m = rx.fullmatch(msg.strip())
        if m:
            return tmpl.format(*m.groups())
    return msg


def tr_warnings(msgs) -> list[str]:
    return [tr_warning(m) for m in msgs]


def load_logo(path, width_mm: float, n_colors: int = 4) -> LogoResult:
    """Kaligraf logo pipeline (SVG / PNG / JPG -> coloured regions in mm) with Turkish warnings."""
    res = _load_logo(path, width_mm, n_colors)
    res.warnings = tr_warnings(res.warnings)
    return res


def twist_extrude(points, z0: float, z1: float, twist_deg: float, divisions: int) -> Manifold:
    """Extrude one closed (N,2) polygon from z0 to z1 while rotating it by ``twist_deg`` (helical threads)."""
    cs = CrossSection([np.asarray(points, dtype=np.float64)])
    return Manifold.extrude(cs, z1 - z0, n_divisions=divisions, twist_degrees=twist_deg).translate((0.0, 0.0, z0))


# Per-filament overrides for a PETG slot (OrcaSlicer system profile "Elegoo PETG @ECC" and its @base parent).
PETG_SLOT = {
    "filament_type": "PETG", "filament_settings_id": "Elegoo PETG @ECC", "filament_vendor": "Elegoo",
    "nozzle_temperature": "250", "nozzle_temperature_initial_layer": "250", "nozzle_temperature_range_low": "230",
    "nozzle_temperature_range_high": "270", "hot_plate_temp": "70", "hot_plate_temp_initial_layer": "70",
    "textured_plate_temp": "70", "textured_plate_temp_initial_layer": "70", "eng_plate_temp": "70",
    "eng_plate_temp_initial_layer": "70", "cool_plate_temp": "0", "cool_plate_temp_initial_layer": "0",
    "fan_max_speed": "40", "fan_min_speed": "10", "filament_max_volumetric_speed": "11", "filament_density": "1.25",
    "pressure_advance": "0.024", "overhang_fan_threshold": "50%", "overhang_fan_speed": "90", "slow_down_layer_time": "12",
    "fan_cooling_layer_time": "30",
}


def write_plates_3mf(path, plates, filaments, *, title="Workbench Maker", meta=None, mold_names=(), tower_xy=None,
                     pauses=None, object_settings=None) -> Path:
    """OrcaSlicer project with one plate per entry of ``plates``.

    ``plates``: list of plates, each a list of (object name, pieces) with pieces = [(piece name, mesh in 250x250 plate
    coordinates, filament slot 1..n)]; an object with pieces in several slots is one multi-colour object.
    ``filaments``: list of (colour, material) per slot; PETG slots get Orca's Elegoo PETG @ECC settings and the
    project switches to the textured PEI plate (PETG is not allowed on the cool plate). Objects named in
    ``mold_names`` get 10 % gyroid infill (Kaligraf's per-object override), the rest the project's 15 %.
    ``tower_xy``: prime tower position (bed coordinates) for multi-colour plates.
    ``pauses``: {plate index: [z, ...]}: pause (M600) before printing the layer at that height, e.g. to insert an NFC tag.
    ``object_settings``: {object name: {Orca key: value}} per-object overrides (e.g. a lithophane's 100 % infill).
    """
    objects = []
    for pi, items in enumerate(plates):
        for name, pieces in items:
            specs = [(SimpleNamespace(name=pn, part=SimpleNamespace(name=pn, extruder=slot)), mesh) for pn, mesh, slot in pieces]
            objects.append(ObjectSpec(name, pi, specs, "mold" if name in mold_names else None))
    path = write_3mf(path, objects, len(plates), [c for c, _ in filaments], title=title, meta=meta, infill_percent=15,
                     tower_xy=tower_xy)
    petg = [i for i, (_, m) in enumerate(filaments) if m.upper() == "PETG"]
    if not petg and not pauses and not object_settings:
        return Path(path)
    with zipfile.ZipFile(path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    if petg:
        proj = json.loads(files["Metadata/project_settings.config"])
        for k, v in PETG_SLOT.items():
            if isinstance(proj.get(k), list) and len(proj[k]) == len(filaments):
                for i in petg:
                    proj[k][i] = v
        proj["curr_bed_type"] = "Textured PEI Plate"
        files["Metadata/project_settings.config"] = json.dumps(proj, indent=2).encode()
    if pauses:
        files["Metadata/custom_gcode_per_layer.xml"] = _pause_xml(pauses, len(filaments)).encode()
    if object_settings:
        cfg = files["Metadata/model_settings.config"].decode()
        for name, kv in object_settings.items():
            line = f'    <metadata key="name" value={quoteattr(name)}/>\n'  # object level (parts are indented deeper)
            extra = "".join(f'    <metadata key="{k}" value={quoteattr(str(v))}/>\n' for k, v in kv.items())
            cfg = cfg.replace(line, line + extra)
        files["Metadata/model_settings.config"] = cfg.encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in files.items():
            z.writestr(n, b)
    return Path(path)


def _pause_xml(pauses: dict, n_filaments: int) -> str:
    """Orca/Bambu per-layer custom G-code: type 1 = PausePrint (Orca inserts the printer's machine_pause_gcode)."""
    mode = "MultiAsSingle" if n_filaments > 1 else "SingleExtruder"
    out = ['<?xml version="1.0" encoding="utf-8"?>', "<custom_gcodes_per_layer>"]
    for pi in sorted(pauses):
        out += ["<plate>", f'<plate_info id="{pi + 1}"/>']
        out += [f'<layer top_z="{z:.2f}" type="1" extruder="1" color="" extra="" gcode="M600"/>' for z in sorted(set(pauses[pi]))]
        out += [f'<mode value="{mode}"/>', "</plate>"]
    out.append("</custom_gcodes_per_layer>")
    return "\n".join(out) + "\n"
