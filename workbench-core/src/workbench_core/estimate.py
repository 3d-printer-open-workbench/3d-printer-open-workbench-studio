"""Filament and print-time estimates (rough, documented assumptions).

Filament (PLA, 1.24 g/cm3), infill-aware:
    shell  = surface area * thickness, where thickness is WALL_MM for steep faces
             (3 loops x 0.42 mm) and TOPBOT_MM for near-horizontal faces
             (5 layers x 0.2 mm); capped at the part volume
    interior = volume - shell, printed at ``infill`` (fraction)
    grams  = (shell + interior * infill) * density
Thin parts therefore come out (nearly) solid, big hollow-ish letters scale with infill.

Time (volumetric-flow model, deliberately conservative):
    t = extruded_volume / FLOW_MM3_S          # effective average, incl. accel/travel losses
      + layers * LAYER_OVERHEAD_S             # layer change, travel, z-hop
      + colour_changes * CHANGE_S             # CANVAS swap + purge
      + PLATE_SETUP_S                         # heat-up, bed levelling, first-layer slow-down
Colour changes per plate = sum over layers of (active filaments - 1) plus one for every
layer whose set of active filaments differs from the previous layer.
These are order-of-magnitude figures (typically +-30%), not slicer output.
"""
from __future__ import annotations

import math
from pathlib import Path
from dataclasses import dataclass, field

import numpy as np
import trimesh
import yaml

from .split import Plate, SplitPiece, SplitResult, plate_meshes

DENSITY_G_CM3 = 1.24
WALL_MM = 3 * 0.42
TOPBOT_MM = 5 * 0.2
LAYER_H = 0.2
FLOW_MM3_S = 9.0
LAYER_OVERHEAD_S = 2.5
CHANGE_S = 40.0
PLATE_SETUP_S = 360.0

@dataclass(frozen=True)
class PrinterProfile:
    """Calibration knobs for the time model (``printer.yaml``)."""

    flow_mm3_s: float = FLOW_MM3_S
    colour_change_s: float = CHANGE_S
    layer_overhead_s: float = LAYER_OVERHEAD_S
    plate_setup_s: float = PLATE_SETUP_S


DEFAULT_PRINTER_FILE = Path(__file__).resolve().parents[2] / "printer.yaml"


def load_printer(path: str | Path | None = None) -> PrinterProfile:
    """Load ``printer.yaml`` (defaults if the file is missing). Unknown keys are an error."""
    p = Path(path) if path else DEFAULT_PRINTER_FILE
    if not p.exists():
        if path:
            raise FileNotFoundError(f"printer profile not found: {p}")
        return PrinterProfile()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    unknown = set(data) - set(PrinterProfile.__dataclass_fields__)
    if unknown:
        raise ValueError(f"unknown printer.yaml key(s): {', '.join(sorted(unknown))}")
    prof = PrinterProfile(**{k: float(v) for k, v in data.items()})
    if prof.flow_mm3_s <= 0 or prof.colour_change_s < 0:
        raise ValueError("printer.yaml: flow_mm3_s must be > 0 and colour_change_s >= 0")
    return prof


ASSUMPTIONS = {
    "density_g_cm3": DENSITY_G_CM3,
    "wall_mm": WALL_MM,
    "top_bottom_mm": TOPBOT_MM,
    "layer_height_mm": LAYER_H,
    "effective_flow_mm3_s": FLOW_MM3_S,
    "layer_overhead_s": LAYER_OVERHEAD_S,
    "colour_change_s": CHANGE_S,
    "plate_setup_s": PLATE_SETUP_S,
}


@dataclass
class Estimate:
    grams_by_color: dict[str, float]
    grams_by_part: dict[str, float]
    grams_total: float
    time_s: float
    time_by_plate_s: list[float]
    colour_changes: int
    assumptions: dict = field(default_factory=lambda: dict(ASSUMPTIONS))

    @property
    def time_h(self) -> float:
        return self.time_s / 3600.0


