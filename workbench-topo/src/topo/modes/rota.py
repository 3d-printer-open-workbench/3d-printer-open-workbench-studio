"""Trail map (Likya Yolu style): terrain + raised route from GPX or an OSM route relation, stats caption, profile."""
from .base import Mode, Theme

MODE = Mode(
    key="rota",
    label="Rota haritası (Likya Yolu tarzı)",
    description="GPX ya da OSM rotası, gerçek arazi üzerinde yükseltilmiş çizgi; alt bantta mesafe, tırmanış ve yükseklik profili.",
    area_source="route",
    layers={"terrain": True, "sea": True, "water": True, "green": False, "forest": False, "roads": False, "rail": False, "paths": False,
            "buildings": False, "ruins": False, "route": True, "markers": True, "frame": True, "caption": True, "profile": True},
    themes=[
        Theme("Likya", {"terrain": "#6E9F4E", "sea": "#3D7EB8", "water": "#3D7EB8", "route": "#D62828",
                        "markers": "#D62828", "frame": "#F4F4F0", "text": "#D62828"},
              bands=[(0, "#6E9F4E"), (1700, "#F4F4F0")]),
        Theme("Orman", {"terrain": "#A7C77A", "forest": "#3F7D3A", "green": "#A7C77A", "sea": "#3D7EB8", "water": "#3D7EB8",
                        "route": "#D62828", "markers": "#D62828", "frame": "#A7C77A", "text": "#3F7D3A"},
              layers={"forest": True}),
        Theme("Alpin", {"terrain": "#5B7F3A", "sea": "#5B7F3A", "water": "#F4F4F0", "route": "#D62828",
                        "markers": "#D62828", "frame": "#8A8A8A", "text": "#F4F4F0"},
              bands=[(0, "#5B7F3A"), (1400, "#8A8A8A"), (2300, "#F4F4F0")]),
        Theme("Taş", {"terrain": "#D9D4C7", "sea": "#6C8EAD", "water": "#6C8EAD", "route": "#C0392B",
                      "markers": "#C0392B", "frame": "#3A3A3A", "text": "#D9D4C7"}),
        Theme("Gece", {"terrain": "#2B2D42", "sea": "#4D6A9A", "water": "#4D6A9A", "route": "#FFD166",
                       "markers": "#FFD166", "frame": "#8D99AE", "text": "#FFD166"}),
    ],
    defaults={"shape": "rect", "size_mm": 200, "z_exag": 0, "base_mm": 4.0, "margin_pct": 12, "route_width_mm": 2.4},
)
