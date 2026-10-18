import json

import pytest

from film_radar.watched import (
    WatchedError, dump_watched, is_watched, load_watched, load_watched_file, split_watched, version_ids, watched_ids,
)
from helpers import make_candidate

ENTRY = {"title": "潘神的迷宫", "since": "2026-10-17T14:03:00-04:00", "ids": [62050]}


def listing(films):
    return json.dumps({"version": 1, "films": films}, ensure_ascii=False)


# ---- 名单文件（spec 第 3 节）----

def test_a_missing_file_is_an_empty_list(tmp_path):
    assert load_watched(None) == {}
    assert load_watched_file(tmp_path / "watched.json") == {}


def test_keys_and_ids_become_integers_and_ids_are_sorted():
    films = load_watched(listing({"62050": {**ENTRY, "ids": [62252, 62050, 62050]}}))
    assert films == {62050: {**ENTRY, "ids": [62050, 62252]}}


@pytest.mark.parametrize("bad", [
    "", "{not json", "[]",
    json.dumps({"films": {}}), json.dumps({"version": 2, "films": {}}), json.dumps({"version": 1, "films": []}),
    listing({"abc": ENTRY}), listing({"６２": ENTRY}),
    listing({"62050": {"title": "x", "since": "y"}}), listing({"62050": {**ENTRY, "extra": 1}}),
    listing({"62050": {**ENTRY, "ids": []}}), listing({"62050": {**ENTRY, "ids": ["62050"]}}),
    listing({"62050": {**ENTRY, "ids": [1]}}), listing({"62050": {**ENTRY, "ids": [62050, True]}}),
    listing({"62050": {**ENTRY, "title": None}}),
])
def test_a_malformed_file_raises_instead_of_meaning_empty(bad):
    """当成空名单的话，同步会把所有 Issue 里的勾全部清掉。"""
    with pytest.raises(WatchedError):
        load_watched(bad)


def test_dump_is_stable_and_round_trips():
    films = {62050: dict(ENTRY), 100: {"title": "Z", "since": "s", "ids": [100]}}
    text = dump_watched(films)
    assert text == dump_watched(dict(reversed(list(films.items()))))
    assert load_watched(text) == films
    assert text.endswith("\n") and '\n "films": {' in text and "潘神的迷宫" in text


# ---- 匹配 ----

def test_watched_ids_is_the_union_of_every_entry():
    films = {1: {"title": "a", "since": "s", "ids": [1, 5]}, 2: {"title": "b", "since": "s", "ids": [2]}}
    assert watched_ids(films) == {1, 2, 5}


def test_a_film_is_watched_when_any_version_is_listed():
    versions = [{"film_id": 62050, "name": "A", "language": "English", "subtitle": ""},
                {"film_id": 62252, "name": "A (Spanish)", "language": "Spanish", "subtitle": ""}]
    candidate = make_candidate(62050, "A", versions=versions)
    assert version_ids(candidate) == {62050, 62252}
    assert is_watched(candidate, frozenset({62252}))
    assert not is_watched(candidate, frozenset({1}))


def test_version_ids_reads_watched_showing_entries_too():
    assert version_ids({"film_id": 7, "version_ids": [7, 8]}) == {7, 8}


def test_split_keeps_the_order_of_the_rest_and_sorts_watched_by_title():
    zeta, alpha, mid = make_candidate(1, "Zeta"), make_candidate(2, "Alpha"), make_candidate(3, "Mid")
    rest, showing = split_watched([zeta, alpha, mid], frozenset({1, 2}))
    assert rest == [mid]
    assert [e["title"] for e in showing] == ["Alpha", "Zeta"]
    assert showing[0] == {
        "film_id": 2, "title": "Alpha", "status": "now_playing", "release_date": "2026-10-02",
        "weeks_in_release": 1, "detail_url": "https://www.cineplex.com/movie/film-2", "version_ids": [2],
    }


# ---- Issue 任务项（spec 第 4 节）----

from film_radar.watched import (  # noqa: E402
    Issue, IssueFormatError, Line, ParsedIssue, edition_marker, has_edition_marker, parse_issue, task_line,
)

FJORD = "- [ ] **Fjord** · 在映第 2 周：一句话 <!-- film:62301 bot:0 -->"
BODY = "\n".join([
    "<!-- film-radar:edition 2026-10-22 -->",
    "第 4 期重点推荐：",
    "",
    FJORD,
    "",
    "看过、仍在映（取消勾选可撤销）：",
    "",
    "- [x] **Pan** · 重映（2006 年上映） <!-- film:62050 bot:1 -->",
    "",
    "cc @AKASHA-R",
    "",
])


