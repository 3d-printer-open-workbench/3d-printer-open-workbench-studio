"""Decorative landscape: a real place's relief as a desk / wall piece - green mountains, fine black roads, white
buildings and rocks, blue seas, lakes and rivers (rivers widen downstream and swell / narrow along their course).
Four filaments exactly; colours are a stylised palette, the shapes are real."""
from .base import Mode, Theme

MODE = Mode(
    key="arazi",
    label="Arazi (dekoratif)",
    description="Gerçek arazi kabartması, dekoratif renklerle: dağlar yeşil, ince yollar siyah, binalar ve kayalıklar beyaz, "
                "deniz, göl ve ırmaklar mavi (ırmaklar akış boyunca genişleyip daralır).",
    area_source="place",
    layers={"terrain": True, "sea": True, "water": True, "streams": True, "green": False, "forest": False, "rocks": True,
            "roads": True, "rail": False, "paths": False, "buildings": True, "ruins": False, "route": False, "markers": False,
            "frame": False, "caption": False, "profile": False},
    themes=[
        Theme("Yeşil dağlar", {"terrain": "#3F8F3A", "roads": "#1E1E1E", "buildings": "#FFFFFF", "rocks": "#FFFFFF",
                               "water": "#2AA7E0", "streams": "#2AA7E0", "sea": "#2AA7E0", "frame": "#1E1E1E",
                               "text": "#FFFFFF", "markers": "#1E1E1E"}, road_scale=0.6),
        Theme("Kar ve göl", {"terrain": "#FFFFFF", "roads": "#1E1E1E", "buildings": "#A3A3A3", "rocks": "#A3A3A3",
                             "water": "#2AA7E0", "streams": "#2AA7E0", "sea": "#2AA7E0", "frame": "#1E1E1E",
                             "text": "#1E1E1E", "markers": "#1E1E1E"}, road_scale=0.6),
        Theme("Kum ve deniz", {"terrain": "#E9D8B9", "roads": "#6B4E31", "buildings": "#FFFFFF", "rocks": "#FFFFFF",
                               "water": "#1F6FB2", "streams": "#1F6FB2", "sea": "#1F6FB2", "frame": "#6B4E31",
                               "text": "#FFFFFF", "markers": "#6B4E31"}, road_scale=0.6),
    ],
    defaults={"shape": "rect", "size_mm": 200, "z_exag": 2.0, "base_mm": 3.0, "area_km": 4.0, "dem_smooth_m": 60},
)
