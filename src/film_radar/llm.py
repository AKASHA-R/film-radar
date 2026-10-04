"""唯一调用 anthropic SDK 的地方。

SDK 自带对 429、5xx、连接错误的重试。这里把重试用尽后的异常统一成 LLMError，
并处理服务端工具的 pause_turn 续跑。stop_reason 为 max_tokens 或 refusal 时不抛异常，
原样返回，由调用方决定怎么算失败。
"""
from __future__ import annotations

from dataclasses import dataclass

import anthropic
import httpx2

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_CONTINUATIONS = 3


class LLMError(Exception):
    pass


@dataclass
class LLMResult:
    stop_reason: str
    text: str
    blocks: list[dict]
    input_tokens: int
    output_tokens: int


def _send(client, params: dict):
    """发一次请求。返回 (message.to_dict(), message.content)。

    第二项是 SDK 原始的内容块对象，pause_turn 续跑时要把它原样发回去。
    """
    try:
        with client.beta.messages.stream(**params) as stream:
            final = stream.get_final_message()
        return final.to_dict(), final.content
    except anthropic.RateLimitError as e:
        raise LLMError(f"限流: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"API 错误 {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError(f"连接失败: {e}") from e
    except httpx2.HTTPError as e:
        # SDK 只给"发请求"这一步包了异常；流式响应读到一半断连，httpx2 的错误会原样漏出来，
        # 而且不会被重试。不转成 LLMError，review_film 就记不成「这一部精评失败」，整期作废
        raise LLMError(f"流式传输中断: {type(e).__name__}: {e}") from e


def call(client, *, model: str, system: str, user: str, effort: str, max_tokens: int,
         schema: dict | None = None, tools: list[dict] | None = None) -> LLMResult:
    output_config: dict = {"effort": effort}
    if schema is not None:
        output_config["format"] = {"type": "json_schema", "schema": schema}

    blocks: list[dict] = []
    resend: list = []
    tokens_in = tokens_out = 0
    for _ in range(MAX_CONTINUATIONS + 1):
        messages = [{"role": "user", "content": user}]
        if resend:
            messages.append({"role": "assistant", "content": list(resend)})
        params = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": messages,
            "thinking": {"type": "adaptive"},
            "output_config": output_config,
            "betas": [FALLBACK_BETA],
            "fallbacks": "default",
        }
        if tools:
            params["tools"] = tools
        as_dict, original = _send(client, params)
        blocks.extend(as_dict["content"])
        resend.extend(original)
        usage = as_dict.get("usage") or {}
        tokens_in += usage.get("input_tokens") or 0
        tokens_out += usage.get("output_tokens") or 0
        if as_dict["stop_reason"] != "pause_turn":
            text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            return LLMResult(as_dict["stop_reason"], text, blocks, tokens_in, tokens_out)
    raise LLMError(f"pause_turn 续跑 {MAX_CONTINUATIONS} 次后仍未完成")
