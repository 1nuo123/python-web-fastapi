"""
安全防护契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.security_contract.outbound_url_safety_contract import (
    OutboundUrlSafetyEnvelope,
)
from src.core.security_contract.rate_limit_policy_contract import (
    RateLimitKeyDimension,
    RateLimitPolicyDetail,
    RateLimitPolicyEnvelope,
    RateLimitPolicyHeader,
)
from src.core.security_contract.security_event_contract import (
    IpBlockSecurityEventDetail,
    RateLimitSecurityEventDetail,
    SecurityEventEnvelope,
    SecurityEventHeader,
    SecurityEventSeverity,
)
from src.core.security_contract.token_binding_contract import (
    TokenBindingEnvelope,
    TokenBindingMode,
)
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment


class TestSecurityProtectionContract:
    """
    安全防护契约测试集合。
    """

    def test_rate_limit_policy_should_validate_detail_kind(self) -> None:
        """
        验证限流策略公共头与扩展字段一致。
        """

        policy = RateLimitPolicyEnvelope(
            header=RateLimitPolicyHeader(policy_name="global", enabled=True),
            detail=RateLimitPolicyDetail(
                limit=10,
                window_seconds=60,
                key_dimensions=[RateLimitKeyDimension.IP_DIGEST],
            ),
        )

        assert policy.detail.limit == 10

    def test_security_event_should_validate_detail_kind(self) -> None:
        """
        验证安全事件公共头与扩展字段一致。
        """

        detail = RateLimitSecurityEventDetail(
            ip_digest="1234567890abcdef",
            count=11,
            limit=10,
            blocked=True,
        )
        event = SecurityEventEnvelope(
            header=SecurityEventHeader(
                event_type="rate_limit.blocked",
                detail_kind=detail.kind,
                severity=SecurityEventSeverity.WARNING,
                request_id="request-1",
                trace_id=None,
                path="/health/live",
                method="GET",
                policy_name="global",
            ),
            detail=detail,
        )

        assert event.detail.blocked is True

    def test_ip_block_event_detail_should_expose_retry_after_contract(self) -> None:
        """
        验证 IP 封禁事件扩展字段暴露封禁状态与 Retry-After。
        """

        detail = IpBlockSecurityEventDetail(
            ip_digest="1234567890abcdef",
            reason_code="security.ip_blocked",
            blocked=True,
            blocked_until_epoch=1100,
            retry_after_seconds=100,
        )

        assert detail.blocked is True
        assert detail.retry_after_seconds == 100

    def test_token_binding_and_outbound_contract_should_forbid_extra(self) -> None:
        """
        验证 Token-IP 绑定与出站 URL 策略禁止额外字段。
        """

        token_policy = TokenBindingEnvelope(
            enabled=False,
            mode=TokenBindingMode.HIGH_RISK_ONLY,
            ip_digest_ttl_seconds=60,
        )
        outbound_policy = OutboundUrlSafetyEnvelope(
            enabled=True,
            allowed_schemes=["http", "https"],
            deny_private_networks=True,
            deny_metadata_address=True,
        )

        assert token_policy.enabled is False
        assert outbound_policy.deny_private_networks is True
        assert outbound_policy.allowed_hostnames == []
        assert outbound_policy.enforce_allowed_hostnames is False
        with pytest.raises(ValidationError):
            OutboundUrlSafetyEnvelope.model_validate(
                {
                    "enabled": True,
                    "allowed_schemes": ["https"],
                    "deny_private_networks": True,
                    "deny_metadata_address": True,
                    "extra_payload": {},
                }
            )

    def test_policy_ttl_window_and_settings_parse_failure_should_be_validated(
        self,
    ) -> None:
        """
        验证 TTL、窗口和配置解析失败路径。
        """

        with pytest.raises(ValidationError):
            RateLimitPolicyDetail(
                limit=0,
                window_seconds=60,
                key_dimensions=[RateLimitKeyDimension.IP_DIGEST],
            )
        with pytest.raises(ValidationError):
            TokenBindingEnvelope(
                enabled=True,
                mode=TokenBindingMode.HIGH_RISK_ONLY,
                ip_digest_ttl_seconds=0,
            )
        settings = AppSettingsLoader("config").load_for_environment(AppEnvironment.TEST)

        assert settings.runtime.security.detail.protection.flow_control.default_limit == 120
        assert (
            settings.runtime.security.detail.protection.flow_control.policies[0].detail.path
            == "/auth/token"
        )
