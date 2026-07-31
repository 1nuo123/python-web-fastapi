"""
告警规则目录加载单元测试模块。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.core.observability_contract.alert_rule_contract import (
    ALERT_RULE_CATALOG_HEADER_KIND,
    AlertRuleKind,
    ThresholdAlertRuleDetail,
)
from src.infrastructure.observability.alert_rule_catalog_loader import (
    AlertRuleCatalogLoader,
    AlertRuleCatalogLoadError,
)
from src.infrastructure.observability.prometheus_metrics_registry import (
    LOG_BUFFER_FLUSH_TOTAL_NAME,
    REQUEST_DURATION_SECONDS_NAME,
    REQUEST_TOTAL_NAME,
    RUNTIME_READY_NAME,
    TASK_EXECUTION_TOTAL_NAME,
)

ALERT_RULES_PATH = Path("config/observability/alert_rules.yml")
MISSING_RULES_PATH = Path("config/observability/alert_rules_missing.yml")
INVALID_ROOT_FILE_NAME = "alert_rules_invalid_root.yml"
INVALID_SCHEMA_FILE_NAME = "alert_rules_invalid_schema.yml"
INVALID_ROOT_DOCUMENT = "- 规则一\n- 规则二\n"
INVALID_SCHEMA_DOCUMENT = "header:\n  kind: alert_rule_catalog_header\nrules: []\n"
EXPECTED_RULE_COUNT = 6
EXPECTED_RULE_NAMES = frozenset(
    {
        "http_5xx_error_rate_high",
        "http_p95_latency_high",
        "runtime_ready_down",
        "log_buffer_flush_failure_growing",
        "audit_critical_write_failure",
        "task_execution_failure_rate_high",
    }
)
RULE_METRIC_NAME_BY_RULE = {
    "http_5xx_error_rate_high": REQUEST_TOTAL_NAME,
    "http_p95_latency_high": REQUEST_DURATION_SECONDS_NAME,
    "runtime_ready_down": RUNTIME_READY_NAME,
    "log_buffer_flush_failure_growing": LOG_BUFFER_FLUSH_TOTAL_NAME,
    "audit_critical_write_failure": LOG_BUFFER_FLUSH_TOTAL_NAME,
    "task_execution_failure_rate_high": TASK_EXECUTION_TOTAL_NAME,
}
AUDIT_CRITICAL_RULE_NAME = "audit_critical_write_failure"
AUDIT_CRITICAL_REASON_LABEL_TEXT = 'reason="audit_critical"'
FAILED_LABEL_TEXT = 'failed="true"'


class TestAlertRuleCatalogUnit:
    """
    告警规则目录加载单元测试集合。
    """

    def test_load_should_return_six_baseline_rules(self) -> None:
        """
        验证基线规则文件可加载且包含六条规则。
        """

        catalog = AlertRuleCatalogLoader(path=ALERT_RULES_PATH).load()

        assert catalog.header.kind == ALERT_RULE_CATALOG_HEADER_KIND
        assert len(catalog.rules) == EXPECTED_RULE_COUNT
        assert {rule.header.rule_name for rule in catalog.rules} == EXPECTED_RULE_NAMES
        assert all(rule.header.rule_kind.value == rule.detail.kind for rule in catalog.rules)

    def test_rules_should_reference_registered_metric_names(self) -> None:
        """
        验证六条规则 PromQL 引用的指标名与注册器指标名逐一对应。
        """

        catalog = AlertRuleCatalogLoader(path=ALERT_RULES_PATH).load()

        for rule in catalog.rules:
            expected_metric_name = RULE_METRIC_NAME_BY_RULE[rule.header.rule_name]
            assert expected_metric_name in rule.detail.promql_expression

    def test_audit_critical_rule_should_filter_audit_reason_label(self) -> None:
        """
        验证审计写失败规则使用 audit_critical 原因标签过滤。
        """

        catalog = AlertRuleCatalogLoader(path=ALERT_RULES_PATH).load()
        audit_rule = next(
            rule for rule in catalog.rules if rule.header.rule_name == AUDIT_CRITICAL_RULE_NAME
        )

        assert isinstance(audit_rule.detail, ThresholdAlertRuleDetail)
        assert audit_rule.header.rule_kind == AlertRuleKind.THRESHOLD_ALERT
        assert AUDIT_CRITICAL_REASON_LABEL_TEXT in audit_rule.detail.promql_expression
        assert FAILED_LABEL_TEXT in audit_rule.detail.promql_expression

    def test_load_when_file_missing_should_raise(self) -> None:
        """
        验证规则文件缺失时抛出加载异常。
        """

        with pytest.raises(AlertRuleCatalogLoadError):
            AlertRuleCatalogLoader(path=MISSING_RULES_PATH).load()

    def test_load_when_root_not_mapping_should_raise(self, tmp_path: Path) -> None:
        """
        验证根节点非映射结构时抛出加载异常。
        """

        invalid_path = tmp_path / INVALID_ROOT_FILE_NAME
        invalid_path.write_text(INVALID_ROOT_DOCUMENT, encoding="utf-8")

        with pytest.raises(AlertRuleCatalogLoadError):
            AlertRuleCatalogLoader(path=invalid_path).load()

    def test_load_when_schema_invalid_should_raise(self, tmp_path: Path) -> None:
        """
        验证契约校验失败时抛出加载异常。
        """

        invalid_path = tmp_path / INVALID_SCHEMA_FILE_NAME
        invalid_path.write_text(INVALID_SCHEMA_DOCUMENT, encoding="utf-8")

        with pytest.raises(AlertRuleCatalogLoadError):
            AlertRuleCatalogLoader(path=invalid_path).load()
