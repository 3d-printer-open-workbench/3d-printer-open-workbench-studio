"""Mode registry. New mode: add a module with ``MODE`` and append it to ``_MODULES``."""
from . import ani, arazi, rota, sehir
from .base import COLOR_TR, LAYER_TR, LAYER_ORDER, ROAD_WIDTH_M, SELECTORS, Mode, Theme, default_classify

_MODULES = [rota, sehir, ani, arazi]
MODES: dict[str, Mode] = {m.MODE.key: m.MODE for m in _MODULES}


def get_mode(key: str) -> Mode:
    try:
        return MODES[key]
    except KeyError:
        raise ValueError(f"bilinmeyen mod: {key} (seçenekler: {', '.join(MODES)})") from None