def test_marker_and_task_line_formats():
    assert edition_marker("2026-10-22") == "<!-- film-radar:edition 2026-10-22 -->"
    assert task_line("**A** · 在映第 1 周", 5, True) == "- [x] **A** · 在映第 1 周 <!-- film:5 bot:1 -->"
    assert task_line("**A** · 在映第 1 周", 5, False) == "- [ ] **A** · 在映第 1 周 <!-- film:5 bot:0 -->"
    assert has_edition_marker(BODY) and not has_edition_marker("备注\n" + BODY) and not has_edition_marker("")


def test_parse_reads_every_task_line():
    assert parse_issue(Issue(7, BODY)) == ParsedIssue(7, "2026-10-22", (Line(62301, False, False), Line(62050, True, True)))


def test_parse_accepts_uppercase_x_and_crlf():
    """GitHub 网页编辑过的正文可能是 \\r\\n 换行（Review Focus 1）。"""
    body = BODY.replace("- [ ] **Fjord**", "- [X] **Fjord**").replace("\n", "\r\n")
    parsed = parse_issue(Issue(7, body))
    assert parsed.edition_id == "2026-10-22"
    assert parsed.lines == (Line(62301, True, False), Line(62050, True, True))


def test_an_issue_without_marker_or_film_lines_is_ignored():
    assert parse_issue(Issue(3, "第 2 期重点推荐：\n\n- **A**（在映第 1 周）：旧格式\n")) is None
    assert parse_issue(Issue(9, "")) is None


def test_text_inserted_above_the_marker_is_reported_not_ignored():
    """静默忽略的话，这个 Issue 里的勾永远不生效（Review Focus 2）。"""
    with pytest.raises(IssueFormatError, match="第一行"):
        parse_issue(Issue(7, "我的备注\n" + BODY))


@pytest.mark.parametrize("broken", [
    "- [ ] **Fjord** · x <!-- film:62301 bot:2 -->",
    "- [ ] **Fjord** · x <!-- film:abc bot:0 -->",
    "* [ ] **Fjord** · x <!-- film:62301 bot:0 -->",
    "  - [ ] **Fjord** · x <!-- film:62301 bot:0 -->",
    "- [ ] **Fjord** · x <!-- film:62301 bot:0 --> 我加的字",
])
def test_a_broken_line_makes_the_whole_issue_unparsable(broken):
    with pytest.raises(IssueFormatError) as caught:
        parse_issue(Issue(7, BODY.replace(FJORD, broken)))
    assert caught.value.number == 7 and "第 4 行" in caught.value.reasons[0]


def test_a_film_listed_twice_makes_the_whole_issue_unparsable():
    with pytest.raises(IssueFormatError, match="两次"):
        parse_issue(Issue(7, BODY.replace("film:62050", "film:62301")))


# ---- 同步（spec 第 5 节）----

from film_radar.watched import Action, Rewrite, build_catalog, sync  # noqa: E402
from helpers import task_issue  # noqa: E402

NOW = "2026-10-18T09:00:00-04:00"


def edition(edition_id, *film_ids, versions=None, showing=()):
    versions = versions or {}
    data = {"edition_id": edition_id, "films": [
        {"film_id": f, "title": f"Film {f}", "versions": [{"film_id": v} for v in versions.get(f, [f])]}
        for f in film_ids
    ]}
    if showing:
        data["watched_showing"] = [{"film_id": f, "title": f"Film {f}", "version_ids": [f]} for f in showing]
    return data


CATALOG = build_catalog([edition("2026-10-03", 1, 2), edition("2026-10-08", 1, 3)])


def entry(film_id, since=NOW, ids=None):
    return {"title": f"Film {film_id}", "since": since, "ids": ids or [film_id]}


def run(films, issues, catalog=CATALOG):
    return sync(films, [Issue(number, body) for number, body in issues.items()], catalog, NOW)


def test_a_tick_adds_the_film_and_plans_every_issue_that_shows_it():
    result = run({}, {2: task_issue("2026-10-03", (1, True, False), (2, False, False)),
                      5: task_issue("2026-10-08", (1, False, False), (3, False, False))})
    assert result.films == {1: entry(1)} and result.changed
    assert result.actions == [Action(2, 1, True)]
    assert result.rewrites == [Rewrite(2, 1, True, True), Rewrite(5, 1, False, True)]
    assert result.conflicts == [] and result.problems == []


def test_an_untick_removes_the_film_everywhere():
    result = run({1: entry(1)}, {2: task_issue("2026-10-03", (1, False, True)),
                                 5: task_issue("2026-10-08", (1, True, True))})
    assert result.films == {} and result.changed
    assert result.actions == [Action(2, 1, False)]
    assert result.rewrites == [Rewrite(2, 1, False, False), Rewrite(5, 1, True, False)]


