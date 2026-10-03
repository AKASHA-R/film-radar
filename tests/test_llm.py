from types import SimpleNamespace

import anthropic
import pytest

from film_radar import llm
from film_radar.llm import FALLBACK_BETA, LLMError, LLMResult


def message(stop="end_turn", content=None, tokens_in=10, tokens_out=5):
    content = content if content is not None else [{"type": "text", "text": "好"}]
    as_dict = {
        "stop_reason": stop,
        "content": content,
        "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
    }
    return as_dict, content


@pytest.fixture
def sent(monkeypatch):
    """把 llm._send 换成按顺序吐出预设回复的假实现，并记录每次的请求参数。"""
    record = SimpleNamespace(params=[], replies=[])

    def fake_send(client, params):
        record.params.append(params)
        return record.replies.pop(0)

    monkeypatch.setattr(llm, "_send", fake_send)
    return record


def call(**overrides):
    kwargs = dict(model="claude-opus-5-5", system="系统", user="用户", effort="medium", max_tokens=16000)
    kwargs.update(overrides)
    return llm.call(object(), **kwargs)


def test_request_shape_without_schema_or_tools(sent):
    sent.replies.append(message())
    result = call()
    params = sent.params[0]
    assert params["model"] == "claude-opus-5-5"
    assert params["max_tokens"] == 16000
    assert params["system"] == "系统"
    assert params["messages"] == [{"role": "user", "content": "用户"}]
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"] == {"effort": "medium"}
    assert params["betas"] == [FALLBACK_BETA]
    assert params["fallbacks"] == "default"
    assert "tools" not in params
    assert isinstance(result, LLMResult)
    assert result.stop_reason == "end_turn"
    assert result.text == "好"
    assert (result.input_tokens, result.output_tokens) == (10, 5)


def test_schema_goes_into_output_config_format(sent):
    sent.replies.append(message())
    schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    call(schema=schema, effort="high")
    assert sent.params[0]["output_config"] == {
        "effort": "high",
        "format": {"type": "json_schema", "schema": schema},
    }


def test_tools_are_passed_through(sent):
    sent.replies.append(message())
    tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": 5}]
    call(tools=tools)
    assert sent.params[0]["tools"] == tools


def test_text_joins_only_text_blocks(sent):
    sent.replies.append(message(content=[
        {"type": "thinking", "thinking": "", "signature": "x"},
        {"type": "text", "text": "第一段"},
        {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "q"}},
        {"type": "text", "text": "第二段"},
    ]))
    result = call()
    assert result.text == "第一段第二段"
    assert len(result.blocks) == 4


def test_pause_turn_resends_user_and_assistant_without_extra_message(sent):
    first = message(stop="pause_turn", content=[{"type": "text", "text": "查到一半"}], tokens_in=100, tokens_out=20)
    second = message(content=[{"type": "text", "text": "，查完了"}], tokens_in=130, tokens_out=30)
    sent.replies.extend([first, second])
    result = call()
    assert len(sent.params) == 2
    assert sent.params[1]["messages"] == [
        {"role": "user", "content": "用户"},
        {"role": "assistant", "content": [{"type": "text", "text": "查到一半"}]},
    ]
    assert result.stop_reason == "end_turn"
    assert result.text == "查到一半，查完了"
    assert (result.input_tokens, result.output_tokens) == (230, 50)


def test_second_pause_resends_everything_so_far(sent):
    sent.replies.extend([
        message(stop="pause_turn", content=[{"type": "text", "text": "一"}]),
        message(stop="pause_turn", content=[{"type": "text", "text": "二"}]),
        message(content=[{"type": "text", "text": "三"}]),
    ])
    result = call()
    assert sent.params[2]["messages"][1]["content"] == [
        {"type": "text", "text": "一"},
        {"type": "text", "text": "二"},
    ]
    assert result.text == "一二三"


def test_gives_up_after_max_continuations(sent):
    sent.replies.extend([message(stop="pause_turn") for _ in range(llm.MAX_CONTINUATIONS + 1)])
    with pytest.raises(LLMError, match="pause_turn"):
        call()
    assert len(sent.params) == llm.MAX_CONTINUATIONS + 1


def test_non_end_stop_reasons_are_returned_not_raised(sent):
    sent.replies.append(message(stop="max_tokens"))
    assert call().stop_reason == "max_tokens"
    sent.replies.append(message(stop="refusal", content=[]))
    refused = call()
    assert refused.stop_reason == "refusal"
    assert refused.text == ""


# ---- _send：唯一碰 SDK 的地方 ----

class FakeStream:
    def __init__(self, final):
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._final


def client_returning(final):
    captured = {}

    def stream(**params):
        captured.update(params)
        return FakeStream(final)

    client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))
    return client, captured


def client_raising(error):
    def stream(**params):
        raise error

    return SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))


def test_send_streams_and_returns_dict_plus_original_content():
    content = [SimpleNamespace(type="text", text="好")]
    final = SimpleNamespace(content=content, to_dict=lambda: {"stop_reason": "end_turn", "content": [{"type": "text", "text": "好"}], "usage": {}})
    client, captured = client_returning(final)
    as_dict, original = llm._send(client, {"model": "claude-opus-5-5"})
    assert captured == {"model": "claude-opus-5-5"}
    assert as_dict["stop_reason"] == "end_turn"
    assert original is content


def bare(error_class, **attrs):
    """绕过 SDK 异常的构造函数，只设置 _send 会读的属性。"""
    error = error_class.__new__(error_class)
    for name, value in attrs.items():
        setattr(error, name, value)
    return error


def test_send_maps_rate_limit():
    error = bare(anthropic.RateLimitError, status_code=429, message="slow down")
    with pytest.raises(LLMError, match="限流: slow down"):
        llm._send(client_raising(error), {})


def test_send_maps_status_error():
    error = bare(anthropic.APIStatusError, status_code=529, message="overloaded")
    with pytest.raises(LLMError, match="API 错误 529: overloaded"):
        llm._send(client_raising(error), {})


def test_send_maps_connection_error():
    error = bare(anthropic.APIConnectionError)
    with pytest.raises(LLMError, match="连接失败"):
        llm._send(client_raising(error), {})
