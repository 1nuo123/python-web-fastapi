"""Codex thread command usecase 的终态重试边界测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from pydantic import JsonValue

from src.application.codex.execute_thread_command_usecase import (
    ExecuteCodexThreadCommandUsecase,
    PreparedCodexOperation,
)
from src.application.ports.codex_agent_command_dispatch_port import (
    CodexAgentCommandDispatchPort,
)
from src.application.ports.codex_command_payload_cipher_port import (
    CodexCommandPayloadCipherPort,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.application.ports.codex_realtime_event_port import CodexRealtimeEventPort
from src.core.codex_contract.operation_contract import CodexControlOperationSnapshot
from src.core.codex_contract.thread_contract import (
    CodexThreadIndexSnapshot,
    CodexThreadStatus,
    CodexThreadTitleSource,
)
from src.core.codex_contract.turn_contract import CodexExecutionOptions
from src.core.codex_contract.turn_runtime_contract import CodexTurnPhase, CodexTurnRuntime
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.domain.codex.codex_error_code import CodexErrorCode
from src.domain.codex.host_status import CodexOperationStatus

BASE_TIME = datetime(2026, 8, 19, 2, 15, tzinfo=UTC)
HOST_ID = uuid4()
WORKSPACE_ID = uuid4()
THREAD_ID = "thread-terminal-retry"
TURN_ID = "turn-terminal-retry"
OWNER_SUBJECT_ID = "owner-terminal-retry"


def _terminal_thread() -> CodexThreadIndexSnapshot:
    """构造已收到终态事件、但仍保留 runtime turn 身份的线程。"""

    return CodexThreadIndexSnapshot(
        thread_index_id=uuid4(),
        host_id=HOST_ID,
        workspace_id=WORKSPACE_ID,
        owner_subject_id=OWNER_SUBJECT_ID,
        upstream_thread_id=THREAD_ID,
        display_name="终态重试线程",
        title_source=CodexThreadTitleSource.NEW_CONVERSATION,
        model=None,
        model_provider=None,
        reasoning_effort=None,
        status=CodexThreadStatus.IDLE,
        active_turn_id=None,
        turn_runtime=CodexTurnRuntime(
            turn_id=TURN_ID,
            thread_id=THREAD_ID,
            phase=CodexTurnPhase.INTERRUPTED,
            last_activity_at=BASE_TIME,
            stalled_reason=None,
            lease_generation=3,
            lease_expires_at=None,
        ),
        archived=False,
        is_pinned=False,
        source_kind="app_server",
        created_at=BASE_TIME,
        recency_at=BASE_TIME,
        updated_at=BASE_TIME,
        last_synced_at=BASE_TIME,
    )


def _stalled_thread() -> CodexThreadIndexSnapshot:
    """构造必须先同步或中断的停滞线程。"""

    terminal_thread = _terminal_thread()
    runtime = terminal_thread.turn_runtime
    assert runtime is not None
    return terminal_thread.model_copy(
        update={
            "status": CodexThreadStatus.ACTIVE,
            "active_turn_id": TURN_ID,
            "turn_runtime": runtime.model_copy(
                update={
                    "phase": CodexTurnPhase.STALLED,
                    "stalled_reason": "lease_expired_no_activity",
                }
            ),
        }
    )


def _usecase(
    control_port: Mock,
) -> ExecuteCodexThreadCommandUsecase:
    """创建只调用准备阶段的 usecase。"""

    return ExecuteCodexThreadCommandUsecase(
        control_port=cast(CodexControlPort, control_port),
        dispatch_port=cast(CodexAgentCommandDispatchPort, Mock()),
        payload_cipher=cast(CodexCommandPayloadCipherPort, Mock()),
        event_port=cast(CodexRealtimeEventPort, Mock()),
        ack_timeout_seconds=10,
        outbox_ttl_seconds=60,
    )


def _prepare_control_port(thread: CodexThreadIndexSnapshot, existing: object | None) -> Mock:
    """为准备阶段提供不连接真实数据库的仓储替身。"""

    control_port = Mock()
    unit_of_work = Mock()
    session = object()
    host_repository = Mock()
    thread_repository = Mock()
    operation_repository = Mock()
    workspace_repository = Mock()
    unit_of_work.get_session.return_value = session
    control_port.create_unit_of_work.return_value = unit_of_work
    control_port.create_codex_host_repository.return_value = host_repository
    control_port.create_codex_thread_repository.return_value = thread_repository
    control_port.create_codex_operation_repository.return_value = operation_repository
    control_port.create_codex_workspace_repository.return_value = workspace_repository
    host_repository.get_by_id_and_owner.return_value = object()
    thread_repository.get_by_upstream_id_and_owner.return_value = thread
    operation_repository.get_by_actor_and_idempotency_key.return_value = existing
    workspace_repository.get_by_id_and_owner.return_value = SimpleNamespace(
        enabled=True,
        agent_workspace_key="terminal-retry-workspace",
    )
    return control_port


def _existing_turn_operation(
    *,
    idempotency_key: str,
    request_digest: str,
) -> CodexControlOperationSnapshot:
    """构造已确认的幂等 operation，隔离测试不需要数据库序列化细节。"""

    return CodexControlOperationSnapshot.model_construct(
        operation_id=uuid4(),
        command_id=uuid4(),
        actor_subject_id=OWNER_SUBJECT_ID,
        owner_subject_id=OWNER_SUBJECT_ID,
        host_id=HOST_ID,
        workspace_id=WORKSPACE_ID,
        thread_id=THREAD_ID,
        operation_type="turn.start",
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        status=CodexOperationStatus.ACKNOWLEDGED.value,
        dispatch_attempt=1,
        last_dispatched_at=BASE_TIME,
        ack_deadline_at=BASE_TIME,
        error_code=None,
        projection=None,
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
    )


def _turn_start_params(message: str) -> dict[str, JsonValue]:
    """构造与公开 start_turn 路径一致的受控命令参数。"""

    return {
        "threadId": THREAD_ID,
        "workspace_key": "terminal-retry-workspace",
        "clientUserMessageId": "11111111-1111-4111-8111-111111111111",
        "input": [{"type": "text", "text": message, "text_elements": []}],
    }


def test_interrupt_retry_after_terminal_event_reuses_runtime_turn_id() -> None:
    """终态后重试同一 key 必须继续使用原 turn，而不是创建新目标。"""

    control_port = _prepare_control_port(_terminal_thread(), object())
    usecase = _usecase(control_port)
    prepared = cast(PreparedCodexOperation, object())
    with (
        patch.object(usecase, "_validate_host_command"),
        patch.object(
            usecase,
            "_build_or_reuse_operation",
            return_value=prepared,
        ) as build_operation,
    ):
        result = usecase._prepare_active_turn_operation(
            host_id=HOST_ID,
            upstream_thread_id=THREAD_ID,
            actor_subject_id=OWNER_SUBJECT_ID,
            idempotency_key="interrupt-terminal-retry",
            operation_type="turn.interrupt",
            params={"threadId": THREAD_ID},
        )

    assert result is prepared
    assert build_operation.call_args.kwargs["params"]["turnId"] == TURN_ID
    control_port.create_unit_of_work.return_value.commit.assert_called_once()


def test_interrupt_without_active_turn_and_without_existing_operation_is_rejected() -> None:
    """没有活动 turn 且不是已知重试时，不能伪造中断命令。"""

    control_port = _prepare_control_port(_terminal_thread(), None)
    usecase = _usecase(control_port)

    with patch.object(usecase, "_validate_host_command"):
        with pytest.raises(HttpFaultException):
            usecase._prepare_active_turn_operation(
                host_id=HOST_ID,
                upstream_thread_id=THREAD_ID,
                actor_subject_id=OWNER_SUBJECT_ID,
                idempotency_key="new-interrupt-after-terminal",
                operation_type="turn.interrupt",
                params={"threadId": THREAD_ID},
            )


def test_start_turn_when_runtime_is_stalled_is_rejected_before_operation_creation() -> None:
    """停滞 turn 未同步或中断前不得被新 turn 覆盖。"""

    control_port = _prepare_control_port(_stalled_thread(), None)
    usecase = _usecase(control_port)

    with patch.object(usecase, "_validate_host_command"):
        with pytest.raises(HttpFaultException) as exc_info:
            usecase._prepare_thread_operation(
                host_id=HOST_ID,
                upstream_thread_id=THREAD_ID,
                actor_subject_id=OWNER_SUBJECT_ID,
                idempotency_key="start-after-stalled",
                operation_type="turn.start",
                params={"threadId": THREAD_ID},
            )

    assert exc_info.value.status_code == HTTPStatus.CONFLICT
    assert exc_info.value.error_code is CodexErrorCode.STATE_CONFLICT
    control_port.create_codex_operation_repository.return_value.get_by_actor_and_idempotency_key.assert_not_called()
    control_port.create_unit_of_work.return_value.rollback.assert_called_once()
    control_port.create_unit_of_work.return_value.commit.assert_not_called()


def test_send_same_operation_retry_returns_original_result() -> None:
    """相同 key 与相同负载必须复用已确认 operation，不能创建第二条命令。"""

    idempotency_key = "11111111-1111-4111-8111-111111111111"
    params = _turn_start_params("保持原请求")
    execution = CodexExecutionOptions()
    request_digest = calculate_agent_request_digest(
        "turn.start",
        params,
        sandbox_mode=execution.sandbox_mode.value,
        approval_policy=execution.approval_policy.value,
    )
    existing = _existing_turn_operation(
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    control_port = _prepare_control_port(_terminal_thread(), existing)
    usecase = _usecase(control_port)
    control_port.create_codex_command_outbox_repository.return_value.get_by_command_id.return_value = object()

    prepared = usecase._build_or_reuse_operation(
        unit_of_work=control_port.create_unit_of_work.return_value,
        session=cast(PersistenceSession, object()),
        host_id=HOST_ID,
        workspace_id=WORKSPACE_ID,
        thread_id=THREAD_ID,
        actor_subject_id=OWNER_SUBJECT_ID,
        idempotency_key=idempotency_key,
        operation_type="turn.start",
        params=params,
        execution=execution,
    )

    assert prepared.already_accepted is True
    assert prepared.operation.operation_id == existing.operation_id
    assert prepared.command.command_id == existing.command_id
    control_port.create_codex_operation_repository.return_value.add.assert_not_called()
    control_port.create_codex_operation_repository.return_value.save.assert_not_called()


def test_send_same_operation_different_payload_returns_conflict() -> None:
    """相同 key 改变正文后必须在投递前返回明确的幂等冲突。"""

    idempotency_key = "11111111-1111-4111-8111-111111111111"
    original_params = _turn_start_params("原请求")
    execution = CodexExecutionOptions()
    existing = _existing_turn_operation(
        idempotency_key=idempotency_key,
        request_digest=calculate_agent_request_digest(
            "turn.start",
            original_params,
            sandbox_mode=execution.sandbox_mode.value,
            approval_policy=execution.approval_policy.value,
        ),
    )
    control_port = _prepare_control_port(_terminal_thread(), existing)
    usecase = _usecase(control_port)

    with pytest.raises(HttpFaultException) as exc_info:
        usecase._build_or_reuse_operation(
            unit_of_work=control_port.create_unit_of_work.return_value,
            session=cast(PersistenceSession, object()),
            host_id=HOST_ID,
            workspace_id=WORKSPACE_ID,
            thread_id=THREAD_ID,
            actor_subject_id=OWNER_SUBJECT_ID,
            idempotency_key=idempotency_key,
            operation_type="turn.start",
            params=_turn_start_params("已被修改的请求"),
            execution=execution,
        )

    assert exc_info.value.status_code == HTTPStatus.CONFLICT
    assert exc_info.value.error_code is CodexErrorCode.IDEMPOTENCY_CONFLICT
    control_port.create_codex_operation_repository.return_value.add.assert_not_called()
