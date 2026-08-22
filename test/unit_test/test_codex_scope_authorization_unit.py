"""Codex 审批能力到 scope 的映射单元测试。"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.core.codex_contract.approval_contract import (
    CodexApprovalAuditSnapshot,
    CodexApprovalDecision,
    CodexApprovalDisplaySummary,
    CodexApprovalKind,
    CodexApprovalRiskLevel,
    CodexApprovalState,
)
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.domain.codex.codex_authorization_policy import (
    build_codex_approval_decision_authorization_requirement,
)


class TestCodexScopeAuthorizationUnit:
    """冻结接受与拒绝审批时的额外 scope 要求。"""

    def test_accept_network_command_with_extra_root_should_require_all_capability_scopes(
        self,
    ) -> None:
        approval = self._build_approval(
            approval_kind=CodexApprovalKind.COMMAND,
            network_requested=True,
            file_scope=("docs",),
            extra_root_requested=True,
        )

        requirement = build_codex_approval_decision_authorization_requirement(
            approval,
            CodexApprovalDecision.ACCEPT,
        )

        assert set(requirement.required_scopes) == {
            AuthScopeCode.CODEX_FILES.value,
            AuthScopeCode.CODEX_TERMINAL.value,
            AuthScopeCode.CODEX_NETWORK.value,
            AuthScopeCode.CODEX_FULL_ACCESS.value,
        }

    def test_decline_high_risk_request_should_not_require_requested_capability_scopes(
        self,
    ) -> None:
        approval = self._build_approval(
            approval_kind=CodexApprovalKind.PERMISSIONS,
            network_requested=True,
            file_scope=("docs",),
            extra_root_requested=True,
        )

        requirement = build_codex_approval_decision_authorization_requirement(
            approval,
            CodexApprovalDecision.DECLINE,
        )

        assert requirement.required_scopes == []

    @pytest.mark.parametrize(
        "decision",
        (
            CodexApprovalDecision.ACCEPT_FOR_SESSION,
            CodexApprovalDecision.ACCEPT_WITH_EXECPOLICY_AMENDMENT,
            CodexApprovalDecision.APPLY_NETWORK_POLICY_AMENDMENT,
        ),
    )
    def test_official_grant_variants_should_require_the_same_capability_scopes(
        self,
        decision: CodexApprovalDecision,
    ) -> None:
        """会话和策略类 grant 不能绕开命令、网络或文件 scope。"""

        approval = self._build_approval(
            approval_kind=CodexApprovalKind.COMMAND,
            network_requested=True,
            file_scope=("docs",),
            extra_root_requested=True,
        )

        requirement = build_codex_approval_decision_authorization_requirement(
            approval,
            decision,
        )

        assert set(requirement.required_scopes) == {
            AuthScopeCode.CODEX_FILES.value,
            AuthScopeCode.CODEX_TERMINAL.value,
            AuthScopeCode.CODEX_NETWORK.value,
            AuthScopeCode.CODEX_FULL_ACCESS.value,
        }

    def _build_approval(
        self,
        *,
        approval_kind: CodexApprovalKind,
        network_requested: bool,
        file_scope: tuple[str, ...],
        extra_root_requested: bool,
    ) -> CodexApprovalAuditSnapshot:
        now = datetime.now(UTC)
        return CodexApprovalAuditSnapshot(
            approval_id=uuid4(),
            owner_subject_id="subject",
            host_id=uuid4(),
            workspace_id=uuid4(),
            thread_id="thread-1",
            turn_id="turn-1",
            item_id="item-1",
            approval_kind=approval_kind,
            risk_level=CodexApprovalRiskLevel.HIGH,
            payload_digest="a" * 64,
            display_summary=CodexApprovalDisplaySummary(
                title="审批",
                reason="测试能力映射",
                risk_level=CodexApprovalRiskLevel.HIGH,
                file_scope=file_scope,
                network_requested=network_requested,
                extra_root_requested=extra_root_requested,
            ),
            state=CodexApprovalState.PENDING,
            version=1,
            expires_at=now + timedelta(minutes=5),
            created_at=now,
            updated_at=now,
        )
