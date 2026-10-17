"""FastAPI Codex 长期连接运行时集合。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.application.codex.manage_device_authorization_usecase import (
    CleanupExpiredDeviceAuthorizationsUsecase,
    CreateDeviceAuthorizationUsecase,
    DecideDeviceAuthorizationUsecase,
    PollDeviceAuthorizationUsecase,
    ReadDeviceAuthorizationUsecase,
)
from src.application.codex.manage_device_challenge_usecase import (
    ConsumeAgentConnectionTicketUsecase,
    IssueDeviceChallengeUsecase,
    VerifyDeviceChallengeUsecase,
)
from src.application.codex.manage_enrollment_intent_usecase import (
    ManageCodexEnrollmentIntentUsecase,
)
from src.application.codex.manage_host_usecase import (
    RenameCodexHostUsecase,
    RevokeCodexHostUsecase,
)
from src.application.codex.record_client_diagnostic_usecase import (
    RecordCodexClientDiagnosticUsecase,
)
from src.application.codex.record_client_performance_usecase import (
    RecordCodexClientPerformanceUsecase,
)
from src.application.codex.start_device_key_rotation_usecase import (
    StartDeviceKeyRotationUsecase,
)
from src.application.codex.sync_agent_state_usecase import SyncCodexAgentStateUsecase
from src.application.codex.turn_runtime_coordinator import CodexTurnRuntimeCoordinator
from src.application.ports.codex_agent_revocation_signal_port import CodexAgentRevocationSignalPort
from src.application.ports.codex_command_payload_cipher_port import (
    CodexCommandPayloadCipherPort,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.application.ports.codex_device_authorization_store_port import (
    CodexDeviceAuthorizationStorePort,
)
from src.application.ports.codex_device_challenge_store_port import CodexDeviceChallengeStorePort
from src.application.ports.codex_enrollment_intent_store_port import (
    CodexEnrollmentIntentStorePort,
)
from src.application.ports.signature_verifier_port import SignatureVerifierPort
from src.application.ports.step_up_grant_port import StepUpGrantPort
from src.application.streaming.stream_access_ticket_service import StreamAccessTicketService
from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentApprovalOpened,
    CodexAgentRealtimeEvent,
)
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentApprovalOpenedEventDetail,
    AgentApprovalResolvedEventDetail,
)
from src.core.codex_contract.approval_contract import CodexApprovalKind
from src.core.codex_contract.codex_runtime_contract import CodexRuntimeSettings
from src.core.codex_contract.command_outbox_contract import CodexCommandOutboxSnapshot
from src.core.codex_contract.feature_flags_contract import CodexExperienceFeatureFlags
from src.core.codex_contract.instance_control_contract import (
    CodexDispatchSignalDetail,
    CodexRevokeSignalDetail,
)
from src.core.codex_contract.realtime_event_contract import (
    CodexRealtimeEventType,
    CodexThreadPatch,
)
from src.core.codex_contract.thread_contract import CodexThreadIndexSnapshot
from src.core.concurrency_contract.fenced_lease_contract import FencedLeasePort
from src.core.distributed_state_contract.atomic_state_contract import AtomicStatePort
from src.core.logging_contract.log_event_contract import (
    CodexExperienceFeatureFlagsLogDetail,
    LogEventEnvelope,
    LogEventHeader,
    LogEventKind,
    LogLevel,
)
from src.domain.codex.codex_compatibility_policy import CodexCompatibilityPolicy
from src.infrastructure.codex.agent_device_authentication import AgentDeviceAuthenticationGuard
from src.infrastructure.codex.codex_active_host_service import CodexActiveHostService
from src.infrastructure.codex.codex_agent_credential_service import (
    CodexAgentCredentialService,
)
from src.infrastructure.codex.codex_agent_event_buffer import CodexAgentEventBuffer
from src.infrastructure.codex.codex_agent_event_cursor_store import (
    CodexAgentEventCursorStore,
)
from src.infrastructure.codex.codex_agent_revocation_signal import CodexAgentRevocationSignal
from src.infrastructure.codex.codex_browser_event_hub import CodexBrowserEventHub
from src.infrastructure.codex.codex_client_diagnostic_recorder import (
    CodexClientDiagnosticRecorder,
)
from src.infrastructure.codex.codex_client_diagnostic_retention_cleaner import (
    CodexClientDiagnosticRetentionCleaner,
)
from src.infrastructure.codex.codex_client_performance_recorder import (
    CodexClientPerformanceRecorder,
)
from src.infrastructure.codex.codex_command_outbox_dispatcher import (
    CodexCommandOutboxDispatcher,
)
from src.infrastructure.codex.codex_connection_registry import CodexConnectionRegistry
from src.infrastructure.codex.codex_device_authorization_store import CodexDeviceAuthorizationStore
from src.infrastructure.codex.codex_device_challenge_store import CodexDeviceChallengeStore
from src.infrastructure.codex.codex_enrollment_intent_store import CodexEnrollmentIntentStore
from src.infrastructure.codex.codex_host_actor import CodexHostActorRegistry
from src.infrastructure.codex.codex_host_presence_adapter import CodexHostPresenceAdapter
from src.infrastructure.codex.codex_instance_control_signal_adapter import (
    CodexInstanceControlSignalAdapter,
)
from src.infrastructure.codex.codex_pairing_service import CodexPairingService
from src.infrastructure.codex.codex_protocol_mapper import CodexProductEvent, CodexProtocolMapper
from src.infrastructure.codex.codex_realtime_stream_adapter import CodexRealtimeStreamAdapter
from src.infrastructure.codex_agent.app_server_manifest_registry import (
    AppServerManifestRegistry,
)
from src.infrastructure.key_management.sensitive_digest_service import SensitiveDigestService
from src.infrastructure.observability.prometheus_metrics_registry import (
    PrometheusMetricsRegistry,
)
from src.infrastructure.outbox.reliable_outbox_runner import AsyncReliableOutboxRunner
from src.infrastructure.streaming.deferred_stream_resources import DeferredStreamStateStore
from src.infrastructure.streaming.stream_step_up_grant_adapter import StreamStepUpGrantAdapter

DEFAULT_APP_SERVER_PROTOCOL_ROOT = (
    Path(__file__).resolve().parents[3] / "protocol" / "codex_app_server"
)
CODEX_EXPERIENCE_FEATURE_FLAGS_LOG_MESSAGE = "Codex体验开关决策"
CODEX_EXPERIENCE_FEATURE_FLAGS_SOURCE_MODULE = "infrastructure"
CODEX_EXPERIENCE_FEATURE_FLAGS_SOURCE_COMPONENT = "codex_control_runtime"


@dataclass(slots=True)
class CodexAgentEventPublication:
    """保留一条已按 Agent 顺序同步的事件，待整批 fan-out。"""

    event: CodexAgentRealtimeEvent
    updated_thread: CodexThreadIndexSnapshot | None
    overflowed: bool
    approval_events: tuple[CodexProductEvent, ...] = ()


@dataclass(slots=True)
class CodexControlRuntime:
    """连接注册表、host actor 与设备认证的稳定运行时集合。"""

    settings: CodexRuntimeSettings
    instance_id: UUID
    connection_registry: CodexConnectionRegistry
    actor_registry: CodexHostActorRegistry
    authentication_guard: AgentDeviceAuthenticationGuard
    state_synchronizer: SyncCodexAgentStateUsecase
    turn_runtime_coordinator: CodexTurnRuntimeCoordinator
    event_buffer: CodexAgentEventBuffer
    event_cursor_store: CodexAgentEventCursorStore
    browser_event_hub: CodexBrowserEventHub
    realtime_stream_adapter: CodexRealtimeStreamAdapter
    protocol_mapper: CodexProtocolMapper
    control_port: CodexControlPort
    pairing_service: CodexPairingService
    step_up_grant_service: StepUpGrantPort
    compatibility_policy: CodexCompatibilityPolicy
    stream_ticket_service: StreamAccessTicketService
    device_authorization_store: CodexDeviceAuthorizationStorePort
    device_challenge_store: CodexDeviceChallengeStorePort
    enrollment_intent_store: CodexEnrollmentIntentStorePort
    revocation_signal: CodexAgentRevocationSignalPort
    create_device_authorization: CreateDeviceAuthorizationUsecase
    poll_device_authorization: PollDeviceAuthorizationUsecase
    read_device_authorization: ReadDeviceAuthorizationUsecase
    decide_device_authorization: DecideDeviceAuthorizationUsecase
    issue_device_challenge: IssueDeviceChallengeUsecase
    verify_device_challenge: VerifyDeviceChallengeUsecase
    consume_agent_connection_ticket: ConsumeAgentConnectionTicketUsecase
    rename_host: RenameCodexHostUsecase
    revoke_host: RevokeCodexHostUsecase
    start_device_key_rotation: StartDeviceKeyRotationUsecase
    cleanup_expired_device_authorizations: CleanupExpiredDeviceAuthorizationsUsecase
    manage_enrollment_intent: ManageCodexEnrollmentIntentUsecase
    record_client_diagnostic: RecordCodexClientDiagnosticUsecase
    record_client_performance: RecordCodexClientPerformanceUsecase
    client_diagnostic_retention_cleaner: CodexClientDiagnosticRetentionCleaner
    active_host: CodexActiveHostService
    presence_adapter: CodexHostPresenceAdapter
    instance_control_signal_adapter: CodexInstanceControlSignalAdapter
    outbox_dispatcher: CodexCommandOutboxDispatcher
    outbox_runner: AsyncReliableOutboxRunner[CodexCommandOutboxSnapshot]
    logger: logging.Logger
    feature_flag_log_event_emitter: Callable[[LogEventEnvelope], None] | None
    _signal_reader_task: asyncio.Task[None] | None = None
    _turn_runtime_watchdog_task: asyncio.Task[None] | None = None
    _client_diagnostic_retention_task: asyncio.Task[None] | None = None
    _runtime_stop_event: asyncio.Event | None = None

    @classmethod
    def build(
        cls,
        *,
        settings: CodexRuntimeSettings,
        credential_service: CodexAgentCredentialService,
        control_port: CodexControlPort,
        atomic_state: AtomicStatePort,
        fenced_lease_store: FencedLeasePort,
        stream_state_store: DeferredStreamStateStore,
        sensitive_digest_service: SensitiveDigestService,
        signature_verifier: SignatureVerifierPort,
        command_payload_cipher: CodexCommandPayloadCipherPort,
        logger: logging.Logger,
        diagnostic_log_event_emitter: Callable[[LogEventEnvelope], None] | None = None,
        metrics_registry_provider: Callable[[], PrometheusMetricsRegistry | None] | None = None,
        protocol_root: Path = DEFAULT_APP_SERVER_PROTOCOL_ROOT,
    ) -> CodexControlRuntime:
        """按同一配置构造互相绑定的运行时组件。"""

        connection_registry = CodexConnectionRegistry(
            max_connected_agents=settings.max_connected_agents
        )
        instance_id = uuid4()
        presence_adapter = CodexHostPresenceAdapter(
            store=fenced_lease_store,
            ttl_seconds=settings.agent_offline_after_seconds,
        )
        active_host = CodexActiveHostService(atomic_state, control_port)
        actor_registry = CodexHostActorRegistry(connection_registry)
        instance_control_signal_adapter = CodexInstanceControlSignalAdapter(
            store=stream_state_store,
            ttl_seconds=settings.instance_control_stream_ttl_seconds,
            max_events=settings.instance_control_stream_max_events,
        )
        outbox_dispatcher = CodexCommandOutboxDispatcher(
            active_host=active_host,
            control_port=control_port,
            payload_cipher=command_payload_cipher,
            presence=presence_adapter,
            connection_registry=connection_registry,
            actor_registry=actor_registry,
            signal_adapter=instance_control_signal_adapter,
            instance_id=instance_id,
            ack_timeout_seconds=settings.agent_rpc_ack_timeout_seconds,
            retry_seconds=settings.command_outbox_retry_seconds,
            completed_retention_seconds=(settings.command_outbox_completed_retention_seconds),
        )
        outbox_runner = AsyncReliableOutboxRunner(
            adapter=outbox_dispatcher,
            logger=logging.getLogger("codex_command_outbox"),
            interval_seconds=settings.command_outbox_scan_interval_seconds,
            stale_seconds=settings.command_outbox_retry_seconds,
            batch_limit=settings.command_outbox_batch_size,
        )
        stream_ticket_service = StreamAccessTicketService(
            state_store=stream_state_store,
            ttl_seconds=settings.realtime_ticket_ttl_seconds,
        )
        step_up_grant_service = StreamStepUpGrantAdapter(
            ticket_service=StreamAccessTicketService(
                state_store=stream_state_store,
                ttl_seconds=settings.step_up_grant_ttl_seconds,
            )
        )
        device_authorization_store = CodexDeviceAuthorizationStore(
            state=atomic_state,
            digest_service=sensitive_digest_service,
        )
        device_challenge_store = CodexDeviceChallengeStore(state=atomic_state)
        enrollment_intent_store = CodexEnrollmentIntentStore(
            state=atomic_state,
            digest_service=sensitive_digest_service,
        )
        revocation_signal = CodexAgentRevocationSignal(
            state=atomic_state,
            connection_registry=connection_registry,
            presence=presence_adapter,
            signal_adapter=instance_control_signal_adapter,
            instance_id=instance_id,
        )
        create_device_authorization = CreateDeviceAuthorizationUsecase(
            store=device_authorization_store,
            digest_service=sensitive_digest_service,
            signature_verifier=signature_verifier,
            ttl_seconds=settings.device_authorization_ttl_seconds,
            poll_interval_seconds=settings.device_authorization_poll_interval_seconds,
            maximum_create_attempts=settings.device_authorization_create_attempts,
        )
        verify_device_challenge = VerifyDeviceChallengeUsecase(
            store=device_challenge_store,
            control_port=control_port,
            signature_verifier=signature_verifier,
            ticket_service=stream_ticket_service,
        )
        realtime_stream_adapter = CodexRealtimeStreamAdapter(
            store=stream_state_store,
            ttl_seconds=settings.browser_event_replay_ttl_seconds,
            max_events=settings.browser_event_replay_max_events,
        )
        return cls(
            settings=settings,
            instance_id=instance_id,
            connection_registry=connection_registry,
            actor_registry=actor_registry,
            authentication_guard=AgentDeviceAuthenticationGuard(verifier=credential_service),
            state_synchronizer=SyncCodexAgentStateUsecase(
                control_port,
                max_workspaces_per_host=settings.max_workspaces_per_host,
            ),
            turn_runtime_coordinator=CodexTurnRuntimeCoordinator(
                control_port=control_port,
                lease_store=fenced_lease_store,
                lease_ttl_seconds=settings.turn_runtime_lease_ttl_seconds,
                stalled_after_seconds=settings.turn_runtime_stalled_after_seconds,
            ),
            event_buffer=CodexAgentEventBuffer(capacity=settings.agent_event_replay_buffer_size),
            event_cursor_store=CodexAgentEventCursorStore(state=atomic_state),
            browser_event_hub=CodexBrowserEventHub(
                queue_capacity=settings.browser_event_queue_size,
                distributed_stream=realtime_stream_adapter,
            ),
            realtime_stream_adapter=realtime_stream_adapter,
            protocol_mapper=CodexProtocolMapper(),
            control_port=control_port,
            pairing_service=CodexPairingService(control_port=control_port, settings=settings),
            step_up_grant_service=step_up_grant_service,
            compatibility_policy=AppServerManifestRegistry(protocol_root).build_policy(
                minimum_codex_version=settings.minimum_codex_version,
                blocked_codex_versions=settings.blocked_codex_versions,
            ),
            stream_ticket_service=stream_ticket_service,
            device_authorization_store=device_authorization_store,
            device_challenge_store=device_challenge_store,
            enrollment_intent_store=enrollment_intent_store,
            revocation_signal=revocation_signal,
            create_device_authorization=create_device_authorization,
            poll_device_authorization=PollDeviceAuthorizationUsecase(
                store=device_authorization_store,
                maximum_poll_attempts=settings.device_authorization_max_poll_attempts,
            ),
            read_device_authorization=ReadDeviceAuthorizationUsecase(
                store=device_authorization_store,
            ),
            decide_device_authorization=DecideDeviceAuthorizationUsecase(
                store=device_authorization_store,
                control_port=control_port,
                key_rotation_grace_seconds=settings.device_key_rotation_grace_seconds,
                max_hosts_per_user=settings.max_hosts_per_user,
            ),
            issue_device_challenge=IssueDeviceChallengeUsecase(
                store=device_challenge_store,
                control_port=control_port,
                ttl_seconds=settings.device_challenge_ttl_seconds,
            ),
            verify_device_challenge=verify_device_challenge,
            consume_agent_connection_ticket=ConsumeAgentConnectionTicketUsecase(
                ticket_service=stream_ticket_service,
                control_port=control_port,
            ),
            rename_host=RenameCodexHostUsecase(control_port=control_port),
            revoke_host=RevokeCodexHostUsecase(
                control_port=control_port,
                step_up_port=step_up_grant_service,
                revocation_signal=revocation_signal,
            ),
            start_device_key_rotation=StartDeviceKeyRotationUsecase(
                challenge_verifier=verify_device_challenge,
                authorization_creator=create_device_authorization,
            ),
            cleanup_expired_device_authorizations=CleanupExpiredDeviceAuthorizationsUsecase(
                control_port=control_port,
                pending_ttl_seconds=settings.device_authorization_ttl_seconds,
            ),
            manage_enrollment_intent=ManageCodexEnrollmentIntentUsecase(
                store=enrollment_intent_store,
                device_authorization_store=device_authorization_store,
                create_device_authorization=create_device_authorization,
                digest_service=sensitive_digest_service,
                ttl_seconds=settings.enrollment_intent_ttl_seconds,
                maximum_create_attempts=settings.device_authorization_create_attempts,
            ),
            record_client_diagnostic=RecordCodexClientDiagnosticUsecase(
                CodexClientDiagnosticRecorder(
                    logger=logger,
                    log_event_emitter=diagnostic_log_event_emitter,
                    metrics_registry_provider=metrics_registry_provider,
                )
            ),
            record_client_performance=RecordCodexClientPerformanceUsecase(
                CodexClientPerformanceRecorder(
                    logger=logger,
                    log_event_emitter=diagnostic_log_event_emitter,
                    metrics_registry_provider=metrics_registry_provider,
                )
            ),
            client_diagnostic_retention_cleaner=CodexClientDiagnosticRetentionCleaner(
                control_port=control_port,
                error_retention_days=settings.client_diagnostic_error_retention_days,
                performance_retention_days=settings.client_diagnostic_performance_retention_days,
            ),
            active_host=active_host,
            presence_adapter=presence_adapter,
            instance_control_signal_adapter=instance_control_signal_adapter,
            outbox_dispatcher=outbox_dispatcher,
            outbox_runner=outbox_runner,
            logger=logger,
            feature_flag_log_event_emitter=diagnostic_log_event_emitter,
        )

    def record_experience_feature_flag_decisions(
        self,
        flags: CodexExperienceFeatureFlags,
    ) -> None:
        """记录服务端实际批准的开关决策，不记录请求或主体标识。

        开关读取是浏览器加载和重试期间的低频控制面操作。日志仅写固定词表中的
        开关状态、默认值、回退路径和删除条件，因而不能携带会话正文、URL、令牌或
        认证主体；未装配结构化发射器时保留相同低基数信息的标准日志兜底。

        :param flags: 当前运行时批准的封闭体验开关值。
        :type flags: CodexExperienceFeatureFlags
        """

        decisions = flags.decisions()
        if self.feature_flag_log_event_emitter is not None:
            self.feature_flag_log_event_emitter(
                LogEventEnvelope(
                    header=LogEventHeader(
                        event_id=str(uuid4()),
                        occurred_at=datetime.now(UTC),
                        level=LogLevel.INFO,
                        kind=LogEventKind.CODEX_EXPERIENCE_FEATURE_FLAGS,
                        message=CODEX_EXPERIENCE_FEATURE_FLAGS_LOG_MESSAGE,
                        source_module=CODEX_EXPERIENCE_FEATURE_FLAGS_SOURCE_MODULE,
                        source_component=CODEX_EXPERIENCE_FEATURE_FLAGS_SOURCE_COMPONENT,
                    ),
                    detail=CodexExperienceFeatureFlagsLogDetail(decisions=decisions),
                )
            )
            return
        self.logger.info(
            "%s decisions=%s",
            CODEX_EXPERIENCE_FEATURE_FLAGS_LOG_MESSAGE,
            tuple(
                (
                    decision.name.value,
                    decision.enabled,
                    decision.default_enabled,
                    decision.fallback_path.value,
                    decision.deletion_condition.value,
                )
                for decision in decisions
            ),
        )

    async def start(self) -> None:
        """统一流资源就绪后启动 outbox 与实例信号 reader。"""

        if self._signal_reader_task is not None:
            return
        self._runtime_stop_event = asyncio.Event()
        self.outbox_runner.start()
        self._signal_reader_task = asyncio.create_task(self._run_instance_control_reader())
        self._turn_runtime_watchdog_task = asyncio.create_task(self._run_turn_runtime_watchdog())
        self._client_diagnostic_retention_task = asyncio.create_task(
            self._run_client_diagnostic_retention_cleanup()
        )

    async def _run_instance_control_reader(self) -> None:
        cursor: str | None = None
        stop_event = self._runtime_stop_event
        if stop_event is None:
            raise RuntimeError("Codex运行时停止事件尚未初始化。")
        while not stop_event.is_set():
            try:
                signals, next_cursor, gap = await self.instance_control_signal_adapter.read(
                    instance_id=self.instance_id,
                    after_cursor=cursor,
                    limit=self.settings.instance_control_read_limit,
                )
                if gap:
                    self.outbox_runner.notify()
                    cursor = None
                else:
                    cursor = next_cursor
                    for signal in signals:
                        if isinstance(signal.detail, CodexDispatchSignalDetail):
                            await self.outbox_dispatcher.dispatch_signaled(
                                command_id=signal.detail.command_id,
                                route_fencing_token=signal.detail.route_fencing_token,
                            )
                        elif isinstance(signal.detail, CodexRevokeSignalDetail):
                            await self.connection_registry.revoke(signal.detail.host_id)
            except Exception:
                logging.getLogger("codex_instance_control").exception("Codex实例控制信号读取失败。")
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.settings.command_outbox_scan_interval_seconds,
                )
            except TimeoutError:
                continue

    async def _run_turn_runtime_watchdog(self) -> None:
        """按固定间隔标记失去租约且长期无活动的 turn。"""

        stop_event = self._runtime_stop_event
        if stop_event is None:
            raise RuntimeError("Codex运行时停止事件尚未初始化。")
        logger = logging.getLogger("codex_turn_runtime_watchdog")
        while not stop_event.is_set():
            try:
                updated_threads = await self.turn_runtime_coordinator.mark_expired_turns_stalled()
                for thread in updated_threads:
                    await self.publish_thread_updated(
                        owner_subject_id=thread.owner_subject_id,
                        thread=thread,
                        occurred_at=thread.turn_runtime.last_activity_at
                        if thread.turn_runtime is not None
                        else datetime.now(UTC),
                    )
            except Exception:
                logger.exception("Codex turn watchdog执行失败。")
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.settings.turn_runtime_watchdog_seconds,
                )
            except TimeoutError:
                continue

    async def _run_client_diagnostic_retention_cleanup(self) -> None:
        """定期清理过期诊断，失败时保持运行并在下个周期重试。"""

        stop_event = self._runtime_stop_event
        if stop_event is None:
            raise RuntimeError("Codex运行时停止事件尚未初始化。")
        logger = logging.getLogger("codex_client_diagnostic_retention")
        while not stop_event.is_set():
            try:
                result = await asyncio.to_thread(
                    self.client_diagnostic_retention_cleaner.cleanup_expired_records
                )
                logger.info(
                    "Codex客户端诊断留存清理完成：错误=%s 性能=%s",
                    result.deleted_error_record_count,
                    result.deleted_performance_record_count,
                )
            except Exception:
                # 清理是可重入删除，不影响会话操作；下一个间隔会自然重试。
                logger.exception("Codex客户端诊断留存清理失败，将在下个周期重试。")
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.settings.client_diagnostic_cleanup_interval_seconds,
                )
            except TimeoutError:
                continue

    async def publish_agent_event(
        self,
        event: CodexAgentRealtimeEvent,
        principal: AgentDevicePrincipal,
    ) -> None:
        """兼容旧单事件入口，并使用统一批次路径保持相同状态语义。"""

        await self.publish_agent_events((event,), principal)

    async def publish_agent_events(
        self,
        events: tuple[CodexAgentRealtimeEvent, ...],
        principal: AgentDevicePrincipal,
    ) -> None:
        """按 Agent v2 的有序边界同步控制面，并只向 hub 提交一次产品事件集合。"""

        if not events:
            return
        publications: list[CodexAgentEventPublication] = []
        for event in events:
            if isinstance(event.detail, AgentApprovalResolvedEventDetail):
                approval = await asyncio.to_thread(
                    self.state_synchronizer.accept_approval_resolved,
                    event.detail,
                    event.host_id,
                    principal,
                )
                resolved_events: list[CodexProductEvent] = []
                if approval is not None:
                    resumed = await self.turn_runtime_coordinator.observe_approval_resolved(
                        approval
                    )
                    resolved_events.append(
                        CodexProductEvent(
                            host_id=approval.host_id,
                            workspace_id=approval.workspace_id,
                            thread_id=approval.thread_id,
                            turn_id=approval.turn_id,
                            item_id=approval.item_id,
                            event_type=CodexRealtimeEventType.APPROVAL_RESOLVED,
                            payload={"approval": approval.model_dump(mode="json")},
                            occurred_at=event.occurred_at,
                        )
                    )
                    if resumed is not None:
                        resolved_events.append(
                            self._build_thread_updated_product_event(
                                resumed, occurred_at=event.occurred_at
                            )
                        )
                publications.append(
                    CodexAgentEventPublication(
                        event=event,
                        updated_thread=None,
                        overflowed=await self.event_buffer.publish(event, principal),
                        approval_events=tuple(resolved_events),
                    )
                )
                continue
            if isinstance(event.detail, AgentApprovalOpenedEventDetail):
                approval_events = await self._prepare_approval_opened(event, principal)
                overflowed = await self.event_buffer.publish(event, principal)
                publications.append(
                    CodexAgentEventPublication(
                        event=event,
                        updated_thread=None,
                        overflowed=overflowed,
                        approval_events=approval_events,
                    )
                )
                continue
            runtime_outcome = await self.turn_runtime_coordinator.observe_agent_event(
                event, principal
            )
            if runtime_outcome.handled and not runtime_outcome.accepted:
                continue
            updated_thread = runtime_outcome.thread
            if not runtime_outcome.handled:
                # Approval handling reads the persisted thread immediately.
                # Keep ordinary events ahead of it in the same Agent batch so
                # its runtime snapshot cannot reintroduce earlier metadata.
                updated_thread = await asyncio.to_thread(
                    self.state_synchronizer.accept_realtime_event,
                    event,
                    principal,
                )
            publications.append(
                CodexAgentEventPublication(
                    event=event,
                    updated_thread=updated_thread,
                    overflowed=await self.event_buffer.publish(event, principal),
                )
            )
        product_events: list[CodexProductEvent] = []
        for publication in publications:
            workspace_id: UUID | None
            if publication.approval_events:
                product_events.extend(publication.approval_events)
                workspace_id = publication.approval_events[0].workspace_id
            else:
                workspace_id = (
                    publication.updated_thread.workspace_id
                    if publication.updated_thread is not None
                    else await asyncio.to_thread(
                        self._find_workspace_id,
                        publication.event,
                        principal.owner_subject_id,
                    )
                )
                if publication.updated_thread is not None:
                    product_events.append(
                        self._build_thread_updated_product_event(
                            publication.updated_thread,
                            occurred_at=publication.event.occurred_at,
                        )
                    )
                product_event = self.protocol_mapper.map_event(
                    publication.event,
                    workspace_id=workspace_id,
                )
                if product_event is not None:
                    product_events.append(product_event)
            if publication.overflowed:
                product_events.append(
                    CodexProductEvent(
                        host_id=publication.event.host_id,
                        workspace_id=workspace_id,
                        thread_id=None,
                        turn_id=None,
                        item_id=None,
                        event_type=CodexRealtimeEventType.STREAM_GAP_DETECTED,
                        payload={"reason": "agent_event_buffer_overflow"},
                        occurred_at=publication.event.occurred_at,
                    )
                )
        await self.browser_event_hub.publish_batch(
            principal.owner_subject_id,
            tuple(product_events),
        )

    async def publish_thread_updated(
        self,
        *,
        owner_subject_id: str,
        thread: CodexThreadIndexSnapshot,
        occurred_at: datetime,
    ) -> None:
        """向浏览器发布数据库确认后的会话索引局部更新。"""

        await self.browser_event_hub.publish(
            owner_subject_id,
            self._build_thread_updated_product_event(thread, occurred_at=occurred_at),
        )

    def _build_thread_updated_product_event(
        self,
        thread: CodexThreadIndexSnapshot,
        *,
        occurred_at: datetime,
    ) -> CodexProductEvent:
        """构造已提交线程投影，供单事件与 Agent 批次路径复用。"""

        patch = CodexThreadPatch(
            host_id=thread.host_id,
            workspace_id=thread.workspace_id,
            upstream_thread_id=thread.upstream_thread_id,
            display_name=thread.display_name,
            title_source=thread.title_source.value,
            model=thread.model,
            model_provider=thread.model_provider,
            reasoning_effort=thread.reasoning_effort,
            status=thread.status,
            active_turn_id=thread.active_turn_id,
            turn_runtime=thread.turn_runtime,
            archived=thread.archived,
            is_pinned=thread.is_pinned,
            created_at=thread.created_at,
            recency_at=thread.recency_at,
            updated_at=thread.updated_at,
        )
        return CodexProductEvent(
            host_id=thread.host_id,
            workspace_id=thread.workspace_id,
            thread_id=thread.upstream_thread_id,
            turn_id=thread.active_turn_id,
            item_id=None,
            event_type=CodexRealtimeEventType.THREAD_UPDATED,
            payload={"thread": patch.model_dump(mode="json")},
            occurred_at=occurred_at,
        )

    async def publish_host_status_changed(
        self,
        *,
        owner_subject_id: str,
        host_id: UUID,
        status: str,
        last_seen_at: datetime | None,
    ) -> None:
        """向浏览器推送控制面 host 可投递状态变化。"""

        if status == "online" and not await self.active_host.permits(owner_subject_id, host_id):
            status = "offline"
        await self.browser_event_hub.publish(
            owner_subject_id,
            CodexProductEvent(
                host_id=host_id,
                workspace_id=None,
                thread_id=None,
                turn_id=None,
                item_id=None,
                event_type=CodexRealtimeEventType.HOST_STATUS_CHANGED,
                payload={
                    "host_id": str(host_id),
                    "status": status,
                    "last_seen_at": (
                        last_seen_at.isoformat() if last_seen_at is not None else None
                    ),
                },
            ),
        )

    async def publish_approval_opened(
        self,
        approval: CodexAgentApprovalOpened,
        principal: AgentDevicePrincipal,
    ) -> None:
        """把已脱敏审批按设备所有者发送给浏览器。"""

        await self.browser_event_hub.publish_batch(
            principal.owner_subject_id,
            await self._prepare_approval_opened_from_approval(approval, principal),
        )

    async def _prepare_approval_opened(
        self,
        event: CodexAgentRealtimeEvent,
        principal: AgentDevicePrincipal,
    ) -> tuple[CodexProductEvent, ...]:
        """将 v2 审批记录收敛为同一 Agent 批次内的屏障产品事件。"""

        detail = event.detail
        if not isinstance(detail, AgentApprovalOpenedEventDetail):
            raise ValueError("批次审批事件缺少AgentApprovalOpenedEventDetail。")
        approval = detail.approval
        return await self._prepare_approval_opened_from_approval(
            CodexAgentApprovalOpened(
                approval_id=approval.approval_id,
                host_id=event.host_id,
                app_server_instance_id=str(approval.app_server_instance_id),
                approval_kind=CodexApprovalKind(approval.approval_kind),
                thread_id=approval.thread_id,
                turn_id=approval.turn_id,
                item_id=approval.item_id,
                risk_level=approval.display.risk_level,
                payload_digest=approval.payload_digest,
                version=approval.version,
                display_summary=approval.display,
                expires_at=approval.expires_at,
            ),
            principal,
        )

    async def _prepare_approval_opened_from_approval(
        self,
        approval: CodexAgentApprovalOpened,
        principal: AgentDevicePrincipal,
    ) -> tuple[CodexProductEvent, ...]:
        """完成审批权威写入并返回待广播事件，调用方负责保持其批次顺序。"""

        runtime_thread = await self.turn_runtime_coordinator.observe_approval_opened(
            approval,
            principal,
        )
        if runtime_thread is None:
            return ()
        await asyncio.to_thread(
            self.state_synchronizer.accept_approval_opened,
            approval,
            principal,
        )
        return await asyncio.to_thread(self._read_approval_publication, approval, principal)

    def _read_approval_publication(
        self,
        approval: CodexAgentApprovalOpened,
        principal: AgentDevicePrincipal,
    ) -> tuple[CodexProductEvent, ...]:
        """完整同步读取闭包，session不跨线程。"""
        unit_of_work = self.control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            thread = self.control_port.create_codex_thread_repository(
                session
            ).get_by_upstream_id_and_owner(
                approval.host_id,
                approval.thread_id,
                principal.owner_subject_id,
            )
            persisted_approval = self.control_port.create_codex_approval_repository(
                session
            ).get_by_id_and_owner(
                approval.approval_id,
                principal.owner_subject_id,
            )
        finally:
            unit_of_work.dispose()
        if thread is None or persisted_approval is None:
            return ()
        return (
            CodexProductEvent(
                host_id=approval.host_id,
                workspace_id=thread.workspace_id,
                thread_id=approval.thread_id,
                turn_id=approval.turn_id,
                item_id=approval.item_id,
                event_type=CodexRealtimeEventType.APPROVAL_OPENED,
                payload={"approval": persisted_approval.model_dump(mode="json")},
            ),
            self._build_thread_updated_product_event(
                thread,
                occurred_at=thread.recency_at,
            ),
        )

    def _find_workspace_id(
        self,
        event: CodexAgentRealtimeEvent,
        owner_subject_id: str,
    ) -> UUID | None:
        params = (
            cast(Mapping[str, JsonValue], event.params) if isinstance(event.params, Mapping) else {}
        )
        thread_id = params.get("threadId")
        nested_thread = params.get("thread")
        if not isinstance(thread_id, str) and isinstance(nested_thread, Mapping):
            nested_id = cast(Mapping[str, object], nested_thread).get("id")
            thread_id = nested_id if isinstance(nested_id, str) else None
        if not isinstance(thread_id, str):
            return None
        unit_of_work = self.control_port.create_unit_of_work()
        try:
            repository = self.control_port.create_codex_thread_repository(
                unit_of_work.get_session()
            )
            thread = repository.get_by_upstream_id_and_owner(
                event.host_id,
                thread_id,
                owner_subject_id,
            )
            return None if thread is None else thread.workspace_id
        finally:
            unit_of_work.dispose()

    async def shutdown(self) -> None:
        """先停止新操作，再通知所有 Agent 会话关闭。"""

        await self.connection_registry.shutdown()
        if self._runtime_stop_event is not None:
            self._runtime_stop_event.set()
        if self._signal_reader_task is not None:
            await self._signal_reader_task
            self._signal_reader_task = None
        if self._turn_runtime_watchdog_task is not None:
            await self._turn_runtime_watchdog_task
            self._turn_runtime_watchdog_task = None
        if self._client_diagnostic_retention_task is not None:
            await self._client_diagnostic_retention_task
            self._client_diagnostic_retention_task = None
        await self.outbox_runner.shutdown()
        await self.browser_event_hub.shutdown()
