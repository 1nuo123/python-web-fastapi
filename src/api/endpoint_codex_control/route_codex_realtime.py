"""Codex 浏览器一次性票据与长期产品事件 WebSocket。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from enum import StrEnum
from http import HTTPStatus
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Security, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import JsonValue
from starlette.websockets import WebSocketState

from src.api.dependency_context_accessor import DependencyContextAccessor
from src.core.codex_contract.realtime_event_contract import (
    CODEX_REALTIME_OPERATION_NAME,
    CodexRealtimeEvent,
    CodexRealtimeEventType,
    CodexRealtimeTicket,
    CodexRealtimeTicketSubject,
)
from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.response_envelope_contract import ResponseEnvelope
from src.core.stream_contract.stream_access_contract import StreamAccessTicketIssuedDetail
from src.core.stream_contract.stream_event_contract import StreamTransport
from src.domain.codex.codex_authorization_policy import CODEX_READ_AUTHORIZATION_REQUIREMENT
from src.domain.codex.codex_error_code import CodexErrorCode
from src.infrastructure.codex.codex_browser_event_hub import CodexBrowserSubscription
from src.infrastructure.codex.codex_control_runtime import CodexControlRuntime
from src.infrastructure.security.browser_origin_resolver import (
    build_allowed_browser_origins,
)
from src.infrastructure.shared_resource_mount import SharedResourceMount
from src.infrastructure.streaming.stream_session_registry import StreamSessionIdentity

CODEX_REALTIME_BEARER_SCHEME = HTTPBearer(auto_error=False)
CODEX_REALTIME_REJECTED_CLOSE_CODE = 4403
CODEX_REALTIME_ZERO_HOST_ID = UUID(int=0)


class CodexBrowserRealtimeSessionState(StrEnum):
    """浏览器实时连接的显式关闭状态。"""

    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class CodexBrowserRealtimeSession:
    """单写者驱动的浏览器实时连接生命周期。"""

    def __init__(
        self,
        *,
        websocket: WebSocket,
        subscription: CodexBrowserSubscription,
        runtime: CodexControlRuntime,
    ) -> None:
        self._websocket = websocket
        self._subscription = subscription
        self._runtime = runtime
        self._state = CodexBrowserRealtimeSessionState.OPEN
        self._state_lock = asyncio.Lock()
        self._stop_event = asyncio.Event()

    async def run(self) -> None:
        """运行单写者与断开监听，并完整回收两个任务。"""

        writer = asyncio.create_task(self._send_events())
        disconnect_waiter = asyncio.create_task(self._wait_for_disconnect())
        tasks = (writer, disconnect_waiter)
        failure: BaseException | None = None
        try:
            completed, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in completed:
                try:
                    task.result()
                except asyncio.CancelledError:
                    continue
                except WebSocketDisconnect:
                    continue
                except RuntimeError as exc:
                    if not self._is_disconnected():
                        failure = exc
                except BaseException as exc:
                    failure = exc
        finally:
            await self.close()
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            async with self._state_lock:
                self._state = CodexBrowserRealtimeSessionState.CLOSED
        if failure is not None:
            raise failure

    async def send_event(self, event: CodexRealtimeEvent) -> bool:
        """只在连接仍开放时由唯一写锁发送事件。"""

        async with self._state_lock:
            if self._state is not CodexBrowserRealtimeSessionState.OPEN:
                return False
            if self._is_disconnected():
                self._state = CodexBrowserRealtimeSessionState.CLOSING
                self._stop_event.set()
                return False
            try:
                await self._websocket.send_text(event.model_dump_json())
            except (WebSocketDisconnect, RuntimeError):
                if not self._is_disconnected():
                    raise
                self._state = CodexBrowserRealtimeSessionState.CLOSING
                self._stop_event.set()
                return False
            return True

    async def close(self) -> None:
        """幂等停止后续发送，不重复写 WebSocket close 帧。"""

        async with self._state_lock:
            if self._state is CodexBrowserRealtimeSessionState.CLOSED:
                return
            self._state = CodexBrowserRealtimeSessionState.CLOSING
            self._stop_event.set()

    async def _send_events(self) -> None:
        heartbeat_seconds = self._runtime.settings.agent_heartbeat_seconds
        while not self._stop_event.is_set():
            try:
                event = await asyncio.wait_for(
                    self._subscription.queue.get(),
                    timeout=heartbeat_seconds,
                )
            except TimeoutError:
                event = self._subscription.build_local_event(
                    event_type=CodexRealtimeEventType.CONNECTION_HEARTBEAT,
                    host_id=CODEX_REALTIME_ZERO_HOST_ID,
                    payload={"server_time": datetime.now(UTC).isoformat()},
                )
            if not await self.send_event(event):
                return

    async def _wait_for_disconnect(self) -> None:
        try:
            while not self._stop_event.is_set():
                await self._websocket.receive_text()
        finally:
            await self.close()

    def _is_disconnected(self) -> bool:
        return (
            self._websocket.client_state is WebSocketState.DISCONNECTED
            or self._websocket.application_state is WebSocketState.DISCONNECTED
        )


class CodexRealtimeRouteCatalog:
    """注册浏览器票据和只发送稳定产品事件的 WebSocket。"""

    def __init__(self) -> None:
        self._accessor = DependencyContextAccessor()
        self.router = APIRouter()
        self.router.add_api_route(
            "/codex/realtime-tickets",
            self.issue_ticket,
            methods=["POST"],
            response_model=ResponseEnvelope[CodexRealtimeTicket],
            dependencies=[Depends(self.require_codex_read)],
        )
        self.router.add_api_websocket_route("/codex/events", self.connect)

    async def require_codex_read(
        self,
        request: Request,
        _credentials: HTTPAuthorizationCredentials | None = Security(CODEX_REALTIME_BEARER_SCHEME),
    ) -> None:
        self._accessor.read_authorized_principal(request, CODEX_READ_AUTHORIZATION_REQUIREMENT)

    async def issue_ticket(self, request: Request) -> ResponseEnvelope[CodexRealtimeTicket]:
        """签发绑定主体与客户端地址的高熵一次性票据。"""

        if not self._origin_allowed(
            request.headers.get("origin"),
            self._allowed_origins(request),
        ):
            raise HttpFaultException(
                status_code=HTTPStatus.FORBIDDEN,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="Codex实时请求Origin不允许。",
            )
        principal = self._accessor.read_authenticated_principal(request)
        resource_mount = request.app.state.container.resource_mount
        runtime = self._read_runtime(resource_mount)
        client_ip = resource_mount.get_client_ip_resolver().resolve_client_ip(request)
        envelope = await runtime.stream_ticket_service.issue(
            subject_id=CodexRealtimeTicketSubject(
                owner_subject_id=principal.subject_id,
            ).encode(),
            operation_name=CODEX_REALTIME_OPERATION_NAME,
            client_ip=client_ip,
        )
        if not isinstance(envelope.detail, StreamAccessTicketIssuedDetail):
            raise RuntimeError("Codex实时票据签发未返回issued扩展。")
        ticket = CodexRealtimeTicket(
            ticket=envelope.detail.ticket,
            expires_at=envelope.detail.expires_at,
        )
        return self._accessor.read_response_factory(request).build(
            code=str(SuccessCode.OK),
            message="Codex实时票据签发成功。",
            request_scope=self._accessor.read_request_scope(request),
            data=ticket,
        )

    async def connect(
        self,
        websocket: WebSocket,
        ticket: str = Query(min_length=32, max_length=512),
        cursor: str | None = Query(default=None, max_length=512),
    ) -> None:
        """消费票据后建立主体固定、epoch 独立的长期连接。"""

        resource_mount = websocket.app.state.container.resource_mount
        runtime = self._read_runtime(resource_mount)
        client_ip = resource_mount.get_client_ip_resolver().resolve_client_ip(websocket)
        try:
            if not self._origin_allowed(
                websocket.headers.get("origin"),
                self._allowed_origins_from_mount(resource_mount, websocket),
            ):
                raise PermissionError("Codex实时连接Origin不允许。")
            record = await runtime.stream_ticket_service.consume_record(
                ticket=ticket,
                operation_name=CODEX_REALTIME_OPERATION_NAME,
                client_ip=client_ip,
            )
            if record is None:
                raise PermissionError("Codex实时票据无效或已消费。")
            ticket_subject = CodexRealtimeTicketSubject.decode(record.subject_id)
            subject_id = ticket_subject.owner_subject_id
            lease = await resource_mount.get_streaming_resources().session_registry.acquire(
                identity=StreamSessionIdentity(
                    subject_id=subject_id,
                    client_ip=client_ip,
                    operation_name=CODEX_REALTIME_OPERATION_NAME,
                    transport=StreamTransport.WEBSOCKET,
                )
            )
        except (PermissionError, RuntimeError, ValueError):
            await websocket.close(code=CODEX_REALTIME_REJECTED_CLOSE_CODE)
            return
        subscription = await runtime.browser_event_hub.subscribe(subject_id)
        await websocket.accept()
        session = CodexBrowserRealtimeSession(
            websocket=websocket,
            subscription=subscription,
            runtime=runtime,
        )
        try:
            replayed = await self._replay_cursor_events(
                session=session,
                subscription=subscription,
                runtime=runtime,
                cursor=cursor,
            )
            if not replayed:
                await self._enqueue_initial_events(websocket, subscription, runtime)
            await session.run()
        except WebSocketDisconnect:
            return
        finally:
            await session.close()
            await runtime.browser_event_hub.unsubscribe(subscription)
            await lease.release()

    async def _enqueue_initial_events(
        self,
        websocket: WebSocket,
        subscription: CodexBrowserSubscription,
        runtime: CodexControlRuntime,
    ) -> None:
        runtime.browser_event_hub.enqueue_local(
            subscription,
            event_type=CodexRealtimeEventType.CONNECTION_READY,
            host_id=CODEX_REALTIME_ZERO_HOST_ID,
            payload={
                "heartbeat_interval": runtime.settings.agent_heartbeat_seconds,
                "server_time": datetime.now(UTC).isoformat(),
            },
        )
        hosts, workspaces = await asyncio.to_thread(
            self._load_authority_snapshot,
            runtime,
            subscription.subject_id,
        )
        runtime.browser_event_hub.enqueue_local(
            subscription,
            event_type=CodexRealtimeEventType.HOST_SNAPSHOT,
            host_id=CODEX_REALTIME_ZERO_HOST_ID,
            payload={"hosts": hosts},
        )
        runtime.browser_event_hub.enqueue_local(
            subscription,
            event_type=CodexRealtimeEventType.WORKSPACE_SNAPSHOT,
            host_id=CODEX_REALTIME_ZERO_HOST_ID,
            payload={"workspaces": workspaces},
        )

    async def _replay_cursor_events(
        self,
        *,
        session: CodexBrowserRealtimeSession,
        subscription: CodexBrowserSubscription,
        runtime: CodexControlRuntime,
        cursor: str | None,
    ) -> bool:
        if cursor is None:
            return False
        window = await runtime.realtime_stream_adapter.read(
            owner_subject_id=subscription.subject_id,
            after_cursor=cursor,
            limit=runtime.settings.browser_replay_read_limit,
        )
        if window.gap:
            runtime.browser_event_hub.enqueue_local(
                subscription,
                event_type=CodexRealtimeEventType.STREAM_GAP_DETECTED,
                host_id=CODEX_REALTIME_ZERO_HOST_ID,
                payload={"reason": "cursor_trimmed", "snapshot_required": True},
            )
            return False
        for event_record, event_cursor in zip(window.events, window.cursors, strict=True):
            persisted_event = CodexRealtimeEvent.model_validate_json(event_record.payload)
            event = persisted_event.model_copy(
                update={
                    "header": persisted_event.header.model_copy(update={"cursor": event_cursor})
                }
            )
            if not await session.send_event(event):
                return True
        return True

    def _load_authority_snapshot(
        self,
        runtime: CodexControlRuntime,
        subject_id: str,
    ) -> tuple[list[JsonValue], list[JsonValue]]:
        unit_of_work = runtime.control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            hosts = runtime.control_port.create_codex_host_repository(session).list_by_owner(
                subject_id
            )
            workspace_repository = runtime.control_port.create_codex_workspace_repository(session)
            workspaces = [
                workspace
                for host in hosts
                for workspace in workspace_repository.list_by_host_and_owner(
                    host.host_id,
                    subject_id,
                )
            ]
            return (
                [cast(JsonValue, host.model_dump(mode="json")) for host in hosts],
                [cast(JsonValue, workspace.model_dump(mode="json")) for workspace in workspaces],
            )
        finally:
            unit_of_work.dispose()

    def _allowed_origins(self, request: Request) -> set[str]:
        resource_mount = request.app.state.container.resource_mount
        settings = resource_mount.read_runtime_bundle().settings
        return build_allowed_browser_origins(
            request,
            configured_origins=settings.runtime.stream.detail.allowed_origins,
            client_ip_resolver=resource_mount.get_client_ip_resolver(),
        )

    def _allowed_origins_from_mount(
        self,
        resource_mount: SharedResourceMount,
        websocket: WebSocket,
    ) -> set[str]:
        settings = resource_mount.read_runtime_bundle().settings
        return build_allowed_browser_origins(
            websocket,
            configured_origins=settings.runtime.stream.detail.allowed_origins,
            client_ip_resolver=resource_mount.get_client_ip_resolver(),
        )

    def _origin_allowed(self, origin: str | None, allowed_origins: set[str]) -> bool:
        return origin is not None and origin.rstrip("/") in {
            allowed.rstrip("/") for allowed in allowed_origins
        }

    def _read_runtime(self, resource_mount: SharedResourceMount) -> CodexControlRuntime:
        return resource_mount.get_codex_control_runtime()
