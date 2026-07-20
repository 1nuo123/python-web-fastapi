"""
运行时访问器刷新器。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.authorization_guard import AuthorizationGuard
    from src.core.logging_contract.log_event_contract import LogEventEnvelope
    from src.domain.auth.authorization_policy_evaluator import (
        AuthorizationPolicyEvaluator,
    )
    from src.infrastructure.auth.auth_failure_throttle import AuthFailureThrottle
    from src.infrastructure.auth.jwt_token_service import JwtTokenService
    from src.infrastructure.auth.oauth2_scheme_provider import OAuth2SchemeProvider
    from src.infrastructure.auth.password_hasher import PasswordHasher
    from src.infrastructure.logging.log_event_builder import LogEventBuilder
    from src.infrastructure.logging.structured_log_handler import StructuredLogHandler
    from src.infrastructure.resource_mount.shared_resource_models import (
        AuthSupportAccessor,
        LoggingSupportAccessor,
    )


@dataclass(slots=True)
class RuntimeAccessorSnapshot:
    """
    运行时访问器快照。

    :ivar auth_accessor: 鉴权支持访问器。
    :vartype auth_accessor: AuthSupportAccessor
    :ivar logging_accessor: 日志支持访问器。
    :vartype logging_accessor: LoggingSupportAccessor
    """

    auth_accessor: AuthSupportAccessor
    logging_accessor: LoggingSupportAccessor


class RuntimeAccessorRefresher:
    """
    运行时访问器刷新器。
    """

    def refresh(
        self,
        *,
        password_hasher: PasswordHasher,
        jwt_token_service: JwtTokenService,
        auth_failure_throttle: AuthFailureThrottle | None,
        oauth2_scheme_provider: OAuth2SchemeProvider,
        authorization_policy_evaluator: AuthorizationPolicyEvaluator,
        authorization_guard: AuthorizationGuard,
        log_event_builder: LogEventBuilder,
        structured_log_handler: StructuredLogHandler | None,
        pending_log_events: list[LogEventEnvelope],
    ) -> RuntimeAccessorSnapshot:
        """
        刷新鉴权与日志访问器快照。

        :param password_hasher: 当前密码哈希器。
        :type password_hasher: PasswordHasher
        :param jwt_token_service: 当前 JWT 令牌服务。
        :type jwt_token_service: JwtTokenService
        :param auth_failure_throttle: 当前鉴权失败节流器。
        :type auth_failure_throttle: AuthFailureThrottle | None
        :param oauth2_scheme_provider: OAuth2 方案提供器。
        :type oauth2_scheme_provider: OAuth2SchemeProvider
        :param authorization_policy_evaluator: 授权策略评估器。
        :type authorization_policy_evaluator: AuthorizationPolicyEvaluator
        :param authorization_guard: 授权守卫。
        :type authorization_guard: AuthorizationGuard
        :param log_event_builder: 日志事件构造器。
        :type log_event_builder: LogEventBuilder
        :param structured_log_handler: 结构化日志处理器。
        :type structured_log_handler: StructuredLogHandler | None
        :param pending_log_events: 待写入日志事件缓冲。
        :type pending_log_events: list[LogEventEnvelope]
        :returns: 返回新的运行时访问器快照。
        :rtype: RuntimeAccessorSnapshot
        """

        from src.infrastructure.resource_mount.shared_resource_models import (
            AuthSupportAccessor,
            LoggingSupportAccessor,
        )

        return RuntimeAccessorSnapshot(
            auth_accessor=AuthSupportAccessor(
                password_hasher=password_hasher,
                jwt_token_service=jwt_token_service,
                auth_failure_throttle=auth_failure_throttle,
                oauth2_scheme_provider=oauth2_scheme_provider,
                authorization_policy_evaluator=authorization_policy_evaluator,
                authorization_guard=authorization_guard,
            ),
            logging_accessor=LoggingSupportAccessor(
                log_event_builder=log_event_builder,
                structured_log_handler=structured_log_handler,
                pending_log_events=pending_log_events,
            ),
        )
