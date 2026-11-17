"""Rough filament / time / TRY estimates (Kaligraf's shell + infill model, Maker's own price table ``costs.yaml``)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from . import core

DEFAULT_FILE = Path(__file__).with_name("costs.yaml")
USER_FILE = Path(os.environ.get("MAKER_COSTS", Path.home() / ".config/workbench-maker/costs.yaml"))


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def costs() -> dict:
    base = dict(_load(str(DEFAULT_FILE)))
    if USER_FILE.is_file():
        for k, v in _load(str(USER_FILE)).items():
            base[k] = {**base.get(k, {}), **v} if isinstance(v, dict) else v
    return base


@dataclass
class PartEstimate:
    grams: float
    minutes: float
    try_: float


def part_estimate(mesh, material: str, role: str = "part") -> PartEstimate:
    c = costs()
    infill = float(c["infill"].get(role, 0.15))
    _, eff_mm3 = core.part_volume_split(mesh, infill)
    grams = eff_mm3 / 1000 * float(c["density_g_cm3"].get(material, 1.24))
    pr = core.load_printer()
    layers = mesh.extents[2] / core.LAYER_H
    minutes = (eff_mm3 / pr.flow_mm3_s + layers * pr.layer_overhead_s) / 60
    cal = c.get("calibration", {}).get(role, {})
    grams *= float(cal.get("grams", 1.0))
    minutes *= float(cal.get("minutes", 1.0))
    return PartEstimate(round(grams, 1), round(minutes), round(grams / 1000 * float(c["filament_try_kg"].get(material, 0)), 1))


def sheet_try(sheet_id: str, w_mm: float, h_mm: float) -> float | None:
    price = costs().get("sheet_try_m2", {}).get(sheet_id)
    return None if price is None else round(float(price) * w_mm * h_mm / 1e6, 1)
