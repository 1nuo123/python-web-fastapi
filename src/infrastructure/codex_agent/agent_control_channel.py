"""Windows Agent 到 FastAPI 的主动出站 WSS 主链路。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import PureWindowsPath
from typing import Final, Literal, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from httpx import HTTPStatusError, TransportError
from pydantic import BaseModel, JsonValue
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from src.application.ports.agent_connection_ticket_provider_port import (
    AgentConnectionTicketProviderPort,
)
from src.core.codex_contract.agent_diagnostic_contract import (
    AgentDiagnosticCode,
    AgentDiagnosticEnvelope,
    AgentDiagnosticHeader,
    AgentProtocolWarningDiagnosticDetail,
)
from src.core.codex_contract.agent_protocol_contract import (
    CODEX_AGENT_PROTOCOL_VERSION,
    CodexAgentApprovalOpened,
    CodexAgentCommand,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
    CodexAgentHeartbeat,
    CodexAgentHello,
    CodexAgentHelloAck,
    CodexAgentRealtimeEvent,
)
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentApprovalDisplaySummary,
    AgentApprovalOpenedEventDetail,
    AgentCommandAckV2Detail,
    AgentCommandResultPayload,
    AgentCommandResultReference,
    AgentCommandResultV2Detail,
    AgentCommandV2Detail,
    AgentDiffChangedEventDetail,
    AgentEventAckV2Detail,
    AgentEventBatchV2Detail,
    AgentEventDetail,
    AgentEventRecord,
    AgentGapEventDetail,
    AgentHeartbeatV2Detail,
    AgentHelloAckV2Detail,
    AgentHelloV2Detail,
    AgentItemChangedEventDetail,
    AgentItemDeltaEventDetail,
    AgentPendingApprovalSnapshot,
    AgentPlanChangedEventDetail,
    AgentProtocolWarningEventDetail,
    AgentReplayRequestV2Detail,
    AgentThreadChangedEventDetail,
    AgentThreadMetadataChangedEventDetail,
    AgentThreadReadCommandResult,
    AgentTurnChangedEventDetail,
)
from src.core.codex_contract.app_server_jsonrpc_contract import JsonRpcId
from src.core.codex_contract.app_server_product_contract import (
    AppServerDiffChangedDetail,
    AppServerItemChangedDetail,
    AppServerItemDeltaDetail,
    AppServerPlanChangedDetail,
    AppServerProductNotificationDetail,
    AppServerThreadChangedDetail,
    AppServerThreadMetadataChangedDetail,
    AppServerTurnChangedDetail,
    AppServerWarningDetail,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerDefaultCatalog,
    AppServerNotificationName,
)
from src.core.codex_contract.approval_contract import (
    CodexApprovalCommandAction,
    CodexApprovalDecision,
    CodexApprovalFileChange,
    CodexApprovalKind,
    CodexApprovalRiskLevel,
)
from src.core.codex_contract.connection_session_contract import (
    CodexConnectionFrame,
    CodexConnectionProtocolVersion,
    CodexConnectionTransportClosed,
    CodexConnectionTransportPort,
    CodexOutboundFrameSenderPort,
)
from src.core.codex_contract.host_contract import CodexApprovalPolicy
from src.domain.codex.agent_command_policy import (
    AgentAppServerSecurityPolicy,
    AgentCommandPolicy,
    read_upstream_identifiers,
)
from src.infrastructure.codex.agent_protocol_codec import (
    AgentCommandV2Mapper,
    AgentProtocolCodecRegistry,
    AgentV1MessageType,
)
from src.infrastructure.codex.codex_connection_session import (
    CodexConnectionSessionPolicy,
    CodexDuplexConnectionSession,
)
from src.infrastructure.codex_agent.agent_command_executor import AgentCommandExecutor
from src.infrastructure.codex_agent.agent_command_journal import AgentCommandJournal
from src.infrastructure.codex_agent.agent_configuration import (
    CodexHostAgentSettings,
    build_agent_tls_context,
)
from src.infrastructure.codex_agent.agent_event_batcher import AgentEventBatcher
from src.infrastructure.codex_agent.agent_event_replay_buffer import (
    AgentBufferedEvent,
    AgentEventReplayBuffer,
)
from src.infrastructure.codex_agent.agent_execution_root_store import AgentExecutionRootStore
from src.infrastructure.codex_agent.agent_secret_store import AgentSecretStorePort
from src.infrastructure.codex_agent.agent_snapshot_builder import AgentSnapshotBuilder
from src.infrastructure.codex_agent.agent_thread_history_capacity_registry import (
    AgentThreadHistoryCapacityRegistry,
)
from src.infrastructure.codex_agent.agent_thread_history_window_cache import (
    AgentThreadHistoryWindowCache,
)
from src.infrastructure.codex_agent.agent_workspace_registry import AgentWorkspaceRegistry
from src.infrastructure.codex_agent.app_server_process_supervisor import (
    AppServerProcessHandle,
    AppServerProcessSupervisor,
)
from src.infrastructure.codex_agent.app_server_protocol_adapter import AppServerProtocolAdapter
from src.infrastructure.worktree.git_worktree_adapter import GitWorktreeAdapter

_SYSTEM_RANDOM = secrets.SystemRandom()

INTERNAL_PROTOCOL_WARNING_METHOD = "internal/protocol.warning"
UNRESOLVED_WORKSPACE_KEY = "unresolved"
RETRYABLE_AGENT_HANDSHAKE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})
RETRY_AFTER_HEADER_NAME: Final = "Retry-After"
AGENT_HELLO_ACK_TIMEOUT_SECONDS: Final = 10.0
AGENT_SEND_ENQUEUE_TIMEOUT_SECONDS: Final = 1.0
AGENT_RETRY_MIN_WAIT_SECONDS: Final = 0.01
AGENT_METADATA_REFRESH_DEBOUNCE_SECONDS: Final = 0.2
AGENT_METADATA_REFRESH_TIMEOUT_SECONDS: Final = 10.0


class AgentControlConnectionPolicy:
    """控制面握手失败分类与退避策略。"""

    @staticmethod
    def should_retry(exc: BaseException) -> bool:
        """判断连接失败是否允许按退避策略重试。"""

        if isinstance(exc, InvalidStatus):
            status_code = AgentControlConnectionPolicy.read_status_code(exc)
            return status_code is None or status_code in RETRYABLE_AGENT_HANDSHAKE_STATUS_CODES
        if isinstance(exc, HTTPStatusError):
            return exc.response.status_code in RETRYABLE_AGENT_HANDSHAKE_STATUS_CODES
        if isinstance(exc, InvalidHandshake):
            return True
        return isinstance(
            exc,
            (ConnectionError, OSError, TimeoutError, TransportError, ValueError),
        )

    @staticmethod
    def describe(exc: BaseException) -> str:
        """生成不含凭据的稳定连接失败摘要。"""

        status_code = AgentControlConnectionPolicy.read_status_code(exc)
        if status_code is not None:
            return f"HTTP {status_code}"
        return type(exc).__name__

    @staticmethod
    def read_status_code(exc: BaseException) -> int | None:
        """兼容不同 websockets 版本读取握手状态码。"""

        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if isinstance(status_code, int):
            return status_code
        legacy_status_code = getattr(exc, "status_code", None)
        if isinstance(legacy_status_code, int):
            return legacy_status_code
        return None

    @staticmethod
    def read_retry_after_seconds(exc: BaseException) -> int | None:
        """读取服务端返回的秒级 Retry-After，非法值按未提供处理。"""

        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if headers is None:
            return None
        raw_value = headers.get(RETRY_AFTER_HEADER_NAME)
        if not isinstance(raw_value, str):
            return None
        try:
            seconds = int(raw_value)
        except ValueError:
            return None
        return seconds if seconds > 0 else None


class AgentEventCursorRegressionError(ConnectionError):
    """控制面累计 ACK 丢失，当前 Agent 必须轮换事件 epoch。"""


class AgentWebSocketTransport(CodexConnectionTransportPort):
    """websockets 16 客户端到长期会话传输端口的适配器。"""

    def __init__(self, connection: ClientConnection) -> None:
        self._connection = connection

    async def receive_text(self) -> str:
        """只接受产品协议文本帧。"""

        try:
            payload = await self._connection.recv()
        except ConnectionClosed as exc:
            raise CodexConnectionTransportClosed("控制面WebSocket已关闭。") from exc
        if not isinstance(payload, str):
            raise ValueError("Agent控制通道不接受二进制帧。")
        return payload

    async def send_text(self, payload: str) -> None:
        """发送一个完整产品协议文本帧。"""

        try:
            await self._connection.send(payload)
        except ConnectionClosed as exc:
            raise CodexConnectionTransportClosed("控制面WebSocket已关闭。") from exc

    async def close(self, *, code: int, reason: str) -> None:
        """关闭 WebSocket 客户端连接。"""

        await self._connection.close(code=code, reason=reason)


@dataclass(frozen=True, slots=True)
class PendingAgentApproval:
    """只在当前 App Server 代次有效的审批 RPC 关联。"""

    request_id: JsonRpcId
    approval_id: UUID
    method: str
    app_server_instance_id: str
    approval_kind: Literal["command", "file_change", "permissions"]
    thread_id: str
    turn_id: str
    item_id: str
    payload_digest: str
    display: AgentApprovalDisplaySummary
    expires_at: datetime
    requested_permissions: JsonValue | None = None
    proposed_execpolicy_amendment: tuple[str, ...] = ()
    proposed_network_policy_amendments: tuple[dict[str, JsonValue], ...] = ()


class AgentControlChannel:
    """保持 App Server 独立存活，并在控制面断线时重连和有界缓冲。"""

    def __init__(
        self,
        *,
        settings: CodexHostAgentSettings,
        secret_store: AgentSecretStorePort,
        connection_ticket_provider: AgentConnectionTicketProviderPort | None,
        workspace_registry: AgentWorkspaceRegistry,
        journal: AgentCommandJournal,
        logger: logging.Logger,
    ) -> None:
        self._settings = settings
        self._tls_context = build_agent_tls_context(
            deployment_profile=settings.agent.deployment_profile,
            development_ca_certificate_path=settings.agent.development_ca_certificate_path,
        )
        self._secret_store = secret_store
        self._connection_ticket_provider = connection_ticket_provider
        self._workspace_registry = workspace_registry
        self._worktree_port = GitWorktreeAdapter(workspace_registry)
        self._execution_root_store = AgentExecutionRootStore.from_state_directory(
            settings.agent.state_database.parent
        )
        self._journal = journal
        self._logger = logger
        self._protocol_version = settings.protocol.agent_schema_version
        self._protocol_codec = AgentProtocolCodecRegistry()
        self._command_mapper = AgentCommandV2Mapper()
        self._shutdown_event = asyncio.Event()
        self._active_sender: CodexOutboundFrameSenderPort | None = None
        self._connection_epoch: int | None = None
        self._revocation_generation = 0
        self._hello_ack_event = asyncio.Event()
        self._event_epoch, self._event_ack = self._journal.read_event_ack()
        self._event_buffer = AgentEventReplayBuffer(capacity=settings.agent.max_buffered_events)
        self._event_batcher = self._build_event_batcher()
        self._batch_flush_task: asyncio.Task[None] | None = None
        self._metadata_refresh_tasks: dict[str, asyncio.Task[None]] = {}
        self._pending_approvals: dict[UUID, PendingAgentApproval] = {}
        self._history_capacity_registry = AgentThreadHistoryCapacityRegistry(
            max_source_bytes=settings.agent.max_app_server_line_bytes
        )
        self._history_window_cache = AgentThreadHistoryWindowCache()
        self._app_server_protocol_adapter = AppServerProtocolAdapter()
        self._supervisor = AppServerProcessSupervisor(
            codex_binary=settings.agent.codex_binary,
            allowed_versions=[settings.protocol.expected_codex_version],
            max_line_bytes=settings.agent.max_app_server_line_bytes,
            notification_handler=self._accept_app_server_notification,
            request_handler=self._accept_app_server_request,
            warning_handler=self._accept_protocol_warning,
            logger=logger,
            host_id=str(settings.agent.host_id),
        )

    async def run(self) -> None:
        """启动 App Server 一次，并在控制面 WSS 失败时指数退避重连。"""

        handle = await self._supervisor.start()
        legacy_token = self._read_legacy_token()
        delay = self._settings.agent.reconnect_min_seconds
        try:
            while not self._shutdown_event.is_set():
                try:
                    if handle.process.returncode is not None or not handle.client.running:
                        # 新 App Server 代次不继承旧进程的实时事件序列，必须丢弃正文窗口。
                        self._history_window_cache.clear()
                        handle = await self._supervisor.restart()
                    await self._run_connection(handle, legacy_token)
                    delay = self._settings.agent.reconnect_min_seconds
                except asyncio.CancelledError:
                    raise
                except (
                    ConnectionError,
                    OSError,
                    TimeoutError,
                    HTTPStatusError,
                    TransportError,
                    ValueError,
                    InvalidHandshake,
                ) as exc:
                    if self._shutdown_event.is_set():
                        break
                    if not AgentControlConnectionPolicy.should_retry(exc):
                        self._logger.error(
                            "Agent控制通道握手被拒绝，请重新注册主机或检查设备凭据：%s",
                            AgentControlConnectionPolicy.describe(exc),
                        )
                        raise
                    self._logger.warning("Agent控制通道连接失败，将重试：%s", exc)
                    try:
                        jitter = delay * self._settings.agent.reconnect_jitter_ratio
                        retry_after_seconds = (
                            AgentControlConnectionPolicy.read_retry_after_seconds(exc) or 0
                        )
                        wait_seconds = max(
                            AGENT_RETRY_MIN_WAIT_SECONDS,
                            delay + _SYSTEM_RANDOM.uniform(-jitter, jitter),
                            retry_after_seconds,
                        )
                        await asyncio.wait_for(
                            self._shutdown_event.wait(),
                            timeout=wait_seconds,
                        )
                    except TimeoutError:
                        delay = min(delay * 2, self._settings.agent.reconnect_max_seconds)
        finally:
            self._active_sender = None
            if self._batch_flush_task is not None:
                self._batch_flush_task.cancel()
                await asyncio.gather(self._batch_flush_task, return_exceptions=True)
                self._batch_flush_task = None
            for task in self._metadata_refresh_tasks.values():
                task.cancel()
            await asyncio.gather(
                *self._metadata_refresh_tasks.values(),
                return_exceptions=True,
            )
            self._metadata_refresh_tasks.clear()
            self._history_window_cache.clear()
            await self._supervisor.stop()

    def request_shutdown(self) -> None:
        """请求停止新连接与新命令。"""

        self._shutdown_event.set()

    def _raise_if_connection_closed_unexpectedly(self) -> None:
        """把非停机导致的正常关闭转换为可退避重试的连接异常。"""

        if self._shutdown_event.is_set():
            return
        raise CodexConnectionTransportClosed("控制面WebSocket连接意外关闭，Agent将按退避策略重连。")

    async def _run_connection(
        self,
        handle: AppServerProcessHandle,
        legacy_token: str | None,
    ) -> None:
        """运行一个控制面连接代次，断线不停止本地 App Server。"""

        connection_url, headers = await self._build_connection_request(legacy_token)
        # websockets rejects an explicit ``ssl=None`` for wss:// URLs. The
        # default system trust store is selected by omitting the argument;
        # development profiles may still provide an explicit SSLContext.
        if self._tls_context is not None:
            connection_context = connect(
                connection_url,
                additional_headers=headers,
                max_size=self._settings.agent.max_app_server_line_bytes,
                ping_interval=None,
                ssl=self._tls_context,
            )
        else:
            connection_context = connect(
                connection_url,
                additional_headers=headers,
                max_size=self._settings.agent.max_app_server_line_bytes,
                ping_interval=None,
            )
        async with connection_context as connection:
            session = CodexDuplexConnectionSession(
                transport=AgentWebSocketTransport(connection),
                inbound_handler=self._handle_control_frame,
                policy=CodexConnectionSessionPolicy(
                    outbound_queue_capacity=self._settings.agent.writer_queue_capacity,
                    max_frame_bytes=self._settings.agent.max_app_server_line_bytes,
                    send_enqueue_timeout_seconds=AGENT_SEND_ENQUEUE_TIMEOUT_SECONDS,
                ),
            )
            self._hello_ack_event.clear()
            self._connection_epoch = None
            session_task = asyncio.create_task(session.run(shutdown_event=self._shutdown_event))
            await asyncio.sleep(0)
            self._active_sender = session
            heartbeat_task: asyncio.Task[None] | None = None
            process_wait_task = asyncio.create_task(handle.process.wait())
            client_wait_task = asyncio.create_task(handle.client.wait_stopped())
            try:
                await self._require_active_session(session_task)
                await session.send(self._build_hello_frame(handle))
                await self._wait_for_hello_ack(session_task)
                await self._require_active_session(session_task)
                await self._send_snapshot(handle, session)
                await self._require_active_session(session_task)
                await self._flush_buffer(session)
                heartbeat_task = asyncio.create_task(self._heartbeat_loop(handle, session))
                done, _ = await asyncio.wait(
                    (session_task, process_wait_task, client_wait_task),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if process_wait_task in done:
                    raise ConnectionError("Codex App Server进程异常退出。")
                if client_wait_task in done:
                    await client_wait_task
                    raise ConnectionError("Codex App Server JSON-RPC读取循环停止。")
                await session_task
                self._raise_if_connection_closed_unexpectedly()
            finally:
                if heartbeat_task is not None:
                    if not heartbeat_task.done():
                        heartbeat_task.cancel()
                    await asyncio.gather(heartbeat_task, return_exceptions=True)
                self._active_sender = None
                connection_tasks = (session_task, process_wait_task, client_wait_task)
                for task in connection_tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*connection_tasks, return_exceptions=True)

    async def _wait_for_hello_ack(self, session_task: asyncio.Task[None]) -> None:
        """等待握手确认，同时立即感知已经结束的连接会话。"""

        hello_ack_task = asyncio.create_task(self._hello_ack_event.wait())
        try:
            done, _ = await asyncio.wait(
                (session_task, hello_ack_task),
                timeout=AGENT_HELLO_ACK_TIMEOUT_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if session_task in done:
                await self._require_active_session(session_task)
            if hello_ack_task not in done:
                raise TimeoutError("等待控制面hello_ack超时。")
            await hello_ack_task
        finally:
            if not hello_ack_task.done():
                hello_ack_task.cancel()
            await asyncio.gather(hello_ack_task, return_exceptions=True)

    async def _require_active_session(self, session_task: asyncio.Task[None]) -> None:
        """拒绝向已经提前结束的控制面连接继续发送。"""

        if not session_task.done():
            return
        await session_task
        raise CodexConnectionTransportClosed("控制面WebSocket会话已提前结束。")

    async def _handle_control_frame(
        self,
        frame: CodexConnectionFrame,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        """处理 hello_ack 和稳定 command。"""

        decoded = self._protocol_codec.decode(frame)
        if decoded.protocol_version != self._protocol_version:
            raise ValueError("控制面响应协议版本与Agent配置不一致。")
        if decoded.v1 is not None and decoded.v1.message_type == AgentV1MessageType.HELLO_ACK:
            if not isinstance(decoded.v1.payload, CodexAgentHelloAck):
                raise ValueError("控制面v1 hello_ack结构错误。")
            v1_ack = decoded.v1.payload
            if v1_ack.host_id != self._settings.agent.host_id:
                raise PermissionError("hello_ack的host_id不匹配。")
            self._connection_epoch = v1_ack.connection_epoch
            self._hello_ack_event.set()
            return
        if decoded.v2 is not None and isinstance(decoded.v2.detail, AgentHelloAckV2Detail):
            self._verify_v2_control_host(decoded.v2.header.host_id)
            v2_ack = decoded.v2.detail
            self._connection_epoch = v2_ack.connection_epoch
            self._revocation_generation = v2_ack.revocation_generation
            if v2_ack.acknowledged_event_epoch == self._event_epoch:
                if v2_ack.after_seq < self._event_ack:
                    await self._rotate_event_epoch()
                    raise AgentEventCursorRegressionError(
                        "控制面事件ACK游标回退，Agent已经轮换事件epoch并准备重连。"
                    )
                self._journal.write_event_ack(
                    epoch=self._event_epoch,
                    after_seq=v2_ack.after_seq,
                )
                self._event_ack = v2_ack.after_seq
                self._event_buffer.discard_acknowledged(
                    epoch=self._event_epoch,
                    after_seq=v2_ack.after_seq,
                )
            self._hello_ack_event.set()
            return
        if not self._hello_ack_event.is_set():
            raise ValueError("控制面在hello_ack之前发送了业务消息。")
        if decoded.v2 is not None and isinstance(decoded.v2.detail, AgentEventAckV2Detail):
            self._accept_event_ack(decoded.v2.detail)
            return
        if decoded.v2 is not None and isinstance(decoded.v2.detail, AgentReplayRequestV2Detail):
            await self._replay_v2_events(decoded.v2.detail, sender)
            return
        if decoded.v1 is not None:
            if decoded.v1.message_type != AgentV1MessageType.COMMAND or not isinstance(
                decoded.v1.payload, CodexAgentCommand
            ):
                raise ValueError("控制面发送了不受支持的Agent v1消息。")
            command = decoded.v1.payload
        elif decoded.v2 is not None and isinstance(decoded.v2.detail, AgentCommandV2Detail):
            self._verify_v2_control_host(decoded.v2.header.host_id)
            command = self._command_mapper.to_v1_command(
                host_id=self._settings.agent.host_id,
                command=decoded.v2.detail,
            )
        else:
            raise ValueError("控制面发送了不受支持的Agent消息。")
        if command.host_id != self._settings.agent.host_id:
            raise PermissionError("控制面命令host_id与本机Agent不匹配。")
        executor = AgentCommandExecutor(
            journal=self._journal,
            client=self._supervisor.handle.client,
            command_policy=AgentCommandPolicy(
                self._workspace_registry,
                self._resolve_command_security_policy(command),
            ),
            ack_sender=lambda ack: self._send_command_ack(sender, ack),
            result_sender=lambda result: self._send_command_result(
                sender,
                result,
                command.command_type,
            ),
            approval_reply_handler=self._reply_approval,
            history_capacity_registry=self._history_capacity_registry,
            history_window_cache=self._history_window_cache,
            worktree_port=self._worktree_port,
            execution_root_store=self._execution_root_store,
            workspace_registry=self._workspace_registry,
        )
        await executor.execute(command)
        if command.command_type in {"thread.start", "thread.resume"}:
            await self._send_snapshot(self._supervisor.handle, sender)

    def _resolve_command_security_policy(
        self,
        command: CodexAgentCommand,
    ) -> AgentAppServerSecurityPolicy:
        """从具体命令参数构建本次 App Server 安全策略。"""

        local_policy = self._settings.app_server_security.to_policy()
        if command.command_type not in {"thread.start", "turn.start"}:
            return local_policy
        if command.sandbox_mode is None or command.approval_policy is None:
            raise PermissionError("Agent命令缺少用户确认的执行限制。")
        if command.approval_policy == CodexApprovalPolicy.NEVER:
            raise PermissionError("Agent不支持禁用审批的远程命令。")
        return AgentAppServerSecurityPolicy(
            approval_policy=cast(
                Literal["untrusted", "on-request"],
                command.approval_policy.value,
            ),
            approvals_reviewer=local_policy.approvals_reviewer,
            sandbox_mode=command.sandbox_mode.value,
        )

    async def _send_snapshot(
        self,
        handle: AppServerProcessHandle,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        builder = AgentSnapshotBuilder(
            host_id=self._settings.agent.host_id,
            workspace_registry=self._workspace_registry,
            client=handle.client,
            app_server_instance_id=handle.instance_id,
            journal=self._journal,
            history_capacity_registry=self._history_capacity_registry,
        )
        if self._protocol_version == CodexConnectionProtocolVersion.V2:
            v2_snapshot = await builder.build_v2(
                page_index=0,
                page_size=self._settings.agent.snapshot_page_size,
                pending_approvals=self._build_pending_approval_snapshots(),
            )
            await sender.send(
                self._protocol_codec.encode_v2(
                    host_id=self._settings.agent.host_id,
                    key_id=self._settings.agent.key_id,
                    message_id=uuid4(),
                    detail=v2_snapshot,
                )
            )
            return
        v1_snapshot = await builder.build()
        await self._send_model(sender, AgentV1MessageType.STATE_SNAPSHOT.value, v1_snapshot)

    async def _heartbeat_loop(
        self,
        handle: AppServerProcessHandle,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        """按 hello_ack 连接代次发送应用层心跳。"""

        while True:
            await asyncio.sleep(self._settings.agent.heartbeat_seconds)
            epoch = self._connection_epoch
            if epoch is None:
                raise RuntimeError("Agent心跳缺少连接代次。")
            heartbeat = CodexAgentHeartbeat(
                host_id=self._settings.agent.host_id,
                connection_epoch=epoch,
                app_server_instance_id=handle.instance_id,
                sent_at=datetime.now(UTC),
            )
            if self._protocol_version == CodexConnectionProtocolVersion.V2:
                await sender.send(
                    self._protocol_codec.encode_v2(
                        host_id=self._settings.agent.host_id,
                        key_id=self._settings.agent.key_id,
                        message_id=uuid4(),
                        detail=AgentHeartbeatV2Detail(
                            connection_epoch=epoch,
                            app_server_instance_id=UUID(handle.instance_id),
                            revocation_generation=self._revocation_generation,
                        ),
                    )
                )
            else:
                await self._send_model(sender, AgentV1MessageType.HEARTBEAT.value, heartbeat)

    def _build_hello_frame(self, handle: AppServerProcessHandle) -> CodexConnectionFrame:
        if self._protocol_version == CodexConnectionProtocolVersion.V2:
            return self._protocol_codec.encode_v2(
                host_id=self._settings.agent.host_id,
                key_id=self._settings.agent.key_id,
                message_id=uuid4(),
                detail=AgentHelloV2Detail(
                    agent_version=self._settings.protocol.agent_version,
                    codex_version=handle.codex_version,
                    app_server_schema_digest=self._settings.protocol.app_server_schema_digest,
                    capabilities=AppServerDefaultCatalog().build_capabilities(),
                    model_ids=(),
                    reasoning_efforts=(),
                    agent_event_epoch=self._event_epoch,
                ),
            )
        hello = CodexAgentHello(
            host_id=self._settings.agent.host_id,
            agent_version=self._settings.protocol.agent_version,
            codex_version=handle.codex_version,
            agent_protocol_version=CODEX_AGENT_PROTOCOL_VERSION,
            app_server_schema_digest=self._settings.protocol.app_server_schema_digest,
            capabilities={
                "thread": ["list", "read", "start", "resume"],
                "turn": ["start", "steer", "interrupt"],
                "experimentalApi": self._settings.protocol.allow_experimental_api,
            },
        )
        return self._protocol_codec.encode_v1(
            AgentV1MessageType.HELLO,
            hello,
        )

    async def _accept_app_server_notification(self, method: str, params: JsonValue) -> None:
        adapted = self._app_server_protocol_adapter.adapt_notification(method=method, params=params)
        if adapted.notification is not None:
            self._invalidate_history_window_for_notification(adapted.notification.detail)
        if self._protocol_version == CodexConnectionProtocolVersion.V2:
            if adapted.notification is None:
                detail: AgentEventDetail = AgentProtocolWarningEventDetail(
                    reason_code=(
                        adapted.warning_reason.value
                        if adapted.warning_reason is not None
                        else "malformed_payload"
                    ),
                    method=adapted.warning_method or method,
                )
            else:
                detail = self._map_product_notification(adapted.notification.detail, method)
            await self._queue_v2_event(detail)
            if (
                isinstance(detail, AgentTurnChangedEventDetail)
                and detail.method is AppServerNotificationName.TURN_COMPLETED
            ):
                self._schedule_metadata_refresh(detail.thread_id)
            return
        if adapted.notification is not None:
            event_method = method
            event_params: JsonValue = {}
            product_notification = adapted.notification
        else:
            event_method = INTERNAL_PROTOCOL_WARNING_METHOD
            event_params = {
                "reason_code": adapted.warning_reason.value
                if adapted.warning_reason is not None
                else "malformed_payload",
                "method": adapted.warning_method or method,
            }
            product_notification = None
        event = CodexAgentRealtimeEvent(
            host_id=self._settings.agent.host_id,
            app_server_instance_id=self._supervisor.handle.instance_id,
            occurred_at=datetime.now(UTC),
            method=event_method,
            params=event_params,
            product_notification=product_notification,
        )
        await self._send_or_buffer(self._build_model_frame("realtime.event", event))

    def _invalidate_history_window_for_notification(
        self,
        detail: AppServerProductNotificationDetail,
    ) -> None:
        """上游线程变更到达时删除完整历史缓存，避免流式增量被旧窗口覆盖。"""

        if isinstance(detail, AppServerThreadChangedDetail):
            thread_id = detail.thread.thread_id
        elif isinstance(
            detail,
            (
                AppServerThreadMetadataChangedDetail,
                AppServerTurnChangedDetail,
                AppServerItemChangedDetail,
                AppServerItemDeltaDetail,
                AppServerPlanChangedDetail,
                AppServerDiffChangedDetail,
            ),
        ):
            thread_id = detail.thread_id
        else:
            return
        self._history_window_cache.invalidate_thread(thread_id)

    def _schedule_metadata_refresh(self, thread_id: str) -> None:
        """按会话合并 turn 完成后的权威元数据刷新。"""

        existing = self._metadata_refresh_tasks.get(thread_id)
        if existing is not None and not existing.done():
            return
        task = asyncio.create_task(self._refresh_thread_metadata(thread_id))
        self._metadata_refresh_tasks[thread_id] = task

    async def _refresh_thread_metadata(self, thread_id: str) -> None:
        """从 App Server 校准标题和 recencyAt，不读取会话正文。"""

        try:
            await asyncio.sleep(AGENT_METADATA_REFRESH_DEBOUNCE_SECONDS)
            result = await self._supervisor.handle.client.request(
                "thread/read",
                {"threadId": thread_id, "includeTurns": False},
                timeout_seconds=AGENT_METADATA_REFRESH_TIMEOUT_SECONDS,
            )
            snapshot = self._app_server_protocol_adapter.adapt_thread_read_result(result)
            await self._queue_v2_event(
                AgentThreadChangedEventDetail(
                    method=AppServerNotificationName.THREAD_STATUS_CHANGED,
                    thread=snapshot.thread,
                )
            )
        except asyncio.CancelledError:
            raise
        except (ConnectionError, RuntimeError, TimeoutError, ValueError):
            self._logger.warning(
                "Agent会话权威元数据刷新失败：thread_id=%s",
                thread_id,
            )
        finally:
            current = self._metadata_refresh_tasks.get(thread_id)
            if current is asyncio.current_task():
                self._metadata_refresh_tasks.pop(thread_id, None)

    async def _accept_app_server_request(
        self,
        request_id: JsonRpcId,
        method: str,
        params: JsonValue,
    ) -> None:
        """把支持的审批收窄并绑定当前进程代次，拒绝未知请求。"""

        approval_kinds = {
            "item/commandExecution/requestApproval": "command",
            "item/fileChange/requestApproval": "file_change",
            "item/permissions/requestApproval": "permissions",
        }
        approval_kind = approval_kinds.get(method)
        if approval_kind is None or not isinstance(params, Mapping):
            await self._supervisor.handle.client.reply_error(
                request_id,
                code=-32601,
                message="Codex Remote Agent不支持该主动请求。",
            )
            return
        mapping = cast(Mapping[str, JsonValue], params)
        thread_id = mapping.get("threadId")
        turn_id = mapping.get("turnId")
        item_id = mapping.get("itemId")
        if not all(isinstance(value, str) and value for value in (thread_id, turn_id, item_id)):
            await self._supervisor.handle.client.reply_error(
                request_id,
                code=-32602,
                message="审批请求缺少稳定定位字段。",
            )
            return
        instance_id = self._supervisor.handle.instance_id
        approval_id = uuid5(NAMESPACE_URL, f"{instance_id}:{request_id}:{method}")
        expires_at = datetime.now(UTC) + timedelta(minutes=5)
        canonical = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        reason = mapping.get("reason")
        risk_level: Literal["normal", "high"] = (
            "high"
            if approval_kind == "permissions"
            or mapping.get("networkApprovalContext") is not None
            or mapping.get("grantRoot") is not None
            else "normal"
        )
        display = self._build_approval_display(
            mapping=mapping,
            approval_kind=approval_kind,
            risk_level=risk_level,
            reason=reason,
        )
        proposed_execpolicy_amendment = self._read_execpolicy_amendment(mapping)
        proposed_network_policy_amendments = self._read_network_policy_amendments(mapping)
        self._pending_approvals[approval_id] = PendingAgentApproval(
            request_id=request_id,
            approval_id=approval_id,
            method=method,
            app_server_instance_id=instance_id,
            approval_kind=cast(Literal["command", "file_change", "permissions"], approval_kind),
            thread_id=cast(str, thread_id),
            turn_id=cast(str, turn_id),
            item_id=cast(str, item_id),
            payload_digest=payload_digest,
            display=display,
            expires_at=expires_at,
            requested_permissions=(
                mapping.get("permissions") if approval_kind == "permissions" else None
            ),
            proposed_execpolicy_amendment=proposed_execpolicy_amendment,
            proposed_network_policy_amendments=proposed_network_policy_amendments,
        )
        approval = CodexAgentApprovalOpened(
            approval_id=approval_id,
            host_id=self._settings.agent.host_id,
            app_server_instance_id=instance_id,
            approval_kind=CodexApprovalKind(approval_kind),
            thread_id=cast(str, thread_id),
            turn_id=cast(str, turn_id),
            item_id=cast(str, item_id),
            risk_level=CodexApprovalRiskLevel(risk_level),
            payload_digest=payload_digest,
            display_summary=display,
            expires_at=expires_at,
        )
        if self._protocol_version == CodexConnectionProtocolVersion.V2:
            await self._queue_v2_event(
                AgentApprovalOpenedEventDetail(
                    approval=self._to_v2_pending_approval(self._pending_approvals[approval_id])
                )
            )
        else:
            await self._send_or_buffer(
                self._build_model_frame(AgentV1MessageType.APPROVAL_OPENED.value, approval)
            )

    def _build_approval_display(
        self,
        *,
        mapping: Mapping[str, JsonValue],
        approval_kind: str,
        risk_level: Literal["normal", "high"],
        reason: JsonValue | None,
    ) -> AgentApprovalDisplaySummary:
        """从官方字段生成结构化、工作区相对的展示摘要。"""

        cwd = mapping.get("cwd")
        grant_root = mapping.get("grantRoot")
        workspace_name = self._path_name(cwd)
        file_changes = self._build_file_changes(mapping.get("fileChanges"), cwd)
        relative_grant_root = self._relative_path(grant_root, cwd)
        file_scope = tuple(
            dict.fromkeys(
                [
                    *(change.path for change in file_changes),
                    *([relative_grant_root] if relative_grant_root is not None else []),
                ]
            )
        )
        permissions = mapping.get("permissions")
        permission_names = (
            tuple(str(key) for key, value in permissions.items() if value is not None)
            if isinstance(permissions, Mapping)
            else ()
        )
        command = mapping.get("command")
        display_command = command[:1_024] if isinstance(command, str) and command else None
        command_actions = self._build_command_actions(mapping.get("commandActions"), cwd)
        command_summary = (
            " | ".join(action.command for action in command_actions)[:256]
            if command_actions
            else display_command[:256]
            if display_command is not None
            else "需要执行本机命令"
            if approval_kind == "command"
            else None
        )
        read_only = bool(command_actions) and all(
            action.action_type in {"read", "listFiles", "search"} for action in command_actions
        )
        network_requested = mapping.get("networkApprovalContext") is not None or (
            isinstance(permissions, Mapping) and permissions.get("network") is not None
        )
        allowed_actions = self._allowed_approval_actions(
            approval_kind=approval_kind,
            mapping=mapping,
        )
        risk_reason = (
            "network_access"
            if network_requested
            else "extra_workspace_root"
            if grant_root is not None
            else "permission_elevation"
            if approval_kind == "permissions"
            else None
        )
        return AgentApprovalDisplaySummary(
            title=(
                "命令审批"
                if approval_kind == "command"
                else "文件变更审批"
                if approval_kind == "file_change"
                else "额外权限审批"
            ),
            reason=str(reason)[:256] if reason is not None else "Codex请求继续执行。",
            workspace_name=workspace_name,
            risk_level=CodexApprovalRiskLevel(risk_level),
            command_summary=command_summary,
            command=display_command,
            command_actions=command_actions,
            working_directory="." if isinstance(cwd, str) and cwd else None,
            read_only=read_only,
            file_scope=file_scope,
            file_changes=file_changes,
            permission_names=permission_names,
            network_requested=network_requested,
            extra_root_requested=grant_root is not None,
            risk_reason=risk_reason,
            allowed_actions=allowed_actions,
        )

    def _read_execpolicy_amendment(
        self,
        mapping: Mapping[str, JsonValue],
    ) -> tuple[str, ...]:
        """只保留官方 execpolicy proposal 的受限字符串列表。"""

        value = mapping.get("proposedExecpolicyAmendment")
        if not isinstance(value, list):
            return ()
        return tuple(item[:1_024] for item in value[:64] if isinstance(item, str) and item)

    def _read_network_policy_amendments(
        self,
        mapping: Mapping[str, JsonValue],
    ) -> tuple[dict[str, JsonValue], ...]:
        """只保留 schema 定义的单主机 allow/deny proposal。"""

        value = mapping.get("proposedNetworkPolicyAmendments")
        if not isinstance(value, list):
            return ()
        proposals: list[dict[str, JsonValue]] = []
        for item in value[:16]:
            if not isinstance(item, Mapping):
                continue
            action = item.get("action")
            host = item.get("host")
            if action not in {"allow", "deny"} or not isinstance(host, str) or not host:
                continue
            proposals.append({"action": action, "host": host[:256]})
        return tuple(proposals)

    def _allowed_approval_actions(
        self,
        *,
        approval_kind: str,
        mapping: Mapping[str, JsonValue],
    ) -> tuple[CodexApprovalDecision, ...]:
        """根据官方 request 中实际存在的 proposal 生成可见动作。"""

        actions = [CodexApprovalDecision.ACCEPT, CodexApprovalDecision.ACCEPT_FOR_SESSION]
        if approval_kind == "command":
            if self._read_execpolicy_amendment(mapping):
                actions.append(CodexApprovalDecision.ACCEPT_WITH_EXECPOLICY_AMENDMENT)
            if len(self._read_network_policy_amendments(mapping)) == 1:
                actions.append(CodexApprovalDecision.APPLY_NETWORK_POLICY_AMENDMENT)
            actions.extend((CodexApprovalDecision.DECLINE, CodexApprovalDecision.CANCEL))
        elif approval_kind == "file_change":
            actions.extend((CodexApprovalDecision.DECLINE, CodexApprovalDecision.CANCEL))
        else:
            actions.append(CodexApprovalDecision.DECLINE)
        return tuple(actions)

    def _build_command_actions(
        self,
        value: JsonValue | None,
        cwd: JsonValue | None,
    ) -> tuple[CodexApprovalCommandAction, ...]:
        if not isinstance(value, list):
            return ()
        actions: list[CodexApprovalCommandAction] = []
        for raw_action in value[:32]:
            if not isinstance(raw_action, Mapping):
                continue
            action = cast(Mapping[str, JsonValue], raw_action)
            action_type = action.get("type")
            command = action.get("command")
            if not isinstance(action_type, str) or not action_type:
                continue
            if not isinstance(command, str) or not command:
                continue
            name = action.get("name")
            query = action.get("query")
            actions.append(
                CodexApprovalCommandAction(
                    action_type=action_type[:64],
                    command=command[:1_024],
                    path=self._relative_path(action.get("path"), cwd),
                    name=name[:128] if isinstance(name, str) and name else None,
                    query=query[:256] if isinstance(query, str) and query else None,
                )
            )
        return tuple(actions)

    def _build_file_changes(
        self,
        value: JsonValue | None,
        cwd: JsonValue | None,
    ) -> tuple[CodexApprovalFileChange, ...]:
        if not isinstance(value, Mapping):
            return ()
        changes: list[CodexApprovalFileChange] = []
        for raw_path, raw_change in list(value.items())[:64]:
            if not isinstance(raw_path, str) or not raw_path:
                continue
            change = (
                cast(Mapping[str, JsonValue], raw_change) if isinstance(raw_change, Mapping) else {}
            )
            relative_path = self._relative_path(raw_path, cwd) or self._path_name(raw_path)
            if relative_path is None:
                continue
            change_kind = change.get("type") or change.get("kind") or "modified"
            added_lines = change.get("addedLines", change.get("added_lines"))
            deleted_lines = change.get("deletedLines", change.get("deleted_lines"))
            changes.append(
                CodexApprovalFileChange(
                    path=relative_path,
                    change_kind=str(change_kind)[:64],
                    added_lines=(
                        added_lines
                        if isinstance(added_lines, int)
                        and not isinstance(added_lines, bool)
                        and added_lines >= 0
                        else None
                    ),
                    deleted_lines=(
                        deleted_lines
                        if isinstance(deleted_lines, int)
                        and not isinstance(deleted_lines, bool)
                        and deleted_lines >= 0
                        else None
                    ),
                    sensitive=self._is_sensitive_path(relative_path),
                )
            )
        return tuple(changes)

    def _relative_path(
        self,
        value: JsonValue | None,
        cwd: JsonValue | None,
    ) -> str | None:
        if not isinstance(value, str) or not value:
            return None
        candidate = PureWindowsPath(value)
        if isinstance(cwd, str) and cwd:
            root = PureWindowsPath(cwd)
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                relative = None
            if relative is not None:
                normalized = str(relative)
                return normalized[:1_024] if normalized not in {"", "."} else "."
        name = candidate.name
        return name[:1_024] if name else None

    def _is_sensitive_path(self, value: str) -> bool:
        segments = {segment.lower() for segment in PureWindowsPath(value).parts}
        return bool(segments & {".env", ".git", ".ssh", "secrets", "credentials"})

    def _path_name(self, value: JsonValue | None) -> str | None:
        """把官方绝对路径收敛为单个目录名。"""

        if not isinstance(value, str) or not value:
            return None
        name = PureWindowsPath(value).name
        return name[:128] if name else None

    async def _reply_approval(self, command: CodexAgentCommand) -> JsonValue:
        approval_value = command.params.get("approvalId")
        decision = command.params.get("decision")
        if not isinstance(approval_value, str) or not isinstance(decision, str):
            raise ValueError("审批决定缺少approvalId或decision。")
        try:
            parsed_decision = CodexApprovalDecision(decision)
        except ValueError:
            raise ValueError("审批决定不受支持。")
        approval_id = UUID(approval_value)
        pending = self._pending_approvals.get(approval_id)
        if pending is None:
            raise ValueError("审批RPC关联不存在或已失效。")
        if pending.expires_at <= datetime.now(UTC):
            self._pending_approvals.pop(approval_id, None)
            raise ValueError("审批已经过期。")
        if pending.app_server_instance_id != self._supervisor.handle.instance_id:
            raise ValueError("审批所属App Server代次已经失效。")
        if parsed_decision not in pending.display.allowed_actions:
            raise ValueError("审批决定不在该官方请求的允许动作内。")
        response: dict[str, JsonValue]
        if pending.method == "item/permissions/requestApproval":
            response = {
                "permissions": (
                    pending.requested_permissions
                    if parsed_decision
                    in {
                        CodexApprovalDecision.ACCEPT,
                        CodexApprovalDecision.ACCEPT_FOR_SESSION,
                    }
                    and isinstance(pending.requested_permissions, Mapping)
                    else {}
                ),
                "scope": (
                    "session"
                    if parsed_decision is CodexApprovalDecision.ACCEPT_FOR_SESSION
                    else "turn"
                ),
            }
        elif parsed_decision is CodexApprovalDecision.ACCEPT_WITH_EXECPOLICY_AMENDMENT:
            response = {
                "decision": {
                    "acceptWithExecpolicyAmendment": {
                        "execpolicy_amendment": list(pending.proposed_execpolicy_amendment),
                    }
                }
            }
        elif parsed_decision is CodexApprovalDecision.APPLY_NETWORK_POLICY_AMENDMENT:
            response = {
                "decision": {
                    "applyNetworkPolicyAmendment": {
                        "network_policy_amendment": pending.proposed_network_policy_amendments[0],
                    }
                }
            }
        else:
            response = {"decision": parsed_decision.value}
        await self._supervisor.handle.client.reply(pending.request_id, response)
        self._pending_approvals.pop(approval_id, None)
        return {"approvalId": approval_value, "state": "applied"}

    async def _accept_protocol_warning(self, warning: str) -> None:
        warning_digest = hashlib.sha256(warning.encode("utf-8")).hexdigest()[:16]
        handle = self._supervisor.handle
        self._logger.warning(
            AgentDiagnosticEnvelope(
                header=AgentDiagnosticHeader(
                    detail_kind=AgentDiagnosticCode.APP_SERVER_PROTOCOL_WARNING,
                    host_id=str(self._settings.agent.host_id),
                    app_server_instance_id=handle.instance_id,
                    process_id=handle.process.pid,
                    codex_version=handle.codex_version,
                    occurred_at=datetime.now(UTC),
                ),
                detail=AgentProtocolWarningDiagnosticDetail(
                    byte_count=len(warning.encode("utf-8")),
                    digest=warning_digest,
                ),
            ).to_log_line()
        )
        if self._protocol_version == CodexConnectionProtocolVersion.V2:
            await self._queue_v2_event(
                AgentProtocolWarningEventDetail(
                    reason_code="app_server_protocol_warning",
                    method=warning_digest,
                )
            )
            return
        event = CodexAgentRealtimeEvent(
            host_id=self._settings.agent.host_id,
            app_server_instance_id=self._supervisor.handle.instance_id,
            occurred_at=datetime.now(UTC),
            method="internal/protocol.warning",
            params={"warning_digest": warning_digest},
        )
        await self._send_or_buffer(
            self._build_model_frame(AgentV1MessageType.REALTIME_EVENT.value, event)
        )

    async def _send_or_buffer(
        self,
        frame: CodexConnectionFrame,
        *,
        seq: int | None = None,
        retain_until_ack: bool = False,
    ) -> None:
        buffered = AgentBufferedEvent(
            epoch=self._event_epoch,
            seq=seq if seq is not None else self._journal.next_event_seq(),
            frame=frame,
        )
        self._event_buffer.append(buffered)
        sender = self._active_sender
        if sender is not None:
            try:
                await sender.send(frame)
                if not retain_until_ack:
                    self._event_buffer.discard_acknowledged(
                        epoch=buffered.epoch,
                        after_seq=buffered.seq,
                    )
                return
            except (ConnectionError, RuntimeError, TimeoutError):
                pass

    async def _flush_buffer(self, sender: CodexOutboundFrameSenderPort) -> None:
        window = self._event_buffer.read_after(
            epoch=self._event_epoch,
            after_seq=self._event_ack,
        )
        if window.snapshot_required:
            if self._protocol_version == CodexConnectionProtocolVersion.V2:
                first_available_seq = window.first_available_seq or 1
                gap_record = self._build_event_record(
                    AgentGapEventDetail(
                        first_available_seq=first_available_seq,
                    )
                )
                await self._send_v2_batch(
                    AgentEventBatchV2Detail(
                        agent_event_epoch=self._event_epoch,
                        first_seq=gap_record.seq,
                        last_seq=gap_record.seq,
                        events=(gap_record,),
                    )
                )
            else:
                gap = CodexAgentRealtimeEvent(
                    host_id=self._settings.agent.host_id,
                    app_server_instance_id=self._supervisor.handle.instance_id,
                    occurred_at=datetime.now(UTC),
                    method="internal/event.gap",
                    params={"snapshotRequired": True},
                )
                await sender.send(
                    self._build_model_frame(AgentV1MessageType.REALTIME_EVENT.value, gap)
                )
        for buffered in window.events:
            await sender.send(buffered.frame)
            if self._protocol_version == CodexConnectionProtocolVersion.V1:
                self._event_buffer.discard_acknowledged(
                    epoch=buffered.epoch,
                    after_seq=buffered.seq,
                )

    async def _send_command_ack(
        self,
        sender: CodexOutboundFrameSenderPort,
        ack: CodexAgentCommandAck,
    ) -> None:
        if self._protocol_version == CodexConnectionProtocolVersion.V1:
            await self._send_model(sender, AgentV1MessageType.COMMAND_ACK.value, ack)
            return
        state = "executing" if ack.state == "accepted" else ack.state
        if state not in {"received", "executing", "completed", "failed", "unknown"}:
            state = "unknown"
        await sender.send(
            self._protocol_codec.encode_v2(
                host_id=self._settings.agent.host_id,
                key_id=self._settings.agent.key_id,
                message_id=uuid4(),
                detail=AgentCommandAckV2Detail(
                    command_id=ack.command_id,
                    operation_id=ack.operation_id,
                    state=cast(
                        Literal["received", "executing", "completed", "failed", "unknown"],
                        state,
                    ),
                    replayed=ack.replayed,
                    recovery_required=ack.recovery_required,
                ),
            )
        )

    async def _send_command_result(
        self,
        sender: CodexOutboundFrameSenderPort,
        result: CodexAgentCommandResult,
        command_type: str | None = None,
    ) -> None:
        if self._protocol_version == CodexConnectionProtocolVersion.V1:
            await self._send_model(sender, AgentV1MessageType.COMMAND_RESULT.value, result)
            return
        thread_id, turn_id = read_upstream_identifiers(result.result)
        typed_result: AgentCommandResultPayload | None = None
        if (
            command_type == "thread.read"
            and result.outcome == "completed"
            and result.result is not None
        ):
            product_result = self._app_server_protocol_adapter.adapt_thread_read_result(
                result.result
            )
            typed_result = AgentThreadReadCommandResult(snapshot=product_result)
        await sender.send(
            self._protocol_codec.encode_v2(
                host_id=self._settings.agent.host_id,
                key_id=self._settings.agent.key_id,
                message_id=uuid4(),
                detail=AgentCommandResultV2Detail(
                    command_id=result.command_id,
                    operation_id=result.operation_id,
                    outcome=result.outcome,
                    result=typed_result,
                    reference=AgentCommandResultReference(
                        upstream_thread_id=thread_id,
                        upstream_turn_id=turn_id,
                        status=result.outcome,
                    ),
                    error_code=result.error_code,
                    error_summary=result.error_message,
                ),
            )
        )

    async def _queue_v2_event(self, detail: AgentEventDetail) -> None:
        record = self._build_event_record(detail)
        result = self._event_batcher.push(record)
        for batch in result.flushed:
            await self._send_v2_batch(batch)
        if self._event_batcher.has_pending and (
            self._batch_flush_task is None or self._batch_flush_task.done()
        ):
            self._batch_flush_task = asyncio.create_task(self._flush_pending_batch())

    async def _flush_pending_batch(self) -> None:
        await asyncio.sleep(self._settings.agent.event_batch_window_milliseconds / 1_000)
        if self._event_batcher.has_pending:
            await self._send_v2_batch(self._event_batcher.flush())

    async def _rotate_event_epoch(self) -> None:
        """在控制面丢失累计 ACK 时丢弃旧增量并启动新事件代次。"""

        flush_task = self._batch_flush_task
        self._batch_flush_task = None
        if flush_task is not None and not flush_task.done():
            flush_task.cancel()
            await asyncio.gather(flush_task, return_exceptions=True)
        self._event_batcher = self._build_event_batcher()
        self._event_buffer.clear()
        self._event_epoch = self._journal.start_event_epoch()
        self._event_ack = 0

    def _build_event_batcher(self) -> AgentEventBatcher:
        """按 Agent 强类型容量配置构建唯一事件批处理器。"""

        return AgentEventBatcher(
            window=timedelta(milliseconds=self._settings.agent.event_batch_window_milliseconds),
            max_bytes=self._settings.agent.event_batch_max_bytes,
        )

    async def _send_v2_batch(self, batch: AgentEventBatchV2Detail) -> None:
        frame = self._protocol_codec.encode_v2(
            host_id=self._settings.agent.host_id,
            key_id=self._settings.agent.key_id,
            message_id=uuid4(),
            detail=batch,
        )
        await self._send_or_buffer(
            frame,
            seq=batch.last_seq,
            retain_until_ack=True,
        )

    def _build_event_record(self, detail: AgentEventDetail) -> AgentEventRecord:
        return AgentEventRecord(
            agent_event_epoch=self._event_epoch,
            seq=self._journal.next_event_seq(),
            event_id=uuid4(),
            app_server_instance_id=UUID(self._supervisor.handle.instance_id),
            occurred_at=datetime.now(UTC),
            detail=detail,
        )

    def _accept_event_ack(self, ack: AgentEventAckV2Detail) -> None:
        if ack.agent_event_epoch != self._event_epoch:
            raise ValueError("控制面事件ACK epoch不匹配。")
        self._journal.write_event_ack(epoch=self._event_epoch, after_seq=ack.after_seq)
        self._event_ack = max(self._event_ack, ack.after_seq)
        self._event_buffer.discard_acknowledged(
            epoch=self._event_epoch,
            after_seq=ack.after_seq,
        )

    async def _replay_v2_events(
        self,
        request: AgentReplayRequestV2Detail,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        if request.agent_event_epoch != self._event_epoch:
            await self._send_snapshot(self._supervisor.handle, sender)
            return
        window = self._event_buffer.read_after(
            epoch=request.agent_event_epoch,
            after_seq=request.after_seq,
        )
        if window.snapshot_required:
            await self._send_snapshot(self._supervisor.handle, sender)
        for buffered in window.events:
            await sender.send(buffered.frame)

    def _verify_v2_control_host(self, host_id: UUID) -> None:
        if host_id != self._settings.agent.host_id:
            raise PermissionError("控制面v2消息host_id与本机Agent不匹配。")

    def _read_legacy_token(self) -> str | None:
        """仅在显式 v1 迁移配置下读取旧 bearer。"""

        if self._protocol_version != CodexConnectionProtocolVersion.V1:
            return None
        credential_id = self._settings.agent.legacy_credential_id
        if credential_id is None:
            raise ValueError("Agent v1配置缺少旧凭据标识。")
        return self._secret_store.read(credential_id)

    async def _build_connection_request(
        self,
        legacy_token: str | None,
    ) -> tuple[str, dict[str, str]]:
        """为 v2 构造单次 ticket URL；v1 仅走有界 bearer 迁移。"""

        if self._protocol_version == CodexConnectionProtocolVersion.V1:
            if legacy_token is None:
                raise ValueError("Agent v1连接缺少旧 bearer。")
            return (
                self._settings.agent.control_plane_url,
                {"Authorization": f"Bearer {legacy_token}"},
            )
        key_id = self._settings.agent.key_id
        if key_id is None or self._connection_ticket_provider is None:
            raise ValueError("Agent v2连接缺少设备key或票据提供器。")
        issued = await self._connection_ticket_provider.issue(
            host_id=self._settings.agent.host_id,
            key_id=key_id,
        )
        parsed = urlsplit(self._settings.agent.control_plane_url)
        query = parse_qsl(parsed.query, keep_blank_values=True)
        query.append(("ticket", issued.ticket))
        return (
            urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
            ),
            {},
        )

    def _build_pending_approval_snapshots(
        self,
    ) -> tuple[AgentPendingApprovalSnapshot, ...]:
        return tuple(
            self._to_v2_pending_approval(item)
            for item in self._pending_approvals.values()
            if item.expires_at > datetime.now(UTC)
        )

    def _to_v2_pending_approval(
        self,
        pending: PendingAgentApproval,
    ) -> AgentPendingApprovalSnapshot:
        return AgentPendingApprovalSnapshot(
            approval_id=pending.approval_id,
            app_server_instance_id=UUID(pending.app_server_instance_id),
            approval_kind=pending.approval_kind,
            thread_id=pending.thread_id,
            turn_id=pending.turn_id,
            item_id=pending.item_id,
            payload_digest=pending.payload_digest,
            version=1,
            expires_at=pending.expires_at,
            display=pending.display,
        )

    def _map_product_notification(
        self,
        detail: AppServerProductNotificationDetail,
        method: str,
    ) -> AgentEventDetail:
        if isinstance(detail, AppServerThreadChangedDetail):
            return AgentThreadChangedEventDetail(
                method=cast(
                    Literal[
                        AppServerNotificationName.THREAD_STARTED,
                        AppServerNotificationName.THREAD_STATUS_CHANGED,
                    ],
                    AppServerNotificationName(method),
                ),
                thread=detail.thread,
            )
        if isinstance(detail, AppServerThreadMetadataChangedDetail):
            return AgentThreadMetadataChangedEventDetail(
                method=cast(
                    Literal[
                        AppServerNotificationName.THREAD_NAME_UPDATED,
                        AppServerNotificationName.THREAD_ARCHIVED,
                        AppServerNotificationName.THREAD_UNARCHIVED,
                    ],
                    AppServerNotificationName(method),
                ),
                thread_id=detail.thread_id,
                display_name=detail.display_name,
                archived=detail.archived,
            )
        if isinstance(detail, AppServerTurnChangedDetail):
            return AgentTurnChangedEventDetail(
                method=cast(
                    Literal[
                        AppServerNotificationName.TURN_STARTED,
                        AppServerNotificationName.TURN_COMPLETED,
                    ],
                    AppServerNotificationName(method),
                ),
                thread_id=detail.thread_id,
                turn_id=detail.turn_id,
                status=detail.status,
            )
        if isinstance(detail, AppServerItemChangedDetail):
            return AgentItemChangedEventDetail(
                method=cast(
                    Literal[
                        AppServerNotificationName.ITEM_STARTED,
                        AppServerNotificationName.ITEM_COMPLETED,
                    ],
                    AppServerNotificationName(method),
                ),
                thread_id=detail.thread_id,
                turn_id=detail.turn_id,
                status=detail.status,
                item=detail.item,
            )
        if isinstance(detail, AppServerItemDeltaDetail):
            return AgentItemDeltaEventDetail(
                method=cast(
                    Literal[
                        AppServerNotificationName.AGENT_MESSAGE_DELTA,
                        AppServerNotificationName.COMMAND_OUTPUT_DELTA,
                        AppServerNotificationName.FILE_OUTPUT_DELTA,
                    ],
                    AppServerNotificationName(method),
                ),
                thread_id=detail.thread_id,
                turn_id=detail.turn_id,
                item_id=detail.item_id,
                delta=detail.delta,
            )
        if isinstance(detail, AppServerPlanChangedDetail):
            return AgentPlanChangedEventDetail(
                thread_id=detail.thread_id,
                turn_id=detail.turn_id,
                explanation=detail.explanation,
                steps=detail.steps,
            )
        if isinstance(detail, AppServerDiffChangedDetail):
            return AgentDiffChangedEventDetail(
                thread_id=detail.thread_id,
                turn_id=detail.turn_id,
                unified_diff=detail.unified_diff,
                truncated=detail.truncated,
            )
        if isinstance(detail, AppServerWarningDetail):
            return AgentProtocolWarningEventDetail(
                reason_code=detail.reason_code,
                method=method,
            )
        raise ValueError("App Server产品通知未映射到Agent事件。")

    async def _send_model(
        self,
        sender: CodexOutboundFrameSenderPort,
        message_type: str,
        model: BaseModel,
    ) -> None:
        await sender.send(self._build_model_frame(message_type, model))

    def _build_model_frame(self, message_type: str, model: BaseModel) -> CodexConnectionFrame:
        payload = cast(dict[str, JsonValue], model.model_dump(mode="json"))
        return CodexConnectionFrame(
            message_id=str(uuid4()),
            message_type=message_type,
            payload=payload,
        )
