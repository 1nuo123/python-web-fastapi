"""Codex 审批可见动作与 step-up 边界测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from typing import cast
from unittest.mock import Mock
from uuid import uuid4

import pytest

from src.application.codex.manage_approval_usecase import ManageCodexApprovalUsecase
from src.application.ports.codex_agent_command_dispatch_port import (
    CodexAgentCommandDispatchPort,
)
from src.application.ports.codex_command_payload_cipher_port import (
    CodexCommandPayloadCipherPort,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.application.ports.codex_realtime_event_port import CodexRealtimeEventPort
from src.application.ports.step_up_grant_port import StepUpGrantPort
from src.core.codex_contract.approval_contract import (
    CodexApprovalAuditSnapshot,
    CodexApprovalDecision,
    CodexApprovalDisplaySummary,
    CodexApprovalKind,
    CodexApprovalRiskLevel,
    CodexApprovalState,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode

BASE_TIME = datetime(2026, 8, 19, 3, 0, tzinfo=UTC)
HOST_ID = uuid4()
WORKSPACE_ID = uuid4()
APPROVAL_ID = uuid4()
OWNER_SUBJECT_ID = "approval-owner"


def _approval(
    *,
    risk_level: CodexApprovalRiskLevel = CodexApprovalRiskLevel.NORMAL,
    allowed_actions: tuple[CodexApprovalDecision, ...],
) -> CodexApprovalAuditSnapshot:
    """构造只含脱敏 proposal 能力标志的待处理审批。"""

    return CodexApprovalAuditSnapshot(
        approval_id=APPROVAL_ID,
        owner_subject_id=OWNER_SUBJECT_ID,
        host_id=HOST_ID,
        workspace_id=WORKSPACE_ID,
        thread_id="thread-1",
        turn_id="turn-1",
        item_id="item-1",
        approval_kind=CodexApprovalKind.COMMAND,
        risk_level=risk_level,
        payload_digest="a" * 64,
        display_summary=CodexApprovalDisplaySummary(
            title="命令审批",
            reason="测试官方动作约束",
            risk_level=risk_level,
            allowed_actions=allowed_actions,
        ),
        state=CodexApprovalState.PENDING,
        version=1,
        expires_at=BASE_TIME + timedelta(minutes=5),
        created_at=BASE_TIME,
        updated_at=BASE_TIME,
    )


def _usecase(approval: CodexApprovalAuditSnapshot) -> ManageCodexApprovalUsecase:
    """构造不连接数据库的准备阶段依赖。"""

    control_port = Mock()
    unit_of_work = Mock()
    approval_repository = Mock()
    operation_repository = Mock()
    unit_of_work.get_session.return_value = object()
    control_port.create_unit_of_work.return_value = unit_of_work
    control_port.create_codex_approval_repository.return_value = approval_repository
    control_port.create_codex_operation_repository.return_value = operation_repository
    operation_repository.get_by_actor_and_idempotency_key.return_value = None
    approval_repository.get_by_id_and_owner.return_value = approval
    return ManageCodexApprovalUsecase(
        control_port=cast(CodexControlPort, control_port),
        dispatch_port=cast(CodexAgentCommandDispatchPort, Mock()),
        payload_cipher=cast(CodexCommandPayloadCipherPort, Mock()),
        ack_timeout_seconds=10,
        outbox_ttl_seconds=60,
        event_port=cast(CodexRealtimeEventPort, Mock()),
        step_up_port=cast(StepUpGrantPort, Mock()),
    )


def test_hidden_amendment_action_is_rejected_before_agent_delivery() -> None:
    """API 不能接受 Agent 未对该请求公布的 amendment 动作。"""

    usecase = _usecase(
        _approval(
            allowed_actions=(
                CodexApprovalDecision.ACCEPT,
                CodexApprovalDecision.ACCEPT_FOR_SESSION,
                CodexApprovalDecision.DECLINE,
                CodexApprovalDecision.CANCEL,
            )
        )
    )

    with pytest.raises(HttpFaultException) as captured:
        usecase._prepare(
            approval_id=APPROVAL_ID,
            approval_version=1,
            decision=CodexApprovalDecision.ACCEPT_WITH_EXECPOLICY_AMENDMENT.value,
            actor_subject_id=OWNER_SUBJECT_ID,
            idempotency_key="hidden-amendment",
            step_up_verified=False,
        )

    assert captured.value.status_code == 409


@pytest.mark.parametrize(
    "decision",
    (
        CodexApprovalDecision.ACCEPT,
        CodexApprovalDecision.ACCEPT_FOR_SESSION,
        CodexApprovalDecision.ACCEPT_WITH_EXECPOLICY_AMENDMENT,
        CodexApprovalDecision.APPLY_NETWORK_POLICY_AMENDMENT,
    ),
)
def test_all_high_risk_grants_require_step_up_before_claiming(
    decision: CodexApprovalDecision,
) -> None:
    """所有官方 grant 变体都不能绕过高风险增强认证。"""

    usecase = _usecase(
        _approval(
            risk_level=CodexApprovalRiskLevel.HIGH,
            allowed_actions=(decision,),
        )
    )

    with pytest.raises(HttpFaultException) as captured:
        usecase._prepare(
            approval_id=APPROVAL_ID,
            approval_version=1,
            decision=decision.value,
            actor_subject_id=OWNER_SUBJECT_ID,
            idempotency_key="high-risk-session",
            step_up_verified=False,
        )

    assert captured.value.status_code == 403


def test_unadvertised_approval_action_is_rejected_when_agent_omits_allowed_actions() -> None:
    """缺少 Agent 允许动作的历史审批必须 fail closed。"""

    usecase = _usecase(_approval(allowed_actions=()))

    with pytest.raises(HttpFaultException) as captured:
        usecase._prepare(
            approval_id=APPROVAL_ID,
            approval_version=1,
            decision=CodexApprovalDecision.ACCEPT.value,
            actor_subject_id=OWNER_SUBJECT_ID,
            idempotency_key="missing-allowed-actions",
            step_up_verified=False,
        )

    assert captured.value.status_code == HTTPStatus.CONFLICT
    assert captured.value.error_code is CodexErrorCode.STATE_CONFLICT


def test_approval_version_conflict_does_not_create_operation_or_outbox() -> None:
    """审批 claim 的版本冲突必须在 Agent 投递前终止。"""

    usecase = _usecase(_approval(allowed_actions=(CodexApprovalDecision.ACCEPT,)))
    control_port = cast(Mock, usecase._control_port)
    approval_repository = control_port.create_codex_approval_repository.return_value
    operation_repository = control_port.create_codex_operation_repository.return_value
    approval_repository.claim_decision.return_value = None

    with pytest.raises(HttpFaultException) as captured:
        usecase._prepare(
            approval_id=APPROVAL_ID,
            approval_version=2,
            decision=CodexApprovalDecision.ACCEPT.value,
            actor_subject_id=OWNER_SUBJECT_ID,
            idempotency_key="approval-version-conflict",
            step_up_verified=False,
        )

    assert captured.value.status_code == HTTPStatus.GONE
    assert captured.value.error_code is CodexErrorCode.APPROVAL_GONE
    operation_repository.add.assert_not_called()
    control_port.create_codex_command_outbox_repository.assert_not_called()
