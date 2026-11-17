"""Vessel generator: bowls and vases turned around the vertical axis (Japanese forms: chawan, donburi, hira, tsubo),
with an optional foot ring (kodai) and a carved surface (shinogi grooves, twisted ribs, mentori facets, ripples).

The outer body is revolved from a profile, refined and warped for the surface pattern, then the smooth cavity is
subtracted: the inside stays smooth, the pattern only touches the outside. Printed upright, no supports: the foot ring
meets the body with a 45 deg chamfer and the walls' overhang is checked."""
from __future__ import annotations

import math

import numpy as np
from manifold3d import CrossSection, Manifold

from .. import core, estimate
from .base import BuildResult, Generator, Param, Part

SEGMENTS = 256
FORMS_TR = {
    "chawan": "Chawan (çay kasesi)",
    "donburi": "Donburi (derin kase)",
    "hira": "Hira (sığ kase)",
    "tsubo": "Tsubo (karınlı vazo)",
    "tsutsu": "Tsutsu (silindir vazo)",
}
DEFAULT_SIZE = {"chawan": (120, 75), "donburi": (150, 80), "hira": (160, 55), "tsubo": (110, 160), "tsutsu": (80, 180)}
SURFACES_TR = {"smooth": "Düz", "shinogi": "Shinogi (dikey oluk)", "twist": "Burgulu oluk", "mentori": "Mentori (köşeli yüz)",
               "wave": "Yatay dalga"}
MAX_OVERHANG = 55.0  # deg from vertical; steeper needs supports


def form_radius(form: str, t: np.ndarray) -> np.ndarray:
    """Outer radius as a fraction of the largest radius, ``t`` = 0 (bottom of the body) .. 1 (rim)."""
    t = np.clip(t, 0.0, 1.0)
    def ease(a: float, k: float) -> np.ndarray:  # a .. 1, finite slope at the base (printable), flat at the rim
        return a + (1 - a) * (1 - (1 - t) ** k)

    if form == "chawan":  # wide base, near-vertical walls that open slightly toward the rim
        return ease(0.66, 1.8)
    if form == "donburi":  # deep and round
        return ease(0.50, 2.0)
    if form == "hira":  # shallow and wide (starts wide so the outside stays printable)
        return ease(0.68, 1.5)
    if form == "tsubo":  # belly at ~40 %, narrow neck, small flared mouth
        belly = np.exp(-((t - 0.42) / 0.33) ** 2)
        return np.maximum(0.42 + 0.58 * belly, 0.38 + 0.25 * np.clip((t - 0.86) / 0.14, 0, 1) ** 2)
    if form == "tsutsu":
        return 0.9 + 0.1 * t
    raise ValueError(f"bilinmeyen form: {form}")


def profile(v: dict) -> tuple[np.ndarray, np.ndarray, float]:
    """Outer profile (r, z) from the foot to the rim, and the height where the body starts."""
    R = v["diameter_mm"] / 2
    H = v["height_mm"]
    z_body = 0.0
    pts = []
    t = np.linspace(0, 1, 160)
    r = R * form_radius(v["form"], t)
    if v["foot"]:
        rf = r[0] * v["foot_pct"] / 100
        step = r[0] - rf  # 45 deg chamfer from the foot ring out to the body
        z_body = v["foot_h"] + step
        pts += [(rf, 0.0), (rf, v["foot_h"])]
    z = z_body + t * (H - z_body)
    pts += list(zip(r, z))
    return np.array(pts), np.array([p[1] for p in pts]), z_body


def _revolve(poly: list[tuple[float, float]]) -> Manifold:
    return Manifold.revolve(CrossSection([poly]), SEGMENTS)


