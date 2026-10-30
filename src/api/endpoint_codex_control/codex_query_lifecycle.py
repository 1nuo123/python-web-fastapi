"""HTTP 断开显式取消只读等待；Agent 最多完成原 deadline 内的一块。"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import Request
from pydantic import BaseModel
from starlette.responses import Response
from src.application.codex.read_codex_content_usecase import content_http_fault
from src.core.codex_contract.agent_content_contract import ContentErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode

T = TypeVar("T")


async def await_codex_query(request: Request, operation: Awaitable[T]) -> T:
    async def disconnected() -> None:
        while True:
            message = await request.receive()
            if message["type"] == "http.disconnect":
                return

    task = asyncio.ensure_future(operation)
    watcher = asyncio.create_task(disconnected())
    try:
        done, _ = await asyncio.wait((task, watcher), return_when=asyncio.FIRST_COMPLETED)
        if task in done:
            return task.result()
        raise HttpFaultException(
            status_code=499,
            error_code=CodexErrorCode.QUERY_CANCELLED,
            message="浏览器已取消Codex查询。",
        )
    finally:
        for pending in (task, watcher):
            if not pending.done():
                pending.cancel()
        await asyncio.gather(task, watcher, return_exceptions=True)


class _HttpQueryCapacity:
    def __init__(self) -> None:
        self.bytes = 0
        self.requests = 0


class _BoundedQueryResponse(Response):
    def __init__(self, payload: bytes, release: Callable[[], None]) -> None:
        super().__init__(
            content=payload, media_type="application/json", headers={"Cache-Control": "no-store"}
        )
        self._release = release

    async def __call__(self, scope, receive, send) -> None:
        try:
            async with asyncio.timeout(30):
                await super().__call__(scope, receive, send)
        finally:
            self._release()


async def bounded_codex_response(
    request: Request, *, max_bytes: int, operation: Callable[[], Awaitable[BaseModel]]
) -> Response:
    """从查询开始到HTTP发送结束持有全进程预算；实际发送量与计量使用同一编码。"""
    capacity = getattr(request.app.state, "codex_http_query_capacity", None)
    if capacity is None:
        capacity = _HttpQueryCapacity()
        request.app.state.codex_http_query_capacity = capacity
    if capacity.requests >= 128 or capacity.bytes + max_bytes > 16 * 1024 * 1024:
        raise content_http_fault(ContentErrorCode.OVERLOADED)
    capacity.bytes += max_bytes
    capacity.requests += 1
    released = False

    def release() -> None:
        nonlocal released
        if not released:
            released = True
            capacity.bytes -= max_bytes
            capacity.requests -= 1

    try:
        try:
            async with asyncio.timeout(30):
                envelope = await await_codex_query(request, operation())
        except TimeoutError as exc:
            raise content_http_fault(ContentErrorCode.TIMEOUT) from exc
        payload = envelope.model_dump_json().encode("utf-8")
        if len(payload) > max_bytes:
            raise content_http_fault(ContentErrorCode.MESSAGE_TOO_LARGE)
        return _BoundedQueryResponse(payload, release)
    except BaseException:
        release()
        raise
