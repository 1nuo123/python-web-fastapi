"""Codex 生产硬化公共头与强类型扩展契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

CODEX_PRODUCTION_POLICY_SCHEMA_VERSION: Final = "1.0"
CODEX_PRODUCTION_POLICY_HEADER_KIND: Final = "codex_production_policy_header"
CODEX_ABUSE_POLICY_KIND: Final = "codex_abuse_policy"
CODEX_RETENTION_POLICY_KIND: Final = "codex_retention_policy"
CODEX_SLO_POLICY_KIND: Final = "codex_slo_policy"
SECONDS_PER_DAY: Final = 86_400
DAYS_PER_WEEK: Final = 7
DAYS_PER_MONTH: Final = 30
DAYS_PER_QUARTER: Final = 90
DAYS_PER_YEAR: Final = 365
MINIMUM_RETENTION_SECONDS: Final = 60
DEFAULT_ENROLLMENT_PER_IP_PER_HOUR: Final = 12
DEFAULT_ENROLLMENT_PER_USER_PER_HOUR: Final = 8
DEFAULT_ENROLLMENT_PER_ASN_PER_HOUR: Final = 2_000
DEFAULT_ANOMALOUS_FINGERPRINT_THRESHOLD: Final = 5
MAXIMUM_ENROLLMENT_RATE: Final = 10_000
MAXIMUM_ASN_ENROLLMENT_RATE: Final = 1_000_000
MAXIMUM_FINGERPRINT_THRESHOLD: Final = 1_000
DEFAULT_HOST_ONLINE_P95_MILLISECONDS: Final = 3_000
DEFAULT_COMMAND_ACK_P95_MILLISECONDS: Final = 1_000
DEFAULT_RECONNECT_P95_MILLISECONDS: Final = 5_000
DEFAULT_ERROR_BUDGET_PERCENT: Final = 1.0
MAXIMUM_ERROR_BUDGET_PERCENT: Final = 100.0


class CodexCanaryStage(StrEnum):
    """生产发布分批阶段。"""

    INTERNAL = "internal"
    INVITED = "invited"
    LIMITED_PUBLIC = "limited_public"
    GENERAL_AVAILABILITY = "general_availability"


class CodexProductionPolicyHeader(BaseModel):
    """生产硬化策略公共头。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_production_policy_header"] = CODEX_PRODUCTION_POLICY_HEADER_KIND
    schema_version: Literal["1.0"] = CODEX_PRODUCTION_POLICY_SCHEMA_VERSION
    detail_kind: Literal[
        "codex_abuse_policy",
        "codex_retention_policy",
        "codex_slo_policy",
    ]
    enabled: bool = True


class CodexAbusePolicyDetail(BaseModel):
    """公开注册与设备授权的滥用防护阈值。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_abuse_policy"] = CODEX_ABUSE_POLICY_KIND
    schema_version: Literal["1.0"] = CODEX_PRODUCTION_POLICY_SCHEMA_VERSION
    enrollment_per_ip_per_hour: int = Field(
        default=DEFAULT_ENROLLMENT_PER_IP_PER_HOUR,
        ge=1,
        le=MAXIMUM_ENROLLMENT_RATE,
    )
    enrollment_per_user_per_hour: int = Field(
        default=DEFAULT_ENROLLMENT_PER_USER_PER_HOUR,
        ge=1,
        le=MAXIMUM_ENROLLMENT_RATE,
    )
    enrollment_per_asn_per_hour: int = Field(
        default=DEFAULT_ENROLLMENT_PER_ASN_PER_HOUR,
        ge=1,
        le=MAXIMUM_ASN_ENROLLMENT_RATE,
    )
    anomalous_fingerprint_threshold: int = Field(
        default=DEFAULT_ANOMALOUS_FINGERPRINT_THRESHOLD,
        ge=1,
        le=MAXIMUM_FINGERPRINT_THRESHOLD,
    )
    manual_freeze_enabled: bool = True


class CodexRetentionPolicyDetail(BaseModel):
    """服务端与 Agent 本地最小化留存策略。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_retention_policy"] = CODEX_RETENTION_POLICY_KIND
    schema_version: Literal["1.0"] = CODEX_PRODUCTION_POLICY_SCHEMA_VERSION
    completed_outbox_seconds: int = Field(
        default=SECONDS_PER_DAY,
        ge=MINIMUM_RETENTION_SECONDS,
        le=DAYS_PER_MONTH * SECONDS_PER_DAY,
    )
    browser_event_stream_seconds: int = Field(
        default=SECONDS_PER_DAY,
        ge=MINIMUM_RETENTION_SECONDS,
        le=DAYS_PER_WEEK * SECONDS_PER_DAY,
    )
    agent_command_journal_seconds: int = Field(
        default=DAYS_PER_WEEK * SECONDS_PER_DAY,
        ge=SECONDS_PER_DAY,
        le=DAYS_PER_QUARTER * SECONDS_PER_DAY,
    )
    revoked_host_metadata_seconds: int = Field(
        default=DAYS_PER_MONTH * SECONDS_PER_DAY,
        ge=SECONDS_PER_DAY,
        le=DAYS_PER_YEAR * SECONDS_PER_DAY,
    )


class CodexSloPolicyDetail(BaseModel):
    """SLO、错误预算与 rollout 停止阈值。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_slo_policy"] = CODEX_SLO_POLICY_KIND
    schema_version: Literal["1.0"] = CODEX_PRODUCTION_POLICY_SCHEMA_VERSION
    host_online_p95_milliseconds: int = Field(
        default=DEFAULT_HOST_ONLINE_P95_MILLISECONDS,
        ge=1,
    )
    command_ack_p95_milliseconds: int = Field(
        default=DEFAULT_COMMAND_ACK_P95_MILLISECONDS,
        ge=1,
    )
    reconnect_p95_milliseconds: int = Field(
        default=DEFAULT_RECONNECT_P95_MILLISECONDS,
        ge=1,
    )
    maximum_event_gap_count: int = Field(default=0, ge=0)
    error_budget_percent: float = Field(
        default=DEFAULT_ERROR_BUDGET_PERCENT,
        gt=0,
        le=MAXIMUM_ERROR_BUDGET_PERCENT,
    )
    rollout_stage: CodexCanaryStage = CodexCanaryStage.INTERNAL
    pause_rollout_when_exceeded: bool = True


CodexProductionPolicyDetail = Annotated[
    CodexAbusePolicyDetail | CodexRetentionPolicyDetail | CodexSloPolicyDetail,
    Field(discriminator="kind"),
]


class CodexProductionPolicyEnvelope(BaseModel):
    """生产硬化策略信封。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    header: CodexProductionPolicyHeader
    detail: CodexProductionPolicyDetail

    @model_validator(mode="after")
    def validate_envelope(self) -> CodexProductionPolicyEnvelope:
        """校验公共头与强类型扩展字段一致。"""

        if self.header.detail_kind != self.detail.kind:
            raise ValueError("Codex生产策略header.detail_kind与detail.kind不一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("Codex生产策略schema_version不一致。")
        return self
