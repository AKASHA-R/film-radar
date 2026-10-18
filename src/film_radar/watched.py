"""「已看过」名单（data/watched.json）与 edition Issue 勾选框之间的同步。纯函数，不碰网络。

名单是唯一的事实来源；Issue 里的勾选框是用户的操作入口。设计见
docs/superpowers/specs/2026-10-17-watched-list-design.md。

命名：这里的 watched 是「用户看过」。assemble.py 里的 seen_before 是「上一期也推荐过」，两回事。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
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


# ---- Issue 任务项（spec 第 4 节）----

EDITION_MARKER = re.compile(r"<!-- film-radar:edition (\d{4}-\d{2}-\d{2}) -->")
FILM_MARK = "<!-- film:"
TASK_LINE = re.compile(r"^- \[( |x|X)\] .*<!-- film:(\d+) bot:([01]) -->\s*$")


@dataclass(frozen=True)
class Issue:
    number: int
    body: str


@dataclass(frozen=True)
class Line:
    film_id: int
    checked: bool
    bot: bool          # 程序最后一次写入时这一行勾没勾；用户的操作＝当前勾选 ≠ bot


@dataclass(frozen=True)
class ParsedIssue:
    number: int
    edition_id: str
    lines: tuple[Line, ...]


class IssueFormatError(Exception):
    def __init__(self, number: int, reasons: list[str]):
        super().__init__(f"Issue #{number} 无法解析：" + "；".join(reasons))
        self.number = number
        self.reasons = list(reasons)


def edition_marker(edition_id: str) -> str:
    return f"<!-- film-radar:edition {edition_id} -->"


def task_line(text: str, film_id: int, checked: bool) -> str:
    """一部片一行任务项。text 必须已经清理过（render._issue_text）。"""
    return f"- [{'x' if checked else ' '}] {text} <!-- film:{film_id} bot:{int(checked)} -->"


def _first_line(body: str) -> str:
    return body.split("\n", 1)[0].lstrip("\ufeff").strip()


def has_edition_marker(body: str) -> bool:
    return EDITION_MARKER.fullmatch(_first_line(body)) is not None


def parse_issue(issue: Issue) -> ParsedIssue | None:
    """不是程序管理的 Issue（没有标记、也没有任何任务项标记）返回 None。

    是程序管理的、但有坏行或重复编号，抛 IssueFormatError：整个 Issue 跳过、一个勾都不采用，
    手改坏的 Issue 里分不清哪些勾是用户的意图。标记不在第一行（用户在上面加了字）也算坏，
    否则这个 Issue 会被静默忽略。按 "\\n" 分行，行尾的 "\\r" 由正则的 \\s* 吸收。"""
    rows = issue.body.split("\n")
    marker = EDITION_MARKER.fullmatch(_first_line(issue.body))
    if marker is None:
        if any(FILM_MARK in row or EDITION_MARKER.search(row) for row in rows):
            raise IssueFormatError(issue.number, ["第一行的 edition 标记不见了（是不是在它上面加了文字？）"])
        return None
    lines, reasons, seen = [], [], set()
    for n, row in enumerate(rows, 1):
        if FILM_MARK not in row:
            continue
        hit = TASK_LINE.match(row)
        if hit is None:
            reasons.append(f"第 {n} 行格式不对：{row.strip()[:80]}")
            continue
        film_id = int(hit.group(2))
        if film_id in seen:
            reasons.append(f"第 {n} 行：编号 {film_id} 出现了两次")
            continue
        seen.add(film_id)
        lines.append(Line(film_id, hit.group(1) != " ", hit.group(3) == "1"))
    if reasons:
        raise IssueFormatError(issue.number, reasons)
    return ParsedIssue(issue.number, marker.group(1), tuple(lines))


# ---- 同步（spec 第 5 节）----

@dataclass(frozen=True)
class Action:
    issue: int
    film_id: int
    watched: bool          # True＝勾上（标为看过），False＝取消（撤销）


@dataclass(frozen=True)
class Rewrite:
    issue: int
    film_id: int
    observed: bool         # 计算时读到的勾选：改写时用它判断用户之后有没有又改过（spec 第 6 节第 4 步）
    target: bool


@dataclass(frozen=True)
class Problem:
    issue: int
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    """data/editions 里的编号：某一期里某部片的版本编号；每个主编号跨期合并后的版本编号；片名。"""
    by_edition: dict
    by_primary: dict
    titles: dict

    def versions(self, edition_id: str, film_id: int) -> frozenset[int]:
        return self.by_edition.get((edition_id, film_id), frozenset({film_id}))


@dataclass
class SyncResult:
    films: dict[int, dict]
    changed: bool
    actions: list[Action]
    conflicts: list[int]
    rewrites: list[Rewrite]
    problems: list[Problem]


def build_catalog(editions: list[dict]) -> Catalog:
    by_edition, by_primary, titles = {}, {}, {}
    for edition in sorted(editions, key=lambda e: e["edition_id"]):
        for film in [*edition["films"], *edition.get("watched_showing", [])]:      # 老数据没有 watched_showing
            ids = version_ids(film)
            by_edition[(edition["edition_id"], film["film_id"])] = ids
            by_primary[film["film_id"]] = by_primary.get(film["film_id"], frozenset()) | ids
            titles[film["film_id"]] = film["title"]
    return Catalog(by_edition, by_primary, titles)


def sync(films: dict[int, dict], issues: list[Issue], catalog: Catalog, now: str) -> SyncResult:
    """films 是旧名单，issues 是所有 edition Issue（含已关闭的），now 是多伦多时区的 ISO 时间。"""
    parsed, problems = [], []
    for issue in sorted(issues, key=lambda i: i.number):
        try:
            result = parse_issue(issue)
        except IssueFormatError as e:
            problems.append(Problem(e.number, tuple(e.reasons)))
            continue
        if result is not None:
            parsed.append(result)

    # 用户的操作＝当前勾选和 bot 不一致的行。按 Issue 编号从小到大应用，冲突时编号大的（较新的一期）自然胜出。
    # 不用 updated_at：评论、关闭、改标签都会刷新它，反映不了勾选的先后
    actions = [Action(p.number, line.film_id, line.checked) for p in parsed for line in p.lines if line.checked != line.bot]
    kinds: dict[int, set[bool]] = {}
    for action in actions:
        kinds.setdefault(action.film_id, set()).add(action.watched)
    conflicts = sorted(film_id for film_id, seen in kinds.items() if len(seen) > 1)

    edition_of = {p.number: p.edition_id for p in parsed}
    new = {film_id: {**entry, "ids": list(entry["ids"])} for film_id, entry in films.items()}
    for action in actions:
        ids = catalog.versions(edition_of[action.issue], action.film_id)
        covering = [key for key, entry in new.items() if not ids.isdisjoint(entry["ids"])]
        if action.watched and not covering:          # 已经在名单里的片再勾一次，不改动已有条目
            # 本轮里较旧的 Issue 刚把它取消、较新的又勾上：原条目原样放回，不刷新 since（spec 第 3 节）
            deleted = {key: entry for key, entry in films.items() if key not in new and not ids.isdisjoint(entry["ids"])}
            if deleted:
                for key, entry in deleted.items():
                    new[key] = {**entry, "ids": list(entry["ids"])}
            else:
                new[action.film_id] = {
                    "title": catalog.titles.get(action.film_id, str(action.film_id)),
                    "since": now,
                    "ids": sorted(ids | catalog.by_primary.get(action.film_id, frozenset())),
                }
        elif not action.watched:
            for key in covering:
                del new[key]

    listed = watched_ids(new)
    rewrites = []
    for p in parsed:
        for line in p.lines:
            target = not catalog.versions(p.edition_id, line.film_id).isdisjoint(listed)
            if line.checked != target or line.bot != target:
                rewrites.append(Rewrite(p.number, line.film_id, line.checked, target))
    return SyncResult(new, new != films, actions, conflicts, rewrites, problems)


def apply_rewrites(body: str, rewrites: list[Rewrite]) -> str:
    """在改写前新读到的正文上逐行合并（spec 第 6 节第 4 步），只动勾选框和 bot 两处，其他文字原样保留。

    bot 一律写成目标；勾选框只在「新读到的勾选」等于「计算时读到的勾选」时才改，否则保留用户刚改的勾选：
    那一行变成「当前 ≠ bot」，下一次同步能认出这个操作。"""
    plan = {r.film_id: r for r in rewrites}
    rows = body.split("\n")
    for i, row in enumerate(rows):
        hit = TASK_LINE.match(row)
        if hit is None or int(hit.group(2)) not in plan:
            continue
        rewrite = plan[int(hit.group(2))]
        current = hit.group(1) != " "
        checked = rewrite.target if current == rewrite.observed else current
        start, end = hit.span(3)
        rows[i] = f"- [{'x' if checked else ' '}]" + row[5:start] + str(int(rewrite.target)) + row[end:]
    return "\n".join(rows)
