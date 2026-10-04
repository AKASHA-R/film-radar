import importlib.util

from film_radar import review
from helpers import FakeCaller, ROOT, llm_reply, make_candidate, make_card, make_verdict

SRC = "https://example.com/review"


def load_script():
    spec = importlib.util.spec_from_file_location("research_compare", ROOT / "scripts" / "research_compare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def research_reply(blocks, notes="笔记。"):
    return llm_reply(notes, blocks=blocks + [{"type": "text", "text": notes}])


GOOD = [
    {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "q1"}},
    {"type": "web_search_tool_result", "tool_use_id": "s1", "content": [
        {"type": "web_search_result", "url": SRC, "title": "t", "encrypted_content": "x", "page_age": None}]},
]
LIMIT = [
    {"type": "server_tool_use", "id": "s2", "name": "web_search", "input": {"query": "q2"}},
    {"type": "web_search_tool_result", "tool_use_id": "s2",
     "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}},
    {"type": "code_execution_tool_result", "tool_use_id": "s3",
     "content": {"type": "encrypted_code_execution_result", "stderr": "Server tool use limit exceeded", "return_code": 1}},
]


def film():
    return make_candidate(7, "Film Seven"), make_verdict(7, category="horror", reason="理由")


def test_each_variant_is_run_on_each_film_and_summarised():
    compare = load_script()
    caller = FakeCaller(
        research_reply(GOOD + LIMIT), llm_reply(make_card(sources=[{"title": "t", "url": SRC}])),
        research_reply(GOOD), llm_reply(make_card(sources=[{"title": "t", "url": SRC}])),
    )
    variants = {"base": {"allowed_callers": None, "budget_prompt": False},
                "direct": {"allowed_callers": ["direct"], "budget_prompt": True}}
    records = compare.run_variants([film()], variants, "口味", 5, lambda: caller)
    assert [(r["film"], r["variant"]) for r in records] == [("Film Seven", "base"), ("Film Seven", "direct")]
    base, direct = records
    assert (base["searches"], base["results_ok"], base["results_error"], base["code_failures"]) == (2, 1, 1, 1)
    assert base["error_codes"] == ["max_uses_exceeded"]
    assert base["whitelisted_urls"] == 1
    assert (direct["searches"], direct["results_error"], direct["code_failures"]) == (1, 0, 0)
    assert base["evidence"] == "ample" and base["card_sources"] == 1
    assert base["error"] is None


def test_variant_settings_reach_the_request_and_are_restored():
    compare = load_script()
    caller = FakeCaller(research_reply(GOOD), llm_reply(make_card(sources=[{"title": "t", "url": SRC}])))
    before = (review.RESEARCH_SYSTEM, review.SEARCH_ALLOWED_CALLERS)
    compare.run_variants([film()], {"v": {"allowed_callers": ["direct"], "budget_prompt": True}}, "口味", 5, lambda: caller)
    first = caller.calls[0]
    assert first["tools"][0]["allowed_callers"] == ["direct"]
    assert "最多" in first["system"] and "5 次" in first["system"] and first["system"].startswith(before[0])
    assert (review.RESEARCH_SYSTEM, review.SEARCH_ALLOWED_CALLERS) == before     # 不能把改动留给后面的测试和调用方


def test_a_failed_review_is_recorded_not_fatal():
    compare = load_script()
    caller = FakeCaller(llm_reply("", stop="max_tokens"))
    records = compare.run_variants([film()], {"v": {"allowed_callers": None, "budget_prompt": False}}, "口味", 5, lambda: caller)
    assert records[0]["error"] and "max_tokens" in records[0]["error"]
    assert records[0]["evidence"] is None


def test_real_edition_films_work_as_input():
    """脚本直接拿期数据里的 film 和它的 verdict 当输入。字段不够要在这里发现，不要等到花了钱。"""
    import json
    compare = load_script()
    films = {f["film_id"]: f for f in json.loads((ROOT / "data" / "editions" / "2026-10-04.json").read_text(encoding="utf-8"))["films"]}
    ninja = films[61994]
    caller = FakeCaller(research_reply(GOOD), llm_reply(make_card(sources=[{"title": "t", "url": SRC}])))
    records = compare.run_variants([(ninja, ninja["verdict"])], {"v": {"allowed_callers": None, "budget_prompt": True}},
                                   "口味", 5, lambda: caller)
    assert records[0]["film"] == "Ninja Scroll 4K" and records[0]["error"] is None
    assert "Ninja Scroll 4K" in caller.calls[0]["user"]
