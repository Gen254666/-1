from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID

from steel_core.db.enums import Role


class ToolError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class UserContext:
    user_id: UUID
    role: Role


user_context_var: ContextVar[UserContext | None] = ContextVar("mcp_user_context", default=None)


def require_context() -> UserContext:
    context = user_context_var.get()
    if context is None:
        raise ToolError("AUTH_TOKEN_INVALID", "缺少用户上下文")
    return context
