"""Job definition (YAML/dict), validation and the end-to-end pipeline.

``run_job`` -> ``output/<job_id>/`` with ``model.3mf``, ``parts/*.stl``, ``job.json`` and
``warnings.txt`` (renders, template and prompts are added by later milestones).
"""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import yaml

from . import __version__
from .estimate import estimate, format_duration, load_printer
from .export3mf import build_objects, plate_reserved, write_3mf
from .fonts import DEFAULT_FONTS_DIR, resolve_font
from .geometry import (
    BED_MM,
    RECOMMENDED_INFILL,
    Model,
    make_flat,
    make_letters,
    make_logo_flat,
)
from .mounting import normalize_mounting
from .split import SplitResult, pack_plates, split_model

COLOR_NAMES = {
    "siyah": "#222222", "black": "#222222",
    "beyaz": "#F5F5F5", "white": "#F5F5F5",
    "kırmızı": "#C0392B", "kirmizi": "#C0392B", "red": "#C0392B",
    "mavi": "#2980B9", "blue": "#2980B9",
    "yeşil": "#27AE60", "yesil": "#27AE60", "green": "#27AE60",
    "sarı": "#F1C40F", "sari": "#F1C40F", "yellow": "#F1C40F",
    "turuncu": "#E67E22", "orange": "#E67E22",
    "mor": "#8E44AD", "purple": "#8E44AD",
    "pembe": "#E84393", "pink": "#E84393",
    "gri": "#7F8C8D", "gray": "#7F8C8D", "grey": "#7F8C8D",
    "altın": "#D4AF37", "altin": "#D4AF37", "gold": "#D4AF37",
    "gümüş": "#C0C0C0", "gumus": "#C0C0C0", "silver": "#C0C0C0",
    "kahverengi": "#6D4C41", "brown": "#6D4C41",
}


def resolve_color(c: str) -> str:
    s = str(c).strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", s):
        return s.upper()
    key = s.lower()
    if key in COLOR_NAMES:
        return COLOR_NAMES[key]
    raise ValueError(f"unknown color {c!r}: use #RRGGBB or one of {', '.join(sorted(set(COLOR_NAMES)))}")


