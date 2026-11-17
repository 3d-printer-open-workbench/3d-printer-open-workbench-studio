"""Bill of materials + TRY cost (filament by colour, LED strip, controller, supply, screws, jumper wire)."""
from __future__ import annotations

import csv
from pathlib import Path

from .hardware import Hardware
from .parts import norm_color

SUPPLY_ADAPTER = {"usb_5v_2a": "usb_adapter", "usb_5v_3a": "usb_adapter"}


def build_bom(hw: Hardware, meta: dict, grams_by_color: dict[str, float]) -> dict:
    """Rows + totals. ``meta`` is the LightBox meta; filament grams come from Kaligraf's estimate."""
    op = hw.other_prices
    diff = hw.diffuser(meta["diffuser"])
    led = hw.led(meta["led"])
    ctrl = hw.controller(meta.get("controller_bom", meta["controller"]))
    rows: list[dict] = []

    def add(item: str, qty: float, unit: str, unit_price: float, note: str = "", item_tr: str = "", note_tr: str = "") -> None:
        rows.append({"item": item, "item_tr": item_tr or item, "qty": round(qty, 2), "unit": unit,
                     "unit_price_try": round(unit_price, 2), "total_try": round(qty * unit_price, 2),
                     "note": note, "note_tr": note_tr or note})

    diff_col = norm_color(diff.color)
    for color, g in sorted(grams_by_color.items(), key=lambda kv: -kv[1]):
        is_diff = norm_color(color) == diff_col
        per_kg = diff.price_try_per_kg if is_diff else op.get("body_filament_per_kg", 600.0)
        add(f"Filament {color}" + (" (diffuser)" if is_diff else ""), g, "g", per_kg / 1000.0,
            f"{g:.0f} g (excl. purge and waste)", f"Filament {color}" + (" (difüzör)" if is_diff else ""),
            f"{g:.0f} g (fire ve purge hariç)")
    pw = meta["power"]
    add(f"LED strip {led.label}", pw["strip_to_buy_m"], "m", led.price_try_per_m,
        f"used {pw['strip_length_mm'] / 1000:.2f} m, {pw['n_leds']} LED", f"LED şerit {led.label}",
        f"kullanılan {pw['strip_length_mm'] / 1000:.2f} m, {pw['n_leds']} LED")
    ext = meta.get("controller_mode") == "external"
    add(f"Controller {ctrl.label}", 1, "pcs", ctrl.price_try, "inline on the cable, outside the box" if ext else "",
        f"Kontrolcü {ctrl.label}", "kablo üzerinde, kutunun dışında" if ext else "")
    add("USB cable", 1, "pcs", op.get("usb_cable", 0.0), item_tr="USB kablo")
    sup = pw["supply"].replace("usb_", "").replace("_", " ")
    add(f"USB adapter ({sup})", 1, "pcs", op.get("usb_adapter", 0.0), item_tr=f"USB adaptör ({sup.upper()})")
    add("M3 x 8 screws", int(meta.get("n_bosses", 0)), "pcs", op.get("screw_m3", 0.0), item_tr="M3 x 8 kendinden kılavuzlu vida")
    wire_mm = float(meta["led_path"].get("jumper_wire_total_mm", 0.0))
    if wire_mm > 0:
        add("Jumper wire (x3 cores)", wire_mm * 3 / 1000.0 + 0.2, "m", op.get("wire_per_m", 0.0), "5V/GND/DIN jumpers + spare",
            item_tr="Jumper kablo (3 damarlı)", note_tr="5V/GND/DIN bağlantıları + yedek")
    filament = sum(r["total_try"] for r in rows if r["item"].startswith("Filament"))
    total = sum(r["total_try"] for r in rows)
    return {"rows": rows, "filament_try": round(filament, 2), "total_try": round(total, 2), "currency": "TRY"}


def write_bom_csv(bom: dict, path: Path) -> Path:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["item", "item_tr", "qty", "unit", "unit_price_try", "total_try", "note", "note_tr"])
        w.writeheader()
        w.writerows(bom["rows"])
        w.writerow({"item": "TOTAL", "total_try": bom["total_try"]})
    return path
