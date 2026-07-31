"""流式 Prometheus 指标单元测试。"""

from __future__ import annotations

from src.core.stream_contract.stream_event_contract import StreamCloseReason, StreamTransport
from src.infrastructure.observability.prometheus_metrics_registry import (
    STREAM_ACTIVE_SESSIONS_NAME,
    STREAM_EVENT_BYTES_NAME,
    STREAM_EVENT_TOTAL_NAME,
    STREAM_QUEUE_SATURATION_NAME,
    STREAM_SESSION_TOTAL_NAME,
    PrometheusMetricsRegistry,
    StreamEventMetric,
    StreamMetricEventKind,
    StreamMetricOutcome,
    StreamQueueSaturationMetric,
    StreamSessionMetric,
)


class TestStreamMetricsUnit:
    """流式 Prometheus 指标单元测试集合。"""

    def test_stream_metrics_should_render_only_low_cardinality_labels(self) -> None:
        """验证流会话、事件与队列指标使用受控标签。"""

        registry = PrometheusMetricsRegistry()
        registry.set_stream_active_sessions(transport=StreamTransport.SSE, count=2)
        registry.record_stream_session(
            StreamSessionMetric(
                transport=StreamTransport.SSE,
                outcome=StreamMetricOutcome.SUCCESS,
                reason=StreamCloseReason.COMPLETED,
                duration_seconds=0.1,
            )
        )
        registry.record_stream_event(
            StreamEventMetric(
                transport=StreamTransport.SSE,
                event_kind=StreamMetricEventKind.COMPLETED,
                byte_count=128,
            )
        )
        registry.set_stream_queue_saturation(
            StreamQueueSaturationMetric(
                transport=StreamTransport.SSE,
                ratio=1.5,
            )
        )

        metrics_text = registry.render().decode()

        assert STREAM_ACTIVE_SESSIONS_NAME in metrics_text
        assert STREAM_SESSION_TOTAL_NAME in metrics_text
        assert STREAM_EVENT_TOTAL_NAME in metrics_text
        assert STREAM_EVENT_BYTES_NAME in metrics_text
        assert STREAM_QUEUE_SATURATION_NAME in metrics_text
        assert "stream_id" not in metrics_text
