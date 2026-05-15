"""VLM provider 封装。默认 mock 模式（无 API key 即可跑）。"""
from __future__ import annotations

import json
import os
from typing import Any


def _provider_from_env() -> str:
    explicit = os.getenv("VLM_PROVIDER", "").strip().lower()
    if explicit:
        if explicit not in {"anthropic", "openai"}:
            raise RuntimeError(f"unsupported VLM_PROVIDER={explicit!r}; use anthropic or openai")
        return explicit
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "anthropic"


PROVIDER = _provider_from_env()
_KEY_ENV = "OPENAI_API_KEY" if PROVIDER == "openai" else "ANTHROPIC_API_KEY"
MOCK_MODE = os.getenv("VLM_MOCK", "1") == "1" or not os.getenv(_KEY_ENV)
MODEL_ID = os.getenv(
    "VLM_MODEL",
    "gpt-5.4-mini" if PROVIDER == "openai" else "claude-sonnet-4-6",
)


def is_mock() -> bool:
    return MOCK_MODE


def provider_name() -> str:
    return "mock" if MOCK_MODE else PROVIDER


def model_name() -> str:
    return "mock" if MOCK_MODE else f"{PROVIDER}:{MODEL_ID}"


def _get_field(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _extract_openai_text(resp: Any) -> str:
    output_text = getattr(resp, "output_text", None)
    if output_text:
        return str(output_text)

    parts: list[str] = []
    for item in _get_field(resp, "output") or []:
        for block in _get_field(item, "content") or []:
            text = _get_field(block, "text")
            if text:
                parts.append(str(text))
    if parts:
        return "\n".join(parts)
    raise RuntimeError(f"OpenAI response did not contain output_text: {resp}")


def _parse_json_object(text: str, provider: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        snippet = text[:1000].replace("\n", "\\n")
        raise RuntimeError(f"{provider} returned invalid JSON: {snippet}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{provider} returned non-object JSON: {data!r}")
    return data


def call_vlm(
    system: str,
    user_text: str,
    images_b64: list[str],
    tool_schema: dict,
    *,
    max_tokens: int = 1024,
) -> dict:
    """调用当前 VLM provider，返回结构化 decision dict。

    mock 模式下不调真 API，调用方应通过 decisions/*.py 的 mock 分支早早返回。
    """
    if MOCK_MODE:
        raise RuntimeError(
            "call_vlm() invoked in mock mode; "
            "decisions/*.py should branch on is_mock() and return mock response first."
        )

    if PROVIDER == "openai":
        return _call_openai(system, user_text, images_b64, tool_schema, max_tokens=max_tokens)
    return _call_anthropic(system, user_text, images_b64, tool_schema, max_tokens=max_tokens)


def _call_anthropic(
    system: str,
    user_text: str,
    images_b64: list[str],
    tool_schema: dict,
    *,
    max_tokens: int,
) -> dict:
    from anthropic import Anthropic

    client = Anthropic()
    content: list[dict] = []
    for b64 in images_b64:
        if not b64:
            continue
        content.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
            }
        )
    content.append({"type": "text", "text": user_text})

    resp = client.messages.create(
        model=MODEL_ID,
        max_tokens=max_tokens,
        system=[
            {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
        ],
        tools=[
            {
                "name": "submit_decision",
                "description": "提交本次决策结果",
                "input_schema": tool_schema,
            }
        ],
        tool_choice={"type": "tool", "name": "submit_decision"},
        messages=[{"role": "user", "content": content}],
    )

    for block in resp.content:
        if block.type == "tool_use" and block.name == "submit_decision":
            return dict(block.input)
    raise RuntimeError(f"VLM did not return tool_use: {resp}")


def _call_openai(
    system: str,
    user_text: str,
    images_b64: list[str],
    tool_schema: dict,
    *,
    max_tokens: int,
) -> dict:
    from openai import OpenAI

    client = OpenAI()
    content: list[dict] = []
    for b64 in images_b64:
        if not b64:
            continue
        content.append(
            {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{b64}",
                "detail": "auto",
            }
        )
    content.append({"type": "input_text", "text": user_text})

    resp = client.responses.create(
        model=MODEL_ID,
        input=[
            {
                "role": "system",
                "content": system + "\n\n请严格输出符合 JSON Schema 的 JSON 对象。",
            },
            {"role": "user", "content": content},
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": "submit_decision",
                "schema": tool_schema,
                "strict": False,
            }
        },
        max_output_tokens=max_tokens,
    )
    return _parse_json_object(_extract_openai_text(resp), "OpenAI")
