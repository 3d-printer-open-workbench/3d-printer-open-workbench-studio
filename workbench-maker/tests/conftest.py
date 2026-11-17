import pytest


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """No test writes to the real cache / config / output."""
    from maker import sheets

    monkeypatch.setattr(sheets, "USER_FILE", tmp_path / "no-user-sheets.yaml")
    from maker import estimate

    monkeypatch.setattr(estimate, "USER_FILE", tmp_path / "no-user-costs.yaml")
