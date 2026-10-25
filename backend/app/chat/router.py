from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.chat.dependencies import get_llm_router, get_mcp_client_factory
from app.chat.orchestrator import run_chat
from app.chat.safety import check_prompt_injection
from app.core.config import get_settings
from app.core.db import get_db_session, get_db_session_factory
from app.core.errors import ApiError
from app.core.http import client_ip
from app.core.rate_limit import RateLimiter
from app.core.redis import get_redis_client
from app.llm.providers import AllProvidersFailed
from steel_core.audit.service import write_audit
from steel_core.db.enums import MessageRole
from steel_core.db.models.accounts import ChatMessage, ChatSession, User

router = APIRouter(prefix="/api/chat", tags=["chat"])
logger = logging.getLogger("app.chat")


class ChatRequest(BaseModel):
    message: str
    session_id: UUID | None = None


class SessionCreate(BaseModel):
    title: str | None = None


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def _chunks(text: str, size: int = 40) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]


def _session_dict(session: ChatSession) -> dict[str, Any]:
    return {
        "id": str(session.id),
        "title": session.title,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


def _message_dict(message: ChatMessage) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "role": message.role.value,
        "content": message.content,
        "artifacts": message.artifacts,
        "tool_calls": message.tool_calls,
        "created_at": message.created_at.isoformat(),
    }


async def _owned_session(session: AsyncSession, *, session_id: UUID, user: User) -> ChatSession:
    chat_session = await session.get(ChatSession, session_id)
    if chat_session is None or chat_session.user_id != user.id:
        raise ApiError(404, "NOT_FOUND", "会话不存在")
    return chat_session


async def _history(session: AsyncSession, chat_session_id: UUID) -> list[dict[str, str]]:
    messages = list(
        (
            await session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.session_id == chat_session_id,
                    ChatMessage.role.in_([MessageRole.USER, MessageRole.ASSISTANT]),
                )
                .order_by(ChatMessage.created_at.desc())
                .limit(20)
            )
        ).all()
    )
    return [
        {"role": message.role.value, "content": message.content} for message in reversed(messages)
    ]


@router.post("/sessions", status_code=201)
async def create_session_endpoint(
    payload: SessionCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    chat_session = ChatSession(user_id=user.id, title=payload.title or "新会话")
    session.add(chat_session)
    await session.commit()
    return _session_dict(chat_session)


@router.get("/sessions")
async def list_sessions_endpoint(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    sessions = list(
        (
            await session.scalars(
                select(ChatSession)
                .where(ChatSession.user_id == user.id)
                .order_by(ChatSession.updated_at.desc())
                .limit(50)
            )
        ).all()
    )
    return [_session_dict(item) for item in sessions]


@router.get("/sessions/{session_id}/messages")
async def list_messages_endpoint(
    session_id: UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict[str, Any]]:
    chat_session = await _owned_session(session, session_id=session_id, user=user)
    messages = list(
        (
            await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == chat_session.id)
                .order_by(ChatMessage.created_at)
            )
        ).all()
    )
    return [_message_dict(message) for message in messages]


