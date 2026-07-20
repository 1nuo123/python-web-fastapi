"""
统一安全防护门面模块。
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import Request

from src.core.http_contract.security_runtime_contract import RateLimitFailMode
from src.core.security_contract.rate_limit_policy_contract import RateLimitKeyDimension
from src.core.security_contract.security_decision_contract import (
    SecurityAction,
    SecurityDecisionEnvelope,
)
from src.core.security_contract.security_event_contract import SecurityEventType
from src.core.security_contract.security_ip_block_contract import SecurityIpBlockReason
from src.infrastructure.security.client_ip_resolver import ClientIpResolver
from src.infrastructure.security.ip_block_guard import IpBlockGuard
from src.infrastructure.security.rate_limit_guard import RateLimitGuard
from src.infrastructure.security.risk_signal_guard import RiskSignalGuard
from src.infrastructure.security.security_event_builder import SecurityEventBuilder

SECURITY_DECISION_POLICY_DEFAULT = "security_protection_default"
SECURITY_DECISION_ALLOW_REASON = "security.allowed"
SECURITY_DECISION_IP_BLOCKED_REASON = "security.ip_blocked"
SECURITY_DECISION_RATE_LIMIT_REASON = "security.rate_limited"


class SecurityProtectionGuard:
    """
    安全防护门面。
    """

    def __init__(
        self,
        *,
        ip_block_guard: IpBlockGuard,
        rate_limit_guard: RateLimitGuard,
        risk_signal_guard: RiskSignalGuard | None = None,
        client_ip_resolver: ClientIpResolver | None = None,
        security_event_builder: SecurityEventBuilder | None = None,
    ) -> None:
        """
        初始化安全防护门面。
        """

        self._ip_block_guard = ip_block_guard
        self._rate_limit_guard = rate_limit_guard
        self._risk_signal_guard = risk_signal_guard
        self._client_ip_resolver = client_ip_resolver or ClientIpResolver()
        self._security_event_builder = security_event_builder or SecurityEventBuilder()

    def evaluate_request(
        self,
        *,
        request: Request,
        limit: int,
        window_seconds: int,
        block_seconds: int,
        ip_block_cache_ttl_seconds: int,
        flow_control_enabled: bool = True,
        ip_block_enabled: bool = True,
        policy_name: str = SECURITY_DECISION_POLICY_DEFAULT,
        key_dimensions: list[RateLimitKeyDimension] | None = None,
        auth_field_values: list[str] | None = None,
        block_when_exceeded: bool = True,
        rate_limit_fail_mode: RateLimitFailMode = RateLimitFailMode.FAIL_CLOSED,
    ) -> SecurityDecisionEnvelope:
        """
        评估请求安全决策。
        """

        if self._risk_signal_guard is not None:
            self._risk_signal_guard.record_request_observation(
                path=request.url.path,
                ip=self._client_ip_resolver.resolve_client_ip(request),
                window_seconds=window_seconds,
            )
        if ip_block_enabled:
            block_result = self._ip_block_guard.evaluate(
                request,
                cache_ttl_seconds=ip_block_cache_ttl_seconds,
            )
            if block_result.blocked:
                return SecurityDecisionEnvelope(
                    action=SecurityAction.RETURN_429,
                    policy_name=policy_name,
                    reason_code=SECURITY_DECISION_IP_BLOCKED_REASON,
                    retry_after_seconds=block_result.retry_after_seconds,
                    security_event=self._security_event_builder.build_ip_block_event(
                        request=request,
                        ip_digest=block_result.ip_digest,
                        blocked=True,
                        blocked_until_epoch=block_result.blocked_until_epoch,
                        retry_after_seconds=block_result.retry_after_seconds,
                        reason_code=SECURITY_DECISION_IP_BLOCKED_REASON,
                        event_type=SecurityEventType.IP_BLOCKED,
                        status_code=HTTPStatus.TOO_MANY_REQUESTS,
                    ),
                )
        if not flow_control_enabled:
            return SecurityDecisionEnvelope(
                action=SecurityAction.ALLOW,
                policy_name=policy_name,
                reason_code=SECURITY_DECISION_ALLOW_REASON,
            )
        rate_limit_result = self._rate_limit_guard.evaluate(
            request=request,
            limit=limit,
            window_seconds=window_seconds,
            policy_name=policy_name,
            key_dimensions=key_dimensions,
            auth_field_values=auth_field_values,
            fail_mode=rate_limit_fail_mode,
        )
        if rate_limit_result.exceeded:
            if ip_block_enabled and block_when_exceeded:
                self._ip_block_guard.block_ip(
                    ip_digest=rate_limit_result.ip_digest,
                    reason=SecurityIpBlockReason.RATE_LIMIT_EXCEEDED,
                    block_seconds=block_seconds,
                    cache_ttl_seconds=ip_block_cache_ttl_seconds,
                )
            return SecurityDecisionEnvelope(
                action=SecurityAction.RETURN_429,
                policy_name=policy_name,
                reason_code=SECURITY_DECISION_RATE_LIMIT_REASON,
                retry_after_seconds=rate_limit_result.retry_after_seconds,
                security_event=self._security_event_builder.build_rate_limit_event(
                    request=request,
                    ip_digest=rate_limit_result.ip_digest,
                    count=rate_limit_result.count,
                    limit=rate_limit_result.limit,
                    blocked=True,
                ),
            )
        return SecurityDecisionEnvelope(
            action=SecurityAction.ALLOW,
            policy_name=policy_name,
            reason_code=SECURITY_DECISION_ALLOW_REASON,
        )
