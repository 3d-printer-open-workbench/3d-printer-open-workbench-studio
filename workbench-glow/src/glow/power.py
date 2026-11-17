"""Electrical estimate for the LED strip against the common USB 5 V supplies."""
from __future__ import annotations

import math

from .hardware import Hardware, strip_power_w

TYPICAL_ADDRESSABLE = 0.4  # typical average brightness of an animated / coloured WS2812B strip
CONTROLLER_W = 0.5  # controller + logic overhead
ABL_MARGIN = 0.85  # keep the supply at 85 % at most when suggesting a WLED current cap


def power_report(hw: Hardware, led_id: str, strip_length_mm: float) -> tuple[dict, list[str]]:
    """Power numbers, a supply recommendation and warnings for ``strip_length_mm`` of ``led_id``."""
    led = hw.led(led_id)
    strip_full = strip_power_w(led, strip_length_mm)
    full = strip_full + CONTROLLER_W
    typ_f = TYPICAL_ADDRESSABLE if led.addressable else 1.0
    strip_typ = strip_power_w(led, strip_length_mm, typ_f)
    typ = strip_typ + CONTROLLER_W
    limits = sorted(hw.usb_limits_w.items(), key=lambda kv: kv[1])
    warnings: list[str] = []
    # smallest supply that carries the typical load, else the biggest one
    chosen = next((k for k, v in limits if v >= typ), limits[-1][0])
    cap_w = hw.usb_limits_w[chosen]
    meters = strip_length_mm / 1000.0
    rep = {
        "strip_length_mm": round(strip_length_mm, 1),
        "strip_to_buy_m": round(math.ceil(meters * 2 - 1e-9) / 2, 1),  # sold in 0.5 m steps at least
        "voltage": hw.voltage,
        "full_white_w": round(strip_full, 2), "typical_w": round(strip_typ, 2),
        "total_full_w": round(full, 2), "total_typical_w": round(typ, 2), "controller_w": CONTROLLER_W,
        "full_white_a": round(full / hw.voltage, 2), "typical_a": round(typ / hw.voltage, 2),
        "typical_fraction": typ_f, "supply": chosen, "supply_w": cap_w,
        "limits_w": dict(hw.usb_limits_w),
    }
    cap_ma = int(cap_w * ABL_MARGIN / hw.voltage * 1000)
    over = [k for k, v in limits if full > v]
    if over:
        if led.addressable:
            rep["wled_abl_ma"] = cap_ma
            warnings.append(
                f"Full white would draw {full:.1f} W ({full / hw.voltage:.1f} A): above {', '.join(over)}. "
                f"Run it from a {chosen.replace('usb_', '').replace('_', ' ').upper()} supply with a brightness cap "
                f"(WLED 'Maximum Current' ~{cap_ma} mA, or Bluetooth app brightness <= {int(cap_w * ABL_MARGIN / full * 100)} %).")
        else:
            rep["max_brightness_pct"] = int(cap_w * ABL_MARGIN / full * 100)
            warnings.append(
                f"Full brightness draws {full:.1f} W ({full / hw.voltage:.1f} A): above {', '.join(over)}; "
                f"keep the dimmer below {rep['max_brightness_pct']} % or use a stronger supply.")
    if typ > limits[-1][1]:
        warnings.append(f"Even the typical load ({typ:.1f} W) exceeds the strongest listed USB supply ({limits[-1][1]:.0f} W): "
                        "shorten the strip or inject power at both ends.")
    if strip_length_mm > 2000 and led.addressable:
        warnings.append("Strip longer than 2 m: expect colour drop at the far end; feed 5 V/GND at both ends.")
    return rep, warnings
