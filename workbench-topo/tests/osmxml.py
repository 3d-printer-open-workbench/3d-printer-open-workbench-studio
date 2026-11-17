"""Convert an OSM API XML extract into Overpass-style JSON elements (with geometry) for offline tests."""
import xml.etree.ElementTree as ET


def elements(path):
    r = ET.parse(path).getroot()
    N = {n.get("id"): {"lat": float(n.get("lat")), "lon": float(n.get("lon"))} for n in r.iter("node")}
    W = {}
    out = []
    for w in r.iter("way"):
        geom = [N[n.get("ref")] for n in w.findall("nd") if n.get("ref") in N]
        W[w.get("id")] = geom
        out.append({"type": "way", "id": int(w.get("id")), "tags": {t.get("k"): t.get("v") for t in w.findall("tag")}, "geometry": geom})
    for rel in r.iter("relation"):
        mem = [{"type": m.get("type"), "ref": int(m.get("ref")), "role": m.get("role"), "geometry": W.get(m.get("ref"), [])}
               for m in rel.findall("member")]
        out.append({"type": "relation", "id": int(rel.get("id")), "tags": {t.get("k"): t.get("v") for t in rel.findall("tag")}, "members": mem})
    return out
