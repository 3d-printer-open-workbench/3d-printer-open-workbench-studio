"""Headless renders (pure numpy z-buffer, no GL/EGL): transparent PNGs and the dimensions image.

Orthographic projection of the wall-orientation model (x right, y up, face towards +z).
Flat Lambert shading with a high ambient term so colours stay close to the real filament colours.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .geometry import Model

AMBIENT, DIFFUSE = 0.72, 0.30
# finish -> (specular strength, shininess, texture id): matte = low specular, glossy = medium, silk = high + sheen
FINISH_SHADING = {
    "matte": (0.02, 4.0, 0), "glossy": (0.20, 12.0, 0), "silk": (0.26, 6.0, 1), "wood": (0.03, 4.0, 2),
    "marble": (0.18, 10.0, 3), "sparkle": (0.08, 6.0, 4), "translucent": (0.20, 10.0, 5),
}
LIGHT = np.array([-0.35, 0.55, 0.75])  # from the upper left, in front
SUPERSAMPLE = 2
BG = "#c9ced6"  # neutral grey so white and black filaments are both visible in dims.png
MAX_PIXELS_PER_CHUNK = 4_000_000


def _hex(c: str) -> np.ndarray:
    c = c.lstrip("#")
    return np.array([int(c[i:i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0


def view_matrix(view: str) -> np.ndarray:
    """Rotation applied to wall coordinates before the orthographic projection."""
    if view == "front":
        return np.eye(3)
    if view == "34":  # turn 32 degrees about the vertical axis, tilt 18 degrees down onto the sign
        a, b = np.radians(-32.0), np.radians(18.0)
        ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
        rx = np.array([[1, 0, 0], [0, np.cos(b), -np.sin(b)], [0, np.sin(b), np.cos(b)]])
        return rx @ ry
    raise ValueError(view)


def _raster(tris_px: np.ndarray, z: np.ndarray, colors: np.ndarray, w: int, h: int, mats: np.ndarray | None = None):
    """Z-buffer rasterisation of screen-space triangles (n,3,2) with per-triangle colour. Returns (rgb, depth, material).

    Scanline spans, fully vectorised: for every pixel row a triangle covers, its exact [x_left, x_right] span is
    computed from the three edges, so the work is proportional to the covered area (a long thin glyph triangle no
    longer costs its whole bounding box). A pixel is covered when its centre lies inside the triangle."""
    depth = np.full(w * h, np.inf, dtype=np.float32)
    rgb = np.zeros((w * h, 3), dtype=np.float32)
    mat = np.zeros(w * h, dtype=np.uint8)
    mats = np.zeros(len(z), dtype=np.uint8) if mats is None else mats
    x, y = tris_px[..., 0].astype(np.float64), tris_px[..., 1].astype(np.float64)
    area2 = (x[:, 1] - x[:, 0]) * (y[:, 2] - y[:, 0]) - (x[:, 2] - x[:, 0]) * (y[:, 1] - y[:, 0])
    r0 = np.clip(np.ceil(y.min(1) - 0.5), 0, h).astype(np.int64)  # first / last row whose centre is inside
    r1 = np.clip(np.floor(y.max(1) - 0.5), -1, h - 1).astype(np.int64)
    rows = np.where(np.abs(area2) > 1e-9, r1 - r0 + 1, 0).clip(0)
    est = rows * (np.clip(x.max(1) - x.min(1), 0, w) + 2)  # upper bound of pixels per triangle, for chunking
    ids_all = np.nonzero(rows)[0]
    cum = np.cumsum(est[ids_all])
    starts = np.unique(np.searchsorted(cum, np.arange(0, cum[-1] if len(cum) else 0, MAX_PIXELS_PER_CHUNK), side="right"))
    bounds = [0] + [int(i) for i in starts if 0 < i < len(ids_all)] + [len(ids_all)]
    for a, b in zip(bounds[:-1], bounds[1:]):
        ids = ids_all[a:b]
        n = rows[ids]
        t = np.repeat(ids, n)  # one entry per (triangle, row)
        row = np.repeat(r0[ids], n) + (np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n))
        cy = row + 0.5
        xl = np.full(len(t), np.inf)
        xr = np.full(len(t), -np.inf)
        for i, j in ((0, 1), (1, 2), (2, 0)):  # where the row centre line crosses each edge
            ya, yb, xa, xb = y[t, i], y[t, j], x[t, i], x[t, j]
            lo, hi = np.minimum(ya, yb), np.maximum(ya, yb)
            m = (cy >= lo) & (cy <= hi) & (hi > lo)
            xs = xa[m] + (cy[m] - ya[m]) * (xb[m] - xa[m]) / (yb[m] - ya[m])
            xl[m] = np.minimum(xl[m], xs)
            xr[m] = np.maximum(xr[m], xs)
        c0 = np.clip(np.ceil(xl - 0.5), 0, w).astype(np.int64)
        c1 = np.clip(np.floor(xr - 0.5), -1, w - 1).astype(np.int64)
        cnt = np.where(np.isfinite(xl), c1 - c0 + 1, 0).clip(0)
        if cnt.sum() == 0:
            continue
        tp = np.repeat(t, cnt)
        py = np.repeat(row, cnt)
        px = np.repeat(c0, cnt) + (np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt))
        cx, cyp = px + 0.5, py + 0.5
        ax, ay = x[tp, 0], y[tp, 0]
        w1 = ((cx - ax) * (y[tp, 2] - ay) - (x[tp, 2] - ax) * (cyp - ay)) / area2[tp]  # weight of vertex 1
        w2 = ((x[tp, 1] - ax) * (cyp - ay) - (cx - ax) * (y[tp, 1] - ay)) / area2[tp]  # weight of vertex 2
        zv = ((1 - w1 - w2) * z[tp, 0] + w1 * z[tp, 1] + w2 * z[tp, 2]).astype(np.float32)
        pix = py * w + px
        keep = zv < depth[pix]
        pix, zv, tp = pix[keep], zv[keep], tp[keep]
        order = np.argsort(-zv, kind="stable")  # far first, nearest written last
        pix, zv, tp = pix[order], zv[order], tp[order]
        depth[pix] = zv
        rgb[pix] = colors[tp]
        mat[pix] = mats[tp]
    return rgb.reshape(h, w, 3), depth.reshape(h, w), mat.reshape(h, w)


def render_model(model: Model, view: str = "front", width_px: int = 1600, margin: float = 0.06) -> Image.Image:
    """Transparent-background RGBA render of ``model``."""
    rot = view_matrix(view)
    tris, cols, mats = [], [], []
    ldir = LIGHT / np.linalg.norm(LIGHT)
    half = ldir + np.array([0.0, 0.0, 1.0])
    half /= np.linalg.norm(half)
    for p in model.parts:
        m = p.mesh_wall
        v = m.vertices @ rot.T
        f = m.faces
        t = v[f]
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        lit = AMBIENT + DIFFUSE * np.clip(n @ ldir, 0, 1)
        ks, shin, tex = FINISH_SHADING.get(p.meta.get("finish", "matte"), FINISH_SHADING["matte"])
        spec = ks * np.clip(n @ half, 0, 1) ** shin
        base = _hex(p.color)
        cols.append(np.clip(base[None] * lit[:, None] + spec[:, None], 0, 1))
        mats.append(np.full(len(f), tex, dtype=np.uint8))
        tris.append(t)
    tris = np.concatenate(tris)
    cols = np.concatenate(cols).astype(np.float32)
    mats = np.concatenate(mats)
    # camera looks down -z (towards the wall): screen x = x, screen y = -y, depth = -z (near = small)
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    ext = hi - lo
    ss = SUPERSAMPLE
    inner = width_px * ss * (1 - 2 * margin)
    k = inner / max(ext[0], ext[1])
    w = int(width_px * ss)
    h = int(round(ext[1] * k + 2 * margin * width_px * ss))
    h = max(h, 8)
    ox = (w - ext[0] * k) / 2
    oy = (h - ext[1] * k) / 2
    px = np.empty(tris.shape[:2] + (2,), dtype=np.float64)
    px[..., 0] = (tris[..., 0] - lo[0]) * k + ox
    px[..., 1] = (hi[1] - tris[..., 1]) * k + oy
    z = -tris[..., 2]
    rgb, depth, mat = _raster(px, z, cols, w, h, mats)
    rgb = _apply_textures(rgb, mat)
    alpha = np.isfinite(depth).astype(np.float32)
    # premultiplied downsample for clean edges
    pm = np.concatenate([rgb * alpha[..., None], alpha[..., None]], axis=2)
    pm = pm.reshape(h // ss, ss, w // ss, ss, 4).mean(axis=(1, 3)) if h % ss == 0 else _box(pm, ss)
    a = pm[..., 3:4]
    out = np.where(a > 0, pm[..., :3] / np.maximum(a, 1e-6), 0.0)
    img = np.concatenate([out, a], axis=2)
    return Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA")


def _apply_textures(rgb: np.ndarray, mat: np.ndarray) -> np.ndarray:
    """Cheap screen-space textures for wood / marble / sparkle / silk (deterministic)."""
    if not mat.any():
        return rgb
    h, w = mat.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rng = np.random.default_rng(7)
    noise = rng.random((h, w), dtype=np.float32)
    out = rgb.copy()

    def mul(mask, factor):
        out[mask] = np.clip(out[mask] * factor[mask][:, None], 0, 1)

    scale = max(w, 1) / 3200.0
    # silk: soft diagonal sheen bands
    mul(mat == 1, 1.0 + 0.05 * np.sin((xx + 0.6 * yy) * 0.012 / scale))
    # wood: grain lines along x with slight waviness
    grain = 1.0 + 0.07 * np.sin(yy * 0.11 / scale + 4 * np.sin(xx * 0.004 / scale)) + 0.03 * (noise - 0.5)
    mul(mat == 2, grain)
    # marble: low-frequency veins
    vein = np.abs(np.sin((xx * 0.7 + yy * 0.4) * 0.01 / scale + 3 * np.sin(yy * 0.007 / scale)))
    mul(mat == 3, 0.93 + 0.1 * vein ** 6 + 0.04 * (noise - 0.5))
    # sparkle: sparse bright speckles
    sp = (mat == 4) & (noise > 0.985)
    out[sp] = np.clip(out[sp] + 0.35, 0, 1)
    # translucent: slightly lighter
    mul(mat == 5, np.full((h, w), 1.05, dtype=np.float32))
    return out


def _box(a: np.ndarray, ss: int) -> np.ndarray:
    h, w = (a.shape[0] // ss) * ss, (a.shape[1] // ss) * ss
    a = a[:h, :w]
    return a.reshape(h // ss, ss, w // ss, ss, 4).mean(axis=(1, 3))


def render_views(model: Model, out_dir: str | Path, width_px: int = 1600) -> dict[str, Path]:
    out = Path(out_dir)
    paths = {}
    for view, name in (("front", "render_front.png"), ("34", "render_34.png")):
        img = render_model(model, view, width_px)
        paths[view] = out / name
        img.save(paths[view])
    return paths


def render_dims(model: Model, out_path: str | Path, overall: dict | None = None, title: str | None = None) -> Path:
    """Front view with dimension arrows and cm labels (Genişlik / Yükseklik / Derinlik)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    lo = np.min([p.mesh_wall.bounds[0] for p in model.parts], axis=0)
    hi = np.max([p.mesh_wall.bounds[1] for p in model.parts], axis=0)
    W, H, D = (hi - lo)
    if overall:
        W, H, D = overall["width_mm"], overall["height_mm"], overall["depth_mm"]
    img = np.asarray(render_model(model, "front", 1400, margin=0.0))
    # crop to the content so the extent maps exactly onto mm
    ys, xs = np.nonzero(img[..., 3] > 0)
    img = img[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

    pad = max(W, H) * 0.14
    side_w = max(D / max(H, 1e-6) * H, 0) if D else 0
    gap = pad * 0.9
    fig_w = (W + 2 * pad + gap + side_w + pad) / max(W, H) * 9
    fig_h = (H + 2 * pad) / max(W, H) * 9 + (0.6 if title else 0)
    fig, ax = plt.subplots(figsize=(max(fig_w, 4), max(fig_h, 3)), dpi=150)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    ax.imshow(img, extent=(0, W, 0, H), interpolation="lanczos", zorder=2)
    col, fs = "#1a5fb4", 11
    arrow = dict(arrowstyle="<->", color=col, lw=1.4, shrinkA=0, shrinkB=0)
    yb = -pad * 0.45
    ax.annotate("", (0, yb), (W, yb), arrowprops=arrow)
    ax.plot([0, 0], [0, yb * 1.15], color=col, lw=0.8)
    ax.plot([W, W], [0, yb * 1.15], color=col, lw=0.8)
    ax.text(W / 2, yb - pad * 0.12, f"Genişlik: {W / 10:.1f} cm", ha="center", va="top", color=col, fontsize=fs, fontweight="bold")
    xl = -pad * 0.45
    ax.annotate("", (xl, 0), (xl, H), arrowprops=arrow)
    ax.plot([0, xl * 1.15], [0, 0], color=col, lw=0.8)
    ax.plot([0, xl * 1.15], [H, H], color=col, lw=0.8)
    ax.text(xl - pad * 0.12, H / 2, f"Yükseklik: {H / 10:.1f} cm", ha="right", va="center", rotation=90, color=col, fontsize=fs, fontweight="bold")
    xmax = W + pad
    if D:
        # side profile: depth x height, shaded rectangle with the depth arrow
        sx = W + gap
        ax.add_patch(plt.Rectangle((sx, 0), D, H, facecolor="#e4e6ea", edgecolor="#555", lw=1, zorder=2))
        ax.text(sx + D / 2, H + pad * 0.1, "yan görünüm", ha="center", va="bottom", color="#555", fontsize=8)
        yd = -pad * 0.45
        ax.annotate("", (sx, yd), (sx + D, yd), arrowprops=arrow)
        ax.text(sx + D / 2, yd - pad * 0.12, f"Derinlik: {D / 10:.1f} cm", ha="center", va="top", color=col, fontsize=fs, fontweight="bold")
        xmax = sx + max(D, pad * 2.2)
    ax.set_xlim(-pad * 1.0, xmax)
    ax.set_ylim(-pad * 1.0, H + pad * 0.45)
    ax.set_aspect("equal")
    ax.axis("off")
    if title:
        fig.suptitle(title, fontsize=12, color="#333")
    out = Path(out_path)
    fig.savefig(out, facecolor=BG, bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)
    return out


# --------------------------------------------------------------------------- #
# Generic mesh renders and 3D previews (Maker, Glow, Topo and Studio share these)
# --------------------------------------------------------------------------- #
Z_UP = np.array([[1.0, 0, 0], [0, 0, 1], [0, -1, 0]])  # print orientation (z up) -> screen y up, y away from the viewer


def view_rotation(azim_deg: float, elev_deg: float) -> np.ndarray:
    """Turn ``azim`` degrees about the vertical axis, then tilt ``elev`` degrees towards the viewer (screen z = depth)."""
    a, b = np.radians(azim_deg), np.radians(elev_deg)
    ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    rx = np.array([[1, 0, 0], [0, np.cos(b), -np.sin(b)], [0, np.sin(b), np.cos(b)]])
    return rx @ ry


def render_meshes(items, rot: np.ndarray, *, width_px: int = 1200, margin: float = 0.05, bg=None,
                  ambient: float = AMBIENT, diffuse: float = DIFFUSE, light=LIGHT, light_in_model: bool = False,
                  cull: bool = True, supersample: int = SUPERSAMPLE) -> Image.Image:
    """Orthographic z-buffer render of coloured meshes. ``items``: (mesh, '#RRGGBB') or (mesh, colour, options) with
    options ``gloss`` (0..1 specular highlight, smooth normals), ``emissive`` (0..1, LED faces glow at full colour).

    ``rot`` maps model coordinates to the screen (x right, y up, z towards the viewer). ``light_in_model``: the light
    is fixed to the model instead of the camera. ``cull``: skip faces turned away (closed meshes only). Returns RGBA
    with a transparent background, or RGB over ``bg`` (r, g, b)."""
    ldir = np.asarray(light, float) / np.linalg.norm(light)
    half = (ldir + [0, 0, 1]) / np.linalg.norm(ldir + [0, 0, 1])  # Blinn half vector, viewer on +z
    tris, cols = [], []
    for it in items:
        mesh, color = it[0], it[1]
        opt = it[2] if len(it) > 2 and isinstance(it[2], dict) else {}
        gloss, emis = float(opt.get("gloss", 0) or 0), float(opt.get("emissive", 0) or 0)
        t = (mesh.vertices @ rot.T)[mesh.faces]
        n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        keep = n[:, 2] > 0 if cull else np.ones(len(n), bool)
        if gloss:  # smooth shading: face normal = mean of its vertex normals (no facet glitter)
            vn = mesh.vertex_normals @ rot.T
            n = vn[mesh.faces].mean(axis=1)
            n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
        nl = (mesh.face_normals @ ldir) if light_in_model else (n @ ldir)
        t, n, nl = t[keep], n[keep], nl[keep]
        base = _hex(color)[None]
        c = base * (ambient + diffuse * np.clip(nl, 0, 1))[:, None]
        if gloss:
            c = c + gloss * np.clip(n @ half, 0, 1)[:, None] ** 40
        if emis:
            c = c * (1 - emis) + base * emis
        tris.append(t)
        cols.append(np.clip(c, 0, 1))
    tris = np.concatenate(tris)
    cols = np.concatenate(cols).astype(np.float32)
    lo, hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
    ext = hi - lo
    ss = supersample
    k = width_px * ss * (1 - 2 * margin) / max(ext[0], ext[1], 1e-6)
    w = int(width_px * ss)
    h = max(int(round(ext[1] * k + 2 * margin * width_px * ss)) // ss * ss, 8)
    px = np.empty(tris.shape[:2] + (2,), dtype=np.float64)
    px[..., 0] = (tris[..., 0] - lo[0]) * k + (w - ext[0] * k) / 2
    px[..., 1] = (hi[1] - tris[..., 1]) * k + (h - ext[1] * k) / 2
    rgb, depth, _ = _raster(px, -tris[..., 2], cols, w, h)
    alpha = np.isfinite(depth).astype(np.float32)
    pm = np.concatenate([rgb * alpha[..., None], alpha[..., None]], axis=2)
    pm = pm.reshape(h // ss, ss, w // ss, ss, 4).mean(axis=(1, 3))
    a = pm[..., 3:4]
    if bg is not None:  # composite over an opaque background
        img = pm[..., :3] + (1 - a) * (np.array(bg[:3], np.float32) / 255)
        return Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
    img = np.concatenate([np.where(a > 0, pm[..., :3] / np.maximum(a, 1e-6), 0.0), a], axis=2)
    return Image.fromarray((np.clip(img, 0, 1) * 255 + 0.5).astype(np.uint8), "RGBA")


def decimate(mesh, target_faces: int):
    """Fewer triangles for previews (fast-simplification); the mesh as is when it is small or the library is missing."""
    import trimesh

    if len(mesh.faces) <= target_faces:
        return mesh
    try:
        import fast_simplification

        v, f = fast_simplification.simplify(np.asarray(mesh.vertices, np.float32), np.asarray(mesh.faces, np.int64),
                                            target_reduction=1 - target_faces / len(mesh.faces))
        return trimesh.Trimesh(v, f, process=False)
    except Exception:  # pragma: no cover - preview only
        return mesh


def write_glb(items, path: str | Path, *, max_faces: int | None = None, z_up: bool = False, roughness: float = 0.85) -> Path:
    """Binary glTF preview: one node per (mesh, '#RRGGBB'[, name]) with a matte PBR colour. ``max_faces`` thins
    big models; ``z_up`` turns print-orientation meshes to glTF's y-up."""
    import trimesh

    total = sum(len(it[0].faces) for it in items) or 1
    scene = trimesh.Scene()
    for i, it in enumerate(items):
        m = it[0] if max_faces is None else decimate(it[0], max(2000, int(max_faces * len(it[0].faces) / total)))
        m = m.copy()
        rgba = [float(x) for x in _hex(it[1])] + [1.0]
        m.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=rgba, metallicFactor=0.0, roughnessFactor=roughness))
        if z_up:
            m.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
        name = it[2] if len(it) > 2 and isinstance(it[2], str) else f"part_{i}"
        scene.add_geometry(m, node_name=name, geom_name=name)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(scene.export(file_type="glb"))
    return path
