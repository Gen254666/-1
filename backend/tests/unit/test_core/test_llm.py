import json

import httpx
import pytest

from app.llm.breaker import CircuitBreaker
from app.llm.providers import (
    AllProvidersFailed,
    FakeProvider,
    HttpLLMProvider,
    LLMRouter,
)


def _openai_handler(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    assert payload["model"] == "deepseek-chat"
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": "你好，钢材行情"}}]},
    )


def _anthropic_handler(request: httpx.Request) -> httpx.Response:
    payload = json.loads(request.content)
    assert payload["model"] == "claude-test"
    return httpx.Response(200, json={"content": [{"type": "text", "text": "你好"}]})


async def test_openai_compatible_provider() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_openai_handler))
    provider = HttpLLMProvider(
        name="deepseek",
        kind="openai",
        api_key="key",
        base_url="https://api.deepseek.com",
        model="deepseek-chat",
        client=client,
    )

    text = await provider.complete([{"role": "user", "content": "hi"}])

    assert text == "你好，钢材行情"
    await client.aclose()


async def test_anthropic_provider() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(_anthropic_handler))
    provider = HttpLLMProvider(
        name="claude",
        kind="anthropic",
        api_key="key",
        base_url="https://api.anthropic.com",
        model="claude-test",
        client=client,
    )

    text = await provider.complete([{"role": "user", "content": "hi"}])

    assert text == "你好"
    await client.aclose()


async def test_router_falls_back_and_breaker_opens() -> None:
    failing = FakeProvider(name="first", fail=True)
    working = FakeProvider(name="second", response="fallback ok")
    breaker = CircuitBreaker(threshold=2, reset_seconds=60, name="test")
    router = LLMRouter([failing, working], breaker)

    assert await router.complete([{"role": "user", "content": "q"}]) == "fallback ok"
    assert await router.complete([{"role": "user", "content": "q"}]) == "fallback ok"
    assert breaker.is_open("first")

    assert await router.complete([{"role": "user", "content": "q"}]) == "fallback ok"
    assert failing.calls == 2


async def test_router_caps_total_attempts() -> None:
    providers = [FakeProvider(name=f"p{index}", fail=True) for index in range(5)]
    router = LLMRouter(
        providers,
        CircuitBreaker(threshold=10, reset_seconds=60, name="test"),
        max_attempts_per_provider=2,
        max_total_attempts=3,
    )

    with pytest.raises(AllProvidersFailed):
        await router.complete([{"role": "user", "content": "q"}])

    assert sum(provider.calls for provider in providers) == 3


async def test_router_raises_when_all_fail() -> None:
    router = LLMRouter(
        [FakeProvider(name="a", fail=True), FakeProvider(name="b", fail=True)],
        CircuitBreaker(threshold=1, reset_seconds=60, name="test"),
    )

    with pytest.raises(AllProvidersFailed):
        await router.complete([{"role": "user", "content": "q"}])


def test_breaker_resets_after_success() -> None:
    breaker = CircuitBreaker(threshold=2, reset_seconds=60, name="test")
    breaker.record_failure("p")
    breaker.record_failure("p")
    assert breaker.is_open("p")

    breaker.record_success("p")
    assert not breaker.is_open("p")
