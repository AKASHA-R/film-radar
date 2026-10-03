import pytest

from film_radar.settings import load_settings
from helpers import ROOT


@pytest.fixture
def settings():
    return load_settings(ROOT / "config" / "settings.toml")
