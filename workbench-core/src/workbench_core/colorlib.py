"""Colour math and universal colour codes: HEX, RGB, CIELAB, nearest RAL Classic, English name.

ΔE is CIEDE2000. Named colours come from matplotlib's XKCD + CSS4 tables; RAL Classic from
``templates/ral_classic.json`` (approximate sRGB renderings of the public RAL Classic palette).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

RAL_FILE = Path(__file__).resolve().parents[2] / "templates" / "ral_classic.json"

# canonical filament colour names: (hex, Turkish, English)
CANON = [
    ("#222222", "siyah", "black"), ("#F5F5F5", "beyaz", "white"), ("#C0392B", "kırmızı", "red"),
    ("#2980B9", "mavi", "blue"), ("#27AE60", "yeşil", "green"), ("#F1C40F", "sarı", "yellow"),
    ("#E67E22", "turuncu", "orange"), ("#8E44AD", "mor", "purple"), ("#E84393", "pembe", "pink"),
    ("#7F8C8D", "gri", "grey"), ("#D4AF37", "altın", "gold"), ("#C0C0C0", "gümüş", "silver"),
    ("#6D4C41", "kahverengi", "brown"),
]

# filament palette of every colour picker (Maker, Topo, Studio): (hex, Turkish name)
PALETTE = [
    ("#FFFFFF", "beyaz"), ("#F5F0E6", "krem"), ("#111111", "siyah"), ("#8A8D8F", "gri"), ("#C0C0C0", "gümüş"),
    ("#E0453A", "kırmızı"), ("#D62828", "koyu kırmızı"), ("#C8664A", "kiremit"), ("#F28C28", "turuncu"), ("#FFD23F", "sarı"),
    ("#D4AF37", "altın"), ("#3E9B4F", "yeşil"), ("#7A9B76", "adaçayı"), ("#6EC6FF", "açık mavi"), ("#1F6FB2", "mavi"),
    ("#1B2A4A", "lacivert"), ("#7B4FA0", "mor"), ("#F3A6C8", "pembe"), ("#8B5A2B", "kahverengi"), ("#C9A27E", "ahşap"),
    ("#2A3B4C", "antrasit"),
]


def palette_path():
    """Your filament palette file (optional): ``$WORKBENCH_PALETTE``, else ``$WORKBENCH_CONFIG/renk_paleti.yaml``,
    else ``$WORKBENCH_ROOT/config/renk_paleti.yaml`` (the layout of the Open Workbench bot), else
    ``$STUDIO_HOME/renk_paleti.yaml`` (default ``~/.local/share/workbench-studio``). Format:
    ``examples/palette.example.yaml`` at the repository root."""
    import os
    from pathlib import Path

    if os.environ.get("WORKBENCH_PALETTE"):
        return Path(os.environ["WORKBENCH_PALETTE"]).expanduser()
    if os.environ.get("WORKBENCH_CONFIG"):
        return Path(os.environ["WORKBENCH_CONFIG"]).expanduser() / "renk_paleti.yaml"
    if os.environ.get("WORKBENCH_ROOT"):
        return Path(os.environ["WORKBENCH_ROOT"]).expanduser() / "config" / "renk_paleti.yaml"
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return Path(os.environ.get("STUDIO_HOME") or data_home / "workbench-studio").expanduser() / "renk_paleti.yaml"


def filament_palette() -> list[tuple[str, str]]:
    """Filament colours for the colour pickers: your own palette file (``palette_path()``, measured HEX values of the
    filaments you own) first, then the generic PALETTE. Without a palette file only PALETTE."""
    out: list[tuple[str, str]] = []
    yol = palette_path()
    if yol.is_file():
        try:
            import yaml

            for r in (yaml.safe_load(yol.read_text(encoding="utf-8")) or {}).get("renkler") or []:
                if r.get("hex") and r.get("ad"):
                    ad = str(r["ad"]) + (f" ({r['marka']})" if r.get("marka") else "") + ("" if r.get("dogrulandi") else " ~")
                    out.append((norm_hex(r["hex"]), ad))
        except Exception:
            out = []
    gorulen = {h for h, _ in out}
    return out + [(h, n) for h, n in PALETTE if h not in gorulen]


def basic_names() -> list[str]:
    """Named colours for dropdowns (Kaligraf, Glow): the canonical filament names."""
    return [tr for _, tr, _ in CANON]


def norm_hex(h: str) -> str:
    s = str(h).strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{3}", s):
        s = "".join(c * 2 for c in s)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        raise ValueError(f"invalid HEX colour {h!r}")
    return "#" + s.upper()


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = norm_hex(h)
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


def rgb_to_hex(rgb) -> str:
    r, g, b = (int(round(float(v))) for v in rgb)
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, v)) for v in (r, g, b)))


def rgb_to_lab(rgb) -> np.ndarray:
    """sRGB (0-255, D65) -> CIELAB; accepts (3,) or (n, 3)."""
    a = np.asarray(rgb, dtype=float) / 255.0
    lin = np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = lin @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], axis=-1)


def hex_to_lab(h: str) -> np.ndarray:
    return rgb_to_lab(hex_to_rgb(h))


def delta_e2000(lab1, lab2) -> np.ndarray:
    """CIEDE2000 between Lab arrays (broadcasting over leading dimensions)."""
    l1, a1, b1 = (np.asarray(lab1, dtype=float)[..., i] for i in range(3))
    l2, a2, b2 = (np.asarray(lab2, dtype=float)[..., i] for i in range(3))
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    cm = (c1 + c2) / 2
    g = 0.5 * (1 - np.sqrt(cm**7 / (cm**7 + 25.0**7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dl, dc = l2 - l1, c2p - c1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(c1p * c2p == 0, 0, dh)
    dH = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh) / 2)
    lp, cp = (l1 + l2) / 2, (c1p + c2p) / 2
    hs = h1p + h2p
    hp = np.where(c1p * c2p == 0, hs, np.where(np.abs(h1p - h2p) <= 180, hs / 2, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2)))
    t = (1 - 0.17 * np.cos(np.radians(hp - 30)) + 0.24 * np.cos(np.radians(2 * hp))
         + 0.32 * np.cos(np.radians(3 * hp + 6)) - 0.20 * np.cos(np.radians(4 * hp - 63)))
    sl = 1 + 0.015 * (lp - 50) ** 2 / np.sqrt(20 + (lp - 50) ** 2)
    sc, sh = 1 + 0.045 * cp, 1 + 0.015 * cp * t
    rt = -2 * np.sqrt(cp**7 / (cp**7 + 25.0**7)) * np.sin(np.radians(60 * np.exp(-(((hp - 275) / 25) ** 2))))
    return np.sqrt((dl / sl) ** 2 + (dc / sc) ** 2 + (dH / sh) ** 2 + rt * (dc / sc) * (dH / sh))


@dataclass(frozen=True)
class Palette:
    names: tuple[str, ...]
    hexes: tuple[str, ...]
    labs: np.ndarray

    def nearest(self, hex_color: str, n: int = 1) -> list[tuple[str, str, float]]:
        """[(name, hex, ΔE2000)] sorted by distance."""
        d = delta_e2000(self.labs, hex_to_lab(hex_color))
        idx = np.argsort(d)[:n]
        return [(self.names[i], self.hexes[i], float(d[i])) for i in idx]


@lru_cache(maxsize=1)
def ral_palette() -> Palette:
    items = json.loads(RAL_FILE.read_text(encoding="utf-8"))["colors"]
    return Palette(tuple(f"RAL {c['code']}|{c['name']}" for c in items), tuple(c["hex"] for c in items),
                   rgb_to_lab([hex_to_rgb(c["hex"]) for c in items]))


@lru_cache(maxsize=1)
def name_palette() -> Palette:
    import matplotlib.colors as mc

    pairs = {k.replace("xkcd:", ""): v for k, v in mc.XKCD_COLORS.items()}
    for k, v in mc.CSS4_COLORS.items():
        pairs.setdefault(k, v)
    names = tuple(pairs)
    hexes = tuple(norm_hex(pairs[n]) for n in names)
    return Palette(names, hexes, rgb_to_lab([hex_to_rgb(h) for h in hexes]))


def nearest_ral(hex_color: str) -> dict:
    name, hx, de = ral_palette().nearest(hex_color)[0]
    code, desc = name.split("|")
    return {"code": code, "name": desc, "hex": hx, "delta_e": round(de, 1)}


def english_name(hex_color: str) -> str:
    """Canonical filament name for exact matches, else the nearest XKCD/CSS colour name."""
    h = norm_hex(hex_color)
    for c, _, en in CANON:
        if c == h:
            return en
    return name_palette().nearest(h)[0][0]


def canonical_tr(hex_color: str) -> str:
    """Turkish name of the nearest canonical filament colour."""
    lab = hex_to_lab(hex_color)
    best = min(CANON, key=lambda c: float(delta_e2000(hex_to_lab(c[0]), lab)))
    return best[1]


def color_code(hex_color: str) -> dict:
    """Universal colour code: HEX, RGB, Lab, nearest RAL Classic and English name."""
    h = norm_hex(hex_color)
    rgb = hex_to_rgb(h)
    lab = hex_to_lab(h)
    ral = nearest_ral(h)
    name = english_name(h)
    return {"hex": h, "rgb": list(rgb), "lab": [round(float(v), 1) for v in lab], "ral": ral, "name_en": name,
            "text": f"{name} ({h}, ~{ral['code']})"}


# --------------------------------------------------------------------------- #
# Surface finish ("Yüzey"): render-only, per colour
# --------------------------------------------------------------------------- #
FINISHES = ("matte", "glossy", "silk", "wood", "marble", "sparkle")
FINISH_TR = {"matte": "mat", "glossy": "parlak", "silk": "ipek", "wood": "ahşap görünümlü", "marble": "mermer görünümlü",
             "sparkle": "simli"}
FINISH_UI = {"matte": "mat", "glossy": "parlak", "silk": "ipek", "wood": "ahşap", "marble": "mermer", "sparkle": "simli"}
_FINISH_ALIASES = {**{k: k for k in FINISHES}, **{v: k for k, v in FINISH_UI.items()}, "mat": "matte", "parlak": "glossy",
                   "ipek": "silk", "ahşap": "wood", "ahsap": "wood", "mermer": "marble", "simli": "sparkle"}


def norm_finish(value: str | None) -> str:
    """'mat' / 'matte' / 'İpek' ... -> internal finish id (default matte)."""
    if value in (None, ""):
        return "matte"
    key = str(value).strip().lower().replace("i̇", "i")
    if key not in _FINISH_ALIASES:
        raise ValueError(f"unknown finish {value!r}: use {', '.join(FINISH_UI.values())}")
    return _FINISH_ALIASES[key]


def descriptor(hex_color: str, finish: str | None = "matte") -> dict:
    """Universal colour code plus finish words, as written to job.json and the AI prompts."""
    code = color_code(hex_color)
    fin = norm_finish(finish)
    name_tr = canonical_tr(hex_color)
    return {
        **code, "finish": fin, "finish_tr": FINISH_TR[fin], "name_tr": name_tr,
        "text_en": f"{fin} {code['name_en'].lower()} PLA ({code['hex']}, close to {code['ral']['code']})",
        "text_tr": f"{FINISH_TR[fin]} {name_tr} PLA ({code['hex']}, {code['ral']['code']}'e yakın)",
    }
