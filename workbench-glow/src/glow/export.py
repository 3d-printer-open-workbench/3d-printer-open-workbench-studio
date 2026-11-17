"""Write STL / 3MF / job.json / warnings.txt for a built lightbox."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from workbench_core.export3mf import build_objects, plate_reserved, write_3mf
from workbench_core.estimate import estimate
from workbench_core.geometry import Model
from workbench_core.split import pack_plates, split_model

from . import __version__

INFILL_PERCENT = 15
TOWER_EXTRA_4C = 25.0  # mm, extra tower depth for 4 filaments (Orca result: 4-colour tower overflows the bed otherwise)


def write_model_files(model: Model, out: Path, slug: str) -> dict:
    """parts/*.stl (print orientation, each moved to the origin) and model.3mf (Orca, colours = extruders)."""
    out.mkdir(parents=True, exist_ok=True)
    parts_dir = out / "parts"
    if parts_dir.exists():
        shutil.rmtree(parts_dir)
    parts_dir.mkdir()
    result = split_model(model)
    n_fil = max(p.extruder for p in model.parts)
    reserved, mixed, tower = plate_reserved(n_fil > 1)
    if n_fil > 3 and tower is not None:
        # 4-colour prime tower is deeper than Kaligraf's 30 mm assumption: lift it and keep more area free
        shift = TOWER_EXTRA_4C
        mixed = [(x, y - shift, w, h + shift) for x, y, w, h in mixed]
        tower = (tower[0], tower[1] - shift)
    plates = pack_plates(result.pieces, reserved=reserved, mixed_reserved=mixed)
    stl = []
    for pc in result.pieces:
        m = pc.mesh.copy()
        m.apply_translation(-m.bounds[0])
        f = parts_dir / f"{pc.name}.stl"
        m.export(f)
        stl.append(f)
    objects = build_objects(result, plates)
    p3 = write_3mf(out / "model.3mf", objects, len(plates), model.colors, title=slug, tower_xy=tower,
                   infill_percent=INFILL_PERCENT, meta={"generator": f"glow {__version__}"})
    est = estimate(result, plates, INFILL_PERCENT / 100.0)
    return {"estimate": est, "3mf": p3, "parts": parts_dir, "stl": stl, "plates": len(plates), "split_warnings": list(result.warnings)}
