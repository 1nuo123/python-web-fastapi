"""
Prometheus 指标注册基础设施模块。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.exposition import generate_latest

from src.core.codex_contract.client_diagnostic_contract import CodexClientDiagnosticSource
from src.core.codex_contract.client_performance_contract import (
    CodexClientPerformanceMetric,
    CodexClientPerformanceObservation,
)
from src.core.logging_contract.log_writer_contract import LogWriteReason
from src.core.security_contract.security_event_contract import (
    SecurityEventDecision,
    SecurityEventSeverity,
    SecurityEventType,
)
from src.core.stream_contract.stream_event_contract import StreamCloseReason, StreamTransport

REQUEST_TOTAL_NAME = "fastapi_request_total"
REQUEST_TOTAL_DESCRIPTION = "FastAPI HTTP 请求总数"
REQUEST_DURATION_SECONDS_NAME = "fastapi_request_duration_seconds"
REQUEST_DURATION_SECONDS_DESCRIPTION = "FastAPI HTTP 请求耗时秒数"
RUNTIME_READY_NAME = "fastapi_runtime_ready"
RUNTIME_READY_DESCRIPTION = "FastAPI 应用 ready 状态"
SECURITY_EVENT_TOTAL_NAME = "fastapi_security_event_total"
SECURITY_EVENT_TOTAL_DESCRIPTION = "安全事件总数"
LOG_BUFFER_FLUSH_TOTAL_NAME = "fastapi_log_buffer_flush_total"
LOG_BUFFER_FLUSH_TOTAL_DESCRIPTION = "日志缓冲刷盘事件总数"
LOG_BUFFER_PENDING_ITEMS_NAME = "fastapi_log_buffer_pending_items"
LOG_BUFFER_PENDING_ITEMS_DESCRIPTION = "日志缓冲待落库事件数量"
TASK_EXECUTION_TOTAL_NAME = "fastapi_task_execution_total"
TASK_EXECUTION_TOTAL_DESCRIPTION = "任务执行结果总数"
RUNTIME_SATURATION_RATIO_NAME = "fastapi_runtime_saturation_ratio"
RUNTIME_SATURATION_RATIO_DESCRIPTION = "运行时有界资源饱和度"
STREAM_ACTIVE_SESSIONS_NAME = "fastapi_stream_active_sessions"
STREAM_ACTIVE_SESSIONS_DESCRIPTION = "流式活跃会话数"
STREAM_SESSION_TOTAL_NAME = "fastapi_stream_session_total"
STREAM_SESSION_TOTAL_DESCRIPTION = "流式会话结果总数"
STREAM_SESSION_DURATION_SECONDS_NAME = "fastapi_stream_session_duration_seconds"
STREAM_SESSION_DURATION_SECONDS_DESCRIPTION = "流式会话持续时间秒数"
STREAM_EVENT_TOTAL_NAME = "fastapi_stream_event_total"
STREAM_EVENT_TOTAL_DESCRIPTION = "流式事件发送总数"
STREAM_EVENT_BYTES_NAME = "fastapi_stream_event_bytes_total"
STREAM_EVENT_BYTES_DESCRIPTION = "流式事件发送字节总数"
STREAM_QUEUE_SATURATION_NAME = "fastapi_stream_queue_saturation_ratio"
STREAM_QUEUE_SATURATION_DESCRIPTION = "流式会话队列饱和度"
STREAM_RESUME_TOTAL_NAME = "fastapi_stream_resume_total"
STREAM_RESUME_TOTAL_DESCRIPTION = "流式有限恢复结果总数"
CODEX_CLIENT_DIAGNOSTIC_TOTAL_NAME = "fastapi_codex_client_diagnostic_total"
CODEX_CLIENT_DIAGNOSTIC_TOTAL_DESCRIPTION = "Codex 客户端诊断处理结果总数"
CODEX_CLIENT_PERFORMANCE_SAMPLE_TOTAL_NAME = "fastapi_codex_client_performance_sample_total"
CODEX_CLIENT_PERFORMANCE_SAMPLE_TOTAL_DESCRIPTION = "Codex 客户端性能样本总数"
CODEX_CLIENT_PERFORMANCE_VALUE_NAME = "fastapi_codex_client_performance_value"
CODEX_CLIENT_PERFORMANCE_VALUE_DESCRIPTION = "Codex 客户端最新性能样本值"
REQUEST_METHOD_LABEL = "method"
REQUEST_PATH_LABEL = "path"
REQUEST_STATUS_CODE_LABEL = "status_code"
SECURITY_EVENT_TYPE_LABEL = "event_type"
SECURITY_EVENT_DECISION_LABEL = "decision"
SECURITY_EVENT_SEVERITY_LABEL = "severity"
LOG_BUFFER_REASON_LABEL = "reason"
LOG_BUFFER_FAILED_LABEL = "failed"
TASK_NAME_LABEL = "task_name"
TASK_OUTCOME_LABEL = "outcome"
SATURATION_RESOURCE_LABEL = "resource"
STREAM_TRANSPORT_LABEL = "transport"
STREAM_OUTCOME_LABEL = "outcome"
STREAM_REASON_LABEL = "reason"
STREAM_EVENT_KIND_LABEL = "event_kind"
CODEX_CLIENT_DIAGNOSTIC_SOURCE_LABEL = "source"
CODEX_CLIENT_DIAGNOSTIC_ERROR_CODE_LABEL = "error_code"
CODEX_CLIENT_DIAGNOSTIC_OUTCOME_LABEL = "outcome"
CODEX_CLIENT_PERFORMANCE_METRIC_LABEL = "metric"
CODEX_CLIENT_PERFORMANCE_OBSERVATION_LABEL = "observation"
READY_TRUE_VALUE = 1.0
READY_FALSE_VALUE = 0.0
BOOLEAN_LABEL_TRUE = "true"
BOOLEAN_LABEL_FALSE = "false"
SATURATION_RATIO_MINIMUM = 0.0
SATURATION_RATIO_MAXIMUM = 1.0
CONTENT_TYPE_SEPARATOR = ";"
UNKNOWN_REQUEST_PATH_LABEL = "unknown"
PATH_SEPARATOR = "/"
ROUTE_PARAMETER_START_MARK = "{"
ROUTE_PARAMETER_END_MARK = "}"
DYNAMIC_PATH_SEGMENT_PATTERN = re.compile(r"^\d+$|^[0-9a-fA-F]{8,}(-[0-9a-fA-F]{4,})*$")


class TaskExecutionMetricOutcome(StrEnum):
    """
    任务执行指标结果枚举。

    :cvar SUCCESS: 任务执行成功。
    :cvar FAILED: 任务执行失败。
    :cvar REJECTED: 任务分发被去重约束拒绝，复用既有执行记录。
    """

    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"


class RuntimeSaturationResource(StrEnum):
    """
    运行时饱和度资源枚举。

    :cvar REQUEST_THREAD_POOL: 同步请求卸载线程池。
    :cvar DB_POOL: 数据库连接池。
    :cvar TASK_QUEUE: 本地任务消息队列。
    :cvar LOG_BUFFER: 日志缓冲积压。
    """

    REQUEST_THREAD_POOL = "request_thread_pool"
    DB_POOL = "db_pool"
    TASK_QUEUE = "task_queue"
    LOG_BUFFER = "log_buffer"


class StreamMetricOutcome(StrEnum):
    """流式指标结果封闭集合。"""

    SUCCESS = "success"
    DISCONNECTED = "disconnected"
    REJECTED = "rejected"
    FAILED = "failed"


class StreamMetricEventKind(StrEnum):
    """Prometheus 允许使用的低基数流事件类型。"""

    STARTED = "stream_started"
    PROGRESS = "stream_progress"
    HEARTBEAT = "stream_heartbeat"
    COMPLETED = "stream_completed"
    FAULT = "stream_fault"
    BUSINESS = "business"

    @classmethod
    def resolve(cls, event_kind: str) -> StreamMetricEventKind:
        """把业务自定义事件归一化为固定 business 标签。"""

        try:
            return cls(event_kind)
        except ValueError:
            return cls.BUSINESS


class CodexClientDiagnosticMetricOutcome(StrEnum):
    """客户端诊断在服务端的处理结果，标签值保持低基数。"""

    RECORDED = "recorded"
    RATE_LIMITED = "rate_limited"


@dataclass(frozen=True, slots=True)
class HttpRequestMetric:
    """
    HTTP 请求指标数据。

    :ivar method: HTTP 方法。
    :vartype method: str
    :ivar path: 低基数路径模板。
    :vartype path: str
    :ivar status_code: HTTP 状态码。
    :vartype status_code: int
    :ivar duration_seconds: 请求耗时秒数。
    :vartype duration_seconds: float
    """

    method: str
    path: str
    status_code: int
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class RuntimeReadyMetric:
    """
    运行时 ready 指标数据。

    :ivar ready: 应用是否已进入 ready 状态。
    :vartype ready: bool
    """

    ready: bool


@dataclass(frozen=True, slots=True)
class SecurityEventMetric:
    """
    安全事件指标数据。

    :ivar event_type: 安全事件类型，取值限定在 ``SecurityEventType`` 白名单内。
    :vartype event_type: SecurityEventType
    :ivar decision: 安全事件决策。
    :vartype decision: SecurityEventDecision
    :ivar severity: 安全事件严重级别。
    :vartype severity: SecurityEventSeverity
    """

    event_type: SecurityEventType
    decision: SecurityEventDecision
    severity: SecurityEventSeverity


@dataclass(frozen=True, slots=True)
class LogBufferFlushMetric:
    """
    日志缓冲刷盘指标数据。

    :ivar reason: 刷盘触发原因，取值限定在 ``LogWriteReason`` 白名单内。
    :vartype reason: LogWriteReason
    :ivar failed: 本批次是否存在写入失败。
    :vartype failed: bool
    :ivar batch_size: 本批次事件数量。
    :vartype batch_size: int
    """

    reason: LogWriteReason
    failed: bool
    batch_size: int


@dataclass(frozen=True, slots=True)
class LogBufferPendingMetric:
    """
    日志缓冲积压指标数据。

    :ivar pending_items: 尚未完成落库的日志事件数量。
    :vartype pending_items: int
    """

    pending_items: int


@dataclass(frozen=True, slots=True)
class TaskExecutionMetric:
    """
    任务执行指标数据。

    :ivar task_name: 任务注册名（job_kind），来自任务注册中心的低基数集合。
    :vartype task_name: str
    :ivar outcome: 任务执行结果。
    :vartype outcome: TaskExecutionMetricOutcome
    """

    task_name: str
    outcome: TaskExecutionMetricOutcome


@dataclass(frozen=True, slots=True)
class RuntimeSaturationMetric:
    """
    运行时饱和度指标数据。

    :ivar resource: 有界资源标识。
    :vartype resource: RuntimeSaturationResource
    :ivar ratio: 饱和度比值，落点在 0 到 1 区间，超界值由注册器收敛。
    :vartype ratio: float
    """

    resource: RuntimeSaturationResource
    ratio: float


@dataclass(frozen=True, slots=True)
class StreamSessionMetric:
    """流会话指标数据。"""

    transport: StreamTransport
    outcome: StreamMetricOutcome
    reason: StreamCloseReason
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class StreamEventMetric:
    """流事件指标数据。"""

    transport: StreamTransport
    event_kind: StreamMetricEventKind
    byte_count: int


@dataclass(frozen=True, slots=True)
class StreamQueueSaturationMetric:
    """流会话队列饱和度指标数据。"""

    transport: StreamTransport
    ratio: float


@dataclass(frozen=True, slots=True)
class StreamResumeMetric:
    """有限恢复结果指标数据。"""

    transport: StreamTransport
    outcome: StreamMetricOutcome


@dataclass(frozen=True, slots=True)
class CodexClientDiagnosticMetric:
    """服务端二次脱敏后的 Codex 客户端诊断计数输入。"""

    source: CodexClientDiagnosticSource
    error_code: str
    outcome: CodexClientDiagnosticMetricOutcome


@dataclass(frozen=True, slots=True)
class CodexClientPerformanceMetricSample:
    """服务端已按封闭词表校验的客户端性能指标输入。"""

    metric: CodexClientPerformanceMetric
    observation: CodexClientPerformanceObservation
    value: float


@dataclass(frozen=True, slots=True)
class PrometheusMetricsRegistryOptions:
    """
    Prometheus 指标注册器开关选项。

    :ivar include_security_metrics: 是否注册安全事件指标。
    :vartype include_security_metrics: bool
    :ivar include_task_metrics: 是否注册任务执行指标。
    :vartype include_task_metrics: bool
    :ivar include_log_buffer_metrics: 是否注册日志缓冲指标。
    :vartype include_log_buffer_metrics: bool
    :ivar include_saturation_metrics: 是否注册运行时饱和度指标。
    :vartype include_saturation_metrics: bool
    """

    include_security_metrics: bool = True
    include_task_metrics: bool = True
    include_log_buffer_metrics: bool = True
    include_saturation_metrics: bool = True
    include_stream_metrics: bool = True
    include_codex_diagnostic_metrics: bool = True


class PrometheusMetricsRegistry:
    """
    Prometheus 指标注册器。
    """

    def __init__(self, *, options: PrometheusMetricsRegistryOptions | None = None) -> None:
        """
        初始化 Prometheus 指标注册器。

        :param options: 指标族注册开关；``None`` 时全部注册。
        :type options: PrometheusMetricsRegistryOptions | None
        :returns: 无返回值。
        :rtype: None
        """

        resolved_options = options if options is not None else PrometheusMetricsRegistryOptions()
        self._collector_registry = CollectorRegistry()
        self._request_total = Counter(
            REQUEST_TOTAL_NAME,
            REQUEST_TOTAL_DESCRIPTION,
            [
                REQUEST_METHOD_LABEL,
                REQUEST_PATH_LABEL,
                REQUEST_STATUS_CODE_LABEL,
            ],
            registry=self._collector_registry,
        )
        self._request_duration_seconds = Histogram(
            REQUEST_DURATION_SECONDS_NAME,
            REQUEST_DURATION_SECONDS_DESCRIPTION,
            [
                REQUEST_METHOD_LABEL,
                REQUEST_PATH_LABEL,
                REQUEST_STATUS_CODE_LABEL,
            ],
            registry=self._collector_registry,
        )
        self._runtime_ready = Gauge(
            RUNTIME_READY_NAME,
            RUNTIME_READY_DESCRIPTION,
            registry=self._collector_registry,
        )
        self._security_event_total: Counter | None = (
            Counter(
                SECURITY_EVENT_TOTAL_NAME,
                SECURITY_EVENT_TOTAL_DESCRIPTION,
                [
                    SECURITY_EVENT_TYPE_LABEL,
                    SECURITY_EVENT_DECISION_LABEL,
                    SECURITY_EVENT_SEVERITY_LABEL,
                ],
                registry=self._collector_registry,
            )
            if resolved_options.include_security_metrics
            else None
        )
        self._log_buffer_flush_total: Counter | None = (
            Counter(
                LOG_BUFFER_FLUSH_TOTAL_NAME,
                LOG_BUFFER_FLUSH_TOTAL_DESCRIPTION,
                [
                    LOG_BUFFER_REASON_LABEL,
                    LOG_BUFFER_FAILED_LABEL,
                ],
                registry=self._collector_registry,
            )
            if resolved_options.include_log_buffer_metrics
            else None
        )
        self._log_buffer_pending_items: Gauge | None = (
            Gauge(
                LOG_BUFFER_PENDING_ITEMS_NAME,
                LOG_BUFFER_PENDING_ITEMS_DESCRIPTION,
                registry=self._collector_registry,
            )
            if resolved_options.include_log_buffer_metrics
            else None
        )
        self._task_execution_total: Counter | None = (
            Counter(
                TASK_EXECUTION_TOTAL_NAME,
                TASK_EXECUTION_TOTAL_DESCRIPTION,
                [
                    TASK_NAME_LABEL,
                    TASK_OUTCOME_LABEL,
                ],
                registry=self._collector_registry,
            )
            if resolved_options.include_task_metrics
            else None
        )
        self._runtime_saturation_ratio: Gauge | None = (
            Gauge(
                RUNTIME_SATURATION_RATIO_NAME,
                RUNTIME_SATURATION_RATIO_DESCRIPTION,
                [SATURATION_RESOURCE_LABEL],
                registry=self._collector_registry,
            )
            if resolved_options.include_saturation_metrics
            else None
        )
        self._stream_active_sessions: Gauge | None = (
            Gauge(
                STREAM_ACTIVE_SESSIONS_NAME,
                STREAM_ACTIVE_SESSIONS_DESCRIPTION,
                [STREAM_TRANSPORT_LABEL],
                registry=self._collector_registry,
            )
            if resolved_options.include_stream_metrics
            else None
        )
        self._stream_session_total: Counter | None = (
            Counter(
                STREAM_SESSION_TOTAL_NAME,
                STREAM_SESSION_TOTAL_DESCRIPTION,
                [STREAM_TRANSPORT_LABEL, STREAM_OUTCOME_LABEL, STREAM_REASON_LABEL],
                registry=self._collector_registry,
            )
            if resolved_options.include_stream_metrics
            else None
        )
        self._stream_session_duration_seconds: Histogram | None = (
            Histogram(
                STREAM_SESSION_DURATION_SECONDS_NAME,
                STREAM_SESSION_DURATION_SECONDS_DESCRIPTION,
                [STREAM_TRANSPORT_LABEL, STREAM_OUTCOME_LABEL, STREAM_REASON_LABEL],
                registry=self._collector_registry,
            )
            if resolved_options.include_stream_metrics
            else None
        )
        self._stream_event_total: Counter | None = (
            Counter(
                STREAM_EVENT_TOTAL_NAME,
                STREAM_EVENT_TOTAL_DESCRIPTION,
                [STREAM_TRANSPORT_LABEL, STREAM_EVENT_KIND_LABEL],
                registry=self._collector_registry,
            )
            if resolved_options.include_stream_metrics
            else None
        )
        self._stream_event_bytes: Counter | None = (
            Counter(
                STREAM_EVENT_BYTES_NAME,
                STREAM_EVENT_BYTES_DESCRIPTION,
                [STREAM_TRANSPORT_LABEL, STREAM_EVENT_KIND_LABEL],
                registry=self._collector_registry,
            )
            if resolved_options.include_stream_metrics
            else None
        )
        self._stream_queue_saturation: Gauge | None = (
            Gauge(
                STREAM_QUEUE_SATURATION_NAME,
                STREAM_QUEUE_SATURATION_DESCRIPTION,
                [STREAM_TRANSPORT_LABEL],
                registry=self._collector_registry,
            )
            if resolved_options.include_stream_metrics
            else None
        )
        self._stream_resume_total: Counter | None = (
            Counter(
                STREAM_RESUME_TOTAL_NAME,
                STREAM_RESUME_TOTAL_DESCRIPTION,
                [STREAM_TRANSPORT_LABEL, STREAM_OUTCOME_LABEL],
                registry=self._collector_registry,
            )
            if resolved_options.include_stream_metrics
            else None
        )
        self._codex_client_diagnostic_total: Counter | None = (
            Counter(
                CODEX_CLIENT_DIAGNOSTIC_TOTAL_NAME,
                CODEX_CLIENT_DIAGNOSTIC_TOTAL_DESCRIPTION,
                [
                    CODEX_CLIENT_DIAGNOSTIC_SOURCE_LABEL,
                    CODEX_CLIENT_DIAGNOSTIC_ERROR_CODE_LABEL,
                    CODEX_CLIENT_DIAGNOSTIC_OUTCOME_LABEL,
                ],
                registry=self._collector_registry,
            )
            if resolved_options.include_codex_diagnostic_metrics
            else None
        )
        self._codex_client_performance_sample_total: Counter | None = (
            Counter(
                CODEX_CLIENT_PERFORMANCE_SAMPLE_TOTAL_NAME,
                CODEX_CLIENT_PERFORMANCE_SAMPLE_TOTAL_DESCRIPTION,
                [
                    CODEX_CLIENT_PERFORMANCE_METRIC_LABEL,
                    CODEX_CLIENT_PERFORMANCE_OBSERVATION_LABEL,
                ],
                registry=self._collector_registry,
            )
            if resolved_options.include_codex_diagnostic_metrics
            else None
        )
        self._codex_client_performance_value: Gauge | None = (
            Gauge(
                CODEX_CLIENT_PERFORMANCE_VALUE_NAME,
                CODEX_CLIENT_PERFORMANCE_VALUE_DESCRIPTION,
                [
                    CODEX_CLIENT_PERFORMANCE_METRIC_LABEL,
                    CODEX_CLIENT_PERFORMANCE_OBSERVATION_LABEL,
                ],
                registry=self._collector_registry,
            )
            if resolved_options.include_codex_diagnostic_metrics
            else None
        )

    def record_http_request(self, metric: HttpRequestMetric) -> None:
        """
        记录 HTTP 请求指标。

        :param metric: HTTP 请求指标数据。
        :type metric: HttpRequestMetric
        :returns: 无返回值。
        :rtype: None
        """

        status_code = str(metric.status_code)
        method = metric.method.upper()
        path = self._normalize_path_label(metric.path)
        self._request_total.labels(
            method=method,
            path=path,
            status_code=status_code,
        ).inc()
        self._request_duration_seconds.labels(
            method=method,
            path=path,
            status_code=status_code,
        ).observe(metric.duration_seconds)

    def record_security_event(self, metric: SecurityEventMetric) -> None:
        """
        记录安全事件指标。

        :param metric: 安全事件指标数据，标签值全部来自封闭枚举白名单。
        :type metric: SecurityEventMetric
        :returns: 无返回值。
        :rtype: None
        """

        if self._security_event_total is None:
            return
        self._security_event_total.labels(
            event_type=metric.event_type.value,
            decision=metric.decision.value,
            severity=metric.severity.value,
        ).inc()

    def record_log_buffer_flush(self, metric: LogBufferFlushMetric) -> None:
        """
        记录日志缓冲刷盘指标。

        :param metric: 日志缓冲刷盘指标数据，按本批次事件数量累加。
        :type metric: LogBufferFlushMetric
        :returns: 无返回值。
        :rtype: None
        """

        if self._log_buffer_flush_total is None:
            return
        self._log_buffer_flush_total.labels(
            reason=metric.reason.value,
            failed=BOOLEAN_LABEL_TRUE if metric.failed else BOOLEAN_LABEL_FALSE,
        ).inc(metric.batch_size)

    def set_log_buffer_pending_items(self, metric: LogBufferPendingMetric) -> None:
        """
        设置日志缓冲积压指标。

        :param metric: 日志缓冲积压指标数据。
        :type metric: LogBufferPendingMetric
        :returns: 无返回值。
        :rtype: None
        """

        if self._log_buffer_pending_items is None:
            return
        self._log_buffer_pending_items.set(metric.pending_items)

    def record_task_execution(self, metric: TaskExecutionMetric) -> None:
        """
        记录任务执行指标。

        :param metric: 任务执行指标数据，``task_name`` 为任务注册名。
        :type metric: TaskExecutionMetric
        :returns: 无返回值。
        :rtype: None
        """

        if self._task_execution_total is None:
            return
        self._task_execution_total.labels(
            task_name=metric.task_name,
            outcome=metric.outcome.value,
        ).inc()

    def set_runtime_saturation(self, metric: RuntimeSaturationMetric) -> None:
        """
        设置运行时饱和度指标。

        :param metric: 运行时饱和度指标数据，比值超界时收敛到 0-1 区间。
        :type metric: RuntimeSaturationMetric
        :returns: 无返回值。
        :rtype: None
        """

        if self._runtime_saturation_ratio is None:
            return
        clamped_ratio = min(
            max(metric.ratio, SATURATION_RATIO_MINIMUM),
            SATURATION_RATIO_MAXIMUM,
        )
        self._runtime_saturation_ratio.labels(resource=metric.resource.value).set(clamped_ratio)

    def set_stream_active_sessions(self, *, transport: StreamTransport, count: int) -> None:
        """设置指定传输的活跃流会话数。"""

        if self._stream_active_sessions is None:
            return
        self._stream_active_sessions.labels(transport=transport.value).set(max(0, count))

    def record_stream_session(self, metric: StreamSessionMetric) -> None:
        """记录低基数流会话结果与耗时。"""

        if self._stream_session_total is None or self._stream_session_duration_seconds is None:
            return
        labels = {
            STREAM_TRANSPORT_LABEL: metric.transport.value,
            STREAM_OUTCOME_LABEL: metric.outcome.value,
            STREAM_REASON_LABEL: metric.reason.value,
        }
        self._stream_session_total.labels(**labels).inc()
        self._stream_session_duration_seconds.labels(**labels).observe(metric.duration_seconds)

    def record_stream_event(self, metric: StreamEventMetric) -> None:
        """记录受控类型的事件数量与字节。"""

        if self._stream_event_total is None or self._stream_event_bytes is None:
            return
        labels = {
            STREAM_TRANSPORT_LABEL: metric.transport.value,
            STREAM_EVENT_KIND_LABEL: metric.event_kind.value,
        }
        self._stream_event_total.labels(**labels).inc()
        self._stream_event_bytes.labels(**labels).inc(max(0, metric.byte_count))

    def set_stream_queue_saturation(self, metric: StreamQueueSaturationMetric) -> None:
        """设置指定传输的队列饱和度。"""

        if self._stream_queue_saturation is None:
            return
        ratio = min(max(metric.ratio, SATURATION_RATIO_MINIMUM), SATURATION_RATIO_MAXIMUM)
        self._stream_queue_saturation.labels(transport=metric.transport.value).set(ratio)

    def record_stream_resume(self, metric: StreamResumeMetric) -> None:
        """记录有限恢复成功或拒绝结果。"""

        if self._stream_resume_total is None:
            return
        self._stream_resume_total.labels(
            transport=metric.transport.value,
            outcome=metric.outcome.value,
        ).inc()

    def record_codex_client_diagnostic(self, metric: CodexClientDiagnosticMetric) -> None:
        """记录已被服务端白名单收敛的客户端诊断结果。"""

        if self._codex_client_diagnostic_total is None:
            return
        self._codex_client_diagnostic_total.labels(
            source=metric.source.value,
            error_code=metric.error_code,
            outcome=metric.outcome.value,
        ).inc()

    def record_codex_client_performance(
        self,
        sample: CodexClientPerformanceMetricSample,
    ) -> None:
        """记录封闭性能样本的计数和最新值，禁止将用户输入作为标签。"""

        if (
            self._codex_client_performance_sample_total is None
            or self._codex_client_performance_value is None
        ):
            return
        labels = {
            CODEX_CLIENT_PERFORMANCE_METRIC_LABEL: sample.metric.value,
            CODEX_CLIENT_PERFORMANCE_OBSERVATION_LABEL: sample.observation.value,
        }
        self._codex_client_performance_sample_total.labels(**labels).inc()
        self._codex_client_performance_value.labels(**labels).set(sample.value)

    def _normalize_path_label(self, path: str) -> str:
        """
        归一化 HTTP 指标路径标签。

        :param path: 原始路径或路由模板。
        :type path: str
        :returns: 低基数路径标签。
        :rtype: str
        """

        normalized_path = path.strip()
        if normalized_path == "" or not normalized_path.startswith(PATH_SEPARATOR):
            return UNKNOWN_REQUEST_PATH_LABEL
        if (
            ROUTE_PARAMETER_START_MARK in normalized_path
            and ROUTE_PARAMETER_END_MARK in normalized_path
        ):
            return normalized_path
        segments = [segment for segment in normalized_path.split(PATH_SEPARATOR) if segment != ""]
        if any(DYNAMIC_PATH_SEGMENT_PATTERN.fullmatch(segment) is not None for segment in segments):
            return UNKNOWN_REQUEST_PATH_LABEL
        return normalized_path

    def set_runtime_ready(self, metric: RuntimeReadyMetric) -> None:
        """
        设置运行时 ready 指标。

        :param metric: 运行时 ready 指标数据。
        :type metric: RuntimeReadyMetric
        :returns: 无返回值。
        :rtype: None
        """

        self._runtime_ready.set(READY_TRUE_VALUE if metric.ready else READY_FALSE_VALUE)

    def render(self) -> bytes:
        """
        渲染 Prometheus 文本指标。

        :returns: Prometheus 文本指标字节串。
        :rtype: bytes
        """

        return generate_latest(self._collector_registry)

    def get_content_type(self) -> str:
        """
        获取 Prometheus 指标响应内容类型。

        :returns: 内容类型。
        :rtype: str
        """

        return CONTENT_TYPE_LATEST.split(CONTENT_TYPE_SEPARATOR)[0]
