"""Agent WSS 产品协议会话入口。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Final, cast
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.application.ports.codex_agent_revocation_signal_port import (
    CodexAgentRevocationSignalPort,
)
from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_protocol_contract import (
    CODEX_AGENT_PROTOCOL_VERSION,
    AgentConversationSnapshotDetail,
    CodexAgentApprovalOpened,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
    CodexAgentHeartbeat,
    CodexAgentHello,
    CodexAgentHelloAck,
    CodexAgentRealtimeEvent,
    CodexAgentStateSnapshot,
    CodexAgentWorkspaceSnapshot,
)
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentApprovalOpenedEventDetail,
    AgentCommandAckV2Detail,
    AgentCommandResultPayload,
    AgentCommandResultReference,
    AgentCommandResultV2Detail,
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
    AgentPlanChangedEventDetail,
    AgentProtocolV2Detail,
    AgentStateSnapshotV2Detail,
    AgentThreadChangedEventDetail,
    AgentThreadMetadataChangedEventDetail,
    AgentThreadReadCommandResult,
    AgentTurnChangedEventDetail,
)
from src.core.codex_contract.app_server_product_contract import (
    AppServerAgentMessageItem,
    AppServerCommandItem,
    AppServerContextCompactionItem,
    AppServerDiffItem,
    AppServerPlanItem,
    AppServerProductTimelineItem,
    AppServerUserMessageItem,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerCapabilityCode,
    AppServerNotificationName,
)
from src.core.codex_contract.approval_contract import CodexApprovalKind
from src.core.codex_contract.connection_session_contract import (
    CodexConnectionFrame,
    CodexConnectionProtocolVersion,
    CodexOutboundFrameSenderPort,
)
from src.core.codex_contract.presence_contract import (
    CodexHostPresence,
    CodexHostPresenceOwner,
)
from src.domain.codex.codex_compatibility_policy import (
    CodexCompatibilityDecision,
    CodexCompatibilityPolicy,
    CodexConnectionCompatibilityTuple,
)
from src.infrastructure.codex.agent_protocol_codec import (
    AgentProtocolCodecRegistry,
    AgentV1MessageType,
    AgentV1Payload,
    DecodedAgentProtocolMessage,
)
from src.infrastructure.codex.codex_agent_event_cursor_store import (
    CodexAgentEventCursorStore,
    CodexAgentEventEpochConflictError,
)
from src.infrastructure.codex.codex_connection_registry import (
    CodexConnectionLease,
    CodexConnectionRegistry,
)
from src.infrastructure.codex.codex_host_actor import CodexHostActorRegistry
from src.infrastructure.codex.codex_host_presence_adapter import CodexHostPresenceAdapter

COMMAND_RESULT_ID_FIELD: Final = "id"
COMMAND_RESULT_STATUS_FIELD: Final = "status"
COMMAND_RESULT_THREAD_FIELD: Final = "thread"
COMMAND_RESULT_TURN_FIELD: Final = "turn"
INTERNAL_EVENT_GAP_METHOD: Final = "internal/event.gap"

AgentHelloObserver = Callable[[CodexAgentHello, AgentDevicePrincipal], Awaitable[None]]
AgentCommandAckObserver = Callable[[CodexAgentCommandAck, AgentDevicePrincipal], Awaitable[None]]
AgentCommandResultObserver = Callable[
    [CodexAgentCommandResult, AgentDevicePrincipal], Awaitable[None]
]
AgentHeartbeatObserver = Callable[[CodexAgentHeartbeat, AgentDevicePrincipal], Awaitable[None]]
AgentSnapshotObserver = Callable[[CodexAgentStateSnapshot, AgentDevicePrincipal], Awaitable[None]]
AgentEventObserver = Callable[[CodexAgentRealtimeEvent, AgentDevicePrincipal], Awaitable[None]]
AgentEventBatchObserver = Callable[
    [tuple[CodexAgentRealtimeEvent, ...], AgentDevicePrincipal], Awaitable[None]
]
AgentApprovalObserver = Callable[[CodexAgentApprovalOpened, AgentDevicePrincipal], Awaitable[None]]
AgentDisconnectObserver = Callable[[UUID, AgentDevicePrincipal, datetime], Awaitable[None]]
AgentCompatibilityObserver = Callable[
    [UUID, AgentDevicePrincipal, CodexCompatibilityDecision], Awaitable[None]
]


class CodexAgentGatewayHandler:
    """协商 v1/v2，校验兼容 tuple，并分派强类型消息。"""

    def __init__(
        self,
        *,
        principal: AgentDevicePrincipal,
        connection_registry: CodexConnectionRegistry,
        actor_registry: CodexHostActorRegistry,
        compatibility_policy: CodexCompatibilityPolicy,
        allowed_codex_versions: list[str],
        heartbeat_seconds: int,
        event_cursor_store: CodexAgentEventCursorStore,
        revocation_generation: int = 0,
        presence_adapter: CodexHostPresenceAdapter | None = None,
        instance_id: UUID | None = None,
        revocation_signal: CodexAgentRevocationSignalPort | None = None,
        shutdown_event: asyncio.Event | None = None,
        hello_observer: AgentHelloObserver | None = None,
        command_ack_observer: AgentCommandAckObserver | None = None,
        command_result_observer: AgentCommandResultObserver | None = None,
        heartbeat_observer: AgentHeartbeatObserver | None = None,
        snapshot_observer: AgentSnapshotObserver | None = None,
        event_observer: AgentEventObserver | None = None,
        event_batch_observer: AgentEventBatchObserver | None = None,
        approval_observer: AgentApprovalObserver | None = None,
        disconnect_observer: AgentDisconnectObserver | None = None,
        compatibility_observer: AgentCompatibilityObserver | None = None,
    ) -> None:
        self._principal = principal
        self._connection_registry = connection_registry
        self._actor_registry = actor_registry
        self._compatibility_policy = compatibility_policy
        self._allowed_codex_versions = tuple(allowed_codex_versions)
        self._heartbeat_seconds = heartbeat_seconds
        self._event_cursor_store = event_cursor_store
        self._revocation_generation = revocation_generation
        self._presence_adapter = presence_adapter
        self._instance_id = instance_id
        self._revocation_signal = revocation_signal
        self._shutdown_event = shutdown_event
        self._hello_observer = hello_observer or self._ignore_hello
        self._command_ack_observer = command_ack_observer or self._ignore_command_ack
        self._command_result_observer = command_result_observer or self._ignore_command_result
        self._heartbeat_observer = heartbeat_observer or self._ignore_heartbeat
        self._snapshot_observer = snapshot_observer or self._ignore_snapshot
        self._event_observer = event_observer or self._ignore_event
        self._event_batch_observer = event_batch_observer
        self._approval_observer = approval_observer or self._ignore_approval
        self._disconnect_observer = disconnect_observer or self._ignore_disconnect
        self._compatibility_observer = compatibility_observer or self._ignore_compatibility
        self._codec = AgentProtocolCodecRegistry()
        self._lease: CodexConnectionLease | None = None
        self._agent_event_epoch: UUID | None = None
        self._last_event_seq = 0
        self._presence: CodexHostPresence | None = None

    @property
    def lease(self) -> CodexConnectionLease | None:
        """读取 hello 成功后建立的连接租约。"""

        return self._lease

    async def __call__(
        self,
        frame: CodexConnectionFrame,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        """解码并处理一帧 Agent 产品协议。"""

        decoded = self._codec.decode(frame)
        if self._lease is None:
            await self._accept_hello(decoded, sender)
            return
        if decoded.protocol_version != self._lease.protocol_version:
            raise ValueError("Agent连接协商后不得切换协议版本。")
        if decoded.v1 is not None:
            await self._accept_v1(decoded.v1.message_type, decoded.v1.payload)
            return
        if decoded.v2 is None:
            raise ValueError("Agent协议解码结果为空。")
        self._verify_bound_host(decoded.v2.header.host_id)
        self._verify_bound_key(decoded.v2.header.key_id)
        await self._accept_v2(decoded.v2.detail, sender)

    async def close(self) -> None:
        """释放当前代次的 registry 租约。"""

        if self._lease is not None:
            lease = self._lease
            await self._connection_registry.unregister(lease)
            if self._presence_adapter is not None and self._presence is not None:
                await self._presence_adapter.release(self._presence)
                self._presence = None
            self._lease = None
            await self._disconnect_observer(
                lease.host_id,
                self._principal,
                lease.connected_at,
            )

    async def _accept_hello(
        self,
        decoded: DecodedAgentProtocolMessage,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        if decoded.v1 is not None:
            if decoded.v1.message_type != AgentV1MessageType.HELLO or not isinstance(
                decoded.v1.payload, CodexAgentHello
            ):
                raise ValueError("Agent连接首帧必须是hello。")
            await self._accept_v1_hello(decoded.v1.payload, sender)
            return
        if decoded.v2 is None or not isinstance(decoded.v2.detail, AgentHelloV2Detail):
            raise ValueError("Agent连接首帧必须是v2 hello。")
        self._verify_bound_host(decoded.v2.header.host_id)
        self._verify_bound_key(decoded.v2.header.key_id)
        await self._accept_v2_hello(decoded.v2.detail, sender)

    async def _accept_v1_hello(
        self,
        hello: CodexAgentHello,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        self._verify_bound_host(hello.host_id)
        if hello.agent_protocol_version != CODEX_AGENT_PROTOCOL_VERSION:
            raise ValueError("Agent v1协议版本不兼容。")
        decision = self._evaluate_connection(
            codex_version=hello.codex_version,
            protocol_version=hello.agent_protocol_version,
            schema_digest=hello.app_server_schema_digest,
            capabilities=self._read_v1_capabilities(hello),
        )
        await self._hello_observer(hello, self._principal)
        await self._compatibility_observer(hello.host_id, self._principal, decision)
        lease = await self._register(
            hello.host_id,
            sender,
            protocol_version=CodexConnectionProtocolVersion.V1,
            decision=decision,
        )
        await sender.send(
            self._codec.encode_v1(
                AgentV1MessageType.HELLO_ACK,
                CodexAgentHelloAck(
                    host_id=hello.host_id,
                    connection_epoch=lease.epoch,
                    heartbeat_seconds=self._heartbeat_seconds,
                ),
            )
        )

    async def _accept_v2_hello(
        self,
        hello: AgentHelloV2Detail,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        host_id = UUID(self._principal.host_id)
        decision = self._evaluate_connection(
            codex_version=hello.codex_version,
            protocol_version=CodexConnectionProtocolVersion.V2.value,
            schema_digest=hello.app_server_schema_digest,
            capabilities=frozenset(item.code for item in hello.capabilities),
        )
        legacy_hello = CodexAgentHello(
            host_id=host_id,
            agent_version=hello.agent_version,
            codex_version=hello.codex_version,
            agent_protocol_version=CodexConnectionProtocolVersion.V2.value,
            app_server_schema_digest=hello.app_server_schema_digest,
            capabilities={
                "items": [item.model_dump(mode="json") for item in hello.capabilities],
                "model_ids": list(hello.model_ids),
                "reasoning_efforts": list(hello.reasoning_efforts),
                "model_catalog": hello.model_catalog.model_dump(mode="json"),
                "app_server_instance_id": hello.app_server_instance_id,
                "runtime_status": (
                    hello.runtime_status.model_dump(mode="json")
                    if hello.runtime_status is not None
                    else None
                ),
                "sandbox_modes": [item.value for item in hello.sandbox_modes],
                "approval_policies": [item.value for item in hello.approval_policies],
            },
        )
        await self._hello_observer(legacy_hello, self._principal)
        await self._compatibility_observer(host_id, self._principal, decision)
        lease = await self._register(
            host_id,
            sender,
            protocol_version=CodexConnectionProtocolVersion.V2,
            decision=decision,
        )
        if self._presence_adapter is not None:
            if self._instance_id is None:
                raise RuntimeError("Codex presence缺少API实例标识。")
            self._presence = await self._presence_adapter.acquire(
                CodexHostPresenceOwner(
                    instance_id=self._instance_id,
                    host_id=host_id,
                    connection_epoch=lease.epoch,
                    revocation_generation=self._revocation_generation,
                )
            )
        self._agent_event_epoch = hello.agent_event_epoch
        self._last_event_seq = await self._event_cursor_store.load_or_start(
            host_id=host_id,
            event_epoch=hello.agent_event_epoch,
        )
        await sender.send(
            self._codec.encode_v2(
                host_id=host_id,
                message_id=uuid4(),
                detail=AgentHelloAckV2Detail(
                    connection_epoch=lease.epoch,
                    heartbeat_seconds=self._heartbeat_seconds,
                    revocation_generation=self._revocation_generation,
                    acknowledged_event_epoch=hello.agent_event_epoch,
                    after_seq=self._last_event_seq,
                ),
            )
        )

    async def _register(
        self,
        host_id: UUID,
        sender: CodexOutboundFrameSenderPort,
        *,
        protocol_version: CodexConnectionProtocolVersion,
        decision: CodexCompatibilityDecision,
    ) -> CodexConnectionLease:
        lease = await self._connection_registry.register(
            host_id,
            sender,
            shutdown_event=self._shutdown_event,
            protocol_version=protocol_version,
            compatibility_decision=decision,
        )
        self._lease = lease
        return lease

    def _evaluate_connection(
        self,
        *,
        codex_version: str,
        protocol_version: str,
        schema_digest: str,
        capabilities: frozenset[AppServerCapabilityCode],
    ) -> CodexCompatibilityDecision:
        result = self._compatibility_policy.evaluate_connection(
            CodexConnectionCompatibilityTuple(
                codex_version=codex_version,
                agent_protocol_version=protocol_version,
                app_server_schema_digest=schema_digest,
                capabilities=capabilities,
            )
        )
        if result.decision in {
            CodexCompatibilityDecision.BLOCKED,
            CodexCompatibilityDecision.UPGRADE_REQUIRED,
        }:
            raise ValueError(f"Agent兼容性检查失败：{result.reason.value}。")
        return result.decision

    async def _accept_v1(
        self,
        message_type: AgentV1MessageType,
        payload: AgentV1Payload,
    ) -> None:
        if message_type == AgentV1MessageType.HEARTBEAT and isinstance(
            payload, CodexAgentHeartbeat
        ):
            self._verify_bound_host(payload.host_id)
            await self._heartbeat_observer(payload, self._principal)
            return
        if message_type == AgentV1MessageType.COMMAND_ACK and isinstance(
            payload, CodexAgentCommandAck
        ):
            await self._accept_command_ack(payload)
            return
        if message_type == AgentV1MessageType.COMMAND_RESULT and isinstance(
            payload, CodexAgentCommandResult
        ):
            await self._accept_command_result(payload)
            return
        if message_type == AgentV1MessageType.STATE_SNAPSHOT and isinstance(
            payload, CodexAgentStateSnapshot
        ):
            self._verify_bound_host(payload.host_id)
            await self._snapshot_observer(payload, self._principal)
            return
        if message_type == AgentV1MessageType.REALTIME_EVENT and isinstance(
            payload, CodexAgentRealtimeEvent
        ):
            self._verify_bound_host(payload.host_id)
            await self._event_observer(payload, self._principal)
            return
        if message_type == AgentV1MessageType.APPROVAL_OPENED and isinstance(
            payload, CodexAgentApprovalOpened
        ):
            self._verify_bound_host(payload.host_id)
            await self._approval_observer(payload, self._principal)
            return
        raise ValueError("Agent发送了不受支持的v1消息类型。")

    async def _accept_v2(
        self,
        detail: AgentProtocolV2Detail,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        host_id = UUID(self._principal.host_id)
        if isinstance(detail, AgentHeartbeatV2Detail):
            if self._revocation_signal is not None:
                current_generation = await self._revocation_signal.read_generation(host_id)
                if current_generation != self._revocation_generation:
                    raise PermissionError("Agent设备已经撤销或代次已更新。")
            if detail.revocation_generation != self._revocation_generation:
                raise PermissionError("Agent撤销代次与当前连接身份不一致。")
            if self._presence_adapter is not None and self._presence is not None:
                renewed = await self._presence_adapter.renew(self._presence)
                if renewed is None:
                    raise PermissionError("Agent presence fencing token已经失效。")
                self._presence = renewed
            await self._heartbeat_observer(
                CodexAgentHeartbeat(
                    host_id=host_id,
                    connection_epoch=detail.connection_epoch,
                    app_server_instance_id=str(detail.app_server_instance_id),
                    sent_at=datetime.now(UTC),
                ),
                self._principal,
            )
            return
        if isinstance(detail, AgentCommandAckV2Detail):
            await self._accept_command_ack(
                CodexAgentCommandAck(
                    command_id=detail.command_id,
                    operation_id=detail.operation_id,
                    state=detail.state,
                    replayed=detail.replayed,
                    recovery_required=detail.recovery_required,
                )
            )
            return
        if isinstance(detail, AgentCommandResultV2Detail):
            await self._accept_command_result(
                CodexAgentCommandResult(
                    command_id=detail.command_id,
                    operation_id=detail.operation_id,
                    outcome=detail.outcome,
                    result=(
                        self._to_v1_command_result(detail.result, detail.reference)
                        if detail.result is not None or detail.reference is not None
                        else None
                    ),
                    error_code=detail.error_code,
                    error_message=detail.error_summary,
                )
            )
            return
        if isinstance(detail, AgentStateSnapshotV2Detail):
            await self._snapshot_observer(
                self._to_v1_snapshot(host_id, detail),
                self._principal,
            )
            return

        if isinstance(detail, AgentEventBatchV2Detail):
            await self._accept_event_batch(host_id, detail, sender)
            return
        raise ValueError("Agent发送了不受支持的v2消息类型。")

    def _to_v1_command_result(
        self,
        payload: AgentCommandResultPayload | None,
        reference: AgentCommandResultReference | None,
    ) -> dict[str, JsonValue]:
        """把 v2 强类型结果映射为应用层冻结的官方字段形态。"""

        result: dict[str, JsonValue] = {}
        if isinstance(payload, AgentThreadReadCommandResult):
            snapshot = payload.snapshot
            # 应用层历史读取优先消费此冻结产品快照，与实时 typed event
            # 使用同一归一化路径；下方 legacy 字段仅服务 v1 兼容消费者。
            result["productThreadRead"] = cast(JsonValue, snapshot.model_dump(mode="json"))
            result[COMMAND_RESULT_THREAD_FIELD] = {
                "id": snapshot.thread.thread_id,
                "name": snapshot.thread.display_name,
                "preview": snapshot.thread.display_name,
                "modelProvider": snapshot.thread.model_provider,
                "status": snapshot.thread.status,
                "createdAt": snapshot.thread.created_at,
                "updatedAt": snapshot.thread.updated_at,
                "turns": [
                    {
                        "id": turn.turn_id,
                        "status": turn.status,
                        "startedAt": turn.started_at,
                        "completedAt": turn.completed_at,
                        "error": (
                            {"message": turn.error_message}
                            if turn.error_message is not None
                            else None
                        ),
                        "items": [self._to_v1_timeline_item(item) for item in turn.items],
                    }
                    for turn in snapshot.turns
                ],
            }
            result["historyStatus"] = snapshot.history_status
        if reference is None:
            return result
        if reference.upstream_thread_id is not None and COMMAND_RESULT_THREAD_FIELD not in result:
            result[COMMAND_RESULT_THREAD_FIELD] = {
                COMMAND_RESULT_ID_FIELD: reference.upstream_thread_id,
            }
        if reference.upstream_turn_id is not None:
            result[COMMAND_RESULT_TURN_FIELD] = {
                COMMAND_RESULT_ID_FIELD: reference.upstream_turn_id,
            }
        if reference.status is not None:
            result[COMMAND_RESULT_STATUS_FIELD] = reference.status
        return result

    def _to_v1_timeline_item(
        self,
        item: AppServerProductTimelineItem,
    ) -> dict[str, JsonValue]:
        """恢复 CodexProtocolMapper 已冻结的官方 item 字段名。"""

        if isinstance(item, AppServerUserMessageItem):
            return {
                "id": item.item_id,
                "type": "userMessage",
                "clientId": str(item.client_operation_id) if item.client_operation_id else None,
                "content": [{"type": "text", "text": item.text}],
            }
        if isinstance(item, AppServerAgentMessageItem):
            return {"id": item.item_id, "type": "agentMessage", "text": item.text}
        if isinstance(item, AppServerPlanItem):
            return {"id": item.item_id, "type": "plan", "text": item.explanation}
        if isinstance(item, AppServerCommandItem):
            return {
                "id": item.item_id,
                "type": "commandExecution",
                "command": item.command,
                "aggregatedOutput": item.output,
                "exitCode": item.exit_code,
                "status": item.status,
            }
        if isinstance(item, AppServerDiffItem):
            return {
                "id": item.item_id,
                "type": "fileChange",
                "status": item.status,
                "changes": [
                    {
                        "path": change.path,
                        "kind": {
                            "type": (
                                "add"
                                if change.change_kind == "added"
                                else "delete"
                                if change.change_kind == "deleted"
                                else "update"
                            ),
                            "move_path": change.old_path,
                        },
                        "diff": change.diff,
                    }
                    for change in item.changes
                ],
            }
        if isinstance(item, AppServerContextCompactionItem):
            return {"id": item.item_id, "type": "contextCompaction"}
        return {
            "id": item.item_id,
            "type": item.label,
            "summary": [item.text] if item.text else [],
        }

    async def _accept_event_batch(
        self,
        host_id: UUID,
        batch: AgentEventBatchV2Detail,
        sender: CodexOutboundFrameSenderPort,
    ) -> None:
        if self._agent_event_epoch != batch.agent_event_epoch:
            raise ValueError("Agent事件批次epoch与hello不一致。")
        first_record = batch.events[0]
        if batch.first_seq > self._last_event_seq + 1 and not isinstance(
            first_record.detail,
            AgentGapEventDetail,
        ):
            raise ValueError("Agent事件批次存在未声明的序号缺口。")
        records = tuple(record for record in batch.events if record.seq > self._last_event_seq)
        events = tuple(self._to_realtime_event(host_id, record) for record in records)
        if self._event_batch_observer is not None and events:
            # v2 批次必须在推进 ACK 前作为一个有序边界交给控制面，避免重新逐条 fan-out。
            await self._event_batch_observer(events, self._principal)
        for record, event in zip(records, events, strict=True):
            if self._event_batch_observer is None:
                if isinstance(record.detail, AgentApprovalOpenedEventDetail):
                    approval = record.detail.approval
                    await self._approval_observer(
                        CodexAgentApprovalOpened(
                            approval_id=approval.approval_id,
                            host_id=host_id,
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
                        self._principal,
                    )
                await self._event_observer(event, self._principal)
            try:
                self._last_event_seq = await self._event_cursor_store.advance(
                    host_id=host_id,
                    event_epoch=batch.agent_event_epoch,
                    after_seq=record.seq,
                )
            except CodexAgentEventEpochConflictError:
                if self._shutdown_event is not None:
                    self._shutdown_event.set()
                raise
        await sender.send(
            self._codec.encode_v2(
                host_id=host_id,
                message_id=uuid4(),
                detail=self._build_event_ack(batch),
            )
        )

    def _to_realtime_event(
        self,
        host_id: UUID,
        record: AgentEventRecord,
    ) -> CodexAgentRealtimeEvent:
        """把已校验的 v2 record 转换为控制面唯一消费的强类型事件。"""

        return CodexAgentRealtimeEvent(
            host_id=host_id,
            app_server_instance_id=str(record.app_server_instance_id),
            occurred_at=record.occurred_at,
            method=self._to_v1_event_method(record.detail),
            params=self._to_v1_event_params(record.detail),
            detail=record.detail,
        )

    def _to_v1_event_params(self, detail: AgentEventDetail) -> dict[str, JsonValue]:
        """把 v2 event detail 映射到现有应用层事件字段。"""

        if isinstance(detail, AgentGapEventDetail):
            return {
                "snapshotRequired": detail.snapshot_required,
                "firstAvailableSeq": detail.first_available_seq,
            }
        if isinstance(detail, AgentThreadChangedEventDetail):
            thread = detail.thread
            return {
                "thread": {
                    "id": thread.thread_id,
                    "name": thread.display_name,
                    "preview": thread.display_name,
                    "modelProvider": thread.model_provider,
                    "status": thread.status,
                    "createdAt": thread.created_at,
                    "updatedAt": thread.updated_at,
                    "turns": [],
                },
                "threadId": thread.thread_id,
                "status": thread.status,
            }
        if isinstance(detail, AgentThreadMetadataChangedEventDetail):
            params: dict[str, JsonValue] = {"threadId": detail.thread_id}
            if detail.display_name is not None:
                params["threadName"] = detail.display_name
            if detail.archived is not None:
                params["archived"] = detail.archived
            return params
        if isinstance(detail, AgentTurnChangedEventDetail):
            return {
                "threadId": detail.thread_id,
                "turnId": detail.turn_id,
                "turn": {"id": detail.turn_id, "status": detail.status},
            }
        if isinstance(detail, AgentItemChangedEventDetail):
            return {
                "threadId": detail.thread_id,
                "turnId": detail.turn_id,
                "item": self._to_v1_timeline_item(detail.item),
            }
        if isinstance(detail, AgentItemDeltaEventDetail):
            return {
                "threadId": detail.thread_id,
                "turnId": detail.turn_id,
                "itemId": detail.item_id,
                "delta": detail.delta,
            }
        if isinstance(detail, AgentPlanChangedEventDetail):
            return {
                "threadId": detail.thread_id,
                "turnId": detail.turn_id,
                "explanation": detail.explanation,
                "plan": [item.model_dump(mode="json") for item in detail.steps],
            }
        if isinstance(detail, AgentDiffChangedEventDetail):
            return {
                "threadId": detail.thread_id,
                "turnId": detail.turn_id,
                "diff": detail.unified_diff,
            }
        return cast(dict[str, JsonValue], detail.model_dump(mode="json"))

    def _to_v1_event_method(self, detail: AgentEventDetail) -> str:
        """恢复应用层审核过的官方 notification method。"""

        if isinstance(detail, AgentGapEventDetail):
            return INTERNAL_EVENT_GAP_METHOD
        if isinstance(
            detail,
            (
                AgentThreadChangedEventDetail,
                AgentThreadMetadataChangedEventDetail,
                AgentTurnChangedEventDetail,
                AgentItemChangedEventDetail,
                AgentItemDeltaEventDetail,
            ),
        ):
            return detail.method.value
        if isinstance(detail, AgentPlanChangedEventDetail):
            return AppServerNotificationName.TURN_PLAN_UPDATED.value
        if isinstance(detail, AgentDiffChangedEventDetail):
            return AppServerNotificationName.TURN_DIFF_UPDATED.value
        return detail.kind

    def _build_event_ack(
        self,
        batch: AgentEventBatchV2Detail,
    ) -> AgentEventAckV2Detail:
        return AgentEventAckV2Detail(
            agent_event_epoch=batch.agent_event_epoch,
            after_seq=self._last_event_seq,
        )

    async def _accept_command_ack(self, ack: CodexAgentCommandAck) -> None:
        await self._actor_registry.get(self._read_lease().host_id).accept_ack(ack)
        await self._command_ack_observer(ack, self._principal)

    async def _accept_command_result(self, result: CodexAgentCommandResult) -> None:
        await self._actor_registry.get(self._read_lease().host_id).accept_result(result)
        await self._command_result_observer(result, self._principal)

    def _to_v1_snapshot(
        self,
        host_id: UUID,
        snapshot: AgentStateSnapshotV2Detail,
    ) -> CodexAgentStateSnapshot:
        return CodexAgentStateSnapshot(
            host_id=host_id,
            app_server_instance_id=str(snapshot.app_server_instance_id),
            workspaces=[
                CodexAgentWorkspaceSnapshot(
                    key=item.workspace_key,
                    display_name=item.display_name,
                    repo_fingerprint=item.repo_fingerprint,
                    default_branch=item.default_branch,
                    allow_write=item.allow_write,
                )
                for item in snapshot.workspaces
            ],
            threads=[
                AgentConversationSnapshotDetail(
                    thread_id=item.thread_id,
                    workspace_key=item.workspace_key,
                    display_name=item.display_name,
                    title_source=item.title_source,
                    model_id=item.model_id,
                    model_provider=item.model_provider,
                    status=item.status,
                    active_turn_id=item.active_turn_id,
                    archived=item.archived,
                    created_at=item.created_at,
                    recency_at=item.recency_at,
                )
                for item in snapshot.threads
            ],
            omitted_thread_workspace_keys=[],
            pending_commands=[item.model_dump(mode="json") for item in snapshot.pending_commands],
            captured_at=snapshot.captured_at,
        )

    def _read_v1_capabilities(
        self,
        hello: CodexAgentHello,
    ) -> frozenset[AppServerCapabilityCode]:
        resolved: set[AppServerCapabilityCode] = set()
        for group_name in ("thread", "turn"):
            values = hello.capabilities.get(group_name)
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, str):
                    continue
                try:
                    resolved.add(AppServerCapabilityCode(f"{group_name}.{value}"))
                except ValueError:
                    continue
        return frozenset(resolved)

    def _verify_bound_host(self, host_id: UUID) -> None:
        if str(host_id) != self._principal.host_id:
            raise PermissionError("Agent消息host_id与设备凭据不匹配。")

    def _verify_bound_key(self, key_id: UUID | None) -> None:
        """校验 v2 hello 使用的设备 key 与一次性票据一致。"""

        if key_id is None or str(key_id) != self._principal.credential_id:
            raise PermissionError("Agent消息key_id与一次性连接票据不匹配。")

    def _read_lease(self) -> CodexConnectionLease:
        if self._lease is None:
            raise RuntimeError("Agent连接尚未完成hello。")
        return self._lease

    async def _ignore_hello(
        self,
        _hello: CodexAgentHello,
        _principal: AgentDevicePrincipal,
    ) -> None:
        return None

    async def _ignore_command_ack(
        self,
        _ack: CodexAgentCommandAck,
        _principal: AgentDevicePrincipal,
    ) -> None:
        return None

    async def _ignore_command_result(
        self,
        _result: CodexAgentCommandResult,
        _principal: AgentDevicePrincipal,
    ) -> None:
        return None

    async def _ignore_heartbeat(
        self,
        _heartbeat: CodexAgentHeartbeat,
        _principal: AgentDevicePrincipal,
    ) -> None:
        return None

    async def _ignore_snapshot(
        self,
        _snapshot: CodexAgentStateSnapshot,
        _principal: AgentDevicePrincipal,
    ) -> None:
        return None

    async def _ignore_event(
        self,
        _event: CodexAgentRealtimeEvent,
        _principal: AgentDevicePrincipal,
    ) -> None:
        return None

    async def _ignore_approval(
        self,
        _approval: CodexAgentApprovalOpened,
        _principal: AgentDevicePrincipal,
    ) -> None:
        return None

    async def _ignore_disconnect(
        self,
        _host_id: UUID,
        _principal: AgentDevicePrincipal,
        _connection_started_at: datetime,
    ) -> None:
        return None

    async def _ignore_compatibility(
        self,
        _host_id: UUID,
        _principal: AgentDevicePrincipal,
        _decision: CodexCompatibilityDecision,
    ) -> None:
        return None
