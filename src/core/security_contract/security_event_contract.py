"""
安全事件契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SECURITY_EVENT_SCHEMA_VERSION: Final = "1.0"
SECURITY_EVENT_HEADER_KIND: Final = "security_event_header"
AUTH_FAILURE_EVENT_KIND: Final = "auth_failure_security_event"
RATE_LIMIT_EVENT_KIND: Final = "rate_limit_security_event"
PAYLOAD_EVENT_KIND: Final = "payload_security_event"
TOKEN_BINDING_EVENT_KIND: Final = "token_binding_security_event"
SSRF_EVENT_KIND: Final = "ssrf_security_event"
IP_BLOCK_EVENT_KIND: Final = "ip_block_security_event"
AUTHORIZATION_EVENT_KIND: Final = "authorization_security_event"
CONFIG_SECURITY_EVENT_KIND: Final = "config_security_event"
ADMIN_IDENTITY_SECURITY_EVENT_KIND: Final = "admin_identity_security_event"
SECURITY_EVENT_TYPE_MINIMUM_LENGTH = 1
SECURITY_EVENT_REASON_MINIMUM_LENGTH = 1
SECURITY_EVENT_OCCURRED_AT_MINIMUM = 0
SECURITY_EVENT_COUNT_MINIMUM = 0
SECURITY_EVENT_RECORDED_REASON = "security.event.recorded"


class SecurityEventSeverity(StrEnum):
    """
    安全事件严重级别。
    """

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"


class SecurityEventType(StrEnum):
    """
    安全事件类型枚举。
    """

    AUTH_LOGIN_FAILURE = "auth.login.failure"
    AUTH_LOGIN_THROTTLED = "auth.login.throttled"
    AUTH_PASSWORD_SPRAY_SUSPECTED = "auth.password_spray_suspected"
    AUTH_REFRESH_REUSED = "auth.refresh.reused"
    AUTH_TOKEN_INVALID = "auth.token.invalid"
    AUTHZ_DENIED = "authz.denied"
    IP_BLOCKED = "ip.blocked"
    IP_UNBLOCKED = "ip.unblocked"
    RATE_LIMIT_BLOCKED = "rate_limit.blocked"
    PAYLOAD_TOO_LARGE = "payload.too_large"
    SSRF_BLOCKED = "ssrf.blocked"
    TOKEN_BINDING_MISMATCH = "token_binding.mismatch"
    CONFIG_SECURITY_REJECTED = "config.security_rejected"
    ADMIN_IDENTITY_CHANGED = "admin.identity.changed"


class SecurityEventDecision(StrEnum):
    """
    安全事件决策枚举。
    """

    ALLOW = "allow"
    DENY = "deny"
    THROTTLE = "throttle"
    RECORD_ONLY = "record_only"


class SecurityEventHeader(BaseModel):
    """
    安全事件公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["security_event_header"] = SECURITY_EVENT_HEADER_KIND
    schema_version: Literal["1.0"] = SECURITY_EVENT_SCHEMA_VERSION
    event_type: str = Field(min_length=SECURITY_EVENT_TYPE_MINIMUM_LENGTH)
    detail_kind: str
    severity: SecurityEventSeverity
    decision: SecurityEventDecision = SecurityEventDecision.RECORD_ONLY
    reason_code: str = Field(
        default=SECURITY_EVENT_RECORDED_REASON,
        min_length=SECURITY_EVENT_REASON_MINIMUM_LENGTH,
    )
    request_id: str
    trace_id: str | None
    path: str
    method: str
    status_code: int | None = None
    subject_id: str | None = None
    ip_digest: str | None = None
    user_agent_digest: str | None = None
    policy_name: str
    occurred_at_epoch: int = Field(default=0, ge=SECURITY_EVENT_OCCURRED_AT_MINIMUM)


class AuthFailureSecurityEventDetail(BaseModel):
    """
    认证失败安全事件扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["auth_failure_security_event"] = AUTH_FAILURE_EVENT_KIND
    schema_version: Literal["1.0"] = SECURITY_EVENT_SCHEMA_VERSION
    subject_digest: str | None = None
    ip_digest: str | None = None
    reason_code: str


class RateLimitSecurityEventDetail(BaseModel):
    """
    限流安全事件扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["rate_limit_security_event"] = RATE_LIMIT_EVENT_KIND
    schema_version: Literal["1.0"] = SECURITY_EVENT_SCHEMA_VERSION
    ip_digest: str
    count: int
    limit: int
    blocked: bool


class PayloadSecurityEventDetail(BaseModel):
    """
    请求体安全事件扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["payload_security_event"] = PAYLOAD_EVENT_KIND
    schema_version: Literal["1.0"] = SECURITY_EVENT_SCHEMA_VERSION
    limit_bytes: int


class TokenBindingSecurityEventDetail(BaseModel):
    """
    Token-IP 绑定安全事件扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["token_binding_security_event"] = TOKEN_BINDING_EVENT_KIND
    schema_version: Literal["1.0"] = SECURITY_EVENT_SCHEMA_VERSION
    token_digest: str
    ip_digest: str
    reason_code: str


