"""程序过滤：去非电影活动、合并同片多版本、按排片与上映日决定候选。

全部是纯函数。是否活动场一律以片单为准（排片接口里的 isEvent 不可信）。
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from .settings import Settings

MERGE_WINDOW_DAYS = 60
_TRAILING_PAREN = re.compile(r"\s*\([^()]*\)\s*$")


def base_title(name: str) -> str:
    stripped = _TRAILING_PAREN.sub("", name).strip()
    return stripped or name.strip()


def gta_theatres(theatres: list[dict], radius_km: float) -> list[dict]:
    limit = radius_km * 1000
    return [t for t in theatres if t["location"]["distanceToOriginInMeters"] <= limit]


def _release(movie: dict) -> date:
    return date.fromisoformat(movie["releaseDate"][:10])


def _split_events(movies: list[dict], non_film_categories) -> tuple[list[dict], list[dict]]:
    blocked = set(non_film_categories)
    kept, filtered = [], []
    for movie in movies:
        hit = sorted(blocked & set(movie["filmCategories"]))
        if movie["isEvent"] and hit:
            filtered.append({"film_id": movie["id"], "name": movie["name"], "categories": hit})
        else:
            kept.append(movie)
    return kept, filtered


def _primary_first(cluster: list[dict]) -> list[dict]:
    plain = [m for m in cluster if m["name"].strip() == base_title(m["name"])]
    primary = min(plain or cluster, key=lambda m: m["id"])
    rest = sorted((m for m in cluster if m is not primary), key=lambda m: m["id"])
    return [primary] + rest


def _cluster_versions(movies: list[dict]) -> list[list[dict]]:
    """同名且上映日相差不超过 MERGE_WINDOW_DAYS 的条目归为一部片。每组主条目在前。"""
    groups: dict[str, list[dict]] = {}
    for movie in movies:
        groups.setdefault(base_title(movie["name"]), []).append(movie)
    clusters = []
    for group in groups.values():
        group = sorted(group, key=lambda m: (_release(m), m["id"]))
        current = [group[0]]
        for movie in group[1:]:
            if (_release(movie) - _release(current[0])).days <= MERGE_WINDOW_DAYS:
                current.append(movie)
            else:
                clusters.append(current)
                current = [movie]
        clusters.append(current)
    return [_primary_first(c) for c in clusters]


def _candidate(cluster: list[dict], shows: list[tuple[str, str]], run_date: date) -> dict:
    primary = cluster[0]
    status = "coming_soon" if primary["isComingSoon"] else "now_playing"
    theatres = sorted({theatre for theatre, _ in shows})
    weeks = None
    hurry = False
    if status == "now_playing":
        weeks = max(1, (run_date - _release(primary)).days // 7 + 1)
        hurry = weeks >= 3 and len(theatres) <= 2
    rating = next((r for r in primary.get("ratings") or [] if r.get("provinceCode") == "ON"), None)
    return {
        "film_id": primary["id"],
        "title": base_title(primary["name"]),
        "film_url": primary["filmUrl"],
        "versions": [
            {
                "film_id": m["id"],
                "name": m["name"],
                "language": m.get("language") or "",
                "subtitle": m.get("subtitleLanguage") or "",
            }
            for m in cluster
        ],
        "status": status,
        "is_event": any(m["isEvent"] for m in cluster),
        "release_date": primary["releaseDate"][:10],
        "runtime": primary.get("runtimeInMinutes"),
        "genres": list(primary.get("genres") or []),
        "film_categories": list(primary["filmCategories"]),
        "distributor": primary.get("distributor") or "",
        "poster_url": primary.get("mediumPosterImageUrl") or "",
        "detail_url": f"https://www.cineplex.com/movie/{primary['filmUrl']}",
        "gta_theatres": theatres,
        "gta_dates": sorted({day for _, day in shows}),
        "weeks_in_release": weeks,
        "hurry": hurry,
        "rating_on": (
            {"rating": rating.get("rating") or "", "warnings": list(rating.get("warnings") or [])}
            if rating else None
        ),
        "synopsis": "",
        "director": "",
        "starring": "",
        "details_missing": True,
    }


def build_candidates(movies: list[dict], showtimes: list[dict], run_date: date,
                     settings: Settings) -> tuple[list[dict], list[dict], list[int]]:
    kept, filtered = _split_events(movies, settings.non_film_categories)

    window_end = run_date + timedelta(days=settings.showtime_days)
    shows_by_film: dict[int, list[tuple[str, str]]] = {}
    for entry in showtimes:
        if not run_date <= date.fromisoformat(entry["date"]) < window_end:
            continue
        for film_id in entry["film_ids"]:
            shows_by_film.setdefault(film_id, []).append((entry["theatre_name"], entry["date"]))

    known = {m["id"] for m in movies}
    orphans = sorted(set(shows_by_film) - known)

    candidates = []
    for cluster in _cluster_versions(kept):
        primary = cluster[0]
        shows = [s for m in cluster for s in shows_by_film.get(m["id"], [])]
        days_until_release = (_release(primary) - run_date).days
        opening_soon = primary["isComingSoon"] and 0 < days_until_release <= settings.coming_soon_days
        if shows or opening_soon:
            candidates.append(_candidate(cluster, shows, run_date))
    candidates.sort(key=lambda c: c["film_id"])
    return candidates, filtered, orphans


def film_brief(candidate: dict) -> dict:
    """给模型看的字段。排片、影院这些程序事实不给模型，免得它转述出错。"""
    return {
        "film_id": candidate["film_id"],
        "title": candidate["title"],
        "versions": [{"language": v["language"], "subtitle": v["subtitle"]} for v in candidate["versions"]],
        "status": candidate["status"],
        "release_date": candidate["release_date"],
        "is_event": candidate["is_event"],
        "runtime": candidate["runtime"],
        "genres": candidate["genres"],
        "film_categories": candidate["film_categories"],
        "distributor": candidate["distributor"],
        "director": candidate["director"],
        "starring": candidate["starring"],
        "synopsis": candidate["synopsis"],
    }
