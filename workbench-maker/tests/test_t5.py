import zipfile

import cv2
import numpy as np
import pytest
import trimesh
from PIL import Image, ImageDraw

from maker import core, flat, plates, qr
from maker.generators import GENERATORS, Part
from maker.job import build, run_job
from maker.shapes import shape_polygon


def _top_view(mesh, s=8, pad=40):
    """Top faces of a mesh, black on white (what a phone camera sees)."""
    top = mesh.bounds[1][2]
    f = (mesh.face_normals[:, 2] > 0.9) & (mesh.triangles[:, :, 2].min(axis=1) > top - 0.01)
    tri = mesh.triangles[f][:, :, :2]
    lo, hi = tri.reshape(-1, 2).min(axis=0), tri.reshape(-1, 2).max(axis=0)
    im = Image.new("L", (int((hi[0] - lo[0]) * s) + 2 * pad, int((hi[1] - lo[1]) * s) + 2 * pad), 255)
    d = ImageDraw.Draw(im)
    for t in tri:
        d.polygon([((x - lo[0]) * s + pad, (hi[1] - y) * s + pad) for x, y in t], fill=0)
    return np.array(im)


def _decodes(mesh, data) -> bool:
    det = cv2.QRCodeDetector()
    return any(det.detectAndDecode(_top_view(mesh, s))[0] == data for s in (6, 8, 10, 12))


def test_t5_generators_ready():
    for k in ("keychain", "qr_plaque", "pet_tag"):
        assert GENERATORS[k].status == "ready"


def test_keychain_layers_ring_and_single_colour():
    res, _ = build({"generator": "keychain", "params": {"text": "Ayşe"}})
    base, txt = res.parts
    assert base.meta["group"] == txt.meta["group"] == "keychain"
    assert txt.mesh.bounds[0][2] == pytest.approx(base.mesh.bounds[1][2])  # colours stacked, not side by side
    assert base.mesh.bounds[0][0] < txt.mesh.bounds[0][0] - 5  # ring eye on the left
    assert len(base.mesh.split()) == 1 and base.mesh.euler_number == 0  # one body with one through hole (the eye)
    res, _ = build({"generator": "keychain", "params": {"text": "Ayşe", "text_color": "#1F6FB2"}})
    assert len(res.parts) == 1 and res.parts[0].mesh.extents[2] == pytest.approx(4.0)


def test_keychain_nfc_pocket_and_pause(tmp_path):
    res = run_job({"generator": "keychain", "name": "n", "params": {"text": "Can", "nfc": True, "count": 3}}, tmp_path)
    base = next(p for p in res.data["parts"] if p["name"] == "base")
    assert base["pause_z"] == pytest.approx(2.0)
    m = trimesh.load(res.out_dir / "parts" / base["stl"])
    assert m.euler_number == 2 and len(m.split(only_watertight=False)) == 2  # outer skin with the eye (0) + closed NFC void (2)
    with zipfile.ZipFile(res.out_dir / "model.3mf") as z:
        x = z.read("Metadata/custom_gcode_per_layer.xml").decode()
    assert x.count('top_z="2.00" type="1"') == 1  # one pause for all three keychains on the plate
    assert any("Z=2 mm" in n for n in res.data["notes"])


def test_plates_multicolour_tower_slots_and_batches(tmp_path):
    res, _ = build({"generator": "keychain", "params": {"count": 12}})
    pls = plates.write_3mf(res.parts, tmp_path / "k.3mf")
    (tx, ty, tw, th), _ = plates._tower()
    for pl in pls:
        for _, m in pl.items:
            lo, hi = m.bounds
            assert hi[0] <= tx + 1e-6 or hi[1] <= ty + 1e-6, "object on the prime tower area"
    info = core.inspect_3mf(tmp_path / "k.3mf")
    assert info["project"]["filament_colour"] == ["#1F6FB2", "#FFFFFF"]
    assert {p["extruder"] for o in info["objects"] for p in o["parts"]} == {1, 2}
    res, _ = build({"generator": "qr_plaque", "params": {"mount": "stand"}})
    pls = plates.pack(res.parts)
    assert [[n for n, _ in pl.items] for pl in pls] == [["plaque"], ["stand"]]  # stand alone: no change per layer
    box = trimesh.creation.box((10, 10, 2))
    many = [Part(f"p{i}", "x", box, f"#0{i}0000", meta={"group": "g"}) for i in range(5)]
    with pytest.raises(ValueError, match="en çok 4"):
        plates.write_3mf(many, tmp_path / "m.3mf")