def part_volume_split(mesh: trimesh.Trimesh, infill: float) -> tuple[float, float]:
    """(solid_shell_mm3, effective_extruded_mm3) for one mesh."""
    vol = float(mesh.volume)
    if vol <= 0:
        return 0.0, 0.0
    n = mesh.face_normals
    horizontal = np.abs(n[:, 2]) > 0.7
    area = mesh.area_faces
    shell = float(area[horizontal].sum() * TOPBOT_MM + area[~horizontal].sum() * WALL_MM)
    shell = min(shell, vol)
    return shell, shell + (vol - shell) * infill


def part_grams(mesh: trimesh.Trimesh, infill: float) -> float:
    _, eff = part_volume_split(mesh, infill)
    return eff / 1000.0 * DENSITY_G_CM3


def estimate_pieces(pieces: list[SplitPiece], infill: float) -> tuple[dict[str, float], dict[str, float]]:
    by_color: dict[str, float] = {}
    by_part: dict[str, float] = {}
    for pc in pieces:
        g = part_grams(pc.mesh, infill)
        by_color[pc.part.color] = by_color.get(pc.part.color, 0.0) + g
        by_part[pc.name] = g
    return by_color, by_part


def plate_time(
    items: list[tuple[SplitPiece, trimesh.Trimesh]], infill: float, printer: PrinterProfile | None = None
) -> tuple[float, int]:
    return slot_plate_time([(pc.part.extruder, m) for pc, m in items], infill, printer)


def slot_plate_time(items: list[tuple[int, trimesh.Trimesh]], infill: float, printer: PrinterProfile | None = None) -> tuple[float, int]:
    """(seconds, colour changes) for one plate of (filament slot, mesh in plate coordinates)."""
    printer = printer or PrinterProfile()
    vol = sum(part_volume_split(m, infill)[1] for _, m in items)
    ztop = max(m.bounds[1][2] for _, m in items)
    layers = max(1, math.ceil(ztop / LAYER_H - 1e-6))
    changes = 0
    prev: frozenset[int] | None = None
    for k in range(layers):
        z = (k + 0.5) * LAYER_H
        active = frozenset(e for e, m in items if m.bounds[0][2] - 1e-6 <= z < m.bounds[1][2] + 1e-6)
        if not active:
            continue
        changes += len(active) - 1
        if prev is not None and active != prev:
            changes += 1
        prev = active
    t = vol / printer.flow_mm3_s + layers * printer.layer_overhead_s + changes * printer.colour_change_s + printer.plate_setup_s
    return t, changes


def estimate_slots(plates: list[list[tuple[int, trimesh.Trimesh]]], infill: float, printer: PrinterProfile | None = None) -> dict:
    """Grams per filament slot, seconds per plate and colour changes for plates of (slot, mesh)."""
    printer = printer or load_printer()
    grams: dict[int, float] = {}
    times, changes = [], 0
    for items in plates:
        for e, m in items:
            grams[e] = grams.get(e, 0.0) + part_grams(m, infill)
        t, c = slot_plate_time(items, infill, printer)
        times.append(t)
        changes += c
    return {"grams_by_slot": grams, "time_by_plate_s": times, "time_s": sum(times), "colour_changes": changes}


def estimate(
    result: SplitResult, plates: list[Plate], infill: float, printer: PrinterProfile | None = None
) -> Estimate:
    printer = printer or load_printer()
    by_color, by_part = estimate_pieces(result.pieces, infill)
    times, changes = [], 0
    for items in plate_meshes(result, plates):
        t, c = plate_time(items, infill, printer)
        times.append(t)
        changes += c
    return Estimate(
        grams_by_color={k: round(v, 1) for k, v in by_color.items()},
        grams_by_part={k: round(v, 1) for k, v in by_part.items()},
        grams_total=round(sum(by_color.values()), 1),
        time_s=sum(times),
        time_by_plate_s=times,
        colour_changes=changes,
        assumptions={**ASSUMPTIONS, "effective_flow_mm3_s": printer.flow_mm3_s, "colour_change_s": printer.colour_change_s,
                     "layer_overhead_s": printer.layer_overhead_s, "plate_setup_s": printer.plate_setup_s},
    )


def format_duration(seconds: float) -> str:
    m = int(round(seconds / 60))
    return f"{m // 60} sa {m % 60:02d} dk" if m >= 60 else f"{m} dk"
