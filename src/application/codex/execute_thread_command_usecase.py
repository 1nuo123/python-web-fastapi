"""创建 thread 与启动 turn 的幂等命令受理用例。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.application.ports.codex_agent_command_dispatch_port import (
    CodexAgentCommandDispatchPort,
)
from src.application.ports.codex_command_payload_cipher_port import (
    CodexCommandPayloadCipherPort,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.command_outbox_contract import (
    CodexCommandOutboxSnapshot,
    CodexCommandOutboxState,
)
from src.core.codex_contract.connection_session_contract import CodexHostOfflineError
from src.core.codex_contract.host_contract import (
    CodexHostCompatibilityState,
    CodexHostSnapshot,
)
from src.core.codex_contract.operation_contract import CodexControlOperationSnapshot
from src.core.codex_contract.product_command_contract import (
    CodexProductCommandCatalog,
    CodexProductCommandCode,
)
from src.core.codex_contract.turn_contract import CodexExecutionOptions, CodexOperationAccepted
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession, UnitOfWork
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.domain.codex.codex_error_code import CodexErrorCode
from src.domain.codex.host_status import CodexOperationStatus


@dataclass(frozen=True, slots=True)
class PreparedCodexOperation:
    """数据库已提交、可使用固定 command id 投递的操作。"""

    operation: CodexControlOperationSnapshot
    command: CodexAgentCommand
    already_accepted: bool


class ExecuteCodexThreadCommandUsecase:
    """把 HTTP 幂等与 Agent 副作用去重串联为两层保证。"""

    def __init__(
        self,
        *,
        control_port: CodexControlPort,
        dispatch_port: CodexAgentCommandDispatchPort,
        payload_cipher: CodexCommandPayloadCipherPort,
        ack_timeout_seconds: int,
        outbox_ttl_seconds: int,
    ) -> None:
        self._control_port = control_port
        self._dispatch_port = dispatch_port
        self._payload_cipher = payload_cipher
        self._ack_timeout_seconds = ack_timeout_seconds
        self._outbox_ttl_seconds = outbox_ttl_seconds
        self._command_catalog = CodexProductCommandCatalog()

    async def start_thread(
        self,
        *,
        host_id: UUID,
        workspace_id: UUID,
        execution: CodexExecutionOptions,
        actor_subject_id: str,
        idempotency_key: str,
    ) -> CodexOperationAccepted:
        """创建 thread；cwd 只由 Agent 本地 workspace registry 注入。"""

        params: dict[str, JsonValue] = {}
        if execution.model is not None:
            params["model"] = execution.model
        prepared = await asyncio.to_thread(
            self._prepare_workspace_operation,
            host_id=host_id,
            workspace_id=workspace_id,
            actor_subject_id=actor_subject_id,
            idempotency_key=idempotency_key,
            operation_type="thread.start",
            params=params,
            execution=execution,
        )
        return await self._dispatch(prepared)

    async def start_turn(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        message: str,
        execution: CodexExecutionOptions,
        actor_subject_id: str,
        idempotency_key: str,
    ) -> CodexOperationAccepted:
        """向所有权已确认的 thread 发起文本 turn。"""

        params: dict[str, JsonValue] = {
            "threadId": upstream_thread_id,
            "input": [{"type": "text", "text": message, "text_elements": []}],
        }
        if execution.model is not None:
            params["model"] = execution.model
        if execution.reasoning_effort is not None:
            params["effort"] = execution.reasoning_effort
        prepared = await asyncio.to_thread(
            self._prepare_thread_operation,
            host_id=host_id,
            upstream_thread_id=upstream_thread_id,
            actor_subject_id=actor_subject_id,
            idempotency_key=idempotency_key,
            operation_type="turn.start",
            params=params,
            execution=execution,
        )
        return await self._dispatch(prepared)

    async def steer_turn(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        message: str,
        actor_subject_id: str,
        idempotency_key: str,
    ) -> CodexOperationAccepted:
        """向当前 active turn 追加文本输入并固定 expectedTurnId。"""

        prepared = await asyncio.to_thread(
            self._prepare_active_turn_operation,
            host_id=host_id,
            upstream_thread_id=upstream_thread_id,
            actor_subject_id=actor_subject_id,
            idempotency_key=idempotency_key,
            operation_type="turn.steer",
            params={
                "threadId": upstream_thread_id,
                "input": [{"type": "text", "text": message, "text_elements": []}],
            },
        )
        return await self._dispatch(prepared)

    async def interrupt_turn(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        actor_subject_id: str,
        idempotency_key: str,
    ) -> CodexOperationAccepted:
        """幂等中断当前 active turn。"""

        prepared = await asyncio.to_thread(
            self._prepare_active_turn_operation,
            host_id=host_id,
            upstream_thread_id=upstream_thread_id,
            actor_subject_id=actor_subject_id,
            idempotency_key=idempotency_key,
            operation_type="turn.interrupt",
            params={"threadId": upstream_thread_id},
        )
        return await self._dispatch(prepared)

    async def resume_thread(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        actor_subject_id: str,
        idempotency_key: str,
    ) -> CodexOperationAccepted:
        """在所属工作区恢复已持久化 thread。"""

        prepared = await asyncio.to_thread(
            self._prepare_thread_operation,
            host_id=host_id,
            upstream_thread_id=upstream_thread_id,
            actor_subject_id=actor_subject_id,
            idempotency_key=idempotency_key,
            operation_type="thread.resume",
            params={"threadId": upstream_thread_id},
        )
        return await self._dispatch(prepared)

    async def compact_thread(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        actor_subject_id: str,
        idempotency_key: str,
    ) -> CodexOperationAccepted:
        """在 capability 允许时启动线程上下文压缩。"""

        prepared = await asyncio.to_thread(
            self._prepare_thread_operation,
            host_id=host_id,
            upstream_thread_id=upstream_thread_id,
            actor_subject_id=actor_subject_id,
            idempotency_key=idempotency_key,
            operation_type=CodexProductCommandCode.THREAD_COMPACT.value,
            params={"threadId": upstream_thread_id},
            execution=None,
        )
        return await self._dispatch(prepared)

    async def _dispatch(
        self,
        prepared: PreparedCodexOperation,
    ) -> CodexOperationAccepted:
        """重放终态直接返回；其余始终沿原 command id 投递。"""

        if prepared.already_accepted:
            return self._to_acceptance(prepared.operation, replayed=True)
        try:
            ack = await self._dispatch_port.dispatch(
                prepared.command,
                ack_timeout_seconds=self._ack_timeout_seconds,
            )
        except CodexHostOfflineError as exc:
            await asyncio.to_thread(
                self._update_operation_status,
                prepared.operation.operation_id,
                prepared.operation.owner_subject_id,
                CodexOperationStatus.FAILED,
                CodexErrorCode.HOST_OFFLINE.value,
            )
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CodexErrorCode.HOST_OFFLINE,
                message="Codex主机离线，operation可按原Idempotency-Key重试。",
            ) from exc
        except TimeoutError as exc:
            await asyncio.to_thread(
                self._update_operation_status,
                prepared.operation.operation_id,
                prepared.operation.owner_subject_id,
                CodexOperationStatus.TIMED_OUT,
                CodexErrorCode.AGENT_ACK_TIMEOUT.value,
            )
            raise HttpFaultException(
                status_code=HTTPStatus.GATEWAY_TIMEOUT,
                error_code=CodexErrorCode.AGENT_ACK_TIMEOUT,
                message="Agent未在时限内确认，结果必须按原operation核对。",
            ) from exc
        if ack.state == "deferred":
            return self._to_acceptance(prepared.operation, replayed=ack.replayed)
        target_status = (
            CodexOperationStatus.ACKNOWLEDGED
            if ack.state in {"accepted", "completed", "received", "executing"}
            else CodexOperationStatus.FAILED
        )
        updated = await asyncio.to_thread(
            self._update_operation_status,
            prepared.operation.operation_id,
            prepared.operation.owner_subject_id,
            target_status,
        )
        return self._to_acceptance(updated, replayed=ack.replayed)

    def _prepare_workspace_operation(
        self,
        *,
        host_id: UUID,
        workspace_id: UUID,
        actor_subject_id: str,
        idempotency_key: str,
        operation_type: str,
        params: dict[str, JsonValue],
        execution: CodexExecutionOptions | None,
    ) -> PreparedCodexOperation:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            host_repository = self._control_port.create_codex_host_repository(session)
            host = host_repository.get_by_id_and_owner(host_id, actor_subject_id)
            if host is None:
                raise self._not_found()
            self._validate_host_command(host, operation_type, execution)
            workspace_repository = self._control_port.create_codex_workspace_repository(session)
            workspace = workspace_repository.get_by_id_and_owner(
                workspace_id,
                actor_subject_id,
            )
            if workspace is None or workspace.host_id != host_id or not workspace.enabled:
                raise self._not_found()
            command_params = dict(params)
            command_params["workspace_key"] = workspace.agent_workspace_key
            if (
                operation_type == CodexProductCommandCode.THREAD_START.value
                and workspace.worktree_policy.enabled
            ):
                command_params["worktree_policy"] = workspace.worktree_policy.model_dump(
                    mode="json",
                    exclude={"managed_root"},
                )
            prepared = self._build_or_reuse_operation(
                unit_of_work=unit_of_work,
                session=session,
                host_id=host_id,
                workspace_id=workspace_id,
                thread_id=None,
                actor_subject_id=actor_subject_id,
                idempotency_key=idempotency_key,
                operation_type=operation_type,
                params=command_params,
            )
            unit_of_work.commit()
            return prepared
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _prepare_thread_operation(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        actor_subject_id: str,
        idempotency_key: str,
        operation_type: str,
        params: dict[str, JsonValue],
        execution: CodexExecutionOptions | None = None,
    ) -> PreparedCodexOperation:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            host_repository = self._control_port.create_codex_host_repository(session)
            host = host_repository.get_by_id_and_owner(host_id, actor_subject_id)
            if host is None:
                raise self._not_found()
            self._validate_host_command(host, operation_type, execution)
            thread_repository = self._control_port.create_codex_thread_repository(session)
            thread = thread_repository.get_by_upstream_id_and_owner(
                host_id,
                upstream_thread_id,
                actor_subject_id,
            )
            if thread is None:
                raise self._not_found()
            workspace_repository = self._control_port.create_codex_workspace_repository(session)
            workspace = workspace_repository.get_by_id_and_owner(
                thread.workspace_id,
                actor_subject_id,
            )
            if workspace is None or not workspace.enabled:
                raise self._not_found()
            command_params = dict(params)
            command_params["workspace_key"] = workspace.agent_workspace_key
            prepared = self._build_or_reuse_operation(
                unit_of_work=unit_of_work,
                session=session,
                host_id=host_id,
                workspace_id=thread.workspace_id,
                thread_id=upstream_thread_id,
                actor_subject_id=actor_subject_id,
                idempotency_key=idempotency_key,
                operation_type=operation_type,
                params=command_params,
            )
            unit_of_work.commit()
            return prepared
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _prepare_active_turn_operation(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        actor_subject_id: str,
        idempotency_key: str,
        operation_type: str,
        params: dict[str, JsonValue],
    ) -> PreparedCodexOperation:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            host = self._control_port.create_codex_host_repository(session).get_by_id_and_owner(
                host_id, actor_subject_id
            )
            if host is None:
                raise self._not_found()
            self._validate_host_command(host, operation_type, None)
            thread_repository = self._control_port.create_codex_thread_repository(session)
            thread = thread_repository.get_by_upstream_id_and_owner(
                host_id,
                upstream_thread_id,
                actor_subject_id,
            )
            if thread is None:
                raise self._not_found()
            if thread.active_turn_id is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.CONFLICT,
                    error_code=CodexErrorCode.STATE_CONFLICT,
                    message="Codex thread当前没有可操作的active turn。",
                )
            workspace_repository = self._control_port.create_codex_workspace_repository(session)
            workspace = workspace_repository.get_by_id_and_owner(
                thread.workspace_id,
                actor_subject_id,
            )
            if workspace is None or not workspace.enabled:
                raise self._not_found()
            command_params = dict(params)
            command_params["workspace_key"] = workspace.agent_workspace_key
            command_params["expectedTurnId" if operation_type == "turn.steer" else "turnId"] = (
                thread.active_turn_id
            )
            prepared = self._build_or_reuse_operation(
                unit_of_work=unit_of_work,
                session=session,
                host_id=host_id,
                workspace_id=thread.workspace_id,
                thread_id=upstream_thread_id,
                actor_subject_id=actor_subject_id,
                idempotency_key=idempotency_key,
                operation_type=operation_type,
                params=command_params,
            )
            unit_of_work.commit()
            return prepared
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _build_or_reuse_operation(
        self,
        *,
        unit_of_work: UnitOfWork,
        session: PersistenceSession,
        host_id: UUID,
        workspace_id: UUID,
        thread_id: str | None,
        actor_subject_id: str,
        idempotency_key: str,
        operation_type: str,
        params: dict[str, JsonValue],
    ) -> PreparedCodexOperation:
        repository = self._control_port.create_codex_operation_repository(session)
        request_digest = calculate_agent_request_digest(operation_type, params)
        existing = repository.get_by_actor_and_idempotency_key(
            actor_subject_id,
            idempotency_key,
        )
        now = datetime.now(UTC)
        if existing is not None:
            if existing.request_digest != request_digest:
                raise HttpFaultException(
                    status_code=HTTPStatus.CONFLICT,
                    error_code=CodexErrorCode.IDEMPOTENCY_CONFLICT,
                    message="Idempotency-Key已用于不同请求。",
                )
            if existing.status == "unknown":
                raise HttpFaultException(
                    status_code=HTTPStatus.CONFLICT,
                    error_code=CodexErrorCode.STATE_CONFLICT,
                    message="Codex操作结果未知，必须先读取权威thread快照。",
                )
            operation = existing.model_copy(
                update={
                    "status": CodexOperationStatus.DISPATCHED.value,
                    "dispatch_attempt": existing.dispatch_attempt + 1,
                    "last_dispatched_at": now,
                    "ack_deadline_at": now + timedelta(seconds=self._ack_timeout_seconds),
                    "updated_at": now,
                }
            )
            already_accepted = existing.status in {
                CodexOperationStatus.ACKNOWLEDGED.value,
                CodexOperationStatus.COMPLETED.value,
            }
            if not already_accepted:
                repository.save(operation)
            else:
                operation = existing
        else:
            operation = CodexControlOperationSnapshot(
                operation_id=uuid4(),
                command_id=uuid4(),
                actor_subject_id=actor_subject_id,
                owner_subject_id=actor_subject_id,
                host_id=host_id,
                workspace_id=workspace_id,
                thread_id=thread_id,
                operation_type=operation_type,
                idempotency_key=idempotency_key,
                request_digest=request_digest,
                status=CodexOperationStatus.DISPATCHED.value,
                dispatch_attempt=1,
                last_dispatched_at=now,
                ack_deadline_at=now + timedelta(seconds=self._ack_timeout_seconds),
                created_at=now,
                updated_at=now,
            )
            repository.add(operation)
            unit_of_work.flush()
            already_accepted = False
        command = CodexAgentCommand(
            command_id=operation.command_id,
            operation_id=operation.operation_id,
            host_id=host_id,
            request_digest=request_digest,
            command_type=operation_type,
            params=params,
            deadline=now + timedelta(seconds=self._ack_timeout_seconds),
        )
        outbox_repository = self._control_port.create_codex_command_outbox_repository(session)
        if outbox_repository.get_by_command_id(operation.command_id) is None:
            outbox_repository.add(
                CodexCommandOutboxSnapshot(
                    outbox_id=uuid4(),
                    operation_id=operation.operation_id,
                    command_id=operation.command_id,
                    host_id=host_id,
                    owner_subject_id=actor_subject_id,
                    payload=self._payload_cipher.encrypt(command, actor_subject_id),
                    state=CodexCommandOutboxState.PENDING,
                    dispatch_attempt=0,
                    available_at=now,
                    expires_at=now + timedelta(seconds=self._outbox_ttl_seconds),
                    created_at=now,
                    updated_at=now,
                    version=1,
                )
            )
        return PreparedCodexOperation(
            operation=operation,
            command=command,
            already_accepted=already_accepted,
        )

    def _update_operation_status(
        self,
        operation_id: UUID,
        owner_subject_id: str,
        status: CodexOperationStatus,
        error_code: str | None = None,
    ) -> CodexControlOperationSnapshot:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_operation_repository(
                unit_of_work.get_session()
            )
            operation = repository.get_by_id_and_owner(operation_id, owner_subject_id)
            if operation is None:
                raise RuntimeError("Codex operation状态更新目标不存在。")
            if operation.status in {
                CodexOperationStatus.COMPLETED.value,
                CodexOperationStatus.FAILED.value,
            }:
                return operation
            now = datetime.now(UTC)
            updated = operation.model_copy(
                update={
                    "status": status.value,
                    "accepted_at": now
                    if status == CodexOperationStatus.ACKNOWLEDGED
                    else operation.accepted_at,
                    "completed_at": now
                    if status == CodexOperationStatus.COMPLETED
                    else operation.completed_at,
                    "error_code": error_code,
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

    def _to_acceptance(
        self,
        operation: CodexControlOperationSnapshot,
        *,
        replayed: bool,
    ) -> CodexOperationAccepted:
        return CodexOperationAccepted(
            operation_id=operation.operation_id,
            command_id=operation.command_id,
            status=operation.status,
            replayed=replayed,
        )

    def _not_found(self) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.NOT_FOUND,
            error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
            message="Codex资源不存在。",
        )

    def _validate_host_command(
        self,
        host: CodexHostSnapshot,
        operation_type: str,
        execution: CodexExecutionOptions | None,
    ) -> None:
        try:
            command = CodexProductCommandCode(operation_type)
        except ValueError as exc:
            raise HttpFaultException(
                status_code=HTTPStatus.BAD_REQUEST,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="Codex产品命令不受支持。",
            ) from exc
        policy = self._command_catalog.read(command)
        capability_codes = {item.code for item in host.capabilities.items}
        if policy.required_capability not in capability_codes:
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="当前Agent capability不支持该操作。",
            )
        if host.compatibility.state != CodexHostCompatibilityState.COMPATIBLE:
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="当前Agent兼容状态不允许执行修改操作。",
            )
        if execution is None:
            return
        if execution.model is not None and execution.model not in host.capabilities.model_ids:
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="所选模型不在Agent capability快照中。",
            )
        if (
            execution.reasoning_effort is not None
            and execution.reasoning_effort not in host.capabilities.reasoning_efforts
        ):
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="所选推理强度不在Agent capability快照中。",
            )
        if execution.sandbox_mode not in host.capabilities.sandbox_modes:
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="所选沙箱模式不在Agent capability快照中。",
            )
        if execution.approval_policy not in host.capabilities.approval_policies:
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="所选审批策略不在Agent capability快照中。",
            )
