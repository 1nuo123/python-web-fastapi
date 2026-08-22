"""创建 thread 与启动 turn 的幂等命令受理用例。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.application.codex.operation_projection_service import (
    CodexAppliedOperationProjection,
    CodexOperationProjectionService,
)
from src.application.ports.codex_agent_command_dispatch_port import (
    CodexAgentCommandDispatchPort,
)
from src.application.ports.codex_command_payload_cipher_port import (
    CodexCommandPayloadCipherPort,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.application.ports.codex_realtime_event_port import CodexRealtimeEventPort
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
from src.core.codex_contract.operation_contract import (
    CodexControlOperationSnapshot,
    CodexOperationProjection,
    CodexOperationProjectionHeader,
    CodexOperationProjectionKind,
    CodexTurnSubmissionProjectionDetail,
)
from src.core.codex_contract.product_command_contract import (
    CodexProductCommandCatalog,
    CodexProductCommandCode,
)
from src.core.codex_contract.thread_contract import CodexThreadTitleSource
from src.core.codex_contract.turn_contract import CodexExecutionOptions, CodexOperationAccepted
from src.core.codex_contract.turn_runtime_contract import CodexTurnPhase
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession, UnitOfWork
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.domain.codex.codex_error_code import CodexErrorCode
from src.domain.codex.host_status import CodexOperationStatus
from src.domain.codex.thread_title_policy import CodexThreadTitlePolicy


@dataclass(frozen=True, slots=True)
class PreparedCodexOperation:
    """数据库已提交、可使用固定 command id 投递的操作。"""

    operation: CodexControlOperationSnapshot
    command: CodexAgentCommand
    already_accepted: bool


@dataclass(frozen=True, slots=True)
class CodexManualTitleUpdate:
    """在命令事务内先提交的手工标题。"""

    display_name: str


@dataclass(frozen=True, slots=True)
class CodexOperationStatusUpdate:
    """operation 状态更新与同事务派生投影结果。"""

    operation: CodexControlOperationSnapshot
    applied_projection: CodexAppliedOperationProjection | None


class ExecuteCodexThreadCommandUsecase:
    """把 HTTP 幂等与 Agent 副作用去重串联为两层保证。"""

    def __init__(
        self,
        *,
        control_port: CodexControlPort,
        dispatch_port: CodexAgentCommandDispatchPort,
        payload_cipher: CodexCommandPayloadCipherPort,
        event_port: CodexRealtimeEventPort,
        ack_timeout_seconds: int,
        outbox_ttl_seconds: int,
    ) -> None:
        self._control_port = control_port
        self._dispatch_port = dispatch_port
        self._payload_cipher = payload_cipher
        self._event_port = event_port
        self._ack_timeout_seconds = ack_timeout_seconds
        self._outbox_ttl_seconds = outbox_ttl_seconds
        self._command_catalog = CodexProductCommandCatalog()
        self._projection_service = CodexOperationProjectionService(control_port)

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
        client_operation_id: UUID,
    ) -> CodexOperationAccepted:
        """向所有权已确认的 thread 发起文本 turn。"""

        params: dict[str, JsonValue] = {
            "threadId": upstream_thread_id,
            # 官方 0.145.0 字段把 HTTP 重试身份贯穿到上游 turn。
            "clientUserMessageId": str(client_operation_id),
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
            operation_projection=CodexOperationProjection(
                header=CodexOperationProjectionHeader(
                    detail_kind=CodexOperationProjectionKind.TURN_SUBMISSION,
                ),
                detail=CodexTurnSubmissionProjectionDetail(
                    display_name=CodexThreadTitlePolicy().normalize(message),
                    occurred_at=datetime.now(UTC),
                ),
            ),
        )
        return (await self._dispatch(prepared)).model_copy(
            update={"client_operation_id": client_operation_id}
        )

    async def steer_turn(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        message: str,
        actor_subject_id: str,
        idempotency_key: str,
        client_operation_id: UUID,
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
                "clientUserMessageId": str(client_operation_id),
                "input": [{"type": "text", "text": message, "text_elements": []}],
            },
            operation_projection=CodexOperationProjection(
                header=CodexOperationProjectionHeader(
                    detail_kind=CodexOperationProjectionKind.TURN_SUBMISSION,
                ),
                detail=CodexTurnSubmissionProjectionDetail(
                    display_name=None,
                    occurred_at=datetime.now(UTC),
                ),
            ),
        )
        return (await self._dispatch(prepared)).model_copy(
            update={"client_operation_id": client_operation_id}
        )

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

    async def rename_thread(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        display_name: str,
        actor_subject_id: str,
        idempotency_key: str,
    ) -> CodexOperationAccepted:
        """先保存手工标题，再可靠投递 ``thread/name/set``。"""

        normalized_title = CodexThreadTitlePolicy().normalize(display_name)
        if normalized_title is None:
            raise HttpFaultException(
                status_code=HTTPStatus.BAD_REQUEST,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="Codex会话标题不能为空白。",
            )
        prepared = await asyncio.to_thread(
            self._prepare_thread_operation,
            host_id=host_id,
            upstream_thread_id=upstream_thread_id,
            actor_subject_id=actor_subject_id,
            idempotency_key=idempotency_key,
            operation_type=CodexProductCommandCode.THREAD_NAME_SET.value,
            params={
                "threadId": upstream_thread_id,
                "name": normalized_title,
            },
            local_title_update=CodexManualTitleUpdate(normalized_title),
        )
        return await self._dispatch(prepared)

    async def archive_thread(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        actor_subject_id: str,
        idempotency_key: str,
    ) -> CodexOperationAccepted:
        """投递归档命令，最终状态由成功结果或通知确认。"""

        prepared = await asyncio.to_thread(
            self._prepare_thread_operation,
            host_id=host_id,
            upstream_thread_id=upstream_thread_id,
            actor_subject_id=actor_subject_id,
            idempotency_key=idempotency_key,
            operation_type=CodexProductCommandCode.THREAD_ARCHIVE.value,
            params={"threadId": upstream_thread_id},
        )
        return await self._dispatch(prepared)

    async def unarchive_thread(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        actor_subject_id: str,
        idempotency_key: str,
    ) -> CodexOperationAccepted:
        """投递恢复归档命令，最终状态由成功结果或通知确认。"""

        prepared = await asyncio.to_thread(
            self._prepare_thread_operation,
            host_id=host_id,
            upstream_thread_id=upstream_thread_id,
            actor_subject_id=actor_subject_id,
            idempotency_key=idempotency_key,
            operation_type=CodexProductCommandCode.THREAD_UNARCHIVE.value,
            params={"threadId": upstream_thread_id},
        )
        return await self._dispatch(prepared)

    async def _dispatch(
        self,
        prepared: PreparedCodexOperation,
    ) -> CodexOperationAccepted:
        """重放终态直接返回；其余始终沿原 command id 投递。"""

        if prepared.already_accepted:
            applied_projection = await asyncio.to_thread(
                self._apply_accepted_operation_projection,
                prepared.operation,
            )
            await self._publish_applied_projection(applied_projection)
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
        update_result = await asyncio.to_thread(
            self._update_operation_status,
            prepared.operation.operation_id,
            prepared.operation.owner_subject_id,
            target_status,
            None,
        )
        await self._publish_applied_projection(update_result.applied_projection)
        return self._to_acceptance(update_result.operation, replayed=ack.replayed)

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
            self._validate_host_command(
                host=host,
                operation_type=operation_type,
                execution=execution,
            )
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
                execution=execution,
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
        local_title_update: CodexManualTitleUpdate | None = None,
        operation_projection: CodexOperationProjection | None = None,
    ) -> PreparedCodexOperation:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            host_repository = self._control_port.create_codex_host_repository(session)
            host = host_repository.get_by_id_and_owner(host_id, actor_subject_id)
            if host is None:
                raise self._not_found()
            self._validate_host_command(
                host=host,
                operation_type=operation_type,
                execution=execution,
            )
            thread_repository = self._control_port.create_codex_thread_repository(session)
            thread = thread_repository.get_by_upstream_id_and_owner(
                host_id,
                upstream_thread_id,
                actor_subject_id,
            )
            if thread is None:
                raise self._not_found()
            if (
                operation_type == "turn.start"
                and thread.turn_runtime is not None
                and thread.turn_runtime.phase is CodexTurnPhase.STALLED
            ):
                raise HttpFaultException(
                    status_code=HTTPStatus.CONFLICT,
                    error_code=CodexErrorCode.STATE_CONFLICT,
                    message="Codex thread处于stalled状态，必须先同步或中断当前turn。",
                )
            if local_title_update is not None:
                now = datetime.now(UTC)
                thread = thread.model_copy(
                    update={
                        "display_name": local_title_update.display_name,
                        "title_source": CodexThreadTitleSource.MANUAL,
                        "updated_at": now,
                    }
                )
                thread_repository.save(thread)
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
                execution=execution,
                operation_projection=(
                    operation_projection
                    if operation_projection is None
                    or thread.title_source is CodexThreadTitleSource.NEW_CONVERSATION
                    else operation_projection.model_copy(
                        update={
                            "detail": operation_projection.detail.model_copy(
                                update={"display_name": None}
                            )
                        }
                    )
                ),
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
        operation_projection: CodexOperationProjection | None = None,
    ) -> PreparedCodexOperation:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            host = self._control_port.create_codex_host_repository(session).get_by_id_and_owner(
                host_id, actor_subject_id
            )
            if host is None:
                raise self._not_found()
            self._validate_host_command(
                host=host,
                operation_type=operation_type,
                execution=None,
            )
            thread_repository = self._control_port.create_codex_thread_repository(session)
            thread = thread_repository.get_by_upstream_id_and_owner(
                host_id,
                upstream_thread_id,
                actor_subject_id,
            )
            if thread is None:
                raise self._not_found()
            operation_repository = self._control_port.create_codex_operation_repository(session)
            existing_operation = operation_repository.get_by_actor_and_idempotency_key(
                actor_subject_id,
                idempotency_key,
            )
            target_turn_id = thread.active_turn_id
            if (
                target_turn_id is None
                and operation_type == CodexProductCommandCode.TURN_INTERRUPT.value
                and existing_operation is not None
                and thread.turn_runtime is not None
            ):
                # 中断重试可能发生在终态事件清空 active_turn_id 之后；沿用
                # 已持久化 runtime turn 身份，才能复用同一 operation/command。
                target_turn_id = thread.turn_runtime.turn_id
            if target_turn_id is None:
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
                target_turn_id
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
                execution=None,
                operation_projection=operation_projection,
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
        execution: CodexExecutionOptions | None,
        operation_projection: CodexOperationProjection | None = None,
    ) -> PreparedCodexOperation:
        repository = self._control_port.create_codex_operation_repository(session)
        request_digest = calculate_agent_request_digest(
            operation_type,
            params,
            sandbox_mode=execution.sandbox_mode.value if execution is not None else None,
            approval_policy=(execution.approval_policy.value if execution is not None else None),
        )
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
                projection=operation_projection,
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
            sandbox_mode=execution.sandbox_mode if execution is not None else None,
            approval_policy=execution.approval_policy if execution is not None else None,
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
    ) -> CodexOperationStatusUpdate:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = self._control_port.create_codex_operation_repository(session)
            operation = repository.get_by_id_and_owner(operation_id, owner_subject_id)
            if operation is None:
                raise RuntimeError("Codex operation状态更新目标不存在。")
            if operation.status in {
                CodexOperationStatus.COMPLETED.value,
                CodexOperationStatus.FAILED.value,
            }:
                return CodexOperationStatusUpdate(
                    operation=operation,
                    applied_projection=None,
                )
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
            applied_projection = (
                self._projection_service.apply_accepted(
                    session=session,
                    operation=updated,
                )
                if status is CodexOperationStatus.ACKNOWLEDGED
                else None
            )
            unit_of_work.commit()
            return CodexOperationStatusUpdate(
                operation=updated,
                applied_projection=applied_projection,
            )
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _apply_accepted_operation_projection(
        self,
        operation: CodexControlOperationSnapshot,
    ) -> CodexAppliedOperationProjection | None:
        """幂等补齐已受理操作的标题与活动时间投影。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            applied_projection = self._projection_service.apply_accepted(
                session=unit_of_work.get_session(),
                operation=operation,
            )
            unit_of_work.commit()
            return applied_projection
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    async def _publish_applied_projection(
        self,
        applied_projection: CodexAppliedOperationProjection | None,
    ) -> None:
        """仅在数据库投影提交后发布会话局部更新。"""

        if applied_projection is None:
            return
        await self._event_port.publish_thread_updated(
            applied_projection.thread,
            occurred_at=applied_projection.occurred_at,
        )

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
        *,
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
