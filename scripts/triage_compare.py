"""粗筛稳定性对照：同一份候选、同一份口味档案，每个模型各跑几次粗筛，记下每次入围的片和名次。

用来回答「两期之间同一部片一次入围一次落选，是模型不同，还是同一个模型自己每次也不一样」。
只调粗筛（每次一个调用），不联网搜索，不碰流水线的数据文件。只在 triage-compare 工作流里用，
结果写到 out/triage-compare/runs.json。
"""
from __future__ import annotations

import argparse
import json
import sys
from functools import partial
from pathlib import Path

from film_radar import llm
from film_radar.llm import LLMError
from film_radar.settings import load_settings
from film_radar.triage import TriageError, triage

OUT = Path("out/triage-compare")


def run_compare(candidates: list[dict], taste: str, cap: int, runs_per_model: dict[str, int], make_caller) -> list[dict]:
    """返回每次调用一条记录。一次失败只记下来，不能让整个对照作废：已经花掉的钱不能白花。"""
    titles = {c["film_id"]: c["title"] for c in candidates}
    records: list[dict] = []
    for model, runs in runs_per_model.items():
        caller = make_caller(model)
        for i in range(runs):
            record = {"model": model, "run": i, "kept": None, "error": None, "input_tokens": 0, "output_tokens": 0}
            try:
                verdicts, results = triage(caller, taste, candidates, cap)
            except (LLMError, TriageError) as e:
                record["error"] = str(e)
            else:
                record["kept"] = {titles[v["film_id"]]: v["rank"] for v in verdicts if v["keep"]}
                record["input_tokens"] = sum(r.input_tokens for r in results)
                record["output_tokens"] = sum(r.output_tokens for r in results)
            records.append(record)
    return records


def main(argv: list[str] | None = None) -> int:
    import anthropic

    parser = argparse.ArgumentParser(prog="triage_compare")
    parser.add_argument("--edition", required=True, help="用哪一期的候选，如 2026-10-04")
    parser.add_argument("--models", required=True, help="逗号分隔的模型 ID")
    parser.add_argument("--runs", type=int, default=3, help="每个模型跑几次")
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    settings = load_settings(root / "config" / "settings.toml")
    taste = (root / "config" / "taste_profile.md").read_text(encoding="utf-8")
    edition = json.loads((root / "data" / "editions" / f"{args.edition}.json").read_text(encoding="utf-8"))
    client = anthropic.Anthropic()
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    records = run_compare(
        edition["films"], taste, settings.shortlist_cap, {m: args.runs for m in models},
        lambda model: partial(llm.call, client, model=model),
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "runs.json").write_text(json.dumps(
        {"edition": args.edition, "cap": settings.shortlist_cap, "runs": records}, ensure_ascii=False, indent=1,
    ), encoding="utf-8")
    for r in records:
        status = f"入围 {len(r['kept'])} 部" if r["kept"] is not None else f"失败：{r['error']}"
        print(f"{r['model']} 第 {r['run'] + 1} 次：{status}（输入 {r['input_tokens']:,} / 输出 {r['output_tokens']:,}）")
    return 1 if any(r["error"] for r in records) else 0


if __name__ == "__main__":
    sys.exit(main())
