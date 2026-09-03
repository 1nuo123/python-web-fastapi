"""Codex App Server stdio JSON-RPC 客户端。"""

from __future__ import annotations

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Final, cast

from pydantic import JsonValue, ValidationError

from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerClientStoppedError,
    AppServerLineReaderPort,
    AppServerLineWriterPort,
    AppServerMessageTooLargeError,
    AppServerOverloadBudgetExceededError,
    AppServerProtocolError,
    AppServerProtocolMessage,
    AppServerRpcError,
    AppServerUnknownOutcomeError,
    JsonRpcId,
    PendingAppServerRequest,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerDefaultCatalog,
    AppServerMethodEffect,
    AppServerMethodPolicy,
    AppServerNotificationName,
)

APP_SERVER_JSONRPC_VERSION: Final = "2.0"
APP_SERVER_OVERLOAD_ERROR_CODE: Final = -32001
APP_SERVER_OVERLOAD_MAX_ATTEMPTS: Final = 3
APP_SERVER_OVERLOAD_BASE_DELAY_SECONDS: Final = 0.1
APP_SERVER_OVERLOAD_MAX_DELAY_SECONDS: Final = 0.8
APP_SERVER_OVERLOAD_JITTER_RATIO: Final = 0.2
SUPPORTED_NOTIFICATION_NAMES: Final = frozenset(
    notification.value for notification in AppServerNotificationName
)
DEFAULT_INITIALIZE_PARAMS: Final[dict[str, JsonValue]] = {
    "clientInfo": {"name": "codex-remote-agent", "title": "Codex Remote Agent", "version": "1.0"},
    "capabilities": None,
}

AppServerNotificationHandler = Callable[[str, JsonValue], Awaitable[None]]
AppServerRequestHandler = Callable[[JsonRpcId, str, JsonValue], Awaitable[None]]
AppServerWarningHandler = Callable[[str], Awaitable[None]]


class BoundedAppServerLineReader:
    """在固定内存边界内读取 JSONL，并消费掉超限行后继续服务。"""

    def __init__(self, reader: asyncio.StreamReader, *, max_line_bytes: int) -> None:
        if max_line_bytes <= 0:
            raise ValueError("App Server单行上限必须大于零。")
        self._reader = reader
        self._max_line_bytes = max_line_bytes

    async def readline(self) -> bytes:
        """读取一行；超限时丢弃到换行符并返回容量异常。"""

        try:
            line = await self._reader.readuntil(b"\n")
        except asyncio.LimitOverrunError as exc:
            await self._discard_oversized_line(exc.consumed)
            raise AppServerMessageTooLargeError(self._max_line_bytes) from exc
        except asyncio.IncompleteReadError as exc:
            if len(exc.partial) > self._max_line_bytes:
                raise AppServerMessageTooLargeError(self._max_line_bytes) from exc
            return exc.partial
        if len(line) > self._max_line_bytes:
            raise AppServerMessageTooLargeError(self._max_line_bytes)
        return line

    async def _discard_oversized_line(self, consumed_bytes: int) -> None:
        """分段消费当前超限行，不在内存中拼接正文。"""

        if consumed_bytes > 0:
            await self._reader.readexactly(consumed_bytes)
        while True:
            try:
                await self._reader.readuntil(b"\n")
                return
            except asyncio.LimitOverrunError as exc:
                if exc.consumed > 0:
                    await self._reader.readexactly(exc.consumed)
            except asyncio.IncompleteReadError:
                return


