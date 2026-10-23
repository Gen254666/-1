from __future__ import annotations

import logging
import time

logger = logging.getLogger("app.llm.breaker")


class CircuitBreaker:
    def __init__(
        self,
        *,
        threshold: int = 5,
        reset_seconds: int = 30,
        name: str = "llm",
    ) -> None:
        self._threshold = threshold
        self._reset_seconds = reset_seconds
        self._name = name
        self._failures: dict[str, int] = {}
        self._opened_at: dict[str, float] = {}

    def is_open(self, key: str) -> bool:
        opened_at = self._opened_at.get(key)
        if opened_at is None:
            return False
        if time.monotonic() - opened_at >= self._reset_seconds:
            self._opened_at.pop(key, None)
            return False
        return True

    def record_failure(self, key: str) -> None:
        failures = self._failures.get(key, 0) + 1
        self._failures[key] = failures
        if failures >= self._threshold:
            self._opened_at[key] = time.monotonic()
            logger.warning(
                "circuit breaker opened",
                extra={"breaker": self._name, "provider": key, "failures": failures},
            )

    def record_success(self, key: str) -> None:
        self._failures.pop(key, None)
        self._opened_at.pop(key, None)
