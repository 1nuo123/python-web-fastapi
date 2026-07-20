"""
Prometheus 指标注册基础设施模块。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.exposition import generate_latest

REQUEST_TOTAL_NAME = "fastapi_request_total"
REQUEST_TOTAL_DESCRIPTION = "FastAPI HTTP 请求总数"
REQUEST_DURATION_SECONDS_NAME = "fastapi_request_duration_seconds"
REQUEST_DURATION_SECONDS_DESCRIPTION = "FastAPI HTTP 请求耗时秒数"
RUNTIME_READY_NAME = "fastapi_runtime_ready"
RUNTIME_READY_DESCRIPTION = "FastAPI 应用 ready 状态"
REQUEST_METHOD_LABEL = "method"
REQUEST_PATH_LABEL = "path"
REQUEST_STATUS_CODE_LABEL = "status_code"
READY_TRUE_VALUE = 1.0
READY_FALSE_VALUE = 0.0
CONTENT_TYPE_SEPARATOR = ";"
UNKNOWN_REQUEST_PATH_LABEL = "unknown"
PATH_SEPARATOR = "/"
ROUTE_PARAMETER_START_MARK = "{"
ROUTE_PARAMETER_END_MARK = "}"
DYNAMIC_PATH_SEGMENT_PATTERN = re.compile(r"^\d+$|^[0-9a-fA-F]{8,}(-[0-9a-fA-F]{4,})*$")


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


class PrometheusMetricsRegistry:
    """
    Prometheus 指标注册器。
    """

    def __init__(self) -> None:
        """
        初始化 Prometheus 指标注册器。

        :returns: 无返回值。
        :rtype: None
        """

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
