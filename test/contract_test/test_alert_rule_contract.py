"""
告警规则契约测试模块。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.observability_contract.alert_rule_contract import (
    ABSENCE_ALERT_RULE_DETAIL_KIND,
    ALERT_RULE_CATALOG_HEADER_KIND,
    ALERT_RULE_HEADER_KIND,
    ALERT_RULE_SCHEMA_VERSION,
    THRESHOLD_ALERT_RULE_DETAIL_KIND,
    AbsenceAlertRuleDetail,
    AlertRuleCatalogEnvelope,
    AlertRuleEnvelope,
    AlertRuleKind,
    AlertRuleSeverity,
    ThresholdAlertRuleDetail,
)

HEADER_FIELD = "header"
DETAIL_FIELD = "detail"
RULES_FIELD = "rules"
RULE_KIND_FIELD = "rule_kind"
RULE_NAME_FIELD = "rule_name"
EXTRA_FIELD = "extra_field"
KIND_FIELD = "kind"
SCHEMA_VERSION_FIELD = "schema_version"
TEST_POLICY_NAME = "test_alert_policy"
TEST_THRESHOLD_RULE_NAME = "threshold_rule"
TEST_ABSENCE_RULE_NAME = "absence_rule"
TEST_PROMQL_EXPRESSION = "sum(rate(fastapi_request_total[5m])) > 0.05"
TEST_ABSENCE_EXPRESSION = "absent(fastapi_runtime_ready)"
TEST_THRESHOLD_VALUE = 0.05
TEST_FOR_DURATION_SECONDS = 300
TEST_SUMMARY = "测试告警摘要。"


class TestAlertRuleContract:
    """
    告警规则契约测试集合。
    """

    def test_valid_threshold_rule_should_pass(self) -> None:
        """
        验证合法阈值规则信封通过校验且判别联合选择正确扩展。
        """

        envelope = AlertRuleEnvelope.model_validate(self._build_threshold_rule_payload())

        assert isinstance(envelope.detail, ThresholdAlertRuleDetail)
        assert envelope.header.rule_kind == AlertRuleKind.THRESHOLD_ALERT
        assert envelope.detail.threshold == TEST_THRESHOLD_VALUE

    def test_valid_absence_rule_should_pass(self) -> None:
        """
        验证合法缺失规则信封通过校验且判别联合选择正确扩展。
        """

        envelope = AlertRuleEnvelope.model_validate(self._build_absence_rule_payload())

        assert isinstance(envelope.detail, AbsenceAlertRuleDetail)
        assert envelope.header.severity == AlertRuleSeverity.CRITICAL

    def test_rule_kind_mismatch_should_fail(self) -> None:
        """
        验证外层 rule_kind 与内层 detail.kind 不一致时拒绝。
        """

        payload = self._build_threshold_rule_payload()
        header = dict(payload[HEADER_FIELD])
        header[RULE_KIND_FIELD] = ABSENCE_ALERT_RULE_DETAIL_KIND
        payload[HEADER_FIELD] = header

        with pytest.raises(ValidationError):
            AlertRuleEnvelope.model_validate(payload)

    def test_extra_field_should_fail(self) -> None:
        """
        验证信封与扩展字段拒绝未知字段。
        """

        envelope_payload = self._build_threshold_rule_payload()
        envelope_payload[EXTRA_FIELD] = True
        with pytest.raises(ValidationError):
            AlertRuleEnvelope.model_validate(envelope_payload)

        detail_payload = self._build_threshold_rule_payload()
        detail = dict(detail_payload[DETAIL_FIELD])
        detail[EXTRA_FIELD] = True
        detail_payload[DETAIL_FIELD] = detail
        with pytest.raises(ValidationError):
            AlertRuleEnvelope.model_validate(detail_payload)

    def test_catalog_should_reject_duplicate_rule_names(self) -> None:
        """
        验证目录信封拒绝重复规则名。
        """

        payload = self._build_catalog_payload()
        payload[RULES_FIELD] = [
            self._build_threshold_rule_payload(),
            self._build_threshold_rule_payload(),
        ]

        with pytest.raises(ValidationError):
            AlertRuleCatalogEnvelope.model_validate(payload)

    def test_catalog_should_reject_empty_rules(self) -> None:
        """
        验证目录信封拒绝空规则列表。
        """

        payload = self._build_catalog_payload()
        payload[RULES_FIELD] = []

        with pytest.raises(ValidationError):
            AlertRuleCatalogEnvelope.model_validate(payload)

    def test_catalog_with_mixed_rule_kinds_should_pass(self) -> None:
        """
        验证目录信封同时承载阈值与缺失两类规则。
        """

        catalog = AlertRuleCatalogEnvelope.model_validate(self._build_catalog_payload())

        assert catalog.header.kind == ALERT_RULE_CATALOG_HEADER_KIND
        assert {rule.detail.kind for rule in catalog.rules} == {
            THRESHOLD_ALERT_RULE_DETAIL_KIND,
            ABSENCE_ALERT_RULE_DETAIL_KIND,
        }

    def _build_threshold_rule_payload(self) -> dict[str, object]:
        """
        构建阈值规则载荷。
        """

        return {
            HEADER_FIELD: {
                KIND_FIELD: ALERT_RULE_HEADER_KIND,
                SCHEMA_VERSION_FIELD: ALERT_RULE_SCHEMA_VERSION,
                RULE_NAME_FIELD: TEST_THRESHOLD_RULE_NAME,
                "severity": AlertRuleSeverity.WARNING.value,
                RULE_KIND_FIELD: THRESHOLD_ALERT_RULE_DETAIL_KIND,
            },
            DETAIL_FIELD: {
                KIND_FIELD: THRESHOLD_ALERT_RULE_DETAIL_KIND,
                SCHEMA_VERSION_FIELD: ALERT_RULE_SCHEMA_VERSION,
                "promql_expression": TEST_PROMQL_EXPRESSION,
                "threshold": TEST_THRESHOLD_VALUE,
                "for_duration_seconds": TEST_FOR_DURATION_SECONDS,
                "summary": TEST_SUMMARY,
            },
        }

    def _build_absence_rule_payload(self) -> dict[str, object]:
        """
        构建缺失规则载荷。
        """

        return {
            HEADER_FIELD: {
                KIND_FIELD: ALERT_RULE_HEADER_KIND,
                SCHEMA_VERSION_FIELD: ALERT_RULE_SCHEMA_VERSION,
                RULE_NAME_FIELD: TEST_ABSENCE_RULE_NAME,
                "severity": AlertRuleSeverity.CRITICAL.value,
                RULE_KIND_FIELD: ABSENCE_ALERT_RULE_DETAIL_KIND,
            },
            DETAIL_FIELD: {
                KIND_FIELD: ABSENCE_ALERT_RULE_DETAIL_KIND,
                SCHEMA_VERSION_FIELD: ALERT_RULE_SCHEMA_VERSION,
                "promql_expression": TEST_ABSENCE_EXPRESSION,
                "for_duration_seconds": TEST_FOR_DURATION_SECONDS,
                "summary": TEST_SUMMARY,
            },
        }

    def _build_catalog_payload(self) -> dict[str, object]:
        """
        构建目录信封载荷。
        """

        return {
            HEADER_FIELD: {
                KIND_FIELD: ALERT_RULE_CATALOG_HEADER_KIND,
                SCHEMA_VERSION_FIELD: ALERT_RULE_SCHEMA_VERSION,
                "policy_name": TEST_POLICY_NAME,
            },
            RULES_FIELD: [
                self._build_threshold_rule_payload(),
                self._build_absence_rule_payload(),
            ],
        }
