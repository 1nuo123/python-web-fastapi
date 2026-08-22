"""
日志事件契约核心模块。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.codex_contract.client_diagnostic_contract import (
    CLIENT_DIAGNOSTIC_CODE_PATTERN,
    CLIENT_DIAGNOSTIC_FINGERPRINT_PATTERN,
    CodexClientDiagnosticSource,
    CodexClientDiagnosticSummary,
)
from src.core.codex_contract.client_performance_contract import (
    CodexClientPerformanceMetric,
    CodexClientPerformanceObservation,
    CodexClientPerformanceSource,
    CodexClientPerformanceUnit,
)
from src.core.codex_contract.feature_flags_contract import (
    CODEX_EXPERIENCE_FEATURE_FLAG_POLICIES,
    CodexExperienceFeatureFlagDecision,
)
from src.core.http_contract.runtime_resource_contract import RuntimeResourceStatus
from src.core.security_contract.security_event_contract import (
    SecurityEventEnvelope,
    SecurityEventType,
)
from src.core.stream_contract.stream_event_contract import StreamCloseReason, StreamTransport

LOG_EVENT_SCHEMA_VERSION: Final = "1.1"
REQUEST_LOG_CONTEXT_KIND: Final = "request_log_context"
LOG_EVENT_HEADER_KIND: Final = "log_event_header"
ACCESS_LOG_DETAIL_KIND: Final = "access"
STREAM_ACCESS_LOG_DETAIL_KIND: Final = "stream_access"
EXCEPTION_LOG_DETAIL_KIND: Final = "exception"
RESOURCE_LIFECYCLE_LOG_DETAIL_KIND: Final = "resource_lifecycle"
TASK_FAILURE_LOG_DETAIL_KIND: Final = "task_failure"
SECURITY_LOG_DETAIL_KIND: Final = "security"
CODEX_CLIENT_DIAGNOSTIC_LOG_DETAIL_KIND: Final = "codex_client_diagnostic"
CODEX_CLIENT_PERFORMANCE_LOG_DETAIL_KIND: Final = "codex_client_performance"
CODEX_EXPERIENCE_FEATURE_FLAGS_LOG_DETAIL_KIND: Final = "codex_experience_feature_flags"
EVENT_ID_MINIMUM_LENGTH = 1
MESSAGE_MINIMUM_LENGTH = 1
SOURCE_NAME_MINIMUM_LENGTH = 1
ELAPSED_MILLISECONDS_MINIMUM = 0.0
HTTP_STATUS_CODE_MINIMUM = 100
HTTP_STATUS_CODE_MAXIMUM = 599


class LogPersistencePriority(StrEnum):
    """
    日志持久化优先级枚举。

    :cvar STANDARD: 标准优先级，事件进入缓冲区按容量或时间窗口批量刷盘。
    :cvar AUDIT_CRITICAL: 审计关键优先级，事件绕过缓冲区在发射线程内即时同步落库。
    """

    STANDARD = "standard"
    AUDIT_CRITICAL = "audit_critical"


AUDIT_CRITICAL_SECURITY_EVENT_TYPES: Final[frozenset[SecurityEventType]] = frozenset(
    {
        SecurityEventType.ADMIN_IDENTITY_CHANGED,
        SecurityEventType.CONFIG_SECURITY_REJECTED,
    }
)


class LogLevel(StrEnum):
    """
    日志级别枚举。
    """

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogEventKind(StrEnum):
    """
    日志事件类型枚举。
    """

    ACCESS = ACCESS_LOG_DETAIL_KIND
    STREAM_ACCESS = STREAM_ACCESS_LOG_DETAIL_KIND
    EXCEPTION = EXCEPTION_LOG_DETAIL_KIND
    RESOURCE_LIFECYCLE = RESOURCE_LIFECYCLE_LOG_DETAIL_KIND
    TASK_FAILURE = TASK_FAILURE_LOG_DETAIL_KIND
    SECURITY = SECURITY_LOG_DETAIL_KIND
    CODEX_CLIENT_DIAGNOSTIC = CODEX_CLIENT_DIAGNOSTIC_LOG_DETAIL_KIND
    CODEX_CLIENT_PERFORMANCE = CODEX_CLIENT_PERFORMANCE_LOG_DETAIL_KIND
    CODEX_EXPERIENCE_FEATURE_FLAGS = CODEX_EXPERIENCE_FEATURE_FLAGS_LOG_DETAIL_KIND


class ResourceLifecycleAction(StrEnum):
    """
    资源生命周期动作枚举。
    """

    STARTUP = "startup"
    SHUTDOWN = "shutdown"
    RELOAD = "reload"


class RequestLogContext(BaseModel):
    """
    请求日志上下文模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["request_log_context"] = REQUEST_LOG_CONTEXT_KIND
    schema_version: Literal["1.1"] = LOG_EVENT_SCHEMA_VERSION
    request_id: str = Field(min_length=EVENT_ID_MINIMUM_LENGTH)
    trace_id: str | None = None
    request_path: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    request_method: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    authenticated_subject_id: str | None = None
    client_ip: str | None = None
    user_agent: str | None = None


