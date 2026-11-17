import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """No network: synthetic hills for elevation, the Efes OSM extract for features."""
    import osmxml
    import topo.data as d

    monkeypatch.setattr(d, "CACHE", tmp_path / "cache")

    def elev(lat, lon, res=30):
        lat, lon = np.asarray(lat, float), np.asarray(lon, float)
        z = 300 * np.exp(-(((lat - 37.937) / 0.01) ** 2 + ((lon - 27.346) / 0.012) ** 2)) + 40 * (lon - 27.33) * 30
        return np.where(lon < 27.334, 0.0, np.clip(z, 0, None))

    monkeypatch.setattr(d, "sample_elevation", elev)
    els = osmxml.elements(Path(__file__).parent / "data" / "efes_osm.xml")
    monkeypatch.setattr(d, "osm_features", lambda bb, sel: els)
    yield
