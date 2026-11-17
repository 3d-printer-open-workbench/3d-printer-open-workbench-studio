"""Product / parts PNGs and the no-WebGL preview: the shared renderer (workbench_core.render.render_meshes)."""
from __future__ import annotations

from PIL import Image

from . import core
from .generators import Part


def render_parts(parts: list[Part], *, azim: float = -30.0, elev: float = 30.0, width_px: int = 900,
                 margin: float = 0.06) -> Image.Image:
    """Assembled parts (print orientation, z up) seen from the front-left above; transparent background.
    Glossy parts (``meta.gloss``, the formed PETG shell) get smooth normals and a highlight."""
    items = [(p.mesh, p.color, {"gloss": p.meta.get("gloss", 0)}) for p in parts]
    return core.render_meshes(items, core.view_rotation(azim, elev) @ core.Z_UP, width_px=width_px, margin=margin)
