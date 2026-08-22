"""
指标运行时配置契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

METRICS_RUNTIME_SCHEMA_VERSION: Final = "1.1"
METRICS_RUNTIME_ENVELOPE_KIND: Final = "metrics_runtime_envelope"
METRICS_RUNTIME_HEADER_KIND: Final = "metrics_runtime_header"
PROMETHEUS_METRICS_DETAIL_KIND: Final = "prometheus_metrics"
DEFAULT_METRICS_PATH = "/metrics"
DEFAULT_METRICS_POLICY_NAME = "metrics_default"
METRICS_PATH_MINIMUM_LENGTH = 1
METRICS_POLICY_NAME_MINIMUM_LENGTH = 1
URL_PATH_SEPARATOR = "/"


class MetricsRuntimeMode(StrEnum):
    """
    指标运行时模式枚举。
    """

    PROMETHEUS = PROMETHEUS_METRICS_DETAIL_KIND


class MetricsRuntimeHeader(BaseModel):
    """
    指标运行时公共头模型。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["metrics_runtime_header"] = METRICS_RUNTIME_HEADER_KIND
    schema_version: Literal["1.1"] = METRICS_RUNTIME_SCHEMA_VERSION
    mode: MetricsRuntimeMode
    enabled: bool
    policy_name: str = Field(min_length=METRICS_POLICY_NAME_MINIMUM_LENGTH)


class PrometheusMetricsRuntimeDetail(BaseModel):
    """
    Prometheus 指标运行时扩展模型。

    :ivar include_security_metrics: 是否暴露安全事件指标。
    :vartype include_security_metrics: bool
    :ivar include_task_metrics: 是否暴露任务执行指标。
    :vartype include_task_metrics: bool
    :ivar include_log_buffer_metrics: 是否暴露日志缓冲刷盘与积压指标。
    :vartype include_log_buffer_metrics: bool
    :ivar include_saturation_metrics: 是否暴露运行时饱和度指标。
    :vartype include_saturation_metrics: bool
    :ivar include_codex_diagnostic_metrics: 是否暴露 Codex 客户端诊断低基数计数。
    :vartype include_codex_diagnostic_metrics: bool
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["prometheus_metrics"] = PROMETHEUS_METRICS_DETAIL_KIND
    schema_version: Literal["1.1"] = METRICS_RUNTIME_SCHEMA_VERSION
    metrics_path: str = Field(
        default=DEFAULT_METRICS_PATH,
        min_length=METRICS_PATH_MINIMUM_LENGTH,
    )
    include_http_metrics: bool = True
    include_runtime_metrics: bool = True
    include_security_metrics: bool = True
    include_task_metrics: bool = True
    include_log_buffer_metrics: bool = True
    include_saturation_metrics: bool = True
    include_codex_diagnostic_metrics: bool = True

    @model_validator(mode="after")
    def validate_metrics_path(self) -> PrometheusMetricsRuntimeDetail:
        """
        校验 Prometheus 指标路径。

        :returns: 当前模型实例。
        :rtype: PrometheusMetricsRuntimeDetail
        :raises ValueError: 当指标路径不是绝对路径时抛出。
        """

        if not self.metrics_path.startswith(URL_PATH_SEPARATOR):
            raise ValueError("runtime.metrics.detail.metrics_path 必须以 / 开头。")
        return self


MetricsRuntimeDetail = Annotated[
    PrometheusMetricsRuntimeDetail,
    Field(discriminator="kind"),
]


class MetricsRuntimeEnvelope(BaseModel):
    """
    指标运行时配置信封模型。
    """

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["metrics_runtime_envelope"] = METRICS_RUNTIME_ENVELOPE_KIND
    schema_version: Literal["1.1"] = METRICS_RUNTIME_SCHEMA_VERSION
    header: MetricsRuntimeHeader
    detail: MetricsRuntimeDetail

    @model_validator(mode="after")
    def validate_detail_contract(self) -> MetricsRuntimeEnvelope:
        """
        校验指标运行时公共头与扩展配置一致性。

        :returns: 当前模型实例。
        :rtype: MetricsRuntimeEnvelope
        :raises ValueError: 当外层类型与内层扩展类型或版本不一致时抛出。
        """

        if self.header.mode.value != self.detail.kind:
            raise ValueError("runtime.metrics.header.mode 必须与 detail.kind 一致。")
        if self.schema_version != self.header.schema_version:
            raise ValueError("runtime.metrics.schema_version 必须与 header.schema_version 一致。")
        if self.schema_version != self.detail.schema_version:
            raise ValueError("runtime.metrics.schema_version 必须与 detail.schema_version 一致。")
        return self
