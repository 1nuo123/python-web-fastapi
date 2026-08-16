"""Codex 控制面稳定错误码。"""

from enum import StrEnum


class CodexErrorCode(StrEnum):
    RESOURCE_NOT_FOUND = "codex.resource.not_found"
    IDEMPOTENCY_CONFLICT = "codex.operation.idempotency_conflict"
    STATE_CONFLICT = "codex.state.conflict"
    HOST_OFFLINE = "codex.host.offline"
    AGENT_ACK_TIMEOUT = "codex.agent.ack_timeout"
    PROTOCOL_INCOMPATIBLE = "codex.protocol.incompatible"
    UPSTREAM_FAILURE = "codex.upstream.failure"
    APPROVAL_GONE = "codex.approval.gone"
    DEVICE_AUTHORIZATION_NOT_FOUND = "codex.device_authorization.not_found"
    DEVICE_AUTHORIZATION_EXPIRED = "codex.device_authorization.expired"
    DEVICE_AUTHORIZATION_PENDING = "codex.device_authorization.pending"
    DEVICE_AUTHORIZATION_DENIED = "codex.device_authorization.denied"
    DEVICE_AUTHORIZATION_SLOW_DOWN = "codex.device_authorization.slow_down"
    DEVICE_AUTHORIZATION_FINALIZATION_PENDING = "codex.device_authorization.finalization_pending"
    ENROLLMENT_INTENT_NOT_FOUND = "codex.enrollment_intent.not_found"
    ENROLLMENT_INTENT_EXPIRED = "codex.enrollment_intent.expired"
    DEVICE_CHALLENGE_INVALID = "codex.device_challenge.invalid"
    DEVICE_TICKET_INVALID = "codex.device_ticket.invalid"
    VERSION_CONFLICT = "codex.version.conflict"
    SECURITY_RATE_LIMITED = "codex.security.rate_limited"
    PERMISSION_POLICY_DENIED = "codex.permission.policy_denied"
