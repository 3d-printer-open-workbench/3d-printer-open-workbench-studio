"""Slice our 3MF with the real OrcaSlicer CLI (skipped when the binary is not installed).

Set WORKBENCH_ORCA to the AppRun/orca-slicer path; on a headless box xvfb-run is used when found.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from kaligraf.export3mf import inspect_3mf
from kaligraf.job import Job, run_job

ORCA = Path(os.environ.get("WORKBENCH_ORCA") or shutil.which("orcaslicer") or shutil.which("orca-slicer") or "orcaslicer")
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"

pytestmark = pytest.mark.skipif(not ORCA.exists(), reason="OrcaSlicer CLI not installed")


def _orca(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    cmd = [str(ORCA), *args]
    if shutil.which("xvfb-run"):
        cmd = ["xvfb-run", "-a", *cmd]
    env = {**os.environ, "XDG_RUNTIME_DIR": os.environ.get("XDG_RUNTIME_DIR", "/tmp/xdg-workbench")}
    Path(env["XDG_RUNTIME_DIR"]).mkdir(parents=True, exist_ok=True)
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=600)


@pytest.fixture
def orca_dir():
    """A scratch folder OrcaSlicer can read: flatpak / snap builds only see $HOME, not /tmp."""
    import tempfile

    base = Path(os.environ.get("WORKBENCH_SLICE_DIR") or Path.home() / ".cache" / "workbench-studio" / "slice")
    base.mkdir(parents=True, exist_ok=True)
    d = Path(tempfile.mkdtemp(prefix="test-orca-", dir=base))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _job(name: str) -> Job:
    return Job.from_dict(yaml.safe_load((EXAMPLES / name).read_text(encoding="utf-8")))


@pytest.mark.parametrize("example", ["sample_flat.yaml", "sukru_letters.yaml"])
def test_orca_loads_and_slices_our_3mf(example, orca_dir):
    tmp_path = orca_dir
    res = run_job(_job(example), tmp_path)
    path = res.files["3mf"]
    info = inspect_3mf(path)
    n_ext = max(p["extruder"] for o in info["objects"] for p in o["parts"])
    assert n_ext >= 2

    # loader does not crash and sees our objects
    r = _orca(["--info", str(path)], tmp_path)
    assert r.returncode == 0, r.stdout[-500:] + r.stderr[-500:]

    tools: set[int] = set()
    for plate in range(1, len(info["plates"]) + 1):
        work = tmp_path / f"slice{plate}"
        work.mkdir()
        _orca(["--arrange", "0", "--slice", str(plate), "--outputdir", str(work), str(path)], work)
        out = json.loads((work / "result.json").read_text())
        assert out["return_code"] == 0, (plate, out["error_string"])
        gcode = (work / f"plate_{plate}.gcode").read_text()
        tools |= {int(m) for m in re.findall(r"^T(\d+)\s*$", gcode, re.M)}
    assert tools == set(range(n_ext))


def test_orca_slice_all_plates_in_one_run(orca_dir):
    """`--slice 0` (all plates, default arrange behaviour) must keep our placement and succeed."""
    tmp_path = orca_dir
    res = run_job(_job("sukru_letters.yaml"), tmp_path)
    work = tmp_path / "all"
    work.mkdir()
    _orca(["--slice", "0", "--outputdir", str(work), str(res.files["3mf"])], work)
    out = json.loads((work / "result.json").read_text())
    assert out["return_code"] == 0, out["error_string"]
    assert len(list(work.glob("plate_*.gcode"))) == res.data["plates"]
