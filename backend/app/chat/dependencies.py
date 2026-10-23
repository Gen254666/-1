from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.chat.mcp_client import default_mcp_factory
from app.core.config import get_settings
from app.llm.breaker import CircuitBreaker
from app.llm.providers import HttpLLMProvider, LLMRouter


@lru_cache
def get_llm_router() -> LLMRouter:
    settings = get_settings()
    providers: list[HttpLLMProvider] = []
    for name in settings.llm_fallback_order.split(","):
        provider_name = name.strip()
        if provider_name == "claude":
            providers.append(
                HttpLLMProvider(
                    name="claude",
                    kind="anthropic",
                    api_key=settings.anthropic_api_key,
                    base_url=settings.anthropic_base_url,
                    model=settings.claude_model,
                    timeout=settings.llm_timeout_seconds,
                )
            )
        elif provider_name == "deepseek":
            providers.append(
                HttpLLMProvider(
                    name="deepseek",
                    kind="openai",
                    api_key=settings.deepseek_api_key,
                    base_url=settings.deepseek_base_url,
                    model=settings.deepseek_model,
                    timeout=settings.llm_timeout_seconds,
                )
            )
        elif provider_name == "doubao" and settings.doubao_model:
            providers.append(
                HttpLLMProvider(
                    name="doubao",
                    kind="openai",
                    api_key=settings.doubao_api_key,
                    base_url=settings.doubao_base_url,
                    model=settings.doubao_model,
                    timeout=settings.llm_timeout_seconds,
                )
            )
    return LLMRouter(providers, CircuitBreaker(threshold=5, reset_seconds=30, name="llm"))


def get_mcp_client_factory() -> Any:
    return default_mcp_factory
