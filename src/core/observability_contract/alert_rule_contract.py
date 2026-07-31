"""
告警规则契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ALERT_RULE_SCHEMA_VERSION: Final = "1.0"
ALERT_RULE_CATALOG_HEADER_KIND: Final = "alert_rule_catalog_header"
ALERT_RULE_HEADER_KIND: Final = "alert_rule_header"
THRESHOLD_ALERT_RULE_DETAIL_KIND: Final = "threshold_alert"
ABSENCE_ALERT_RULE_DETAIL_KIND: Final = "absence_alert"
ALERT_RULE_NAME_MINIMUM_LENGTH = 1
ALERT_RULE_POLICY_NAME_MINIMUM_LENGTH = 1
ALERT_RULE_EXPRESSION_MINIMUM_LENGTH = 1
ALERT_RULE_SUMMARY_MINIMUM_LENGTH = 1
ALERT_RULE_FOR_DURATION_MINIMUM_SECONDS = 0
ALERT_RULE_CATALOG_MINIMUM_RULES = 1


class AlertRuleSeverity(StrEnum):
    """
    告警规则严重级别枚举。

    :cvar WARNING: 警告级别，需要关注但不要求立即处置。
    :cvar CRITICAL: 严重级别，需要立即处置。
    """

    WARNING = "warning"
    CRITICAL = "critical"


class AlertRuleKind(StrEnum):
    """
    告警规则类型枚举。

    :cvar THRESHOLD_ALERT: 阈值告警规则，表达式结果越过阈值触发。
    :cvar ABSENCE_ALERT: 缺失告警规则，用于 ready 掉线或抓取缺失类场景。
    """

    THRESHOLD_ALERT = THRESHOLD_ALERT_RULE_DETAIL_KIND
    ABSENCE_ALERT = ABSENCE_ALERT_RULE_DETAIL_KIND


class AlertRuleHeader(BaseModel):
    """
    告警规则公共头模型。

    :ivar rule_name: 规则名称，低基数稳定标识。
    :vartype rule_name: str
    :ivar severity: 告警严重级别。
    :vartype severity: AlertRuleSeverity
    :ivar rule_kind: 规则类型，必须与扩展字段 ``detail.kind`` 一致。
    :vartype rule_kind: AlertRuleKind
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["alert_rule_header"] = ALERT_RULE_HEADER_KIND
    schema_version: Literal["1.0"] = ALERT_RULE_SCHEMA_VERSION
    rule_name: str = Field(min_length=ALERT_RULE_NAME_MINIMUM_LENGTH)
    severity: AlertRuleSeverity
    rule_kind: AlertRuleKind


class ThresholdAlertRuleDetail(BaseModel):
    """
    阈值告警规则扩展模型。

    :ivar promql_expression: PromQL 表达式，表达式已内嵌阈值比较。
    :vartype promql_expression: str
    :ivar threshold: 触发阈值，与表达式内比较值保持一致，供面板与文档展示。
    :vartype threshold: float
    :ivar for_duration_seconds: 持续满足条件的等待秒数。
    :vartype for_duration_seconds: int
    :ivar summary: 告警摘要说明。
    :vartype summary: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["threshold_alert"] = THRESHOLD_ALERT_RULE_DETAIL_KIND
    schema_version: Literal["1.0"] = ALERT_RULE_SCHEMA_VERSION
    promql_expression: str = Field(min_length=ALERT_RULE_EXPRESSION_MINIMUM_LENGTH)
    threshold: float
    for_duration_seconds: int = Field(ge=ALERT_RULE_FOR_DURATION_MINIMUM_SECONDS)
    summary: str = Field(min_length=ALERT_RULE_SUMMARY_MINIMUM_LENGTH)


class AbsenceAlertRuleDetail(BaseModel):
    """
    缺失告警规则扩展模型。

    :ivar promql_expression: PromQL 表达式，覆盖指标缺失或 ready 掉线判定。
    :vartype promql_expression: str
    :ivar for_duration_seconds: 持续满足条件的等待秒数。
    :vartype for_duration_seconds: int
    :ivar summary: 告警摘要说明。
    :vartype summary: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["absence_alert"] = ABSENCE_ALERT_RULE_DETAIL_KIND
    schema_version: Literal["1.0"] = ALERT_RULE_SCHEMA_VERSION
    promql_expression: str = Field(min_length=ALERT_RULE_EXPRESSION_MINIMUM_LENGTH)
    for_duration_seconds: int = Field(ge=ALERT_RULE_FOR_DURATION_MINIMUM_SECONDS)
    summary: str = Field(min_length=ALERT_RULE_SUMMARY_MINIMUM_LENGTH)


AlertRuleDetail = Annotated[
    ThresholdAlertRuleDetail | AbsenceAlertRuleDetail,
    Field(discriminator="kind"),
]


class AlertRuleEnvelope(BaseModel):
    """
    告警规则信封模型。
    """

    model_config = ConfigDict(extra="forbid")

    header: AlertRuleHeader
    detail: AlertRuleDetail

    @model_validator(mode="after")
    def validate_rule_contract(self) -> AlertRuleEnvelope:
        """
        校验告警规则公共头与扩展字段一致。

        :returns: 当前信封实例。
        :rtype: AlertRuleEnvelope
        :raises ValueError: 当外层规则类型或版本与扩展字段不一致时抛出。
        """

        if self.header.rule_kind.value != self.detail.kind:
            raise ValueError("告警规则 header.rule_kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("告警规则 header.schema_version 必须与 detail.schema_version 一致。")
        return self


class AlertRuleCatalogHeader(BaseModel):
    """
    告警规则目录公共头模型。

    :ivar policy_name: 告警策略名称。
    :vartype policy_name: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["alert_rule_catalog_header"] = ALERT_RULE_CATALOG_HEADER_KIND
    schema_version: Literal["1.0"] = ALERT_RULE_SCHEMA_VERSION
    policy_name: str = Field(min_length=ALERT_RULE_POLICY_NAME_MINIMUM_LENGTH)


class AlertRuleCatalogEnvelope(BaseModel):
    """
    告警规则目录信封模型。
    """

    model_config = ConfigDict(extra="forbid")

    header: AlertRuleCatalogHeader
    rules: list[AlertRuleEnvelope] = Field(min_length=ALERT_RULE_CATALOG_MINIMUM_RULES)

    @model_validator(mode="after")
    def validate_catalog_contract(self) -> AlertRuleCatalogEnvelope:
        """
        校验告警规则目录版本一致性与规则名唯一性。

        :returns: 当前目录信封实例。
        :rtype: AlertRuleCatalogEnvelope
        :raises ValueError: 当规则版本与目录不一致或规则名重复时抛出。
        """

        rule_names = [rule.header.rule_name for rule in self.rules]
        if len(rule_names) != len(set(rule_names)):
            raise ValueError("告警规则目录内 rule_name 不允许重复。")
        for rule in self.rules:
            if rule.header.schema_version != self.header.schema_version:
                raise ValueError("告警规则版本必须与目录 schema_version 一致。")
        return self
