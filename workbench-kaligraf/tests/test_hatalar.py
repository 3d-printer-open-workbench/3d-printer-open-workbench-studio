from workbench_core.hatalar import turkce


def test_turkce_known_messages():
    assert turkce("At most 4 colors are supported, got 5").startswith("En fazla 4 renk")
    assert turkce("depth must be between 2 and 250 mm") == "Harf derinliği 2 ile 250 mm arasında olmalı."
    assert "2000×300 mm" not in turkce("unit body (300x200) does not fit the bed") and "300×200 mm" in turkce("unit body (300x200) does not fit the bed")
    assert turkce("bilinmeyen bir şey") == "bilinmeyen bir şey"