def test_qr_payloads():
    assert qr.payload("wifi", {"ssid": 'Ev;Ağı', "password": "a:b\\c", "security": "WPA"}) == r"WIFI:T:WPA;S:Ev\;Ağı;P:a\:b\\c;;"
    assert qr.payload("wifi", {"ssid": "x", "security": "nopass", "hidden": True}) == "WIFI:T:nopass;S:x;H:true;;"
    assert qr.payload("whatsapp", {"phone": "0532 123 45 67", "message": "Merhaba!"}) == "https://wa.me/905321234567?text=Merhaba%21"
    assert qr.payload("review", {"link": "ChIJabc"}).endswith("writereview?placeid=ChIJabc")
    assert qr.payload("instagram", {"user": "@workbench"}) == "https://instagram.com/workbench"
    assert qr.payload("phone", {"phone": "+90 532 123 45 67"}) == "tel:+905321234567"
    with pytest.raises(ValueError):
        qr.payload("wifi", {"ssid": ""})


@pytest.mark.parametrize("params", [
    {"password": "gizli1234", "show_password": True},
    {"kind": "whatsapp", "phone": "0532 123 45 67", "message": "Sipariş vermek istiyorum", "mount": "holes"},
    {"kind": "review", "link": "ChIJN1t_tDeuEmsRUsoyG83frY4", "ecc": "h", "mount": "magnet"},
])
def test_qr_plaque_scans_from_the_mesh(params):
    res, _ = build({"generator": "qr_plaque", "params": params})
    qrp = next(p for p in res.parts if p.name == "qr")
    assert _decodes(qrp.mesh, res.meta["qr_data"])
    assert res.meta["module_mm"] >= qr.MIN_MODULE_MM
    plate = res.parts[0]
    assert qrp.mesh.bounds[0][2] == pytest.approx(plate.mesh.bounds[1][2])


def test_qr_small_module_and_contrast_warnings():
    res, _ = build({"generator": "qr_plaque", "params": {"kind": "url", "link": "example.com/" + "x" * 80, "width_mm": 50}})
    assert any("telefon zor okur" in w for w in res.warnings)
    res, _ = build({"generator": "qr_plaque", "params": {"qr_color": "#EEEEEE"}})
    assert any("koyu" in w for w in res.warnings)


def test_pet_tag_front_back():
    back, _ = build({"generator": "pet_tag", "params": {"back_text": "Bulursanız arayın"}})
    tag = back.parts[0].mesh
    bottom = (tag.face_normals[:, 2] < -0.9) & (tag.triangles[:, :, 2].max(axis=1) < 0.01)
    flat_bottom = tag.area_faces[bottom].sum()
    assert flat_bottom < tag.area_faces[(tag.face_normals[:, 2] > 0.9)].sum()  # the engraving takes area off the bottom
    assert len(back.parts) == 2 and not any("sığmıyor" in w for w in back.warnings)
    front, _ = build({"generator": "pet_tag", "params": {"shape": "circle", "phone_side": "front"}})
    assert front.parts[1].label == "İsim + Telefon"
    assert front.parts[0].mesh.volume > tag.volume * 0.9
    bone, _ = build({"generator": "pet_tag", "params": {}})
    assert not any("küçültüldü" in w for w in bone.warnings if w.startswith("İsim"))


def test_fit_text_thickens_thin_strokes():
    w: list[str] = []
    region = shape_polygon("circle", 40).buffer(-2)
    g, _ = flat.fit_text("0532 123 45 67", "Righteous", region, 32, w, "Telefon")
    assert not core.thin_regions(g, flat.MIN_STROKE) and region.contains(g)


def test_qr_plaque_stand_assembled_preview_and_clearance():
    res, _ = build({"generator": "qr_plaque", "params": {"kind": "wifi", "title": "Test", "mount": "stand"}})
    previews = [p for p in res.parts if p.meta.get("product")]
    assert len(previews) >= 3 and all(not p.printable for p in previews)
    stand_prev = next(p for p in previews if p.name == "stand_preview")
    plaque_prev = next(p for p in previews if p.name == "plate_preview")
    assert plaque_prev.mesh.extents[2] > stand_prev.mesh.extents[2] * 3  # dik montajlı önizleme
    cap_flat = next(p for p in res.parts if p.printable and "Alt yazı" in p.label)
    plate_flat = next(p for p in res.parts if p.printable and p.name == "plate")
    assert cap_flat.mesh.bounds[0][1] - plate_flat.mesh.bounds[0][1] >= 12.0  # stand dudağı yazıyı kapatmaz