def test_the_list_wins_over_an_issue_left_behind_by_a_failed_rewrite():
    """名单是事实来源：Issue 和名单不一致、却没有用户操作（勾选＝bot），按名单改 Issue，不反过来改名单。"""
    result = run({1: entry(1)}, {5: task_issue("2026-10-08", (1, False, False))})
    assert result.films == {1: entry(1)} and not result.changed and result.actions == []
    assert result.rewrites == [Rewrite(5, 1, False, True)]


def test_conflicting_actions_are_settled_by_the_newer_issue():
    newer_unticks = run({}, {5: task_issue("2026-10-08", (1, False, True)), 2: task_issue("2026-10-03", (1, True, False))})
    assert newer_unticks.films == {} and newer_unticks.conflicts == [1]
    listed = {1: entry(1, since="2026-10-01T00:00:00-04:00")}
    newer_ticks = run(listed, {2: task_issue("2026-10-03", (1, False, True)), 5: task_issue("2026-10-08", (1, True, False))})
    assert newer_ticks.conflicts == [1]
    assert newer_ticks.films == listed and not newer_ticks.changed          # 名单里已有的片再被勾上：原条目原样保留


def test_an_unparsable_issue_is_skipped_without_blocking_the_others():
    unparsable = task_issue("2026-10-03", (1, True, False)).replace("bot:0", "bot:9")
    result = run({}, {2: unparsable, 5: task_issue("2026-10-08", (3, True, False))})
    assert result.films == {3: entry(3)}
    assert [p.issue for p in result.problems] == [2] and "格式不对" in result.problems[0].reasons[0]
    assert {r.issue for r in result.rewrites} == {5}


def test_issues_without_the_edition_marker_are_ignored():
    result = run({}, {3: "第 2 期重点推荐：\n\n- **Film 1**（在映第 1 周）：旧格式\n",
                      9: "film-radar 运行失败\n\ncc @AKASHA-R\n"})
    assert result.films == {} and result.actions == [] and result.rewrites == [] and result.problems == []


def test_a_second_run_on_the_settled_issues_does_nothing():
    first = run({}, {2: task_issue("2026-10-03", (1, True, False), (2, False, False)),
                     5: task_issue("2026-10-08", (1, False, False))})
    second = run(first.films, {2: task_issue("2026-10-03", (1, True, True), (2, False, False)),
                               5: task_issue("2026-10-08", (1, True, True))})
    assert second.films == first.films
    assert not second.changed and second.actions == [] and second.rewrites == []


def test_ticking_a_listed_film_again_keeps_its_entry():
    old = entry(1, since="2026-10-01T00:00:00-04:00")
    result = run({1: old}, {5: task_issue("2026-10-08", (1, True, False))})
    assert result.films == {1: old} and not result.changed


def test_unticking_a_film_that_is_not_listed_changes_nothing():
    result = run({}, {5: task_issue("2026-10-08", (1, False, True))})
    assert result.films == {} and not result.changed
    assert result.rewrites == [Rewrite(5, 1, False, False)]          # 只把 bot 对齐


def test_a_tick_records_every_version_seen_for_that_film():
    catalog = build_catalog([edition("2026-10-03", 1), edition("2026-10-08", 1, versions={1: [1, 4]})])
    result = run({}, {2: task_issue("2026-10-03", (1, True, False))}, catalog)
    assert result.films == {1: entry(1, ids=[1, 4])}


def test_films_are_matched_by_any_version_when_the_primary_id_changes():
    catalog = build_catalog([edition("2026-10-08", 1, versions={1: [1, 4]}), edition("2026-10-22", 4)])
    listed = {1: entry(1, ids=[1, 4])}
    result = run(listed, {7: task_issue("2026-10-22", (4, False, False))}, catalog)
    assert result.rewrites == [Rewrite(7, 4, False, True)] and not result.changed
    assert run(listed, {7: task_issue("2026-10-22", (4, False, True))}, catalog).films == {}


def test_a_film_missing_from_the_editions_is_still_recorded():
    result = run({}, {5: task_issue("2026-10-08", (9000001, True, False))})
    assert result.films == {9000001: {"title": "9000001", "since": NOW, "ids": [9000001]}}


def test_catalog_reads_watched_showing_and_tolerates_old_editions():
    catalog = build_catalog([edition("2026-10-03", 1), edition("2026-10-22", 2, showing=(5,))])
    assert catalog.versions("2026-10-22", 5) == {5}
    assert catalog.versions("2026-10-03", 1) == {1}
    assert catalog.versions("2026-10-03", 77) == {77}          # 没见过的片只认它自己的编号
    assert catalog.titles[5] == "Film 5"


