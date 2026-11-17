"""Job runner: model -> tiles -> filament slots -> STL / 3MF / renders / job.json."""
from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from pathlib import Path

import manifold3d as m3
import numpy as np

from workbench_core.estimate import estimate_slots, format_duration

from . import __version__
from .build import Model, build_model
from .export3mf import PLATE_MAX_MONO, PLATE_MAX_MULTI, write_3mf
from .geom import to_mesh
from .job import Job
from .render import render, write_glb

TIME_CALIBRATION = 2.1
PURGE_G_PER_CHANGE = 0.38  # prime tower + flush per counted colour change (fit to OrcaSlicer 2.4.2 on two 4-colour landscapes: +9 % / -5 %)
PIN_D, PIN_DEPTH, PIN_EVERY = 2.0, 6.0, 55.0  # holes for 1.75 mm filament pieces used as alignment pins
ATTRIBUTION = "Harita verisi © OpenStreetMap katkıcıları (ODbL). Yükseklik: Copernicus DEM GLO-30/90 © DLR e.V. 2010-2014 ve © Airbus 2014-2018, ESA tarafından sağlanmıştır."


@dataclass
class Result:
    out_dir: Path
    data: dict
    files: dict


def slug(s: str) -> str:
    tr = str.maketrans("çğıöşüÇĞİÖŞÜ ", "cgiosuCGIOSU_")
    return re.sub(r"[^A-Za-z0-9_\-]+", "", s.translate(tr))[:60] or "harita"


def _tiles(model: Model, n_colors: int):
    """List of (name, (x0, y0, x1, y1)) tiles covering the footprint, each fitting one plate."""
    x0, y0, x1, y1 = model.footprint.bounds
    W, H = x1 - x0, y1 - y0
    mx, my = PLATE_MAX_MULTI if n_colors > 1 else PLATE_MAX_MONO
    fits = (W <= mx and H <= my) or (H <= mx and W <= my)
    if fits or not model.job.split:
        if not fits:
            model.warnings.append(f"Model {W:.0f}x{H:.0f} mm tablaya sığmıyor ve bölme kapalı.")
        return [("harita", (x0 - 1, y0 - 1, x1 + 1, y1 + 1))], 1, 1
    nx, ny = math.ceil(W / mx), math.ceil(H / my)
    tw, th = W / nx, H / ny
    out = []
    for j in range(ny):
        for i in range(nx):
            out.append((f"parca_{j * nx + i + 1}of{nx * ny}",
                        (x0 + i * tw - (1 if i == 0 else 0), y0 + j * th - (1 if j == 0 else 0),
                         x0 + (i + 1) * tw + (1 if i == nx - 1 else 0), y0 + (j + 1) * th + (1 if j == ny - 1 else 0))))
    model.warnings.append(f"Model {W:.0f}x{H:.0f} mm; {nx}x{ny} = {nx * ny} parçaya bölündü. "
                          f"Birleştirme için kesim yüzlerinde Ø{PIN_D} mm delikler var (1,75 mm filament parçası pim olur).")
    return out, nx, ny


def _orient(parts, n_colors):
    """Turn a tile 90 degrees when that is the only way it fits the plate's usable area."""
    import trimesh

    if not parts:
        return parts
    v = np.vstack([m.vertices for _, _, m in parts])
    w, d = np.ptp(v[:, 0]), np.ptp(v[:, 1])
    mx, my = PLATE_MAX_MULTI if n_colors > 1 else PLATE_MAX_MONO
    if (w > mx or d > my) and d <= mx and w <= my:
        R = trimesh.transformations.rotation_matrix(np.pi / 2, [0, 0, 1])
        parts = [(n, e, m.copy().apply_transform(R)) for n, e, m in parts]
    return parts