@dataclass
class Job:
    mode: str  # "flat" | "letters"
    text: str = ""
    font: str = "Montserrat"
    logo: str | None = None
    job_id: str | None = None
    # flat
    width_cm: float | None = None
    thickness_mm: float = 5
    color_style: str = "single"  # single | two_tone | backplate
    colors: list[str] = field(default_factory=list)
    plate_offset_mm: float = 6.0
    n_colors: int = 4
    split_letters: bool = False  # flat mode: build and export one STL/part per letter
    stroke_offset_mm: float = 0.0  # >0 boldens/thickens letter strokes, <0 thins them
    # letters
    letter_height_cm: float | None = None
    letter_width_mm: float | None = None  # widest letter width (X); None/0 = font proportions
    fit_letter_box: bool = False  # True: letter_height_cm = tallest letter (not cap height) -> each letter <= W x H x D
    depth_mm: float = 30
    face_color: str | None = None
    letter_colors: list[str] = field(default_factory=list)
    open_back_shell: bool = False
    letter_joints: str = "puzzle"  # joined (script) words: "puzzle" = one part per letter with jigsaw locks, "none" = one part
    # shared
    mounting: list[str] = field(default_factory=lambda: ["tape"])
    tracking: float = 0.0
    line_spacing: float = 1.0
    language: str | None = None  # BCP 47 for OpenType locl forms, e.g. "tr" (dotted small-cap i)
    oversize_policy: str = "split"
    infill_percent: float | None = None  # default: 10 (letters) / 15 (flat)
    printer_profile: str | None = None  # path to a printer.yaml (default: repo printer.yaml)
    keyhole_boss: bool = False  # backplate signs: glued Ø30 boss carrying the keyhole
    logo_layout: str = "logo_above"  # logo + text: logo_above | logo_left
    logo_gap_mm: float = 10.0
    logo_share: float = 0.5  # logo_above: logo width as a fraction of the sign width
    finishes: dict = field(default_factory=dict)  # colour (name/#HEX) -> surface: mat/parlak/ipek/ahşap/mermer/simli (render-only)

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        known = set(cls.__dataclass_fields__)
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"unknown job field(s): {', '.join(sorted(unknown))}")
        job = cls(**d)
        job.validate()
        return job

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Job":
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        job = cls.from_dict(data)
        if job.logo and not Path(job.logo).is_absolute():
            job.logo = str((Path(path).resolve().parent / job.logo))
        return job

    def validate(self) -> None:
        if self.mode not in ("flat", "letters"):
            raise ValueError("mode must be 'flat' or 'letters'")
        if self.oversize_policy not in ("split", "limit"):
            raise ValueError("oversize_policy must be 'split' or 'limit'")
        normalize_mounting(self.mounting)
        from .colorlib import norm_finish

        for k, v in self.finishes.items():
            resolve_color(k)
            norm_finish(v)
        if not -2.0 <= float(self.stroke_offset_mm) <= 10.0:
            raise ValueError("stroke_offset_mm must be between -2 and 10")
        if self.mode == "flat":
            if not self.text and not self.logo:
                raise ValueError("flat mode needs text and/or logo")
            if self.logo_layout not in ("logo_above", "logo_left"):
                raise ValueError("logo_layout must be logo_above or logo_left")
            if not 0.1 <= self.logo_share <= 1.0:
                raise ValueError("logo_share must be between 0.1 and 1.0")
            if not self.width_cm or self.width_cm <= 0:
                raise ValueError("flat mode needs width_cm > 0")
            if not (1.0 <= float(self.thickness_mm) <= 250.0):
                raise ValueError("thickness_mm must be between 1 and 250")
            if self.color_style not in ("single", "two_tone", "backplate"):
                raise ValueError("color_style must be single, two_tone or backplate")
            if self.logo and self.color_style != "single":
                raise ValueError("logo jobs use one body per color; leave color_style as 'single'")
            if self.keyhole_boss and self.color_style != "backplate":
                raise ValueError("keyhole_boss is for color_style 'backplate'")
        else:
            if not self.text:
                raise ValueError("letters mode needs text")
            if not self.letter_height_cm or not 2 <= self.letter_height_cm <= 40:
                raise ValueError("letters mode needs letter_height_cm between 2 and 40")
            if self.letter_width_mm and not 5.0 <= float(self.letter_width_mm) <= 250.0:
                raise ValueError("letter_width_mm must be between 5 and 250 (0 = font proportions)")
            if not (2.0 <= float(self.depth_mm) <= 250.0):
                raise ValueError("depth_mm must be between 2 and 250")
            if self.logo:
                raise ValueError("letters mode does not take a logo")

    @property
    def slug(self) -> str:
        if self.job_id:
            return self.job_id
        base = self.text or (Path(self.logo).stem if self.logo else "job")
        base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
        base = re.sub(r"[^A-Za-z0-9]+", "-", base).strip("-").lower() or "job"
        size = f"{self.width_cm:g}cm" if self.mode == "flat" else f"{self.letter_height_cm:g}cm"
        return f"{base[:30]}_{self.mode}_{size}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class JobResult:
    job: Job
    out_dir: Path
    model: Model
    split: SplitResult
    data: dict
    files: dict[str, Path]


def _py(o):
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"not JSON serialisable: {type(o)}")


def build_model(job: Job, fonts_dir: Path | str = DEFAULT_FONTS_DIR) -> Model:
    """Job -> Model (bodies + mounting), honouring oversize_policy."""
    common = dict(oversize_policy=job.oversize_policy, mounting=job.mounting)
    if job.mode == "flat" and job.logo:
        extra = {}
        if job.text:
            extra = dict(
                text=job.text, font=resolve_font(job.font, fonts_dir), layout=job.logo_layout,
                gap_mm=job.logo_gap_mm, logo_share=job.logo_share, tracking=job.tracking,
                line_spacing=job.line_spacing, language=job.language,
            )
            if job.colors:
                extra["text_color"] = resolve_color(job.colors[0])
        return make_logo_flat(
            job.logo, job.width_cm * 10, thickness=job.thickness_mm, n_colors=job.n_colors, **extra, **common
        )
    font = resolve_font(job.font, fonts_dir)
    if job.mode == "flat":
        cols = [resolve_color(c) for c in job.colors] or None
        return make_flat(
            job.text, font, job.width_cm * 10, thickness=job.thickness_mm, style=job.color_style,
            colors=cols, plate_offset=job.plate_offset_mm, tracking=job.tracking,
            line_spacing=job.line_spacing, keyhole_boss=job.keyhole_boss, language=job.language,
            split_letters=job.split_letters, stroke_offset_mm=job.stroke_offset_mm, **common,
        )
    return make_letters(
        job.text, font, job.letter_height_cm * 10, depth=job.depth_mm, tracking=job.tracking, language=job.language,
        letter_width_mm=job.letter_width_mm or None, fit_box=job.fit_letter_box,
        colors=[resolve_color(c) for c in job.letter_colors] or None,
        face_color=resolve_color(job.face_color) if job.face_color else None,
        open_back_shell=job.open_back_shell, joints=job.letter_joints,
        stroke_offset_mm=job.stroke_offset_mm, **common,
    )


