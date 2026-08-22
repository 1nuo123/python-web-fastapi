"""Codex 客户端性能记录器的隔离单元测试。"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import Mock

from src.core.codex_contract.client_performance_contract import (
    CodexClientPerformanceDetail,
    CodexClientPerformanceEnvelope,
    CodexClientPerformanceHeader,
    CodexClientPerformanceMetric,
    CodexClientPerformanceObservation,
    CodexClientPerformanceUnit,
)
from src.core.logging_contract.log_event_contract import LogEventEnvelope
from src.infrastructure.codex.codex_client_performance_recorder import (
    CodexClientPerformanceRecorder,
)
from src.infrastructure.observability.prometheus_metrics_registry import (
    PrometheusMetricsRegistry,
)


def build_envelope() -> CodexClientPerformanceEnvelope:
    """构建一个不包含调用方身份或自由文本的性能信封。"""

    return CodexClientPerformanceEnvelope(
        header=CodexClientPerformanceHeader(
            event_id="performance-recorder-test",
            occurred_at=datetime(2026, 8, 19, tzinfo=UTC),
        ),
        detail=CodexClientPerformanceDetail(
            metric=CodexClientPerformanceMetric.APPROXIMATE_FPS,
            observation=CodexClientPerformanceObservation.OBSERVED,
            unit=CodexClientPerformanceUnit.FRAMES_PER_SECOND,
            value=58.0,
        ),
    )


def test_record_should_emit_rebuilt_structured_log_without_caller_identity() -> None:
    """结构化样本只包含服务端词表字段，不保留事件 ID 或发生时间。"""

    logger = Mock(spec=logging.Logger)
    events: list[LogEventEnvelope] = []
    recorder = CodexClientPerformanceRecorder(
        logger=logger,
        log_event_emitter=events.append,
    )

    receipt = recorder.record(envelope=build_envelope())

    assert receipt.recorded
    assert len(events) == 1
    event = events[0]
    assert event.detail.metric is CodexClientPerformanceMetric.APPROXIMATE_FPS
    assert event.detail.observation is CodexClientPerformanceObservation.OBSERVED
    assert event.detail.value == 58.0
    assert event.header.authenticated_subject_id is None
    assert "performance-recorder-test" not in str(event)
    logger.info.assert_not_called()


def test_record_should_write_low_cardinality_prometheus_sample() -> None:
    """指标只以固定测量和观测作为标签，数值不进入标签。"""

    metrics_registry = PrometheusMetricsRegistry()
    recorder = CodexClientPerformanceRecorder(
        logger=Mock(spec=logging.Logger),
        metrics_registry_provider=lambda: metrics_registry,
    )

    receipt = recorder.record(envelope=build_envelope())
    metrics_text = metrics_registry.render().decode()

    assert receipt.recorded
    assert 'metric="approximate_fps",observation="observed"' in metrics_text
    assert "58.0" in metrics_text
