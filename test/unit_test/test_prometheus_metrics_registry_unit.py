"""
Prometheus 指标注册器单元测试模块。
"""

from __future__ import annotations

from src.infrastructure.observability.prometheus_metrics_registry import (
    UNKNOWN_REQUEST_PATH_LABEL,
    HttpRequestMetric,
    PrometheusMetricsRegistry,
    RuntimeReadyMetric,
)

HEALTH_LIVE_PATH = "/health/live"
USER_NUMERIC_PATH = "/users/123"
ITEM_UUID_PATH = "/items/123e4567-e89b-12d3-a456-426614174000"
BLOB_HEX_PATH = "/blob/abcdef1234567890"
HTTP_GET_METHOD = "GET"
HTTP_STATUS_OK = 200
REQUEST_DURATION_SECONDS = 0.01
REQUEST_TOTAL_METRIC_NAME = "fastapi_request_total"
REQUEST_DURATION_METRIC_NAME = "fastapi_request_duration_seconds"
RUNTIME_READY_METRIC_NAME = "fastapi_runtime_ready"
CONTENT_TYPE_TEXT = "text/plain"


class TestPrometheusMetricsRegistryUnit:
    """
    Prometheus 指标注册器单元测试集合。
    """

    def test_render_should_include_http_and_runtime_metrics(self) -> None:
        """
        验证渲染结果应包含 HTTP 与运行时指标。
        """

        registry = PrometheusMetricsRegistry()
        registry.record_http_request(
            HttpRequestMetric(
                method=HTTP_GET_METHOD,
                path=HEALTH_LIVE_PATH,
                status_code=HTTP_STATUS_OK,
                duration_seconds=REQUEST_DURATION_SECONDS,
            )
        )
        registry.set_runtime_ready(RuntimeReadyMetric(ready=True))

        metrics_text = registry.render().decode()

        assert REQUEST_TOTAL_METRIC_NAME in metrics_text
        assert REQUEST_DURATION_METRIC_NAME in metrics_text
        assert RUNTIME_READY_METRIC_NAME in metrics_text
        assert HEALTH_LIVE_PATH in metrics_text

    def test_content_type_should_be_prometheus_text(self) -> None:
        """
        验证内容类型应为 Prometheus 文本基础类型。
        """

        registry = PrometheusMetricsRegistry()

        assert registry.get_content_type() == CONTENT_TYPE_TEXT

    def test_render_when_dynamic_path_should_use_unknown_label(self) -> None:
        """
        验证动态路径指标应归入 unknown 标签。
        """

        registry = PrometheusMetricsRegistry()
        for path in [USER_NUMERIC_PATH, ITEM_UUID_PATH, BLOB_HEX_PATH]:
            registry.record_http_request(
                HttpRequestMetric(
                    method=HTTP_GET_METHOD,
                    path=path,
                    status_code=HTTP_STATUS_OK,
                    duration_seconds=REQUEST_DURATION_SECONDS,
                )
            )

        metrics_text = registry.render().decode()

        assert f'path="{UNKNOWN_REQUEST_PATH_LABEL}"' in metrics_text
        assert USER_NUMERIC_PATH not in metrics_text
        assert ITEM_UUID_PATH not in metrics_text
        assert BLOB_HEX_PATH not in metrics_text
