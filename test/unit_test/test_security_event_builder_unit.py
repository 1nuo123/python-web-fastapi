"""
安全事件构建器单元测试模块。
"""

from __future__ import annotations

from starlette.requests import Request

from src.core.http_contract.request_scope_contract import RequestScope
from src.core.security_contract.security_event_contract import (
    SecurityEventDecision,
    SecurityEventType,
)
from src.infrastructure.logging.log_event_builder import LogEventBuilder
from src.infrastructure.security.client_ip_resolver import (
    ClientIpResolver,
    TrustedProxyPolicy,
)
from src.infrastructure.security.security_event_builder import SecurityEventBuilder

RAW_BEARER_TOKEN = "Bearer abcdefghij.abcdefghij.abcdefghij"
RAW_PASSWORD_TEXT = "password=plain-secret"
TRUSTED_PROXY_IP = "10.20.0.10"
FORWARDED_CLIENT_IP = "203.0.113.8"


class TestSecurityEventBuilderUnit:
    """
    安全事件构建器单元测试集合。
    """

    def test_rate_limit_event_should_keep_request_context(self) -> None:
        """
        验证限流安全事件保留请求链路字段。
        """

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/health/live",
                "headers": [],
                "client": ("127.0.0.1", 12345),
                "scheme": "http",
                "server": ("testserver", 80),
            }
        )
        request.state.request_scope = RequestScope(
            request_id="request-1",
            trace_id="trace-1",
            request_time_epoch=1,
            request_path="/health/live",
            request_method="GET",
        )

        event = SecurityEventBuilder().build_rate_limit_event(
            request=request,
            ip_digest="1234567890abcdef",
            count=2,
            limit=1,
            blocked=True,
        )

        assert event.header.request_id == "request-1"
        assert event.detail.ip_digest == "1234567890abcdef"

    def test_auth_failure_event_should_only_keep_digest_fields(self) -> None:
        """
        验证认证失败事件只保存摘要和决策字段。
        """

        request = self._build_request()
        request.state.request_scope = RequestScope(
            request_id="request-1",
            trace_id="trace-1",
            request_time_epoch=1,
            request_path="/auth/token",
            request_method="POST",
        )

        event = SecurityEventBuilder().build_auth_failure_event(
            request=request,
            subject_digest="username-digest",
            ip_digest="ip-digest",
            reason_code="auth.access.invalid_credentials",
            event_type=SecurityEventType.AUTH_LOGIN_FAILURE,
            status_code=401,
            user_agent_digest="user-agent-digest",
        )
        event_payload = event.model_dump_json()

        assert event.header.event_type == SecurityEventType.AUTH_LOGIN_FAILURE
        assert event.header.decision == SecurityEventDecision.DENY
        assert event.header.status_code == 401
        assert event.header.ip_digest == "ip-digest"
        assert event.header.user_agent_digest == "user-agent-digest"
        assert "password" not in event_payload
        assert "Bearer" not in event_payload

    def test_ip_block_event_should_include_retry_after_detail(self) -> None:
        """
        验证 IP 封禁事件包含封禁状态和重试等待字段。
        """

        request = self._build_request()
        event = SecurityEventBuilder().build_ip_block_event(
            request=request,
            ip_digest="1234567890abcdef",
            reason_code="security.ip_blocked",
            event_type=SecurityEventType.IP_BLOCKED,
            status_code=429,
            blocked=True,
            blocked_until_epoch=1100,
            retry_after_seconds=100,
        )

        assert event.header.event_type == SecurityEventType.IP_BLOCKED
        assert event.detail.blocked is True
        assert event.detail.blocked_until_epoch == 1100
        assert event.detail.retry_after_seconds == 100

    def test_security_log_event_should_reuse_sensitive_text_redactor(self) -> None:
        """
        验证安全事件写入日志前复用敏感文本脱敏能力。
        """

        request = self._build_request()
        request.state.request_scope = RequestScope(
            request_id="request-1",
            trace_id="trace-1",
            request_time_epoch=1,
            request_path="/auth/token",
            request_method="POST",
        )
        security_event = SecurityEventBuilder().build_auth_failure_event(
            request=request,
            subject_digest="username-digest",
            ip_digest="ip-digest",
            reason_code=f"{RAW_PASSWORD_TEXT} {RAW_BEARER_TOKEN}",
            event_type=SecurityEventType.AUTH_LOGIN_FAILURE,
            status_code=401,
            user_agent_digest="user-agent-digest",
        )

        log_event = LogEventBuilder().build_security_event(security_event=security_event)
        log_payload = log_event.model_dump_json()

        assert "plain-secret" not in log_payload
        assert "abcdefghij.abcdefghij.abcdefghij" not in log_payload

    def test_log_request_context_should_resolve_client_ip_from_configured_proxy(
        self,
    ) -> None:
        """
        Verify ordinary log context uses ClientIpResolver instead of direct remote IP.
        """

        request = self._build_request(
            client_ip=TRUSTED_PROXY_IP,
            headers=[("x-forwarded-for", FORWARDED_CLIENT_IP)],
        )
        log_event_builder = LogEventBuilder(
            client_ip_resolver=ClientIpResolver(
                trusted_proxy_policy=TrustedProxyPolicy(cidr_blocks=("10.20.0.0/16",))
            )
        )

        request_context = log_event_builder.build_request_context(request)

        assert request_context.client_ip == FORWARDED_CLIENT_IP

    def _build_request(
        self,
        *,
        client_ip: str = "127.0.0.1",
        headers: list[tuple[str, str]] | None = None,
    ) -> Request:
        """
        构建测试请求。
        """

        raw_headers = [
            (name.encode("latin-1"), value.encode("latin-1")) for name, value in (headers or [])
        ]
        return Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/auth/token",
                "headers": raw_headers,
                "client": (client_ip, 12345),
                "scheme": "http",
                "server": ("testserver", 80),
            }
        )
