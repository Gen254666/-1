from typing import Any

from app.chat.orchestrator import run_chat


class FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    async def complete(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        return self.responses.pop(0)


class FakeMCP:
    def __init__(
        self,
        *,
        result: dict[str, Any] | None = None,
    ) -> None:
        self.result = result or {
            "summary": "1 条报价",
            "artifact": {"type": "cards", "payload": {"items": [{"price": 3550}]}},
            "meta": {"as_of": "2026-10-23"},
            "error": None,
        }
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def list_tools(self) -> list[dict[str, Any]]:
        return [{"name": "get_quotes"}, {"name": "get_inventory"}]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        return self.result


async def test_run_chat_calls_tool_then_answers() -> None:
    llm = FakeLLM(
        [
            '{"tool": "get_quotes", "arguments": {"category": "方管"}}',
            '{"final": "今日方管 3550 元/吨"}',
        ]
    )
    mcp = FakeMCP()

    result = await run_chat(llm=llm, mcp=mcp, message="今天方管多少钱")

    assert result.text == "今日方管 3550 元/吨"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "get_quotes"
    assert result.artifacts == [{"type": "cards", "payload": {"items": [{"price": 3550}]}}]
    assert mcp.calls == [("get_quotes", {"category": "方管"})]


async def test_run_chat_stops_at_tool_call_limit() -> None:
    llm = FakeLLM(['{"tool": "get_quotes", "arguments": {}}'] * 5)
    mcp = FakeMCP()

    result = await run_chat(llm=llm, mcp=mcp, message="查一下", max_rounds=4, max_calls=1)

    assert len(result.tool_calls) == 1
    assert any("上限" in warning for warning in result.warnings)
    assert "已达到查询轮数上限" in result.text


async def test_run_chat_reports_tool_error_to_llm() -> None:
    llm = FakeLLM(
        [
            '{"tool": "get_quotes", "arguments": {}}',
            '{"final": "数据暂时不可用"}',
        ]
    )
    mcp = FakeMCP(
        result={
            "summary": "",
            "artifact": None,
            "meta": {},
            "error": {
                "code": "DATA_UNAVAILABLE",
                "message": "没有数据",
                "details": {},
                "retryable": False,
            },
        }
    )

    result = await run_chat(llm=llm, mcp=mcp, message="查价")

    assert result.text == "数据暂时不可用"
    assert "没有数据" in result.warnings


async def test_run_chat_accepts_fenced_json() -> None:
    llm = FakeLLM(['```json\n{"final": "完成"}\n```'])
    mcp = FakeMCP()

    result = await run_chat(llm=llm, mcp=mcp, message="你好")

    assert result.text == "完成"
    assert result.tool_calls == []
