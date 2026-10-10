"""Codex Agent 长期 WebSocket 连接路由。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from fastapi import APIRouter, Query, Request, WebSocket, WebSocketDisconnect

from src.api.web_bundle_catalog import (
    WebBundleProvider,
    WebBundleProviderDetail,
    WebBundleProviderEnvelope,
    WebBundleProviderHeader,
)
from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_enrollment_contract import (
    CodexAgentCredentialResponse,
    CodexAgentEnrollRequest,
)
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentApprovalOpened,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
    CodexAgentHeartbeat,
    CodexAgentHello,
    CodexAgentRealtimeEvent,
    CodexAgentStateSnapshot,
)
from src.core.codex_contract.connection_session_contract import (
    CodexConnectionTransportClosed,
    CodexConnectionTransportPort,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.web_bundle_contract import ApplicationModuleName, WebBundle
from src.domain.codex.codex_compatibility_policy import CodexCompatibilityDecision
from src.domain.codex.codex_error_code import CodexErrorCode
from src.domain.codex.host_status import CodexHostStatus
from src.infrastructure.codex.agent_device_authentication import (
    AgentDeviceAuthenticationError,
)
from src.infrastructure.codex.codex_agent_gateway import (
    AgentApprovalObserver,
    AgentCommandAckObserver,
    AgentCommandResultObserver,
    AgentCompatibilityObserver,
    AgentDisconnectObserver,
    AgentEventBatchObserver,
    AgentEventObserver,
    AgentHeartbeatObserver,
    AgentHelloObserver,
    AgentSnapshotObserver,
    CodexAgentGatewayHandler,
)
from src.infrastructure.codex.codex_connection_session import (
    CodexConnectionSessionPolicy,
    CodexDuplexConnectionSession,
)
from src.infrastructure.codex.codex_control_runtime import CodexControlRuntime

CODEX_AGENT_ROUTE_TAG = "codex_agent_gateway"
AGENT_AUTHENTICATION_CLOSE_CODE = 4401


class FastApiAgentWebSocketTransport(CodexConnectionTransportPort):
    """FastAPI WebSocket 到长期双向会话传输端口的适配器。"""

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._disconnected = False
        self._close_sent = False

    async def receive_text(self) -> str:
        try:
            return await self._websocket.receive_text()
        except WebSocketDisconnect as exc:
            self._disconnected = True
            raise CodexConnectionTransportClosed("Agent WebSocket已关闭。") from exc

    async def send_text(self, payload: str) -> None:
        try:
            await self._websocket.send_text(payload)
        except (RuntimeError, WebSocketDisconnect) as exc:
            self._disconnected = True
            raise CodexConnectionTransportClosed("Agent WebSocket已关闭。") from exc

    async def close(self, *, code: int, reason: str) -> None:
        if self._close_sent:
            return
        self._close_sent = True
        try:
            await self._websocket.close(code=code, reason=reason)
        except RuntimeError:
            return


class CodexAgentConnectRouteCatalog:
    """设备认证边界内的 Agent WSS 路由。"""

    def __init__(self) -> None:
        self.router = APIRouter(tags=[CODEX_AGENT_ROUTE_TAG])
        self.router.add_api_websocket_route(
            "/internal/codex-agents/connect",
            self.connect,
        )
        self.router.add_api_route(
            "/internal/codex-agents/enroll",
            self.enroll,
            methods=["POST"],
            response_model=CodexAgentCredentialResponse,
        )
        self.router.add_api_route(
            "/internal/codex-agents/rotate-credential",
            self.rotate_credential,
            methods=["POST"],
            response_model=CodexAgentCredentialResponse,
        )

    async def enroll(
        self,
        request: Request,
        body: CodexAgentEnrollRequest,
    ) -> CodexAgentCredentialResponse:
        """用一次性配对码兑换设备凭据；响应中的 token 只出现一次。"""

        runtime = self._read_runtime(request)
        if not runtime.settings.allow_legacy_agent_bearer:
            raise HttpFaultException(
                status_code=410,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="旧版Agent bearer注册已经停用。",
            )
        try:
            credential_id, token = await asyncio.to_thread(
                runtime.pairing_service.enroll,
                pairing_code=body.pairing_code,
                host_id=body.host_id,
            )
        except ValueError as exc:
            raise HttpFaultException(
                status_code=409,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="Codex配对码无效、已使用或已过期。",
            ) from exc
        return CodexAgentCredentialResponse(
            credential_id=credential_id,
            device_token=token,
        )

    async def rotate_credential(self, request: Request) -> CodexAgentCredentialResponse:
        """只接受独立 CodexAgent scheme 的设备凭据轮换。"""

        runtime = self._read_runtime(request)
        if not runtime.settings.allow_legacy_agent_bearer:
            raise HttpFaultException(
                status_code=410,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="旧版Agent bearer轮换已经停用。",
            )
        try:
            principal = await asyncio.to_thread(
                runtime.authentication_guard.authenticate_http,
                request.headers,
            )
            credential_id, token = await asyncio.to_thread(
                runtime.pairing_service.rotate,
                principal,
            )
        except AgentDeviceAuthenticationError as exc:
            raise HttpFaultException(
                status_code=401,
                error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
                message="Agent设备凭据无效。",
            ) from exc
        except ValueError as exc:
            raise HttpFaultException(
                status_code=409,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="Agent设备凭据无法轮换。",
            ) from exc
        return CodexAgentCredentialResponse(
            credential_id=credential_id,
            device_token=token,
        )

    async def connect(
        self,
        websocket: WebSocket,
        ticket: str | None = Query(default=None, min_length=32, max_length=512),
    ) -> None:
        """在 accept 前消费一次性票据，再运行独立长期会话。"""

        runtime = self._read_runtime(websocket)
        try:
            if ticket is not None:
                principal = await runtime.consume_agent_connection_ticket.execute(
                    ticket=ticket,
                    client_ip=(websocket.client.host if websocket.client is not None else None),
                )
            elif runtime.settings.allow_legacy_agent_bearer:
                principal = await asyncio.to_thread(
                    runtime.authentication_guard.authenticate_websocket,
                    websocket.headers,
                )
            else:
                raise AgentDeviceAuthenticationError("缺少Agent一次性连接票据。")
        except (AgentDeviceAuthenticationError, PermissionError, ValueError):
            await websocket.close(code=AGENT_AUTHENTICATION_CLOSE_CODE)
            return
        revocation_generation = await runtime.revocation_signal.read_generation(
            UUID(principal.host_id)
        )
        await websocket.accept()
        shutdown_event = asyncio.Event()
        handler = CodexAgentGatewayHandler(
            principal=principal,
            connection_registry=runtime.connection_registry,
            actor_registry=runtime.actor_registry,
            compatibility_policy=runtime.compatibility_policy,
            heartbeat_seconds=runtime.settings.agent_heartbeat_seconds,
            revocation_generation=revocation_generation,
            event_cursor_store=runtime.event_cursor_store,
            presence_adapter=runtime.presence_adapter,
            active_host=runtime.active_host,
            instance_id=runtime.instance_id,
            revocation_signal=runtime.revocation_signal,
            shutdown_event=shutdown_event,
            hello_observer=self._build_hello_observer(runtime),
            heartbeat_observer=self._build_heartbeat_observer(runtime),
            snapshot_observer=self._build_snapshot_observer(runtime),
            command_ack_observer=self._build_command_ack_observer(runtime),
            command_result_observer=self._build_command_result_observer(runtime),
            event_observer=self._build_event_observer(runtime),
            event_batch_observer=self._build_event_batch_observer(runtime),
            approval_observer=self._build_approval_observer(runtime),
            disconnect_observer=self._build_disconnect_observer(runtime),
            compatibility_observer=self._build_compatibility_observer(runtime),
        )
        session = CodexDuplexConnectionSession(
            transport=FastApiAgentWebSocketTransport(websocket),
            inbound_handler=handler,
            policy=CodexConnectionSessionPolicy(
                outbound_queue_capacity=runtime.settings.agent_outgoing_queue_size,
                max_frame_bytes=runtime.settings.max_agent_frame_bytes,
                send_enqueue_timeout_seconds=1.0,
            ),
        )
        hello_watchdog = asyncio.create_task(
            self._stop_if_hello_missing(
                handler=handler,
                shutdown_event=shutdown_event,
                timeout_seconds=runtime.settings.agent_rpc_ack_timeout_seconds,
            )
        )
        try:
            await session.run(shutdown_event=shutdown_event)
        finally:
            hello_watchdog.cancel()
            await asyncio.gather(hello_watchdog, return_exceptions=True)
            await handler.close()

    async def _stop_if_hello_missing(
        self,
        *,
        handler: CodexAgentGatewayHandler,
        shutdown_event: asyncio.Event,
        timeout_seconds: int,
    ) -> None:
        """阻止通过设备认证但不发送 hello 的空闲连接占满容量。"""

        await asyncio.sleep(timeout_seconds)
        if handler.lease is None:
            shutdown_event.set()

    def _read_runtime(self, request: Request | WebSocket) -> CodexControlRuntime:
        """从应用组合根读取唯一 Codex 运行时。"""

        return cast(
            CodexControlRuntime,
            request.app.state.container.resource_mount.get_codex_control_runtime(),
        )

    def _build_hello_observer(self, runtime: CodexControlRuntime) -> AgentHelloObserver:
        async def observe(
            hello: CodexAgentHello,
            principal: AgentDevicePrincipal,
        ) -> None:
            await asyncio.to_thread(runtime.state_synchronizer.accept_hello, hello, principal)
            await runtime.publish_host_status_changed(
                owner_subject_id=principal.owner_subject_id,
                host_id=hello.host_id,
                status=CodexHostStatus.ONLINE.value,
                last_seen_at=datetime.now(UTC),
            )

        return observe

    def _build_heartbeat_observer(
        self,
        runtime: CodexControlRuntime,
    ) -> AgentHeartbeatObserver:
        async def observe(
            heartbeat: CodexAgentHeartbeat,
            principal: AgentDevicePrincipal,
        ) -> None:
            await asyncio.to_thread(
                runtime.state_synchronizer.accept_heartbeat,
                heartbeat,
                principal,
            )
            updated_threads = await runtime.turn_runtime_coordinator.renew_heartbeat_leases(
                heartbeat,
                principal,
            )
            for thread in updated_threads:
                await runtime.publish_thread_updated(
                    owner_subject_id=principal.owner_subject_id,
                    thread=thread,
                    occurred_at=heartbeat.sent_at,
                )

        return observe

    def _build_snapshot_observer(
        self,
        runtime: CodexControlRuntime,
    ) -> AgentSnapshotObserver:
        async def observe(
            snapshot: CodexAgentStateSnapshot,
            principal: AgentDevicePrincipal,
        ) -> None:
            await asyncio.to_thread(
                runtime.state_synchronizer.accept_snapshot,
                snapshot,
                principal,
            )

        return observe

    def _build_command_ack_observer(
        self,
        runtime: CodexControlRuntime,
    ) -> AgentCommandAckObserver:
        async def observe(
            ack: CodexAgentCommandAck,
            principal: AgentDevicePrincipal,
        ) -> None:
            applied_projection = await asyncio.to_thread(
                runtime.state_synchronizer.accept_command_ack,
                ack,
                principal,
            )
            if applied_projection is not None:
                await runtime.publish_thread_updated(
                    owner_subject_id=principal.owner_subject_id,
                    thread=applied_projection.thread,
                    occurred_at=applied_projection.occurred_at,
                )

        return observe

    def _build_command_result_observer(
        self,
        runtime: CodexControlRuntime,
    ) -> AgentCommandResultObserver:
        async def observe(
            result: CodexAgentCommandResult,
            principal: AgentDevicePrincipal,
        ) -> None:
            applied_projection = await asyncio.to_thread(
                runtime.state_synchronizer.accept_command_result,
                result,
                principal,
            )
            if applied_projection is not None:
                await runtime.publish_thread_updated(
                    owner_subject_id=principal.owner_subject_id,
                    thread=applied_projection.thread,
                    occurred_at=applied_projection.occurred_at,
                )

        return observe

    def _build_event_observer(self, runtime: CodexControlRuntime) -> AgentEventObserver:
        async def observe(
            event: CodexAgentRealtimeEvent,
            principal: AgentDevicePrincipal,
        ) -> None:
            await runtime.publish_agent_event(event, principal)

        return observe

    def _build_event_batch_observer(
        self,
        runtime: CodexControlRuntime,
    ) -> AgentEventBatchObserver:
        """保留 Agent v2 的批次边界，避免网关展开后逐条广播。"""

        async def observe(
            events: tuple[CodexAgentRealtimeEvent, ...],
            principal: AgentDevicePrincipal,
        ) -> None:
            await runtime.publish_agent_events(events, principal)

        return observe

    def _build_approval_observer(
        self,
        runtime: CodexControlRuntime,
    ) -> AgentApprovalObserver:
        async def observe(
            approval: CodexAgentApprovalOpened,
            principal: AgentDevicePrincipal,
        ) -> None:
            await runtime.publish_approval_opened(approval, principal)

        return observe

    def _build_disconnect_observer(
        self,
        runtime: CodexControlRuntime,
    ) -> AgentDisconnectObserver:
        async def observe(
            host_id: UUID,
            principal: AgentDevicePrincipal,
            connection_started_at: datetime,
        ) -> None:
            if await runtime.connection_registry.read(host_id) is not None:
                return
            host = await asyncio.to_thread(
                runtime.state_synchronizer.accept_disconnect,
                host_id,
                principal,
                connection_started_at,
            )
            if host is None:
                return
            await runtime.publish_host_status_changed(
                owner_subject_id=principal.owner_subject_id,
                host_id=host_id,
                status=CodexHostStatus.OFFLINE.value,
                last_seen_at=None,
            )

        return observe

    def _build_compatibility_observer(
        self,
        runtime: CodexControlRuntime,
    ) -> AgentCompatibilityObserver:
        async def observe(
            host_id: UUID,
            principal: AgentDevicePrincipal,
            decision: CodexCompatibilityDecision,
        ) -> None:
            await asyncio.to_thread(
                runtime.state_synchronizer.accept_compatibility,
                host_id,
                principal,
                decision,
            )

        return observe


class CodexAgentGatewayBundleProvider(WebBundleProvider):
    """Codex Agent 设备认证模块提供者。"""

    module_name = ApplicationModuleName.CODEX_AGENT_GATEWAY.value

    def provide(self) -> WebBundleProviderEnvelope:
        return WebBundleProviderEnvelope(
            header=WebBundleProviderHeader(module_name=self.module_name),
            detail=WebBundleProviderDetail(provider_name=self.__class__.__name__),
            bundle=WebBundle(
                module_name=self.module_name,
                router=CodexAgentConnectRouteCatalog().router,
            ),
        )
