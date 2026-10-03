import json
from dataclasses import replace
from datetime import date

import pytest

from film_radar.assemble import OUTCOMES, AssembleError, assemble
from helpers import (
    USAGE, broken, build_edition, make_candidate, make_verdict, ok_review, recommended, skipped,
)


def films(edition):
    return {f["film_id"]: f for f in edition["films"]}


# ---- 去向 ----

def test_each_path_lands_in_the_right_outcome(settings):
    edition = build_edition(settings, [
        recommended(1, "Must One", tier="must"),
        recommended(2, "Ok Two", tier="ok", one_liner="还行。"),
        recommended(3, "Skip Three", tier="skip", skip_reason="其实是砍杀片"),
        skipped(4, "Triage Four", reason="儿童动画"),
        broken(5, "Broken Five", error="联网搜索没有返回任何结果"),
    ])
    f = films(edition)
    assert [f[i]["outcome"] for i in (1, 2, 3, 4, 5)] == ["must", "ok", "skip", "skip", "review_failed"]
    assert f[2]["outcome_reason"] == "还行。"
    assert f[3]["outcome_reason"] == "其实是砍杀片"
    assert f[3]["card"]["tier"] == "skip"
    assert f[4]["outcome_reason"] == "儿童动画"
    assert f[4]["card"] is None
    assert f[5]["outcome_reason"] == "联网搜索没有返回任何结果"
    assert f[5]["review_error"] == "联网搜索没有返回任何结果"
    assert f[5]["card"] is None
    assert edition["counts"] == {"must": 1, "ok": 1, "skip": 2, "review_failed": 1}
    assert OUTCOMES == ("must", "ok", "skip", "review_failed")


def test_film_keeps_candidate_fields_and_verdict(settings):
    edition = build_edition(settings, [recommended(1, "Must One")])
    film = edition["films"][0]
    assert film["title"] == "Must One"
    assert film["gta_theatres"] == ["Scotiabank Theatre Toronto"]
    assert film["verdict"]["reason"] == "粗筛理由"
    assert film["flags"] == []


def test_no_must_is_a_valid_edition(settings):
    edition = build_edition(settings, [skipped(1, "A"), skipped(2, "B")])
    assert edition["counts"] == {"must": 0, "ok": 0, "skip": 2, "review_failed": 0}


# ---- 规则 1：无来源不得重点推荐 ----

def test_must_without_sources_is_demoted(settings):
    edition = build_edition(settings, [recommended(1, "No Source", tier="must", sources=[], evidence="none")])
    film = edition["films"][0]
    assert film["outcome"] == "ok"
    assert film["flags"] == ["无有效来源，不能列入重点推荐"]


def test_ok_without_sources_stays_ok_and_unflagged(settings):
    edition = build_edition(settings, [recommended(1, "No Source", tier="ok", sources=[])])
    assert edition["films"][0]["outcome"] == "ok"
    assert edition["films"][0]["flags"] == []


# ---- 规则 2：口味之外的名额 ----

def test_outside_cap_keeps_the_strongest(settings):
    edition = build_edition(settings, [
        recommended(1, "Outside Ok Weak", tier="ok", strength=2, category="outside"),
        recommended(2, "Outside Must", tier="must", strength=3, category="outside"),
        recommended(3, "Outside Ok Strong", tier="ok", strength=5, category="outside"),
        recommended(4, "Inside", tier="ok", strength=1, category="horror"),
    ])
    f = films(edition)
    assert f[2]["outcome"] == "must"
    assert f[3]["outcome"] == "ok"
    assert f[1]["outcome"] == "skip"
    assert f[1]["outcome_reason"] == "口味之外名额已满"
    assert f[1]["flags"] == ["口味之外名额已满"]
    assert f[4]["outcome"] == "ok"


def test_outside_cap_follows_settings(settings):
    entries = [recommended(i, f"Outside {i}", tier="ok", category="outside") for i in (1, 2, 3)]
    edition = build_edition(replace(settings, outside_cap=0), entries)
    assert edition["counts"]["skip"] == 3


# ---- 规则 3：重点推荐的名额 ----

def test_must_cap_demotes_the_weakest(settings):
    entries = [recommended(i, f"Must {i}", tier="must", strength=5) for i in range(1, 7)]
    entries.append(recommended(7, "Must Weak", tier="must", strength=1))
    f = films(build_edition(settings, entries))
    assert sum(1 for x in f.values() if x["outcome"] == "must") == 6
    assert f[7]["outcome"] == "ok"
    assert f[7]["flags"] == ["超出重点推荐名额"]


def test_must_cap_tie_breaks_on_newer_release(settings):
    entries = [
        recommended(1, "Older", {"release_date": "2026-09-01"}, tier="must", strength=4),
        recommended(2, "Newer", {"release_date": "2026-10-02"}, tier="must", strength=4),
    ]
    f = films(build_edition(replace(settings, must_cap=1), entries))
    assert f[2]["outcome"] == "must"
    assert f[1]["outcome"] == "ok"


