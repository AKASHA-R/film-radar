"""程序侧规则：名额、降档、新旧标记、总数核对。产出一期的完整数据。"""
from __future__ import annotations

import copy
from datetime import date, timedelta

from .settings import CADENCE_DAYS, Settings

OUTCOMES = ("must", "ok", "skip", "review_failed")


class AssembleError(Exception):
    pass


def _film(candidate: dict, verdict: dict, review: dict | None) -> dict:
    film = copy.deepcopy(candidate)
    film.update({
        "verdict": dict(verdict),
        "card": None,
        "review_error": None,
        "flags": [],
        "seen_before": None,
    })
    if not verdict["keep"]:
        film["outcome"] = "skip"
        film["outcome_reason"] = verdict["reason"]
    elif review is None:
        raise AssembleError(f"入围片 {candidate['film_id']}（{candidate['title']}）没有精评结果")
    elif not review["ok"]:
        film["outcome"] = "review_failed"
        film["outcome_reason"] = review["error"]
        film["review_error"] = review["error"]
    else:
        card = copy.deepcopy(review["card"])
        film["card"] = card
        if card["tier"] == "skip":
            film["outcome"] = "skip"
            film["outcome_reason"] = card["skip_reason"]
        else:
            film["outcome"] = card["tier"]
            film["outcome_reason"] = card["one_liner"]
    return film


def _demote_unsourced(films: list[dict]) -> None:
    for film in films:
        if film["outcome"] == "must" and not film["card"]["sources"]:
            film["outcome"] = "ok"
            film["flags"].append("无有效来源，不能列入重点推荐")


def _cap_outside(films: list[dict], cap: int) -> None:
    picks = [f for f in films if f["outcome"] in ("must", "ok") and f["card"]["category"] == "outside"]
    picks.sort(key=lambda f: (0 if f["outcome"] == "must" else 1, -f["card"]["strength"], f["film_id"]))
    for film in picks[cap:]:
        film["outcome"] = "skip"
        film["outcome_reason"] = "口味之外名额已满"
        film["flags"].append("口味之外名额已满")


def _cap_must(films: list[dict], cap: int) -> None:
    musts = [f for f in films if f["outcome"] == "must"]
    musts.sort(key=lambda f: (
        -f["card"]["strength"],
        -date.fromisoformat(f["release_date"]).toordinal(),
        f["film_id"],
    ))
    for film in musts[cap:]:
        film["outcome"] = "ok"
        film["flags"].append("超出重点推荐名额")


def _mark_seen(films: list[dict], previous: dict | None) -> None:
    if previous is None:
        return
    seen = {f["film_id"] for f in previous["films"] if f["outcome"] in ("must", "ok")}
    for film in films:
        film["seen_before"] = film["film_id"] in seen


def assemble(*, candidates: list[dict], verdicts: list[dict], reviews: list[dict],
             previous: dict | None, filtered_events: list[dict], orphan_ids: list[int],
             usage: dict, run_date: date, generated_at: str, settings: Settings) -> dict:
    ids = [c["film_id"] for c in candidates]
    if len(set(ids)) != len(ids):
        raise AssembleError("候选里有重复的 film_id")
    verdict_by = {v["film_id"]: v for v in verdicts}
    if len(verdicts) != len(ids) or set(verdict_by) != set(ids):
        raise AssembleError(f"判定与候选对不上：候选 {len(ids)} 部，判定 {len(verdicts)} 条")
    review_by = {r["film_id"]: r for r in reviews}

    films = [_film(c, verdict_by[c["film_id"]], review_by.get(c["film_id"])) for c in candidates]
    _demote_unsourced(films)
    _cap_outside(films, settings.outside_cap)
    _cap_must(films, settings.must_cap)
    _mark_seen(films, previous)

    counts = {outcome: sum(1 for f in films if f["outcome"] == outcome) for outcome in OUTCOMES}
    if sum(counts.values()) != len(candidates):
        raise AssembleError(
            f"总数核对失败：各去向合计 {sum(counts.values())} 部，候选 {len(candidates)} 部"
        )

    return {
        "edition_id": run_date.isoformat(),
        "generated_at": generated_at,
        "next_edition_date": (run_date + timedelta(days=CADENCE_DAYS)).isoformat(),
        "settings": {
            "radius_km": settings.radius_km,
            "showtime_days": settings.showtime_days,
            "coming_soon_days": settings.coming_soon_days,
            "shortlist_cap": settings.shortlist_cap,
            "must_cap": settings.must_cap,
            "outside_cap": settings.outside_cap,
            "stale_after_days": settings.stale_after_days,
        },
        "films": films,
        "filtered_events": list(filtered_events),
        "orphan_ids": list(orphan_ids),
        "usage": dict(usage),
        "counts": counts,
    }
