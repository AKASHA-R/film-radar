"""命令行入口：双周门控、串联流水线、写产物。

失败时只写 out/failure.txt 并以退出码 1 结束；当期数据文件和 site/ 都不动，
这样已发布的页面在失败时保持原样。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections import Counter
from datetime import date, datetime, timedelta
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from . import llm
from .assemble import AssembleError, assemble
from .candidates import build_candidates, gta_theatres
from .cineplex import CineplexClient, CineplexError
from .llm import LLMError
from .render import cost_text, issue_body, issue_title, render_site
from .review import review_film
from .settings import Settings, SettingsError, load_settings
from .triage import TriageError, triage


class PipelineError(Exception):
    pass


class ReviewError(Exception):
    """入围片里超过一半精评失败。单独一类，失败 Issue 才能写成「联网精评」而不是「数据核对」。"""


STAGES = {
    SettingsError: "读取配置",
    CineplexError: "Cineplex 抓取",
    PipelineError: "数据核对",
    ReviewError: "联网精评",
    TriageError: "粗筛",
    LLMError: "Claude 调用",
    AssembleError: "汇总",
}
UNEXPECTED_STAGE = "未预期的错误"


def should_run(run_date: date, anchor: date, manual: bool) -> bool:
    """按距离锚点的整周数判断奇偶，跨年不会错位。"""
    return manual or ((run_date - anchor).days // 7) % 2 == 0


def collect(client, settings: Settings, run_date: date):
    movies = client.movies()
    theatres = gta_theatres(client.theatres(settings.home_lat, settings.home_lon), settings.radius_km)
    window = {run_date + timedelta(days=n) for n in range(settings.showtime_days)}
    showtimes = []
    for theatre in theatres:
        for day in sorted(window & set(client.bookable_dates(theatre["theatreId"]))):
            film_ids = client.showtimes(theatre["theatreId"], day)
            if film_ids:
                showtimes.append({
                    "theatre_id": theatre["theatreId"],
                    "theatre_name": theatre["theatreName"],
                    "date": day.isoformat(),
                    "film_ids": film_ids,
                })
    return movies, theatres, showtimes


def check_sanity(movies, theatres, showtimes, candidates) -> None:
    """这些"0"更可能是接口变了，而不是真的没片。一次报全。"""
    problems = []
    if len(movies) < 20:
        problems.append(f"片单只有 {len(movies)} 部")
    if not any(m["isNowPlaying"] for m in movies):
        problems.append("在映片为 0")
    if not theatres:
        problems.append("GTA 影院为 0")
    if not showtimes:
        problems.append("GTA 排片为 0")
    if not candidates:
        problems.append("候选为 0")
    if problems:
        raise PipelineError("数据可疑：" + "；".join(problems))


def attach_details(client, candidates: list[dict]) -> None:
    failed = 0
    for candidate in candidates:
        try:
            details = client.movie_details(candidate["film_url"])
        except CineplexError:
            failed += 1
            continue
        candidate.update(details)
        candidate["details_missing"] = False
    if failed * 2 > len(candidates):
        raise PipelineError(f"{len(candidates)} 部候选里有 {failed} 部详情页失败，超过一半")


def summarize_usage(triage_results, review_results, searches: int, settings: Settings) -> dict:
    """粗筛和精评用的不是同一个模型，各按各的单价算。"""
    def cost(results, price_input: float, price_output: float) -> float:
        return (
            sum(r.input_tokens for r in results) / 1_000_000 * price_input
            + sum(r.output_tokens for r in results) / 1_000_000 * price_output
        )

    results = list(triage_results) + list(review_results)
    total = (
        cost(triage_results, settings.triage_price_input_per_mtok, settings.triage_price_output_per_mtok)
        + cost(review_results, settings.price_input_per_mtok, settings.price_output_per_mtok)
    )
    search_cost = searches * settings.search_price_per_search
    return {
        "calls": len(results),
        "input_tokens": sum(r.input_tokens for r in results),
        "output_tokens": sum(r.output_tokens for r in results),
        "searches": searches,
        "estimated_token_cost_usd": round(total, 4),
        "estimated_search_cost_usd": round(search_cost, 4),
        "estimated_cost_usd": round(total + search_cost, 4),
    }


def run_pipeline(*, client, caller, settings: Settings, taste: str, run_date: date,
                 previous: dict | None, generated_at: str, triage_caller=None) -> dict:
    """caller 做精评；triage_caller 做粗筛，不给就和精评共用同一个。"""
    triage_caller = triage_caller or caller
    movies, theatres, showtimes = collect(client, settings, run_date)
    candidates, filtered_events, orphan_ids = build_candidates(movies, showtimes, run_date, settings)
    check_sanity(movies, theatres, showtimes, candidates)
    attach_details(client, candidates)

    verdicts, triage_results = triage(triage_caller, taste, candidates, settings.shortlist_cap)
    by_id = {c["film_id"]: c for c in candidates}
    reviews = [
        review_film(caller, taste, by_id[v["film_id"]], v, settings.search_max_uses)
        for v in verdicts if v["keep"]
    ]
    failed = sum(1 for r in reviews if not r["ok"])
    if failed * 2 > len(reviews):
        reasons = Counter(r["error"] for r in reviews if not r["ok"]).most_common(3)
        detail = "；".join(f"{reason} ×{n}" for reason, n in reasons)
        raise ReviewError(f"{len(reviews)} 部入围片里有 {failed} 部精评失败，超过一半，本期不发布。原因：{detail}")

    review_results = [result for r in reviews for result in r["usage"]]
    usage = summarize_usage(triage_results, review_results, sum(r["searches"] for r in reviews), settings)
    return assemble(
        candidates=candidates, verdicts=verdicts, reviews=reviews, previous=previous,
        filtered_events=filtered_events, orphan_ids=orphan_ids, usage=usage,
        run_date=run_date, generated_at=generated_at, settings=settings,
    )


def load_editions(directory: Path) -> list[dict]:
    if not directory.is_dir():
        return []
    editions = [json.loads(p.read_text(encoding="utf-8")) for p in directory.glob("*.json")]
    return sorted(editions, key=lambda e: e["edition_id"])


def previous_edition(editions: list[dict], run_date: date) -> dict | None:
    """早于运行日的最近一期。当天已有的那一期不算，否则同日重跑会把每部片都标成"上期已推荐"。"""
    earlier = [e for e in editions if e["edition_id"] < run_date.isoformat()]
    return earlier[-1] if earlier else None


def build_clients(settings: Settings):
    import anthropic
    import requests

    client = CineplexClient(requests.Session())
    anthropic_client = anthropic.Anthropic()
    caller = partial(llm.call, anthropic_client, model=settings.model)
    triage_caller = partial(llm.call, anthropic_client, model=settings.triage_model)
    return client, caller, triage_caller


def _set_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def _write_summary(edition: dict, number: int) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    counts, usage = edition["counts"], edition["usage"]
    lines = [
        f"## 第 {number} 期 {edition['edition_id']}",
        "",
        f"- 重点推荐 {counts['must']}，可以看 {counts['ok']}，跳过 {counts['skip']}，未能评估 {counts['review_failed']}",
        f"- 模型调用 {usage['calls']} 次，输入 {usage['input_tokens']:,} / 输出 {usage['output_tokens']:,} token，"
        f"联网搜索 {usage['searches']} 次",
        f"- {cost_text(usage)}",
        "",
    ]
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _run(root: Path, manual: bool, date_arg: str | None) -> int:
    settings = load_settings(root / "config" / "settings.toml")
    now = datetime.now(ZoneInfo(settings.timezone))
    run_date = date.fromisoformat(date_arg) if date_arg else now.date()
    if not should_run(run_date, settings.anchor_date, manual):
        print(f"{run_date} 是跳过周，不生成新一期。")
        _set_output("skipped", "true")
        return 0

    taste = (root / "config" / "taste_profile.md").read_text(encoding="utf-8")
    editions_dir = root / "data" / "editions"
    previous = previous_edition(load_editions(editions_dir), run_date)
    client, caller, triage_caller = build_clients(settings)
    edition = run_pipeline(
        client=client, caller=caller, triage_caller=triage_caller, settings=settings, taste=taste, run_date=run_date,
        previous=previous, generated_at=now.isoformat(timespec="seconds"),
    )

    editions_dir.mkdir(parents=True, exist_ok=True)
    (editions_dir / f"{edition['edition_id']}.json").write_text(
        json.dumps(edition, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    editions = load_editions(editions_dir)
    render_site(editions, root / "site")
    number = [e["edition_id"] for e in editions].index(edition["edition_id"]) + 1

    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "issue_title.txt").write_text(issue_title(edition, number), encoding="utf-8")
    (out / "issue_body.md").write_text(issue_body(edition, number, settings.page_url), encoding="utf-8")
    _set_output("skipped", "false")
    _set_output("edition_id", edition["edition_id"])
    _write_summary(edition, number)
    print(f"第 {number} 期已生成：{edition['counts']}")
    return 0


def _build_site(root: Path) -> int:
    render_site(load_editions(root / "data" / "editions"), root / "site")
    return 0


def _fail(root: Path, stage: str, reason: str) -> int:
    message = f"失败环节：{stage}\n原因：{reason}"
    print(message, file=sys.stderr)
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "failure.txt").write_text(message + "\n", encoding="utf-8")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="film-radar")
    parser.add_argument("--root", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--manual", action="store_true")
    run.add_argument("--date")
    commands.add_parser("build-site")
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        if args.command == "run":
            return _run(root, args.manual, args.date)
        return _build_site(root)
    except tuple(STAGES) as e:
        stage = next(label for kind, label in STAGES.items() if isinstance(e, kind))
        return _fail(root, stage, str(e))
    except Exception as e:  # 没列入 STAGES 的异常也要留下 failure.txt，工作流的失败 Issue 靠它写明环节
        traceback.print_exc()
        return _fail(root, UNEXPECTED_STAGE, f"{type(e).__name__}: {e}")


if __name__ == "__main__":
    sys.exit(main())
