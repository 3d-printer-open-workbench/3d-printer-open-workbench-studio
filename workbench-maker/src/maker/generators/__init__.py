"""Generator registry. New generator: add a module with ``GENERATOR`` and append it to ``_MODULES``."""
from __future__ import annotations

from . import cake_topper, coloring_plaque, container, cookie_cutter, coupon, grid_cutter, keychain, letter_stamp, nameplate, ornament, pet_tag, photo_stand, plate, qr_plaque, rattan_letters, roller, string_art, thermoform, vessel
from .base import BuildResult, Generator, Param, Part, SheetLayout
from .planned import PLANNED

_MODULES = [thermoform, coupon, keychain, qr_plaque, pet_tag, cookie_cutter, letter_stamp, grid_cutter, roller, cake_topper, container, photo_stand, ornament, string_art, rattan_letters, coloring_plaque, vessel, nameplate, plate]
GENERATORS: dict[str, Generator] = {m.GENERATOR.key: m.GENERATOR for m in _MODULES} | {g.key: g for g in PLANNED}


def get_generator(key: str) -> Generator:
    try:
        return GENERATORS[key]
    except KeyError:
        raise ValueError(f"bilinmeyen jeneratör: {key} (seçenekler: {', '.join(GENERATORS)})") from None


__all__ = ["BuildResult", "GENERATORS", "Generator", "Param", "Part", "SheetLayout", "get_generator"]
