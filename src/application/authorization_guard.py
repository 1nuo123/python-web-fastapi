"""
授权守卫应用服务。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.auth_contract.authorization_policy_contract import (
    AuthorizationPolicy,
    RouteAuthorizationRequirement,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.auth.auth_error_code import AuthErrorCode
from src.domain.auth.authorization_policy_evaluator import (
    AuthorizationPolicyEvaluator,
)


class AuthorizationPolicyRuntimePort(Protocol):
    """
    授权策略协议，定义当前场景所需的最小依赖能力。
    """

    def get_authorization_policy_evaluator(self) -> AuthorizationPolicyEvaluator:
        """
        获取授权策略评估器。

        :returns: 返回读取到的对象或状态快照。
        :rtype: AuthorizationPolicyEvaluator
        """

        pass


class AuthorizationGuard:
    """
    授权守卫，负责执行应用访问策略校验。
    """

    def __init__(self, *, runtime_port: AuthorizationPolicyRuntimePort) -> None:
        """
        初始化授权守卫。

        :param runtime_port: 运行时端口实现，用于向用例提供最小依赖能力。约束：需符合 ``AuthorizationPolicyRuntimePort`` 注解。
        :type runtime_port: AuthorizationPolicyRuntimePort
        :returns: 无返回值。
        :rtype: None
        """

        self._runtime_port = runtime_port

    def assert_requirement(
        self,
        *,
        principal: AuthenticatedPrincipal,
        requirement: RouteAuthorizationRequirement,
    ) -> None:
        """
        断言要求。

        :param principal: 认证主体对象。约束：需符合 ``AuthenticatedPrincipal`` 注解。
        :type principal: AuthenticatedPrincipal
        :param requirement: 当前步骤使用的要求参数。约束：需符合 ``RouteAuthorizationRequirement`` 注解。
        :type requirement: RouteAuthorizationRequirement
        :returns: 无返回值。
        :rtype: None
        """

        self.assert_policy(
            principal=principal,
            policy=requirement.to_policy(),
        )

    def assert_policy(
        self,
        *,
        principal: AuthenticatedPrincipal,
        policy: AuthorizationPolicy,
    ) -> None:
        """
        断言策略。

        :param principal: 认证主体对象。约束：需符合 ``AuthenticatedPrincipal`` 注解。
        :type principal: AuthenticatedPrincipal
        :param policy: 授权策略对象。约束：需符合 ``AuthorizationPolicy`` 注解。
        :type policy: AuthorizationPolicy
        :returns: 无返回值。
        :rtype: None
        :raises HttpFaultException: 当业务校验失败、资源未就绪、配置错误或令牌状态异常时抛出。
        """

        decision = self._runtime_port.get_authorization_policy_evaluator().evaluate(
            principal,
            policy,
        )
        if decision.allowed:
            return
        raise HttpFaultException(
            status_code=HTTPStatus.FORBIDDEN,
            error_code=AuthErrorCode.PERMISSION_DENIED,
            message=decision.reason or "当前主体无权访问。",
        )
