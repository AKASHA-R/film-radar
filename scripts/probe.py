"""前提探针：真实跑一遍 Cineplex 抓取和两种 Claude 调用。

只在 probe 工作流里用，不属于流水线。结果写到 out/probe/。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import anthropic
import requests

from film_radar import llm
from film_radar.cineplex import CineplexClient

OUT = Path("out/probe")
MODEL = "claude-opus-5-5"


def trim(value, limit: int = 300):
    """递归截断长字符串。搜索结果里的加密正文很长，存成测试数据用不着。"""
    if isinstance(value, str):
        return value[:limit]
    if isinstance(value, list):
        return [trim(v, limit) for v in value]
    if isinstance(value, dict):
        return {k: trim(v, limit) for k, v in value.items()}
    return value


def probe_cineplex() -> dict:
    client = CineplexClient(requests.Session())
    movies = client.movies()
    theatres = client.theatres(43.6532, -79.3832)
    days = client.bookable_dates(7130)
    film_ids = client.showtimes(7130, days[0]) if days else []
    playing = next(m for m in movies if m["isNowPlaying"] and not m["isEvent"])
    details = client.movie_details(playing["filmUrl"])
    return {
        "movies": len(movies),
        "theatres": len(theatres),
        "bookable_days": len(days),
        "films_on_first_day": len(film_ids),
        "detail_film": playing["name"],
        "synopsis_chars": len(details["synopsis"]),
    }


def probe_claude() -> dict:
    client = anthropic.Anthropic()
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}},
        "required": ["ok", "note"],
        "additionalProperties": False,
    }
    structured = llm.call(
        client, model=MODEL, system="按要求输出 JSON。",
        user="把 ok 设为 true，note 写“探针”。",
        effort="medium", max_tokens=16000, schema=schema,
    )
    research = llm.call(
        client, model=MODEL,
        system="用联网搜索查证后，用中文写三句话。提到评分时在括号里写出来源网址。",
        user="电影 Dune: Part Two（2024，导演 Denis Villeneuve）的影评口碑怎么样？",
        effort="high", max_tokens=16000,
        tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 3}],
    )
    fixture = {"stop_reason": research.stop_reason, "text": research.text, "blocks": trim(research.blocks)}
    (OUT / "research.json").write_text(json.dumps(fixture, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "structured_stop": structured.stop_reason,
        "structured_text": structured.text,
        "research_stop": research.stop_reason,
        "research_block_types": sorted({str(b.get("type")) for b in research.blocks}),
        "research_tokens": [research.input_tokens, research.output_tokens],
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict = {}
    failed = False
    for name, probe in (("cineplex", probe_cineplex), ("claude", probe_claude)):
        try:
            report[name] = {"ok": True, **probe()}
        except Exception as e:  # 探针要把每一项的结果都报出来，所以这里兜住所有异常
            report[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            failed = True
    text = json.dumps(report, ensure_ascii=False, indent=1)
    (OUT / "report.json").write_text(text, encoding="utf-8")
    print(text)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
