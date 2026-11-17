"""Job files: dispatch on ``design`` (G2: rect; round G3; contour G4) and write all outputs."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

import yaml

from . import __version__
from .bom import build_bom, write_bom_csv
from .export import write_model_files
from .hardware import default_hardware


def _slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower() or "glow"


def _py(o):
    import numpy as np

    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    raise TypeError(f"not serialisable: {type(o)}")


def _build(design: str, raw: dict):
    if design == "rect":
        from .rect import RectSpec, build_rect

        return RectSpec.from_dict(raw), build_rect
    if design == "round":
        from .round import RoundSpec, build_round

        return RoundSpec.from_dict(raw), build_round
    if design == "contour":
        from .contour import ContourSpec, build_contour

        return ContourSpec.from_dict(raw), build_contour
    raise ValueError(f"unknown design {design!r}: use round | rect | contour")


def run_box(design: str, raw: dict, out_root: str | Path = "output", hw=None, prompt_user: dict | None = None, renders: bool = True) -> dict:
    spec, builder = _build(design, raw)
    hw = hw or default_hardware()
    box = builder(spec, hw)
    model = box.model
    stem = spec.text or Path(spec.logo or "logo").stem
    size = {"rect": f"{getattr(spec, 'width_mm', 0) / 10:g}cm", "round": f"{getattr(spec, 'diameter_mm', 0) / 10:g}cm",
            "contour": f"{getattr(spec, 'width_mm', 0) / 10:g}cm"}[design]
    slug = spec.job_id or _slug(f"{design}_{stem}_{size}")
    out = Path(out_root) / slug
    files = write_model_files(model, out, slug)
    from workbench_core.vector import export_cut_paths, part_outlines

    from shapely.geometry import MultiLineString

    led = ("LED_yolu", "#FF8A1F", MultiLineString(list(box.path.strip_lines())))
    outlines = part_outlines(model.parts, mesh=lambda p: p.mesh_wall)
    cut = export_cut_paths(outlines + [led], out, title=stem)
    files["cut_svg"], files["cut_dxf"] = cut["svg"], cut["dxf"]
    body = [it for it in outlines if it[2].area == max(o[2].area for o in outlines)][:1]  # the outer outline as reference
    led_files = export_cut_paths(body + [led], out, stem="led_yolu", title=f"{stem} - LED yolu")
    files["led_svg"], files["led_dxf"] = led_files["svg"], led_files["dxf"]
    warnings = list(dict.fromkeys([*model.warnings, *files["split_warnings"]]))
    est = files["estimate"]
    bom = build_bom(hw, model.meta, est.grams_by_color)
    write_bom_csv(bom, out / "bom.csv")
    meta = {k: v for k, v in model.meta.items() if k != "polys"}
    data = {"job_id": slug, "tool_version": __version__, "inputs": raw, "overall_mm": {
                "width_mm": model.width_mm, "height_mm": model.height_mm, "depth_mm": model.depth_mm},
            "parts": [{"name": p.name, "color": p.color, "extruder": p.extruder,
                       "size_mm": [round(float(v), 2) for v in p.mesh.extents]} for p in model.parts],
            "plates": files["plates"],
            "print": {"grams_total": est.grams_total, "grams_by_color": est.grams_by_color, "time_h": round(est.time_h, 2),
                      "time_by_plate_s": [round(t) for t in est.time_by_plate_s], "colour_changes": est.colour_changes},
            "power": model.meta["power"], "bom": bom, "files": {k: str(v) for k, v in files.items() if k in ("3mf", "parts", "cut_svg", "cut_dxf", "led_svg", "led_dxf")}, "meta": meta, "checks": box.report, "warnings": warnings}
    if renders:
        from .assembly import build_pdf
        from .prompt import build_prompts, write_prompts
        from .renders import write_renders

        rf = write_renders(box, out)
        from .preview import render_preview

        rf["preview"] = render_preview(box, out / "preview.png")
        data["files"].update({k: str(v) for k, v in rf.items()})
        data["files"]["assembly_pdf"] = str(build_pdf(box, data, rf, out / "assembly_tr.pdf", hw))
        prompts = build_prompts(data, prompt_user)
        write_prompts(prompts, out)
        data["prompts"] = prompts
        data["files"]["prompt_tr"], data["files"]["prompt_en"] = str(out / "prompt_tr.txt"), str(out / "prompt_en.txt")
    (out / "job.json").write_text(json.dumps(data, indent=2, ensure_ascii=False, default=_py), encoding="utf-8")
    (out / "warnings.txt").write_text("\n".join(warnings) + ("\n" if warnings else ""), encoding="utf-8")
    return {"out_dir": out, "box": box, "files": files, "data": data, "warnings": warnings}


def run_rect(raw: dict, out_root: str | Path = "output") -> dict:
    return run_box("rect", raw, out_root)


def run_job_file(path: str | Path, out_root: str | Path = "output", **kw) -> dict:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return run_box(raw.get("design"), raw, out_root, **kw)