def _pin_holes(model: Model, nx: int, ny: int) -> m3.Manifold:
    x0, y0, x1, y1 = model.footprint.bounds
    tw, th = (x1 - x0) / nx, (y1 - y0) / ny
    zc = model.job.base_mm / 2
    holes = m3.Manifold()
    cyl = m3.Manifold.cylinder(2 * PIN_DEPTH, PIN_D / 2, PIN_D / 2, 24)  # along z, centred later
    from shapely.geometry import Point

    for i in range(1, nx):  # vertical cut lines x = const, holes along x
        xc = x0 + i * tw
        n = max(1, int((y1 - y0) // PIN_EVERY))
        for t in range(n):
            yc = y0 + (t + 0.5) * (y1 - y0) / n
            if model.footprint.buffer(-4).contains(Point(xc, yc)):
                holes = holes + cyl.translate([0, 0, -PIN_DEPTH]).rotate([0, 90, 0]).translate([xc, yc, zc])
    for j in range(1, ny):
        yc = y0 + j * th
        n = max(1, int((x1 - x0) // PIN_EVERY))
        for t in range(n):
            xc = x0 + (t + 0.5) * (x1 - x0) / n
            if model.footprint.buffer(-4).contains(Point(xc, yc)):
                holes = holes + cyl.translate([0, 0, -PIN_DEPTH]).rotate([90, 0, 0]).translate([xc, yc, zc])
    return holes


def _estimate(tiles_meshes: list[list[tuple[str, int, object]]], infill: float) -> dict:
    """Shared estimate (workbench_core.estimate), with Topo's time calibration: OrcaSlicer 2.4.2 took 1.8-2.6x the
    model's time on a 2-colour memory map and a 4-colour city map. Grams add the prime tower / flush waste of every
    colour change (a 4-colour landscape changes colour 100-200 times: +40-100 g)."""
    est = estimate_slots([[(ext, m) for _, ext, m in parts] for parts in tiles_meshes], infill)
    secs = est["time_s"] * TIME_CALIBRATION
    return {"grams_by_slot": {str(k): round(v) for k, v in sorted(est["grams_by_slot"].items())},
            "grams_purge": round(est["colour_changes"] * PURGE_G_PER_CHANGE),
            "grams_total": round(sum(est["grams_by_slot"].values()) + est["colour_changes"] * PURGE_G_PER_CHANGE), "seconds": round(secs), "text": format_duration(secs),
            "colour_changes": est["colour_changes"], "note": "Tahmin (gram ±%10, süre ±%25); kesin değer için OrcaSlicer'da dilimleyin."}


def run_job(job: Job, out_root: str | Path = "output", progress=None) -> Result:
    t0 = time.time()
    model = build_model(job, progress)
    job = model.job
    out = Path(out_root) / slug(job.name)
    if out.exists():
        out = Path(out_root) / f"{slug(job.name)}_{time.strftime('%Y%m%d_%H%M%S')}"
    (out / "parts").mkdir(parents=True, exist_ok=True)

    # filament slots (one per distinct colour, in a stable order)
    order = []
    for p in model.parts:
        if p.color.upper() not in order:
            order.append(p.color.upper())
    if len(order) > 4:
        raise ValueError("CANVAS en fazla 4 filament alır; bu iş " + str(len(order)) + " renk kullanıyor: " + ", ".join(order)
                         + ". Aynı rengi birden fazla katmanda kullanın ya da bir katmanı kapatın.")
    slot = {c: i + 1 for i, c in enumerate(order)}

    if progress:
        progress("Tablalara yerleştiriliyor…")
    tiles, nx, ny = _tiles(model, len(order))
    pins = _pin_holes(model, nx, ny) if len(tiles) > 1 else None
    if pins is not None and job.base_mm < 3.5:
        model.warnings.append("Pim delikleri için taban en az 3,5 mm olmalı; delik açılmadı.")
        pins = None
    tiles_meshes = []
    flat_parts = []
    files: dict = {}
    for tname, (bx0, by0, bx1, by1) in tiles:
        cut = m3.Manifold.cube([bx1 - bx0, by1 - by0, 1000]).translate([bx0, by0, -10])
        # one 3MF part / STL per layer (same-colour layers share a filament slot but are not fused:
        # fusing solids that only touch would create non-manifold edges)
        parts = []
        for p in model.parts:
            s = p.solid ^ cut if len(tiles) > 1 else p.solid
            if pins is not None and p.role in ("terrain", "frame"):
                s = s - pins
            if s.is_empty():
                continue
            mesh = to_mesh(s)
            if len(mesh.faces) == 0:
                continue
            color = p.color.upper()
            mesh.export(out / "parts" / f"{tname}_{slot[color]}_{slug(p.name)}.stl")
            parts.append((p.name, slot[color], mesh))
        flat_parts.extend(parts)
        tiles_meshes.append(_orient(parts, len(order)))

    title = job.title or model.caption.get("title") or model.route_name
    files["3mf"] = write_3mf(out / "model.3mf", [{"name": n, "parts": p} for (n, _), p in zip(tiles, tiles_meshes)],
                             order, title, job.infill_percent, meta={"Topo": __version__, "Mode": job.mode})
    if progress:
        progress("Görseller hazırlanıyor…")
    all_parts = [(m, order[e - 1]) for _, e, m in flat_parts]
    preview = [(m, c) for m, c in all_parts]
    from .render import decimate

    light = [(decimate(m, 250_000), c) for m, c in preview]
    render(light, "34").save(out / "render_34.png")
    render(light, "top").save(out / "render_top.png")
    files["render_34"], files["render_top"] = out / "render_34.png", out / "render_top.png"
    files["glb"] = write_glb(light, out / "preview.glb")

    x0, y0, x1, y1 = model.footprint.bounds
    zmax = max(float(m.bounds[1][2]) for m, _ in all_parts)
    est = _estimate(tiles_meshes, job.infill_percent / 100)
    stats = {k: v for k, v in model.stats.items() if not k.startswith("_")}
    d = {
        "tool": f"Workbench - Topo {__version__}",
        "inputs": job.to_dict(),
        "mode": job.mode,
        "area": {"south": model.bbox.south, "west": model.bbox.west, "north": model.bbox.north, "east": model.bbox.east,
                 "width_km": round(model.bbox.size_m()[0] / 1000, 3), "height_km": round(model.bbox.size_m()[1] / 1000, 3)},
        "scale": f"1:{model.proj.scale:,}".replace(",", "."),
        "z_exag": model.z_exag,
        "elevation_m": {"min": round(float(model.elev.min())), "max": round(float(model.elev.max()))},
        "overall_mm": {"width": round(x1 - x0, 1), "depth": round(y1 - y0, 1), "height": round(zmax, 1)},
        "tiles": len(tiles),
        "filaments": [{"slot": slot[c], "color": c, "parts": sorted({p.name for p in model.parts if p.color.upper() == c})} for c in order],
        "estimate": est,
        "route": stats,
        "caption": model.caption,
        "attribution": ATTRIBUTION,
        "warnings": model.warnings,
        "seconds": round(time.time() - t0, 1),
    }
    (out / "job.json").write_text(json.dumps(d, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (out / "warnings.txt").write_text("\n".join(model.warnings) + ("\n" if model.warnings else ""), encoding="utf-8")
    (out / "ATTRIBUTION.txt").write_text(ATTRIBUTION + "\n", encoding="utf-8")
    files["job"] = out / "job.json"
    return Result(out, d, files)


def preview(job: Job, out_path: str | Path, progress=None, image_path: str | Path | None = None) -> dict:
    """Fast coarse model for the on-screen 3D view: GLB + summary (no STL / 3MF). ``image_path``: also a 3/4 view
    PNG, for browsers without WebGL (e.g. embedded app windows)."""
    model = build_model(job, progress, coarse=True)
    order, merged, roles = [], {}, {}
    for p in model.parts:
        c = p.color.upper()
        if c not in order:
            order.append(c)
        merged[c] = merged.get(c, m3.Manifold()) + p.solid
        if p.role not in roles.setdefault(c, []):
            roles[c].append(p.role)
    parts = [(to_mesh(s), c) for c, s in merged.items()]
    write_glb(parts, Path(out_path), max_faces=250_000)
    if image_path is not None:
        from .render import render

        render(parts, "34", width_px=1200).save(image_path)
    x0, y0, x1, y1 = model.footprint.bounds
    zmax = max(float(m.bounds[1][2]) for m, _ in parts)
    return {"scale": f"1:{model.proj.scale:,}".replace(",", "."), "z_exag": model.z_exag,
            "overall_mm": {"width": round(x1 - x0, 1), "depth": round(y1 - y0, 1), "height": round(zmax, 1)},
            "colors": order, "too_many_colors": len(order) > 4, "roles": roles,
            "estimate": _estimate([[(c, i + 1, m) for i, (m, c) in enumerate(parts)]], job.resolved().infill_percent / 100), "caption": model.caption,
            "route": {k: v for k, v in model.stats.items() if not k.startswith("_")}, "warnings": model.warnings}
