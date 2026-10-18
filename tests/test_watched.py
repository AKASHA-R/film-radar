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
