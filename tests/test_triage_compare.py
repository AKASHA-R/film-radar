import importlib.util
import json

from film_radar.llm import LLMError
from helpers import FakeCaller, ROOT, llm_reply, make_candidate


def load_script():
    spec = importlib.util.spec_from_file_location("triage_compare", ROOT / "scripts" / "triage_compare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def verdict_reply(*items):
    rows = [{"film_id": i, "keep": keep, "rank": rank, "category": "scifi", "reason": "理由"} for i, keep, rank in items]
    return llm_reply({"verdicts": rows})


def candidates():
    return [make_candidate(1, "片一"), make_candidate(2, "片二"), make_candidate(3, "片三")]


def test_every_model_is_run_the_requested_number_of_times():
    compare = load_script()
    callers = {
        "model-a": FakeCaller(verdict_reply((1, True, 1), (2, False, None), (3, True, 2)),
                              verdict_reply((1, True, 2), (2, True, 1), (3, False, None))),
        "model-b": FakeCaller(verdict_reply((1, False, None), (2, False, None), (3, True, 1))),
    }
    runs = compare.run_compare(candidates(), "口味", 2, {"model-a": 2, "model-b": 1}, lambda m: callers[m])
    assert [(r["model"], r["run"]) for r in runs] == [("model-a", 0), ("model-a", 1), ("model-b", 0)]
    assert runs[0]["kept"] == {"片一": 1, "片三": 2}
    assert runs[1]["kept"] == {"片二": 1, "片一": 2}
    assert runs[2]["kept"] == {"片三": 1}
    json.dumps(runs, ensure_ascii=False)


def test_usage_is_recorded_per_run():
    compare = load_script()
    caller = FakeCaller(verdict_reply((1, True, 1), (2, False, None), (3, False, None)))
    runs = compare.run_compare(candidates(), "口味", 2, {"m": 1}, lambda m: caller)
    assert runs[0]["input_tokens"] == 100 and runs[0]["output_tokens"] == 50    # llm_reply 的默认用量


def test_a_failing_run_is_recorded_not_fatal():
    """一次调用失败不能让整个对照作废：已经花掉的钱不能白花。"""
    compare = load_script()
    caller = FakeCaller(LLMError("限流: slow"), verdict_reply((1, True, 1), (2, False, None), (3, False, None)))
    runs = compare.run_compare(candidates(), "口味", 2, {"m": 2}, lambda m: caller)
    assert runs[0]["kept"] is None and "限流" in runs[0]["error"]
    assert runs[1]["kept"] == {"片一": 1} and runs[1]["error"] is None


def test_real_edition_films_are_valid_triage_input():
    """脚本直接拿期数据里的 films 当候选。字段不够的话要在这里发现，不要等到花了钱才发现。"""
    compare = load_script()
    films = json.loads((ROOT / "data" / "editions" / "2026-10-04.json").read_text(encoding="utf-8"))["films"]
    rows = [(f["film_id"], False, None) for f in films]
    caller = FakeCaller(verdict_reply(*rows))
    runs = compare.run_compare(films, "口味", 15, {"m": 1}, lambda m: caller)
    assert runs[0]["error"] is None and runs[0]["kept"] == {}
    assert "<candidates>" in caller.calls[0]["user"] and films[0]["title"] in caller.calls[0]["user"]
