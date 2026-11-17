"""Face engine: text/logo -> regions (light vs opaque, per-colour), relief and blocking layers.

Coordinates: 2D geometry in mm, origin at the face centre (x right, y up). Depth ``z`` of a layer is
measured **from the front (visible) surface backwards** (z = 0 front, increasing into the box).

Region kinds
* ``light``  - light passes: diffuser plate at the calibrated thickness (colour = filament colour).
* ``opaque`` - blocks light: >= ``OPAQUE_MIN`` mm thick; with ``block="layer"`` the back ``BLOCK_T`` mm
  is a black blocking layer under the coloured layer (stops bleed of the LED through light colours; skipped for dark
  colours, luminance < 0.3, which block the light themselves and save a filament).

Relief (applies to *features*, i.e. the text/logo regions, relative to the ground)
* ``flush``    all fronts at z = 0.
* ``raised``   features start at z = 0, ground/frame at ``relief_mm`` (features are proud).
* ``recessed`` ground/frame at z = 0, features start at ``relief_mm`` (features are sunk).
Raised/recessed faces are printed face-up (otherwise part of the front would hang over air).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from workbench_core.fonts import ResolvedFont
from workbench_core.geometry import Part
from workbench_core.logo2d import load_logo
from workbench_core.text2d import build_text, thin_regions

from .parts import BLOCK_COLOR, luminance, norm_color, slug, solid, to_mesh, union

OPAQUE_MIN = 1.2
BLOCK_T = 0.4
MIN_BOND = 0.4  # minimum z overlap between neighbouring regions (recessed relief)
MIN_FEATURE_MM = 0.8
DARK_LUM = 0.3  # opaque colours darker than this need no black blocking layer (they do not let LED light bleed through)
RELIEFS = ("flush", "raised", "recessed")
LIGHT_MODES = ("ground", "features")  # which side lets the light through


@dataclass
class Region:
    name: str
    color: str
    kind: str  # light | opaque
    role: str  # ground | feature | frame
    geometry: BaseGeometry


@dataclass
class FaceRegions:
    regions: list[Region]
    outline: BaseGeometry  # whole face plate (frame included)
    window: BaseGeometry  # lit area
    features: BaseGeometry
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def colors(self) -> list[str]:
        out: list[str] = []
        for r in self.regions:
            if r.color not in out:
                out.append(r.color)
        return out


@dataclass
class FaceLayer:
    name: str
    color: str
    role: str  # light | colour | block
    region: str
    geometry: BaseGeometry
    z0: float
    z1: float


# --------------------------------------------------------------------------- #
# Content -> geometry
# --------------------------------------------------------------------------- #
def _center(geom: BaseGeometry) -> BaseGeometry:
    minx, miny, maxx, maxy = geom.bounds
    return affinity.translate(geom, -(minx + maxx) / 2, -(miny + maxy) / 2)


def fit_text(text: str, font: ResolvedFont, box_w: float, box_h: float | None = None, *,
             tracking: float = 0.0, line_spacing: float = 1.0) -> tuple[BaseGeometry, list[str]]:
    """Text as geometry centred on the origin, as large as fits in ``box_w`` x ``box_h`` (box_h optional)."""
    res = build_text(text, font, "flat", width_mm=box_w, tracking=tracking, line_spacing=line_spacing)
    geom, warns = res.geometry, list(res.warnings)
    if box_h is not None and res.height_mm > box_h:
        res = build_text(text, font, "flat", width_mm=box_w * box_h / res.height_mm, tracking=tracking,
                         line_spacing=line_spacing)
        geom = res.geometry
    return _center(geom), warns


def fit_logo(path: str | Path, box_w: float, box_h: float | None = None, n_colors: int = 4,
             ) -> tuple[list[tuple[str, BaseGeometry]], list[str]]:
    """Logo regions (colour, geometry) centred on the origin, fitted into the box."""
    logo = load_logo(path, box_w, n_colors)
    scale = 1.0
    if box_h is not None and logo.height_mm > box_h:
        scale = box_h / logo.height_mm
    cx, cy = logo.width_mm / 2, logo.height_mm / 2
    out = []
    for r in logo.regions:
        g = affinity.translate(r.geometry, -cx, -cy)
        g = affinity.scale(g, scale, scale, origin=(0, 0))
        out.append((norm_color(r.color), g))
    return out, list(logo.warnings)


def window_size_for(content_w: float, content_h: float, margin: float) -> tuple[float, float]:
    return content_w + 2 * margin, content_h + 2 * margin


# --------------------------------------------------------------------------- #
# Regions
# --------------------------------------------------------------------------- #
def build_face_regions(
    outline: BaseGeometry, window: BaseGeometry, features: list[tuple], *,
    light: str = "ground", light_color: str = "#F5F5F5", ground_color: str | None = None,
    frame_color: str = "#1F4D3A", min_feature_mm: float = MIN_FEATURE_MM,
) -> FaceRegions:
    """Split the face into frame / ground / feature regions.

    ``light="ground"``: the window background lets light through (colour ``light_color``), features are
    opaque in their own colours.  ``light="features"``: features glow (in their colours), the ground is
    opaque in ``ground_color`` (default: frame colour).
    """
    if light not in LIGHT_MODES:
        raise ValueError(f"light must be one of {LIGHT_MODES}, got {light!r}")
    warnings: list[str] = []
    frame = outline.difference(window)
    placed: list[Region] = []
    taken: BaseGeometry = Polygon()
    for i, feat in enumerate(features, start=1):
        color, geom = feat[0], feat[1]
        fkind = feat[2] if len(feat) > 2 else ("opaque" if light == "ground" else "light")
        g = geom.intersection(window).difference(taken)
        if g.is_empty or g.area < 0.05:
            continue
        taken = unary_union([taken, g])
        placed.append(Region(f"feature_{i}", norm_color(color), fkind, "feature", g))
        for t in thin_regions(g, min_feature_mm):
            warnings.append(f"Feature {i} ({color}) has strokes thinner than {min_feature_mm} mm near "
                            f"({t.centroid.x:.0f}, {t.centroid.y:.0f}); they may not print cleanly.")
            break
    ground = window.difference(taken)
    if light == "ground":
        g_color, g_kind = norm_color(ground_color or light_color), "light"
    else:
        g_color, g_kind = norm_color(ground_color or frame_color), "opaque"
    regions = [Region("frame", norm_color(frame_color), "opaque", "frame", frame)]
    if not ground.is_empty:
        regions.append(Region("ground", g_color, g_kind, "ground", ground))
    regions += placed
    if not placed:
        warnings.append("No feature (text/logo) inside the window.")
    return FaceRegions(regions, outline, window, taken, warnings, {"light": light})


# --------------------------------------------------------------------------- #
# Layers (z from the front surface)
# --------------------------------------------------------------------------- #
def build_layers(
    fr: FaceRegions, *, t_light: float, relief: str = "flush", relief_mm: float = 1.0,
    block: str = "layer", opaque_min: float = OPAQUE_MIN, block_t: float = BLOCK_T,
    block_color: str = BLOCK_COLOR,
) -> tuple[list[FaceLayer], list[str]]:
    if relief not in RELIEFS:
        raise ValueError(f"relief must be one of {RELIEFS}, got {relief!r}")
    if block not in ("layer", "none"):
        raise ValueError("block must be 'layer' or 'none'")
    if relief != "flush" and not (0.5 <= relief_mm <= 2.5):
        raise ValueError("relief_mm must be within 0.5-2.5 mm")
    warnings: list[str] = []
    t_opaque = max(opaque_min, t_light)
    rel = 0.0 if relief == "flush" else float(relief_mm)

    def thick(r: Region) -> float:
        return t_light if r.kind == "light" else t_opaque

    ground = next((r for r in fr.regions if r.role == "ground"), None)
    t_ground = thick(ground) if ground else t_opaque
    if relief == "recessed" and t_ground - rel < MIN_BOND:
        t_ground = rel + 0.8  # keep the sunk features bonded to the ground
        if ground is not None and ground.kind == "light":
            warnings.append(f"Recessed relief {rel:g} mm needs a {t_ground:.1f} mm ground: the light area is thicker "
                            "than calibrated (dimmer); consider light='features' or a smaller relief.")
    layers: list[FaceLayer] = []
    for r in fr.regions:
        if r.role == "feature":
            zf = rel if relief == "recessed" else 0.0
            zb = zf + thick(r) + (rel if relief == "raised" else 0.0)
            if relief == "raised" and r.kind == "light":
                warnings.append("Raised light regions are thicker than the calibrated diffuser (dimmer than the ground).")
        else:
            zf = rel if relief == "raised" else 0.0
            zb = zf + (t_ground if r.role == "ground" else thick(r))
        use_block = (r.kind == "opaque" and block == "layer" and luminance(r.color) > DARK_LUM)
        if r.kind == "light":
            layers.append(FaceLayer(f"{r.name}_light", r.color, "light", r.name, r.geometry, zf, zb))
        elif use_block:
            layers.append(FaceLayer(f"{r.name}_colour", r.color, "colour", r.name, r.geometry, zf, zb - block_t))
            layers.append(FaceLayer(f"{r.name}_block", block_color, "block", r.name, r.geometry, zb - block_t, zb))
        else:
            if r.kind == "opaque" and luminance(r.color) > 0.6 and block == "none":
                warnings.append(f"Opaque region {r.name} ({r.color}) is a light colour without a blocking layer: LED bleed-through likely.")
            layers.append(FaceLayer(f"{r.name}_colour", r.color, "colour", r.name, r.geometry, zf, zb))
    return layers, warnings


def face_depth(layers: list[FaceLayer]) -> float:
    return max(l.z1 for l in layers)


def light_back_z(layers: list[FaceLayer]) -> float:
    """Deepest z (from the front) of the light-passing layers: the surface the LED gap is measured to."""
    zs = [l.z1 for l in layers if l.role == "light"]
    return max(zs) if zs else face_depth(layers)


def layers_to_parts(layers: list[FaceLayer], front_z: float, *, group: str = "face", name: str = "face") -> list[Part]:
    """One Part per colour (wall orientation, +z toward the viewer; the visible surface at ``front_z``)."""
    by_color: dict[str, list[FaceLayer]] = {}
    for l in layers:
        by_color.setdefault(l.color, []).append(l)
    parts: list[Part] = []
    for color, ls in by_color.items():
        # merge regions of equal colour and depth in 2D first (separately cleaned neighbours would leave micro slivers)
        merged: dict[tuple[float, float], list[BaseGeometry]] = {}
        for l in ls:
            merged.setdefault((round(l.z0, 6), round(l.z1, 6)), []).append(l.geometry)
        m = union([solid(unary_union(gs).buffer(0.002).buffer(-0.002), front_z - z1, front_z - z0) for (z0, z1), gs in merged.items()])
        role = "face_block" if all(l.role == "block" for l in ls) else "face"
        parts.append(Part(f"{name}_{slug(color)}", role, to_mesh(m), color, 1, group=group,
                          meta={"layers": [l.name for l in ls]}))
    return parts