class LogEventHeader(BaseModel):
    """
    日志公共头字段模型。

    :ivar persistence_priority: 日志持久化优先级；``audit_critical`` 事件绕过缓冲即时落库。
    :vartype persistence_priority: LogPersistencePriority
    """

    model_config = ConfigDict(extra="forbid")

    header_kind: Literal["log_event_header"] = LOG_EVENT_HEADER_KIND
    schema_version: Literal["1.1"] = LOG_EVENT_SCHEMA_VERSION
    event_id: str = Field(min_length=EVENT_ID_MINIMUM_LENGTH)
    occurred_at: datetime
    level: LogLevel
    kind: LogEventKind
    persistence_priority: LogPersistencePriority = LogPersistencePriority.STANDARD
    message: str = Field(min_length=MESSAGE_MINIMUM_LENGTH)
    request_id: str | None = None
    trace_id: str | None = None
    authenticated_subject_id: str | None = None
    source_module: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    source_component: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)


class AccessLogDetail(BaseModel):
    """
    访问日志扩展字段模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["access"] = ACCESS_LOG_DETAIL_KIND
    schema_version: Literal["1.1"] = LOG_EVENT_SCHEMA_VERSION
    request_path: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    request_method: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    status_code: int = Field(
        ge=HTTP_STATUS_CODE_MINIMUM,
        le=HTTP_STATUS_CODE_MAXIMUM,
    )
    elapsed_milliseconds: float = Field(ge=ELAPSED_MILLISECONDS_MINIMUM)
    client_ip: str | None = None
    user_agent: str | None = None
    route_name: str | None = None


class StreamAccessLogDetail(BaseModel):
    """流会话完成后的低基数访问日志扩展。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["stream_access"] = STREAM_ACCESS_LOG_DETAIL_KIND
    schema_version: Literal["1.1"] = LOG_EVENT_SCHEMA_VERSION
    request_path: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    request_method: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    status_code: int = Field(ge=HTTP_STATUS_CODE_MINIMUM, le=HTTP_STATUS_CODE_MAXIMUM)
    elapsed_milliseconds: float = Field(ge=ELAPSED_MILLISECONDS_MINIMUM)
    operation_name: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    transport: StreamTransport
    event_count: int = Field(ge=0)
    close_reason: StreamCloseReason
    subject_digest: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)


class ExceptionLogDetail(BaseModel):
    """
    异常日志扩展字段模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["exception"] = EXCEPTION_LOG_DETAIL_KIND
    schema_version: Literal["1.1"] = LOG_EVENT_SCHEMA_VERSION
    request_path: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    request_method: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    status_code: int = Field(
        ge=HTTP_STATUS_CODE_MINIMUM,
        le=HTTP_STATUS_CODE_MAXIMUM,
    )
    error_code: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    exception_type: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    detail: str | None = None
    traceback_text: str | None = None


class ResourceLifecycleLogDetail(BaseModel):
    """
    资源生命周期日志扩展字段模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["resource_lifecycle"] = RESOURCE_LIFECYCLE_LOG_DETAIL_KIND
    schema_version: Literal["1.1"] = LOG_EVENT_SCHEMA_VERSION
    resource_name: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    lifecycle_action: ResourceLifecycleAction
    resource_status: RuntimeResourceStatus
    detail: str | None = None


