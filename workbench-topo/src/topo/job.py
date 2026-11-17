"""Job description (YAML / dict) with defaults coming from the selected mode."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import yaml

from .geom import SHAPES
from .modes import MODES, get_mode

MARKER_KINDS = {"pin": "İğne", "heart": "Kalp", "star": "Yıldız", "dot": "Nokta"}


@dataclass
class Marker:
    lat: float
    lon: float
    kind: str = "pin"
    label: str = ""
    color: str = ""      # empty = the "markers" layer colour


@dataclass
class Job:
    name: str = "harita"
    mode: str = "rota"
    theme: str = ""                      # empty = the mode's first theme
    colors: dict = field(default_factory=dict)   # layer -> #RRGGBB overrides
    layers: dict = field(default_factory=dict)   # layer -> bool overrides
    # area: a place (centre + size) or a route
    place: str = ""                      # geocoded when lat/lon are empty
    lat: float | None = None
    lon: float | None = None
    width_km: float = 0.0                # 0 = mode default (area_km)
    height_km: float = 0.0
    gpx: str = ""                        # GPX file path
    osm_relation: int = 0                # OSM route relation id (e.g. a hiking route)
    margin_pct: float = -1               # around the route; -1 = mode default
    # model
    shape: str = ""
    size_mm: float = 0.0                 # longest edge of the map area (frame/caption added outside)
    base_mm: float = 0.0
    z_exag: float = -1                   # 0 = automatic, -1 = mode default
    z_max_mm: float = 0.0                # 0 = no cap
    res_mm: float = 0.0                  # 0 = automatic grid resolution
    building_scale: float = 0.0          # building height factor; 0 = automatic (a 10 m building ≈ 2.5 mm)
    route_width_mm: float = 0.0
    markers: list = field(default_factory=list)   # [Marker | dict]
    marker_kind: str = ""
    route_endpoints: bool = True         # start / finish markers on route maps
    # frame & caption
    frame_mm: float = 5.0
    title: str = ""                      # empty = route / place name
    subtitle: str = ""                   # empty = automatic route stats
    duration: str = ""                   # optional, e.g. "6 sa 30 dk"
    font: str = ""
    # print
    wall_mount: bool = False
    infill_percent: int = 15
    split: bool = True                   # split oversize models into pinned tiles
    area_fixed: bool = False             # route mode: use lat/lon/width/height instead of fitting the route

    # ------------------------------------------------------------------ helpers
    def resolved(self) -> "Job":
        """Copy with the mode's defaults filled in."""
        m = get_mode(self.mode)
        d = asdict(self)
        dfl = m.defaults
        if not d["theme"]:
            d["theme"] = m.themes[0].name
        if not d["shape"]:
            d["shape"] = dfl.get("shape", "rect")
        for k, default in (("size_mm", 200), ("base_mm", 3.0), ("route_width_mm", 2.4)):
            if not d[k]:
                d[k] = dfl.get(k, default)
        if d["z_exag"] < 0:
            d["z_exag"] = dfl.get("z_exag", 1.0)
        if d["margin_pct"] < 0:
            d["margin_pct"] = dfl.get("margin_pct", 12)
        if not d["width_km"]:
            d["width_km"] = dfl.get("area_km", 2.0)
        if not d["height_km"]:
            d["height_km"] = d["width_km"]
        if not d["marker_kind"]:
            d["marker_kind"] = dfl.get("marker_kind", "pin")
        d["layers"] = {**m.layers, **m.theme(d["theme"]).layers, **(d["layers"] or {})}
        d["colors"] = {**m.theme(d["theme"]).colors, **(d["colors"] or {})}
        if "paths" not in m.theme(d["theme"]).colors and "paths" not in (self.colors or {}) and "roads" in d["colors"]:
            d["colors"]["paths"] = d["colors"]["roads"]
        d["markers"] = [Marker(**x) if isinstance(x, dict) else x for x in d["markers"]]
        j = Job(**d)
        j.validate()
        return j

    def validate(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"Bilinmeyen mod: {self.mode}")
        if self.shape not in SHAPES:
            raise ValueError(f"Bilinmeyen şekil: {self.shape} ({', '.join(SHAPES)})")
        if not 40 <= self.size_mm <= 1200:
            raise ValueError("Boyut 40–1200 mm arasında olmalı.")
        if not 1.5 <= self.base_mm <= 20:
            raise ValueError("Taban kalınlığı 1,5–20 mm arasında olmalı.")
        for k, v in self.colors.items():
            if not (isinstance(v, str) and v.startswith("#") and len(v) == 7):
                raise ValueError(f"Geçersiz renk ({k}): {v}")
        m = get_mode(self.mode)
        if m.area_source == "route" and not (self.gpx or self.osm_relation):
            raise ValueError("Rota modu için GPX dosyası ya da OSM rota numarası gerekli.")
        if m.area_source == "place" and self.lat is None and not self.place.strip():
            raise ValueError("Bir yer adı ya da enlem/boylam girin.")

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise ValueError(f"Bilinmeyen alan(lar): {', '.join(sorted(unknown))}")
        return cls(**d)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "Job":
        d = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if d.get("gpx") and not Path(d["gpx"]).is_absolute():
            d["gpx"] = str((Path(path).parent / d["gpx"]).resolve())
        return cls.from_dict(d)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d
