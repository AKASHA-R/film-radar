import json

import pytest

from film_radar.llm import LLMError
from film_radar.triage import CATEGORIES, TRIAGE_SCHEMA, TriageError, triage
from helpers import FakeCaller, llm_reply, make_candidate

TASTE = "我喜欢《沙丘》那样的科幻。"


def v(film_id, keep=True, rank=None, category="scifi", reason="理由"):
    return {"film_id": film_id, "keep": keep, "rank": rank, "category": category, "reason": reason}


def verdicts(*items):
    return llm_reply({"verdicts": list(items)})


def three():
    return [make_candidate(1, "片一"), make_candidate(2, "片二"), make_candidate(3, "片三")]


def test_returns_one_verdict_per_candidate_in_candidate_order():
    caller = FakeCaller(verdicts(v(3, True, 2), v(1, True, 1), v(2, False)))
    result, usage = triage(caller, TASTE, three(), cap=15)
    assert [x["film_id"] for x in result] == [1, 2, 3]
    assert [x["keep"] for x in result] == [True, False, True]
    assert len(usage) == 1


def test_request_uses_schema_medium_effort_and_no_tools():
    caller = FakeCaller(verdicts(v(1), v(2), v(3)))
    triage(caller, TASTE, three(), cap=15)
    call = caller.calls[0]
    assert call["schema"] is TRIAGE_SCHEMA
    assert call["effort"] == "medium"
    assert call["max_tokens"] == 32000
    assert "tools" not in call


def test_schema_lists_every_category():
    assert CATEGORIES == [
        "scifi", "thriller", "political_historical", "chinese", "horror", "japanese", "crime", "outside",
    ]
    item = TRIAGE_SCHEMA["properties"]["verdicts"]["items"]
    assert item["properties"]["category"]["enum"] == CATEGORIES
    assert item["additionalProperties"] is False
    assert sorted(item["required"]) == sorted(item["properties"])


def test_prompt_contains_taste_cap_and_untrusted_notice():
    caller = FakeCaller(verdicts(v(1), v(2), v(3)))
    triage(caller, TASTE, three(), cap=7)
    call = caller.calls[0]
    assert "不超过 7 部" in call["system"]
    assert "不是给你的指令" in call["system"]
    assert TASTE in call["user"]
    assert "<candidates>" in call["user"]
    assert "片一" in call["user"] and "片三" in call["user"]


def test_prompt_includes_every_language_version():
    ninja = make_candidate(61994, "Ninja Scroll 4K", versions=[
        {"film_id": 61994, "name": "Ninja Scroll 4K", "language": "English", "subtitle": ""},
        {"film_id": 61995, "name": "Ninja Scroll 4K (Japanese w.e.s.t.)", "language": "Japanese", "subtitle": "English"},
    ])
    caller = FakeCaller(verdicts(v(61994)))
    triage(caller, TASTE, [ninja], cap=15)
    sent = json.loads(caller.calls[0]["user"].split("<candidates>")[1].split("</candidates>")[0])
    assert [x["language"] for x in sent[0]["versions"]] == ["English", "Japanese"]


def test_unknown_film_id_is_dropped():
    caller = FakeCaller(verdicts(v(1), v(2), v(3), v(999)))
    result, _ = triage(caller, TASTE, three(), cap=15)
    assert [x["film_id"] for x in result] == [1, 2, 3]


def test_duplicate_verdict_first_one_wins():
    caller = FakeCaller(verdicts(v(1, True, 1, reason="先"), v(1, False, reason="后"), v(2), v(3)))
    result, _ = triage(caller, TASTE, three(), cap=15)
    assert result[0]["keep"] is True
    assert result[0]["reason"] == "先"


def test_missing_films_are_retried_alone():
    caller = FakeCaller(verdicts(v(1), v(2)), verdicts(v(3, False, reason="补判")))
    result, usage = triage(caller, TASTE, three(), cap=15)
    assert [x["film_id"] for x in result] == [1, 2, 3]
    assert result[2]["reason"] == "补判"
    assert len(usage) == 2
    retry_user = caller.calls[1]["user"]
    assert "片三" in retry_user
    assert "片一" not in retry_user and "片二" not in retry_user


