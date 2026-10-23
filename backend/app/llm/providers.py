from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

import httpx

from app.llm.breaker import CircuitBreaker


class AllProvidersFailed(Exception):
    pass


class CompletionClient(Protocol):
    async def complete(self, messages: list[dict[str, str]]) -> str: ...


class LLMProvider(Protocol):
    name: str

    async def complete(self, messages: list[dict[str, str]]) -> str: ...


class FakeProvider:
    def __init__(self, *, name: str, fail: bool = False, response: str = "ok") -> None:
        self.name = name
        self.fail = fail
        self.response = response
        self.calls = 0

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.name} unavailable")
        return self.response


class HttpLLMProvider:
    def __init__(
        self,
        *,
        name: str,
        kind: str,
        api_key: str,
        base_url: str,
        model: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.name = name
        self.kind = kind
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._client = client
        self._timeout = timeout

    async def complete(self, messages: list[dict[str, str]]) -> str:
        if not self.api_key:
            raise RuntimeError(f"{self.name} API key is not configured")
        if self.kind == "anthropic":
            return await self._complete_anthropic(messages)
        return await self._complete_openai(messages)

    async def _complete_openai(self, messages: list[dict[str, str]]) -> str:
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        should_close = self._client is None
        try:
            response = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0.2,
                },
            )
            response.raise_for_status()
            payload = response.json()
            return str(payload["choices"][0]["message"]["content"])
        finally:
            if should_close:
                await client.aclose()

    async def _complete_anthropic(self, messages: list[dict[str, str]]) -> str:
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        should_close = self._client is None
        system_parts = [message["content"] for message in messages if message["role"] == "system"]
        conversation = [message for message in messages if message["role"] != "system"]
        body: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": conversation,
        }
        if system_parts:
            body["system"] = "\n\n".join(system_parts)
        try:
            response = await client.post(
                f"{self.base_url}/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                },
                json=body,
            )
            response.raise_for_status()
            payload = response.json()
            return str(payload["content"][0]["text"])
        finally:
            if should_close:
                await client.aclose()


class LLMRouter:
    def __init__(self, providers: Sequence[LLMProvider], breaker: CircuitBreaker) -> None:
        self._providers = providers
        self._breaker = breaker

    async def complete(self, messages: list[dict[str, str]]) -> str:
        errors: list[str] = []
        for provider in self._providers:
            if self._breaker.is_open(provider.name):
                continue
            try:
                text = await provider.complete(messages)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{provider.name}: {exc}")
                self._breaker.record_failure(provider.name)
                continue
            self._breaker.record_success(provider.name)
            return text
        msg = "全部 LLM 厂商不可用: " + "; ".join(errors)
        raise AllProvidersFailed(msg)
