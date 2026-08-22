"""Codex 客户端诊断的进程内限流与安全日志记录实现。"""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from time import monotonic
from uuid import uuid4

from src.application.ports.codex_client_diagnostic_recorder_port import (
    CodexClientDiagnosticRecorderPort,
)
from src.core.codex_contract.client_diagnostic_contract import (
    CodexClientDiagnosticEnvelope,
    CodexClientDiagnosticReceipt,
    CodexClientDiagnosticSource,
    CodexClientDiagnosticSummary,
)
from src.core.logging_contract.log_event_contract import (
    CodexClientDiagnosticLogDetail,
    LogEventEnvelope,
    LogEventHeader,
    LogEventKind,
    LogLevel,
)
from src.infrastructure.observability.prometheus_metrics_registry import (
    CodexClientDiagnosticMetric,
    CodexClientDiagnosticMetricOutcome,
    PrometheusMetricsRegistry,
)

CODEX_CLIENT_DIAGNOSTIC_RATE_LIMIT_PER_MINUTE = 20
CODEX_CLIENT_DIAGNOSTIC_RATE_LIMIT_WINDOW_SECONDS = 60.0
CODEX_CLIENT_DIAGNOSTIC_MAXIMUM_ACTIVE_BUCKETS = 4096
CODEX_CLIENT_DIAGNOSTIC_FALLBACK_CODE = "client.runtime.unclassified"
CODEX_CLIENT_DIAGNOSTIC_LOG_MESSAGE = "Codex客户端诊断 source=%s summary=%s code=%s fingerprint=%s"
CODEX_CLIENT_DIAGNOSTIC_LOG_MESSAGE_TEXT = "Codex客户端诊断"
CODEX_CLIENT_DIAGNOSTIC_SOURCE_MODULE = "infrastructure"
CODEX_CLIENT_DIAGNOSTIC_SOURCE_COMPONENT = "codex_client_diagnostic_recorder"
KNOWN_CODEX_CLIENT_DIAGNOSTIC_CODES = frozenset(
    {
        CODEX_CLIENT_DIAGNOSTIC_FALLBACK_CODE,
        "client.vue.render_failed",
        "client.vue.runtime_failed",
        "client.window.error",
        "codex.timeline.item_render_failed",
    }
)
SUMMARY_BY_SOURCE = {
    CodexClientDiagnosticSource.VUE: CodexClientDiagnosticSummary.VUE_ERROR,
    CodexClientDiagnosticSource.WINDOW: CodexClientDiagnosticSummary.WINDOW_ERROR,
    CodexClientDiagnosticSource.PROMISE: CodexClientDiagnosticSummary.PROMISE_REJECTION,
    CodexClientDiagnosticSource.REQUEST: CodexClientDiagnosticSummary.REQUEST_FAILURE,
    CodexClientDiagnosticSource.MANUAL: CodexClientDiagnosticSummary.MANUAL_CAPTURE,
}


@dataclass(frozen=True, slots=True)
class SafeCodexClientDiagnosticRecord:
    """允许进入日志与限流器的低基数客户端诊断字段。"""

    source: CodexClientDiagnosticSource
    summary: CodexClientDiagnosticSummary
    error_code: str
    fingerprint: str


