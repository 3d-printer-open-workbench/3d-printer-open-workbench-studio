"""Hardware library loader (hardware.yaml: LEDs, controllers, diffusers, prices)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_HARDWARE = Path(__file__).with_name("hardware.yaml")
USER_HARDWARE = Path.home() / ".config" / "workbench-glow" / "hardware.yaml"


@dataclass(frozen=True)
class Led:
    id: str
    label: str
    addressable: bool
    width_mm: float
    thickness_mm: float
    cut_pitch_mm: float
    min_bend_radius_mm: float
    w_per_m: float
    ma_per_led: float | None
    leds_per_m: float
    price_try_per_m: float
    note: str = ""


@dataclass(frozen=True)
class Controller:
    id: str
    label: str
    pocket_mm: tuple[float, float, float]  # L x W x H
    cable_side: str
    clearance_mm: float
    supports: tuple[str, ...]
    price_try: float
    note: str = ""


@dataclass(frozen=True)
class Diffuser:
    id: str
    label: str
    color: str
    price_try_per_kg: float
    thickness_mm: dict[str, float]
    min_gap_mm: dict[str, float]
    note: str = ""


@dataclass(frozen=True)
class Hardware:
    leds: dict[str, Led]
    controllers: dict[str, Controller]
    diffusers: dict[str, Diffuser]
    usb_limits_w: dict[str, float]
    voltage: float
    other_prices: dict[str, float]

    def led(self, id_: str) -> Led:
        return _get(self.leds, id_, "LED")

    def controller(self, id_: str) -> Controller:
        return _get(self.controllers, id_, "controller")

    def diffuser(self, id_: str) -> Diffuser:
        return _get(self.diffusers, id_, "diffuser")

    def diffuser_thickness(self, diffuser: str, led: str) -> float:
        return _need(self.diffuser(diffuser).thickness_mm, led, f"diffuser {diffuser} thickness")

    def min_gap(self, diffuser: str, led: str) -> float:
        return _need(self.diffuser(diffuser).min_gap_mm, led, f"diffuser {diffuser} min_gap")


def _get(d: dict, key: str, what: str):
    if key not in d:
        raise KeyError(f"unknown {what} {key!r}; available: {', '.join(d)}")
    return d[key]


def _need(d: dict, key: str, what: str) -> float:
    if key not in d:
        raise KeyError(f"hardware.yaml: {what} has no entry for {key!r}")
    return float(d[key])


def parse_hardware(raw: dict) -> Hardware:
    leds = {k: Led(id=k, label=v.get("label", k), addressable=bool(v["addressable"]), width_mm=float(v["width_mm"]),
                   thickness_mm=float(v["thickness_mm"]), cut_pitch_mm=float(v["cut_pitch_mm"]),
                   min_bend_radius_mm=float(v["min_bend_radius_mm"]), w_per_m=float(v["w_per_m"]),
                   ma_per_led=None if v.get("ma_per_led") is None else float(v["ma_per_led"]),
                   leds_per_m=float(v["leds_per_m"]), price_try_per_m=float(v.get("price_try_per_m", 0)), note=str(v.get("note", "")))
            for k, v in raw["leds"].items()}
    ctrls = {k: Controller(id=k, label=v.get("label", k), pocket_mm=tuple(float(x) for x in v["pocket_mm"]),
                           cable_side=v.get("cable_side", "left"), clearance_mm=float(v.get("clearance_mm", 1.0)),
                           supports=tuple(v.get("supports", [])), price_try=float(v.get("price_try", 0)), note=str(v.get("note", "")))
             for k, v in raw["controllers"].items()}
    diffs = {k: Diffuser(id=k, label=v.get("label", k), color=str(v["color"]).upper(),
                         price_try_per_kg=float(v.get("price_try_per_kg", 0)),
                         thickness_mm={a: float(b) for a, b in v["thickness_mm"].items()},
                         min_gap_mm={a: float(b) for a, b in v["min_gap_mm"].items()}, note=str(v.get("note", "")))
             for k, v in raw["diffusers"].items()}
    usb = raw.get("usb", {})
    return Hardware(leds, ctrls, diffs, {k: float(v) for k, v in usb.get("limits_w", {}).items()},
                    float(usb.get("voltage", 5.0)), {k: float(v) for k, v in raw.get("other_prices_try", {}).items()})


def hardware_path() -> Path:
    env = os.environ.get("GLOW_HARDWARE")
    if env:
        return Path(env)
    return USER_HARDWARE if USER_HARDWARE.exists() else DEFAULT_HARDWARE


def load_hardware(path: str | Path | None = None) -> Hardware:
    p = Path(path) if path else hardware_path()
    return parse_hardware(yaml.safe_load(p.read_text(encoding="utf-8")))


@lru_cache(maxsize=4)
def default_hardware() -> Hardware:
    return load_hardware()


def strip_power_w(led: Led, length_mm: float, brightness: float = 1.0) -> float:
    """Power of ``length_mm`` of strip (full white for addressable at brightness 1.0)."""
    return led.w_per_m * length_mm / 1000.0 * brightness
