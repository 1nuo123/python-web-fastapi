"""Agent hello、心跳与 snapshot 的控制面索引同步用例。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.application.codex.operation_projection_service import (
    CodexAppliedOperationProjection,
    CodexOperationProjectionService,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_protocol_contract import (
    AgentConversationSnapshotDetail,
    CodexAgentApprovalOpened,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
    CodexAgentHeartbeat,
    CodexAgentHello,
    CodexAgentRealtimeEvent,
    CodexAgentStateSnapshot,
    CodexAgentWorkspaceSnapshot,
)
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentApprovalOpenedEventDetail,
    AgentApprovalResolvedEventDetail,
    AgentItemChangedEventDetail,
    AgentThreadChangedEventDetail,
    AgentThreadMetadataChangedEventDetail,
    AgentTurnChangedEventDetail,
)
from src.core.codex_contract.agent_runtime_health_contract import AgentRuntimeStatus
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerCapabilityCode,
    AppServerCapabilityDetail,
    AppServerNotificationName,
)
from src.core.codex_contract.approval_contract import (
    CodexApprovalAuditSnapshot,
    CodexApprovalState,
)
from src.core.codex_contract.command_outbox_contract import CodexCommandOutboxState
from src.core.codex_contract.host_contract import (
    CodexApprovalPolicy,
    CodexHostCapabilities,
    CodexHostCompatibilityDetail,
    CodexHostCompatibilityObservationDetail,
    CodexHostCompatibilityState,
    CodexHostDisconnectObservationDetail,
    CodexHostDoctorDetail,
    CodexHostDoctorState,
    CodexHostHeartbeatObservationDetail,
    CodexHostHelloObservationDetail,
    CodexHostObservation,
    CodexHostObservationHeader,
    CodexHostObservationType,
    CodexHostSnapshot,
    CodexHostUpdateDetail,
    CodexHostUpdateState,
    CodexSandboxMode,
)
from src.core.codex_contract.model_catalog_contract import CodexModelCatalog
from src.core.codex_contract.product_command_contract import CodexProductCommandCode
from src.core.codex_contract.thread_contract import (
    CodexActiveTurnUpdateMode,
    CodexThreadIndexSnapshot,
    CodexThreadRuntimeStateUpdate,
    CodexThreadStatus,
    CodexThreadTitleSource,
)
from src.core.codex_contract.turn_runtime_contract import CodexTurnPhase, CodexTurnRuntime
from src.core.codex_contract.workspace_contract import (
    CodexWorkspaceExecutionPreferences,
    CodexWorkspaceSnapshot,
)
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession
from src.domain.codex.codex_compatibility_policy import CodexCompatibilityDecision
from src.domain.codex.thread_execution_state import thread_status_for_phase
from src.domain.codex.thread_title_policy import CodexThreadTitlePolicy


class SyncCodexAgentStateUsecase:
    """仅同步控制元数据，不保存 prompt、Diff 或终端正文。"""

    def __init__(self, control_port: CodexControlPort, *, max_workspaces_per_host: int) -> None:
        self._control_port = control_port
        self._max_workspaces_per_host = max_workspaces_per_host
        self._projection_service = CodexOperationProjectionService(control_port)

    def accept_hello(
        self,
        hello: CodexAgentHello,
        principal: AgentDevicePrincipal,
    ) -> None:
        """把设备认证后的 hello 写入所属主机。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_host_repository(unit_of_work.get_session())
            runtime = AgentRuntimeStatus.model_validate(
                hello.capabilities.get("runtime_status") or {}
            )
            doctor_state = {
                "pass": CodexHostDoctorState.HEALTHY,
                "warn": CodexHostDoctorState.DEGRADED,
                "failed": CodexHostDoctorState.DEGRADED,
                "blocked": CodexHostDoctorState.BLOCKED,
            }.get(runtime.doctor_state or "", CodexHostDoctorState.UNKNOWN)
            update_state = {
                "current": CodexHostUpdateState.CURRENT,
                "updated": CodexHostUpdateState.CURRENT,
                "rolled_back": CodexHostUpdateState.FAILED,
                "failed": CodexHostUpdateState.FAILED,
                "blocked": CodexHostUpdateState.FAILED,
            }.get(runtime.update_state or "", CodexHostUpdateState.UNKNOWN)
            observation = CodexHostObservation(
                header=CodexHostObservationHeader(
                    detail_kind=CodexHostObservationType.HELLO,
                    host_id=hello.host_id,
                    owner_subject_id=principal.owner_subject_id,
                    observed_at=datetime.now(UTC),
                ),
                detail=CodexHostHelloObservationDetail(
                    agent_version=hello.agent_version,
                    codex_version=hello.codex_version,
                    agent_protocol_version=hello.agent_protocol_version,
                    app_server_schema_digest=hello.app_server_schema_digest,
                    capabilities=self._map_host_capabilities(hello),
                    doctor=CodexHostDoctorDetail(
                        state=doctor_state,
                        checked_at=runtime.doctor_checked_at,
                        issue_codes=runtime.doctor_issue_codes,
                    ),
                    update=CodexHostUpdateDetail(
                        state=update_state,
                        current_version=hello.agent_version,
                        target_version=runtime.update_target_version,
                        last_checked_at=runtime.update_checked_at,
                        last_result=runtime.update_reason_code or runtime.update_state,
                    ),
                ),
            )
            if repository.apply_observation(observation) is None:
                raise PermissionError("Agent凭据绑定的主机不存在。")
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _map_host_capabilities(self, hello: CodexAgentHello) -> CodexHostCapabilities:
        typed_items = hello.capabilities.get("items")
        if isinstance(typed_items, list):
            items: list[AppServerCapabilityDetail] = []
            for item in typed_items:
                try:
                    items.append(AppServerCapabilityDetail.model_validate(item))
                except ValueError:
                    continue
            return CodexHostCapabilities(
                items=tuple(items),
                model_catalog=CodexModelCatalog.model_validate(
                    hello.capabilities.get("model_catalog") or {}
                ),
                app_server_instance_id=(
                    value
                    if isinstance(value := hello.capabilities.get("app_server_instance_id"), str)
                    else None
                ),
                model_ids=self._read_capability_strings(hello, "model_ids"),
                reasoning_efforts=self._read_capability_strings(
                    hello,
                    "reasoning_efforts",
                ),
                sandbox_modes=tuple(
                    CodexSandboxMode(value)
                    for value in self._read_capability_strings(hello, "sandbox_modes")
                ),
                approval_policies=tuple(
                    CodexApprovalPolicy(value)
                    for value in self._read_capability_strings(
                        hello,
                        "approval_policies",
                    )
                ),
            )
        items = []
        for group_name in ("thread", "turn"):
            values = hello.capabilities.get(group_name)
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, str):
                    continue
                try:
                    code = AppServerCapabilityCode(f"{group_name}.{value}")
                except ValueError:
                    continue
                items.append(AppServerCapabilityDetail(code=code, version=1))
        return CodexHostCapabilities(items=tuple(items))

    def _read_capability_strings(
        self,
        hello: CodexAgentHello,
        field_name: str,
    ) -> tuple[str, ...]:
        values = hello.capabilities.get(field_name)
        if not isinstance(values, list):
            return ()
        return tuple(value for value in values if isinstance(value, str) and value)

    def accept_compatibility(
        self,
        host_id: UUID,
        principal: AgentDevicePrincipal,
        decision: CodexCompatibilityDecision,
    ) -> None:
        """持久化已协商的兼容状态，DB 仍只保存最后已知值。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_host_repository(unit_of_work.get_session())
            observation = CodexHostObservation(
                header=CodexHostObservationHeader(
                    detail_kind=CodexHostObservationType.COMPATIBILITY,
                    host_id=host_id,
                    owner_subject_id=principal.owner_subject_id,
                    observed_at=datetime.now(UTC),
                ),
                detail=CodexHostCompatibilityObservationDetail(
                    compatibility=CodexHostCompatibilityDetail(
                        state=CodexHostCompatibilityState(decision.value),
                    )
                ),
            )
            if repository.apply_observation(observation) is None:
                raise PermissionError("Agent兼容性主机不存在。")
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def accept_heartbeat(
        self,
        heartbeat: CodexAgentHeartbeat,
        principal: AgentDevicePrincipal,
    ) -> None:
        """刷新当前所有者主机的在线时间。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_host_repository(unit_of_work.get_session())
            observation = CodexHostObservation(
                header=CodexHostObservationHeader(
                    detail_kind=CodexHostObservationType.HEARTBEAT,
                    host_id=heartbeat.host_id,
                    owner_subject_id=principal.owner_subject_id,
                    observed_at=datetime.now(UTC),
                ),
                detail=CodexHostHeartbeatObservationDetail(
                    app_server_instance_id=heartbeat.app_server_instance_id,
                ),
            )
            if repository.apply_observation(observation) is None:
                raise PermissionError("Agent心跳主机不存在。")
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def accept_disconnect(
        self,
        host_id: UUID,
        principal: AgentDevicePrincipal,
        connection_started_at: datetime,
    ) -> CodexHostSnapshot | None:
        """仅在当前权威连接消失后把所属主机标记离线。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_host_repository(unit_of_work.get_session())
            observation = CodexHostObservation(
                header=CodexHostObservationHeader(
                    detail_kind=CodexHostObservationType.DISCONNECT,
                    host_id=host_id,
                    owner_subject_id=principal.owner_subject_id,
                    observed_at=datetime.now(UTC),
                ),
                detail=CodexHostDisconnectObservationDetail(
                    connection_started_at=connection_started_at,
                ),
            )
            host = repository.apply_observation(observation)
            unit_of_work.commit()
            return host
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def accept_snapshot(
        self,
        snapshot: CodexAgentStateSnapshot,
        principal: AgentDevicePrincipal,
    ) -> None:
        """按 host 所有权 upsert 工作区与线程索引。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            host_repository = self._control_port.create_codex_host_repository(session)
            if (
                host_repository.get_by_id_and_owner(
                    snapshot.host_id,
                    principal.owner_subject_id,
                )
                is None
            ):
                raise PermissionError("Agent快照主机不存在。")
            workspace_repository = self._control_port.create_codex_workspace_repository(session)
            thread_repository = self._control_port.create_codex_thread_repository(session)
            enabled_workspaces = workspace_repository.list_by_host_and_owner(
                snapshot.host_id,
                principal.owner_subject_id,
            )
            reported_workspace_keys = {workspace.key for workspace in snapshot.workspaces}
            workspace_ids: dict[str, UUID] = {}
            for workspace in snapshot.workspaces:
                existing = workspace_repository.get_by_agent_key_and_owner(
                    snapshot.host_id,
                    workspace.key,
                    principal.owner_subject_id,
                )
                workspace_state = self._build_workspace_snapshot(
                    host_id=snapshot.host_id,
                    owner_subject_id=principal.owner_subject_id,
                    captured_at=snapshot.captured_at,
                    workspace=workspace,
                    existing=existing,
                )
                workspace_ids[workspace.key] = workspace_state.workspace_id
                if existing is None:
                    if (
                        workspace_repository.count_enabled_by_host_and_owner(
                            snapshot.host_id,
                            principal.owner_subject_id,
                        )
                        >= self._max_workspaces_per_host
                    ):
                        raise PermissionError("Codex主机登记的工作区数量已经达到配额上限。")
                    workspace_repository.add(workspace_state)
                else:
                    workspace_repository.save(workspace_state)
            for enabled_workspace in enabled_workspaces:
                if enabled_workspace.agent_workspace_key in reported_workspace_keys:
                    continue
                workspace_repository.save(
                    enabled_workspace.model_copy(
                        update={
                            "enabled": False,
                            "updated_at": snapshot.captured_at,
                            "version": enabled_workspace.version + 1,
                        }
                    )
                )
            # Make newly discovered workspace rows visible to the thread foreign key
            # before SQLAlchemy batches the thread index inserts.
            unit_of_work.flush()
            for raw_thread in snapshot.threads:
                workspace_key = raw_thread.workspace_key
                thread_id = raw_thread.thread_id
                existing_thread = thread_repository.get_by_upstream_id_and_owner(
                    snapshot.host_id,
                    thread_id,
                    principal.owner_subject_id,
                )
                thread_state = self._build_thread_snapshot(
                    raw_thread=raw_thread,
                    host_id=snapshot.host_id,
                    workspace_id=workspace_ids[workspace_key],
                    owner_subject_id=principal.owner_subject_id,
                    captured_at=snapshot.captured_at,
                    existing=existing_thread,
                )
                if existing_thread is None:
                    thread_repository.add(thread_state)
                else:
                    thread_repository.save(thread_state)
            self._reconcile_operations(
                session=session,
                snapshot=snapshot,
                owner_subject_id=principal.owner_subject_id,
            )
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def accept_command_ack(
        self,
        ack: CodexAgentCommandAck,
        principal: AgentDevicePrincipal,
    ) -> CodexAppliedOperationProjection | None:
        """收敛 HTTP 超时后迟到或重连回放的 Agent ack。"""

        if ack.state not in {"received", "executing", "accepted", "completed", "failed", "unknown"}:
            return None
        if ack.state == "unknown":
            status = "unknown"
        elif ack.state == "failed":
            status = "failed"
        else:
            status = "acknowledged"
        return self._update_operation(
            operation_id=ack.operation_id,
            owner_subject_id=principal.owner_subject_id,
            status=status,
            result_digest=None,
        )

    def accept_command_result(
        self,
        result: CodexAgentCommandResult,
        principal: AgentDevicePrincipal,
    ) -> CodexAppliedOperationProjection | None:
        """把 Agent 最终结果收敛到 operation，正文只计算摘要不落库。"""

        if result.outcome == "unknown":
            return self._update_operation(
                operation_id=result.operation_id,
                owner_subject_id=principal.owner_subject_id,
                status="unknown",
                result_digest=None,
            )
        result_digest = hashlib.sha256(
            json.dumps(
                result.result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self._materialize_started_thread(result, principal)
        self._apply_completed_thread_command(result, principal)
        return self._update_operation(
            operation_id=result.operation_id,
            owner_subject_id=principal.owner_subject_id,
            status="completed" if result.outcome == "completed" else "failed",
            result_digest=result_digest,
        )

    def _materialize_started_thread(
        self,
        result: CodexAgentCommandResult,
        principal: AgentDevicePrincipal,
    ) -> None:
        """Create a minimal thread index from thread/start's stable id.

        Some App Server versions acknowledge ``thread/start`` before the new
        session appears in ``thread/list``. The command result is authoritative
        for the id, so index it immediately and let the next snapshot enrich it.
        """

        if result.outcome != "completed":
            return
        operation_id = UUID(str(result.operation_id))
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            operation_repository = self._control_port.create_codex_operation_repository(session)
            operation = operation_repository.get_by_id_and_owner(
                operation_id,
                principal.owner_subject_id,
            )
            if (
                operation is None
                or operation.operation_type != "thread.start"
                or operation.workspace_id is None
            ):
                unit_of_work.rollback()
                return
            thread_id = self._read_result_thread_id(result.result)
            if thread_id is None:
                unit_of_work.rollback()
                return
            thread_repository = self._control_port.create_codex_thread_repository(session)
            if (
                thread_repository.get_by_upstream_id_and_owner(
                    operation.host_id,
                    thread_id,
                    principal.owner_subject_id,
                )
                is None
            ):
                now = datetime.now(UTC)
                title = CodexThreadTitlePolicy().resolve(created_at=now)
                thread_repository.add(
                    CodexThreadIndexSnapshot(
                        thread_index_id=uuid4(),
                        host_id=operation.host_id,
                        workspace_id=operation.workspace_id,
                        owner_subject_id=principal.owner_subject_id,
                        upstream_thread_id=thread_id,
                        display_name=title.display_name,
                        title_source=title.source,
                        model=None,
                        model_provider=None,
                        reasoning_effort=None,
                        status=CodexThreadStatus.IDLE,
                        active_turn_id=None,
                        archived=False,
                        is_pinned=False,
                        source_kind="remote",
                        created_at=now,
                        recency_at=now,
                        updated_at=now,
                        last_synced_at=now,
                    )
                )
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _read_result_thread_id(self, result: JsonValue | None) -> str | None:
        if not isinstance(result, Mapping):
            return None
        thread = result.get("thread")
        if isinstance(thread, Mapping):
            value = thread.get("id")
            if isinstance(value, str) and value:
                return value
        value = result.get("threadId")
        return value if isinstance(value, str) and value else None

    def _apply_completed_thread_command(
        self,
        result: CodexAgentCommandResult,
        principal: AgentDevicePrincipal,
    ) -> None:
        """App Server 成功后收敛归档或恢复最终状态。"""

        if result.outcome != "completed":
            return
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            operation = self._control_port.create_codex_operation_repository(
                session
            ).get_by_id_and_owner(
                UUID(str(result.operation_id)),
                principal.owner_subject_id,
            )
            if operation is None or operation.thread_id is None:
                unit_of_work.commit()
                return
            if operation.operation_type not in {
                CodexProductCommandCode.THREAD_ARCHIVE.value,
                CodexProductCommandCode.THREAD_UNARCHIVE.value,
            }:
                unit_of_work.commit()
                return
            repository = self._control_port.create_codex_thread_repository(session)
            thread = repository.get_by_upstream_id_and_owner(
                operation.host_id,
                operation.thread_id,
                principal.owner_subject_id,
            )
            if thread is None:
                unit_of_work.commit()
                return
            archived = operation.operation_type == CodexProductCommandCode.THREAD_ARCHIVE.value
            now = datetime.now(UTC)
            repository.save(
                thread.model_copy(
                    update={
                        "archived": archived,
                        "updated_at": now,
                        "last_synced_at": now,
                    }
                )
            )
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def accept_realtime_event(
        self,
        event: CodexAgentRealtimeEvent,
        principal: AgentDevicePrincipal,
    ) -> CodexThreadIndexSnapshot | None:
        """用 turn/thread 生命周期事件更新控制面并发事实，不保存正文。"""

        params = (
            cast(Mapping[str, JsonValue], event.params) if isinstance(event.params, Mapping) else {}
        )
        thread_id: str | None = None
        status: CodexThreadStatus | None = None
        active_turn_id: str | None = None
        active_turn_mode = CodexActiveTurnUpdateMode.PRESERVE
        display_name: str | None = None
        archived: bool | None = None
        activity_at: datetime | None = None
        detail = event.detail
        if isinstance(detail, AgentTurnChangedEventDetail):
            thread_id = detail.thread_id
            activity_at = event.occurred_at
            if detail.method is AppServerNotificationName.TURN_STARTED:
                status = CodexThreadStatus.ACTIVE
                active_turn_id = detail.turn_id
                active_turn_mode = CodexActiveTurnUpdateMode.SET
            else:
                status = self._read_thread_status(detail.status)
                active_turn_mode = CodexActiveTurnUpdateMode.CLEAR
        elif isinstance(detail, AgentThreadChangedEventDetail):
            thread_id = detail.thread.thread_id
            status = self._read_thread_status(detail.thread.status)
            display_name = detail.thread.display_name
            archived = detail.thread.archived
            if detail.thread.recency_at is not None:
                activity_at = datetime.fromtimestamp(detail.thread.recency_at, UTC)
        elif isinstance(detail, AgentThreadMetadataChangedEventDetail):
            thread_id = detail.thread_id
            display_name = detail.display_name
            archived = detail.archived
            if archived is not None:
                activity_at = event.occurred_at
        elif isinstance(detail, AgentItemChangedEventDetail):
            thread_id = detail.thread_id
            activity_at = event.occurred_at
        elif isinstance(detail, AgentApprovalOpenedEventDetail):
            thread_id = detail.approval.thread_id
            activity_at = event.occurred_at
        else:
            raw_thread_id = params.get("threadId")
            thread_id = raw_thread_id if isinstance(raw_thread_id, str) else None
        if thread_id is None:
            return None
        if detail is None and event.method == AppServerNotificationName.TURN_STARTED.value:
            turn = params.get("turn")
            if isinstance(turn, Mapping):
                turn_id = cast(Mapping[str, object], turn).get("id")
                active_turn_id = turn_id if isinstance(turn_id, str) else None
            status = CodexThreadStatus.ACTIVE
            active_turn_mode = CodexActiveTurnUpdateMode.SET
            activity_at = event.occurred_at
        elif detail is None and event.method == AppServerNotificationName.TURN_COMPLETED.value:
            turn = params.get("turn")
            turn_status = (
                cast(Mapping[str, object], turn).get("status")
                if isinstance(turn, Mapping)
                else None
            )
            status = self._read_thread_status(cast(JsonValue | None, turn_status))
            active_turn_mode = CodexActiveTurnUpdateMode.CLEAR
            activity_at = event.occurred_at
        elif (
            detail is None and event.method == AppServerNotificationName.THREAD_STATUS_CHANGED.value
        ):
            status = self._read_thread_status(params.get("status"))
            active_turn_mode = (
                CodexActiveTurnUpdateMode.PRESERVE
                if status is CodexThreadStatus.ACTIVE
                else CodexActiveTurnUpdateMode.CLEAR
            )
        elif detail is None and event.method == AppServerNotificationName.THREAD_NAME_UPDATED.value:
            raw_name = params.get("threadName")
            display_name = raw_name if isinstance(raw_name, str) and raw_name else None
        elif detail is None and event.method == AppServerNotificationName.THREAD_ARCHIVED.value:
            archived = True
            activity_at = event.occurred_at
        elif detail is None and event.method == AppServerNotificationName.THREAD_UNARCHIVED.value:
            archived = False
            activity_at = event.occurred_at
        execution_settings = (
            detail.execution_settings
            if isinstance(detail, AgentThreadMetadataChangedEventDetail)
            else None
        )
        if (
            status is None
            and display_name is None
            and archived is None
            and activity_at is None
            and execution_settings is None
        ):
            return None
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_thread_repository(
                unit_of_work.get_session()
            )
            thread = repository.get_by_upstream_id_and_owner(
                event.host_id,
                thread_id,
                principal.owner_subject_id,
            )
            if thread is None:
                unit_of_work.commit()
                return None
            if thread.turn_runtime is not None and isinstance(
                detail, AgentThreadChangedEventDetail
            ):
                # Thread metadata has no turn identity or fencing information.
                status = thread_status_for_phase(thread.turn_runtime.phase)
                active_turn_mode = CodexActiveTurnUpdateMode.PRESERVE
                active_turn_id = None
            synchronized_at = datetime.now(UTC)
            if display_name is not None:
                title = CodexThreadTitlePolicy().resolve(
                    created_at=thread.created_at,
                    app_server_title=display_name,
                )
                thread = (
                    repository.promote_title(
                        host_id=event.host_id,
                        upstream_thread_id=thread_id,
                        owner_subject_id=principal.owner_subject_id,
                        display_name=title.display_name,
                        source=title.source,
                        updated_at=synchronized_at,
                    )
                    or thread
                )
            if activity_at is not None:
                thread = (
                    repository.advance_activity(
                        host_id=event.host_id,
                        upstream_thread_id=thread_id,
                        owner_subject_id=principal.owner_subject_id,
                        occurred_at=activity_at,
                    )
                    or thread
                )
            if status is not None or archived is not None or execution_settings is not None:
                thread = (
                    repository.apply_runtime_state(
                        host_id=event.host_id,
                        upstream_thread_id=thread_id,
                        owner_subject_id=principal.owner_subject_id,
                        state_update=CodexThreadRuntimeStateUpdate(
                            status=status,
                            active_turn_mode=active_turn_mode,
                            active_turn_id=active_turn_id,
                            archived=archived,
                            execution_settings=execution_settings,
                            synchronized_at=synchronized_at,
                        ),
                    )
                    or thread
                )
            unit_of_work.commit()
            return thread
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def accept_realtime_events(
        self,
        events: tuple[CodexAgentRealtimeEvent, ...],
        principal: AgentDevicePrincipal,
    ) -> tuple[CodexThreadIndexSnapshot | None, ...]:
        """按 Agent 已验证顺序同步一批控制面事件，不在该层广播浏览器消息。"""

        return tuple(self.accept_realtime_event(event, principal) for event in events)

    def accept_approval_resolved(
        self,
        detail: AgentApprovalResolvedEventDetail,
        host_id: UUID,
        principal: AgentDevicePrincipal,
    ) -> CodexApprovalAuditSnapshot | None:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_approval_repository(
                unit_of_work.get_session()
            )
            approval = repository.get_by_id_and_owner(
                detail.approval_id, principal.owner_subject_id, for_update=True
            )
            if (
                approval is None
                or approval.host_id != host_id
                or approval.thread_id != detail.thread_id
                or approval.turn_id != detail.turn_id
            ):
                return None
            if approval.state in {
                CodexApprovalState.APPLIED,
                CodexApprovalState.CANCELLED,
                CodexApprovalState.EXPIRED,
            }:
                return approval
            now = datetime.now(UTC)
            applied = detail.reason == "resolved" and approval.decision is not None
            updated = approval.model_copy(
                update={
                    "state": CodexApprovalState.APPLIED
                    if applied
                    else CodexApprovalState.EXPIRED
                    if detail.reason == "expired"
                    else CodexApprovalState.CANCELLED,
                    "applied_at": now if applied else approval.applied_at,
                    "updated_at": now,
                }
            )
            repository.save(updated)
            unit_of_work.commit()
            return updated
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def accept_approval_opened(
        self,
        approval: CodexAgentApprovalOpened,
        principal: AgentDevicePrincipal,
    ) -> None:
        """持久化脱敏审批摘要；命令、路径、代码与 Diff 永不落库。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            thread_repository = self._control_port.create_codex_thread_repository(session)
            thread = thread_repository.get_by_upstream_id_and_owner(
                approval.host_id,
                approval.thread_id,
                principal.owner_subject_id,
            )
            if thread is None:
                raise PermissionError("Agent审批thread不属于设备所有者。")
            now = datetime.now(UTC)
            thread_repository.advance_activity(
                host_id=approval.host_id,
                upstream_thread_id=approval.thread_id,
                owner_subject_id=principal.owner_subject_id,
                occurred_at=now,
            )
            repository = self._control_port.create_codex_approval_repository(session)
            if (
                repository.get_by_id_and_owner(
                    approval.approval_id,
                    principal.owner_subject_id,
                    for_update=True,
                )
                is None
            ):
                repository.add(
                    CodexApprovalAuditSnapshot(
                        approval_id=approval.approval_id,
                        owner_subject_id=principal.owner_subject_id,
                        host_id=approval.host_id,
                        workspace_id=thread.workspace_id,
                        thread_id=approval.thread_id,
                        turn_id=approval.turn_id,
                        item_id=approval.item_id,
                        approval_kind=approval.approval_kind,
                        risk_level=approval.risk_level,
                        payload_digest=approval.payload_digest,
                        display_summary=approval.display_summary,
                        state=CodexApprovalState.PENDING,
                        version=approval.version,
                        expires_at=approval.expires_at,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                current = repository.get_by_id_and_owner(
                    approval.approval_id,
                    principal.owner_subject_id,
                    for_update=True,
                )
                if (
                    current is not None
                    and approval.version > current.version
                    and current.state
                    in {
                        CodexApprovalState.PENDING,
                        CodexApprovalState.CLAIMED,
                        CodexApprovalState.DELIVERY_FAILED,
                    }
                ):
                    repository.save(
                        current.model_copy(
                            update={
                                "payload_digest": approval.payload_digest,
                                "display_summary": approval.display_summary,
                                "version": approval.version,
                                "state": CodexApprovalState.PENDING,
                                "decided_by": None,
                                "decision": None,
                                "decided_at": None,
                                "applied_at": None,
                                "expires_at": approval.expires_at,
                                "updated_at": now,
                            }
                        )
                    )
            unit_of_work.commit()
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _update_operation(
        self,
        *,
        operation_id: UUID,
        owner_subject_id: str,
        status: str,
        result_digest: str | None,
    ) -> CodexAppliedOperationProjection | None:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = self._control_port.create_codex_operation_repository(session)
            operation = repository.get_by_id_and_owner(operation_id, owner_subject_id)
            if operation is None:
                # thread.read 等瞬时只读命令不创建控制面 operation。
                unit_of_work.commit()
                return None
            if operation.status in {"completed", "failed"} and status == "acknowledged":
                unit_of_work.commit()
                return None
            now = datetime.now(UTC)
            updated_operation = operation.model_copy(
                update={
                    "status": status,
                    "result_digest": result_digest or operation.result_digest,
                    "accepted_at": (now if status == "acknowledged" else operation.accepted_at),
                    "completed_at": (
                        now if status in {"completed", "failed"} else operation.completed_at
                    ),
                    "updated_at": now,
                }
            )
            repository.save(updated_operation)
            applied_projection = (
                self._projection_service.apply_accepted(
                    session=session,
                    operation=updated_operation,
                )
                if status in {"acknowledged", "completed"}
                else None
            )
            outbox_repository = self._control_port.create_codex_command_outbox_repository(session)
            outbox = outbox_repository.get_by_command_id(operation.command_id)
            if outbox is not None:
                outbox_state = {
                    "acknowledged": CodexCommandOutboxState.ACCEPTED,
                    "completed": CodexCommandOutboxState.COMPLETED,
                    "failed": CodexCommandOutboxState.FAILED,
                    "unknown": CodexCommandOutboxState.UNKNOWN,
                }.get(status)
                if outbox_state is not None:
                    outbox_repository.save(
                        outbox.model_copy(
                            update={
                                "state": outbox_state,
                                "accepted_at": (
                                    now
                                    if outbox_state == CodexCommandOutboxState.ACCEPTED
                                    else outbox.accepted_at
                                ),
                                "completed_at": (
                                    now
                                    if outbox_state
                                    in {
                                        CodexCommandOutboxState.COMPLETED,
                                        CodexCommandOutboxState.FAILED,
                                    }
                                    else outbox.completed_at
                                ),
                                "updated_at": now,
                                "version": outbox.version + 1,
                            }
                        )
                    )
            unit_of_work.commit()
            return applied_projection
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _reconcile_operations(
        self,
        *,
        session: PersistenceSession,
        snapshot: CodexAgentStateSnapshot,
        owner_subject_id: str,
    ) -> None:
        """用 Agent 本地账本收敛断线期间的 operation，未知结果禁止自动重试。"""

        repository = self._control_port.create_codex_operation_repository(session)
        outbox_repository = self._control_port.create_codex_command_outbox_repository(session)
        seen_command_ids: set[str] = set()
        now = snapshot.captured_at
        for raw in snapshot.pending_commands:
            command_id = raw.get("command_id")
            if not isinstance(command_id, str):
                continue
            seen_command_ids.add(command_id)
            try:
                operation = repository.get_by_host_and_command_id(
                    snapshot.host_id,
                    UUID(command_id),
                )
            except ValueError:
                continue
            if operation is None or operation.owner_subject_id != owner_subject_id:
                continue
            state = raw.get("state")
            if state == "completed":
                target_status = "completed"
                error_code = operation.error_code
            elif state == "failed":
                target_status = "failed"
                error_code = operation.error_code or "agent_command_failed"
            else:
                target_status = "unknown"
                error_code = "agent_reconciliation_required"
            updated_operation = operation.model_copy(
                update={
                    "status": target_status,
                    "error_code": error_code,
                    "updated_at": now,
                    "completed_at": now if target_status in {"completed", "failed"} else None,
                }
            )
            repository.save(updated_operation)
            if target_status == "completed":
                self._projection_service.apply_accepted(
                    session=session,
                    operation=updated_operation,
                )
            outbox = outbox_repository.get_by_command_id(operation.command_id)
            if outbox is not None:
                outbox_state = {
                    "completed": CodexCommandOutboxState.COMPLETED,
                    "failed": CodexCommandOutboxState.FAILED,
                    "unknown": CodexCommandOutboxState.UNKNOWN,
                }[target_status]
                outbox_repository.save(
                    outbox.model_copy(
                        update={
                            "state": outbox_state,
                            "completed_at": (
                                now
                                if outbox_state
                                in {
                                    CodexCommandOutboxState.COMPLETED,
                                    CodexCommandOutboxState.FAILED,
                                }
                                else outbox.completed_at
                            ),
                            "updated_at": now,
                            "version": outbox.version + 1,
                        }
                    )
                )
        for operation in repository.list_pending_by_host(
            snapshot.host_id,
            ["pending", "dispatched", "acknowledged", "timed_out"],
        ):
            if str(operation.command_id) in seen_command_ids:
                continue
            repository.save(
                operation.model_copy(
                    update={
                        "status": "unknown",
                        "error_code": "agent_reconciliation_required",
                        "updated_at": now,
                    }
                )
            )
            outbox = outbox_repository.get_by_command_id(operation.command_id)
            if outbox is not None:
                outbox_repository.save(
                    outbox.model_copy(
                        update={
                            "state": CodexCommandOutboxState.UNKNOWN,
                            "updated_at": now,
                            "version": outbox.version + 1,
                        }
                    )
                )

    def _build_workspace_snapshot(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
        captured_at: datetime,
        workspace: CodexAgentWorkspaceSnapshot,
        existing: CodexWorkspaceSnapshot | None,
    ) -> CodexWorkspaceSnapshot:
        return CodexWorkspaceSnapshot(
            workspace_id=existing.workspace_id if existing is not None else uuid4(),
            host_id=host_id,
            owner_subject_id=owner_subject_id,
            agent_workspace_key=workspace.key,
            display_name=workspace.display_name,
            repo_fingerprint=workspace.repo_fingerprint,
            default_branch=workspace.default_branch,
            execution_preferences=(
                existing.execution_preferences
                if existing is not None
                else CodexWorkspaceExecutionPreferences()
            ),
            is_pinned=existing.is_pinned if existing is not None else False,
            enabled=True,
            created_at=existing.created_at if existing is not None else captured_at,
            updated_at=captured_at,
            version=existing.version + 1 if existing is not None else 1,
        )

    def _build_thread_snapshot(
        self,
        *,
        raw_thread: AgentConversationSnapshotDetail,
        host_id: UUID,
        workspace_id: UUID,
        owner_subject_id: str,
        captured_at: datetime,
        existing: CodexThreadIndexSnapshot | None,
    ) -> CodexThreadIndexSnapshot:
        """合并 Agent 索引快照，同时保留服务端已确认的 turn 运行态。"""

        thread_id = raw_thread.thread_id
        raw_status = self._read_raw_thread_status(raw_thread.status)
        status = self._read_thread_status(raw_thread.status)
        if existing is not None and raw_status == "notLoaded":
            # Agent 索引快照尚未加载线程状态时，只能保留服务端权威投影；
            # 将其当作非 active 会把仍在运行的 turn 错误中断。
            status = existing.status
        title_source = raw_thread.title_source
        display_name = raw_thread.display_name
        if existing is not None and existing.title_source is CodexThreadTitleSource.MANUAL:
            title_source = existing.title_source
            display_name = existing.display_name
        runtime = existing.turn_runtime if existing is not None else None
        if (
            runtime is not None
            and runtime.phase
            in {
                CodexTurnPhase.COMPLETED,
                CodexTurnPhase.FAILED,
                CodexTurnPhase.INTERRUPTED,
            }
            and raw_thread.active_turn_id not in {None, runtime.turn_id}
        ):
            # 新 turn 必须等待实时事件重新认领 lease，不能复用已终态 turn 的代次。
            runtime = None
        if runtime is not None:
            # 快照不携带 lease fencing 信息，不能覆盖由实时事件确认的运行阶段。
            status = self._status_for_turn_runtime(runtime)
        recency_candidates = [raw_thread.recency_at]
        if existing is not None:
            recency_candidates.append(existing.recency_at)
        if runtime is not None:
            recency_candidates.append(runtime.last_activity_at)
        return CodexThreadIndexSnapshot(
            thread_index_id=existing.thread_index_id if existing is not None else uuid4(),
            host_id=host_id,
            workspace_id=workspace_id,
            owner_subject_id=owner_subject_id,
            upstream_thread_id=thread_id,
            display_name=display_name,
            title_source=title_source,
            model=raw_thread.model_id or (existing.model if existing is not None else None),
            model_provider=raw_thread.model_provider,
            reasoning_effort=existing.reasoning_effort if existing is not None else None,
            status=status,
            active_turn_id=(
                runtime.turn_id
                if runtime is not None
                and runtime.phase
                not in {
                    CodexTurnPhase.COMPLETED,
                    CodexTurnPhase.FAILED,
                    CodexTurnPhase.INTERRUPTED,
                }
                else raw_thread.active_turn_id
                or (
                    existing.active_turn_id if existing is not None and status == "active" else None
                )
            ),
            turn_runtime=runtime,
            archived=raw_thread.archived,
            is_pinned=existing.is_pinned if existing is not None else False,
            source_kind=raw_thread.source_kind,
            created_at=raw_thread.created_at,
            recency_at=max(recency_candidates),
            updated_at=captured_at,
            last_synced_at=captured_at,
        )

    @staticmethod
    def _status_for_turn_runtime(runtime: CodexTurnRuntime) -> CodexThreadStatus:
        """将不含正文的权威运行阶段投影为旧会话状态契约。"""

        return thread_status_for_phase(runtime.phase)

    def _read_thread_status(self, value: JsonValue | None) -> CodexThreadStatus:
        status = self._read_raw_thread_status(value)
        if status in {"active", "inProgress"}:
            return CodexThreadStatus.ACTIVE
        if status in {"interrupted", "cancelled"}:
            return CodexThreadStatus.INTERRUPTED
        if status in {"failed", "systemError"}:
            return CodexThreadStatus.FAILED
        if status in {"idle", "completed"}:
            return CodexThreadStatus.IDLE
        return CodexThreadStatus.UNKNOWN

    @staticmethod
    def _read_raw_thread_status(value: JsonValue | None) -> str | None:
        """读取 Agent 快照原始状态，保留 ``notLoaded`` 的专用语义。"""

        status: str | None = None
        if isinstance(value, Mapping):
            status_type = cast(Mapping[str, object], value).get("type")
            if isinstance(status_type, str):
                status = status_type
        elif isinstance(value, str):
            status = value
        return status