class AppServerJsonRpcClient:
    """关联乱序响应，并独立分发通知和 App Server 主动请求。"""

    def __init__(
        self,
        *,
        reader: AppServerLineReaderPort,
        writer: AppServerLineWriterPort,
        max_line_bytes: int,
        notification_handler: AppServerNotificationHandler,
        request_handler: AppServerRequestHandler,
        warning_handler: AppServerWarningHandler,
        method_catalog: tuple[AppServerMethodPolicy, ...] | None = None,
    ) -> None:
        if max_line_bytes <= 0:
            raise ValueError("App Server单行上限必须大于零。")
        self._reader = reader
        self._writer = writer
        self._max_line_bytes = max_line_bytes
        self._notification_handler = notification_handler
        self._request_handler = request_handler
        self._warning_handler = warning_handler
        catalog = method_catalog or AppServerDefaultCatalog().build_method_catalog()
        self._method_catalog = {policy.method.value: policy for policy in catalog}
        self._write_lock = asyncio.Lock()
        self._pending: dict[JsonRpcId, asyncio.Future[JsonValue]] = {}
        self._pending_metadata: dict[JsonRpcId, PendingAppServerRequest] = {}
        self._next_request_id = 1
        self._reader_task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        """返回 stdout 读取循环是否仍运行。"""

        return self._reader_task is not None and not self._reader_task.done()

    async def start(self) -> None:
        """启动唯一 stdout 读取循环。"""

        if self.running:
            raise RuntimeError("App Server JSON-RPC客户端已经运行。")
        self._reader_task = asyncio.create_task(self._read_loop())

    async def initialize(self, *, timeout_seconds: float = 10.0) -> JsonValue:
        """完成 initialize 请求和 initialized notification。"""

        result = await self.request(
            "initialize",
            DEFAULT_INITIALIZE_PARAMS,
            timeout_seconds=timeout_seconds,
        )
        await self.notify("initialized", None)
        return result

    async def request(
        self,
        method: str,
        params: JsonValue,
        *,
        timeout_seconds: float,
        operation_id: str | None = None,
    ) -> JsonValue:
        """发送请求并按 id 等待对应的乱序响应。"""

        if timeout_seconds <= 0:
            raise ValueError("RPC超时必须大于零。")
        policy = self._method_catalog.get(method)
        if policy is None:
            raise AppServerProtocolError("App Server方法不在已审核method catalog中。")
        deadline = time.monotonic() + timeout_seconds
        attempt = 0
        while True:
            attempt += 1
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                raise self._build_deadline_error(method, operation_id, policy)
            try:
                return await self._request_once(
                    method,
                    params,
                    timeout_seconds=remaining_seconds,
                    operation_id=operation_id,
                )
            except AppServerRpcError as exc:
                if exc.error.code != APP_SERVER_OVERLOAD_ERROR_CODE:
                    raise
                if not policy.retry_on_overload:
                    raise AppServerOverloadBudgetExceededError(method) from exc
                if attempt >= APP_SERVER_OVERLOAD_MAX_ATTEMPTS:
                    raise AppServerOverloadBudgetExceededError(method) from exc
                await self._wait_for_overload_retry(attempt, deadline)
            except TimeoutError as exc:
                raise self._build_deadline_error(method, operation_id, policy) from exc

    async def _request_once(
        self,
        method: str,
        params: JsonValue,
        *,
        timeout_seconds: float,
        operation_id: str | None,
    ) -> JsonValue:
        """发送一次 JSON-RPC；是否重试由外层 method policy 决定。"""

        if not self.running:
            raise AppServerClientStoppedError("App Server JSON-RPC客户端尚未运行。")
        if timeout_seconds <= 0:
            raise ValueError("RPC超时必须大于零。")
        request_id = self._next_request_id
        self._next_request_id += 1
        future = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        self._pending_metadata[request_id] = PendingAppServerRequest(
            method=method,
            operation_id=operation_id,
        )
        try:
            await self._write_message(
                {
                    "jsonrpc": APP_SERVER_JSONRPC_VERSION,
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            return await asyncio.wait_for(future, timeout=timeout_seconds)
        finally:
            self._pending.pop(request_id, None)
            self._pending_metadata.pop(request_id, None)

    def _build_deadline_error(
        self,
        method: str,
        operation_id: str | None,
        policy: AppServerMethodPolicy,
    ) -> TimeoutError:
        """mutation 超时返回 unknown outcome，读取超时保持普通 deadline。"""

        if policy.effect == AppServerMethodEffect.MUTATION:
            return AppServerUnknownOutcomeError(method, operation_id)
        return TimeoutError(f"App Server方法{method}超过deadline。")

    async def _wait_for_overload_retry(self, attempt: int, deadline: float) -> None:
        """执行带 jitter 的有界指数退避，不越过整体 deadline。"""

        base_delay = min(
            APP_SERVER_OVERLOAD_BASE_DELAY_SECONDS * (2 ** (attempt - 1)),
            APP_SERVER_OVERLOAD_MAX_DELAY_SECONDS,
        )
        jitter = random.uniform(
            -APP_SERVER_OVERLOAD_JITTER_RATIO,
            APP_SERVER_OVERLOAD_JITTER_RATIO,
        )
        delay = max(0.0, base_delay * (1.0 + jitter))
        remaining_seconds = deadline - time.monotonic()
        if delay >= remaining_seconds:
            raise TimeoutError("App Server过载退避将超过整体deadline。")
        await asyncio.sleep(delay)

    async def notify(self, method: str, params: JsonValue) -> None:
        """发送不期待响应的客户端 notification。"""

        message: dict[str, JsonValue] = {
            "jsonrpc": APP_SERVER_JSONRPC_VERSION,
            "method": method,
        }
        if params is not None:
            message["params"] = params
        await self._write_message(message)

    async def reply(self, request_id: JsonRpcId, result: JsonValue) -> None:
        """用 App Server 原始 request id 回复审批等主动请求。"""

        await self._write_message(
            {"jsonrpc": APP_SERVER_JSONRPC_VERSION, "id": request_id, "result": result}
        )

    async def reply_error(self, request_id: JsonRpcId, *, code: int, message: str) -> None:
        """拒绝 Agent 不支持的 App Server 主动请求，避免上游永久等待。"""

        await self._write_message(
            {
                "jsonrpc": APP_SERVER_JSONRPC_VERSION,
                "id": request_id,
                "error": {"code": code, "message": message},
            }
        )

    async def close(self) -> None:
        """停止读取循环并使所有 pending RPC 明确失败。"""

        task = self._reader_task
        self._reader_task = None
        if task is not None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self._fail_pending(ConnectionError("App Server JSON-RPC客户端已关闭。"))

    async def wait_stopped(self) -> None:
        """等待 stdout 读取循环结束，并向监督器传播协议失败。"""

        task = self._reader_task
        if task is None:
            raise RuntimeError("App Server JSON-RPC客户端尚未启动。")
        await asyncio.shield(task)

    async def _read_loop(self) -> None:
        """逐行解析并按 JSON-RPC 方向分派。"""

        try:
            while True:
                try:
                    line = await self._reader.readline()
                except AppServerMessageTooLargeError as exc:
                    await self._reject_oversized_message(exc)
                    continue
                if not line:
                    raise ConnectionError("App Server stdout已关闭。")
                if len(line) > self._max_line_bytes:
                    await self._reject_oversized_message(
                        AppServerMessageTooLargeError(self._max_line_bytes)
                    )
                    continue
                message = self._parse_message(line)
                await self._route_message(message)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:
            self._fail_pending(exc)
            raise

    async def _reject_oversized_message(self, error: AppServerMessageTooLargeError) -> None:
        """使无法关联的在途请求失败，并保持后续 JSON-RPC 可读取。"""

        self._fail_pending(error)
        await self._warning_handler("App Server单条输出超过4 MiB，已省略该消息，连接继续可用。")

    async def _route_message(self, message: AppServerProtocolMessage) -> None:
        """区分 response、notification 与 server request。"""

        fields = message.model_fields_set
        if message.id is not None and ("result" in fields or message.error is not None):
            await self._resolve_response(message)
            return
        if message.method is not None and message.id is not None:
            await self._request_handler(message.id, message.method, message.params)
            return
        if message.method is not None:
            if message.method not in SUPPORTED_NOTIFICATION_NAMES:
                await self._warning_handler(
                    "App Server收到未审核notification，已拒绝进入产品事件流。"
                )
                return
            await self._notification_handler(message.method, message.params)
            return
        raise AppServerProtocolError("无法识别App Server JSON-RPC消息方向。")

    async def _resolve_response(self, message: AppServerProtocolMessage) -> None:
        """完成对应 future；未知 id 只产生协议告警。"""

        if message.id is None:
            raise AppServerProtocolError("JSON-RPC响应缺少id。")
        future = self._pending.get(message.id)
        if future is None:
            await self._warning_handler("App Server返回未知或已超时的RPC id。")
            return
        if message.error is not None:
            future.set_exception(AppServerRpcError(message.error))
            return
        future.set_result(message.result)

    def _parse_message(self, line: bytes) -> AppServerProtocolMessage:
        """解析 JSON 对象并拒绝数组、标量及未知顶层字段。"""

        try:
            payload = cast(object, json.loads(line))
            if not isinstance(payload, Mapping):
                raise AppServerProtocolError("App Server JSON-RPC消息必须是对象。")
            normalized = dict(cast(Mapping[str, object], payload))
            normalized.pop("jsonrpc", None)
            return AppServerProtocolMessage.model_validate(normalized)
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError) as exc:
            raise AppServerProtocolError("App Server输出不是有效JSON-RPC消息。") from exc

    async def _write_message(self, message: Mapping[str, JsonValue]) -> None:
        """通过单写者锁发送紧凑 JSONL。"""

        payload = (
            json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        )
        async with self._write_lock:
            self._writer.write(payload)
            await self._writer.drain()

    def _fail_pending(self, error: BaseException) -> None:
        """让所有未完成调用可诊断地收敛。"""

        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
