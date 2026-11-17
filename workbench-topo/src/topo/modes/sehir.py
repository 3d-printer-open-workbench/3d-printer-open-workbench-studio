"""City map: buildings at real heights, roads, water, parks; terrain optional."""
from .base import Mode, Theme

MODE = Mode(
    key="sehir",
    label="Şehir topoğrafyası",
    description="Binalar yükseklikleriyle, yollar, tren hatları, su ve yeşil alanlar; istenirse arazi kabartması (yumuşatılmış).",
    area_source="place",
    layers={"terrain": False, "sea": True, "water": True, "green": True, "forest": True, "roads": True, "rail": True, "paths": False,
            "buildings": True, "ruins": False, "route": False, "markers": False, "frame": False, "caption": False, "profile": False},
    themes=[
        Theme("Klasik", {"terrain": "#FFFFFF", "buildings": "#FFFFFF", "roads": "#1E1E1E", "water": "#2AA7E0",
                         "sea": "#2AA7E0", "green": "#7DB65A", "frame": "#1E1E1E", "text": "#FFFFFF", "markers": "#1E1E1E"}),
        Theme("Gri", {"terrain": "#A3A3A3", "buildings": "#FFFFFF", "roads": "#1E1E1E", "water": "#2AA7E0",
                      "sea": "#2AA7E0", "green": "#A3A3A3", "frame": "#1E1E1E", "text": "#FFFFFF", "markers": "#1E1E1E"}),
        Theme("Doğa", {"terrain": "#F4F1E8", "buildings": "#F4F1E8", "roads": "#F4F1E8", "water": "#2AA7E0", "sea": "#2AA7E0",
                       "green": "#9CCB6B", "forest": "#3F7D3A", "frame": "#3F7D3A", "text": "#F4F1E8", "markers": "#3F7D3A"}),
        Theme("Ahşap", {"terrain": "#C89F6D", "buildings": "#E9D8B9", "roads": "#6B4E31", "water": "#3F6E8C",
                        "sea": "#3F6E8C", "green": "#C89F6D", "frame": "#6B4E31", "text": "#E9D8B9", "markers": "#6B4E31"}),
        Theme("Gece", {"terrain": "#1F2430", "buildings": "#E8E8E8", "roads": "#F2C14E", "water": "#3A5A8C",
                       "sea": "#3A5A8C", "green": "#1F2430", "frame": "#E8E8E8", "text": "#1F2430", "markers": "#F2C14E"}),
        Theme("Beyaz", {"terrain": "#FFFFFF", "buildings": "#FFFFFF", "roads": "#FFFFFF", "water": "#FFFFFF",
                        "sea": "#FFFFFF", "green": "#FFFFFF", "frame": "#FFFFFF", "text": "#FFFFFF", "markers": "#FFFFFF"}),
    ],
    defaults={"shape": "square", "size_mm": 200, "z_exag": 1.5, "base_mm": 3.0, "area_km": 1.8, "dem_smooth_m": 120},
)
