"""
FastAPI中间件计划基础设施模块。
"""

from __future__ import annotations

import logging

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware import Middleware

from src.infrastructure.middleware_chain.access_log_middleware import AccessLogMiddleware
from src.infrastructure.middleware_chain.authentication_binding_middleware import (
    AuthenticationBindingMiddleware,
)
from src.infrastructure.middleware_chain.elapsed_probe_middleware import ElapsedProbeMiddleware
from src.infrastructure.middleware_chain.payload_guard_middleware import PayloadGuardMiddleware
from src.infrastructure.middleware_chain.rate_limit_middleware import RateLimitMiddleware
from src.infrastructure.middleware_chain.request_scope_middleware import RequestScopeMiddleware
from src.infrastructure.middleware_chain.security_header_middleware import SecurityHeaderMiddleware
from src.infrastructure.shared_resource_mount import SharedResourceMount


class FastApiMiddlewarePlan:
    """
    FastAPI中间件计划类型，用于封装当前模块中的相关行为或状态。
    """

    def build_bindings(
        self,
        *,
        resource_mount: SharedResourceMount,
        logger: logging.Logger,
    ) -> list[Middleware]:
        """
        构建绑定集合。

        :param resource_mount: 共享资源挂载点，用于访问数据库、缓存、消息和鉴权能力。约束：需符合 ``SharedResourceMount`` 注解。
        :type resource_mount: SharedResourceMount
        :param logger: 当前组件使用的日志记录器。约束：需符合 ``logging.Logger`` 注解。
        :type logger: logging.Logger
        :returns: 返回按实现构造的列表结果。
        :rtype: list[MiddlewareBinding]
        """

        runtime_settings = resource_mount.read_runtime_bundle().settings
        cors_settings = runtime_settings.runtime.web.cors
        bindings = [
            Middleware(
                RequestScopeMiddleware,
                request_context_manager=resource_mount.get_request_context_manager(),
                telemetry_bridge=resource_mount.get_telemetry_bridge(),
            ),
            Middleware(
                PayloadGuardMiddleware,
                resource_mount=resource_mount,
            ),
            Middleware(
                AuthenticationBindingMiddleware,
                oauth2_scheme_provider=resource_mount.get_oauth2_scheme_provider(),
                resource_mount=resource_mount,
                logger=logger,
            ),
            Middleware(
                RateLimitMiddleware,
                resource_mount=resource_mount,
            ),
            Middleware(
                SecurityHeaderMiddleware,
                resource_mount=resource_mount,
            ),
        ]
        if runtime_settings.runtime.web.enable_access_log:
            bindings.append(
                Middleware(
                    AccessLogMiddleware,
                    resource_mount=resource_mount,
                    logger=logger,
                )
            )
        bindings.append(Middleware(ElapsedProbeMiddleware))
        if cors_settings.enabled:
            bindings.insert(
                0,
                Middleware(
                    CORSMiddleware,
                    allow_origins=cors_settings.allow_origins,
                    allow_methods=cors_settings.allow_methods,
                    allow_headers=cors_settings.allow_headers,
                    allow_credentials=cors_settings.allow_credentials,
                ),
            )
        return bindings