class CodexClientDiagnosticRecorder(CodexClientDiagnosticRecorderPort):
    """二次收敛诊断字段并按主体和指纹执行进程内固定窗口限流。"""

    def __init__(
        self,
        *,
        logger: logging.Logger,
        clock: Callable[[], float] = monotonic,
        log_event_emitter: Callable[[LogEventEnvelope], None] | None = None,
        metrics_registry_provider: Callable[[], PrometheusMetricsRegistry | None] | None = None,
    ) -> None:
        """
        初始化诊断记录器。

        主体标识只保留在短生命周期内存限流键中，绝不写入日志或回执。时钟可注入，
        以便边界测试不依赖真实时间。

        :param logger: 已配置脱敏格式化器的应用日志器。
        :type logger: logging.Logger
        :param clock: 返回单调秒数的时间源。
        :type clock: Callable[[], float]
        :param log_event_emitter: 既有结构化日志缓冲的事件入口；未装配时使用受限标准日志兜底。
        :type log_event_emitter: Callable[[LogEventEnvelope], None] | None
        :param metrics_registry_provider: 延迟读取可选 Prometheus 指标注册器的入口，避免应用装配顺序影响采集。
        :type metrics_registry_provider: Callable[[], PrometheusMetricsRegistry | None] | None
        """

        self._logger = logger
        self._clock = clock
        self._log_event_emitter = log_event_emitter
        self._metrics_registry_provider = metrics_registry_provider
        self._lock = Lock()
        self._buckets: dict[tuple[str, str], deque[float]] = {}

    def record(
        self,
        *,
        owner_subject_id: str,
        envelope: CodexClientDiagnosticEnvelope,
    ) -> CodexClientDiagnosticReceipt:
        """
        记录服务端二次脱敏后的诊断安全字段。

        输入中的事件标识、发生时间、摘要和指纹都不直接记录：事件标识和时间仅用于
        HTTP 契约，摘要按来源重建，未知错误码降级，指纹由来源和错误码重新派生。
        这样路径、URL、异常、header、body 和主体标识均无法进入日志。

        :param owner_subject_id: 当前认证主体，仅参与内存限流键。
        :type owner_subject_id: str
        :param envelope: 已由 Pydantic 校验的客户端诊断信封。
        :type envelope: CodexClientDiagnosticEnvelope
        :returns: 记录成功或被限流/容量保护抑制的无敏感回执。
        :rtype: CodexClientDiagnosticReceipt
        """

        safe_record = self._build_safe_record(envelope)
        if not self._allows(
            owner_subject_id=owner_subject_id,
            fingerprint=safe_record.fingerprint,
        ):
            self._record_metric(
                safe_record,
                outcome=CodexClientDiagnosticMetricOutcome.RATE_LIMITED,
            )
            return CodexClientDiagnosticReceipt(recorded=False)
        self._emit_safe_record(safe_record)
        self._record_metric(
            safe_record,
            outcome=CodexClientDiagnosticMetricOutcome.RECORDED,
        )
        return CodexClientDiagnosticReceipt(recorded=True)

    def _emit_safe_record(self, safe_record: SafeCodexClientDiagnosticRecord) -> None:
        """优先交给既有结构化日志链路，未装配时保留同样字段的受限日志兜底。"""

        if self._log_event_emitter is not None:
            self._log_event_emitter(
                LogEventEnvelope(
                    header=LogEventHeader(
                        event_id=str(uuid4()),
                        occurred_at=datetime.now(UTC),
                        level=LogLevel.WARNING,
                        kind=LogEventKind.CODEX_CLIENT_DIAGNOSTIC,
                        message=CODEX_CLIENT_DIAGNOSTIC_LOG_MESSAGE_TEXT,
                        source_module=CODEX_CLIENT_DIAGNOSTIC_SOURCE_MODULE,
                        source_component=CODEX_CLIENT_DIAGNOSTIC_SOURCE_COMPONENT,
                    ),
                    detail=CodexClientDiagnosticLogDetail(
                        source=safe_record.source,
                        summary=safe_record.summary,
                        error_code=safe_record.error_code,
                        fingerprint=safe_record.fingerprint,
                    ),
                )
            )
            return
        self._logger.warning(
            CODEX_CLIENT_DIAGNOSTIC_LOG_MESSAGE,
            safe_record.source.value,
            safe_record.summary.value,
            safe_record.error_code,
            safe_record.fingerprint,
        )

    def _record_metric(
        self,
        safe_record: SafeCodexClientDiagnosticRecord,
        *,
        outcome: CodexClientDiagnosticMetricOutcome,
    ) -> None:
        """只以服务端重建后的封闭字段写入诊断计数，避免用户输入成为标签。"""

        if self._metrics_registry_provider is None:
            return
        metrics_registry = self._metrics_registry_provider()
        if metrics_registry is None:
            return
        metrics_registry.record_codex_client_diagnostic(
            CodexClientDiagnosticMetric(
                source=safe_record.source,
                error_code=safe_record.error_code,
                outcome=outcome,
            )
        )

    def _build_safe_record(
        self,
        envelope: CodexClientDiagnosticEnvelope,
    ) -> SafeCodexClientDiagnosticRecord:
        """从类型化输入重建可记录字段，拒绝调用方提供的自由派生值。"""

        source = envelope.header.source
        error_code = (
            envelope.detail.error_code
            if envelope.detail.error_code in KNOWN_CODEX_CLIENT_DIAGNOSTIC_CODES
            else CODEX_CLIENT_DIAGNOSTIC_FALLBACK_CODE
        )
        return SafeCodexClientDiagnosticRecord(
            source=source,
            summary=SUMMARY_BY_SOURCE[source],
            error_code=error_code,
            fingerprint=f"{source.value}:{error_code}",
        )

    def _allows(self, *, owner_subject_id: str, fingerprint: str) -> bool:
        """在锁内维护固定一分钟窗口，防止并发请求突破同一配额。"""

        now = self._clock()
        key = (owner_subject_id, fingerprint)
        with self._lock:
            self._prune_expired_buckets(now)
            bucket = self._buckets.get(key)
            if bucket is None:
                if len(self._buckets) >= CODEX_CLIENT_DIAGNOSTIC_MAXIMUM_ACTIVE_BUCKETS:
                    return False
                bucket = deque()
                self._buckets[key] = bucket
            if len(bucket) >= CODEX_CLIENT_DIAGNOSTIC_RATE_LIMIT_PER_MINUTE:
                return False
            bucket.append(now)
            return True

    def _prune_expired_buckets(self, now: float) -> None:
        """释放过期窗口，确保主体标识不会在内存中无限保留。"""

        for key, bucket in tuple(self._buckets.items()):
            while bucket and now - bucket[0] >= CODEX_CLIENT_DIAGNOSTIC_RATE_LIMIT_WINDOW_SECONDS:
                bucket.popleft()
            if not bucket:
                del self._buckets[key]
