"""Agent 连接诊断与执行许可的公共常量。"""

from enum import StrEnum
from typing import Final

AGENT_EXECUTION_LEASE_SECONDS: Final = 35
AGENT_EXECUTION_LEASE_MAX_SECONDS: Final = 60
AGENT_CONNECTION_REJECTION_HEADER: Final = "x-codex-agent-error"
AGENT_CONNECTION_TICKET_EXPIRED: Final = "ticket_expired"


class AgentConnectionIssue(StrEnum):
    """连接原因与认证事实分开，供状态投影及日志共同消费。"""

    TRANSPORT_UNAVAILABLE = "transport_unavailable"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    RATE_LIMITED = "rate_limited"
    TLS_VALIDATION_FAILED = "tls_validation_failed"
    ORIGIN_TLS_FAILED = "origin_tls_failed"
    AUTHORIZATION_REJECTED = "authorization_rejected"
    GATEWAY_POLICY_DENIED = "gateway_policy_denied"
    ROUTE_NOT_FOUND = "route_not_found"
    PROTOCOL_INVALID = "protocol_invalid"
    CONFIG_INVALID = "config_invalid"
    INTERNAL_FAILURE = "internal_failure"
    ATTEMPT_EXPIRED = "connection_attempt_expired"


class AgentCommandAdmissionClosed(PermissionError):
    """开始下一副作用前，原连接准入或执行许可已经失效。"""


class AgentConnectionTicketExpired(PermissionError):
    """一次性票据不存在、过期或已消费，必须重新获取，不能重用。"""
