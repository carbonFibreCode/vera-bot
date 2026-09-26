import json

import httpx
import pytest

from vera.compose.prompts import Draft
from vera.llm.base import LLMError
from vera.llm.openai_compat import OpenAICompatibleClient

DRAFT = {"body": "Dr. Meera, ...", "rationale": "why", "template_params": []}


def client(handler: httpx.MockTransport, strict: bool = True) -> OpenAICompatibleClient:
    return OpenAICompatibleClient(
        "openai/gpt-oss-120b",
        "https://api.groq.com/openai/v1",
        "test-key",
        5,
        strict_schema=strict,
        extra={"reasoning_effort": "low"},
        transport=handler,
    )


def completion(content: dict[str, object]) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})


async def test_strict_schema_request_shape() -> None:
    seen: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return completion(DRAFT)

    draft = await client(httpx.MockTransport(handle)).complete("system", "prompt", Draft)
    assert draft.body == DRAFT["body"]
    body = seen[0]
    assert body["reasoning_effort"] == "low"
    assert body["response_format"]["type"] == "json_schema"  # type: ignore[index]
    assert body["response_format"]["json_schema"]["strict"] is True  # type: ignore[index]


async def test_loose_mode_describes_schema_in_prompt() -> None:
    seen: list[dict[str, object]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return completion(DRAFT)

    await client(httpx.MockTransport(handle), strict=False).complete("system", "prompt", Draft)
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert "Reply with JSON matching" in seen[0]["messages"][0]["content"]  # type: ignore[index]


async def test_rate_limit_triggers_cooldown_without_further_calls() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"retry-after": "30"}, text="rate limited")

    llm = client(httpx.MockTransport(handle))
    with pytest.raises(LLMError, match="429"):
        await llm.complete("system", "prompt", Draft)
    with pytest.raises(LLMError, match="cooling down"):
        await llm.complete("system", "prompt", Draft)
    assert calls == 1


async def test_malformed_output_is_an_llm_error() -> None:
    llm = client(httpx.MockTransport(lambda request: completion({"body": "missing fields"})))
    with pytest.raises(LLMError):
        await llm.complete("system", "prompt", Draft)
