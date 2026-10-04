import json
from dataclasses import replace
from datetime import date

import pytest

from film_radar.candidates import MERGE_WINDOW_DAYS, base_title, build_candidates, film_brief, gta_theatres
from helpers import fixture_json

MOVIES = fixture_json("cineplex", "movies_v2.json")["items"]
_THEATRES = fixture_json("cineplex", "theatres.json")
ALL_THEATRES = _THEATRES["nearbyTheatres"] + _THEATRES["otherTheatres"]
RUN = date(2026, 10, 3)

YD = "Cineplex Cinemas Yonge-Dundas and VIP"
SB = "Scotiabank Theatre Toronto"
VA = "Cineplex Cinemas Varsity and VIP"

SHOWTIMES = [
    {"theatre_id": 7130, "theatre_name": YD, "date": "2026-10-04", "film_ids": [38459, 38401, 37885, 61994, 61995]},
    {"theatre_id": 7402, "theatre_name": SB, "date": "2026-10-05", "film_ids": [38459, 62194, 61890]},
    {"theatre_id": 7199, "theatre_name": VA, "date": "2026-10-13", "film_ids": [32584]},
]


def clone(film_id: int, **changes) -> dict:
    """复制一条真实记录并改个别字段。"""
    original = next(m for m in MOVIES if m["id"] == film_id)
    copy = json.loads(json.dumps(original))
    copy.update(changes)
    return copy


def show(film_id: int, day: str, theatre: str = VA, theatre_id: int = 7199) -> dict:
    return {"theatre_id": theatre_id, "theatre_name": theatre, "date": day, "film_ids": [film_id]}


def by_id(candidates):
    return {c["film_id"]: c for c in candidates}


@pytest.fixture
def built(settings):
    return build_candidates(MOVIES, SHOWTIMES, RUN, settings)


# ---- 片名与影院 ----

@pytest.mark.parametrize("name, expected", [
    ("Digger", "Digger"),
    ("Digger (Dubbed in Spanish)", "Digger"),
    ("Ninja Scroll 4K (Japanese w.e.s.t.)", "Ninja Scroll 4K"),
    ("All Wishes Come True! (Mandarin w/Chinese and e.s.t.)", "All Wishes Come True!"),
    ("V (Cantonese w/Chinese and e.s.t.)", "V"),
    ("Back To The Future: 40th Anniversary", "Back To The Future: 40th Anniversary"),
    ("(Untitled)", "(Untitled)"),
])
def test_base_title(name, expected):
    assert base_title(name) == expected


def test_gta_radius_uses_distance_from_api():
    inside = gta_theatres(ALL_THEATRES, 40)
    names = {t["theatreName"] for t in inside}
    assert len(inside) == 22
    assert "Cineplex Odeon Ajax Cinemas" in names        # 37.8 公里
    assert "Cineplex Odeon Aurora Cinemas" not in names  # 40002.2 米，刚好在外
    assert len(gta_theatres(ALL_THEATRES, 41)) == 23


# ---- 活动过滤 ----

def test_non_film_events_are_filtered_and_recorded(built):
    candidates, filtered, _ = built
    assert {f["film_id"] for f in filtered} == {61729, 61851, 61903, 61929, 62088}
    golden_boy = next(f for f in filtered if f["film_id"] == 61929)
    assert golden_boy["name"] == "Golden Boy - National Theatre Live"
    assert golden_boy["categories"] == ["Stage", "Stage Performance"]
    assert not {61729, 61851, 61903, 61929, 62088} & set(by_id(candidates))


def test_film_events_are_kept(built):
    candidates = by_id(built[0])
    assert 61994 in candidates   # Ninja Scroll 4K：Anime，活动场
    assert 62181 in candidates   # Fresh Meat：Horror，活动场
    assert candidates[62181]["is_event"] is True


def test_event_with_unknown_category_passes_through(settings):
    novel = clone(61729, id=900003, name="Brand New Format Night", filmUrl="brand-new-format",
                  filmCategories=["Event", "Immersive Screening"], releaseDate="2026-10-10T00:00:00",
                  isNowPlaying=False, isComingSoon=True)
    candidates, filtered, _ = build_candidates(MOVIES + [novel], SHOWTIMES, RUN, settings)
    assert 900003 in by_id(candidates)
    assert 900003 not in {f["film_id"] for f in filtered}


def test_non_event_with_blocked_category_is_untouched(built):
    thaapi = by_id(built[0])[62106]   # 类别含 Sport，但不是活动
    assert thaapi["is_event"] is False
    assert "Sport" in thaapi["film_categories"]


def test_filtered_event_with_showtimes_is_neither_candidate_nor_orphan(settings):
    showtimes = SHOWTIMES + [show(61729, "2026-10-04")]   # 歌剧在 GTA 有场
    candidates, filtered, orphans = build_candidates(MOVIES, showtimes, RUN, settings)
    assert 61729 not in by_id(candidates)
    assert 61729 in {f["film_id"] for f in filtered}
    assert orphans == []


# ---- 多版本合并 ----