def surface_offset(v: dict, theta: np.ndarray, t: np.ndarray, r: np.ndarray) -> np.ndarray:
    """Radial change of the outer surface (mm) at angle ``theta`` and height fraction ``t`` of the body."""
    n, d, kind = v["ribs"], v["rib_mm"], v["surface"]
    fade = np.clip(t / 0.06, 0, 1) * np.clip((1 - t) / 0.08, 0, 1)  # keep the rim and the base edge clean
    if kind == "shinogi":
        off = -d * (0.5 + 0.5 * np.cos(n * theta)) ** 3
    elif kind == "twist":
        off = -d * (0.5 + 0.5 * np.cos(n * (theta + math.radians(v["twist_deg"]) * t))) ** 3
    elif kind == "mentori":
        phi = np.mod(theta, 2 * math.pi / n) - math.pi / n
        off = r * (math.cos(math.pi / n) / np.cos(phi) - 1.0)  # flat faces cut into the round body (corners stay)
        off = np.maximum(off, -d * 3)
    elif kind == "wave":
        off = -d * (0.5 + 0.5 * np.sin(2 * math.pi * v["ribs"] / 4 * t))
    else:
        return np.zeros_like(theta)
    return off * fade


def build(v: dict) -> BuildResult:
    warnings, notes = [], []
    R, H, wall = v["diameter_mm"] / 2, v["height_mm"], v["wall_mm"]
    if v["foot"] and v["foot_h"] + 10 > H:
        raise ValueError("Ayak, kabın yüksekliğine göre çok yüksek.")
    pts, _, z_body = profile(v)
    rr, zz = pts[:, 0], pts[:, 1]
    body_r = rr[-160:]
    body_z = zz[-160:]

    # overhang of the outside (deg from vertical)
    dr, dz = np.diff(body_r), np.diff(body_z)
    over = np.degrees(np.arctan2(np.maximum(dr, 0), dz))
    if over.max() > MAX_OVERHANG:
        warnings.append(f"Dış yüzey {over.max():.0f}° sarkıyor (en çok {MAX_OVERHANG:g}° desteksiz basılır); "
                        "yüksekliği artırın ya da formu değiştirin.")
    pattern_depth = v["rib_mm"] * (3 if v["surface"] == "mentori" else 1) if v["surface"] != "smooth" else 0.0
    if v["surface"] == "mentori":
        pattern_depth = R * (1 - math.cos(math.pi / v["ribs"]))
    if v["surface"] != "smooth" and wall - pattern_depth < 1.2:
        raise ValueError(f"Desen için duvar ince: oluk derinliği {pattern_depth:.1f} mm, duvar {wall:g} mm. "
                         f"Duvar en az {pattern_depth + 1.2:.1f} mm olmalı ya da oluğu sığlaştırın"
                         + (" (mentori'de yüz sayısını artırın)." if v["surface"] == "mentori" else "."))

    outer = _revolve([(0.0, 0.0), *map(tuple, pts), (0.0, H)])
    if v["surface"] != "smooth":
        outer = outer.refine_to_length(1.2)
        n_ribs = v["ribs"]

        def warp(p):
            p = np.array(p, dtype=np.float64)
            x, y, z = p[:, 0], p[:, 1], p[:, 2]
            r = np.hypot(x, y)
            theta = np.arctan2(y, x)
            t = (z - z_body) / max(H - z_body, 1e-6)
            body = (z > z_body + 0.5) & (z < H - 0.05) & (r > 0.3 * R)
            off = np.where(body, surface_offset(v, theta, t, r), 0.0)
            k = np.where(r > 1e-6, (r + off) / np.maximum(r, 1e-6), 1.0)
            p[:, 0] *= k
            p[:, 1] *= k
            return p

        outer = outer.warp_batch(warp)

    # cavity: offset inward by the wall measured across the slope, floor ``base_mm`` above the body start
    slope = np.gradient(body_r, body_z)
    inner_r = body_r - wall * np.sqrt(1 + slope ** 2)
    floor_z = z_body + v["base_mm"]
    keep = body_z >= floor_z
    ir, iz = inner_r[keep], body_z[keep]
    if len(ir) < 3 or ir.min() <= 2:
        raise ValueError("Duvar ya da taban bu boyut için çok kalın; kabın içi kalmıyor.")
    r_floor = float(np.interp(floor_z, body_z, inner_r))
    cavity = _revolve([(0.0, floor_z), (r_floor, floor_z), *zip(ir, iz), (float(ir[-1]), H + 2), (0.0, H + 2)])
    body = outer - cavity
    mesh = core.to_trimesh(body)
    if not mesh.is_watertight:
        warnings.append("Model tam kapalı değil; dilimlemeden önce OrcaSlicer onarımına bakın.")

    e = estimate.part_estimate(mesh, "PLA", "part")
    part = Part("body", FORMS_TR[v["form"]].split(" (")[0], mesh, v["color"], "PLA",
                {"role": "part", "product": True, "grams": e.grams, "minutes": e.minutes, "cost_try": e.try_})
    ext = mesh.extents
    notes += [
        f"Ölçü: Ø{ext[0]:.0f} × {ext[2]:.0f} mm, duvar {wall:g} mm, taban {v['base_mm']:g} mm"
        + (f", ayak {v['foot_h']:g} mm" if v["foot"] else "") + ".",
        f"Tahmin: ~{e.grams:.0f} g PLA, ~{e.minutes / 60:.1f} saat (varsayım fiyatlarla ≈ {e.try_:.0f} TL).",
        "Baskı: ayak (ya da taban) tablada, destek yok; duvar için 3 çevre, %15 dolgu. Ağızda dikiş izi görünmesin diye "
        "OrcaSlicer'da dikiş konumunu 'arka' ya da 'hizalı' seçin.",
        "Gıda: FDM baskının katman aralıkları yıkanamaz. Sıcak yemek, sıvı ve bulaşık makinesi için uygun değildir; "
        "kuru ve kabuklu ürün, takı, anahtar ya da dekor için satın. Gıdaya uygun kaplama ayrı bir iştir.",
    ]
    if v["surface"] != "smooth":
        notes.append(f"Yüzey: {SURFACES_TR[v['surface']]}, {v['ribs']} " + ("yüz" if v["surface"] == "mentori" else "oluk")
                     + f"; desen yalnızca dışta, içi pürüzsüz.")
    meta = {"size_mm": [round(float(x), 1) for x in ext], "max_overhang_deg": round(float(over.max()), 1),
            "grams": {"body": e.grams}, "cost_try": round(e.try_, 1), "form": v["form"], "surface": v["surface"]}
    return BuildResult([part], warnings, meta, notes)


