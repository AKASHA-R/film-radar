"""读取并校验 config/settings.toml。"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from datetime import date
from pathlib import Path

CADENCE_DAYS = 14


class SettingsError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    home_lat: float
    home_lon: float
    radius_km: float
    showtime_days: int
    coming_soon_days: int
    non_film_categories: tuple[str, ...]
    shortlist_cap: int
    must_cap: int
    outside_cap: int
    search_max_uses: int
    anchor_date: date
    stale_after_days: int
    model: str
    price_input_per_mtok: float
    price_output_per_mtok: float
    triage_model: str
    triage_price_input_per_mtok: float
    triage_price_output_per_mtok: float
    search_price_per_search: float
    timezone: str
    page_url: str


def load_settings(path: Path) -> Settings:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    names = {f.name for f in fields(Settings)}
    missing = sorted(names - set(raw))
    if missing:
        raise SettingsError(f"配置缺少键: {', '.join(missing)}")
    unknown = sorted(set(raw) - names)
    if unknown:
        raise SettingsError(f"配置里有不认识的键: {', '.join(unknown)}")
    if not isinstance(raw["anchor_date"], date):
        raise SettingsError("anchor_date 必须写成 TOML 日期（不加引号），例如 2026-10-08")
    raw["non_film_categories"] = tuple(raw["non_film_categories"])
    settings = Settings(**raw)
    if settings.showtime_days < CADENCE_DAYS:
        raise SettingsError(
            f"showtime_days = {settings.showtime_days}，小于两期间隔 {CADENCE_DAYS} 天。"
            "排片窗口比两期间隔短时，零星放映的片会两期都查不到。"
        )
    return settings
