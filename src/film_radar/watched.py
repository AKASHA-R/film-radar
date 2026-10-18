"""「已看过」名单（data/watched.json）与 edition Issue 勾选框之间的同步。纯函数，不碰网络。

名单是唯一的事实来源；Issue 里的勾选框是用户的操作入口。设计见
docs/superpowers/specs/2026-10-17-watched-list-design.md。

命名：这里的 watched 是「用户看过」。assemble.py 里的 seen_before 是「上一期也推荐过」，两回事。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

WATCHED_VERSION = 1
_ID = re.compile(r"[0-9]+")


class WatchedError(Exception):
    """名单文件格式不对。绝不能当成空名单：那样同步会把所有 Issue 里的勾全部清掉。"""


def load_watched(text: str | None) -> dict[int, dict]:
    """None（文件不存在）等于空名单。返回 {主编号: {"title", "since", "ids"}}，键和 ids 都是整数。"""
    if text is None:
        return {}
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as e:
        raise WatchedError(f"data/watched.json 不是合法的 JSON：{e}") from e
    if not isinstance(raw, dict) or raw.get("version") != WATCHED_VERSION or not isinstance(raw.get("films"), dict):
        raise WatchedError(f'data/watched.json 顶层必须是 {{"version": {WATCHED_VERSION}, "films": {{...}}}}')
    films = {}
    for key, entry in raw["films"].items():
        if not _ID.fullmatch(key):
            raise WatchedError(f"data/watched.json 的键必须是数字编号：{key!r}")
        if not isinstance(entry, dict) or set(entry) != {"title", "since", "ids"}:
            raise WatchedError(f"data/watched.json 的条目 {key} 必须正好有 title、since、ids 三个字段")
        ids = entry["ids"]
        if not (isinstance(entry["title"], str) and isinstance(entry["since"], str) and isinstance(ids, list)
                and ids and all(type(i) is int for i in ids) and int(key) in ids):
            raise WatchedError(f"data/watched.json 的条目 {key} 内容不对（ids 必须是非空整数列表，且包含 {key}）")
        films[int(key)] = {"title": entry["title"], "since": entry["since"], "ids": sorted(set(ids))}
    return films


def load_watched_file(path: Path) -> dict[int, dict]:
    return load_watched(path.read_text(encoding="utf-8") if path.exists() else None)


def dump_watched(films: dict[int, dict]) -> str:
    """写出格式固定（键排序、缩进 1），避免无意义的差异。"""
    data = {"version": WATCHED_VERSION, "films": {
        str(film_id): {"title": entry["title"], "since": entry["since"], "ids": sorted(entry["ids"])}
        for film_id, entry in films.items()
    }}
    return json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def watched_ids(films: dict[int, dict]) -> frozenset[int]:
    return frozenset(i for entry in films.values() for i in entry["ids"])


def version_ids(film: dict) -> frozenset[int]:
    """一部片的所有编号：主编号加各版本编号。候选、一期里的片（versions）和「看过、仍在映」的条目（version_ids）都能用。"""
    if "version_ids" in film:
        return frozenset([film["film_id"], *film["version_ids"]])
    return frozenset([film["film_id"], *(v["film_id"] for v in film.get("versions", []))])


def is_watched(film: dict, watched: frozenset[int]) -> bool:
    """任一版本编号在名单里就算看过：版本集合在真实数据里会变（spec 第 3 节）。"""
    return not version_ids(film).isdisjoint(watched)


def split_watched(candidates: list[dict], watched: frozenset[int]) -> tuple[list[dict], list[dict]]:
    """把候选分成「继续评估」和「看过、仍在映」。后者只留页面和 Issue 要用的字段，按片名排序。"""
    rest, showing = [], []
    for candidate in candidates:
        (showing if is_watched(candidate, watched) else rest).append(candidate)
    entries = [{
        "film_id": c["film_id"], "title": c["title"], "status": c["status"], "release_date": c["release_date"],
        "weeks_in_release": c["weeks_in_release"], "detail_url": c["detail_url"],
        "version_ids": sorted(version_ids(c)),
    } for c in showing]
    return rest, sorted(entries, key=lambda e: (e["title"], e["film_id"]))
