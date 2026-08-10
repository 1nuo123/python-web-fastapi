"""Codex 浏览器一次性票据与长期产品事件 WebSocket。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from http import HTTPStatus
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Security, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import JsonValue

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
from src.infrastructure.shared_resource_mount import SharedResourceMount
from src.infrastructure.streaming.stream_session_registry import StreamSessionIdentity

CODEX_REALTIME_BEARER_SCHEME = HTTPBearer(auto_error=False)
CODEX_REALTIME_REJECTED_CLOSE_CODE = 4403
CODEX_REALTIME_ZERO_HOST_ID = UUID(int=0)


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
        runtime = self._read_runtime(request.app.state.container.resource_mount)
        envelope = await runtime.stream_ticket_service.issue(
            subject_id=CodexRealtimeTicketSubject(
                owner_subject_id=principal.subject_id,
            ).encode(),
            operation_name=CODEX_REALTIME_OPERATION_NAME,
            client_ip=self._client_ip(request.client.host if request.client else None),
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
        try:
            if not self._origin_allowed(
                websocket.headers.get("origin"),
                self._allowed_origins_from_mount(resource_mount, websocket),
            ):
                raise PermissionError("Codex实时连接Origin不允许。")
            record = await runtime.stream_ticket_service.consume_record(
                ticket=ticket,
                operation_name=CODEX_REALTIME_OPERATION_NAME,
                client_ip=self._client_ip(websocket.client.host if websocket.client else None),
            )
            if record is None:
                raise PermissionError("Codex实时票据无效或已消费。")
            ticket_subject = CodexRealtimeTicketSubject.decode(record.subject_id)
            subject_id = ticket_subject.owner_subject_id
            lease = await resource_mount.get_streaming_resources().session_registry.acquire(
                identity=StreamSessionIdentity(
                    subject_id=subject_id,
                    client_ip=self._client_ip(websocket.client.host if websocket.client else None),
                    operation_name=CODEX_REALTIME_OPERATION_NAME,
                    transport=StreamTransport.WEBSOCKET,
                )
            )
        except (PermissionError, RuntimeError, ValueError):
            await websocket.close(code=CODEX_REALTIME_REJECTED_CLOSE_CODE)
            return
        subscription = await runtime.browser_event_hub.subscribe(subject_id)
        await websocket.accept()
        try:
            replayed = await self._replay_cursor_events(
                websocket=websocket,
                subscription=subscription,
                runtime=runtime,
                cursor=cursor,
            )
            if not replayed:
                await self._enqueue_initial_events(websocket, subscription, runtime)
            await self._serve_events(websocket, subscription, runtime)
        except WebSocketDisconnect:
            return
        finally:
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

    async def _send_events(
        self,
        websocket: WebSocket,
        subscription: CodexBrowserSubscription,
        runtime: CodexControlRuntime,
    ) -> None:
        heartbeat_seconds = runtime.settings.agent_heartbeat_seconds
        while True:
            try:
                event = await asyncio.wait_for(
                    subscription.queue.get(),
                    timeout=heartbeat_seconds,
                )
            except TimeoutError:
                event = subscription.build_local_event(
                    event_type=CodexRealtimeEventType.CONNECTION_HEARTBEAT,
                    host_id=CODEX_REALTIME_ZERO_HOST_ID,
                    payload={"server_time": datetime.now(UTC).isoformat()},
                )
            await websocket.send_text(event.model_dump_json())

    async def _replay_cursor_events(
        self,
        *,
        websocket: WebSocket,
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
            event = CodexRealtimeEvent.model_validate_json(event_record.payload).model_copy(
                update={"cursor": event_cursor}
            )
            await websocket.send_text(event.model_dump_json())
        return True

    async def _serve_events(
        self,
        websocket: WebSocket,
        subscription: CodexBrowserSubscription,
        runtime: CodexControlRuntime,
    ) -> None:
        tasks = {
            asyncio.create_task(self._send_events(websocket, subscription, runtime)),
            asyncio.create_task(self._wait_for_disconnect(websocket)),
        }
        try:
            completed, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in completed:
                task.result()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _wait_for_disconnect(self, websocket: WebSocket) -> None:
        while True:
            await websocket.receive_text()

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
        expected = f"{request.url.scheme}://{request.url.netloc}"
        settings = request.app.state.container.resource_mount.read_runtime_bundle().settings
        return {expected, *settings.runtime.web.cors.allow_origins}

    def _allowed_origins_from_mount(
        self,
        resource_mount: SharedResourceMount,
        websocket: WebSocket,
    ) -> set[str]:
        settings = resource_mount.read_runtime_bundle().settings
        expected = f"{websocket.url.scheme.replace('ws', 'http')}://{websocket.url.netloc}"
        return {expected, *settings.runtime.web.cors.allow_origins}

    def _origin_allowed(self, origin: str | None, allowed_origins: set[str]) -> bool:
        return origin is not None and origin.rstrip("/") in {
            allowed.rstrip("/") for allowed in allowed_origins
        }

    def _read_runtime(self, resource_mount: SharedResourceMount) -> CodexControlRuntime:
        return resource_mount.get_codex_control_runtime()

    def _client_ip(self, value: str | None) -> str:
        return value or "unknown"