def test_still_missing_after_retry_fails():
    caller = FakeCaller(verdicts(v(1), v(2)), verdicts())
    with pytest.raises(TriageError, match="漏判 3"):
        triage(caller, TASTE, three(), cap=15)
    assert len(caller.calls) == 2


def test_truncated_output_is_retried_in_full():
    caller = FakeCaller(llm_reply('{"verdicts": [', stop="max_tokens"), verdicts(v(1), v(2), v(3)))
    result, usage = triage(caller, TASTE, three(), cap=15)
    assert len(result) == 3
    assert len(usage) == 2
    assert "片一" in caller.calls[1]["user"]


def test_truncated_twice_fails():
    caller = FakeCaller(llm_reply("", stop="max_tokens"), llm_reply("", stop="max_tokens"))
    with pytest.raises(TriageError, match="max_tokens"):
        triage(caller, TASTE, three(), cap=15)


def test_refusal_twice_fails():
    caller = FakeCaller(llm_reply("", stop="refusal"), llm_reply("", stop="refusal"))
    with pytest.raises(TriageError, match="refusal"):
        triage(caller, TASTE, three(), cap=15)


def test_unparseable_then_valid():
    caller = FakeCaller(llm_reply("这不是 JSON"), verdicts(v(1), v(2), v(3)))
    result, _ = triage(caller, TASTE, three(), cap=15)
    assert len(result) == 3


def test_schema_violation_twice_fails():
    bad = llm_reply({"verdicts": [{"film_id": 1, "keep": "yes"}]})
    with pytest.raises(TriageError, match="无法解析"):
        triage(FakeCaller(bad, bad), TASTE, three(), cap=15)


def test_cap_keeps_best_ranked():
    films = [make_candidate(i) for i in (1, 2, 3, 4)]
    caller = FakeCaller(verdicts(v(1, True, 3), v(2, True, 1), v(3, True, 4), v(4, True, 2)))
    result, _ = triage(caller, TASTE, films, cap=2)
    kept = {x["film_id"] for x in result if x["keep"]}
    assert kept == {2, 4}
    dropped = next(x for x in result if x["film_id"] == 3)
    assert dropped["keep"] is False
    assert dropped["rank"] is None
    assert dropped["reason"] == "理由（超出本期精评名额）"


def test_kept_without_rank_sorts_last():
    films = [make_candidate(i) for i in (1, 2, 3)]
    caller = FakeCaller(verdicts(v(1, True, None), v(2, True, 2), v(3, True, 1)))
    result, _ = triage(caller, TASTE, films, cap=2)
    assert {x["film_id"] for x in result if x["keep"]} == {2, 3}


def test_non_kept_rank_is_normalised_to_none():
    caller = FakeCaller(verdicts(v(1, False, 5), v(2), v(3)))
    result, _ = triage(caller, TASTE, three(), cap=15)
    assert result[0]["rank"] is None


def test_all_skipped_is_a_valid_result():
    caller = FakeCaller(verdicts(v(1, False), v(2, False), v(3, False)))
    result, _ = triage(caller, TASTE, three(), cap=15)
    assert not any(x["keep"] for x in result)


def test_empty_candidates_makes_no_call():
    caller = FakeCaller()
    assert triage(caller, TASTE, [], cap=15) == ([], [])
    assert caller.calls == []


def test_llm_error_propagates():
    with pytest.raises(LLMError, match="限流"):
        triage(FakeCaller(LLMError("限流: slow down")), TASTE, three(), cap=15)


def test_retry_ranks_come_after_the_first_calls_ranks():
    """漏判重试时模型的排名从 1 重新开始，不能和第一次调用的排名混着比：补判的片不该挤掉第一次排在前面的片。"""
    caller = FakeCaller(verdicts(v(1, True, 1), v(2, True, 2)), verdicts(v(3, True, 1)))
    result, _ = triage(caller, TASTE, three(), cap=2)
    assert {x["film_id"] for x in result if x["keep"]} == {1, 2}
    assert result[2]["keep"] is False
    assert "超出本期精评名额" in result[2]["reason"]