def test_dubbed_version_merges_into_primary(built):
    candidates = by_id(built[0])
    assert 62194 not in candidates
    digger = candidates[38459]
    assert digger["title"] == "Digger"
    assert digger["versions"] == [
        {"film_id": 38459, "name": "Digger", "language": "English", "subtitle": ""},
        {"film_id": 62194, "name": "Digger (Dubbed in Spanish)", "language": "Spanish (Dubbed)", "subtitle": ""},
    ]
    assert digger["gta_theatres"] == [YD, SB]
    assert digger["gta_dates"] == ["2026-10-04", "2026-10-05"]
    assert digger["status"] == "now_playing"


def test_event_versions_merge_and_keep_both_languages(built):
    ninja = by_id(built[0])[61994]
    assert 61995 not in by_id(built[0])
    assert ninja["title"] == "Ninja Scroll 4K"
    assert [v["language"] for v in ninja["versions"]] == ["English", "Japanese"]
    assert ninja["versions"][1]["subtitle"] == "English"
    assert ninja["is_event"] is True
    assert ninja["status"] == "coming_soon"
    assert ninja["gta_theatres"] == [YD]
    assert ninja["gta_dates"] == ["2026-10-04"]
    assert ninja["weeks_in_release"] is None
    assert ninja["hurry"] is False


def test_single_version_with_parenthetical_is_its_own_primary(built):
    wishes = by_id(built[0])[61890]
    assert wishes["title"] == "All Wishes Come True!"
    assert len(wishes["versions"]) == 1
    assert wishes["versions"][0]["language"] == "Chinese"


def test_same_title_released_far_apart_is_not_merged(settings):
    old = clone(38459, id=900002, filmUrl="digger-1990", releaseDate="2026-01-10T00:00:00")
    showtimes = SHOWTIMES + [show(900002, "2026-10-06")]
    candidates = by_id(build_candidates(MOVIES + [old], showtimes, RUN, settings)[0])
    assert len(candidates[900002]["versions"]) == 1
    assert [v["film_id"] for v in candidates[38459]["versions"]] == [38459, 62194]
    assert MERGE_WINDOW_DAYS == 60


# ---- 入选条件 ----

def test_candidate_set_for_fixture_run(built):
    assert sorted(by_id(built[0])) == [
        32584, 37885, 38401, 38459, 61890, 61994, 62103, 62106, 62154, 62163, 62181,
    ]


def test_candidates_are_sorted_by_film_id(built):
    ids = [c["film_id"] for c in built[0]]
    assert ids == sorted(ids)


def test_now_playing_without_gta_showtimes_is_excluded(built):
    assert 61548 not in by_id(built[0])   # Heart of the Beast：在映，但这批排片里没有


def test_coming_soon_without_showtimes_has_empty_theatres(built):
    film = by_id(built[0])[62163]         # 10-09 上映，排片未出
    assert film["status"] == "coming_soon"
    assert film["gta_theatres"] == []
    assert film["gta_dates"] == []


def test_coming_soon_window_includes_day_14_and_excludes_day_15(settings):
    movies = MOVIES + [
        clone(62154, id=900014, name="Edge Fourteen", filmUrl="edge-14", releaseDate="2026-10-17T00:00:00"),
        clone(62154, id=900015, name="Edge Fifteen", filmUrl="edge-15", releaseDate="2026-10-18T00:00:00"),
        clone(62154, id=900000, name="Edge Today", filmUrl="edge-0", releaseDate="2026-10-03T00:00:00"),
    ]
    ids = set(by_id(build_candidates(movies, [], RUN, settings)[0]))
    assert 900014 in ids
    assert 900015 not in ids
    assert 900000 not in ids


def test_far_release_with_gta_showtimes_is_a_coming_soon_candidate(settings):
    showtimes = SHOWTIMES + [show(60710, "2026-10-10")]   # Godzilla 11-06 上映，10-10 有提前场
    godzilla = by_id(build_candidates(MOVIES, showtimes, RUN, settings)[0])[60710]
    assert godzilla["status"] == "coming_soon"
    assert godzilla["gta_dates"] == ["2026-10-10"]
    assert godzilla["weeks_in_release"] is None


def test_sporadic_screening_on_day_10_is_caught(built):
    bttf = by_id(built[0])[32584]         # 2020 年上映的老片，只在第 10 天有一场
    assert bttf["gta_dates"] == ["2026-10-13"]
    assert bttf["gta_theatres"] == [VA]


def test_showtime_window_is_half_open(settings):
    def ids(day):
        return set(by_id(build_candidates(MOVIES, [show(61548, day)], RUN, settings)[0]))

    assert 61548 in ids("2026-10-03")       # 运行当天
    assert 61548 in ids("2026-10-16")       # 第 13 天
    assert 61548 not in ids("2026-10-17")   # 第 14 天，窗口外
    assert 61548 not in ids("2026-10-02")   # 运行日之前


def test_showtime_window_follows_settings(settings):
    wider = replace(settings, showtime_days=21)
    ids = set(by_id(build_candidates(MOVIES, [show(61548, "2026-10-17")], RUN, wider)[0]))
    assert 61548 in ids