def color_descriptors(job: Job, model: Model) -> dict[str, dict]:
    """hex -> universal colour code + finish for every colour of the model."""
    from .colorlib import descriptor

    fin = {resolve_color(k): v for k, v in job.finishes.items()}
    return {c: descriptor(c, fin.get(c)) for c in model.colors}


def _overall(model: Model) -> dict:
    lo = np.min([p.mesh_wall.bounds[0] for p in model.parts], axis=0)
    hi = np.max([p.mesh_wall.bounds[1] for p in model.parts], axis=0)
    d = hi - lo
    out = {"width_mm": round(float(d[0]), 2), "height_mm": round(float(d[1]), 2), "depth_mm": round(float(d[2]), 2)}
    if model.layout is not None and model.mode == "letters":
        out["cap_height_mm"] = round(model.layout.cap_height_mm, 2)
    return out


def run_job(
    job: Job,
    out_root: str | Path = "output",
    fonts_dir: Path | str = DEFAULT_FONTS_DIR,
    *,
    prompt_fields: dict[str, str] | None = None,
    extras: bool = True,
) -> JobResult:
    """Build everything for ``job`` into ``out_root/<job id>/``.

    ``extras`` adds renders, dims.png, template.pdf and the AI prompts (``prompt_fields`` are the
    user-filled prompt form values, see :mod:`kaligraf.prompt`).
    """
    model = build_model(job, fonts_dir)
    result = split_model(model)
    n_fil = max(p.extruder for p in model.parts)
    reserved, mixed_reserved, tower_xy = plate_reserved(n_fil > 1)
    plates = pack_plates(result.pieces, reserved=reserved, mixed_reserved=mixed_reserved)
    infill = (job.infill_percent if job.infill_percent is not None else (10 if job.mode == "letters" else 15)) / 100
    est = estimate(result, plates, infill, load_printer(job.printer_profile))

    descriptors = color_descriptors(job, model)
    for p in model.parts:
        p.meta["finish"] = descriptors[p.color]["finish"]

    out = Path(out_root) / job.slug
    parts_dir = out / "parts"
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir(parents=True, exist_ok=True)

    # STL: print orientation, each piece moved to the origin
    stl_files = []
    for pc in result.pieces:
        m = pc.mesh.copy()
        m.apply_translation(-m.bounds[0])
        p = parts_dir / f"{pc.name}.stl"
        m.export(p)
        stl_files.append(p)

    infill_for = {pc.group: RECOMMENDED_INFILL for pc in result.pieces if job.mode == "letters" and pc.part.role.startswith("letter")}
    objects = build_objects(result, plates, infill_for)
    colors = model.colors
    path3mf = write_3mf(
        out / "model.3mf", objects, len(plates), colors, title=job.slug, tower_xy=tower_xy, infill_percent=int(round(infill * 100)),
        meta={"generator": f"kaligraf {__version__}", "recommended_infill": RECOMMENDED_INFILL if job.mode == "letters" else f"{int(infill * 100)}%"},
    )

    warnings: list[str] = []
    fmetrics = {}
    if job.text:
        from .fontinfo import load_metrics, size_warnings

        spec_id = resolve_font(job.font, fonts_dir).spec.id
        fmetrics = load_metrics(fonts_dir).get(spec_id)
        if job.mode == "flat":
            cap = model.layout.cap_height_mm / 10 if model.layout is not None else None  # width -> resulting cap height
        else:
            cap = model.layout.cap_height_mm / 10 if model.layout is not None else job.letter_height_cm
        if cap:
            model.warnings.extend(size_warnings(fmetrics, job.mode, cap))
    for w in [*model.warnings, *result.warnings]:
        if w not in warnings:
            warnings.append(w)
    ext_of = {}
    for p in model.parts:
        ext_of[p.color] = p.extruder
    plate_of = {}
    for pl in plates:
        for placement in pl.placements:
            plate_of[placement.unit] = pl.index + 1
    meta = model.meta
    data = {
        "job_id": job.slug,
        "tool_version": __version__,
        "inputs": job.to_dict(),
        "overall_mm": _overall(model),
        "mode": model.mode,
        "joints": meta.get("joints", []),  # script letters: where they were cut apart and whether a jigsaw lock holds them
        "colors": [{"extruder": ext_of[c], **descriptors[c]} for c in colors],
        "parts": [
            {
                "name": p.name, "role": p.role, "color": p.color, "extruder": p.extruder,
                "size_mm": [round(float(v), 2) for v in p.mesh.extents],
                "volume_cm3": round(float(p.mesh.volume) / 1000, 2),
                "detached_pieces": p.meta.get("detached_pieces", []),
            }
            for p in model.parts
        ],
        "pieces": [
            {
                "name": pc.name, "part": pc.part.name, "plate": plate_of[(pc.group, *pc.cell)],
                "size_mm": [round(float(v), 2) for v in pc.mesh.extents],
            }
            for pc in result.pieces
        ],
        "plates": len(plates),
        "oversize": {
            "policy": meta.get("oversize_policy"),
            "size_requested_mm": meta.get("size_requested_mm"),
            "size_applied_mm": meta.get("size_applied_mm"),
            "max_no_split_size_mm": round(float(meta.get("max_no_split_size_mm", 0)), 1),
            "split": bool(result.cuts),
        },
        "splitting": {"cuts": result.cuts, "pins": result.pins,
                      "pin_pieces": {"count": len(result.pins), "diameter_mm": 3.0, "length_mm": 20.0}},
        "mounting": meta.get("mounting"),
        "recommended_infill": RECOMMENDED_INFILL if job.mode == "letters" else f"{int(infill * 100)}%",
        "filament_grams": {"by_color": est.grams_by_color, "total": est.grams_total, "by_part": est.grams_by_part},
        "estimated_print_time": {
            "seconds": round(est.time_s), "text": format_duration(est.time_s),
            "per_plate_seconds": [round(t) for t in est.time_by_plate_s],
            "colour_changes": est.colour_changes, "assumptions": est.assumptions,
        },
        "warnings": warnings,
    }
    files = {"3mf": path3mf, "parts": parts_dir}
    if extras:
        from .prompt import build_prompts, write_prompts
        from .render import render_dims, render_views
        from .template_pdf import write_template_pdf

        views = render_views(model, out)
        files["render_front"], files["render_34"] = views["front"], views["34"]
        files["dims"] = render_dims(model, out / "dims.png", data["overall_mm"])
        tinfo = write_template_pdf(model, out / "template.pdf", result.cuts, job.slug)
        files["template"] = out / "template.pdf"
        from workbench_core.vector import export_cut_paths, part_outlines

        cut = export_cut_paths(part_outlines(model.parts, mesh=lambda p: p.mesh_wall), out, title=job.text)
        files["cut_svg"], files["cut_dxf"] = cut["svg"], cut["dxf"]
        data["template"] = {"pages": tinfo["pages"], "tiles": list(tinfo["tiles"]), "orientation": tinfo["orientation"]}
        prompts = build_prompts(job, data, model, prompt_fields)
        pp = write_prompts(prompts, out)
        files["prompt_tr"], files["prompt_en"] = pp["tr"], pp["en"]
        data["prompts"] = prompts
    jpath = out / "job.json"
    jpath.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=_py), encoding="utf-8")
    wpath = out / "warnings.txt"
    wpath.write_text("\n".join(warnings) + ("\n" if warnings else ""), encoding="utf-8")
    files.update({"job": jpath, "warnings": wpath})
    return JobResult(job, out, model, result, data, files)
