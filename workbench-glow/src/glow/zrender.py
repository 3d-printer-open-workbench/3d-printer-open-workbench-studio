"""Lightbox scene renders: the shared renderer (workbench_core.render.render_meshes) in wall coordinates."""
from __future__ import annotations

import numpy as np
from PIL import Image
from workbench_core.render import Z_UP, render_meshes, view_rotation


def render_scene(items: list[tuple], *, azim: float = -32.0, elev: float = 22.0, width_px: int = 1500,
                 margin: float = 0.04, lay_flat: bool = False, bg: tuple[int, int, int, int] = (255, 255, 255, 0)) -> Image.Image:
    """items: (mesh, colour) or (mesh, colour, emissive 0..1); meshes in wall coordinates (z toward the viewer).
    ``lay_flat``: the box lies face up (exploded stacks go upwards)."""
    rot = view_rotation(azim, elev) @ (Z_UP if lay_flat else np.eye(3))
    its = [(it[0], it[1], {"emissive": it[2] if len(it) > 2 else 0.0}) for it in items]
    im = render_meshes(its, rot, width_px=width_px, margin=margin)
    if bg[3] > 0:
        base = Image.new("RGBA", im.size, bg)
        base.alpha_composite(im)
        return base
    return im
