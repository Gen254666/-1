from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.llm.providers import CompletionClient

SYSTEM_PROMPT = (
    "你是钢材行情分析助手。你只能使用工具返回的数据，禁止编造数字。\n"
    "每一步只输出一个 JSON 对象，不要输出其他文字：\n"
    '1. 需要查数据时输出 {"tool": "<工具名>", "arguments": { ... }}\n'
    '2. 可以回答时输出 {"final": "<中文回答，引用 [n] 来源>"}\n'
    "工具失败时如实说明，不要猜测数据。"
)

MAX_HISTORY_MESSAGES = 20


class MCPToolClient(Protocol):
    async def list_tools(self) -> list[dict[str, Any]]: ...

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass
class ChatResult:
    text: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _trim_history(history: list[dict[str, str]] | None) -> list[dict[str, str]]:
    if not history:
        return []
    return history[-MAX_HISTORY_MESSAGES:]


def _parse_decision(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {"final": text.strip()}
    try:
        decision = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError:
        return {"final": text.strip()}
    if not isinstance(decision, dict):
        return {"final": text.strip()}
    return decision


async def run_chat(
    *,
    llm: CompletionClient,
    mcp: MCPToolClient,
    message: str,
    history: list[dict[str, str]] | None = None,
    max_rounds: int = 4,
    max_calls: int = 8,
) -> ChatResult:
    tools = await mcp.list_tools()
    tool_names = [tool.get("name") for tool in tools if tool.get("name")]
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT + f"\n可用工具: {', '.join(str(name) for name in tool_names)}",
        },
        *_trim_history(history),
        {"role": "user", "content": message},
    ]

    artifacts: list[dict[str, Any]] = []
    tool_calls: list[ToolCallRecord] = []
    warnings: list[str] = []

    for _ in range(max_rounds):
        decision_text = await llm.complete(messages)
        decision = _parse_decision(decision_text)

        tool_name = decision.get("tool")
        if not tool_name:
            final_text = str(decision.get("final") or decision_text).strip()
            return ChatResult(final_text, artifacts, tool_calls, warnings)

        if len(tool_calls) >= max_calls:
            warnings.append("已达到单轮工具调用上限")
            break

        arguments = decision.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        result = await mcp.call_tool(str(tool_name), arguments)
        tool_calls.append(ToolCallRecord(name=str(tool_name), arguments=arguments, result=result))
        artifact = result.get("artifact")
        if isinstance(artifact, dict):
            artifacts.append(artifact)
        if result.get("error"):
            error = result["error"]
            warnings.append(str(error.get("message", "工具调用失败")))

        messages.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
        messages.append(
            {
                "role": "user",
                "content": "工具结果："
                + json.dumps(
                    {
                        "summary": result.get("summary"),
                        "meta": result.get("meta"),
                        "error": result.get("error"),
                        "artifact": result.get("artifact"),
                    },
                    ensure_ascii=False,
                    default=str,
                ),
            }
        )

    warnings.append("已达到工具调用轮数上限")
    fallback = "已达到查询轮数上限，以下为已获取的数据，请稍后继续提问。"
    return ChatResult(fallback, artifacts, tool_calls, warnings)