@router.post("/stream")
async def stream_endpoint(
    payload: ChatRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
    redis: Any | None = Depends(get_redis_client),
    llm: Any = Depends(get_llm_router),
    mcp_factory: Any = Depends(get_mcp_client_factory),
    session_factory: Any = Depends(get_db_session_factory),
) -> StreamingResponse:
    settings = get_settings()
    request_ip = client_ip(request)
    limiter = RateLimiter(redis)
    allowed = await limiter.allow(
        scope="chat",
        identifier=str(user.id),
        limit=20,
        window_seconds=60,
    )
    if not allowed:
        raise ApiError(429, "RATE_LIMITED", "对话请求过于频繁，请稍后再试")

    injection = check_prompt_injection(payload.message)
    if injection is not None:
        try:
            await write_audit(
                session,
                user_id=user.id,
                action="chat.prompt_injection",
                resource_type="chat",
                detail={"pattern": injection},
                ip=request_ip,
            )
            await session.commit()
        except Exception:  # noqa: BLE001
            logger.exception("prompt injection audit failed")
        raise ApiError(
            400,
            "PROMPT_INJECTION_BLOCKED",
            "输入包含不允许的指令，请只提问钢材行情相关问题",
        )

    if payload.session_id is not None:
        chat_session = await _owned_session(session, session_id=payload.session_id, user=user)
    else:
        chat_session = ChatSession(user_id=user.id, title=payload.message.strip()[:30] or "新会话")
        session.add(chat_session)
        await session.flush()

    history = await _history(session, chat_session.id)
    session.add(
        ChatMessage(
            session_id=chat_session.id,
            role=MessageRole.USER,
            content=payload.message,
        )
    )
    chat_session.updated_at = datetime.now(UTC)
    await session.commit()

    chat_session_id = chat_session.id

    async def event_stream() -> AsyncIterator[str]:
        yield _sse("session", {"session_id": str(chat_session_id)})
        try:
            async with mcp_factory(user) as mcp:
                result = await run_chat(
                    llm=llm,
                    mcp=mcp,
                    message=payload.message,
                    history=history,
                    max_rounds=settings.chat_max_tool_rounds,
                    max_calls=settings.chat_max_tool_calls,
                )
        except AllProvidersFailed:
            text = "服务暂时不可用，请稍后再试。"
            yield _sse("error", {"code": "UPSTREAM_ERROR", "message": text})
            await _persist_assistant(session_factory, chat_session_id, text, [], [])
            yield _sse("done", {"session_id": str(chat_session_id)})
            return
        except Exception:  # noqa: BLE001
            logger.exception("chat orchestration failed")
            text = "查询失败，请稍后再试。"
            yield _sse("error", {"code": "UPSTREAM_ERROR", "message": text})
            await _persist_assistant(session_factory, chat_session_id, text, [], [])
            yield _sse("done", {"session_id": str(chat_session_id)})
            return

        for artifact in result.artifacts:
            yield _sse("artifact", artifact)
        for warning in result.warnings:
            yield _sse("warning", {"message": warning})
        for chunk in _chunks(result.text):
            yield _sse("token", {"text": chunk})

        tool_calls = [
            {
                "name": record.name,
                "arguments": record.arguments,
                "result": record.result,
            }
            for record in result.tool_calls
        ]
        await _persist_assistant(
            session_factory, chat_session_id, result.text, result.artifacts, tool_calls
        )
        await _audit_tool_calls(session_factory, user.id, request_ip, tool_calls)
        yield _sse("done", {"session_id": str(chat_session_id)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _audit_tool_calls(
    factory: Any,
    user_id: UUID,
    ip: str | None,
    tool_calls: list[dict[str, Any]],
) -> None:
    if not tool_calls:
        return
    try:
        async with factory() as session:
            for call in tool_calls:
                result = call.get("result") or {}
                error = result.get("error") or {}
                await write_audit(
                    session,
                    user_id=user_id,
                    action="mcp.call",
                    resource_type="tool",
                    resource_id=str(call.get("name") or "")[:64],
                    detail={
                        "arguments": json.dumps(
                            call.get("arguments") or {}, ensure_ascii=False
                        )[:500],
                        "error_code": error.get("code") if isinstance(error, dict) else None,
                        "summary": str(result.get("summary") or "")[:200],
                    },
                    ip=ip,
                )
            await session.commit()
    except Exception:  # noqa: BLE001
        logger.exception("mcp audit failed")


async def _persist_assistant(
    factory: Any,
    chat_session_id: UUID,
    text: str,
    artifacts: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
) -> None:
    async with factory() as session:
        session.add(
            ChatMessage(
                session_id=chat_session_id,
                role=MessageRole.ASSISTANT,
                content=text,
                artifacts=artifacts or None,
                tool_calls=tool_calls or None,
            )
        )
        chat_session = await session.get(ChatSession, chat_session_id)
        if chat_session is not None:
            chat_session.updated_at = datetime.now(UTC)
        await session.commit()
