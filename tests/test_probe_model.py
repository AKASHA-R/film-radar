"""探针要测的是流水线实际会用的模型。探针里硬编码一份模型名，换模型时会悄悄漂移：
探针继续测旧模型、报"通过"，而线上用的新模型从没被测过。"""
import importlib.util

from helpers import ROOT


def test_probe_tests_the_model_the_pipeline_uses(settings):
    spec = importlib.util.spec_from_file_location("probe", ROOT / "scripts" / "probe.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    assert probe.MODEL == settings.model
