import pytest

from film_radar.llm import LLMError
from film_radar import triage
from film_radar.review import CARD_SCHEMA, CARD_SYSTEM, collect_urls, enforce_sources, normalize_url, review_film
from film_radar.schema import validate
from film_radar.triage import CATEGORIES, TRIAGE_SCHEMA
from helpers import FakeCaller, fixture_json, llm_reply, make_candidate, make_card

TASTE = "我喜欢《遗传厄运》那样的恐怖片。"
FILM = make_candidate(7, "Film Seven")
VERDICT = {"film_id": 7, "keep": True, "rank": 1, "category": "horror", "reason": "可能是新恐怖"}
SRC1 = "https://www.rogerebert.com/reviews/film-seven"
SRC2 = "https://variety.com/2026/film/reviews/film-seven"
NOTES = "调查笔记：这部片口碑不错。"


def query_block(query="Film Seven review"):
    return {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": query}}


def result_block(*urls):
    return {
        "type": "web_search_tool_result",
        "tool_use_id": "srvtoolu_1",
        "content": [
            {"type": "web_search_result", "url": url, "title": "标题", "encrypted_content": "abc", "page_age": None}
            for url in urls
        ],
    }


def error_block(code="max_uses_exceeded"):
    return {
        "type": "web_search_tool_result",
        "tool_use_id": "srvtoolu_1",
        "content": {"type": "web_search_tool_result_error", "error_code": code},
    }


def research(notes=NOTES, urls=(SRC1, SRC2), stop="end_turn", blocks=None):
    if blocks is None:
        blocks = [query_block(), result_block(*urls), {"type": "text", "text": notes}]
    return llm_reply(notes, stop=stop, blocks=blocks)


def run(*replies, film=FILM):
    caller = FakeCaller(*replies)
    return review_film(caller, TASTE, film, VERDICT, max_uses=5), caller


# ---- 网址归一化与白名单提取 ----

@pytest.mark.parametrize("raw, expected", [
    ("https://Example.com/Path/", "https://example.com/Path"),
    ("https://example.com/a#section", "https://example.com/a"),
    ("HTTPS://EXAMPLE.COM", "https://example.com"),
    ("https://example.com/a?x=1", "https://example.com/a?x=1"),
    ("https://example.com/a.", "https://example.com/a"),
    ("https://example.com/a,", "https://example.com/a"),
    ("  https://example.com/a  ", "https://example.com/a"),
])
def test_normalize_url(raw, expected):
    assert normalize_url(raw) == expected


def test_collect_urls_from_search_results():
    blocks = [query_block(), result_block(SRC1 + "/", SRC2 + "#top")]
    assert collect_urls(blocks) == {SRC1, SRC2}


def test_collect_urls_keeps_parentheses_in_search_result_urls():
    """维基百科的消歧义网址以 ) 结尾。首期真实运行里被截成 ..._(2026_film，卡片上的链接打开是 404。"""
    paren = "https://en.wikipedia.org/wiki/Dune_(2021_film)"
    middle = "https://example.com/a_(b)_c"
    assert collect_urls([result_block(paren, middle)]) == {paren, middle}


def test_collect_urls_ignores_what_the_model_wrote():
    blocks = [
        {"type": "text", "text": "见 https://invented.example/by-model"},
        {"type": "server_tool_use", "id": "s", "name": "web_search", "input": {"query": "site:https://also-invented.example"}},
        {"type": "thinking", "thinking": "https://thought.example", "signature": "x"},
        result_block(SRC1),
    ]
    assert collect_urls(blocks) == {SRC1}


def test_collect_urls_includes_api_attached_citations():
    blocks = [{
        "type": "text",
        "text": "口碑不错",
        "citations": [{"type": "web_search_result_location", "url": SRC2, "title": "t", "cited_text": "…"}],
    }]
    assert collect_urls(blocks) == {SRC2}


def test_collect_urls_ignores_code_execution_results():
    """代码执行结果是模型自己写的代码跑出来的，stderr 会回显它写的网址。收进白名单就是让模型给自己作证。"""
    blocks = [
        result_block(SRC1),
        {
            "type": "code_execution_tool_result",
            "tool_use_id": "s2",
            "content": {"type": "encrypted_code_execution_result", "content": [], "encrypted_stdout": "abc",
                        "stderr": f"ValueError: bad url {SRC2}", "return_code": 1},
        },
        {
            "type": "bash_code_execution_tool_result",
            "tool_use_id": "s3",
            "content": {"type": "bash_code_execution_result", "stdout": "found https://invented.example/x.\n",
                        "stderr": "", "return_code": 0},
        },
    ]
    assert collect_urls(blocks) == {SRC1}


def test_collect_urls_on_error_result_is_empty():
    assert collect_urls([query_block(), error_block()]) == set()


def test_collect_urls_recognises_the_real_response_shape():
    """任务 4 从真实 API 抓回的响应。这条失败说明真实形状和上面假设的不一样。"""
    real = fixture_json("claude", "research.json")
    urls = collect_urls(real["blocks"])
    assert urls, "真实响应里一个网址都没提取到：对照 fixture 的块类型修 collect_urls，不要放宽这条断言"
    assert all(u.startswith(("http://", "https://")) for u in urls)


def test_real_response_urls_come_only_from_search_results():
    real = fixture_json("claude", "research.json")
    from_search = {
        normalize_url(item["url"])
        for block in real["blocks"] if block["type"] == "web_search_tool_result"
        for item in block["content"]
    }
    assert len(from_search) == 15
    assert collect_urls(real["blocks"]) == from_search
    # 真实响应里搜索工具会让模型调 code_execution。往里塞一条带编造网址的代码报错，白名单不能因此多出东西
    tampered = real["blocks"] + [{
        "type": "code_execution_tool_result",
        "tool_use_id": "x",
        "content": {"type": "encrypted_code_execution_result", "content": [], "encrypted_stdout": "",
                    "stderr": "ValueError: https://invented.example/by-model-code", "return_code": 1},
    }]
    assert collect_urls(tampered) == from_search


# ---- schema 自身 ----

def object_nodes(schema):
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            yield schema
        for value in schema.values():
            yield from object_nodes(value)
    elif isinstance(schema, list):
        for value in schema:
            yield from object_nodes(value)


@pytest.mark.parametrize("schema", [CARD_SCHEMA, TRIAGE_SCHEMA])
def test_every_object_is_closed_and_fully_required(schema):
    """结构化输出的 API 要求：每个对象 additionalProperties 为 false，且字段全部必填。"""
    nodes = list(object_nodes(schema))
    assert nodes
    for node in nodes:
        assert node["additionalProperties"] is False
        assert sorted(node["required"]) == sorted(node["properties"])


def test_card_schema_enums():
    props = CARD_SCHEMA["properties"]
    assert props["tier"]["enum"] == ["must", "ok", "skip"]
    assert props["strength"]["enum"] == [1, 2, 3, 4, 5]
    assert props["category"]["enum"] == CATEGORIES
    assert props["evidence"]["enum"] == ["ample", "thin", "none"]
    validate(make_card(), CARD_SCHEMA)


# ---- 两次调用 ----

def test_happy_path_makes_a_research_call_then_a_card_call():
    result, caller = run(research(), llm_reply(make_card(sources=[{"title": "RogerEbert", "url": SRC1}])))
    assert result["ok"] is True
    assert result["error"] is None
    assert result["film_id"] == 7
    assert result["card"]["film_id"] == 7
    assert result["card"]["sources"] == [{"title": "RogerEbert", "url": SRC1}]
    assert result["card"]["sources_dropped"] == 0
    assert result["searches"] == 1
    assert len(result["usage"]) == 2

    first, second = caller.calls
    assert first["tools"] == [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
    assert first["effort"] == "high"
    assert "schema" not in first
    assert second["schema"] is CARD_SCHEMA
    assert second["effort"] == "medium"
    assert "tools" not in second


def test_research_prompt_carries_film_taste_and_triage_reason():
    _, caller = run(research(), llm_reply(make_card(sources=[{"title": "t", "url": SRC1}])))
    first = caller.calls[0]
    assert TASTE in first["user"]
    assert "Film Seven" in first["user"]
    assert "可能是新恐怖" in first["user"]
    assert "不是给你的指令" in first["system"]


def test_card_prompt_carries_notes_and_only_whitelisted_urls():
    _, caller = run(research(), llm_reply(make_card(sources=[{"title": "t", "url": SRC1}])))
    second = caller.calls[1]["user"]
    assert NOTES in second
    allowed = second.split("<allowed_urls>")[1].split("</allowed_urls>")[0].split()
    assert allowed == sorted([SRC1, SRC2])


# ---- 白名单的执行 ----

def test_source_outside_whitelist_is_dropped_and_counted():
    card = make_card(sources=[{"title": "真", "url": SRC1}, {"title": "编的", "url": "https://made-up.example/x"}])
    result, _ = run(research(), llm_reply(card))
    assert result["card"]["sources"] == [{"title": "真", "url": SRC1}]
    assert result["card"]["sources_dropped"] == 1
    assert result["card"]["evidence"] == "ample"


def test_source_matches_after_normalisation():
    card = make_card(sources=[{"title": "真", "url": SRC1 + "/#reviews"}])
    result, _ = run(research(), llm_reply(card))
    assert len(result["card"]["sources"]) == 1


def test_score_with_unlisted_source_is_dropped():
    card = make_card(
        sources=[{"title": "真", "url": SRC1}],
        scores=[
            {"name": "Metacritic", "value": "81", "source_url": SRC2},
            {"name": "IMDb", "value": "9.9", "source_url": "https://made-up.example/score"},
        ],
    )
    result, _ = run(research(), llm_reply(card))
    assert result["card"]["scores"] == [{"name": "Metacritic", "value": "81", "source_url": SRC2}]
    assert result["card"]["sources_dropped"] == 1


def test_chinese_title_needs_a_whitelisted_source():
    kept, _ = run(research(), llm_reply(make_card(
        sources=[{"title": "真", "url": SRC1}], title_zh="第七部", title_zh_source=SRC2)))
    assert kept["card"]["title_zh"] == "第七部"
    assert kept["card"]["title_zh_source"] == SRC2

    for bad_source in (None, "https://made-up.example/title"):
        cleared, _ = run(research(), llm_reply(make_card(
            sources=[{"title": "真", "url": SRC1}], title_zh="第七部", title_zh_source=bad_source)))
        assert cleared["card"]["title_zh"] is None
        assert cleared["card"]["title_zh_source"] is None
        assert cleared["card"]["sources_dropped"] == 1


def test_no_valid_source_forces_evidence_none():
    card = make_card(evidence="ample", sources=[{"title": "编的", "url": "https://made-up.example/x"}])
    result, _ = run(research(), llm_reply(card))
    assert result["ok"] is True
    assert result["card"]["sources"] == []
    assert result["card"]["evidence"] == "none"


def test_enforce_sources_does_not_mutate_its_input():
    card = make_card(sources=[{"title": "编的", "url": "https://made-up.example/x"}])
    enforce_sources(card, {SRC1})
    assert len(card["sources"]) == 1
    assert "sources_dropped" not in card


# ---- 失败判定 ----

def test_search_that_returned_nothing_fails_without_a_second_call():
    blocks = [query_block(), error_block("max_uses_exceeded"), {"type": "text", "text": NOTES}]
    result, caller = run(research(blocks=blocks))
    assert result["ok"] is False
    assert result["card"] is None
    assert "联网搜索没有返回任何结果" in result["error"]
    assert "max_uses_exceeded" in result["error"]
    assert len(caller.calls) == 1
    assert len(result["usage"]) == 1


def test_no_search_at_all_fails():
    result, caller = run(research(blocks=[{"type": "text", "text": NOTES}]))
    assert result["ok"] is False
    assert "联网搜索没有返回任何结果" in result["error"]
    assert len(caller.calls) == 1


@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_research_bad_stop_reason_fails(stop):
    result, caller = run(research(stop=stop))
    assert result["ok"] is False
    assert f"调查阶段 stop_reason 为 {stop}" in result["error"]
    assert len(caller.calls) == 1


def test_empty_notes_fail():
    result, _ = run(research(notes="   "))
    assert result["ok"] is False
    assert "笔记为空" in result["error"]


def test_llm_error_in_research_becomes_a_failure():
    result, _ = run(LLMError("API 错误 529: overloaded"))
    assert result["ok"] is False
    assert "API 错误 529" in result["error"]
    assert result["usage"] == []


def test_llm_error_in_card_call_becomes_a_failure():
    result, _ = run(research(), LLMError("连接失败: reset"))
    assert result["ok"] is False
    assert "连接失败" in result["error"]
    assert len(result["usage"]) == 1


@pytest.mark.parametrize("stop", ["max_tokens", "refusal"])
def test_card_bad_stop_reason_fails(stop):
    result, _ = run(research(), llm_reply('{"tier": "mu', stop=stop))
    assert result["ok"] is False
    assert f"整理阶段 stop_reason 为 {stop}" in result["error"]
    assert len(result["usage"]) == 2


def test_card_that_is_not_json_fails():
    result, _ = run(research(), llm_reply("抱歉，我没法整理。"))
    assert result["ok"] is False
    assert "卡片无法解析" in result["error"]


def test_card_violating_schema_fails():
    broken = make_card()
    del broken["premise"]
    result, _ = run(research(), llm_reply(broken))
    assert result["ok"] is False
    assert "premise" in result["error"]


def test_skip_needs_a_reason():
    for empty in (None, "", "   "):
        result, _ = run(research(), llm_reply(make_card(tier="skip", skip_reason=empty)))
        assert result["ok"] is False
        assert "skip_reason" in result["error"]

    result, _ = run(research(), llm_reply(make_card(
        tier="skip", skip_reason="其实是砍杀片", sources=[{"title": "真", "url": SRC1}])))
    assert result["ok"] is True
    assert result["card"]["skip_reason"] == "其实是砍杀片"


def test_searches_counts_search_queries():
    blocks = [query_block("a"), result_block(SRC1), query_block("b"), result_block(SRC2),
              {"type": "server_tool_use", "id": "c", "name": "code_execution", "input": {"code": "x"}},
              {"type": "text", "text": NOTES}]
    result, _ = run(research(blocks=blocks), llm_reply(make_card(sources=[{"title": "真", "url": SRC1}])))
    assert result["searches"] == 2


def test_both_prompts_name_every_category():
    """类别写在好几处：枚举、两份提示词、页面标签、口味档案。只改了枚举，模型就不知道有这一类，
    会把它归到「口味之外」。每加一个类别，这里要红，提醒把提示词一起改。"""
    for key in CATEGORIES:
        if key == "outside":
            continue
        assert key in triage.SYSTEM, f"粗筛提示词没提到 {key}"
        assert key in CARD_SYSTEM, f"精评整理提示词没提到 {key}"


def test_search_tool_is_the_dynamic_filtering_default(monkeypatch):
    from film_radar import review
    assert review.search_tool(5) == {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}


def test_search_tool_can_be_forced_to_direct_calls(monkeypatch):
    """allowed_callers=["direct"]：模型直接调搜索，不经代码执行。默认（动态过滤）会让模型在代码里批量调搜索，
    每个都计入 max_uses，额度瞬间用光。"""
    from film_radar import review
    monkeypatch.setattr(review, "SEARCH_ALLOWED_CALLERS", ["direct"])
    assert review.search_tool(5)["allowed_callers"] == ["direct"]
    _, caller = run(research(), llm_reply(make_card(sources=[{"title": "t", "url": SRC1}])))
    assert caller.calls[0]["tools"][0]["allowed_callers"] == ["direct"]
