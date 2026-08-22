"""Codex 用户路由授权要求。"""

from src.core.auth_contract.authorization_policy_contract import RouteAuthorizationRequirement
from src.core.codex_contract.approval_contract import (
    CodexApprovalAuditSnapshot,
    CodexApprovalDecision,
    CodexApprovalKind,
)
from src.domain.auth.auth_scope_code import AuthScopeCode

CODEX_READ_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name="codex_read",
    required_scopes=[AuthScopeCode.CODEX_READ.value],
)

CODEX_OPERATE_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name="codex_operate",
    required_scopes=[AuthScopeCode.CODEX_OPERATE.value],
)

CODEX_APPROVE_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name="codex_approve",
    required_scopes=[AuthScopeCode.CODEX_APPROVE.value],
)

CODEX_HOST_MANAGE_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name="codex_host_manage",
    required_scopes=[AuthScopeCode.CODEX_HOST_MANAGE.value],
)

CODEX_TOOL_EXECUTION_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name="codex_tool_execution",
    required_scopes=[
        AuthScopeCode.CODEX_FILES.value,
        AuthScopeCode.CODEX_TERMINAL.value,
    ],
)

CODEX_FULL_ACCESS_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name="codex_full_access",
    required_scopes=[AuthScopeCode.CODEX_FULL_ACCESS.value],
)


def build_codex_approval_decision_authorization_requirement(
    approval: CodexApprovalAuditSnapshot,
    decision: CodexApprovalDecision,
) -> RouteAuthorizationRequirement:
    """根据接受的具体能力请求构造额外 scope 要求。"""

    required_scopes: set[str] = set()
    if decision in {
        CodexApprovalDecision.ACCEPT,
        CodexApprovalDecision.ACCEPT_FOR_SESSION,
        CodexApprovalDecision.ACCEPT_WITH_EXECPOLICY_AMENDMENT,
        CodexApprovalDecision.APPLY_NETWORK_POLICY_AMENDMENT,
    }:
        if (
            approval.approval_kind is CodexApprovalKind.FILE_CHANGE
            or approval.display_summary.file_scope
            or approval.display_summary.file_changes
            or approval.display_summary.extra_root_requested
        ):
            required_scopes.add(AuthScopeCode.CODEX_FILES.value)
        if approval.approval_kind is CodexApprovalKind.COMMAND:
            required_scopes.add(AuthScopeCode.CODEX_TERMINAL.value)
        if approval.display_summary.network_requested:
            required_scopes.add(AuthScopeCode.CODEX_NETWORK.value)
        if approval.display_summary.extra_root_requested:
            required_scopes.add(AuthScopeCode.CODEX_FULL_ACCESS.value)
    return RouteAuthorizationRequirement(
        requirement_name="codex_approval_decision_capabilities",
        required_scopes=sorted(required_scopes),
    )
