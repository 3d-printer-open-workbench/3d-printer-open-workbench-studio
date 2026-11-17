"""Hardware library editing for the "Donanım" tab: raw dict <-> table rows, validation, save/reset of the user override."""
from __future__ import annotations

import copy
import re
from pathlib import Path

import yaml

from . import hardware as hw_mod
from .hardware import DEFAULT_HARDWARE, parse_hardware

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_]*$")
LED_COLS = ["id", "ad", "adresl.", "genişlik mm", "kalınlık mm", "kesim aralığı mm", "min bük. yarıçapı mm", "W/m",
            "mA/LED", "LED/m", "fiyat TL/m", "not"]
CTRL_COLS = ["id", "ad", "uzunluk mm", "genişlik mm", "yükseklik mm", "kablo tarafı", "boşluk mm", "desteklenen LED'ler", "fiyat TL", "not"]
DIFF_COLS = ["id", "ad", "renk", "fiyat TL/kg", "kalınlık mm (led:değer, ...)", "min LED-yüz aralığı mm (led:değer, ...)", "not"]


def load_raw(path: str | Path | None = None) -> dict:
    p = Path(path) if path else hw_mod.hardware_path()
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def default_raw() -> dict:
    return yaml.safe_load(DEFAULT_HARDWARE.read_text(encoding="utf-8"))


def user_path() -> Path:
    import os

    env = os.environ.get("GLOW_HARDWARE")
    return Path(env) if env else hw_mod.USER_HARDWARE


def _map_to_str(m: dict) -> str:
    return ", ".join(f"{k}:{v:g}" for k, v in m.items())


def _str_to_map(s: str, what: str) -> dict[str, float]:
    out = {}
    for part in str(s or "").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"{what}: '{part}' biçimi 'led_id:değer' olmalı")
        k, v = part.split(":", 1)
        out[k.strip()] = float(v)
    return out


def to_rows(raw: dict) -> dict[str, list[list]]:
    leds = [[k, v.get("label", k), bool(v["addressable"]), v["width_mm"], v["thickness_mm"], v["cut_pitch_mm"], v["min_bend_radius_mm"],
             v["w_per_m"], v.get("ma_per_led"), v["leds_per_m"], v.get("price_try_per_m", 0), v.get("note", "")] for k, v in raw["leds"].items()]
    ctrl = [[k, v.get("label", k), *v["pocket_mm"], v.get("cable_side", "left"), v.get("clearance_mm", 1.0), ", ".join(v.get("supports", [])),
             v.get("price_try", 0), v.get("note", "")] for k, v in raw["controllers"].items()]
    diff = [[k, v.get("label", k), v["color"], v.get("price_try_per_kg", 0), _map_to_str(v["thickness_mm"]), _map_to_str(v["min_gap_mm"]),
             v.get("note", "")] for k, v in raw["diffusers"].items()]
    return {"leds": leds, "controllers": ctrl, "diffusers": diff}


def _num(x, name: str, row: str):
    try:
        return float(x)
    except (TypeError, ValueError):
        raise ValueError(f"{row}: '{name}' sayı olmalı (değer: {x!r})") from None


def _opt_num(x):
    if x is None or (isinstance(x, float) and x != x) or str(x).strip() in ("", "None", "nan"):
        return None
    return float(x)


def from_rows(rows: dict[str, list[list]], base: dict) -> dict:
    """Table rows -> raw dict (usb/other prices are kept from ``base``). Raises ValueError (Turkish) on malformed cells."""
    raw = copy.deepcopy(base)
    raw["leds"], raw["controllers"], raw["diffusers"] = {}, {}, {}
    for r in rows["leds"]:
        id_ = str(r[0]).strip()
        if not id_:
            continue
        raw["leds"][id_] = {"label": str(r[1]), "addressable": bool(r[2]), "width_mm": _num(r[3], "genişlik", id_), "thickness_mm": _num(r[4], "kalınlık", id_),
                            "cut_pitch_mm": _num(r[5], "kesim aralığı", id_), "min_bend_radius_mm": _num(r[6], "min bükülme yarıçapı", id_),
                            "w_per_m": _num(r[7], "W/m", id_), "ma_per_led": _opt_num(r[8]), "leds_per_m": _num(r[9], "LED/m", id_),
                            "price_try_per_m": _num(r[10], "fiyat", id_), "note": str(r[11] or "")}
    for r in rows["controllers"]:
        id_ = str(r[0]).strip()
        if not id_:
            continue
        raw["controllers"][id_] = {"label": str(r[1]), "pocket_mm": [_num(r[2], "uzunluk", id_), _num(r[3], "genişlik", id_), _num(r[4], "yükseklik", id_)],
                                   "cable_side": str(r[5]).strip() or "left", "clearance_mm": _num(r[6], "boşluk", id_),
                                   "supports": [s.strip() for s in str(r[7] or "").split(",") if s.strip()], "price_try": _num(r[8], "fiyat", id_),
                                   "note": str(r[9] or "")}
    for r in rows["diffusers"]:
        id_ = str(r[0]).strip()
        if not id_:
            continue
        raw["diffusers"][id_] = {"label": str(r[1]), "color": str(r[2]).strip(), "price_try_per_kg": _num(r[3], "fiyat", id_),
                                 "thickness_mm": _str_to_map(r[4], f"{id_} kalınlık"), "min_gap_mm": _str_to_map(r[5], f"{id_} min aralık"),
                                 "note": str(r[6] or "")}
    return raw


