"""Calibration coupon: diffuser thickness ladder (0.6-2.4 mm) + opaque / blocking test tiles.

Print face-down (front on the bed). Hold the coupon in front of the actual LED strip at the real LED-to-face
gap, pick the thinnest step that hides the LED dots, then set that value in ``hardware.yaml``
(`diffusers.<id>.thickness_mm.<led>`).  Tiles A-D test opaque colour: A 1.2 colour only, B 0.8 colour + 0.4
black block, C 0.8 colour only, D 1.6 colour only.
"""
from __future__ import annotations

import numpy as np
import trimesh
from shapely import affinity
from shapely.geometry import box

from workbench_core.fonts import resolve_font
from workbench_core.geometry import Model, Part
from workbench_core.text2d import build_text

from .hardware import Hardware, default_hardware
from .parts import BLOCK_COLOR, norm_color, slug, solid, to_mesh, union

STEPS = [round(0.6 + 0.2 * i, 1) for i in range(10)]  # 0.6 ... 2.4
OPAQUE_TESTS = {"A": (1.2, 0.0), "B": (1.2, 0.4), "C": (0.8, 0.0), "D": (1.6, 0.0)}  # label -> (total, block)
TILE_W, TILE_H, GAP, SPINE_H, SPINE_T, LABEL_T = 13.0, 22.0, 1.0, 7.0, 0.6, 0.6


def build_calibration(diffuser: str = "pla_white", opaque_color: str = "#1F4D3A", font: str = "Montserrat",
                      hw: Hardware | None = None) -> Model:
    hw = hw or default_hardware()
    dcolor = norm_color(hw.diffuser(diffuser).color)
    ocolor = norm_color(opaque_color)
    rfont = resolve_font(font)
    n_l, n_o = len(STEPS), len(OPAQUE_TESTS)
    n = n_l + n_o
    pitch = TILE_W + GAP
    total_w = n * pitch - GAP + 2.0
    spine = box(0, 0, total_w, SPINE_H)
    # coordinates: front surface at z = 0 (wall orientation z up: front_z = depth)
    top = max(STEPS[-1], 1.6) + LABEL_T
    items: dict[str, list] = {dcolor: [], ocolor: [], BLOCK_COLOR: []}
    items[dcolor].append(solid(spine, top - SPINE_T, top))
    labels = [f"{s:.1f}" for s in STEPS] + list(OPAQUE_TESTS)
    for i in range(n):
        x0 = 1.0 + i * pitch
        tile = box(x0, SPINE_H, x0 + TILE_W, SPINE_H + TILE_H)
        if i < n_l:
            t = STEPS[i]
            items[dcolor].append(solid(tile, top - t, top))
            bridge = box(x0, SPINE_H - 0.5, x0 + TILE_W, SPINE_H + 0.5)  # tile fused to the spine
            items[dcolor].append(solid(bridge, top - max(t, SPINE_T), top))
        else:
            total, blk = OPAQUE_TESTS[labels[i]]
            items[ocolor].append(solid(tile, top - total, top - blk))
            if blk:
                items[BLOCK_COLOR].append(solid(tile, top - blk, top))
            bridge = box(x0, SPINE_H - 0.5, x0 + TILE_W, SPINE_H + 0.5)
            items[ocolor].append(solid(bridge, top - SPINE_T, top))
        # label raised on the back of the spine, centred under the tile
        g = build_text(labels[i], rfont, "flat", width_mm=min(TILE_W - 3.0, 3.2 * len(labels[i]))).geometry
        g = affinity.translate(g, x0 + TILE_W / 2 - (g.bounds[0] + g.bounds[2]) / 2, SPINE_H / 2 - (g.bounds[1] + g.bounds[3]) / 2)
        items[dcolor].append(solid(g, top - SPINE_T - LABEL_T, top - SPINE_T))
    parts: list[Part] = []
    for color, ms in items.items():
        ms = [m for m in ms if not m.is_empty()]
        if not ms:
            continue
        mesh = to_mesh(union(ms))
        p = Part(f"coupon_{slug(color)}", "coupon", mesh, color, 1, group="coupon")
        parts.append(p)
    order: list[str] = []
    for p in parts:
        order.append(p.color)
        p.extruder = len(order)
    tf = _common_flip(parts)
    for p in parts:
        p.print_transform = tf
    model = Model("coupon", parts, total_w, SPINE_H + TILE_H, top, [], {
        "diffuser": diffuser, "steps_mm": STEPS, "opaque_tests": {k: {"total_mm": v[0], "block_mm": v[1]} for k, v in OPAQUE_TESTS.items()},
    })
    return model


def _common_flip(parts: list[Part]) -> np.ndarray:
    """One flip+lift transform for all parts of an assembly (keeps their relative position)."""
    rot = trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0])
    zmin = min(float((p.mesh_wall.vertices @ rot[:3, :3].T)[:, 2].min()) for p in parts)
    t = np.eye(4)
    t[2, 3] = -zmin
    return t @ rot
