from datetime import date

import pytest

from film_radar.settings import CADENCE_DAYS, SettingsError, load_settings
from helpers import ROOT

REPO_SETTINGS = ROOT / "config" / "settings.toml"


def variant(tmp_path, old: str, new: str):
    text = REPO_SETTINGS.read_text(encoding="utf-8")
    assert old in text, f"仓库配置里找不到 {old!r}，测试前提不成立"
    path = tmp_path / "settings.toml"
    path.write_text(text.replace(old, new), encoding="utf-8")
    return path


def test_loads_repo_settings(settings):
    assert settings.home_lat == 43.6532
    assert settings.home_lon == -79.3832
    assert settings.radius_km == 40
    assert settings.showtime_days == 14
    assert settings.coming_soon_days == 14
    assert settings.non_film_categories == (
        "Opera", "Concert", "Stage", "Stage Performance", "Television Event", "Sport",
    )
    assert settings.shortlist_cap == 15
    assert settings.must_cap == 6
    assert settings.outside_cap == 2
    assert settings.search_max_uses == 5
    assert settings.anchor_date == date(2026, 10, 8)
    assert settings.stale_after_days == 16
    assert settings.model == "claude-sonnet-5-5"
    assert settings.price_input_per_mtok == 2.0
    assert settings.price_output_per_mtok == 10.0
    assert settings.timezone == "America/Toronto"
    assert settings.page_url == "https://akasha-r.github.io/film-radar/"


def test_anchor_date_is_a_thursday(settings):
    assert settings.anchor_date.weekday() == 3


def test_cadence_is_two_weeks():
    assert CADENCE_DAYS == 14


def test_rejects_showtime_window_shorter_than_cadence(tmp_path):
    path = variant(tmp_path, "showtime_days = 14", "showtime_days = 13")
    with pytest.raises(SettingsError, match="showtime_days"):
        load_settings(path)


def test_accepts_showtime_window_longer_than_cadence(tmp_path):
    path = variant(tmp_path, "showtime_days = 14", "showtime_days = 21")
    assert load_settings(path).showtime_days == 21


def test_rejects_missing_key(tmp_path):
    path = variant(tmp_path, "must_cap = 6\n", "")
    with pytest.raises(SettingsError, match="must_cap"):
        load_settings(path)


def test_rejects_unknown_key(tmp_path):
    path = variant(tmp_path, "must_cap = 6\n", "must_cap = 6\nmust_capp = 7\n")
    with pytest.raises(SettingsError, match="must_capp"):
        load_settings(path)


def test_rejects_anchor_date_written_as_string(tmp_path):
    path = variant(tmp_path, "anchor_date = 2026-10-08", 'anchor_date = "2026-10-08"')
    with pytest.raises(SettingsError, match="anchor_date"):
        load_settings(path)