GENERATOR = Generator(
    key="vessel", label="Kase / vazo (döner form)", group="Ev ve dekor",
    description="Japon formlarında kase ve vazo: chawan, donburi, hira, tsubo, tsutsu. Ayak halkası (kodai), "
                "dışta shinogi oluk, burgu, mentori köşeli yüz ya da dalga deseni; içi pürüzsüz. Desteksiz basılır.",
    params=[
        Param("form", "Form", "choice", "chawan", options=list(FORMS_TR.items()), section="Form"),
        Param("diameter_mm", "En geniş çap", "number", 120, min=40, max=240, step=1, unit="mm", section="Form"),
        Param("height_mm", "Yükseklik", "number", 75, min=20, max=240, step=1, unit="mm", section="Form"),
        Param("wall_mm", "Duvar kalınlığı", "number", 3.0, min=1.2, max=8, step=0.2, unit="mm", section="Form"),
        Param("base_mm", "Taban kalınlığı", "number", 3.0, min=1.2, max=10, step=0.2, unit="mm", section="Form"),
        Param("foot", "Ayak halkası (kodai)", "bool", True, section="Ayak"),
        Param("foot_h", "Ayak yüksekliği", "number", 6, min=2, max=20, step=0.5, unit="mm", section="Ayak", show_if={"foot": True}),
        Param("foot_pct", "Ayak çapı", "int", 70, min=40, max=95, unit="%", section="Ayak", show_if={"foot": True},
              help="Gövde tabanına göre; ayaktan gövdeye 45° pah ile geçilir"),
        Param("surface", "Dış yüzey", "choice", "smooth", options=list(SURFACES_TR.items()), section="Yüzey"),
        Param("ribs", "Oluk / yüz sayısı", "int", 24, min=4, max=72, section="Yüzey", show_if={"surface": ["shinogi", "twist", "mentori", "wave"]}),
        Param("rib_mm", "Oluk derinliği", "number", 1.2, min=0.4, max=4, step=0.1, unit="mm", section="Yüzey",
              show_if={"surface": ["shinogi", "twist", "wave"]}),
        Param("twist_deg", "Burgu açısı", "number", 60, min=-180, max=180, step=5, unit="°", section="Yüzey", show_if={"surface": "twist"}),
        Param("color", "Renk", "color", "#E9E4DA", section="Baskı"),
    ],
    build=build,
)