class TaskFailureLogDetail(BaseModel):
    """
    任务失败日志扩展字段模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["task_failure"] = TASK_FAILURE_LOG_DETAIL_KIND
    schema_version: Literal["1.1"] = LOG_EVENT_SCHEMA_VERSION
    task_id: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    job_kind: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    backend: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    stage: str = Field(min_length=SOURCE_NAME_MINIMUM_LENGTH)
    retry_count: int = Field(ge=0)
    queue_name: str | None = None
    payload_kind: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    deduplication_key: str | None = None
    attempt_count: int = Field(ge=0, default=0)
    detail: str | None = None


class SecurityLogDetail(BaseModel):
    """
    安全日志扩展字段模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["security"] = SECURITY_LOG_DETAIL_KIND
    schema_version: Literal["1.1"] = LOG_EVENT_SCHEMA_VERSION
    security_event: SecurityEventEnvelope


class CodexClientDiagnosticLogDetail(BaseModel):
    """Codex 客户端错误诊断的受限结构化日志详情。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["codex_client_diagnostic"] = CODEX_CLIENT_DIAGNOSTIC_LOG_DETAIL_KIND
    schema_version: Literal["1.1"] = LOG_EVENT_SCHEMA_VERSION
    source: CodexClientDiagnosticSource
    summary: CodexClientDiagnosticSummary
    error_code: str = Field(pattern=CLIENT_DIAGNOSTIC_CODE_PATTERN)
    fingerprint: str = Field(pattern=CLIENT_DIAGNOSTIC_FINGERPRINT_PATTERN)


class CodexClientPerformanceLogDetail(BaseModel):
    """Codex 客户端性能样本的受限结构化日志详情。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["codex_client_performance"] = CODEX_CLIENT_PERFORMANCE_LOG_DETAIL_KIND
    schema_version: Literal["1.1"] = LOG_EVENT_SCHEMA_VERSION
    source: CodexClientPerformanceSource
    metric: CodexClientPerformanceMetric
    observation: CodexClientPerformanceObservation
    unit: CodexClientPerformanceUnit
    value: float = Field(ge=0)


class CodexExperienceFeatureFlagsLogDetail(BaseModel):
    """服务端下发体验开关时的封闭发布决策日志详情。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["codex_experience_feature_flags"] = CODEX_EXPERIENCE_FEATURE_FLAGS_LOG_DETAIL_KIND
    schema_version: Literal["1.1"] = LOG_EVENT_SCHEMA_VERSION
    decisions: tuple[CodexExperienceFeatureFlagDecision, ...] = Field(
        min_length=len(CODEX_EXPERIENCE_FEATURE_FLAG_POLICIES),
        max_length=len(CODEX_EXPERIENCE_FEATURE_FLAG_POLICIES),
    )

    @model_validator(mode="after")
    def validate_decision_order(self) -> CodexExperienceFeatureFlagsLogDetail:
        """要求完整且固定顺序的开关清单，防止日志遗漏或重排语义。"""

        expected_names = tuple(policy.name for policy in CODEX_EXPERIENCE_FEATURE_FLAG_POLICIES)
        actual_names = tuple(decision.name for decision in self.decisions)
        if actual_names != expected_names:
            raise ValueError("体验开关日志必须包含完整且固定顺序的开关决策。")
        return self


LogDetailUnion = Annotated[
    AccessLogDetail
    | StreamAccessLogDetail
    | ExceptionLogDetail
    | ResourceLifecycleLogDetail
    | TaskFailureLogDetail
    | SecurityLogDetail
    | CodexClientDiagnosticLogDetail
    | CodexClientPerformanceLogDetail
    | CodexExperienceFeatureFlagsLogDetail,
    Field(discriminator="kind"),
]


class LogEventEnvelope(BaseModel):
    """
    日志事件信封模型。
    """

    model_config = ConfigDict(extra="forbid")

    header: LogEventHeader
    detail: LogDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> LogEventEnvelope:
        """
        校验公共头字段与扩展字段的一致性。
        """

        if self.header.kind.value != self.detail.kind:
            raise ValueError("日志公共头字段 kind 必须与扩展字段 kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("日志公共头字段 schema_version 必须与扩展字段 schema_version 一致。")
        return self
