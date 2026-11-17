"""Mode = a product option (trail map, city map, memory map, ...).

A mode only supplies defaults and data rules; the geometry engine (``topo.build``) is shared.
To add a mode: create ``modes/<key>.py`` with a ``MODE = Mode(...)`` and list it in ``modes/__init__.py``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

# Overpass selectors per OSM layer (the bbox is appended by topo.data.osm_features)
SELECTORS: dict[str, list[str]] = {
    "buildings": ['way["building"]', 'relation["building"]["type"="multipolygon"]'],
    "roads": ['way["highway"~"^(motorway|trunk|primary|secondary|tertiary|residential|unclassified|living_street|pedestrian|service|motorway_link|trunk_link|primary_link|secondary_link)$"]'],
    "rail": ['way["railway"~"^(rail|light_rail|subway|tram|narrow_gauge|funicular|monorail)$"]["tunnel"!="yes"]'],
    "paths": ['way["highway"~"^(footway|path|steps|track|cycleway|pedestrian)$"]'],
    "water": ['way["natural"="water"]', 'relation["natural"="water"]', 'way["waterway"~"^(river|canal|riverbank)$"]',
              'way["landuse"="reservoir"]', 'relation["waterway"="riverbank"]'],
    "green": ['way["leisure"~"^(park|garden|pitch|golf_course|playground|dog_park)$"]',
              'way["landuse"~"^(grass|meadow|recreation_ground|cemetery|village_green|allotments|orchard|vineyard|plant_nursery|greenfield)$"]',
              'way["natural"~"^(grassland|heath|scrub)$"]', 'way["amenity"="grave_yard"]',
              'relation["leisure"~"^(park|garden|golf_course)$"]', 'relation["landuse"~"^(grass|meadow|recreation_ground|cemetery|orchard|vineyard)$"]',
              'relation["natural"~"^(grassland|heath|scrub)$"]'],
    "forest": ['way["landuse"="forest"]', 'way["natural"="wood"]', 'relation["landuse"="forest"]', 'relation["natural"="wood"]'],
    "rocks": ['way["natural"~"^(bare_rock|scree|rock|stone|shingle|cliff)$"]', 'relation["natural"~"^(bare_rock|scree|shingle)$"]'],
    "streams": ['way["waterway"="stream"]'],
    "ruins": ['way["historic"~"^(ruins|archaeological_site|monument|city_gate|citywalls)$"]', 'way["ruins"]',
              'relation["historic"~"^(ruins|archaeological_site)$"]', 'relation["ruins"]', 'way["building"="ruins"]'],
}

LAYER_TR = {"terrain": "Arazi", "sea": "Deniz", "water": "Göl / nehir", "streams": "Dereler", "green": "Park / çim", "forest": "Orman",
            "rocks": "Kayalık / taşlık", "roads": "Yollar", "rail": "Tren / raylı sistem", "paths": "Patikalar", "buildings": "Binalar",
            "route": "Rota", "markers": "İşaretler", "frame": "Çerçeve", "caption": "Yazı bandı", "profile": "Yükseklik profili"}
COLOR_TR = {**LAYER_TR, "text": "Yazı"}  # Turkish names of the layers / colour roles (editor labels)

# drape height (mm above the terrain surface) and draw order (higher wins where layers overlap)
LAYER_ORDER = ["green", "forest", "rocks", "water", "streams", "sea", "paths", "roads", "rail", "ruins", "buildings", "route", "markers"]


@dataclass
class Theme:
    name: str
    colors: dict[str, str]  # layer/role -> #RRGGBB
    bands: list[tuple[float, str]] = field(default_factory=list)  # terrain colour bands: (from elevation m, colour)
    layers: dict = field(default_factory=dict)  # layers this theme switches on/off (e.g. forest for "Orman")
    road_scale: float = 1.0  # road / path width factor (decorative themes draw finer roads; never below printable)


@dataclass
class Mode:
    key: str
    label: str
    description: str
    area_source: str  # "place" (centre + size) or "route" (GPX / OSM route)
    layers: dict[str, bool]  # default on/off
    themes: list[Theme]
    defaults: dict = field(default_factory=dict)  # job defaults (shape, size_mm, z_exag, ...)
    classify: Callable[[dict], str | None] | None = None  # optional custom OSM tag -> layer rule
    beta: bool = False

    def theme(self, name: str | None) -> Theme:
        for t in self.themes:
            if t.name == name:
                return t
        return self.themes[0]


def default_classify(tags: dict) -> str | None:
    """Generic OSM tags -> layer key."""
    if "building" in tags and tags.get("building") != "ruins":
        return "buildings"
    if tags.get("historic") in ("ruins", "archaeological_site", "monument", "city_gate", "citywalls") or "ruins" in tags \
            or tags.get("building") == "ruins":
        return "ruins"
    if tags.get("railway") in ("rail", "light_rail", "subway", "tram", "narrow_gauge", "funicular", "monorail") and tags.get("tunnel") != "yes":
        return "rail"
    hw = tags.get("highway")
    if hw in ("footway", "path", "steps", "track", "cycleway"):
        return "paths"
    if hw:
        return "roads"
    if tags.get("waterway") == "stream":
        return "streams"
    if tags.get("natural") == "water" or tags.get("waterway") in ("river", "canal", "riverbank") or tags.get("landuse") == "reservoir":
        return "water"
    if tags.get("natural") in ("bare_rock", "scree", "rock", "stone", "shingle", "cliff"):
        return "rocks"
    if tags.get("landuse") == "forest" or tags.get("natural") == "wood":
        return "forest"
    if tags.get("leisure") in ("park", "garden", "pitch", "golf_course", "playground", "dog_park") or tags.get("amenity") == "grave_yard" \
            or tags.get("natural") in ("grassland", "heath", "scrub") or tags.get("landuse") in ("village_green", "allotments", "orchard", "vineyard",
                                                                                                 "plant_nursery", "greenfield") or tags.get("landuse") in (
            "forest", "grass", "meadow", "recreation_ground", "cemetery") or tags.get("natural") in ("wood", "scrub"):
        return "green"
    return None


ROAD_WIDTH_M = {  # real-world width used for drawing (before the minimum printable width)
    "motorway": 24, "trunk": 20, "primary": 16, "secondary": 13, "tertiary": 11, "motorway_link": 10, "trunk_link": 10,
    "primary_link": 9, "secondary_link": 9, "residential": 8, "unclassified": 8, "living_street": 6, "pedestrian": 7,
    "service": 5, "footway": 3, "path": 2, "steps": 3, "track": 4, "cycleway": 3,
}