class SsrfSecurityEventDetail(BaseModel):
    """
    SSRF 安全事件扩展。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["ssrf_security_event"] = SSRF_EVENT_KIND
    schema_version: Literal["1.0"] = SECURITY_EVENT_SCHEMA_VERSION
    host_digest: str | None
    reason_code: str


class IpBlockSecurityEventDetail(BaseModel):
    """
    IP 封禁安全事件扩展。

    :ivar kind: 扩展类型。
    :vartype kind: Literal[IP_BLOCK_EVENT_KIND]
    :ivar schema_version: 契约版本。
    :vartype schema_version: Literal[SECURITY_EVENT_SCHEMA_VERSION]
    :ivar ip_digest: IP 摘要。
    :vartype ip_digest: str
    :ivar reason_code: 事件原因。
    :vartype reason_code: str
    :ivar blocked: IP 是否处于封禁状态。
    :vartype blocked: bool
    :ivar blocked_until_epoch: 封禁结束时间戳。
    :vartype blocked_until_epoch: int | None
    :ivar retry_after_seconds: 建议重试等待秒数。
    :vartype retry_after_seconds: int | None
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["ip_block_security_event"] = IP_BLOCK_EVENT_KIND
    schema_version: Literal["1.0"] = SECURITY_EVENT_SCHEMA_VERSION
    ip_digest: str
    reason_code: str
    blocked: bool
    blocked_until_epoch: int | None = None
    retry_after_seconds: int | None = None


class AuthorizationSecurityEventDetail(BaseModel):
    """
    授权拒绝安全事件扩展。

    :ivar kind: 扩展类型。
    :vartype kind: Literal[AUTHORIZATION_EVENT_KIND]
    :ivar schema_version: 契约版本。
    :vartype schema_version: Literal[SECURITY_EVENT_SCHEMA_VERSION]
    :ivar subject_id: 授权主体标识。
    :vartype subject_id: str | None
    :ivar reason_code: 授权拒绝原因。
    :vartype reason_code: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["authorization_security_event"] = AUTHORIZATION_EVENT_KIND
    schema_version: Literal["1.0"] = SECURITY_EVENT_SCHEMA_VERSION
    subject_id: str | None
    reason_code: str


class ConfigSecurityEventDetail(BaseModel):
    """
    安全配置拒绝事件扩展。

    :ivar kind: 扩展类型。
    :vartype kind: Literal[CONFIG_SECURITY_EVENT_KIND]
    :ivar schema_version: 契约版本。
    :vartype schema_version: Literal[SECURITY_EVENT_SCHEMA_VERSION]
    :ivar reason_code: 配置拒绝原因。
    :vartype reason_code: str
    :ivar rejected_field_count: 被拒绝字段数量。
    :vartype rejected_field_count: int
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["config_security_event"] = CONFIG_SECURITY_EVENT_KIND
    schema_version: Literal["1.0"] = SECURITY_EVENT_SCHEMA_VERSION
    reason_code: str
    rejected_field_count: int = Field(ge=SECURITY_EVENT_COUNT_MINIMUM)


class AdminIdentitySecurityEventDetail(BaseModel):
    """
    管理员身份变更安全事件扩展。

    :ivar operation_name: 管理员身份操作名称。
    :vartype operation_name: str
    :ivar target_kind: 被操作目标类型。
    :vartype target_kind: str
    :ivar target_id: 被操作目标标识。
    :vartype target_id: str
    :ivar actor_subject_id: 操作者主体标识。
    :vartype actor_subject_id: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["admin_identity_security_event"] = ADMIN_IDENTITY_SECURITY_EVENT_KIND
    schema_version: Literal["1.0"] = SECURITY_EVENT_SCHEMA_VERSION
    operation_name: str
    target_kind: str
    target_id: str
    actor_subject_id: str


SecurityEventDetailUnion = Annotated[
    AuthFailureSecurityEventDetail
    | RateLimitSecurityEventDetail
    | PayloadSecurityEventDetail
    | TokenBindingSecurityEventDetail
    | SsrfSecurityEventDetail
    | IpBlockSecurityEventDetail
    | AuthorizationSecurityEventDetail
    | ConfigSecurityEventDetail
    | AdminIdentitySecurityEventDetail,
    Field(discriminator="kind"),
]


class SecurityEventEnvelope(BaseModel):
    """
    安全事件信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: SecurityEventHeader
    detail: SecurityEventDetailUnion

    @model_validator(mode="after")
    def validate_security_event_contract(self) -> SecurityEventEnvelope:
        """
        校验安全事件公共头与扩展字段一致。
        """

        if self.header.detail_kind != self.detail.kind:
            raise ValueError("安全事件 header.detail_kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("安全事件 header.schema_version 必须与 detail 一致。")
        return self
