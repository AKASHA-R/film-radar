import pytest

from film_radar.settings import load_settings
from helpers import ROOT


@pytest.fixture
def settings():
    return load_settings(ROOT / "config" / "settings.toml")


@pytest.fixture(autouse=True)
def no_github_credentials(monkeypatch):
    """测试绝不能拿到真令牌：漏了替身的测试会以「没有令牌」失败，而不是去改真 Issue。"""
    for name in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_REPOSITORY"):
        monkeypatch.delenv(name, raising=False)
