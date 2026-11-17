"""Functions shared by the MCP server and the CLI."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from .generators import GENERATORS, get_generator
from .sheets import load_sheets


def list_generators() -> list[dict]:
    """All Workbench - Maker generators (key, label, group, status, milestone)."""
    return [{k: g.schema()[k] for k in ("key", "label", "group", "description", "status", "milestone")} for g in GENERATORS.values()]


def generator_params(key: str) -> dict:
    """Parameter schema of one generator (type, default, range, options, Turkish label)."""
    return get_generator(key).schema()


def list_sheets() -> dict:
    """Thermoform sheet table (PETG thicknesses, clearance, forming temperature)."""
    default, sheets = load_sheets()
    return {"default": default, "sheets": [asdict(s) | {"mold_gap_mm": s.mold_gap_mm} for s in sheets.values()]}


def make(job: dict, out_root: str) -> dict:
    """Build a job {generator, name, params} and write files; returns job.json data + output folder."""
    from .job import run_job

    res = run_job(job, Path(out_root))
    return {"out_dir": str(res.out_dir.resolve()), **res.data}