def test_a_conflict_across_primary_ids_keeps_the_original_entry():
    catalog = build_catalog([edition("2026-10-08", 1, versions={1: [1, 4]}), edition("2026-10-22", 4)])
    listed = {1: entry(1, since="2026-10-01T00:00:00-04:00", ids=[1, 4])}
    result = run(listed, {5: task_issue("2026-10-08", (1, False, True)), 7: task_issue("2026-10-22", (4, True, False))}, catalog)
    assert result.films == listed and not result.changed


def test_an_issue_ticked_for_a_film_missing_from_the_list_is_unticked():
    """名单是事实来源，这个方向也一样：勾选和 bot 一致、名单里却没有，按名单把勾去掉。"""
    result = run({}, {5: task_issue("2026-10-08", (1, True, True))})
    assert result.films == {} and not result.changed and result.actions == []
    assert result.rewrites == [Rewrite(5, 1, True, False)]


# ---- 改写合并（spec 第 6 节第 4 步）----

from film_radar.watched import apply_rewrites  # noqa: E402
from helpers import toggle  # noqa: E402


def lines_of(body):
    return parse_issue(Issue(0, body)).lines


def test_a_rewrite_sets_checkbox_and_bot_to_the_target():
    out = apply_rewrites(task_issue("2026-10-08", (1, False, False), (3, False, False)), [Rewrite(5, 1, False, True)])
    assert lines_of(out) == (Line(1, True, True), Line(3, False, False))


def test_a_rewrite_only_touches_the_checkbox_and_the_bot_digit():
    body = task_issue("2026-10-08", (1, False, False)).replace("**Film 1**", "**Film 1** 和朋友一起看").replace("\n", "\r\n")
    out = apply_rewrites(body, [Rewrite(5, 1, False, True)])
    assert out == body.replace("- [ ] **Film 1**", "- [x] **Film 1**").replace("film:1 bot:0", "film:1 bot:1")


def test_a_box_the_user_changed_after_the_computation_keeps_the_users_choice():
    body = task_issue("2026-10-08", (1, False, False))          # 计算时读到「勾上」，改写前用户又取消了
    out = apply_rewrites(body, [Rewrite(5, 1, True, True)])
    assert lines_of(out) == (Line(1, False, True),)             # 勾选保留用户的，bot 写成目标：下一轮认得出这是撤销


def round_trip(films, bodies, user=None):
    """跑一轮同步再改写。user(bodies) 在计算之后、改写之前修改正文，模拟用户手快。"""
    result = sync(films, [Issue(n, b) for n, b in bodies.items()], CATALOG, NOW)
    if user:
        user(bodies)
    for number in sorted({r.issue for r in result.rewrites}):
        bodies[number] = apply_rewrites(bodies[number], [r for r in result.rewrites if r.issue == number])
    return result.films, bodies


def settled(films, bodies):
    """再跑一轮应当什么都不做。"""
    again = sync(films, [Issue(n, b) for n, b in bodies.items()], CATALOG, NOW)
    return again.actions == [] and again.rewrites == [] and not again.changed


def test_unticking_right_after_ticking_is_not_swallowed():
    bodies = {5: task_issue("2026-10-08", (1, True, False))}
    films, bodies = round_trip({}, bodies, user=lambda b: b.update({5: toggle(b[5], 1)}))
    assert list(films) == [1]                                   # 第一轮记下了勾
    films, bodies = round_trip(films, bodies)
    assert films == {} and lines_of(bodies[5]) == (Line(1, False, False),) and settled(films, bodies)


def test_reticking_right_after_unticking_is_not_swallowed():
    bodies = {5: task_issue("2026-10-08", (1, False, True))}
    films, bodies = round_trip({1: entry(1)}, bodies, user=lambda b: b.update({5: toggle(b[5], 1)}))
    assert films == {}
    films, bodies = round_trip(films, bodies)
    assert list(films) == [1] and lines_of(bodies[5]) == (Line(1, True, True),) and settled(films, bodies)


def test_another_line_changed_in_the_same_issue_is_not_overwritten():
    bodies = {5: task_issue("2026-10-08", (1, True, False), (3, False, False))}
    films, bodies = round_trip({}, bodies, user=lambda b: b.update({5: toggle(b[5], 3)}))
    assert list(films) == [1]
    films, bodies = round_trip(films, bodies)
    assert sorted(films) == [1, 3] and settled(films, bodies)


def test_a_rewrite_that_never_happened_is_repaired_by_the_next_run():
    bodies = {2: task_issue("2026-10-03", (1, True, False)), 5: task_issue("2026-10-08", (1, False, False))}
    first = sync({}, [Issue(n, b) for n, b in bodies.items()], CATALOG, NOW)       # 名单已提交，改写全部失败
    films, bodies = round_trip(first.films, bodies)
    assert films == first.films
    assert lines_of(bodies[2]) == (Line(1, True, True),) and lines_of(bodies[5]) == (Line(1, True, True),)
    assert settled(films, bodies)
