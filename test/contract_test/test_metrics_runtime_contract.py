"""
指标运行时契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.observability_contract.metrics_runtime_contract import (
    DEFAULT_METRICS_PATH,
    DEFAULT_METRICS_POLICY_NAME,
    METRICS_RUNTIME_ENVELOPE_KIND,
    METRICS_RUNTIME_HEADER_KIND,
    METRICS_RUNTIME_SCHEMA_VERSION,
    PROMETHEUS_METRICS_DETAIL_KIND,
    MetricsRuntimeEnvelope,
)

ENABLED_FIELD = "enabled"
HEADER_FIELD = "header"
MODE_FIELD = "mode"
POLICY_NAME_FIELD = "policy_name"
DETAIL_FIELD = "detail"
EXTRA_FIELD = "extra_field"
UNKNOWN_MODE = "unknown_metrics"


class TestMetricsRuntimeContract:
    """
    指标运行时契约测试集合。
    """

    def test_valid_prometheus_envelope_should_pass(self) -> None:
        """
        验证有效 Prometheus 指标运行时信封应通过校验。
        """

        envelope = MetricsRuntimeEnvelope.model_validate(self._build_payload())

        assert envelope.header.enabled is False
        assert envelope.detail.metrics_path == DEFAULT_METRICS_PATH

    def test_mode_and_detail_kind_mismatch_should_fail(self) -> None:
        """
        验证公共头模式与扩展类型不一致应失败。
        """

        payload = self._build_payload()
        header = dict(payload[HEADER_FIELD])
        header[MODE_FIELD] = UNKNOWN_MODE
        payload[HEADER_FIELD] = header

        with pytest.raises(ValidationError):
            MetricsRuntimeEnvelope.model_validate(payload)

    def test_extra_field_should_fail(self) -> None:
        """
        验证额外字段应被拒绝。
        """

        payload = self._build_payload()
        payload[EXTRA_FIELD] = True

        with pytest.raises(ValidationError):
            MetricsRuntimeEnvelope.model_validate(payload)

    def _build_payload(self) -> dict[str, object]:
        """
        构建有效指标运行时配置载荷。

        :returns: 指标运行时配置载荷。
        :rtype: dict[str, object]
        """

        return {
            "envelope_kind": METRICS_RUNTIME_ENVELOPE_KIND,
            "schema_version": METRICS_RUNTIME_SCHEMA_VERSION,
            HEADER_FIELD: {
                "kind": METRICS_RUNTIME_HEADER_KIND,
                "schema_version": METRICS_RUNTIME_SCHEMA_VERSION,
                MODE_FIELD: PROMETHEUS_METRICS_DETAIL_KIND,
                ENABLED_FIELD: False,
                POLICY_NAME_FIELD: DEFAULT_METRICS_POLICY_NAME,
            },
            DETAIL_FIELD: {
                "kind": PROMETHEUS_METRICS_DETAIL_KIND,
                "schema_version": METRICS_RUNTIME_SCHEMA_VERSION,
                "metrics_path": DEFAULT_METRICS_PATH,
                "include_http_metrics": True,
                "include_runtime_metrics": True,
            },
        }
