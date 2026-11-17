import importlib

from maker import core, prompt
from maker.generators import GENERATORS
from maker.job import run_job


def test_engine_is_workbench_core():
    assert core.build_text.__module__ == "workbench_core.text2d"
    kal = importlib.import_module("kaligraf.text2d")  # Kaligraf's old name is the same module object
    assert kal is importlib.import_module("workbench_core.text2d")


def test_every_generator_has_a_prompt_product():
    products = prompt.load_template()["products"]
    assert set(GENERATORS) <= set(products)


def test_job_writes_tr_en_prompts(tmp_path):
    res = run_job({"generator": "keychain", "name": "k", "params": {"text": "Ece", "base_color": "#1F6FB2"},
                   "prompt": {"scene": "vitrin", "extra": "hediye kutusu"}}, tmp_path)
    tr = (res.out_dir / "prompt_tr.txt").read_text(encoding="utf-8")
    en = (res.out_dir / "prompt_en.txt").read_text(encoding="utf-8")
    assert '"Ece"' in tr and '"Ece"' in en
    assert "mağaza vitrini" in tr and "shop window" in en and "hediye kutusu" in tr
    assert "anahtarlık" in tr and "keychain" in en and "mavi" in tr
    assert res.data["files"]["prompt_tr"] == "prompt_tr.txt" and res.data["prompts"]["en"] == en.strip()


def test_prompt_size_is_the_product_not_the_molds(tmp_path):
    res = run_job({"generator": "thermoform", "name": "t", "params": {"width_mm": 60}}, tmp_path)
    tr = res.data["prompts"]["tr"]
    assert "parlak şeffaf kubbeli" in tr and "6 ×" in tr.replace("6.0", "6")
