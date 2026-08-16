"""Codex 管理控制面路由授权要求。"""

from src.core.auth_contract.authorization_policy_contract import RouteAuthorizationRequirement
from src.domain.auth.auth_scope_code import AuthScopeCode

CODEX_ADMIN_MANAGE_AUTHORIZATION_REQUIREMENT = RouteAuthorizationRequirement(
    requirement_name="codex_admin_manage",
    required_scopes=[AuthScopeCode.CODEX_ADMIN_MANAGE.value],
)