def test_demoted_unsourced_must_does_not_take_a_must_slot(settings):
    entries = [
        recommended(1, "Strong But Unsourced", tier="must", strength=5, sources=[]),
        recommended(2, "Sourced", tier="must", strength=1),
    ]
    f = films(build_edition(replace(settings, must_cap=1), entries))
    assert f[1]["outcome"] == "ok"
    assert f[2]["outcome"] == "must"


# ---- 规则 4：新旧标记 ----

def test_seen_before_is_none_without_previous_edition(settings):
    edition = build_edition(settings, [recommended(1, "A")])
    assert edition["films"][0]["seen_before"] is None


def test_seen_before_compares_with_previous_recommendations(settings):
    previous = build_edition(settings, [
        recommended(1, "Was Must", tier="must"),
        recommended(2, "Was Ok", tier="ok"),
        skipped(3, "Was Skipped"),
    ], run_date=date(2026, 9, 24))
    edition = build_edition(settings, [
        recommended(1, "Was Must"), recommended(2, "Was Ok"),
        recommended(3, "Was Skipped"), recommended(4, "Brand New"),
    ], previous=previous)
    f = films(edition)
    assert [f[i]["seen_before"] for i in (1, 2, 3, 4)] == [True, True, False, False]


# ---- 当期数据的其余字段 ----

def test_edition_metadata(settings):
    events = [{"film_id": 61729, "name": "Così fan tutte", "categories": ["Opera"]}]
    edition = build_edition(settings, [recommended(1, "A")], filtered_events=events, orphan_ids=[999999])
    assert edition["edition_id"] == "2026-10-08"
    assert edition["next_edition_date"] == "2026-10-22"
    assert edition["generated_at"] == "2026-10-08T07:05:00-04:00"
    assert edition["filtered_events"] == events
    assert edition["orphan_ids"] == [999999]
    assert edition["usage"] == USAGE
    assert edition["settings"] == {
        "radius_km": 40, "showtime_days": 14, "coming_soon_days": 14,
        "shortlist_cap": 15, "must_cap": 6, "outside_cap": 2, "stale_after_days": 16,
    }


def test_edition_is_json_serialisable(settings):
    edition = build_edition(settings, [recommended(1, "A"), skipped(2, "B"), broken(3, "C")])
    assert json.loads(json.dumps(edition, ensure_ascii=False))["counts"]["must"] == 1


def test_review_usage_objects_are_not_copied_into_the_edition(settings):
    candidate, verdict, review = recommended(1, "A")
    review["usage"] = [object()]
    edition = build_edition(settings, [(candidate, verdict, review)])
    json.dumps(edition, ensure_ascii=False)


def test_does_not_mutate_inputs(settings):
    candidate, verdict, review = recommended(1, "No Source", tier="must", sources=[])
    build_edition(settings, [(candidate, verdict, review)])
    assert "outcome" not in candidate
    assert review["card"]["tier"] == "must"


# ---- 核对 ----

def kwargs(settings, **overrides):
    base = dict(
        candidates=[make_candidate(1), make_candidate(2)],
        verdicts=[make_verdict(1), make_verdict(2, keep=False)],
        reviews=[ok_review(1)],
        previous=None, filtered_events=[], orphan_ids=[], usage=dict(USAGE),
        run_date=date(2026, 10, 8), generated_at="2026-10-08T07:05:00-04:00", settings=settings,
    )
    base.update(overrides)
    return base


def test_baseline_assembles(settings):
    assert assemble(**kwargs(settings))["counts"] == {"must": 1, "ok": 0, "skip": 1, "review_failed": 0}


def test_missing_verdict_fails(settings):
    with pytest.raises(AssembleError, match="判定与候选对不上"):
        assemble(**kwargs(settings, verdicts=[make_verdict(1)]))


def test_extra_verdict_fails(settings):
    extra = [make_verdict(1), make_verdict(2, keep=False), make_verdict(3, keep=False)]
    with pytest.raises(AssembleError, match="判定与候选对不上"):
        assemble(**kwargs(settings, verdicts=extra))


def test_duplicate_candidate_fails(settings):
    with pytest.raises(AssembleError, match="重复"):
        assemble(**kwargs(settings, candidates=[make_candidate(1), make_candidate(1)]))


def test_shortlisted_film_without_review_fails(settings):
    with pytest.raises(AssembleError, match="没有精评结果"):
        assemble(**kwargs(settings, reviews=[]))


def test_unknown_tier_breaks_the_count_check(settings):
    with pytest.raises(AssembleError, match="总数核对失败"):
        assemble(**kwargs(settings, reviews=[ok_review(1, tier="great")]))
