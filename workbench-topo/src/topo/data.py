"""Network data with an on-disk cache: geocoding (Nominatim), elevation (Copernicus DEM on AWS),
OpenStreetMap features (Overpass) and GPX parsing.

All network calls send a Workbench User-Agent and are cached under ``$TOPO_CACHE``
(default ``~/.cache/workbench-topo``) so repeated jobs work offline.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np

CACHE = Path(os.environ.get("TOPO_CACHE", Path.home() / ".cache" / "workbench-topo"))
# OpenStreetMap services ask clients to identify themselves: set TOPO_USER_AGENT to e.g.
# "MyWorkbench-Topo/0.1 (contact: you@example.com)".
UA = os.environ.get("TOPO_USER_AGENT") or "OpenWorkbenchStudio-Topo/0.1 (self-hosted 3D map tool)"
OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
TR_BBOX = "(35.5,25.0,42.5,45.0)"
DEM_URL = {
    30: "https://copernicus-dem-30m.s3.amazonaws.com/{n}/{n}.tif",
    90: "https://copernicus-dem-90m.s3.amazonaws.com/{n}/{n}.tif",
}


class DataError(RuntimeError):
    """Raised with a Turkish, user-facing message."""


@dataclass(frozen=True)
class BBox:
    south: float
    west: float
    north: float
    east: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.south + self.north) / 2, (self.west + self.east) / 2

    def size_m(self) -> tuple[float, float]:
        lat = math.radians(self.center[0])
        return (self.east - self.west) * 111320 * math.cos(lat), (self.north - self.south) * 110540

    def expand(self, frac: float) -> "BBox":
        dy, dx = (self.north - self.south) * frac, (self.east - self.west) * frac
        return BBox(self.south - dy, self.west - dx, self.north + dy, self.east + dx)

    @staticmethod
    def around(lat: float, lon: float, width_km: float, height_km: float) -> "BBox":
        dlat = height_km * 1000 / 110540 / 2
        dlon = width_km * 1000 / (111320 * math.cos(math.radians(lat))) / 2
        return BBox(lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def _key(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:20]


def http(url: str, data: bytes | None = None, timeout: int = 120, retries: int = 2) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    last = None
    for i in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404, 509):  # not worth retrying; callers handle these
                raise
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(2 * (i + 1))
    raise DataError(f"Bağlantı hatası: {url.split('/')[2]} ({last})")


# --------------------------------------------------------------------------- geocoding
def geocode(query: str) -> list[dict]:
    """Nominatim search -> [{name, lat, lon, bbox: BBox}] (cached)."""
    f = CACHE / "geocode" / f"{_key(query.strip().lower())}.json"
    if f.is_file():
        raw = json.loads(f.read_text())
    else:
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": query, "format": "jsonv2", "limit": 5, "accept-language": "tr"})
        raw = json.loads(http(url, timeout=30))
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(raw))
    out = []
    for r in raw:
        s, n, w, e = map(float, r["boundingbox"])
        out.append({"name": r["display_name"], "lat": float(r["lat"]), "lon": float(r["lon"]), "bbox": BBox(s, w, n, e)})
    return out


# --------------------------------------------------------------------------- elevation
def _tile_name(lat: int, lon: int, res: int) -> str:
    code = 10 if res == 30 else 30
    ns = f"{'N' if lat >= 0 else 'S'}{abs(lat):02d}"
    ew = f"{'E' if lon >= 0 else 'W'}{abs(lon):03d}"
    return f"Copernicus_DSM_COG_{code}_{ns}_00_{ew}_00_DEM"


def dem_tile(lat: int, lon: int, res: int = 30) -> Path | None:
    """Local path of one 1x1 degree Copernicus tile, downloaded once. None = no tile (open sea)."""
    name = _tile_name(lat, lon, res)
    d = CACHE / f"dem{res}"
    p, miss = d / f"{name}.tif", d / f"{name}.missing"
    if p.is_file():
        return p
    if miss.is_file():
        return None
    d.mkdir(parents=True, exist_ok=True)
    try:
        blob = http(DEM_URL[res].format(n=name), timeout=300)
    except urllib.error.HTTPError:
        miss.touch()
        return None
    tmp = p.with_suffix(".part")
    tmp.write_bytes(blob)
    tmp.rename(p)
    return p


def sample_elevation(lat: np.ndarray, lon: np.ndarray, res: int = 30) -> np.ndarray:
    """Bilinear elevation (m) at the given coordinates. Missing tiles / sea -> 0."""
    import rasterio
    from rasterio.windows import Window
    from scipy.ndimage import map_coordinates

    out = np.zeros(lat.shape, dtype=np.float64)
    for la in range(math.floor(lat.min()), math.floor(lat.max()) + 1):
        for lo in range(math.floor(lon.min()), math.floor(lon.max()) + 1):
            sel = (np.floor(lat) == la) & (np.floor(lon) == lo)
            if not sel.any():
                continue
            p = dem_tile(la, lo, res)
            if p is None:
                continue
            with rasterio.open(p) as ds:
                inv = ~ds.transform
                col, row = inv * (lon[sel], lat[sel])
                c0, r0 = max(int(col.min()) - 2, 0), max(int(row.min()) - 2, 0)
                c1, r1 = min(int(col.max()) + 3, ds.width), min(int(row.max()) + 3, ds.height)
                a = ds.read(1, window=Window(c0, r0, c1 - c0, r1 - r0)).astype(np.float64)
                nod = ds.nodata
            if nod is not None:
                a[a == nod] = 0
            out[sel] = map_coordinates(a, [row - r0 - 0.5, col - c0 - 0.5], order=1, mode="nearest")
    return out


# --------------------------------------------------------------------------- OpenStreetMap
_OVERPASS_DOWN_UNTIL = [0.0]


def overpass(body: str, timeout: int = 180, per_server: int | None = None, max_servers: int = 0) -> dict:
    """Run an Overpass QL body (without the [out:json] header); cached by query text."""
    q = f"[out:json][timeout:{timeout}];{body}"
    f = CACHE / "osm" / f"{_key(q)}.json"
    if f.is_file():
        return json.loads(f.read_text())
    if os.environ.get("TOPO_OFFLINE"):
        raise DataError("Çevrimdışı mod (TOPO_OFFLINE): bu alanın OSM verisi önbellekte yok.")
    last = None
    servers = OVERPASS[:max_servers] if max_servers else OVERPASS
    if time.time() < _OVERPASS_DOWN_UNTIL[0]:
        raise DataError("Overpass şu an yanıt vermiyor (birkaç dakika sonra tekrar denenecek).")
    for url in servers:
        try:
            raw = http(url, data=urllib.parse.urlencode({"data": q}).encode(), timeout=per_server or timeout, retries=0)
            js = json.loads(raw)
            if js.get("remark") and "runtime error" in js["remark"]:
                raise DataError(js["remark"][:200])
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(js))
            return js
        except (DataError, urllib.error.HTTPError, json.JSONDecodeError) as e:
            last = e
    _OVERPASS_DOWN_UNTIL[0] = time.time() + 600  # circuit breaker: skip Overpass for 10 minutes
    raise DataError(f"OpenStreetMap verisi alınamadı (Overpass): {last}")


# --------------------------------------------------------------------------- OSM main API (fallback)
OSM_API = "https://api.openstreetmap.org/api/0.6"
OSM_API_MAX_DEG2 = 0.25  # the API refuses larger /map boxes


def _osm_xml_elements(xml: bytes) -> tuple[list[dict], dict, dict]:
    """OSM API XML -> (Overpass-style elements with geometry, ways {id: geometry}, relations {id: element})."""
    root = ET.fromstring(xml)
    nodes = {n.get("id"): {"lat": float(n.get("lat")), "lon": float(n.get("lon"))} for n in root.iter("node") if n.get("lat")}
    ways, rels, out = {}, {}, []
    for w in root.iter("way"):
        geom = [nodes[n.get("ref")] for n in w.findall("nd") if n.get("ref") in nodes]
        ways[w.get("id")] = geom
        out.append({"type": "way", "id": int(w.get("id")), "tags": {t.get("k"): t.get("v") for t in w.findall("tag")}, "geometry": geom})
    for r in root.iter("relation"):
        el = {"type": "relation", "id": int(r.get("id")), "tags": {t.get("k"): t.get("v") for t in r.findall("tag")},
              "members": [{"type": m.get("type"), "ref": int(m.get("ref")), "role": m.get("role"),
                           "geometry": ways.get(m.get("ref"), [])} for m in r.findall("member")]}
        rels[r.get("id")] = el
        out.append(el)
    return out, ways, rels


def osm_api_map(bbox: BBox) -> list[dict]:
    """All elements of a small area from the main OSM API (used when Overpass is down or busy)."""
    if (bbox.north - bbox.south) * (bbox.east - bbox.west) > OSM_API_MAX_DEG2:
        raise DataError("Alan yedek OSM kaynağı için çok büyük.")
    f = CACHE / "osmapi" / f"{_key(f'{bbox.south:.5f},{bbox.west:.5f},{bbox.north:.5f},{bbox.east:.5f}')}.json"
    if f.is_file():
        return json.loads(f.read_text())
    if os.environ.get("TOPO_OFFLINE"):
        raise DataError("Çevrimdışı mod (TOPO_OFFLINE): bu alanın OSM verisi önbellekte yok.")
    els = _osm_api_tiles(bbox, 0)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(els))
    return els


def _osm_api_tiles(bbox: BBox, depth: int) -> list[dict]:
    """/map call; a box with too many nodes (HTTP 400) is split into four, up to 3 levels (64 calls)."""
    url = f"{OSM_API}/map?bbox={bbox.west:.6f},{bbox.south:.6f},{bbox.east:.6f},{bbox.north:.6f}"
    try:
        els, _, _ = _osm_xml_elements(http(url, timeout=180, retries=1))
        return els
    except urllib.error.HTTPError as e:
        if e.code not in (400, 509) or depth >= 3:
            raise DataError(f"OSM API: {e.code} (alan çok yoğun; daha küçük alan deneyin)")
    mlat, mlon = (bbox.south + bbox.north) / 2, (bbox.west + bbox.east) / 2
    seen, out = set(), []
    for q in (BBox(bbox.south, bbox.west, mlat, mlon), BBox(bbox.south, mlon, mlat, bbox.east),
              BBox(mlat, bbox.west, bbox.north, mlon), BBox(mlat, mlon, bbox.north, bbox.east)):
        for el in _osm_api_tiles(q, depth + 1):
            k = (el["type"], el["id"])
            if k not in seen:
                seen.add(k)
                out.append(el)
    return out


def osm_features(bbox: BBox, selectors: list[str]) -> list[dict]:
    """Elements (ways and relations, with geometry) matching Overpass selectors such as
    ``way["building"]`` inside ``bbox``. Falls back to the main OSM API for small areas;
    the caller classifies elements by their tags, so the extra elements are harmless."""
    if not selectors:
        return []
    b = f"({bbox.south:.6f},{bbox.west:.6f},{bbox.north:.6f},{bbox.east:.6f})"
    body = "(" + "".join(f"{s}{b};" for s in selectors) + ");out geom;"
    small = (bbox.north - bbox.south) * (bbox.east - bbox.west) <= OSM_API_MAX_DEG2
    try:
        # small areas: one Overpass try, then the main OSM API right away; large areas: all mirrors
        return overpass(body, timeout=120, per_server=45 if small else 90, max_servers=1 if small else 0).get("elements", [])
    except DataError as e:
        try:
            return osm_api_map(bbox)
        except DataError as e2:
            raise DataError("OpenStreetMap sunucusu şu an meşgul ve alan yedek kaynak için çok büyük: "
                            "göl, nehir, yol gibi harita katmanları bu sefer eklenemedi (arazi ve rota etkilenmez). "
                            "Birkaç dakika sonra tekrar deneyin." if "çok büyük" in str(e2) else f"OpenStreetMap verisi alınamadı: {e2}")


def osm_relation_full(rel_id: int) -> dict:
    """One relation with complete member geometry (main OSM API /full), cached."""
    f = CACHE / "osmapi" / f"rel_{int(rel_id)}.json"
    if f.is_file():
        return json.loads(f.read_text())
    if os.environ.get("TOPO_OFFLINE"):
        raise DataError("çevrimdışı")
    try:
        _, _, rels = _osm_xml_elements(http(f"{OSM_API}/relation/{int(rel_id)}/full", timeout=120, retries=1))
    except urllib.error.HTTPError as e:
        raise DataError(f"OSM API: {e.code}")
    el = rels.get(str(int(rel_id)))
    if el is None:
        raise DataError("ilişki yok")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(el))
    return el


ROUTE_TYPES = ("hiking", "foot", "walking", "bicycle", "mtb", "running")


def _parent_routes(osm_type: str, osm_id: int) -> list[dict]:
    """Route relations that contain a way/relation (OSM API), one level up and one more for super-routes."""
    out = []
    try:
        els, _, rels = _osm_xml_elements(http(f"{OSM_API}/{osm_type}/{osm_id}/relations", timeout=30, retries=1))
    except (DataError, urllib.error.HTTPError):
        return out
    for el in rels.values():
        t = el["tags"]
        if t.get("type") in ("route", "superroute") and (t.get("route") in ROUTE_TYPES or t.get("type") == "superroute"):
            out.append({"name": t.get("name:tr") or t.get("name") or str(el["id"]), "relation_id": el["id"],
                        "type": f"{t.get('type')}/{t.get('route', '')}"})
    return out


TRAIL_ALIASES = {  # Turkish trail names -> how they are tagged on OSM ways
    "karia": ["Carian Trail", "Karia Yolu"], "likya": ["Likya Yolu", "Lycian Way"], "frig": ["Frig Yolu", "Phrygian Way"],
    "aziz pavlus": ["Aziz Paul Yolu", "St Paul Trail"], "aziz paul": ["Aziz Paul Yolu"], "evliya": ["Evliya Çelebi Yolu", "Evliya Celebi Way"],
    "hitit": ["Hitit Yolu", "Hittite Trail"], "kapadokya": ["Kapadokya Yolu", "Cappadocia"], "sufi": ["Sufi Yolu", "Sufi Trail"],
}


def find_routes(query: str) -> list[dict]:
    """Hiking / cycling route relations matching a name (also tries known alias spellings)."""
    q = query.strip()
    res = _find_routes(q, overpass_ok=False)
    if not res:
        low = q.lower().replace("İ", "i")
        for key, alts in TRAIL_ALIASES.items():
            if key in low:
                for alt in alts:
                    if alt.lower() != low:
                        res = _find_routes(alt, overpass_ok=False)
                        if res:
                            return res
    return res or _find_routes(q, overpass_ok=True)


def _find_routes(query: str, overpass_ok: bool = True) -> list[dict]:
    """Hiking / cycling route relations matching a name.

    1. Nominatim (relations, and ways named like the trail -> their parent route relations via the OSM API)
    2. Overpass name search around Turkey (short timeout; skipped if busy)
    """
    q = query.strip()
    f = CACHE / "geocode" / f"route3_{int(overpass_ok)}_{_key(q.lower())}.json"
    if f.is_file():
        return json.loads(f.read_text())
    out: dict[int, dict] = {}
    try:
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
            {"q": q, "format": "jsonv2", "limit": 10, "accept-language": "tr"})
        raw = json.loads(http(url, timeout=30))
    except (DataError, urllib.error.HTTPError, json.JSONDecodeError):
        raw = []
    checked = 0
    for r in raw:
        if r.get("osm_type") == "relation":
            for p in _parent_routes("relation", int(r["osm_id"])) + [{"name": r["display_name"].split(",")[0], "relation_id": int(r["osm_id"]),
                                                                       "type": f"{r.get('category')}/{r.get('type')}"}]:
                out.setdefault(p["relation_id"], p)
        elif r.get("osm_type") == "way" and checked < 6:
            checked += 1
            for p in _parent_routes("way", int(r["osm_id"])):
                out.setdefault(p["relation_id"], p)
    try:
        if out or not overpass_ok:
            raise DataError("found")  # Overpass only as a last resort: it is slow and often busy
        rx = re.sub(r'[\\"]', "", q)
        js = overpass(f'rel["route"~"^(hiking|foot|walking|bicycle|mtb)$"]["name"~"{rx}",i]{TR_BBOX};out tags;'
                      f'rel["type"="superroute"]["name"~"{rx}",i]{TR_BBOX};out tags;', timeout=60, per_server=30)
        for e in js.get("elements", []):
            t = e.get("tags", {})
            out.setdefault(int(e["id"]), {"name": t.get("name:tr") or t.get("name", str(e["id"])), "relation_id": int(e["id"]),
                                          "type": f"{t.get('type', 'route')}/{t.get('route', '')}"})
    except DataError:
        pass
    # super-routes first, then by name match
    res = sorted(out.values(), key=lambda r: (not r["type"].startswith("superroute"), q.lower() not in r["name"].lower()))
    if res:
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(res))
    return res


def osm_route(relation_id: int) -> tuple[str, list[list[tuple[float, float]]]]:
    """(name, list of polylines [(lat, lon)]) of an OSM route relation; child relations (stages) included."""
    rid = int(relation_id)
    f = CACHE / "routes" / f"{rid}.json"
    if f.is_file():
        d = json.loads(f.read_text())
        return d["name"], [[tuple(p) for p in ln] for ln in d["lines"]]
    name, lines = f"Rota {relation_id}", []
    try:
        js = overpass(f"rel({rid});out tags;rel({rid});>>;way._;out geom;", timeout=180, per_server=60, max_servers=1)
        for e in js.get("elements", []):
            if e["type"] == "relation" and e.get("id") == rid:
                t = e.get("tags", {})
                name = t.get("name:tr") or t.get("name") or name
            elif e["type"] == "way" and e.get("geometry"):
                lines.append([(g["lat"], g["lon"]) for g in e["geometry"]])
    except DataError:
        # main OSM API: /relation/{id}/full, recursing into child relations
        seen: set[int] = set()

        def walk(r: int, depth: int = 0):
            nonlocal name
            if r in seen or depth > 3:
                return
            seen.add(r)
            _, ways, rels = _osm_xml_elements(http(f"{OSM_API}/relation/{r}/full", timeout=180, retries=1))
            me = rels.get(str(r))
            if me is None:
                return
            if r == rid:
                name = me["tags"].get("name:tr") or me["tags"].get("name") or name
            for m in me["members"]:
                if m["type"] == "way" and len(ways.get(str(m["ref"]), [])) > 1:
                    lines.append([(g["lat"], g["lon"]) for g in ways[str(m["ref"])]])
                elif m["type"] == "relation":
                    walk(m["ref"], depth + 1)

        try:
            walk(rid)
        except urllib.error.HTTPError as e:
            raise DataError(f"OSM rota alınamadı: {e.code}")
    if not lines:
        raise DataError(f"OSM rota bulunamadı: {relation_id}")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"name": name, "lines": lines}))
    return name, lines


def parse_gpx(path: str | Path) -> tuple[str, list[list[tuple[float, float, float | None]]]]:
    """(name, segments of (lat, lon, ele)) from a GPX file (tracks, else routes)."""
    root = ET.parse(path).getroot()
    tag = lambda el: el.tag.split("}")[-1]
    name = Path(path).stem
    segs: list[list] = []
    for el in root.iter():
        t = tag(el)
        if t == "name" and el.text and name == Path(path).stem:
            name = el.text.strip()
        if t in ("trkseg", "rte"):
            pts = []
            for p in el:
                if tag(p) in ("trkpt", "rtept"):
                    ele = next((float(c.text) for c in p if tag(c) == "ele" and c.text), None)
                    pts.append((float(p.get("lat")), float(p.get("lon")), ele))
            if len(pts) > 1:
                segs.append(pts)
    if not segs:
        raise DataError("GPX dosyasında iz (track) bulunamadı.")
    return name, segs


def _hysteresis(e: np.ndarray, th: float = 4.0) -> tuple[float, float]:
    """Total climb / descent counting only moves larger than ``th`` metres (filters DEM and GPS noise)."""
    up = down = 0.0
    ref = e[0]
    for v in e[1:]:
        if v - ref >= th:
            up += v - ref
            ref = v
        elif ref - v >= th:
            down += ref - v
            ref = v
    return up, down


def route_stats(segs: list[list[tuple]], elev=None, step_m: float = 30.0) -> dict:
    """Length (km), ascent/descent (m) and min/max elevation of a route.

    Each segment is resampled every ``step_m`` metres; missing elevations come from ``elev(lat, lon)``;
    climbs are counted with a 4 m hysteresis after a ~150 m moving average.
    """
    dist = up = down = 0.0
    zs = []
    for s in segs:
        a = np.array([(p[0], p[1]) for p in s], dtype=float)
        if len(a) < 2:
            continue
        e = np.array([p[2] if len(p) > 2 and p[2] is not None else np.nan for p in s], dtype=float)
        la = np.radians(a[:, 0])
        dlat, dlon = np.diff(la), np.radians(np.diff(a[:, 1]))
        h = np.sin(dlat / 2) ** 2 + np.cos(la[:-1]) * np.cos(la[1:]) * np.sin(dlon / 2) ** 2
        d = np.r_[0.0, np.cumsum(2 * 6371000 * np.arcsin(np.sqrt(h)))]
        dist += float(d[-1])
        if d[-1] <= 0:
            continue
        t = np.arange(0.0, d[-1] + step_m, step_m)
        t[-1] = min(t[-1], d[-1])
        lat_r, lon_r = np.interp(t, d, a[:, 0]), np.interp(t, d, a[:, 1])
        if np.isnan(e).all():
            if elev is None:
                continue
            er = np.asarray(elev(lat_r, lon_r), dtype=float)
        else:
            ok = ~np.isnan(e)
            er = np.interp(t, d[ok], e[ok])
        if len(er) > 5:
            er = np.convolve(np.pad(er, 2, mode="edge"), np.ones(5) / 5, mode="valid")
        u, dn = _hysteresis(er)
        up += u
        down += dn
        zs.append(er)
    z = np.concatenate(zs) if zs else np.array([np.nan])
    return {"length_km": round(dist / 1000, 1), "ascent_m": round(up), "descent_m": round(down),
            "min_m": None if np.isnan(z).all() else round(float(np.nanmin(z))),
            "max_m": None if np.isnan(z).all() else round(float(np.nanmax(z)))}
