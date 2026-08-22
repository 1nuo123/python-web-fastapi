"""Codex 客户端性能样本的安全记录实现。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from src.application.ports.codex_client_performance_recorder_port import (
    CodexClientPerformanceRecorderPort,
)
from src.core.codex_contract.client_performance_contract import (
    CODEX_CLIENT_PERFORMANCE_METRIC_DEFINITIONS,
    CodexClientPerformanceEnvelope,
    CodexClientPerformanceMetric,
    CodexClientPerformanceObservation,
    CodexClientPerformanceReceipt,
    CodexClientPerformanceSource,
    CodexClientPerformanceUnit,
)
from src.core.logging_contract.log_event_contract import (
    CodexClientPerformanceLogDetail,
    LogEventEnvelope,
    LogEventHeader,
    LogEventKind,
    LogLevel,
)
from src.infrastructure.observability.prometheus_metrics_registry import (
    CodexClientPerformanceMetricSample,
    PrometheusMetricsRegistry,
)

CODEX_CLIENT_PERFORMANCE_LOG_MESSAGE = (
    "Codex客户端性能 source=%s metric=%s observation=%s unit=%s value=%s"
)
CODEX_CLIENT_PERFORMANCE_LOG_MESSAGE_TEXT = "Codex客户端性能"
CODEX_CLIENT_PERFORMANCE_SOURCE_MODULE = "infrastructure"
CODEX_CLIENT_PERFORMANCE_SOURCE_COMPONENT = "codex_client_performance_recorder"


@dataclass(frozen=True, slots=True)
class SafeCodexClientPerformanceRecord:
    """允许进入结构化日志和 Prometheus 的低基数性能样本。"""

    source: CodexClientPerformanceSource
    metric: CodexClientPerformanceMetric
    observation: CodexClientPerformanceObservation
    unit: CodexClientPerformanceUnit
    value: float


class CodexClientPerformanceRecorder(CodexClientPerformanceRecorderPort):
    """从封闭词表重建性能样本并写入现有日志与指标链路。"""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        log_event_emitter: Callable[[LogEventEnvelope], None] | None = None,
        metrics_registry_provider: Callable[[], PrometheusMetricsRegistry | None] | None = None,
    ) -> None:
        """
        初始化性能样本记录器。

        调用方事件标识与发生时间仅用于 HTTP 契约，不进入日志、指标或存储。所有可以
        标识用户、会话、线程、URL、正文或异常的字段都不在性能模型中。

        :param logger: 已配置脱敏格式化器的应用日志器。
        :type logger: logging.Logger
        :param log_event_emitter: 既有结构化日志缓冲入口；不可用时使用同样字段的受限日志兜底。
        :type log_event_emitter: Callable[[LogEventEnvelope], None] | None
        :param metrics_registry_provider: 延迟读取 Prometheus 注册器，避免装配顺序影响旁路采集。
        :type metrics_registry_provider: Callable[[], PrometheusMetricsRegistry | None] | None
        """

        self._logger = logger
        self._log_event_emitter = log_event_emitter
        self._metrics_registry_provider = metrics_registry_provider

    def record(
        self,
        *,
        envelope: CodexClientPerformanceEnvelope,
    ) -> CodexClientPerformanceReceipt:
        """
        重建后记录一条严格受限的性能样本。

        :param envelope: 已完成 Pydantic 词表、单位和数值范围校验的性能信封。
        :type envelope: CodexClientPerformanceEnvelope
        :returns: 总是确认当前实例已将安全样本交给日志和指标旁路。
        :rtype: CodexClientPerformanceReceipt
        """

        safe_record = self._build_safe_record(envelope)
        self._emit_safe_record(safe_record)
        self._record_metric(safe_record)
        return CodexClientPerformanceReceipt(recorded=True)

    def _build_safe_record(
        self,
        envelope: CodexClientPerformanceEnvelope,
    ) -> SafeCodexClientPerformanceRecord:
        """从核心词表重建来源和单位，不信任调用方的派生上下文。"""

        definition = CODEX_CLIENT_PERFORMANCE_METRIC_DEFINITIONS[envelope.detail.metric]
        return SafeCodexClientPerformanceRecord(
            source=definition.source,
            metric=envelope.detail.metric,
            observation=envelope.detail.observation,
            unit=definition.unit,
            value=envelope.detail.value,
        )

    def _emit_safe_record(self, safe_record: SafeCodexClientPerformanceRecord) -> None:
        """优先写入结构化日志链路，确保 30 天清理器可按固定详情类型删除。"""

        if self._log_event_emitter is not None:
            self._log_event_emitter(
                LogEventEnvelope(
                    header=LogEventHeader(
                        event_id=str(uuid4()),
                        occurred_at=datetime.now(UTC),
                        level=LogLevel.INFO,
                        kind=LogEventKind.CODEX_CLIENT_PERFORMANCE,
                        message=CODEX_CLIENT_PERFORMANCE_LOG_MESSAGE_TEXT,
                        source_module=CODEX_CLIENT_PERFORMANCE_SOURCE_MODULE,
                        source_component=CODEX_CLIENT_PERFORMANCE_SOURCE_COMPONENT,
                    ),
                    detail=CodexClientPerformanceLogDetail(
                        source=safe_record.source,
                        metric=safe_record.metric,
                        observation=safe_record.observation,
                        unit=safe_record.unit,
                        value=safe_record.value,
                    ),
                )
            )
            return
        self._logger.info(
            CODEX_CLIENT_PERFORMANCE_LOG_MESSAGE,
            safe_record.source.value,
            safe_record.metric.value,
            safe_record.observation.value,
            safe_record.unit.value,
            safe_record.value,
        )

    def _record_metric(self, safe_record: SafeCodexClientPerformanceRecord) -> None:
        """只将服务端词表中的指标、观测和数值交给 Prometheus。"""

        if self._metrics_registry_provider is None:
            return
        metrics_registry = self._metrics_registry_provider()
        if metrics_registry is None:
            return
        metrics_registry.record_codex_client_performance(
            CodexClientPerformanceMetricSample(
                metric=safe_record.metric,
                observation=safe_record.observation,
                value=safe_record.value,
            )
        )
