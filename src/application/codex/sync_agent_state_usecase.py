"""Agent hello、心跳与 snapshot 的控制面索引同步用例。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentApprovalOpened,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
    CodexAgentHeartbeat,
    CodexAgentHello,
    CodexAgentRealtimeEvent,
    CodexAgentStateSnapshot,
    CodexAgentWorkspaceSnapshot,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerCapabilityCode,
    AppServerCapabilityDetail,
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
    CodexHostCompatibilityState,
    CodexSandboxMode,
)
from src.core.codex_contract.thread_contract import CodexThreadIndexSnapshot
from src.core.codex_contract.workspace_contract import CodexWorkspaceSnapshot
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession
from src.domain.codex.codex_compatibility_policy import CodexCompatibilityDecision


class SyncCodexAgentStateUsecase:
    """仅同步控制元数据，不保存 prompt、Diff 或终端正文。"""

    def __init__(self, control_port: CodexControlPort) -> None:
        self._control_port = control_port

    def accept_hello(
        self,
        hello: CodexAgentHello,
        principal: AgentDevicePrincipal,
    ) -> None:
        """把设备认证后的 hello 写入所属主机。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_host_repository(unit_of_work.get_session())
            host = repository.get_by_id_and_owner(hello.host_id, principal.owner_subject_id)
            if host is None:
                raise PermissionError("Agent凭据绑定的主机不存在。")
            now = datetime.now(UTC)
            repository.save(
                host.model_copy(
                    update={
                        "agent_version": hello.agent_version,
                        "codex_version": hello.codex_version,
                        "agent_protocol_version": hello.agent_protocol_version,
                        "app_server_schema_digest": hello.app_server_schema_digest,
                        "status": "online",
                        "capabilities": self._map_host_capabilities(hello),
                        "last_seen_at": now,
                        "updated_at": now,
                        "version": host.version + 1,
                    }
                )
            )
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
            host = repository.get_by_id_and_owner(host_id, principal.owner_subject_id)
            if host is None:
                raise PermissionError("Agent兼容性主机不存在。")
            now = datetime.now(UTC)
            repository.save(
                host.model_copy(
                    update={
                        "compatibility": CodexHostCompatibilityDetail(
                            state=CodexHostCompatibilityState(decision.value),
                        ),
                        "updated_at": now,
                        "version": host.version + 1,
                    }
                )
            )
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
            host = repository.get_by_id_and_owner(
                heartbeat.host_id,
                principal.owner_subject_id,
            )
            if host is None:
                raise PermissionError("Agent心跳主机不存在。")
            now = datetime.now(UTC)
            repository.save(
                host.model_copy(
                    update={
                        "status": "online",
                        "last_seen_at": now,
                        "updated_at": now,
                        "version": host.version + 1,
                    }
                )
            )
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
    ) -> None:
        """仅在当前权威连接消失后把所属主机标记离线。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_host_repository(unit_of_work.get_session())
            host = repository.get_by_id_and_owner(host_id, principal.owner_subject_id)
            if host is None:
                unit_of_work.commit()
                return
            now = datetime.now(UTC)
            repository.save(
                host.model_copy(
                    update={
                        "status": "offline",
                        "updated_at": now,
                        "version": host.version + 1,
                    }
                )
            )
            unit_of_work.commit()
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
                    workspace_repository.add(workspace_state)
                else:
                    workspace_repository.save(workspace_state)
            # Make newly discovered workspace rows visible to the thread foreign key
            # before SQLAlchemy batches the thread index inserts.
            unit_of_work.flush()
            for raw_thread in snapshot.threads:
                workspace_key = raw_thread.get("workspaceKey")
                thread_id = raw_thread.get("id")
                if not isinstance(workspace_key, str) or not isinstance(thread_id, str):
                    raise ValueError("Agent线程快照缺少workspaceKey或id。")
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
    ) -> None:
        """收敛 HTTP 超时后迟到或重连回放的 Agent ack。"""

        if ack.state not in {"received", "executing", "accepted", "completed", "failed", "unknown"}:
            return
        if ack.state == "unknown":
            status = "unknown"
        elif ack.state == "failed":
            status = "failed"
        else:
            status = "acknowledged"
        self._update_operation(
            operation_id=ack.operation_id,
            owner_subject_id=principal.owner_subject_id,
            status=status,
            result_digest=None,
        )

    def accept_command_result(
        self,
        result: CodexAgentCommandResult,
        principal: AgentDevicePrincipal,
    ) -> None:
        """把 Agent 最终结果收敛到 operation，正文只计算摘要不落库。"""

        if result.outcome == "unknown":
            self._update_operation(
                operation_id=result.operation_id,
                owner_subject_id=principal.owner_subject_id,
                status="unknown",
                result_digest=None,
            )
            return
        result_digest = hashlib.sha256(
            json.dumps(
                result.result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        self._materialize_started_thread(result, principal)
        self._update_operation(
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
                thread_repository.add(
                    CodexThreadIndexSnapshot(
                        thread_index_id=uuid4(),
                        host_id=operation.host_id,
                        workspace_id=operation.workspace_id,
                        owner_subject_id=principal.owner_subject_id,
                        upstream_thread_id=thread_id,
                        display_name=None,
                        model=None,
                        reasoning_effort=None,
                        status="idle",
                        active_turn_id=None,
                        archived=False,
                        source_kind="remote",
                        created_at=now,
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

    def accept_realtime_event(
        self,
        event: CodexAgentRealtimeEvent,
        principal: AgentDevicePrincipal,
    ) -> None:
        """用 turn/thread 生命周期事件更新控制面并发事实，不保存正文。"""

        if not isinstance(event.params, Mapping):
            return
        params = cast(Mapping[str, JsonValue], event.params)
        thread_id = params.get("threadId")
        if not isinstance(thread_id, str):
            return
        status: str | None = None
        active_turn_id: str | None = None
        if event.method == "turn/started":
            turn = params.get("turn")
            if isinstance(turn, Mapping):
                turn_id = cast(Mapping[str, object], turn).get("id")
                active_turn_id = turn_id if isinstance(turn_id, str) else None
            status = "active"
        elif event.method == "turn/completed":
            turn = params.get("turn")
            turn_status = (
                cast(Mapping[str, object], turn).get("status")
                if isinstance(turn, Mapping)
                else None
            )
            status = self._read_thread_status(cast(JsonValue | None, turn_status))
            if status == "completed":
                status = "idle"
        elif event.method == "thread/status/changed":
            status = self._read_thread_status(params.get("status"))
            active_turn_id = None
        if status is None:
            return
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
                return
            repository.save(
                thread.model_copy(
                    update={
                        "status": status,
                        "active_turn_id": active_turn_id,
                        "updated_at": datetime.now(UTC),
                        "last_synced_at": datetime.now(UTC),
                    }
                )
            )
            unit_of_work.commit()
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
            thread = self._control_port.create_codex_thread_repository(
                session
            ).get_by_upstream_id_and_owner(
                approval.host_id,
                approval.thread_id,
                principal.owner_subject_id,
            )
            if thread is None:
                raise PermissionError("Agent审批thread不属于设备所有者。")
            repository = self._control_port.create_codex_approval_repository(session)
            if (
                repository.get_by_id_and_owner(
                    approval.approval_id,
                    principal.owner_subject_id,
                )
                is None
            ):
                now = datetime.now(UTC)
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
                        version=1,
                        expires_at=approval.expires_at,
                        created_at=now,
                        updated_at=now,
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
    ) -> None:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = self._control_port.create_codex_operation_repository(session)
            operation = repository.get_by_id_and_owner(operation_id, owner_subject_id)
            if operation is None:
                # thread.read 等瞬时只读命令不创建控制面 operation。
                unit_of_work.commit()
                return
            if operation.status in {"completed", "failed"} and status == "acknowledged":
                unit_of_work.commit()
                return
            now = datetime.now(UTC)
            repository.save(
                operation.model_copy(
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
            repository.save(
                operation.model_copy(
                    update={
                        "status": target_status,
                        "error_code": error_code,
                        "updated_at": now,
                        "completed_at": now if target_status in {"completed", "failed"} else None,
                    }
                )
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
            enabled=True,
            created_at=existing.created_at if existing is not None else captured_at,
            updated_at=captured_at,
            version=existing.version + 1 if existing is not None else 1,
        )

    def _build_thread_snapshot(
        self,
        *,
        raw_thread: Mapping[str, JsonValue],
        host_id: UUID,
        workspace_id: UUID,
        owner_subject_id: str,
        captured_at: datetime,
        existing: CodexThreadIndexSnapshot | None,
    ) -> CodexThreadIndexSnapshot:
        thread_id = self._read_required_string(raw_thread, "id")
        status = self._read_thread_status(raw_thread.get("status"))
        if existing is not None and existing.status == "active" and status != "active":
            status = "interrupted"
        created_at = self._read_epoch(raw_thread.get("createdAt"))
        updated_at = self._read_epoch(raw_thread.get("updatedAt")) or captured_at
        name = raw_thread.get("name")
        preview = raw_thread.get("preview")
        display_name = name if isinstance(name, str) and name else preview
        model_provider = raw_thread.get("modelProvider")
        source = raw_thread.get("threadSource") or raw_thread.get("source")
        return CodexThreadIndexSnapshot(
            thread_index_id=existing.thread_index_id if existing is not None else uuid4(),
            host_id=host_id,
            workspace_id=workspace_id,
            owner_subject_id=owner_subject_id,
            upstream_thread_id=thread_id,
            display_name=(display_name[:256] if isinstance(display_name, str) else None),
            model=model_provider if isinstance(model_provider, str) else None,
            reasoning_effort=None,
            status=status,
            active_turn_id=(
                self._read_active_turn_id(raw_thread)
                or (
                    existing.active_turn_id if existing is not None and status == "active" else None
                )
            ),
            archived=False,
            source_kind=source if isinstance(source, str) else None,
            created_at=created_at,
            updated_at=updated_at,
            last_synced_at=captured_at,
        )

    def _read_required_string(
        self,
        mapping: Mapping[str, JsonValue],
        key: str,
    ) -> str:
        value = mapping.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Agent线程快照缺少{key}。")
        return value

    def _read_thread_status(self, value: JsonValue | None) -> str:
        if isinstance(value, Mapping):
            status_type = cast(Mapping[str, object], value).get("type")
            if isinstance(status_type, str):
                return "unknown" if status_type == "systemError" else status_type
        return value if isinstance(value, str) else "unknown"

    def _read_epoch(self, value: JsonValue | None) -> datetime | None:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return datetime.fromtimestamp(value, tz=UTC)
        return None

    def _read_active_turn_id(self, raw_thread: Mapping[str, JsonValue]) -> str | None:
        turns = raw_thread.get("turns")
        if not isinstance(turns, list):
            return None
        for raw_turn in reversed(turns):
            if not isinstance(raw_turn, Mapping):
                continue
            turn = cast(Mapping[str, JsonValue], raw_turn)
            if self._read_thread_status(turn.get("status")) not in {"active", "inProgress"}:
                continue
            turn_id = turn.get("id")
            return turn_id if isinstance(turn_id, str) else None
        return None
