from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp_server import tools
from mcp_server.auth import ServiceTokenError, decode_service_token
from mcp_server.context import ToolError, require_context, user_context_var
from mcp_server.db import mcp_session
from mcp_server.tools import _error

mcp = FastMCP(
    "steel-market",
    instructions="钢材行情查询、价差、异动、库存、报价与日报工具",
    host="127.0.0.1",
    port=8001,
    stateless_http=True,
)


def _context() -> Any:
    try:
        return require_context()
    except ToolError as exc:
        return _error(exc.code, exc.message)


def _parse_uuids(values: list[str] | None) -> list[UUID] | None:
    if values is None:
        return None
    return [UUID(value) for value in values]


@mcp.tool()
async def get_meta(category: str | None = None) -> dict[str, Any]:
    ctx = _context()
    if isinstance(ctx, dict):
        return ctx
    async with mcp_session() as session:
        return await tools.get_meta(session, ctx, category=category)


@mcp.tool()
async def get_quotes(
    point_ids: list[str] | None = None,
    category: str | None = None,
    region: str | None = None,
    quote_date: date | None = None,
    page: int = 1,
    page_size: int = 20,
    use_cache: bool = True,
) -> dict[str, Any]:
    ctx = _context()
    if isinstance(ctx, dict):
        return ctx
    try:
        parsed_ids = _parse_uuids(point_ids)
    except ValueError:
        return _error("INVALID_ARGUMENT", "point_ids 包含非法 UUID")
    async with mcp_session() as session:
        return await tools.get_quotes(
            session,
            ctx,
            point_ids=parsed_ids,
            category=category,
            region=region,
            quote_date=quote_date,
            page=page,
            page_size=page_size,
            use_cache=use_cache,
        )


@mcp.tool()
async def get_price_history(
    point_ids: list[str],
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    ctx = _context()
    if isinstance(ctx, dict):
        return ctx
    try:
        parsed_ids = [UUID(value) for value in point_ids]
    except ValueError:
        return _error("INVALID_ARGUMENT", "point_ids 包含非法 UUID")
    async with mcp_session() as session:
        return await tools.get_price_history(
            session,
            ctx,
            point_ids=parsed_ids,
            start_date=start_date,
            end_date=end_date,
        )


@mcp.tool()
async def compare_spread(
    left_point_id: str,
    right_point_id: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    ctx = _context()
    if isinstance(ctx, dict):
        return ctx
    try:
        left = UUID(left_point_id)
        right = UUID(right_point_id)
    except ValueError:
        return _error("INVALID_ARGUMENT", "point_id 不是合法 UUID")
    async with mcp_session() as session:
        return await tools.compare_spread(
            session,
            ctx,
            left_point_id=left,
            right_point_id=right,
            start_date=start_date,
            end_date=end_date,
        )


@mcp.tool()
async def scan_anomalies(
    quote_date: date | None = None,
    category: str | None = None,
) -> dict[str, Any]:
    ctx = _context()
    if isinstance(ctx, dict):
        return ctx
    async with mcp_session() as session:
        return await tools.scan_anomalies_tool(
            session, ctx, quote_date=quote_date, category=category
        )


@mcp.tool()
async def get_inventory(
    snapshot_date: date | None = None,
    category: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    ctx = _context()
    if isinstance(ctx, dict):
        return ctx
    async with mcp_session() as session:
        return await tools.get_inventory(
            session,
            ctx,
            snapshot_date=snapshot_date,
            category=category,
            page=page,
            page_size=page_size,
        )


@mcp.tool()
async def generate_quote(
    pieces: int,
    point_id: str | None = None,
    spec: str | None = None,
    freight: Decimal = Decimal("0"),
    processing_fee: Decimal = Decimal("0"),
    tax_mode: str = "as_is",
) -> dict[str, Any]:
    ctx = _context()
    if isinstance(ctx, dict):
        return ctx
    parsed_point: UUID | None = None
    if point_id is not None:
        try:
            parsed_point = UUID(point_id)
        except ValueError:
            return _error("INVALID_ARGUMENT", "point_id 不是合法 UUID")
    async with mcp_session() as session:
        return await tools.generate_quote_tool(
            session,
            ctx,
            pieces=pieces,
            point_id=parsed_point,
            spec=spec,
            freight=freight,
            processing_fee=processing_fee,
            tax_mode=tax_mode,
        )


@mcp.tool()
async def get_daily_report(report_date: date) -> dict[str, Any]:
    ctx = _context()
    if isinstance(ctx, dict):
        return ctx
    async with mcp_session() as session:
        return await tools.get_daily_report(session, ctx, report_date=report_date)


@mcp.tool()
async def generate_daily_report(report_date: date | None = None) -> dict[str, Any]:
    ctx = _context()
    if isinstance(ctx, dict):
        return ctx
    async with mcp_session() as session:
        return await tools.generate_daily_report(session, ctx, report_date=report_date)


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


class ServiceAuthMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if path in {"/healthz", "/readyz"}:
            await self.app(scope, receive, send)
            return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        authorization = headers.get("authorization", "")
        if not authorization.startswith("Bearer "):
            await _send_error(scope, receive, send, 401, "AUTH_TOKEN_INVALID", "缺少服务令牌")
            return

        try:
            context = decode_service_token(authorization.removeprefix("Bearer ").strip())
        except ServiceTokenError as exc:
            await _send_error(scope, receive, send, 401, str(exc), "服务令牌无效")
            return

        token = user_context_var.set(context)
        try:
            await self.app(scope, receive, send)
        finally:
            user_context_var.reset(token)


async def _send_error(
    scope: Any,
    receive: Any,
    send: Any,
    status_code: int,
    code: str,
    message: str,
) -> None:
    response = JSONResponse({"code": code, "message": message}, status_code=status_code)
    await response(scope, receive, send)


app = ServiceAuthMiddleware(mcp.streamable_http_app())
