"""Codex 设备安全操作的统一限流入口。"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import Request

from src.core.codex_contract.codex_runtime_contract import (
    CodexRuntimeSettings,
    CodexSecurityRateLimitOperation,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.security_contract.rate_limit_policy_contract import RateLimitKeyDimension
from src.core.security_contract.security_decision_contract import SecurityAction
from src.domain.codex.codex_error_code import CodexErrorCode


class CodexSecurityRateLimitEnforcer:
    """复用全局安全防护门面执行 fail-closed 设备操作限流。"""

    def enforce(
        self,
        *,
        request: Request,
        settings: CodexRuntimeSettings,
        operation: CodexSecurityRateLimitOperation,
        auth_field_values: list[str] | None = None,
        include_subject: bool = False,
    ) -> None:
        """按 IP、请求路径、主体和业务标识摘要组合限流。"""

        dimensions = [
            RateLimitKeyDimension.IP_DIGEST,
            RateLimitKeyDimension.PATH_METHOD,
        ]
        if auth_field_values:
            dimensions.append(RateLimitKeyDimension.AUTH_FIELD_DIGEST)
        if include_subject:
            dimensions.append(RateLimitKeyDimension.SUBJECT_ID)
        guard = request.app.state.container.resource_mount.get_security_protection_guard()
        decision = guard.evaluate_request(
            request=request,
            limit=settings.device_security_rate_limit,
            window_seconds=settings.device_security_rate_window_seconds,
            block_seconds=settings.device_security_block_seconds,
            ip_block_cache_ttl_seconds=settings.device_security_ip_block_ttl_seconds,
            policy_name=operation.value,
            key_dimensions=dimensions,
            auth_field_values=auth_field_values,
        )
        if decision.action == SecurityAction.RETURN_429:
            raise HttpFaultException(
                status_code=HTTPStatus.TOO_MANY_REQUESTS,
                error_code=CodexErrorCode.SECURITY_RATE_LIMITED,
                message="Codex设备安全操作请求过于频繁。",
                detail=decision.reason_code,
            )
