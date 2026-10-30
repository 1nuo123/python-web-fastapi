"""Windows Agent 到 FastAPI 的主动出站 WSS 主链路。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import secrets
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from dataclasses import replace as dataclass_replace
from datetime import UTC, datetime, timedelta
from pathlib import Path, PureWindowsPath
from typing import Final, Literal, cast
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from httpx import HTTPStatusError, TransportError
from portalocker.exceptions import LockException
from pydantic import BaseModel, JsonValue, ValidationError
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake
from websockets.typing import Subprotocol

from src.application.ports.agent_connection_ticket_provider_port import (
    AgentConnectionTicketProviderPort,
)
from src.core.codex_contract.agent_connection_contract import (
    AgentCommandAdmissionClosed,
    AgentConnectionIssue,
)
from src.core.codex_contract.agent_diagnostic_contract import (
    AgentDiagnosticCode,
    AgentDiagnosticEnvelope,
    AgentDiagnosticHeader,
    AgentLifecycleDiagnosticDetail,
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
    AgentApprovalResolvedEventDetail,
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
    AgentExecutionLeaseV2Detail,
    AgentExecutionStoppedV2Detail,
    AgentGapEventDetail,
    AgentHeartbeatV2Detail,
    AgentHelloAckV2Detail,
    AgentHelloV2Detail,
    AgentBoundedHelloV2Detail,
    AgentBoundedHelloAckV2Detail,
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
from src.core.codex_contract.agent_runtime_health_contract import (
    AgentDoctorCheckState,
    AgentRuntimeStatus,
)
from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerMessageTooLargeError,
    AppServerRpcError,
    JsonRpcId,
)
from src.core.codex_contract.app_server_product_contract import (
    AppServerDiffChangedDetail,
    AppServerDiffItem,
    AppServerFileChange,
    AppServerItemChangedDetail,
    AppServerItemDeltaDetail,
    AppServerNoticeItem,
    AppServerPlanChangedDetail,
    AppServerProductNotificationDetail,
    AppServerThreadChangedDetail,
    AppServerThreadMetadataChangedDetail,
    AppServerThreadReadProductResult,
    AppServerTurnChangedDetail,
    AppServerWarningDetail,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
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
    CODEX_HISTORY_WINDOW_SUBPROTOCOL,
    CODEX_BOUNDED_CONTENT_SUBPROTOCOL,
    CODEX_LEASE_CONTINUITY_SUBPROTOCOL,
    CodexConnectionEnd,
    CodexConnectionEndKind,
    CodexConnectionFrame,
    CodexConnectionFrameTooLargeError,
    CodexConnectionProtocolVersion,
    CodexConnectionSlowConsumerError,
    CodexConnectionTransportClosed,
    CodexConnectionTransportPort,
    CodexOutboundFrameSenderPort,
)
from src.core.codex_contract.host_contract import CodexApprovalPolicy, CodexSandboxMode
from src.core.codex_contract.model_catalog_contract import CodexModelCatalog
from src.core.codex_contract.workspace_contract import (
    CodexWorkspaceExecutionPreferences,
    ProjectExecutionSettingsApply,
)
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
from src.infrastructure.codex_agent.agent_content_query_handler import AgentContentQueryHandler
from src.infrastructure.codex_agent.agent_query_scheduler import AgentQueryScheduler
from src.infrastructure.codex_agent.agent_content_reader import AgentContentReader
from src.infrastructure.codex_agent.agent_command_journal import AgentCommandJournal
from src.infrastructure.codex_agent.agent_configuration import (
    CodexHostAgentSettings,
)
from src.infrastructure.codex_agent.agent_connection_policy import (
    AgentControlConnectionPolicy,
    AgentExecutionStopReason,
)
from src.infrastructure.codex_agent.agent_event_batcher import AgentEventBatcher
from src.infrastructure.codex_agent.agent_event_replay_buffer import (
    AgentBufferedEvent,
    AgentEventReplayBuffer,
)
from src.infrastructure.codex_agent.agent_execution_lease import AgentExecutionLease
from src.infrastructure.codex_agent.agent_execution_root_store import AgentExecutionRootStore
from src.infrastructure.codex_agent.agent_network_policy import AgentNetworkPolicy
from src.infrastructure.codex_agent.agent_runtime_status_store import AgentRuntimeStatusStore
from src.infrastructure.codex_agent.agent_secret_store import AgentSecretStorePort
from src.infrastructure.codex_agent.agent_snapshot_builder import AgentSnapshotBuilder
from src.infrastructure.codex_agent.agent_thread_history_capacity_registry import (
    AgentThreadHistoryCapacityRegistry,
)
from src.infrastructure.codex_agent.agent_thread_history_window_cache import (
    AgentThreadHistoryWindowCache,
)
from src.infrastructure.codex_agent.agent_timeline_store import AgentTimelineStore
from src.infrastructure.codex_agent.agent_workspace_registry import AgentWorkspaceRegistry
from src.infrastructure.codex_agent.app_server_jsonrpc_client import AppServerProtocolWarning
from src.infrastructure.codex_agent.app_server_model_catalog import read_model_catalog
from src.infrastructure.codex_agent.app_server_process_supervisor import (
    AppServerProcessHandle,
    AppServerProcessSupervisor,
)
from src.infrastructure.codex_agent.app_server_protocol_adapter import AppServerProtocolAdapter
from src.infrastructure.codex_agent.project_execution_settings import ProjectExecutionSettings
from src.infrastructure.worktree.git_worktree_adapter import GitWorktreeAdapter

_SYSTEM_RANDOM = secrets.SystemRandom()

INTERNAL_PROTOCOL_WARNING_METHOD = "internal/protocol.warning"
UNRESOLVED_WORKSPACE_KEY = "unresolved"
AGENT_RETRY_MIN_WAIT_SECONDS: Final = 0.01
AGENT_METADATA_REFRESH_DEBOUNCE_SECONDS: Final = 0.2
AGENT_METADATA_REFRESH_TIMEOUT_SECONDS: Final = 10.0
AGENT_PROTOCOL_WARNING_MAX_KEYS: Final = 128


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
            raise self._closed_error(exc) from exc
        if not isinstance(payload, str):
            raise ValueError("Agent控制通道不接受二进制帧。")
        return payload

    async def send_text(self, payload: str) -> None:
        """发送一个完整产品协议文本帧。"""

        try:
            await self._connection.send(payload)
        except ConnectionClosed as exc:
            raise self._closed_error(exc) from exc

    @staticmethod
    def _closed_error(exc: ConnectionClosed) -> CodexConnectionTransportClosed:
        code = exc.rcvd.code if exc.rcvd is not None else None
        error = CodexConnectionTransportClosed(f"控制面WebSocket已关闭(code={code})。")
        error.close_code = code
        peer_reason = exc.rcvd.reason if exc.rcvd is not None else ""
        error.reason_code = (
            peer_reason
            if peer_reason
            in {
                "hello_timeout",
                "send_timeout",
                "presence_expired",
                "renewal_response_timeout",
                "overloaded",
                "transport_failed",
                "authorization_rejected",
                "protocol_invalid",
                "message_too_large",
            }
            else "remote_close"
        )
        return error

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
    file_change_digest: str | None = None
    version: int = 1


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
        runtime_status_reader: Callable[[], AgentRuntimeStatus | None] | None = None,
        config_path: Path | None = None,
        network_policy: AgentNetworkPolicy | None = None,
    ) -> None:
        self._settings = settings
        self._attempt_id = str(uuid4())
        self._recovery_started_at: float | None = None
        self._execution = AgentExecutionLease()
        self._execution_cleanup_pending = False
        self._execution_paused = False
        self._last_event_seq = 0
        self._connection_ready = False
        self._continuity = False
        self._healthy_connection = False
        self._connected_at = 0.0
        self._connection_phase = "starting"
        self._command_queue: asyncio.Queue[
            tuple[CodexAgentCommand | AgentReplayRequestV2Detail, int | None]
        ] = asyncio.Queue(maxsize=settings.agent.writer_queue_capacity)
        self._status_event = asyncio.Event()
        self._pending_status: dict[str, object] | None = None
        self._connection_state = "starting"
        self._connection_reason: str | None = None
        self._execution_resolved: CodexWorkspaceExecutionPreferences | None = None
        self._project_execution = ProjectExecutionSettings(
            config_path or settings.agent.state_database.with_name("agent.toml")
        )
        self._network = network_policy or AgentNetworkPolicy(settings.agent)
        self._secret_store = secret_store
        self._connection_ticket_provider = connection_ticket_provider
        self._workspace_registry = workspace_registry
        self._worktree_port = GitWorktreeAdapter(workspace_registry)
        self._last_worktree_cleanup = 0.0
        self._execution_root_store = AgentExecutionRootStore.from_state_directory(
            settings.agent.state_database.parent
        )
        self._journal = journal
        self._logger = logger
        self._runtime_status_reader = runtime_status_reader
        self._protocol_version = settings.protocol.agent_schema_version
        self._bounded_content = False
        self._content_budgets = settings.agent.content_budgets.model_copy(
            update={"max_receive_message_bytes": settings.agent.max_control_message_bytes}
        )
        self._protocol_codec = AgentProtocolCodecRegistry()
        self._command_mapper = AgentCommandV2Mapper()
        self._shutdown_event = asyncio.Event()
        self._active_sender: CodexOutboundFrameSenderPort | None = None
        self._running_turns: set[str] = set()
        self._completed_turns: deque[str] = deque(maxlen=2000)
        self._refresh_process = asyncio.Event()
        self._command_active = False
        self._queries = AgentQueryScheduler()
        self._connection_epoch: int | None = None
        self._revocation_generation = 0
        self._hello_ack_event = asyncio.Event()
        self._event_epoch, self._event_ack = self._journal.read_event_ack()
        self._event_buffer = AgentEventReplayBuffer(capacity=settings.agent.max_buffered_events)
        self._event_batcher = self._build_event_batcher()
        self._batch_flush_task: asyncio.Task[None] | None = None
        self._metadata_refresh_tasks: dict[str, asyncio.Task[None]] = {}
        self._pending_approvals: dict[UUID, PendingAgentApproval] = {}
        self._protocol_warning_counts: dict[tuple[str, str | None], int] = {}
        # App Server 的 fileChange approval params 只含稳定 item 定位；保留最近
        # 已审核 item，供审批摘要展示真实 path/kind/diff 事实。
        self._file_change_items: dict[tuple[str, str, str], AppServerDiffItem] = {}
        self._model_catalog = CodexModelCatalog()
        self._model_catalog_instance: str | None = None
        self._history_capacity_registry = AgentThreadHistoryCapacityRegistry(
            max_source_bytes=settings.agent.max_app_server_line_bytes
        )
        self._history_window_cache = AgentThreadHistoryWindowCache()
        self._app_server_protocol_adapter = AppServerProtocolAdapter()
        self._supervisor = AppServerProcessSupervisor(
            codex_binary=settings.agent.codex_binary,
            allowed_versions=[settings.protocol.expected_codex_version],
            max_line_bytes=settings.agent.max_app_server_line_bytes,
            allow_experimental_api=settings.protocol.allow_experimental_api,
            notification_handler=self._accept_app_server_notification,
            request_handler=self._accept_app_server_request,
            warning_handler=self._accept_protocol_warning,
            logger=logger,
            host_id=str(settings.agent.host_id),
        )
        self._local_issue: str | None = None
        self._timeline_store = AgentTimelineStore(
            settings.agent.state_database.with_name("timeline.sqlite3")
        )

    async def run(self) -> None:
        """运行期监督执行许可、命令和维护；只有连接循环拥有网络重试。"""
        status_task = asyncio.create_task(self._publish_status())
        shutdown_task = asyncio.create_task(self._wait_for_shutdown())
        critical = (
            status_task,
            asyncio.create_task(self._watch_execution_lease()),
            asyncio.create_task(self._command_loop()),
            asyncio.create_task(self._maintenance_loop()),
        )
        delay = self._settings.agent.reconnect_min_seconds
        try:
            await self._record_connection_state("starting")
            handle = await self._start_local_runtime()
            legacy_token = self._read_legacy_token()
            while not self._shutdown_event.is_set():
                attempt: asyncio.Task[None] | None = None
                try:
                    self._connection_phase = "connecting"
                    self._hello_ack_event.clear()
                    self._healthy_connection = False
                    await self._record_connection_state("connecting")
                    if self._execution_cleanup_pending:
                        await asyncio.sleep(1)
                        continue
                    handle = self._supervisor.current_handle
                    if handle is None and self._local_issue is None:
                        handle = await self._start_local_runtime()
                    if handle is not None and (
                        handle.process.returncode is not None or not handle.client.running
                    ):
                        for pending in tuple(self._pending_approvals.values()):
                            await self._close_pending_approval(pending, "instance_replaced")
                        self._history_window_cache.clear()
                        self._file_change_items.clear()
                        await self._supervisor.stop()
                        self._running_turns.clear()
                        handle = await self._start_local_runtime()
                        self._execution_paused = False
                    attempt = asyncio.create_task(self._run_connection(handle, legacy_token))
                    done, _ = await asyncio.wait(
                        (attempt, shutdown_task, *critical), return_when=asyncio.FIRST_COMPLETED
                    )
                    if self._shutdown_event.is_set():
                        break
                    for task in critical:
                        if task in done:
                            await task
                            raise RuntimeError("Agent关键后台任务意外结束。")
                    await attempt
                except asyncio.CancelledError:
                    raise
                except (
                    OSError,
                    TimeoutError,
                    HTTPStatusError,
                    TransportError,
                    ValueError,
                    InvalidHandshake,
                ) as exc:
                    if self._shutdown_event.is_set():
                        break
                    if any(task.done() for task in critical):
                        raise RuntimeError("Agent关键后台任务失败，停止运行。") from exc
                    issue = AgentControlConnectionPolicy.issue(exc)
                    if not AgentControlConnectionPolicy.should_retry(exc):
                        await self._stop_execution(
                            AgentExecutionStopReason.DEVICE_REVOKED
                            if issue == AgentConnectionIssue.AUTHORIZATION_REJECTED
                            else AgentExecutionStopReason.EXECUTION_FAILED
                        )
                        await self._record_connection_state("blocked", issue.value)
                        self._logger.error(
                            "Agent连接需要修复：phase=%s reason=%s detail=%s",
                            self._connection_phase,
                            issue.value,
                            AgentControlConnectionPolicy.describe(exc),
                        )
                        # 身份、配置或证书问题保留现场和进程；设置修复后正常重启即可。
                        waiter = asyncio.create_task(self._wait_for_shutdown())
                        try:
                            done, _ = await asyncio.wait(
                                (waiter, *critical), return_when=asyncio.FIRST_COMPLETED
                            )
                            if self._shutdown_event.is_set():
                                break
                            for task in critical:
                                if task in done:
                                    await task
                                    raise RuntimeError("Agent关键后台任务意外结束。")
                        finally:
                            waiter.cancel()
                            await asyncio.gather(waiter, return_exceptions=True)
                        break
                    if self._healthy_connection:
                        delay = self._settings.agent.reconnect_min_seconds
                    await self._record_connection_state("offline", issue.value)
                    jitter = delay * self._settings.agent.reconnect_jitter_ratio
                    wait_seconds = max(
                        AGENT_RETRY_MIN_WAIT_SECONDS,
                        delay + _SYSTEM_RANDOM.uniform(-jitter, jitter),
                        AgentControlConnectionPolicy.read_retry_after_seconds(exc) or 0,
                    )
                    self._logger.warning(
                        "Agent连接恢复：phase=%s reason=%s detail=%s retry_in=%.1fs",
                        self._connection_phase,
                        issue.value,
                        AgentControlConnectionPolicy.describe(exc),
                        wait_seconds,
                    )
                    waiter = asyncio.create_task(self._wait_for_shutdown())
                    try:
                        done, _ = await asyncio.wait(
                            (waiter, *critical),
                            timeout=wait_seconds,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if self._shutdown_event.is_set():
                            break
                        for task in critical:
                            if task in done:
                                await task
                                raise RuntimeError("Agent关键后台任务意外结束。")
                    finally:
                        waiter.cancel()
                        await asyncio.gather(waiter, return_exceptions=True)
                    delay = min(delay * 2, self._settings.agent.reconnect_max_seconds)
                finally:
                    if attempt is not None and not attempt.done():
                        attempt.cancel()
                        await asyncio.gather(attempt, return_exceptions=True)
        finally:
            self._connection_ready = False
            self._active_sender = None
            try:
                await self._stop_execution(AgentExecutionStopReason.LOCAL_SHUTDOWN)
            finally:
                tasks = [shutdown_task, *critical, *self._metadata_refresh_tasks.values()]
                if self._batch_flush_task is not None:
                    tasks.append(self._batch_flush_task)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await self._record_connection_state("stopped")
                try:
                    await asyncio.to_thread(
                        AgentRuntimeStatusStore(self._settings.agent.state_database).update,
                        self._pending_status or {},
                    )
                except (OSError, LockException):
                    self._logger.warning("最终连接状态暂时无法发布。")
                status_task.cancel()
                await asyncio.gather(status_task, return_exceptions=True)
                self._timeline_store.close()
                self._history_window_cache.clear()
                self._file_change_items.clear()

    async def _start_local_runtime(self) -> AppServerProcessHandle | None:
        try:
            handle = await self._supervisor.start()
        except (OSError, RuntimeError, ValueError, AppServerRpcError) as exc:
            await self._supervisor.stop()
            self._local_issue = (
                "cli_not_found" if isinstance(exc, FileNotFoundError) else "app_server_start_failed"
            )
            self._logger.warning("本机执行暂不可用：%s (%s)", self._local_issue, type(exc).__name__)
            if self._protocol_version != CodexConnectionProtocolVersion.V2:
                raise
            return None
        self._local_issue = None if handle.profile else "cli_version_unverified"
        self._execution_paused = False
        return handle

    async def _retry_local_runtime(self) -> None:
        while True:
            await asyncio.sleep(30)
            if await self._start_local_runtime() is not None:
                return

    async def _stop_execution(self, reason: AgentExecutionStopReason) -> None:
        self._connection_ready = False
        await self._queries.cancel_all()
        self._execution.disable()
        self._execution_paused = True
        if self._supervisor.current_handle is None and not self._execution_cleanup_pending:
            return
        self._execution_cleanup_pending = True
        self._execution_stop_reason = reason
        self._logger.warning("execution_stopping reason=%s", reason.value)
        await self._supervisor.stop()
        self._execution_cleanup_pending = False
        self._record_lifecycle(
            "agent.execution.stopped", reason.value, duration_seconds=0, preserved=False
        )

    async def _watch_execution_lease(self) -> None:
        while not self._shutdown_event.is_set():
            await asyncio.sleep(1)
            if self._shutdown_event.is_set():
                return
            if self._execution_cleanup_pending or (
                self._execution.enabled and not self._execution.valid
            ):
                try:
                    await self._stop_execution(
                        self._execution_stop_reason
                        if self._execution_cleanup_pending
                        else AgentExecutionStopReason.LEASE_EXPIRED
                    )
                except (OSError, TimeoutError):
                    self._logger.exception("execution_stop_unconfirmed; admission remains closed")
                await self._record_connection_state("blocked", "execution_lease_expired")
            elif (
                isinstance(self._active_sender, CodexDuplexConnectionSession)
                and self._execution.valid
                and asyncio.get_running_loop().time()
                - max(self._execution.last_response_at, self._connected_at)
                >= self._settings.agent.renewal_response_timeout_seconds
            ):
                self._active_sender.request_close(code=1012, reason="renewal_response_timeout")

    def _record_lifecycle(
        self,
        kind: Literal[
            "agent.connection.ended", "agent.connection.recovered", "agent.execution.stopped"
        ],
        reason: str,
        *,
        duration_seconds: float,
        preserved: bool,
    ) -> None:
        handle = self._supervisor.current_handle
        self._logger.info(
            AgentDiagnosticEnvelope(
                header=AgentDiagnosticHeader(
                    detail_kind=AgentDiagnosticCode(kind),
                    host_id=str(self._settings.agent.host_id),
                    app_server_instance_id=handle.instance_id if handle else "unavailable",
                    process_id=os.getpid(),
                    codex_version=handle.codex_version if handle else None,
                    occurred_at=datetime.now(UTC),
                ),
                detail=AgentLifecycleDiagnosticDetail(
                    kind=kind,
                    attempt_id=self._attempt_id,
                    epoch=self._connection_epoch,
                    phase=self._connection_phase,
                    reason_code=reason,
                    duration_seconds=duration_seconds,
                    remaining_lease_seconds=self._execution.remaining_seconds,
                    execution_preserved=preserved,
                ),
            ).to_log_line()
        )

    async def _record_connection_state(self, state: str, reason: str | None = None) -> None:
        """合并状态投影，文件锁或杀毒软件不能阻塞控制消息。"""
        self._connection_state, self._connection_reason = state, reason
        self._pending_status = {
            "connection_state": state,
            "connection_reason": reason,
            "connection_updated_at": datetime.now(UTC),
            "process_id": os.getpid(),
        }
        self._status_event.set()

    async def _publish_status(self) -> None:
        store = AgentRuntimeStatusStore(self._settings.agent.state_database)
        while not self._shutdown_event.is_set():
            try:
                await asyncio.wait_for(
                    self._status_event.wait(), self._settings.agent.heartbeat_seconds
                )
            except TimeoutError:
                await self._record_connection_state(self._connection_state, self._connection_reason)
            self._status_event.clear()
            updates, self._pending_status = self._pending_status, None
            if updates is not None:
                try:
                    await asyncio.to_thread(store.update, updates)
                except (OSError, LockException):
                    self._logger.warning("本机连接状态暂时无法发布。", exc_info=True)

    async def _maintenance_loop(self) -> None:
        while not self._shutdown_event.is_set():
            await asyncio.sleep(self._settings.agent.heartbeat_seconds)
            if self._is_idle() and self._supervisor.current_handle is not None:
                try:
                    changed = self._supervisor.entry_changed()
                except OSError:
                    changed = False  # A host upgrade may temporarily remove its executable.
                if changed:
                    self._connection_ready = False
                    self._refresh_process.set()
            if (
                self._execution.valid
                and asyncio.get_running_loop().time() - self._last_worktree_cleanup >= 60
            ):
                self._last_worktree_cleanup = asyncio.get_running_loop().time()
                for workspace in self._workspace_registry.list_workspaces():
                    if (workspace.root / ".git").exists():
                        try:
                            await asyncio.to_thread(self._worktree_port.prune, workspace.key)
                        except (OSError, RuntimeError, ValueError):
                            self._logger.warning(
                                "隔离工作树清理未完成：workspace=%s", workspace.key
                            )
            for pending in tuple(self._pending_approvals.values()):
                if pending.expires_at <= datetime.now(UTC):
                    await self._close_pending_approval(pending, "expired")

    async def _wait_for_shutdown(self) -> None:
        await self._shutdown_event.wait()

    def request_shutdown(self) -> None:
        """请求停止新连接与新命令。"""

        self._shutdown_event.set()

    def request_shutdown_if_idle(self) -> bool:
        """同一事件循环原子关闭准入，更新不能切断 turn、命令或审批。"""
        if not self._is_idle():
            return False
        self._connection_ready = False
        self.request_shutdown()
        return True

    def _is_idle(self) -> bool:
        return (
            self._hello_ack_event.is_set()
            and not self._command_active
            and not self._queries.active
            and not self._running_turns
            and not self._pending_approvals
            and self._command_queue.empty()
        )

    def _raise_if_connection_closed_unexpectedly(self) -> None:
        """把非停机导致的正常关闭转换为可退避重试的连接异常。"""

        if self._shutdown_event.is_set():
            return
        raise CodexConnectionTransportClosed("控制面WebSocket连接意外关闭，Agent将按退避策略重连。")

    async def _run_connection(
        self, handle: AppServerProcessHandle | None, legacy_token: str | None
    ) -> None:
        self._attempt_id = str(uuid4())
        self._connection_ready = False
        self._execution.begin_connection()
        if (
            handle is not None
            and handle.profile is not None
            and (
                self._model_catalog_instance != handle.instance_id
                or self._model_catalog.state != "ready"
            )
        ):
            self._model_catalog = await read_model_catalog(handle.client)
            self._model_catalog_instance = handle.instance_id
        if handle is None or handle.profile is None:
            self._model_catalog = CodexModelCatalog()
            self._model_catalog_instance = None
        async with asyncio.timeout(
            self._settings.agent.connection_attempt_timeout_seconds
        ) as setup_budget:
            self._connection_phase = "ticket"
            connection_url, headers = await self._build_connection_request(legacy_token)
            self._connection_phase = "websocket"
            proxy = self._network.proxy_for(connection_url)
            self._logger.info(
                "connection_network attempt_id=%s path=%s",
                self._attempt_id,
                self._network.describe(connection_url),
            )
            proxy_tls_options = (
                {"proxy_ssl": self._network.tls_context}
                if proxy is not None and urlsplit(proxy).scheme == "https"
                else {}
            )
            async with connect(
                connection_url,
                additional_headers=headers,
                max_size=self._settings.agent.max_control_message_bytes,
                ping_interval=self._settings.agent.heartbeat_seconds,
                ping_timeout=self._settings.agent.ping_timeout_seconds,
                open_timeout=self._settings.agent.connection_attempt_timeout_seconds,
                close_timeout=self._settings.agent.close_timeout_seconds,
                subprotocols=[
                    Subprotocol(value)
                    for value in (
                        (
                            CODEX_BOUNDED_CONTENT_SUBPROTOCOL,
                            CODEX_HISTORY_WINDOW_SUBPROTOCOL,
                            CODEX_LEASE_CONTINUITY_SUBPROTOCOL,
                        )
                        if handle
                        and handle.profile
                        and handle.profile.detail.allow_experimental_api
                        else (CODEX_LEASE_CONTINUITY_SUBPROTOCOL,)
                    )
                ],
                proxy=proxy,
                ssl=self._network.tls_context if connection_url.startswith("wss:") else None,
                **proxy_tls_options,
            ) as connection:
                self._bounded_content = connection.subprotocol == CODEX_BOUNDED_CONTENT_SUBPROTOCOL
                self._content_budgets = self._settings.agent.content_budgets.model_copy(
                    update={
                        "max_receive_message_bytes": self._settings.agent.max_control_message_bytes
                    }
                )
                self._protocol_codec = AgentProtocolCodecRegistry(
                    bounded_content=self._bounded_content
                )
                negotiated = connection.subprotocol in {
                    CODEX_LEASE_CONTINUITY_SUBPROTOCOL,
                    CODEX_HISTORY_WINDOW_SUBPROTOCOL,
                    CODEX_BOUNDED_CONTENT_SUBPROTOCOL,
                }
                if self._continuity and not negotiated and self._execution.valid:
                    await self._stop_execution(AgentExecutionStopReason.EXECUTION_FAILED)
                    self._continuity = False
                    raise ConnectionError("控制面未协商执行连续性，按保守方式重建执行进程。")
                self._continuity = negotiated
                self._connected_at = asyncio.get_running_loop().time()
                session = CodexDuplexConnectionSession(
                    transport=AgentWebSocketTransport(connection),
                    inbound_handler=self._handle_control_frame,
                    policy=CodexConnectionSessionPolicy(
                        outbound_queue_capacity=self._settings.agent.writer_queue_capacity,
                        max_frame_bytes=self._settings.agent.max_control_message_bytes,
                        send_enqueue_timeout_seconds=self._settings.agent.send_enqueue_timeout_seconds,
                        send_timeout_seconds=self._settings.agent.send_timeout_seconds,
                        close_timeout_seconds=self._settings.agent.close_timeout_seconds,
                        outbound_queue_max_bytes=self._settings.agent.writer_queue_max_bytes,
                    ),
                )
                self._connection_epoch = None
                session_task = asyncio.create_task(session.run(shutdown_event=self._shutdown_event))
                await asyncio.sleep(0)
                self._active_sender = session
                heartbeat_task: asyncio.Task[None] | None = None
                settings_task: asyncio.Task[None] | None = None
                process_task = asyncio.create_task(
                    handle.process.wait() if handle else self._retry_local_runtime()
                )
                client_task = asyncio.create_task(
                    handle.client.wait_stopped() if handle else self._wait_for_shutdown()
                )
                self._refresh_process.clear()
                refresh_task = asyncio.create_task(self._refresh_process.wait())
                preserve = False
                failure_reason = "unexpected_failure"
                try:
                    self._connection_phase = "hello"
                    await self._require_active_session(session_task)
                    await session.send(self._build_hello_frame(handle))
                    await self._wait_for_hello_ack(session_task)
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop(handle, session))
                    self._connection_phase = "execution_authorization"
                    await self._wait_for_session_event(self._execution.ready, session_task)
                    setup_budget.reschedule(None)
                    executable = handle is not None and handle.profile is not None
                    if self._execution.valid and executable:
                        self._connection_phase = "snapshot"
                        await self._synchronize_snapshot(handle, session, session_task)
                        self._connection_ready = True
                    settings_task = asyncio.create_task(
                        self._settings_sync_loop(handle, session)
                        if executable
                        else self._wait_for_shutdown()
                    )
                    await self._record_connection_state(
                        "online" if self._execution.valid else "blocked",
                        self._local_issue if self._execution.valid else "inactive_host",
                    )
                    await self._flush_buffer(session)
                    self._connection_phase = "running"
                    recovered_in = (
                        asyncio.get_running_loop().time() - self._recovery_started_at
                        if self._recovery_started_at is not None
                        else 0.0
                    )
                    self._record_lifecycle(
                        "agent.connection.recovered",
                        "ready",
                        duration_seconds=recovered_in,
                        preserved=self._execution.valid,
                    )
                    self._recovery_started_at = None
                    watched = (
                        session_task,
                        process_task,
                        client_task,
                        heartbeat_task,
                        settings_task,
                        refresh_task,
                    )
                    done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
                    if handle is None and process_task in done:
                        await process_task
                        preserve = True
                        raise ConnectionError("本机执行已恢复，重新握手发布能力。")
                    if refresh_task in done:
                        raise ConnectionError("主机Codex入口已更新，在空闲边界重新选择兼容档案。")
                    if self._execution_paused and (process_task in done or client_task in done):
                        done, _ = await asyncio.wait(
                            (session_task, heartbeat_task, settings_task),
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                    for task in (heartbeat_task, settings_task):
                        if task in done:
                            await task
                            raise RuntimeError("Agent连接后台任务意外结束。")
                    if session_task in done:
                        ended = await session_task
                        failure_reason = ended.reason_code or ended.reason
                        preserve = (
                            self._continuity
                            and self._execution.valid
                            and ended.kind == CodexConnectionEndKind.TRANSPORT_FAILURE
                        )
                        if not self._shutdown_event.is_set():
                            raise ended.as_exception()
                    elif process_task in done or client_task in done:
                        raise ConnectionError("Codex执行进程或JSON-RPC读取循环已停止。")
                except asyncio.CancelledError:
                    # asyncio.timeout 在退出上下文时才转换成 TimeoutError。
                    # 只把自己的建链期限取消视作传输恢复；外部取消仍按停机处理。
                    if setup_budget.expired() and not self._shutdown_event.is_set():
                        failure_reason = "attempt_timeout"
                        preserve = AgentControlConnectionPolicy.preserve_execution(
                            TimeoutError(),
                            continuity=self._continuity,
                            lease_valid=self._execution.valid,
                            process_healthy=handle is not None
                            and handle.process.returncode is None
                            and handle.client.running,
                        )
                    raise
                except (OSError, TimeoutError) as exc:
                    failure_reason = getattr(exc, "reason_code", type(exc).__name__)
                    preserve = AgentControlConnectionPolicy.preserve_execution(
                        exc,
                        continuity=self._continuity,
                        lease_valid=self._execution.valid,
                        process_healthy=handle is not None
                        and handle.process.returncode is None
                        and handle.client.running,
                    )
                    raise
                finally:
                    if self._recovery_started_at is None:
                        self._recovery_started_at = asyncio.get_running_loop().time()
                    self._record_lifecycle(
                        "agent.connection.ended",
                        "local_shutdown" if self._shutdown_event.is_set() else failure_reason,
                        duration_seconds=asyncio.get_running_loop().time() - self._connected_at,
                        preserved=preserve,
                    )
                    self._logger.info(
                        "connection_cleanup phase=%s epoch=%s preserved=%s remaining_lease=%.3f",
                        self._connection_phase,
                        self._connection_epoch,
                        preserve,
                        self._execution.remaining_seconds,
                    )
                    self._connection_ready = False
                    await self._queries.cancel_all()
                    self._active_sender = None
                    try:
                        if not preserve or self._shutdown_event.is_set():
                            await self._stop_execution(
                                AgentExecutionStopReason.LOCAL_SHUTDOWN
                                if self._shutdown_event.is_set()
                                else AgentExecutionStopReason.EXECUTION_FAILED
                            )
                    finally:
                        tasks = [session_task, process_task, client_task, refresh_task]
                        tasks.extend(
                            task for task in (heartbeat_task, settings_task) if task is not None
                        )
                        for connection_task in tasks:
                            connection_task.cancel()
                        await asyncio.gather(*tasks, return_exceptions=True)
                        await self._record_connection_state(
                            "stopped" if self._shutdown_event.is_set() else "offline"
                        )

    async def _synchronize_snapshot(
        self,
        handle: AppServerProcessHandle,
        session: CodexDuplexConnectionSession,
        session_task: asyncio.Task[CodexConnectionEnd],
    ) -> None:
        for attempt in range(3):
            await self._require_active_session(session_task)
            try:
                async with asyncio.timeout(min(10.0, self._execution.remaining_seconds)):
                    await self._send_snapshot(handle, session)
                return
            except (TimeoutError, AppServerRpcError, AppServerMessageTooLargeError) as exc:
                if attempt == 2 or not self._execution.valid or not handle.client.running:
                    raise ConnectionError("snapshot_sync_failed") from exc
                self._logger.warning(
                    "snapshot_retry attempt=%s remaining_lease=%.3f",
                    attempt + 1,
                    self._execution.remaining_seconds,
                )
                await asyncio.sleep(min(1 + attempt, self._execution.remaining_seconds))

    async def _wait_for_hello_ack(self, session_task: asyncio.Task[CodexConnectionEnd]) -> None:
        """等待握手确认，同时立即感知已经结束的连接会话。"""

        await self._wait_for_session_event(self._hello_ack_event, session_task)

    async def _wait_for_session_event(
        self, event: asyncio.Event, session_task: asyncio.Task[CodexConnectionEnd]
    ) -> None:
        """握手/许可等待共享会话退出检测，且受父级建链总期限约束。"""
        hello_ack_task = asyncio.create_task(event.wait())
        try:
            done, _ = await asyncio.wait(
                (session_task, hello_ack_task),
                timeout=self._settings.agent.handshake_timeout_seconds,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if session_task in done:
                await self._require_active_session(session_task)
            if hello_ack_task not in done:
                raise TimeoutError(f"等待控制面{self._connection_phase}超时。")
            await hello_ack_task
        finally:
            if not hello_ack_task.done():
                hello_ack_task.cancel()
            await asyncio.gather(hello_ack_task, return_exceptions=True)

    async def _require_active_session(self, session_task: asyncio.Task[CodexConnectionEnd]) -> None:
        """拒绝向已经提前结束的控制面连接继续发送。"""

        if not session_task.done():
            return
        ended = await session_task
        raise ended.as_exception()

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
            if self._bounded_content:
                if not isinstance(v2_ack, AgentBoundedHelloAckV2Detail):
                    raise ValueError("有界内容连接缺少预算确认。")
                if (
                    v2_ack.content_budgets.intersect(self._content_budgets)
                    != v2_ack.content_budgets
                ):
                    raise ValueError("服务端返回超出本地能力的预算。")
                self._content_budgets = v2_ack.content_budgets
                if isinstance(sender, CodexDuplexConnectionSession):
                    sender.restrict_message_limit(self._content_budgets.max_receive_message_bytes)
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
        if decoded.v2 is not None and isinstance(decoded.v2.detail, AgentExecutionLeaseV2Detail):
            self._verify_v2_control_host(decoded.v2.header.host_id)
            lease = decoded.v2.detail
            if lease.enabled and self._execution_cleanup_pending:
                return
            if not self._execution.accept(lease):
                return
            if (
                self._connection_ready
                and asyncio.get_running_loop().time() - self._connected_at
                >= self._settings.agent.heartbeat_seconds
            ):
                self._healthy_connection = True
            if not self._execution.valid:
                self._connection_ready = False
                self._execution_paused = True
                for pending in tuple(self._pending_approvals.values()):
                    await self._close_pending_approval(pending, "instance_replaced")
                await self._stop_execution(AgentExecutionStopReason.HOST_SWITCHED)
                await self._record_connection_state("blocked", "inactive_host")
                await sender.send(
                    self._protocol_codec.encode_v2(
                        host_id=self._settings.agent.host_id,
                        key_id=self._settings.agent.key_id,
                        message_id=uuid4(),
                        detail=AgentExecutionStoppedV2Detail(generation=lease.generation),
                    )
                )
            elif self._execution_paused and self._local_issue is None:
                raise ConnectionError("活动电脑已切回，重新建立本机执行进程。")
            else:
                await self._record_connection_state("online", self._local_issue)
            return
        if decoded.v2 is not None and isinstance(decoded.v2.detail, AgentEventAckV2Detail):
            self._accept_event_ack(decoded.v2.detail)
            return
        if decoded.v2 is not None and isinstance(decoded.v2.detail, AgentReplayRequestV2Detail):
            self._verify_v2_control_host(decoded.v2.header.host_id)
            try:
                self._command_queue.put_nowait((decoded.v2.detail, self._connection_epoch))
            except asyncio.QueueFull as exc:
                raise CodexConnectionSlowConsumerError("Agent恢复处理容量已满。") from exc
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
        self._require_command_admission(command, self._connection_epoch)
        window = command.params.get("history_window")
        if (
            command.command_type == "content.read"
            or isinstance(window, dict)
            and window.get("content_mode") == "bounded"
        ):
            epoch = self._connection_epoch
            reserve = (
                self._content_budgets.content_chunk_max_message_bytes
                if command.command_type == "content.read"
                else self._content_budgets.history_page_max_bytes
            )

            def failed() -> None:
                self._logger.error("bounded_query_failed")
                if self._active_sender is not None and epoch == self._connection_epoch:
                    self._active_sender.request_close(code=1011, reason="query_failed")

            if not self._queries.submit(
                reserve_bytes=reserve,
                limit_bytes=self._content_budgets.query_inflight_max_bytes,
                operation=lambda: self._execute_command(command, epoch),
                on_failure=failed,
            ):
                await self._execute_command(command, epoch, query_overloaded=True)
            return
        try:
            self._command_queue.put_nowait((command, self._connection_epoch))
        except asyncio.QueueFull as exc:
            raise CodexConnectionSlowConsumerError("Agent命令处理容量已满。") from exc

    def _require_command_admission(self, command: CodexAgentCommand, epoch: int | None) -> None:
        if (
            not self._connection_ready
            or epoch != self._connection_epoch
            or self._active_sender is None
        ):
            raise AgentCommandAdmissionClosed("命令原连接已失去执行准入。")
        self._execution.require(command.execution_generation)

    async def _command_loop(self) -> None:
        while not self._shutdown_event.is_set():
            command, epoch = await self._command_queue.get()
            try:
                if isinstance(command, AgentReplayRequestV2Detail):
                    sender = self._active_sender
                    if sender is not None and epoch == self._connection_epoch:
                        try:
                            await self._replay_v2_events(command, sender)
                        except (ConnectionError, TimeoutError):
                            self._logger.info("回放等待下次连接同步。")
                else:
                    self._command_active = True
                    try:
                        await self._execute_command(command, epoch)
                    finally:
                        self._command_active = False
            finally:
                self._command_queue.task_done()

    async def _execute_command(
        self, command: CodexAgentCommand, epoch: int | None, *, query_overloaded: bool = False
    ) -> None:
        if not self._connection_ready or epoch != self._connection_epoch:
            # 尚未claim/无副作用：留给服务端按原投递合同重新准入。
            return
        window = command.params.get("history_window")
        if (
            command.command_type == "content.read"
            or isinstance(window, dict)
            and window.get("content_mode") == "bounded"
        ):
            if not self._bounded_content or self._active_sender is None:
                raise ValueError("当前连接未协商正文读取。")
            handle = self._supervisor.handle
            self._require_command_admission(command, epoch)
            await AgentContentQueryHandler(
                host_id=self._settings.agent.host_id,
                key_id=self._settings.agent.key_id,
                client=handle.client,
                cache=self._history_window_cache,
                budgets=self._content_budgets,
                timeline_store=self._timeline_store,
                strategy=handle.profile.detail.history_strategy
                if handle.profile
                else "unavailable",
                sanitize=self._sanitize_thread_read_product_result,
                sanitize_source=self._sanitize_history_source_item,
                validate_workspace=self._workspace_registry.resolve_root,
                source_epoch=self._event_epoch,
                source_seq=self._last_event_seq,
            ).execute(command, self._active_sender, overloaded=query_overloaded)
            return
        executor = AgentCommandExecutor(
            journal=self._journal,
            client=self._supervisor.handle.client,
            command_policy=AgentCommandPolicy(
                self._workspace_registry,
                self._resolve_command_security_policy(command),
            ),
            admission_check=lambda: self._require_command_admission(command, epoch),
            ack_sender=self._send_current_ack,
            result_sender=lambda result: self._send_current_result(result, command),
            approval_reply_handler=self._reply_approval,
            history_capacity_registry=self._history_capacity_registry,
            history_window_cache=self._history_window_cache,
            timeline_store=self._timeline_store,
            worktree_port=self._worktree_port,
            execution_root_store=self._execution_root_store,
            workspace_registry=self._workspace_registry,
            allow_experimental_api=bool(
                self._supervisor.handle.profile
                and self._supervisor.handle.profile.detail.allow_experimental_api
                and self._supervisor.handle.profile.detail.history_strategy
                in {"turns_page", "items_page"}
            ),
            workspace_settings_handler=self._apply_project_settings,
            execution_settings_resolver=self._resolve_project_parameters,
        )
        self._execution_resolved = None
        await executor.execute(command)
        if command.command_type in {"thread.start", "thread.resume"} or (
            command.command_type == "turn.start"
            and self._execution_resolved is not None
            and self._execution_resolved.applied_state != "applied"
        ):
            sender = self._active_sender
            if sender is not None and self._connection_ready and self._execution.valid:
                try:
                    await self._send_snapshot(self._supervisor.handle, sender)
                except (ConnectionError, TimeoutError):
                    self._logger.info("命令已收束，快照等待下次连接同步。")

    async def _send_current_ack(self, ack: CodexAgentCommandAck) -> None:
        sender = self._active_sender
        if sender is not None and self._connection_ready:
            try:
                await self._send_command_ack(sender, ack)
            except (ConnectionError, TimeoutError):
                self._logger.info("命令ACK暂未送达，保留原账本。")

    async def _send_current_result(
        self, result: CodexAgentCommandResult, command: CodexAgentCommand
    ) -> None:
        if command.command_type == "turn.start" and isinstance(result.result, dict):
            turn = result.result.get("turn")
            if (
                isinstance(turn, dict)
                and isinstance(turn.get("id"), str)
                and turn.get("status") == "inProgress"
                and turn["id"] not in self._completed_turns
            ):
                self._running_turns.add(turn["id"])
        sender = self._active_sender if self._connection_ready else None
        try:
            await self._send_command_result(sender, result, command.command_type, command)
        except (ConnectionError, TimeoutError):
            self._logger.info("命令结果暂未送达，按原命令ID核对。")

    async def _apply_project_settings(self, command: CodexAgentCommand) -> JsonValue:
        key = command.params.get("workspace_key")
        if not isinstance(key, str):
            raise ValueError("项目身份无效。")
        self._workspace_registry.resolve_root(key)
        request = ProjectExecutionSettingsApply.model_validate(command.params.get("settings"))
        effective = await self._project_execution.apply(
            key, request, self._supervisor.handle.client
        )
        # 成功回读后先发布投影，命令终态不能早于本机持久状态。
        if self._active_sender is not None:
            await self._send_snapshot(self._supervisor.handle, self._active_sender)
        return effective.model_dump(mode="json")

    async def _resolve_project_parameters(
        self, key: str, method: str, cwd: str
    ) -> dict[str, JsonValue]:
        effective = await self._project_execution.resolve(key, self._supervisor.handle.client)
        self._execution_resolved = effective
        return self._project_execution.build_parameters(method, effective, cwd)

    def _resolve_command_security_policy(
        self,
        command: CodexAgentCommand,
    ) -> AgentAppServerSecurityPolicy:
        """从具体命令参数构建本次 App Server 安全策略。"""

        local_policy = self._settings.app_server_security.to_policy()
        if command.command_type not in {"thread.start", "thread.resume", "turn.start"}:
            return local_policy
        if command.sandbox_mode is None or command.approval_policy is None:
            raise PermissionError("Agent命令缺少用户确认的执行限制。")
        return AgentAppServerSecurityPolicy(
            approval_policy=command.approval_policy.value,
            approvals_reviewer=local_policy.approvals_reviewer,
            sandbox_mode=command.sandbox_mode.value,
        )

    async def _send_snapshot(
        self,
        handle: AppServerProcessHandle,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        execution_generation = self._execution.generation
        builder = AgentSnapshotBuilder(
            host_id=self._settings.agent.host_id,
            workspace_registry=self._workspace_registry,
            client=handle.client,
            app_server_instance_id=handle.instance_id,
            journal=self._journal,
            history_capacity_registry=self._history_capacity_registry,
        )
        if self._protocol_version == CodexConnectionProtocolVersion.V2:
            snapshot = await builder.build()
            workspaces = []
            for workspace in snapshot.workspaces:
                try:
                    effective = await self._project_execution.resolve(workspace.key, handle.client)
                except (OSError, ValueError, RuntimeError) as exc:
                    local = await asyncio.to_thread(
                        self._project_execution.read_workspace, workspace.key
                    )
                    effective = CodexWorkspaceExecutionPreferences(
                        requested=local.execution_overrides,
                        local_revision=local.execution_revision,
                        applied_state="blocked",
                        error=str(exc)[:512],
                    )
                workspaces.append(workspace.model_copy(update={"execution_preferences": effective}))
            snapshot = snapshot.model_copy(update={"workspaces": workspaces})
            page_index = 0
            while True:
                v2_snapshot = await builder.build_v2(
                    page_index=page_index,
                    page_size=self._settings.agent.snapshot_page_size,
                    max_page_bytes=self._settings.agent.max_control_message_bytes,
                    encoded_size=lambda value: len(
                        self._protocol_codec.encode_v2(
                            host_id=self._settings.agent.host_id,
                            key_id=self._settings.agent.key_id,
                            message_id=UUID(int=0),
                            detail=value.model_copy(
                                update={"execution_generation": execution_generation}
                            ),
                        )
                        .model_dump_json()
                        .encode("utf-8")
                    ),
                    pending_approvals=self._build_pending_approval_snapshots(),
                    snapshot=snapshot,
                )
                if (
                    not self._execution.enabled
                    or execution_generation != self._execution.generation
                ):
                    return
                v2_snapshot = v2_snapshot.model_copy(
                    update={"execution_generation": execution_generation}
                )
                await sender.send(
                    self._protocol_codec.encode_v2(
                        host_id=self._settings.agent.host_id,
                        key_id=self._settings.agent.key_id,
                        message_id=uuid4(),
                        detail=v2_snapshot,
                    )
                )
                if v2_snapshot.continuation_token is None:
                    break
                page_index += 1
            return
        v1_snapshot = await builder.build()
        await self._send_model(sender, AgentV1MessageType.STATE_SNAPSHOT.value, v1_snapshot)

    async def _settings_sync_loop(
        self,
        handle: AppServerProcessHandle,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        """本机原生修改或 CLI 基线变化后发布同一投影，不阻塞执行租约心跳。"""
        previous: tuple[str, ...] | None = None
        while True:
            await asyncio.sleep(15)
            if not self._execution.enabled or self._execution_paused:
                continue
            try:
                values = []
                for workspace in self._workspace_registry.list_workspaces():
                    effective = await self._project_execution.resolve(workspace.key, handle.client)
                    values.append(effective.model_dump_json())
                signature = tuple(values)
                if signature != previous:
                    await self._send_snapshot(handle, sender)
                    previous = signature
            except (OSError, RuntimeError, ValueError, AppServerRpcError):
                # 失效设置也必须发布 blocked；单次探测失败不终止租约心跳。
                try:
                    await self._send_snapshot(handle, sender)
                except (OSError, RuntimeError, ValueError, AppServerRpcError):
                    self._logger.warning("本机项目设置暂时无法同步，将在下次检查重试。")

    async def _heartbeat_loop(
        self,
        handle: AppServerProcessHandle | None,
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
                app_server_instance_id=handle.instance_id if handle else None,
                sent_at=datetime.now(UTC),
            )
            if self._protocol_version == CodexConnectionProtocolVersion.V2:
                await sender.send(
                    self._protocol_codec.encode_v2(
                        host_id=self._settings.agent.host_id,
                        key_id=self._settings.agent.key_id,
                        message_id=uuid4(),
                        detail=AgentHeartbeatV2Detail(
                            lease_request_id=self._begin_lease_request(),
                            connection_epoch=epoch,
                            app_server_instance_id=UUID(handle.instance_id) if handle else None,
                            revocation_generation=self._revocation_generation,
                        ),
                    )
                )
            else:
                await self._send_model(sender, AgentV1MessageType.HEARTBEAT.value, heartbeat)

    def _begin_lease_request(self) -> UUID:
        return self._execution.begin_request()

    def _build_hello_frame(self, handle: AppServerProcessHandle | None) -> CodexConnectionFrame:
        if self._protocol_version == CodexConnectionProtocolVersion.V2:
            return self._protocol_codec.encode_v2(
                host_id=self._settings.agent.host_id,
                key_id=self._settings.agent.key_id,
                message_id=uuid4(),
                detail=(AgentBoundedHelloV2Detail if self._bounded_content else AgentHelloV2Detail)(
                    **({"content_budgets": self._content_budgets} if self._bounded_content else {}),
                    execution_lease_supported=True,
                    lease_request_id=self._begin_lease_request(),
                    agent_version=self._settings.protocol.agent_version,
                    codex_version=handle.codex_version if handle else None,
                    app_server_schema_digest=handle.schema_digest if handle else None,
                    app_server_state="ready" if handle else "unavailable",
                    capabilities=handle.profile.detail.capabilities
                    if handle and handle.profile
                    else (),
                    model_ids=tuple(item.model for item in self._model_catalog.models),
                    reasoning_efforts=tuple(
                        sorted(
                            {
                                effort
                                for item in self._model_catalog.models
                                for effort in item.reasoning_efforts
                            }
                        )
                    ),
                    model_catalog=self._model_catalog,
                    sandbox_modes=tuple(CodexSandboxMode),
                    approval_policies=tuple(CodexApprovalPolicy),
                    runtime_status=self._read_runtime_status(),
                    app_server_instance_id=handle.instance_id if handle else None,
                    agent_event_epoch=self._event_epoch,
                ),
            )
        if handle is None:
            raise RuntimeError("Legacy protocol requires App Server readiness.")
        hello = CodexAgentHello(
            host_id=self._settings.agent.host_id,
            agent_version=self._settings.protocol.agent_version,
            codex_version=handle.codex_version,
            agent_protocol_version=CODEX_AGENT_PROTOCOL_VERSION,
            app_server_schema_digest=handle.schema_digest,
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

    def _read_runtime_status(self) -> AgentRuntimeStatus | None:
        """读取本连接代次 hello 的最新本地运行态快照。"""

        status = self._runtime_status_reader() if self._runtime_status_reader else None
        if self._local_issue:
            return (status or AgentRuntimeStatus()).model_copy(
                update={
                    "doctor_state": AgentDoctorCheckState.BLOCKED,
                    "doctor_checked_at": datetime.now(UTC),
                    "doctor_issue_codes": (self._local_issue,),
                }
            )
        return status

    async def _accept_app_server_notification(self, method: str, params: JsonValue) -> None:
        if method in {
            "item/agentMessage/delta",
            "item/commandExecution/outputDelta",
            "item/fileChange/outputDelta",
        } and isinstance(params, dict):
            delta = params.get("delta")
            if isinstance(delta, str) and len(delta) > 65536:
                for offset in range(0, len(delta), 65536):
                    await self._accept_app_server_notification(
                        method, {**params, "delta": delta[offset : offset + 65536]}
                    )
                return
        if isinstance(params, dict) and method in {"turn/started", "turn/completed"}:
            turn = params.get("turn")
            if isinstance(turn, dict) and isinstance(turn.get("id"), str):
                if method == "turn/started":
                    self._running_turns.add(turn["id"])
                elif turn.get("status") in {"completed", "failed", "interrupted"}:
                    self._running_turns.discard(turn["id"])
                    self._completed_turns.append(turn["id"])
        if method == AppServerNotificationName.SERVER_REQUEST_RESOLVED.value:
            if not isinstance(params, Mapping):
                await self._accept_protocol_warning(
                    AppServerProtocolWarning(
                        "App Server审批收束通知缺少结构化定位字段。",
                        reason_code="malformed_payload",
                        method=method,
                    )
                )
                return
            resolved_thread_id = params.get("threadId")
            resolved_request_id = params.get("requestId")
            if not isinstance(resolved_thread_id, str) or not isinstance(
                resolved_request_id,
                (str, int),
            ):
                await self._accept_protocol_warning(
                    AppServerProtocolWarning(
                        "App Server审批收束通知缺少稳定定位字段。",
                        reason_code="malformed_payload",
                        method=method,
                    )
                )
                return
            for pending in tuple(self._pending_approvals.values()):
                if (
                    pending.thread_id == resolved_thread_id
                    and pending.request_id == resolved_request_id
                ):
                    await self._close_pending_approval(pending, "resolved")
            return
        original_item_detail = None
        if (
            self._bounded_content
            and method in {"item/started", "item/completed"}
            and isinstance(params, dict)
        ):
            raw_item, thread_id = params.get("item"), params.get("threadId")
            if isinstance(raw_item, dict) and isinstance(thread_id, str):
                binding = self._execution_root_store.load(thread_id)
                if binding is not None:
                    original = self._app_server_protocol_adapter.adapt_notification(
                        method=method,
                        params={
                            **params,
                            "item": self._sanitize_history_source_item(thread_id, raw_item),
                        },
                    ).notification
                    if original is not None:
                        original_item_detail = self._sanitize_file_change_detail(original.detail)
                    item = AgentContentReader(self._history_window_cache).describe_item(
                        self._sanitize_history_source_item(thread_id, raw_item),
                        workspace_key=binding.workspace_key,
                        thread_id=thread_id,
                        expected_generation=self._history_window_cache.invalidation_generation,
                    )
                    descriptor = item.get("contentDescriptor")
                    if isinstance(descriptor, dict):
                        # Realtime references are reissued by the owned HTTP read; no unsigned handle escapes to browsers.
                        descriptor = {
                            key: value
                            for key, value in descriptor.items()
                            if key not in {"content_ref", "expires_at"}
                        }
                        descriptor.update(
                            availability="unavailable",
                            unavailable_reason="content_reference_expired",
                        )
                        item = {**item, "contentDescriptor": descriptor}
                    params = {**params, "item": item}
        adapted = self._app_server_protocol_adapter.adapt_notification(method=method, params=params)
        notification = adapted.notification
        if notification is None:
            await self._accept_protocol_warning(
                AppServerProtocolWarning(
                    "App Server通知未通过已审核产品适配。",
                    reason_code=(
                        adapted.warning_reason.value
                        if adapted.warning_reason is not None
                        else "malformed_payload"
                    ),
                    method=adapted.warning_method or method,
                )
            )
            return
        sanitized_detail = self._sanitize_file_change_detail(notification.detail)
        if sanitized_detail is not notification.detail:
            notification = notification.model_copy(update={"detail": sanitized_detail})
        self._invalidate_history_window_for_notification(sanitized_detail)
        product_detail = sanitized_detail
        if (
            isinstance(product_detail, AppServerItemChangedDetail)
            and isinstance(product_detail.item, AppServerDiffItem)
            and product_detail.turn_id is not None
        ):
            self._file_change_items[
                (product_detail.thread_id, product_detail.turn_id, product_detail.item.item_id)
            ] = product_detail.item
            if len(self._file_change_items) > 512:
                self._file_change_items.pop(next(iter(self._file_change_items)))
            await self._refresh_pending_file_change_approval(product_detail)
        if isinstance(product_detail, AppServerTurnChangedDetail) and product_detail.status in {
            "completed",
            "failed",
            "interrupted",
            "cancelled",
            "systemError",
        }:
            self._clear_file_change_items_for_turn(
                product_detail.thread_id,
                product_detail.turn_id,
            )
            for pending in tuple(self._pending_approvals.values()):
                if (
                    pending.thread_id == product_detail.thread_id
                    and pending.turn_id == product_detail.turn_id
                ):
                    await self._close_pending_approval(pending, "turn_ended")
        if self._protocol_version == CodexConnectionProtocolVersion.V2:
            detail: AgentEventDetail = self._map_product_notification(
                notification.detail,
                method,
            )
            # Preserve the existing local authoritative item, not the wire preview.
            # If the original exceeded the product limit, retain its truthful descriptor.
            stored_detail = original_item_detail or product_detail
            if (
                isinstance(product_detail, AppServerItemChangedDetail)
                and product_detail.item.content is not None
            ):
                descriptor = product_detail.item.content
                if isinstance(stored_detail, AppServerItemChangedDetail):
                    field = {
                        "command": "output",
                        "diff": "unified_diff",
                        "plan": "explanation",
                    }.get(stored_detail.item.kind, "text")
                    body = getattr(stored_detail.item, field, "")
                    if hashlib.sha256(body.encode("utf-8")).hexdigest() != descriptor.revision:
                        stored_detail = product_detail
            self._timeline_store.capture(stored_detail)
            await self._queue_v2_event(detail)
            if (
                isinstance(detail, AgentTurnChangedEventDetail)
                and detail.method is AppServerNotificationName.TURN_COMPLETED
            ):
                self._schedule_metadata_refresh(detail.thread_id)
            return
        event = CodexAgentRealtimeEvent(
            host_id=self._settings.agent.host_id,
            app_server_instance_id=self._supervisor.handle.instance_id,
            occurred_at=datetime.now(UTC),
            method=method,
            params={},
            product_notification=notification,
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

    def _sanitize_file_change_detail(
        self,
        detail: AppServerProductNotificationDetail,
    ) -> AppServerProductNotificationDetail:
        """在 Agent 本机可信执行根内将文件事实降为可公开的相对路径。"""

        if isinstance(detail, AppServerItemChangedDetail) and isinstance(
            detail.item, AppServerDiffItem
        ):
            return detail.model_copy(
                update={
                    "item": self._sanitize_file_change_item(
                        thread_id=detail.thread_id,
                        item=detail.item,
                    )
                }
            )
        if isinstance(detail, AppServerDiffChangedDetail):
            return detail.model_copy(
                update={"unified_diff": self._remove_diff_path_metadata(detail.unified_diff)}
            )
        return detail

    def _sanitize_history_source_item(
        self, thread_id: str, item: dict[str, JsonValue]
    ) -> dict[str, JsonValue]:
        if item.get("type") != "fileChange":
            return item
        root = self._read_trusted_execution_root(thread_id)
        changes = item.get("changes")
        if root is None or not isinstance(changes, list):
            return {**item, "changes": []}
        retained: list[JsonValue] = []
        for change in changes:
            if not isinstance(change, dict) or not isinstance(change.get("path"), str):
                continue
            path = self._to_trusted_relative_path(change["path"], root)
            kind = change.get("kind")
            if path is None or not isinstance(kind, dict):
                continue
            move = kind.get("move_path")
            if isinstance(move, str):
                move = self._to_trusted_relative_path(move, root)
                if move is None:
                    continue
            retained.append(
                {
                    **change,
                    "path": path,
                    "kind": {**kind, "move_path": move},
                    "diff": self._remove_diff_path_metadata(str(change.get("diff") or "")),
                }
            )
        return {**item, "changes": retained}

    def _sanitize_thread_read_product_result(
        self,
        result: AppServerThreadReadProductResult,
    ) -> AppServerThreadReadProductResult:
        """确保 history/read 和实时事件使用相同的文件脱敏规则。"""

        sanitized_turns = tuple(
            turn.model_copy(
                update={
                    "items": tuple(
                        self._sanitize_file_change_item(result.thread.thread_id, item)
                        if isinstance(item, AppServerDiffItem)
                        else item
                        for item in turn.items
                    )
                }
            )
            for turn in result.turns
        )
        return result.model_copy(update={"turns": sanitized_turns})

    def _sanitize_file_change_item(
        self,
        thread_id: str,
        item: AppServerDiffItem,
    ) -> AppServerDiffItem:
        root = self._read_trusted_execution_root(thread_id)
        if root is None:
            return item.model_copy(update={"unified_diff": "", "changes": ()})
        changes: list[AppServerFileChange] = []
        for change in item.changes:
            path = self._to_trusted_relative_path(change.path, root)
            if path is None:
                continue
            old_path = (
                self._to_trusted_relative_path(change.old_path, root)
                if change.old_path is not None
                else None
            )
            if change.old_path is not None and old_path is None:
                continue
            changes.append(
                change.model_copy(
                    update={
                        "path": path,
                        "old_path": old_path,
                        "diff": self._remove_diff_path_metadata(change.diff),
                    }
                )
            )
        return item.model_copy(update={"unified_diff": "", "changes": tuple(changes)})

    def _read_trusted_execution_root(self, thread_id: str) -> Path | None:
        binding = self._execution_root_store.load(thread_id)
        if binding is None:
            return None
        try:
            workspace_root = self._workspace_registry.resolve_root(binding.workspace_key)
            execution_root = binding.execution_root.resolve(strict=True)
        except (OSError, ValueError):
            return None
        if execution_root != workspace_root and not execution_root.is_relative_to(workspace_root):
            return None
        return execution_root

    @staticmethod
    def _to_trusted_relative_path(value: str, root: Path) -> str | None:
        try:
            candidate = Path(value)
            resolved = (
                candidate.resolve(strict=False)
                if candidate.is_absolute()
                else (root / candidate).resolve(strict=False)
            )
            if resolved == root or not resolved.is_relative_to(root):
                return None
            return str(resolved.relative_to(root))[:1_024]
        except (OSError, ValueError):
            return None

    @staticmethod
    def _remove_diff_path_metadata(value: str) -> str:
        """保留 hunk 正文，剥离可能含有本机绝对路径的 Git 元数据。"""

        path_metadata_prefixes = (
            "diff --git ",
            "index ",
            "--- ",
            "+++ ",
            "rename from ",
            "rename to ",
            "similarity index ",
            "new file mode ",
            "deleted file mode ",
        )
        return "\n".join(
            line for line in value.splitlines() if not line.startswith(path_metadata_prefixes)
        )

    def _clear_file_change_items_for_turn(self, thread_id: str, turn_id: str) -> None:
        for key in tuple(self._file_change_items):
            if key[:2] == (thread_id, turn_id):
                self._file_change_items.pop(key, None)

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
        self, request_id: JsonRpcId, method: str, params: JsonValue
    ) -> None:
        try:
            await self._open_app_server_approval(request_id, method, params)
        except (ValidationError, CodexConnectionFrameTooLargeError):
            for identity, pending in tuple(self._pending_approvals.items()):
                if pending.request_id == request_id:
                    self._pending_approvals.pop(identity, None)
            await self._supervisor.handle.client.reply_error(
                request_id,
                code=-32602,
                message="message_too_large: approval cannot be represented without truncating execution parameters",
            )
            await self._queue_v2_event(
                AgentProtocolWarningEventDetail(reason_code="message_too_large", method=method)
            )

    async def _open_app_server_approval(
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
        file_change_digest = (
            self._file_change_digest(
                thread_id=cast(str, thread_id),
                turn_id=cast(str, turn_id),
                item_id=cast(str, item_id),
            )
            if approval_kind == "file_change"
            else None
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
            file_change_digest=file_change_digest,
            version=1,
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
            version=1,
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

    async def _refresh_pending_file_change_approval(
        self,
        detail: AppServerItemChangedDetail,
    ) -> None:
        """同一原生审批请求的 proposal 变化时递增版本并刷新展示。"""

        if not isinstance(detail.item, AppServerDiffItem) or detail.turn_id is None:
            return
        for pending in tuple(self._pending_approvals.values()):
            if (
                pending.approval_kind != "file_change"
                or pending.thread_id != detail.thread_id
                or pending.turn_id != detail.turn_id
                or pending.item_id != detail.item.item_id
            ):
                continue
            latest_digest = self._file_change_digest(
                thread_id=pending.thread_id,
                turn_id=pending.turn_id,
                item_id=pending.item_id,
            )
            if latest_digest == pending.file_change_digest:
                continue
            changes = self._build_file_changes_from_item(detail.item)
            display = pending.display.model_copy(
                update={
                    "file_changes": changes,
                    "file_scope": tuple(change.path for change in changes),
                    "allowed_actions": self._allowed_approval_actions(
                        approval_kind="file_change",
                        mapping={},
                        file_review_available=bool(changes),
                    ),
                }
            )
            updated = dataclass_replace(
                pending,
                display=display,
                file_change_digest=latest_digest,
                version=pending.version + 1,
            )
            self._pending_approvals[pending.approval_id] = updated
            if self._protocol_version == CodexConnectionProtocolVersion.V2:
                await self._queue_v2_event(
                    AgentApprovalOpenedEventDetail(approval=self._to_v2_pending_approval(updated))
                )
            else:
                await self._send_or_buffer(
                    self._build_model_frame(
                        AgentV1MessageType.APPROVAL_OPENED.value,
                        CodexAgentApprovalOpened(
                            approval_id=updated.approval_id,
                            host_id=self._settings.agent.host_id,
                            app_server_instance_id=updated.app_server_instance_id,
                            approval_kind=CodexApprovalKind.FILE_CHANGE,
                            thread_id=updated.thread_id,
                            turn_id=updated.turn_id,
                            item_id=updated.item_id,
                            risk_level=updated.display.risk_level,
                            payload_digest=updated.payload_digest,
                            version=updated.version,
                            display_summary=updated.display,
                            expires_at=updated.expires_at,
                        ),
                    )
                )

    async def _close_pending_approval(
        self,
        pending: PendingAgentApproval,
        reason: Literal["resolved", "expired", "turn_ended", "instance_replaced"],
    ) -> None:
        self._pending_approvals.pop(pending.approval_id, None)
        self._file_change_items.pop((pending.thread_id, pending.turn_id, pending.item_id), None)
        if self._protocol_version == CodexConnectionProtocolVersion.V2:
            await self._queue_v2_event(
                AgentApprovalResolvedEventDetail(
                    approval_id=pending.approval_id,
                    thread_id=pending.thread_id,
                    turn_id=pending.turn_id,
                    reason=reason,
                )
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
        file_changes = (
            self._build_file_changes(mapping.get("fileChanges"), cwd)
            if approval_kind != "file_change"
            else ()
        )
        if approval_kind == "file_change":
            thread_id = mapping.get("threadId")
            turn_id = mapping.get("turnId")
            item_id = mapping.get("itemId")
            if all(isinstance(value, str) and value for value in (thread_id, turn_id, item_id)):
                cached = getattr(self, "_file_change_items", {}).get((thread_id, turn_id, item_id))
                if cached is not None:
                    file_changes = self._build_file_changes_from_item(cached)
                root = self._read_trusted_execution_root(cast(str, thread_id))
                workspace_name = root.name if root is not None else None
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
        display_command = command if isinstance(command, str) and command else None
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
            file_review_available=bool(file_changes),
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
        if len(value) > 64 or any(
            not isinstance(item, str) or not item or len(item) > 1024 for item in value
        ):
            raise CodexConnectionFrameTooLargeError("审批命令策略超过表示容量。")
        return tuple(value)

    def _read_network_policy_amendments(
        self,
        mapping: Mapping[str, JsonValue],
    ) -> tuple[dict[str, JsonValue], ...]:
        """只保留 schema 定义的单主机 allow/deny proposal。"""

        value = mapping.get("proposedNetworkPolicyAmendments")
        if not isinstance(value, list):
            return ()
        proposals: list[dict[str, JsonValue]] = []
        if len(value) > 16:
            raise CodexConnectionFrameTooLargeError("审批网络策略超过表示容量。")
        for item in value:
            if not isinstance(item, Mapping):
                continue
            action = item.get("action")
            host = item.get("host")
            if action not in {"allow", "deny"} or not isinstance(host, str) or not host:
                continue
            if len(host) > 256:
                raise CodexConnectionFrameTooLargeError("审批网络主机超过表示容量。")
            proposals.append({"action": action, "host": host})
        return tuple(proposals)

    def _allowed_approval_actions(
        self,
        *,
        approval_kind: str,
        mapping: Mapping[str, JsonValue],
        file_review_available: bool = True,
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
            if not file_review_available:
                return (CodexApprovalDecision.DECLINE, CodexApprovalDecision.CANCEL)
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
        for raw_action in value:
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
                    command=command,
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
        for raw_path, raw_change in value.items():
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

    def _build_file_changes_from_item(
        self,
        item: AppServerDiffItem,
    ) -> tuple[CodexApprovalFileChange, ...]:
        """把已审核 fileChange item 的 path/kind 映射为审批展示摘要。"""

        result: list[CodexApprovalFileChange] = []
        for change in item.changes[:64]:
            result.append(
                CodexApprovalFileChange(
                    path=change.path,
                    change_kind=change.change_kind,
                    sensitive=self._is_sensitive_path(change.path),
                    diff=change.diff[:32_768],
                    truncated=len(change.diff) > 32_768,
                )
            )
        return tuple(result)

    def _file_change_digest(self, *, thread_id: str, turn_id: str, item_id: str) -> str | None:
        item = self._file_change_items.get((thread_id, turn_id, item_id))
        if item is None:
            return None
        return hashlib.sha256(item.model_dump_json().encode("utf-8")).hexdigest()

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
                return normalized if normalized not in {"", "."} else "."
        name = candidate.name
        return name if name else None

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
        approval_version = command.params.get("approvalVersion")
        if (
            not isinstance(approval_value, str)
            or not isinstance(decision, str)
            or not isinstance(approval_version, int)
            or isinstance(approval_version, bool)
        ):
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
            await self._close_pending_approval(pending, "expired")
            raise ValueError("审批已经过期。")
        if pending.app_server_instance_id != self._supervisor.handle.instance_id:
            raise ValueError("审批所属App Server代次已经失效。")
        if approval_version != pending.version:
            raise ValueError("审批对应的文件提议已经变更，请重新读取后处理。")
        if parsed_decision not in pending.display.allowed_actions:
            raise ValueError("审批决定不在该官方请求的允许动作内。")
        if (
            pending.file_change_digest is not None
            and parsed_decision
            in {CodexApprovalDecision.ACCEPT, CodexApprovalDecision.ACCEPT_FOR_SESSION}
            and pending.file_change_digest
            != self._file_change_digest(
                thread_id=pending.thread_id,
                turn_id=pending.turn_id,
                item_id=pending.item_id,
            )
        ):
            raise ValueError("审批对应的文件提议已经变更，请重新读取后处理。")
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

    async def _accept_protocol_warning(self, warning: AppServerProtocolWarning | str) -> None:
        warning_text = str(warning)
        warning_digest = hashlib.sha256(warning_text.encode("utf-8")).hexdigest()[:16]
        reason_code = (
            warning.reason_code
            if isinstance(warning, AppServerProtocolWarning)
            else "app_server_protocol_warning"
        )
        warning_method = warning.method if isinstance(warning, AppServerProtocolWarning) else None
        warning_key = (reason_code, warning_method)
        if (
            warning_key not in self._protocol_warning_counts
            and len(self._protocol_warning_counts) >= AGENT_PROTOCOL_WARNING_MAX_KEYS
        ):
            self._protocol_warning_counts.pop(next(iter(self._protocol_warning_counts)))
        warning_count = self._protocol_warning_counts.get(warning_key, 0) + 1
        self._protocol_warning_counts[warning_key] = warning_count
        handle = self._supervisor.handle
        if warning_count == 1 or warning_count & (warning_count - 1) == 0:
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
                        byte_count=len(warning_text.encode("utf-8")),
                        digest=warning_digest,
                        reason_code=reason_code,
                        method=warning_method,
                        count=warning_count,
                    ),
                ).to_log_line()
            )
        if self._protocol_version == CodexConnectionProtocolVersion.V2:
            await self._queue_v2_event(
                AgentProtocolWarningEventDetail(
                    reason_code=reason_code,
                    method=warning_method,
                    count=warning_count,
                )
            )
            return
        event = CodexAgentRealtimeEvent(
            host_id=self._settings.agent.host_id,
            app_server_instance_id=self._supervisor.handle.instance_id,
            occurred_at=datetime.now(UTC),
            method="internal/protocol.warning",
            params={
                "warning_digest": warning_digest,
                "reason_code": reason_code,
                "method": warning_method,
                "count": warning_count,
            },
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
        sender: CodexOutboundFrameSenderPort | None,
        result: CodexAgentCommandResult,
        command_type: str | None = None,
        command: CodexAgentCommand | None = None,
    ) -> None:
        if (
            result.outcome == "completed"
            and self._execution_resolved is not None
            and command is not None
        ):
            key = command.params.get("workspace_key")
            if isinstance(key, str) and command.command_type in {
                "thread.start",
                "thread.resume",
                "turn.start",
            }:
                self._project_execution.confirm(key, self._execution_resolved)
        if self._protocol_version == CodexConnectionProtocolVersion.V1:
            if sender is not None:
                await self._send_model(sender, AgentV1MessageType.COMMAND_RESULT.value, result)
            return
        thread_id, turn_id = read_upstream_identifiers(result.result)
        if thread_id is None and command is not None:
            requested_thread_id = command.params.get("threadId")
            if isinstance(requested_thread_id, str):
                thread_id = requested_thread_id
        if (
            command_type == "turn.start"
            and result.outcome == "completed"
            and thread_id
            and turn_id
            and self._execution_resolved is not None
        ):
            effective = self._execution_resolved
            access = {
                "danger-full-access": "完全访问",
                "workspace-write": "工作区写入",
                "read-only": "只读",
            }[effective.sandbox_mode.value]
            approval = {
                "never": "不请求普通命令审批",
                "untrusted": "不受信任的命令需要审批",
                "on-request": "按需审批",
            }.get(effective.approval_policy.value, effective.approval_policy.value)
            item = AppServerNoticeItem(
                item_id=f"execution-settings-{turn_id}",
                label="本轮执行设置",
                text=f"{effective.model or '本机默认模型'} · {effective.reasoning_effort or '默认推理强度'} · {access} · {approval}",
            )
            # 记录已经由上游接受的本轮参数；项目草稿再变化也不会改写此轮事实。
            # RPC 结果可能先于 turn/started 到达，先登记已确认的 turn，避免被孤项回收。
            self._timeline_store.capture(
                AppServerTurnChangedDetail(
                    thread_id=thread_id, turn_id=turn_id, status="inProgress"
                )
            )
            self._timeline_store.capture(
                AppServerItemChangedDetail(
                    thread_id=thread_id, turn_id=turn_id, item=item, status="completed"
                )
            )
            await self._queue_v2_event(
                AgentItemChangedEventDetail(
                    method=AppServerNotificationName.ITEM_COMPLETED,
                    thread_id=thread_id,
                    turn_id=turn_id,
                    item=item,
                    status="completed",
                )
            )
        typed_result: AgentCommandResultPayload | None = None
        if (
            command_type == "thread.read"
            and result.outcome == "completed"
            and result.result is not None
        ):
            product_result = self._sanitize_thread_read_product_result(
                self._app_server_protocol_adapter.adapt_thread_read_result(result.result)
            )
            if product_result.history_window is None:
                product_result = self._timeline_store.supplement(product_result)
            else:
                product_result = self._sanitize_thread_read_product_result(
                    self._timeline_store.refresh_history_window(product_result)
                )
            product_result = product_result.model_copy(
                update={
                    "source_epoch": self._event_epoch,
                    "source_seq": self._last_event_seq,
                }
            )
            typed_result = AgentThreadReadCommandResult(snapshot=product_result)
        if sender is None:
            return
        frame = self._protocol_codec.encode_v2(
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
        if (
            len(frame.model_dump_json().encode("utf-8"))
            > self._settings.agent.max_control_message_bytes
        ):
            detail = AgentCommandResultV2Detail(
                command_id=result.command_id,
                operation_id=result.operation_id,
                outcome="failed" if command_type in {"thread.read", "thread.list"} else "unknown",
                error_code="message_too_large",
                error_summary="命令结果超过网络消息容量。",
            )
            frame = self._protocol_codec.encode_v2(
                host_id=self._settings.agent.host_id,
                key_id=self._settings.agent.key_id,
                message_id=uuid4(),
                detail=detail,
            )
        await sender.send(frame)

    async def _queue_v2_event(self, detail: AgentEventDetail) -> None:
        if isinstance(detail, AgentItemDeltaEventDetail):
            candidate = AgentEventRecord(
                agent_event_epoch=self._event_epoch,
                seq=self._last_event_seq + 1,
                event_id=UUID(int=0),
                app_server_instance_id=UUID(self._supervisor.handle.instance_id),
                occurred_at=datetime.now(UTC),
                detail=detail,
            )
            batch = AgentEventBatchV2Detail(
                agent_event_epoch=self._event_epoch,
                first_seq=candidate.seq,
                last_seq=candidate.seq,
                events=(candidate,),
            )
            if self._event_batch_encoded_size(batch) > self._settings.agent.event_batch_max_bytes:
                if len(detail.delta) < 2:
                    raise CodexConnectionFrameTooLargeError("事件元数据超过批次容量。")
                middle = len(detail.delta) // 2
                await self._queue_v2_event(
                    detail.model_copy(update={"delta": detail.delta[:middle]})
                )
                await self._queue_v2_event(
                    detail.model_copy(update={"delta": detail.delta[middle:]})
                )
                return
        if not isinstance(detail, AgentItemDeltaEventDetail):
            candidate = AgentEventRecord(
                agent_event_epoch=self._event_epoch,
                seq=self._last_event_seq + 1,
                event_id=UUID(int=0),
                app_server_instance_id=UUID(self._supervisor.handle.instance_id),
                occurred_at=datetime.now(UTC),
                detail=detail,
            )
            candidate_batch = AgentEventBatchV2Detail(
                agent_event_epoch=self._event_epoch,
                first_seq=candidate.seq,
                last_seq=candidate.seq,
                events=(candidate,),
            )
            if (
                self._event_batch_encoded_size(candidate_batch)
                > self._content_budgets.max_receive_message_bytes
            ):
                if isinstance(detail, AgentApprovalOpenedEventDetail):
                    raise CodexConnectionFrameTooLargeError("审批超过协商消息容量。")
                detail = AgentProtocolWarningEventDetail(
                    reason_code="message_too_large", method=detail.kind
                )
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
        self._last_event_seq = 0
        self._event_ack = 0

    def _build_event_batcher(self) -> AgentEventBatcher:
        """按 Agent 强类型容量配置构建唯一事件批处理器。"""

        return AgentEventBatcher(
            window=timedelta(milliseconds=self._settings.agent.event_batch_window_milliseconds),
            max_bytes=self._settings.agent.event_batch_max_bytes,
            encoded_size=self._event_batch_encoded_size,
        )

    def _event_batch_encoded_size(self, batch: AgentEventBatchV2Detail) -> int:
        return len(
            self._protocol_codec.encode_v2(
                host_id=self._settings.agent.host_id,
                key_id=self._settings.agent.key_id,
                message_id=UUID(int=0),
                detail=batch,
            )
            .model_dump_json()
            .encode("utf-8")
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
        self._last_event_seq = self._journal.next_event_seq()
        return AgentEventRecord(
            agent_event_epoch=self._event_epoch,
            seq=self._last_event_seq,
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
            version=pending.version,
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
                        AppServerNotificationName.THREAD_SETTINGS_UPDATED,
                    ],
                    AppServerNotificationName(method),
                ),
                thread_id=detail.thread_id,
                display_name=detail.display_name,
                archived=detail.archived,
                execution_settings=detail.execution_settings,
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
                        AppServerNotificationName.FILE_PATCH_UPDATED,
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
