"""Memory map: a meaningful place in a heart / circle / octagon outline, with markers and a caption."""
from .base import Mode, Theme

MODE = Mode(
    key="ani",
    label="Anı haritası (kalp, işaret, yazı)",
    description="Tanıştığınız yer, ilk ev, düğün: kalp/daire/sekizgen şekil, kalp ya da iğne işaretleri ve kişisel yazı.",
    area_source="place",
    layers={"terrain": False, "sea": True, "water": True, "green": False, "forest": False, "roads": True, "rail": False, "paths": False,
            "buildings": False, "ruins": False, "route": False, "markers": True, "frame": True, "caption": True, "profile": False},
    themes=[
        Theme("Romantik", {"terrain": "#FFFFFF", "roads": "#E05A7A", "water": "#9EC5E8", "sea": "#9EC5E8",
                           "green": "#FFFFFF", "buildings": "#FFFFFF", "markers": "#C9184A", "frame": "#E05A7A", "text": "#FFFFFF"}),
        Theme("Minimal", {"terrain": "#F5F5F5", "roads": "#222222", "water": "#222222", "sea": "#222222",
                          "green": "#F5F5F5", "buildings": "#F5F5F5", "markers": "#C9184A", "frame": "#222222", "text": "#F5F5F5"}),
        Theme("Altın", {"terrain": "#1E1E1E", "roads": "#C8A24A", "water": "#3B4A5A", "sea": "#3B4A5A",
                        "green": "#1E1E1E", "buildings": "#1E1E1E", "markers": "#C8A24A", "frame": "#C8A24A", "text": "#1E1E1E"}),
    ],
    defaults={"shape": "heart", "size_mm": 180, "z_exag": 1.0, "base_mm": 3.0, "area_km": 2.5, "marker_kind": "heart", "dem_smooth_m": 120},
)
