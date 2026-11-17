"""Quick preview PNG: exploded view (face / frame / back + LED strips + controller) and a plan view of the LED path.

G6 adds the proper unlit/lit renders; this is the fast matplotlib view used for design checks.
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import trimesh  # noqa: E402
from . import zrender  # noqa: E402
from .parts import solid, to_mesh  # noqa: E402
from .checks import box_ctrl  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import PatchCollection  # noqa: E402
from matplotlib.patches import FancyArrowPatch, PathPatch, Polygon as MplPoly  # noqa: E402
from matplotlib.path import Path as MplPath  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Poly3DCollection  # noqa: E402

LIGHT = np.array([-0.4, -0.6, 0.7]) / np.linalg.norm([-0.4, -0.6, 0.7])


def _subdivide(mesh, max_edge: float = 10.0):
    """Split long triangles: matplotlib sorts polygons by depth, long ones sort wrongly (diagonal artefacts)."""
    import trimesh

    v, f = trimesh.remesh.subdivide_to_size(mesh.vertices, mesh.faces, max_edge=max_edge)
    return trimesh.Trimesh(v, f, process=False)


def _hex(c: str) -> np.ndarray:
    return np.array([int(c[i:i + 2], 16) for i in (1, 3, 5)]) / 255.0


def _shade(items, dz: float, alpha: float = 1.0):
    """items: [(mesh, colour)] merged into ONE collection so triangles of all colours are depth-sorted together."""
    tris_l, cols_l = [], []
    for mesh, color in items:
        mesh = _subdivide(mesh)
        v = mesh.vertices.copy()
        v[:, 2] += dz
        k = 0.45 + 0.55 * np.clip(mesh.face_normals @ LIGHT, 0, 1)
        c = np.clip(_hex(color)[None, :] * k[:, None] + 0.04, 0, 1)
        tris_l.append(v[mesh.faces])
        cols_l.append(np.hstack([c, np.full((len(c), 1), alpha)]))
    cols = np.vstack(cols_l)
    return Poly3DCollection(np.vstack(tris_l), facecolors=cols, edgecolors=cols, linewidths=0.25, antialiaseds=False)


def _poly_patches(geom, **kw):
    """Patches honouring holes (compound paths)."""
    geoms = getattr(geom, "geoms", [geom])
    out = []
    for g in geoms:
        if g.is_empty:
            continue
        rings = [g.exterior, *g.interiors]
        verts, codes = [], []
        for r in rings:
            c = np.asarray(r.coords)
            verts += list(c)
            codes += [MplPath.MOVETO] + [MplPath.LINETO] * (len(c) - 2) + [MplPath.CLOSEPOLY]
        out.append(PathPatch(MplPath(verts, codes), **kw))
    return out


def render_preview(box, out_path: str | Path, title: str | None = None) -> Path:
    model = box.model
    meta = model.meta
    D, tb = model.depth_mm, meta["tb_mm"]
    spread = 42.0
    offs = {"back": -spread, "body": 0.0, "face": +spread, "cover": -spread + 14.0}
    fig = plt.figure(figsize=(15, 6.6), dpi=130, facecolor="white")
    ax = fig.add_axes([0.10, 0.0, 0.46, 1.0])
    ax.axis("off")
    items = []
    for p in model.parts:
        if p.group == "stand":
            continue
        m = p.mesh_wall.copy()
        m.apply_translation([0, 0, offs.get(p.group, 0.0)])
        items.append((m, p.color))
    led = box.model.meta["led"]
    try:
        from .hardware import default_hardware

        _l = default_hardware().led(led)
        sw, led_t = _l.width_mm, max(_l.thickness_mm, 1.2)
    except (KeyError, ValueError):
        sw = 10.0 if "10mm" in led else 5.0
        led_t = 3.0 if "10mm" in led else 2.0

    def led_items(dz):
        out = []
        for ln in box.path.strip_lines():
            g = ln.buffer(sw / 2, cap_style="flat")
            mesh = to_mesh(solid(g, 0, led_t))
            mesh.apply_translation([0, 0, tb + dz])
            out.append((mesh, "#FF8A1F", 0.6))
        Hc_ = meta["controller_pocket"]["controller"][2]
        cb_ = to_mesh(solid(box_ctrl(meta), 0, Hc_))
        cb_.apply_translation([0, 0, tb + dz])
        return out + [(cb_, "#2F6DB5")]

    (cx, cy), (L, Wc, Hc) = meta["controller_pocket"]["center"], meta["controller_pocket"]["controller"]
    items += led_items(offs["back"])
    ax.imshow(zrender.render_scene(items, azim=-18, elev=30, width_px=1500, lay_flat=True, bg=(255, 255, 255, 255)))
    W, H = model.width_mm, model.height_mm
    for name, yy in (("Ön yüz (difüzör + çerçeve)", 0.80), ("Gövde", 0.52), ("Arka kapak + LED + kontrolcü", 0.20)):
        fig.text(0.01, yy, name, fontsize=9, color="#444", ha="left")
    # assembled view (with the stand), cut open so the LED layer is visible is not needed: closed 3/4 view
    ax3 = fig.add_axes([0.58, 0.0, 0.40, 0.40])
    ax3.axis("off")
    asm = [(p.mesh_wall, p.color) for p in model.parts]
    ax3.imshow(zrender.render_scene(asm, azim=-28, elev=14, width_px=900, bg=(255, 255, 255, 255)))
    # plan view
    ax2 = fig.add_axes([0.58, 0.42, 0.40, 0.50])
    polys = meta["polys"]
    ax2.add_collection(PatchCollection(_poly_patches(polys["outline"]), facecolor="#F3F3F3", edgecolor="#1F4D3A", linewidth=2))
    ax2.add_collection(PatchCollection(_poly_patches(polys["inner"]), facecolor="white", edgecolor="#1F4D3A", linewidth=1))
    ax2.add_collection(PatchCollection(_poly_patches(polys["lip_out"].difference(polys["lip_in"])), facecolor="#CFE3D8", edgecolor="none"))
    ax2.add_collection(PatchCollection(_poly_patches(polys["boss_zone"]), facecolor="#9DBBA9", edgecolor="#1F4D3A", linewidth=0.8))
    ax2.add_collection(PatchCollection(_poly_patches(polys["cradle"]), facecolor="#BFD7F2", edgecolor="#143A66", linewidth=0.8))
    ax2.add_collection(PatchCollection(_poly_patches(box_ctrl(meta)), facecolor="#2F6DB5", edgecolor="#143A66", alpha=0.85))
    ax2.text(cx, cy, "kontrolcü", color="white", ha="center", va="center", fontsize=8)
    for ln in box.path.strip_lines():
        ax2.add_collection(PatchCollection(_poly_patches(ln.buffer(sw / 2, cap_style="flat")), facecolor="#FF8A1F", edgecolor="#B35400", linewidth=0.8))
    for s_ in box.path.segments:
        ax2.add_patch(FancyArrowPatch(s_.p0, s_.p1, arrowstyle="-|>", mutation_scale=9, color="#5A2E00", lw=1.1, connectionstyle="arc3,rad=0"))
    for j in box.path.joints:
        if j.type == "jumper":
            xs, ys = j.line.xy
            ax2.plot(xs, ys, color="#B35400", ls="--", lw=1.2)
    csx, csy = meta["cable_slot"]
    ax2.plot([csx], [csy], marker="s", color="#222", ms=7)
    ax2.annotate("USB çıkışı", (csx, csy), xytext=(csx, csy + 17), fontsize=8, ha="center", arrowprops=dict(arrowstyle="-", color="#222"))
    ax2.set_xlim(-W / 2 - 4, W / 2 + 4)
    ax2.set_ylim(-H / 2 - 6, H / 2 + 6)
    ax2.set_aspect("equal")
    ax2.axis("off")
    pw = meta["power"]
    ax2.set_title(f"LED yolu (arka kapak içi): {pw['strip_length_mm']:.0f} mm, {pw['n_leds']} LED, "
                  f"{meta['led_path']['joint']}", fontsize=10)
    fig.suptitle(title or f"Workbench - Glow  {meta['design']} {W / 10:.1f} x {H / 10:.1f} x {D / 10:.1f} cm  ({meta['led']}, {meta['controller']}, {meta['mount']})", fontsize=12, y=0.985)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor="white")
    plt.close(fig)
    return out
