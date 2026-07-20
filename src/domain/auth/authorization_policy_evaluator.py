"""
授权策略评估器领域服务。
"""

from __future__ import annotations

from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.auth_contract.authorization_policy_contract import (
    AuthorizationDecision,
    AuthorizationPolicy,
)


class AuthorizationPolicyEvaluator:
    """
    授权策略评估器，负责评估规则或策略。
    """

    def evaluate(
        self,
        principal: AuthenticatedPrincipal,
        policy: AuthorizationPolicy,
    ) -> AuthorizationDecision:
        """
        处理评估。

        :param principal: 认证主体对象。约束：需符合 ``AuthenticatedPrincipal`` 注解。
        :type principal: AuthenticatedPrincipal
        :param policy: 授权策略对象。约束：需符合 ``AuthorizationPolicy`` 注解。
        :type policy: AuthorizationPolicy
        :returns: 返回当前操作结果。
        :rtype: AuthorizationDecision
        """

        missing_scopes = [
            scope for scope in policy.required_scopes if scope not in principal.scopes
        ]
        if missing_scopes:
            return AuthorizationDecision(
                allowed=False,
                reason=f"缺少权限范围：{','.join(missing_scopes)}。",
            )
        missing_roles = [role for role in policy.required_roles if role not in principal.roles]
        if missing_roles:
            return AuthorizationDecision(
                allowed=False,
                reason=f"缺少角色：{','.join(missing_roles)}。",
            )
        return AuthorizationDecision(allowed=True)
