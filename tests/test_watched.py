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
