"""FastAPI Codex 长期连接运行时集合。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
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
from src.application.codex.manage_host_usecase import (
    RenameCodexHostUsecase,
    RevokeCodexHostUsecase,
)
from src.application.codex.start_device_key_rotation_usecase import (
    StartDeviceKeyRotationUsecase,
)
from src.application.codex.sync_agent_state_usecase import SyncCodexAgentStateUsecase
from src.application.ports.codex_agent_revocation_signal_port import CodexAgentRevocationSignalPort
from src.application.ports.codex_command_payload_cipher_port import (
    CodexCommandPayloadCipherPort,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.application.ports.codex_device_authorization_store_port import (
    CodexDeviceAuthorizationStorePort,
)
from src.application.ports.codex_device_challenge_store_port import CodexDeviceChallengeStorePort
from src.application.ports.signature_verifier_port import SignatureVerifierPort
from src.application.ports.step_up_grant_port import StepUpGrantPort
from src.application.streaming.stream_access_ticket_service import StreamAccessTicketService
from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentApprovalOpened,
    CodexAgentRealtimeEvent,
)
from src.core.codex_contract.codex_runtime_contract import CodexRuntimeSettings
from src.core.codex_contract.command_outbox_contract import CodexCommandOutboxSnapshot
from src.core.codex_contract.instance_control_contract import (
    CodexDispatchSignalDetail,
    CodexRevokeSignalDetail,
)
from src.core.codex_contract.realtime_event_contract import CodexRealtimeEventType
from src.core.concurrency_contract.fenced_lease_contract import FencedLeasePort
from src.core.distributed_state_contract.atomic_state_contract import AtomicStatePort
from src.domain.codex.codex_compatibility_policy import CodexCompatibilityPolicy
from src.infrastructure.codex.agent_device_authentication import AgentDeviceAuthenticationGuard
from src.infrastructure.codex.codex_agent_credential_service import (
    CodexAgentCredentialService,
)
from src.infrastructure.codex.codex_agent_event_buffer import CodexAgentEventBuffer
from src.infrastructure.codex.codex_agent_event_cursor_store import (
    CodexAgentEventCursorStore,
)
from src.infrastructure.codex.codex_agent_revocation_signal import CodexAgentRevocationSignal
from src.infrastructure.codex.codex_browser_event_hub import CodexBrowserEventHub
from src.infrastructure.codex.codex_command_outbox_dispatcher import (
    CodexCommandOutboxDispatcher,
)
from src.infrastructure.codex.codex_connection_registry import CodexConnectionRegistry
from src.infrastructure.codex.codex_device_authorization_store import CodexDeviceAuthorizationStore
from src.infrastructure.codex.codex_device_challenge_store import CodexDeviceChallengeStore
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
from src.infrastructure.outbox.reliable_outbox_runner import AsyncReliableOutboxRunner
from src.infrastructure.streaming.deferred_stream_resources import DeferredStreamStateStore
from src.infrastructure.streaming.stream_step_up_grant_adapter import StreamStepUpGrantAdapter

DEFAULT_APP_SERVER_PROTOCOL_ROOT = (
    Path(__file__).resolve().parents[3] / "protocol" / "codex_app_server"
)


@dataclass(slots=True)
class CodexControlRuntime:
    """连接注册表、host actor 与设备认证的稳定运行时集合。"""

    settings: CodexRuntimeSettings
    instance_id: UUID
    connection_registry: CodexConnectionRegistry
    actor_registry: CodexHostActorRegistry
    authentication_guard: AgentDeviceAuthenticationGuard
    state_synchronizer: SyncCodexAgentStateUsecase
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
    presence_adapter: CodexHostPresenceAdapter
    instance_control_signal_adapter: CodexInstanceControlSignalAdapter
    outbox_dispatcher: CodexCommandOutboxDispatcher
    outbox_runner: AsyncReliableOutboxRunner[CodexCommandOutboxSnapshot]
    _signal_reader_task: asyncio.Task[None] | None = None
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
        actor_registry = CodexHostActorRegistry(connection_registry)
        instance_control_signal_adapter = CodexInstanceControlSignalAdapter(
            store=stream_state_store,
            ttl_seconds=settings.instance_control_stream_ttl_seconds,
            max_events=settings.instance_control_stream_max_events,
        )
        outbox_dispatcher = CodexCommandOutboxDispatcher(
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
            state_synchronizer=SyncCodexAgentStateUsecase(control_port),
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
            compatibility_policy=AppServerManifestRegistry(protocol_root).build_policy(),
            stream_ticket_service=stream_ticket_service,
            device_authorization_store=device_authorization_store,
            device_challenge_store=device_challenge_store,
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
            presence_adapter=presence_adapter,
            instance_control_signal_adapter=instance_control_signal_adapter,
            outbox_dispatcher=outbox_dispatcher,
            outbox_runner=outbox_runner,
        )

    async def start(self) -> None:
        """统一流资源就绪后启动 outbox 与实例信号 reader。"""

        if self._signal_reader_task is not None:
            return
        self._runtime_stop_event = asyncio.Event()
        self.outbox_runner.start()
        self._signal_reader_task = asyncio.create_task(self._run_instance_control_reader())

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

    async def publish_agent_event(
        self,
        event: CodexAgentRealtimeEvent,
        principal: AgentDevicePrincipal,
    ) -> None:
        """保留有界恢复窗口并把 App Server 事件转换后按所有者推送。"""

        overflowed = await self.event_buffer.publish(event, principal)
        await asyncio.to_thread(
            self.state_synchronizer.accept_realtime_event,
            event,
            principal,
        )
        workspace_id = self._find_workspace_id(event, principal.owner_subject_id)
        product_event = self.protocol_mapper.map_event(event, workspace_id=workspace_id)
        if product_event is not None:
            await self.browser_event_hub.publish(principal.owner_subject_id, product_event)
        if overflowed:
            await self.browser_event_hub.publish(
                principal.owner_subject_id,
                CodexProductEvent(
                    host_id=event.host_id,
                    workspace_id=workspace_id,
                    thread_id=None,
                    turn_id=None,
                    item_id=None,
                    event_type=CodexRealtimeEventType.STREAM_GAP_DETECTED,
                    payload={"reason": "agent_event_buffer_overflow"},
                ),
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

        unit_of_work = self.control_port.create_unit_of_work()
        try:
            thread = self.control_port.create_codex_thread_repository(
                unit_of_work.get_session()
            ).get_by_upstream_id_and_owner(
                approval.host_id,
                approval.thread_id,
                principal.owner_subject_id,
            )
        finally:
            unit_of_work.dispose()
        if thread is None:
            return
        await self.browser_event_hub.publish(
            principal.owner_subject_id,
            CodexProductEvent(
                host_id=approval.host_id,
                workspace_id=thread.workspace_id,
                thread_id=approval.thread_id,
                turn_id=approval.turn_id,
                item_id=approval.item_id,
                event_type=CodexRealtimeEventType.APPROVAL_OPENED,
                payload={
                    "approval": {
                        "approval_id": str(approval.approval_id),
                        "host_id": str(approval.host_id),
                        "workspace_id": str(thread.workspace_id),
                        "thread_id": approval.thread_id,
                        "turn_id": approval.turn_id,
                        "item_id": approval.item_id,
                        "approval_kind": approval.approval_kind,
                        "risk_level": approval.risk_level,
                        "display_summary": approval.display_summary.model_dump(mode="json"),
                        "state": "pending",
                        "version": 1,
                        "expires_at": approval.expires_at.isoformat(),
                    }
                },
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

        if self._runtime_stop_event is not None:
            self._runtime_stop_event.set()
        if self._signal_reader_task is not None:
            await self._signal_reader_task
            self._signal_reader_task = None
        await self.outbox_runner.shutdown()
        await self.connection_registry.shutdown()
        await self.browser_event_hub.shutdown()
