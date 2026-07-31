"""
Prometheus 指标注册器单元测试模块。
"""

from __future__ import annotations

from src.core.logging_contract.log_writer_contract import LogWriteReason
from src.core.security_contract.security_event_contract import (
    SecurityEventDecision,
    SecurityEventSeverity,
    SecurityEventType,
)
from src.infrastructure.observability.prometheus_metrics_registry import (
    LOG_BUFFER_FLUSH_TOTAL_NAME,
    LOG_BUFFER_PENDING_ITEMS_NAME,
    RUNTIME_SATURATION_RATIO_NAME,
    SECURITY_EVENT_TOTAL_NAME,
    TASK_EXECUTION_TOTAL_NAME,
    UNKNOWN_REQUEST_PATH_LABEL,
    HttpRequestMetric,
    LogBufferFlushMetric,
    LogBufferPendingMetric,
    PrometheusMetricsRegistry,
    PrometheusMetricsRegistryOptions,
    RuntimeReadyMetric,
    RuntimeSaturationMetric,
    RuntimeSaturationResource,
    SecurityEventMetric,
    TaskExecutionMetric,
    TaskExecutionMetricOutcome,
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
DEMO_TASK_NAME = "demo_task"
FLUSH_BATCH_SIZE = 3
PENDING_ITEMS_VALUE = 5
SATURATION_RATIO_VALUE = 0.42
SATURATION_RATIO_OVERFLOW = 2.5
SATURATION_RATIO_MAXIMUM_TEXT = "1.0"
SECURITY_EVENT_SAMPLE = (
    f'{SECURITY_EVENT_TOTAL_NAME}{{decision="throttle",'
    f'event_type="rate_limit.blocked",severity="warning"}} 1.0'
)
LOG_BUFFER_FLUSH_SAMPLE = (
    f'{LOG_BUFFER_FLUSH_TOTAL_NAME}{{failed="false",reason="interval"}} {float(FLUSH_BATCH_SIZE)}'
)
TASK_EXECUTION_SAMPLE = (
    f'{TASK_EXECUTION_TOTAL_NAME}{{outcome="success",task_name="{DEMO_TASK_NAME}"}} 1.0'
)
SATURATION_SAMPLE = (
    f'{RUNTIME_SATURATION_RATIO_NAME}{{resource="request_thread_pool"}} {SATURATION_RATIO_VALUE}'
)
SATURATION_OVERFLOW_SAMPLE = (
    f'{RUNTIME_SATURATION_RATIO_NAME}{{resource="log_buffer"}} {SATURATION_RATIO_MAXIMUM_TEXT}'
)


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

    def test_record_security_event_should_render_whitelisted_labels(self) -> None:
        """
        验证安全事件指标记录后渲染包含枚举白名单标签样本。
        """

        registry = PrometheusMetricsRegistry()
        registry.record_security_event(
            SecurityEventMetric(
                event_type=SecurityEventType.RATE_LIMIT_BLOCKED,
                decision=SecurityEventDecision.THROTTLE,
                severity=SecurityEventSeverity.WARNING,
            )
        )

        assert SECURITY_EVENT_SAMPLE in registry.render().decode()

    def test_record_log_buffer_flush_should_render_reason_and_failed_labels(self) -> None:
        """
        验证日志缓冲刷盘指标按批次事件数量累加并渲染标签样本。
        """

        registry = PrometheusMetricsRegistry()
        registry.record_log_buffer_flush(
            LogBufferFlushMetric(
                reason=LogWriteReason.INTERVAL,
                failed=False,
                batch_size=FLUSH_BATCH_SIZE,
            )
        )
        registry.set_log_buffer_pending_items(
            LogBufferPendingMetric(pending_items=PENDING_ITEMS_VALUE)
        )

        metrics_text = registry.render().decode()
        assert LOG_BUFFER_FLUSH_SAMPLE in metrics_text
        assert f"{LOG_BUFFER_PENDING_ITEMS_NAME} {float(PENDING_ITEMS_VALUE)}" in metrics_text

    def test_record_task_execution_should_render_outcome_sample(self) -> None:
        """
        验证任务执行指标记录后渲染包含注册名与结果标签样本。
        """

        registry = PrometheusMetricsRegistry()
        registry.record_task_execution(
            TaskExecutionMetric(
                task_name=DEMO_TASK_NAME,
                outcome=TaskExecutionMetricOutcome.SUCCESS,
            )
        )

        assert TASK_EXECUTION_SAMPLE in registry.render().decode()

    def test_set_runtime_saturation_should_render_and_clamp_ratio(self) -> None:
        """
        验证饱和度指标渲染样本且超界比值收敛到 1。
        """

        registry = PrometheusMetricsRegistry()
        registry.set_runtime_saturation(
            RuntimeSaturationMetric(
                resource=RuntimeSaturationResource.REQUEST_THREAD_POOL,
                ratio=SATURATION_RATIO_VALUE,
            )
        )
        registry.set_runtime_saturation(
            RuntimeSaturationMetric(
                resource=RuntimeSaturationResource.LOG_BUFFER,
                ratio=SATURATION_RATIO_OVERFLOW,
            )
        )

        metrics_text = registry.render().decode()
        assert SATURATION_SAMPLE in metrics_text
        assert SATURATION_OVERFLOW_SAMPLE in metrics_text

    def test_disabled_options_should_not_register_metric_families(self) -> None:
        """
        验证开关关闭时对应指标族不注册且记录调用为空操作。
        """

        registry = PrometheusMetricsRegistry(
            options=PrometheusMetricsRegistryOptions(
                include_security_metrics=False,
                include_task_metrics=False,
                include_log_buffer_metrics=False,
                include_saturation_metrics=False,
            )
        )
        registry.record_security_event(
            SecurityEventMetric(
                event_type=SecurityEventType.RATE_LIMIT_BLOCKED,
                decision=SecurityEventDecision.THROTTLE,
                severity=SecurityEventSeverity.WARNING,
            )
        )
        registry.record_log_buffer_flush(
            LogBufferFlushMetric(
                reason=LogWriteReason.MANUAL,
                failed=False,
                batch_size=FLUSH_BATCH_SIZE,
            )
        )
        registry.set_log_buffer_pending_items(
            LogBufferPendingMetric(pending_items=PENDING_ITEMS_VALUE)
        )
        registry.record_task_execution(
            TaskExecutionMetric(
                task_name=DEMO_TASK_NAME,
                outcome=TaskExecutionMetricOutcome.FAILED,
            )
        )
        registry.set_runtime_saturation(
            RuntimeSaturationMetric(
                resource=RuntimeSaturationResource.DB_POOL,
                ratio=SATURATION_RATIO_VALUE,
            )
        )

        metrics_text = registry.render().decode()
        assert SECURITY_EVENT_TOTAL_NAME not in metrics_text
        assert LOG_BUFFER_FLUSH_TOTAL_NAME not in metrics_text
        assert LOG_BUFFER_PENDING_ITEMS_NAME not in metrics_text
        assert TASK_EXECUTION_TOTAL_NAME not in metrics_text
        assert RUNTIME_SATURATION_RATIO_NAME not in metrics_text
