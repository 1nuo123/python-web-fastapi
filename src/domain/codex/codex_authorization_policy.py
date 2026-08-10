"""Codex 用户路由授权要求。"""

from src.core.auth_contract.authorization_policy_contract import RouteAuthorizationRequirement
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
