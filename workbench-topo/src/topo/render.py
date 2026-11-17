"""Headless renders (pure numpy z-buffer, the shared workbench_core rasteriser) and a light GLB preview."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from workbench_core.render import decimate, render_meshes  # noqa: F401  (decimate: used by output.py)
from workbench_core.render import write_glb as _write_glb
import trimesh
from PIL import Image

AMBIENT, DIFFUSE = 0.55, 0.50  # Topo's look: softer contrast, light fixed to the map
LIGHT = np.array([-0.45, 0.55, 0.70])
BG = (238, 240, 243)


def _view(view: str) -> np.ndarray:
    if view == "top":
        return np.eye(3)
    # 3/4 view: rotate -28 deg about z, then tilt 52 deg about x (looking from the front, above)
    a, b = np.radians(-28.0), np.radians(-52.0)
    rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(b), -np.sin(b)], [0, np.sin(b), np.cos(b)]])
    return rx @ rz


def render(parts: list[tuple[trimesh.Trimesh, str]], view: str = "34", width_px: int = 1400, bg=BG) -> Image.Image:
    return render_meshes(parts, _view(view), width_px=width_px, margin=0.05, bg=bg, ambient=AMBIENT, diffuse=DIFFUSE,
                         light=LIGHT, light_in_model=True, cull=False, supersample=2)


def write_glb(parts: list[tuple[trimesh.Trimesh, str]], path: Path, max_faces: int = 400_000) -> Path:
    """Light GLB of the map (y-up for glTF)."""
    return _write_glb(parts, path, max_faces=max_faces, z_up=True)