def validate_raw(raw: dict) -> list[str]:
    """Turkish error messages; empty list = valid."""
    errs: list[str] = []
    for sect, name in (("leds", "LED"), ("controllers", "Kontrolcü"), ("diffusers", "Difüzör")):
        if not raw.get(sect):
            errs.append(f"{name} listesi boş olamaz.")
        for k in raw.get(sect, {}):
            if not ID_RE.match(k):
                errs.append(f"{name} id '{k}' geçersiz: küçük harf, rakam ve _ kullanın (ör. cob_5mm).")
    for k, v in raw.get("leds", {}).items():
        for f, lo in (("width_mm", 1), ("thickness_mm", 0.3), ("cut_pitch_mm", 3), ("min_bend_radius_mm", 2), ("w_per_m", 0.1), ("leds_per_m", 1)):
            if not (v[f] >= lo):
                errs.append(f"LED {k}: {f} en az {lo:g} olmalı.")
        if v["width_mm"] > 20 or v["thickness_mm"] > 8:
            errs.append(f"LED {k}: genişlik ≤ 20 mm ve kalınlık ≤ 8 mm olmalı.")
        if v["addressable"] and not v.get("ma_per_led"):
            errs.append(f"LED {k}: adreslenebilir şerit için mA/LED gerekli.")
        if v.get("price_try_per_m", 0) < 0:
            errs.append(f"LED {k}: fiyat negatif olamaz.")
    for k, v in raw.get("controllers", {}).items():
        if any(x < 5 for x in v["pocket_mm"]) or any(x > 150 for x in v["pocket_mm"]):
            errs.append(f"Kontrolcü {k}: ölçüler 5-150 mm arasında olmalı.")
        if v["cable_side"] not in ("left", "right", "top", "bottom"):
            errs.append(f"Kontrolcü {k}: kablo tarafı left/right/top/bottom olmalı.")
        if not (0 <= v["clearance_mm"] <= 5):
            errs.append(f"Kontrolcü {k}: boşluk 0-5 mm olmalı.")
        for s in v.get("supports", []):
            if s not in raw["leds"]:
                errs.append(f"Kontrolcü {k}: desteklenen LED '{s}' tanımlı değil.")
        if not v.get("supports"):
            errs.append(f"Kontrolcü {k}: en az bir LED tipi desteklemeli.")
    for k, v in raw.get("diffusers", {}).items():
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", v["color"]):
            errs.append(f"Difüzör {k}: renk #RRGGBB olmalı.")
        for led in raw["leds"]:
            t, g = v["thickness_mm"].get(led), v["min_gap_mm"].get(led)
            if t is None or g is None:
                errs.append(f"Difüzör {k}: '{led}' için kalınlık ve min aralık girilmeli.")
            elif not (0.4 <= t <= 4) or not (3 <= g <= 40):
                errs.append(f"Difüzör {k}/{led}: kalınlık 0,4-4 mm, min aralık 3-40 mm olmalı.")
        for led in list(v["thickness_mm"]) + list(v["min_gap_mm"]):
            if led not in raw["leds"]:
                errs.append(f"Difüzör {k}: bilinmeyen LED '{led}'.")
        if v.get("price_try_per_kg", 0) < 0:
            errs.append(f"Difüzör {k}: fiyat negatif olamaz.")
    if not errs:
        try:
            parse_hardware(raw)
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            errs.append(f"Okunamadı: {e}")
    return list(dict.fromkeys(errs))


def save_user(raw: dict, path: str | Path | None = None) -> Path:
    errs = validate_raw(raw)
    if errs:
        raise ValueError("; ".join(errs))
    p = Path(path) if path else user_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    head = ("# Workbench - Glow donanım kütüphanesi (kullanıcı ayarı; Donanım sekmesinden kaydedildi).\n"
            "# Silerseniz varsayılan değerler (paket içindeki hardware.yaml) kullanılır.\n")
    p.write_text(head + yaml.safe_dump(raw, allow_unicode=True, sort_keys=False, default_flow_style=None), encoding="utf-8")
    hw_mod.default_hardware.cache_clear()
    return p


def reset_user(path: str | Path | None = None) -> bool:
    p = Path(path) if path else user_path()
    existed = p.exists()
    if existed:
        p.unlink()
    hw_mod.default_hardware.cache_clear()
    return existed


def new_row(kind: str, existing: list[list]) -> list:
    n = 1
    ids = {str(r[0]) for r in existing}
    while f"yeni_{n}" in ids:
        n += 1
    nid = f"yeni_{n}"
    if kind == "leds":
        return [nid, "Yeni LED", False, 5.0, 1.2, 25.0, 15.0, 5.0, None, 480, 100, "KULLANICI: ölçülen değerleri girin"]
    if kind == "controllers":
        return [nid, "Yeni kontrolcü", 40.0, 22.0, 10.0, "left", 1.0, "", 100, "KULLANICI: ölçülen değerleri girin"]
    return [nid, "Yeni difüzör", "#F5F5F5", 600, "", "", "KULLANICI: kalınlık ve aralığı her LED için girin"]


def duplicate_row(rows: list[list], id_: str) -> list[list]:
    src = next((r for r in rows if str(r[0]) == id_), None)
    if src is None:
        raise ValueError("Önce bir kayıt seçin.")
    ids = {str(r[0]) for r in rows}
    n = 2
    while f"{id_}_kopya{n if n > 2 else ''}" in ids:
        n += 1
    cp = list(src)
    cp[0] = f"{id_}_kopya{n if n > 2 else ''}"
    cp[1] = f"{src[1]} (kopya)"
    return [*rows, cp]