# ---- 程序计算的事实字段 ----

def test_weeks_in_release_and_hurry(built):
    candidates = by_id(built[0])
    assert candidates[38401]["weeks_in_release"] == 1    # Verity 10-02 上映
    assert candidates[38401]["hurry"] is False
    assert candidates[37885]["weeks_in_release"] == 3    # Resident Evil 09-18 上映
    assert candidates[37885]["hurry"] is True            # 第 3 周且只有 1 家
    assert candidates[61890]["weeks_in_release"] == 8
    assert candidates[61890]["hurry"] is True


def test_hurry_needs_few_theatres(settings):
    showtimes = [
        show(37885, "2026-10-04", YD, 7130),
        show(37885, "2026-10-04", SB, 7402),
        show(37885, "2026-10-04", VA, 7199),
    ]
    film = by_id(build_candidates(MOVIES, showtimes, RUN, settings)[0])[37885]
    assert film["gta_theatres"] == [VA, YD, SB]   # 按影院名排序
    assert film["hurry"] is False


def test_weeks_in_release_is_at_least_one(settings):
    future = clone(38401, id=900005, name="Flag Mismatch", filmUrl="flag-mismatch",
                   releaseDate="2026-10-20T00:00:00")   # 标着在映，上映日却在未来
    film = by_id(build_candidates(MOVIES + [future], [show(900005, "2026-10-04")], RUN, settings)[0])[900005]
    assert film["status"] == "now_playing"
    assert film["weeks_in_release"] == 1


def test_ontario_rating(built):
    candidates = by_id(built[0])
    assert candidates[38459]["rating_on"]["rating"] == "14A"
    assert isinstance(candidates[38459]["rating_on"]["warnings"], list)
    assert candidates[61994]["rating_on"] is None


def test_missing_poster_becomes_empty_string(settings):
    bare = clone(38401, id=900004, name="No Poster", filmUrl="no-poster", mediumPosterImageUrl=None)
    film = by_id(build_candidates(MOVIES + [bare], [show(900004, "2026-10-04")], RUN, settings)[0])[900004]
    assert film["poster_url"] == ""


def test_details_start_empty(built):
    film = built[0][0]
    assert (film["synopsis"], film["director"], film["starring"]) == ("", "", "")
    assert film["details_missing"] is True
    assert film["detail_url"] == f"https://www.cineplex.com/movie/{film['film_url']}"


# ---- 排片里的陌生 id ----

def test_showtime_ids_missing_from_movie_list_are_reported(settings):
    showtimes = SHOWTIMES + [show(999999, "2026-10-04"), show(999998, "2026-10-05"), show(999999, "2026-10-06")]
    _, _, orphans = build_candidates(MOVIES, showtimes, RUN, settings)
    assert orphans == [999998, 999999]


def test_no_orphans_for_fixture_run(built):
    assert built[2] == []


# ---- 给模型看的字段 ----

def test_film_brief_exposes_all_versions_and_no_theatres(built):
    brief = film_brief(by_id(built[0])[61994])
    assert brief["versions"] == [
        {"language": "English", "subtitle": ""},
        {"language": "Japanese", "subtitle": "English"},
    ]
    assert set(brief) == {
        "film_id", "title", "versions", "status", "release_date", "is_event", "runtime",
        "genres", "film_categories", "distributor", "director", "starring", "synopsis",
    }
    json.dumps(brief)


# ---- 老片重映、限定放映、变体排片（终审补的缺口）----

def test_classic_rerelease_has_no_meaningful_week_count(settings):
    """Cineplex 在重映时沿用原来的上映日期：2020 年的老片会被算成"在映第 326 周"。"""
    bttf = by_id(build_candidates(MOVIES, SHOWTIMES, RUN, settings)[0])[32584]
    assert bttf["status"] == "now_playing"
    assert bttf["weeks_in_release"] is None
    assert bttf["hurry"] is False


def test_event_film_is_never_marked_hurry(settings):
    """spec 第 6 节：按周数算的 hurry 规则对限定放映不适用。"""
    event = clone(37885, id=900006, name="One Night Only", filmUrl="one-night-only", isEvent=True)
    film = by_id(build_candidates(MOVIES + [event], [show(900006, "2026-10-04")], RUN, settings)[0])[900006]
    assert film["is_event"] is True
    assert film["weeks_in_release"] == 3          # 第 3 周且只有 1 家影院，换成非活动片就是 hurry
    assert film["hurry"] is False


def test_variant_only_showtimes_still_make_the_film_a_candidate(settings):
    """主条目一场都没有、只有配音版有排片：这部片也不能从页面上消失。"""
    showtimes = [show(62194, "2026-10-07", VA, 7199)]     # 只有 Digger (Dubbed in Spanish) 有场
    digger = by_id(build_candidates(MOVIES, showtimes, RUN, settings)[0])[38459]
    assert digger["gta_theatres"] == [VA]
    assert digger["gta_dates"] == ["2026-10-07"]
