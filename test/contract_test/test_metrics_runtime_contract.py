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
SCHEMA_VERSION_FIELD = "schema_version"
UNKNOWN_MODE = "unknown_metrics"
CURRENT_SCHEMA_VERSION = "1.1"
LEGACY_SCHEMA_VERSION = "1.0"
INCLUDE_SECURITY_METRICS_FIELD = "include_security_metrics"
INCLUDE_TASK_METRICS_FIELD = "include_task_metrics"
INCLUDE_LOG_BUFFER_METRICS_FIELD = "include_log_buffer_metrics"
INCLUDE_SATURATION_METRICS_FIELD = "include_saturation_metrics"
INCLUDE_CODEX_DIAGNOSTIC_METRICS_FIELD = "include_codex_diagnostic_metrics"


class TestMetricsRuntimeContract:
    """
    指标运行时契约测试集合。
    """

    def test_schema_version_should_be_upgraded_to_1_1(self) -> None:
        """
        验证指标运行时契约版本已升级到 1.1。
        """

        assert METRICS_RUNTIME_SCHEMA_VERSION == CURRENT_SCHEMA_VERSION

    def test_valid_prometheus_envelope_should_pass(self) -> None:
        """
        验证有效 Prometheus 指标运行时信封应通过校验。
        """

        envelope = MetricsRuntimeEnvelope.model_validate(self._build_payload())

        assert envelope.header.enabled is False
        assert envelope.detail.metrics_path == DEFAULT_METRICS_PATH
        assert envelope.schema_version == CURRENT_SCHEMA_VERSION

    def test_detail_should_expose_metric_switches(self) -> None:
        """
        验证扩展字段包含四个新指标开关且默认开启。
        """

        payload = self._build_payload()
        detail = dict(payload[DETAIL_FIELD])
        for switch_field in (
            INCLUDE_SECURITY_METRICS_FIELD,
            INCLUDE_TASK_METRICS_FIELD,
            INCLUDE_LOG_BUFFER_METRICS_FIELD,
            INCLUDE_SATURATION_METRICS_FIELD,
            INCLUDE_CODEX_DIAGNOSTIC_METRICS_FIELD,
        ):
            detail.pop(switch_field)
        payload[DETAIL_FIELD] = detail

        envelope = MetricsRuntimeEnvelope.model_validate(payload)

        assert envelope.detail.include_security_metrics is True
        assert envelope.detail.include_task_metrics is True
        assert envelope.detail.include_log_buffer_metrics is True
        assert envelope.detail.include_saturation_metrics is True
        assert envelope.detail.include_codex_diagnostic_metrics is True

    def test_legacy_1_0_payload_should_fail_with_explicit_error(self) -> None:
        """
        验证 1.0 版本配置载荷升级路径明确报错。
        """

        payload = self._build_payload()
        payload[SCHEMA_VERSION_FIELD] = LEGACY_SCHEMA_VERSION
        header = dict(payload[HEADER_FIELD])
        header[SCHEMA_VERSION_FIELD] = LEGACY_SCHEMA_VERSION
        payload[HEADER_FIELD] = header
        detail = dict(payload[DETAIL_FIELD])
        detail[SCHEMA_VERSION_FIELD] = LEGACY_SCHEMA_VERSION
        payload[DETAIL_FIELD] = detail

        with pytest.raises(ValidationError):
            MetricsRuntimeEnvelope.model_validate(payload)

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
        验证信封与扩展字段额外字段应被拒绝。
        """

        envelope_payload = self._build_payload()
        envelope_payload[EXTRA_FIELD] = True
        with pytest.raises(ValidationError):
            MetricsRuntimeEnvelope.model_validate(envelope_payload)

        detail_payload = self._build_payload()
        detail = dict(detail_payload[DETAIL_FIELD])
        detail[EXTRA_FIELD] = True
        detail_payload[DETAIL_FIELD] = detail
        with pytest.raises(ValidationError):
            MetricsRuntimeEnvelope.model_validate(detail_payload)

    def _build_payload(self) -> dict[str, object]:
        """
        构建有效指标运行时配置载荷。

        :returns: 指标运行时配置载荷。
        :rtype: dict[str, object]
        """

        return {
            "envelope_kind": METRICS_RUNTIME_ENVELOPE_KIND,
            SCHEMA_VERSION_FIELD: METRICS_RUNTIME_SCHEMA_VERSION,
            HEADER_FIELD: {
                "kind": METRICS_RUNTIME_HEADER_KIND,
                SCHEMA_VERSION_FIELD: METRICS_RUNTIME_SCHEMA_VERSION,
                MODE_FIELD: PROMETHEUS_METRICS_DETAIL_KIND,
                ENABLED_FIELD: False,
                POLICY_NAME_FIELD: DEFAULT_METRICS_POLICY_NAME,
            },
            DETAIL_FIELD: {
                "kind": PROMETHEUS_METRICS_DETAIL_KIND,
                SCHEMA_VERSION_FIELD: METRICS_RUNTIME_SCHEMA_VERSION,
                "metrics_path": DEFAULT_METRICS_PATH,
                "include_http_metrics": True,
                "include_runtime_metrics": True,
                INCLUDE_SECURITY_METRICS_FIELD: True,
                INCLUDE_TASK_METRICS_FIELD: True,
                INCLUDE_LOG_BUFFER_METRICS_FIELD: True,
                INCLUDE_SATURATION_METRICS_FIELD: True,
                INCLUDE_CODEX_DIAGNOSTIC_METRICS_FIELD: True,
            },
        }
