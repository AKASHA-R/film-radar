"""精评的搜索额度对照：同一部片，用不同的搜索调用方式与提示词各跑一次精评，看额度是不是被浪费了。

背景：Sonnet 版的精评里，Ninja Scroll 4K 一个有效来源都没有，卡里自述「搜索工具调用次数超限」。
web_search_20260209 默认让模型在代码里批量调搜索，每个都计入 max_uses。这里 2×2 对照两个可能的修法：
  调用方式：默认（经代码执行）/ allowed_callers=["direct"]（直接调用）
  提示词：  原样 / 写明搜索预算并要求别在代码里批量调搜索
每次运行记下完整的时间线（每次搜索、结果、错误、代码执行的失败），不只是最后的卡片。
只在 research-compare 工作流里用，结果写到 out/research-compare/runs.json。
"""
from __future__ import annotations

import argparse
import json
import sys
from functools import partial
from pathlib import Path

from film_radar import llm, review
from film_radar.settings import load_settings

OUT = Path("out/research-compare")

BUDGET_RULES = """
- 你最多能用 {max_uses} 次联网搜索，用完就查不了了，所以每次搜索都要有用。每次只搜一个具体的查询，看到结果再决定下一个。
- 不要写代码批量或循环地调用搜索：代码里一次发出的多个搜索，每个都计入这 {max_uses} 次，额度会瞬间用光，什么都拿不到。
- 搜索的优先顺序：先查烂番茄和 Metacritic 的评分与影评概述，再查导演、制片背景和电影节获奖，最后才是中文片名。前两项查到就够了，不要为了凑齐所有项目把额度花光。
- 影院、场次、上映日期已经在 <film> 里给你了，不用搜。"""

VARIANTS = {
    "A 基线": {"allowed_callers": None, "budget_prompt": False},
    "B 写明预算": {"allowed_callers": None, "budget_prompt": True},
    "C 直接调用": {"allowed_callers": ["direct"], "budget_prompt": False},
    "D 直接调用+写明预算": {"allowed_callers": ["direct"], "budget_prompt": True},
}


def _short(value, limit: int = 110) -> str:
    return str(value).replace("\n", " ")[:limit]


def summarize(film: str, variant: str, result: dict) -> dict:
    """把一次精评压成一条记录：搜索次数、成功与出错的结果、代码执行的失败、时间线、最后的卡片。"""
    blocks = result["usage"][0].blocks if result["usage"] else []
    timeline: list[str] = []
    results_ok = results_error = code_failures = code_calls = 0
    error_codes: list[str] = []
    for block in blocks:
        kind = block.get("type")
        content = block.get("content")
        if kind == "server_tool_use":
            if block.get("name") == "web_search":
                timeline.append(f"搜索：{_short((block.get('input') or {}).get('query'))}")
            else:
                code_calls += 1
                timeline.append(f"代码：{_short((block.get('input') or {}).get('code'))}")
        elif kind == "web_search_tool_result":
            if isinstance(content, list):
                results_ok += 1
                timeline.append(f"  结果：{len(content)} 条")
            else:
                results_error += 1
                code = (content or {}).get("error_code") if isinstance(content, dict) else None
                error_codes.append(str(code))
                timeline.append(f"  结果：出错 {code}")
        elif kind and kind.endswith("_tool_result") and isinstance(content, dict):
            if content.get("return_code") not in (0, None):
                code_failures += 1
                timeline.append(f"  代码失败：{_short(content.get('stderr'), 90)}")
    card = result["card"] or {}
    return {
        "film": film, "variant": variant, "error": result["error"],
        "searches": review._count_searches(blocks), "results_ok": results_ok, "results_error": results_error,
        "error_codes": error_codes, "code_calls": code_calls, "code_failures": code_failures,
        "whitelisted_urls": len(review.collect_urls(blocks)),
        "input_tokens": sum(u.input_tokens for u in result["usage"]),
        "output_tokens": sum(u.output_tokens for u in result["usage"]),
        "tier": card.get("tier"), "strength": card.get("strength"), "evidence": card.get("evidence"),
        "card_sources": len(card.get("sources", [])), "card_scores": len(card.get("scores", [])),
        "reception": card.get("reception"), "timeline": timeline[:40],
    }


def run_variants(films: list[tuple[dict, dict]], variants: dict, taste: str, max_uses: int, make_caller) -> list[dict]:
    """films 是 (候选, 粗筛判定) 的列表。每次运行前改模块里的提示词和搜索调用方式，运行后一定恢复。"""
    caller = make_caller()
    original = (review.RESEARCH_SYSTEM, review.SEARCH_ALLOWED_CALLERS)
    records = []
    try:
        for candidate, verdict in films:
            for name, cfg in variants.items():
                review.SEARCH_ALLOWED_CALLERS = cfg["allowed_callers"]
                review.RESEARCH_SYSTEM = original[0] + (BUDGET_RULES.format(max_uses=max_uses) if cfg["budget_prompt"] else "")
                result = review.review_film(caller, taste, candidate, verdict, max_uses)
                records.append(summarize(candidate["title"], name, result))
    finally:
        review.RESEARCH_SYSTEM, review.SEARCH_ALLOWED_CALLERS = original
    return records


def main(argv: list[str] | None = None) -> int:
    import anthropic

    parser = argparse.ArgumentParser(prog="research_compare")
    parser.add_argument("--edition", required=True, help="用哪一期的候选与粗筛判定，如 2026-10-04")
    parser.add_argument("--films", required=True, help="逗号分隔的 film_id")
    parser.add_argument("--variants", default=",".join(VARIANTS), help="逗号分隔的配置名，默认全部四种")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    settings = load_settings(root / "config" / "settings.toml")
    taste = (root / "config" / "taste_profile.md").read_text(encoding="utf-8")
    edition = json.loads((root / "data" / "editions" / f"{args.edition}.json").read_text(encoding="utf-8"))
    wanted = [int(x) for x in args.films.split(",") if x.strip()]
    by_id = {f["film_id"]: f for f in edition["films"]}
    films = [(by_id[i], by_id[i]["verdict"]) for i in wanted]
    variants = {name: VARIANTS[name] for name in (n.strip() for n in args.variants.split(",")) if name}

    client = anthropic.Anthropic()
    records = run_variants(films, variants, taste, settings.search_max_uses,
                           lambda: partial(llm.call, client, model=settings.model))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "runs.json").write_text(json.dumps(
        {"edition": args.edition, "model": settings.model, "max_uses": settings.search_max_uses, "runs": records},
        ensure_ascii=False, indent=1), encoding="utf-8")
    for r in records:
        print(f"{r['film'][:28]:28} | {r['variant']:12} | 搜索 {r['searches']} 成功 {r['results_ok']} 出错 {r['results_error']} "
              f"代码失败 {r['code_failures']} | 来源 {r['card_sources']} 评分 {r['card_scores']} {r['evidence']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
