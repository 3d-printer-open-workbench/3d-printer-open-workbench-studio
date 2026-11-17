"""Kaligraf writes laser / CNC cut paths, and joined script letters come out one part each."""
from kaligraf.job import Job, run_job
from workbench_core.vector import read_dxf_rings


def test_script_letters_cut_paths(tmp_path):
    job = Job.from_dict({"mode": "letters", "text": "Ayşe", "font": "Pacifico", "letter_height_cm": 12, "depth_mm": 15,
                         "letter_colors": ["kırmızı"], "mounting": ["tape"], "language": "tr"})
    res = run_job(job, tmp_path)
    assert {"cut_svg", "cut_dxf"} <= set(res.files)
    layers = read_dxf_rings(res.files["cut_dxf"])
    assert len(layers) == 4  # A, y, ş, e
    assert len(res.data["joints"]) == 2 and all(j["lock"] for j in res.data["joints"])
    assert "</svg>" in res.files["cut_svg"].read_text()


def test_joints_off_keeps_words(tmp_path):
    job = Job.from_dict({"mode": "letters", "text": "Ayşe", "font": "Pacifico", "letter_height_cm": 12, "depth_mm": 15,
                         "letter_colors": ["kırmızı"], "mounting": ["tape"], "language": "tr", "letter_joints": "none"})
    res = run_job(job, tmp_path, extras=False)
    assert len([p for p in res.data["parts"]]) == 2
