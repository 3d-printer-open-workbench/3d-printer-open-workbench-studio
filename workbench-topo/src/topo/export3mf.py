"""Multi-colour 3MF for OrcaSlicer (Elegoo Centauri Carbon + CANVAS) through the shared writer
(workbench_core.export3mf): one object per tile, one plate per tile, one sub-part per colour.

Topo's own choices on top of the shared writer: a one-colour tile sits in the middle of the plate; a multi-colour
tile sits front-left with the prime tower in the strip on its right (with 3-4 colours the tower is too deep for the
back strip: Orca refused 4-colour city maps); 3 walls / 5 top / 4 bottom layers, no support."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from workbench_core.export3mf import ObjectSpec
from workbench_core.export3mf import write_3mf as _core_write_3mf

BED = (256.0, 256.0)
# usable area per plate: multi-colour tiles leave the right strip free for the prime tower
PLATE_MAX_MULTI = (200.0, 246.0)
TOWER_XY = (210.0, 100.0)  # bed coordinates, right strip, clear of the front-right exclusion corner
PLATE_MAX_MONO = (246.0, 246.0)
PACK_EXTENT = 250.0  # the shared writer centres a 250 x 250 packing area on the 256 bed
SETTINGS = {"wall_loops": "3", "top_shell_layers": "5", "bottom_shell_layers": "4", "layer_height": "0.2", "enable_support": "0"}


def write_3mf(path: Path, tiles: list[dict], colors: list[str], title: str, infill: int = 15, meta: dict | None = None) -> Path:
    """``tiles``: [{"name", "parts": [(part_name, extruder, mesh)]}], meshes in model mm (any XY origin)."""
    multi = len(colors) > 1
    off = (BED[0] - PACK_EXTENT) / 2
    objects = []
    for ti, t in enumerate(tiles):
        allv = np.vstack([m.vertices for _, _, m in t["parts"]])
        lo, hi = allv.min(0), allv.max(0)
        # target centre on the bed: middle; multi-colour front-left (2 mm from the edges), tower on the right
        cx = (2 + (hi[0] - lo[0]) / 2 if multi else BED[0] / 2) - off
        cy = (2 + (hi[1] - lo[1]) / 2 if multi else BED[1] / 2) - off
        shift = np.array([cx - (lo[0] + hi[0]) / 2, cy - (lo[1] + hi[1]) / 2, -lo[2]])
        pieces = []
        for name, ext, m in t["parts"]:
            mm = m.copy()
            mm.apply_translation(shift)
            pieces.append((SimpleNamespace(name=name, part=SimpleNamespace(name=name, extruder=ext)), mm))
        objects.append(ObjectSpec(t["name"], ti, pieces))
    tower = TOWER_XY if multi else None
    return _core_write_3mf(path, objects, len(tiles), colors, title=title, meta=meta, tower_xy=tower, infill_percent=infill,
                           settings=SETTINGS, plate_names=[t["name"] for t in tiles])
