"""流执行编排器的 Prometheus 观测适配器。"""

from __future__ import annotations

from src.application.streaming.stream_execution_orchestrator import (
    StreamQueueSaturationObserverPort,
)
from src.core.stream_contract.stream_event_contract import StreamTransport
from src.infrastructure.observability.prometheus_metrics_registry import (
    PrometheusMetricsRegistry,
    StreamQueueSaturationMetric,
)


class PrometheusStreamQueueSaturationObserver(StreamQueueSaturationObserverPort):
    """把应用队列饱和度写入低基数 Prometheus 指标。"""

    def __init__(self, *, registry: PrometheusMetricsRegistry) -> None:
        """初始化 Prometheus 指标注册器。"""

        self._registry = registry

    def record(self, *, transport: StreamTransport, ratio: float) -> None:
        """记录指定传输的队列饱和度。"""

        self._registry.set_stream_queue_saturation(
            StreamQueueSaturationMetric(transport=transport, ratio=ratio)
        )
