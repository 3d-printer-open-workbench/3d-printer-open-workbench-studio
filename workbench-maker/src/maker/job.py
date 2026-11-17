"""Run a generator and write its outputs: parts/*.stl, preview.glb, model.3mf (plates), renders/*.png, montaj.pdf,
levha_sablonu.pdf (thermoform), prompt_tr.txt / prompt_en.txt (AI image prompt), job.json, notes.txt, warnings.txt;
optionally sliced G-code (OrcaSlicer CLI)."""
from __future__ import annotations

import json
import re
import subprocess
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from . import __version__, core, docs, plates, prompt, slicer
from .generators import BuildResult, get_generator


@dataclass
class JobResult:
    out_dir: Path
    files: dict[str, Path]
    data: dict


def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s.replace("ı", "i").replace("İ", "I")).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9_-]+", "_", s).strip("_") or "is"


def load_job(path: Path | str) -> dict:
    d = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if "generator" not in d:
        raise ValueError("iş dosyasında 'generator' alanı yok")
    return d


def build(job: dict) -> tuple[BuildResult, dict]:
    gen = get_generator(job["generator"])
    values = gen.values(job.get("params"))
    res = gen.run(values)
    for p in res.parts:
        if not core.is_part_valid(p.mesh):
            raise RuntimeError(f"{p.label}: geometri bozuk (su geçirmez değil)")
        ext = p.mesh.extents
        if p.printable and (ext[0] > core.BED_MM or ext[1] > core.BED_MM):
            res.warnings.append(f"{p.label} tablaya sığmıyor ({ext[0]:.0f} x {ext[1]:.0f} mm > {core.BED_MM:.0f})")
    return res, values


def preview_glb(res: BuildResult, path: Path, gap: float = 0.0) -> Path:
    """Assembled preview (prefers assembled product preview parts if present) as a binary glTF."""
    parts = [p for p in res.parts if p.meta.get("product")] or res.parts
    return core.write_glb([(p.mesh, p.color, p.name) for p in parts], path)


def write_renders(res: BuildResult, out: Path) -> dict[str, Path]:
    from .render import render_parts

    (out / "renders").mkdir(parents=True, exist_ok=True)
    product = [p for p in res.parts if p.meta.get("product")] or [p for p in res.parts if p.printable]
    bed_parts = [p for p in res.parts if not (p.meta.get("product") and not p.printable)]
    files = {"render_product": out / "renders" / "urun.png", "render_parts": out / "renders" / "parcalar.png"}
    render_parts(product, width_px=1200, elev=35).save(files["render_product"])
    render_parts(bed_parts, width_px=1400).save(files["render_parts"])
    return files


def run_job(job: dict, out_root: Path | str = "output") -> JobResult:
    """``job['slice']`` (bool): also slice model.3mf with OrcaSlicer into gcode/ (real grams and time per plate)."""
    res, values = build(job)
    name = slug(job.get("name") or job["generator"])
    out = Path(out_root) / name
    (out / "parts").mkdir(parents=True, exist_ok=True)
    files: dict[str, Path] = {}
    parts = []
    for p in res.parts:
        if not p.printable:
            continue
        m = p.mesh.copy()
        m.apply_translation(-m.bounds[0])
        f = out / "parts" / f"{name}_{p.name}.stl"
        m.export(f)
        x, y, z = (round(float(e), 1) for e in p.mesh.extents)
        parts.append({"name": p.name, "label": p.label, "color": p.color, "material": p.material,
                      "size_mm": [x, y, z], "volume_cm3": round(float(p.mesh.volume) / 1000, 2), "stl": f.name, **p.meta})
    files["preview"] = preview_glb(res, out / "preview.glb")
    cut = core.export_cut_paths(core.part_outlines([p for p in res.parts if p.printable]), out,
                                title=job.get("name") or job["generator"])
    files["cut_svg"], files["cut_dxf"] = cut["svg"], cut["dxf"]
    files |= write_renders(res, out)
    title = job.get("name") or get_generator(job["generator"]).label
    plate_list = plates.write_3mf(res.parts, out / "model.3mf", title=title)
    files["3mf"] = out / "model.3mf"
    plate_info = [{"material": pl.material, "objects": [n for n, _ in pl.items]} for pl in plate_list]
    if job.get("slice"):
        try:
            for info, st in zip(plate_info, slicer.slice_3mf(files["3mf"], out / "gcode")):
                info |= st
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            res.warnings.append(f"Dilimleme yapılamadı: {e}")
    if res.sheet is not None:
        files["sheet_pdf"] = out / "levha_sablonu.pdf"
        res.meta["sheet_template"] = docs.write_sheet_pdf(res.sheet, files["sheet_pdf"])
    lo = np.min([p.mesh.bounds[0] for p in res.parts], axis=0)
    hi = np.max([p.mesh.bounds[1] for p in res.parts], axis=0)
    data = {"app": "workbench-maker", "version": __version__, "name": name, "generator": job["generator"], "params": values,
            "overall_mm": [round(float(v), 1) for v in hi - lo], "parts": parts, "warnings": res.warnings, "notes": res.notes, "meta": res.meta, "plates": plate_info}
    data["prompts"] = prompt.build_prompts(job["generator"], values, res, data, job.get("prompt"))
    for lang, f in prompt.write_prompts(data["prompts"], out).items():
        files[f"prompt_{lang}"] = f
    files["assembly_pdf"] = docs.write_assembly_pdf(res, data, out / "montaj.pdf", files["render_product"], title, plate_info)
    data["files"] = {k: str(Path(v).relative_to(out)) for k, v in files.items()}
    (out / "job.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "notes.txt").write_text("\n".join(res.notes) + ("\n" if res.notes else ""), encoding="utf-8")
    (out / "warnings.txt").write_text("\n".join(res.warnings) + ("\n" if res.warnings else ""), encoding="utf-8")
    files["job"] = out / "job.json"
    files["warnings"] = out / "warnings.txt"
    return JobResult(out, files, data)
