"""
告警规则目录加载器基础设施模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from src.core.observability_contract.alert_rule_contract import AlertRuleCatalogEnvelope

ALERT_RULES_FILE_ENCODING = "utf-8"
ALERT_RULES_FILE_MISSING_MESSAGE = "告警规则文件不存在：{path}"
ALERT_RULES_FILE_INVALID_MESSAGE = "告警规则文件无法通过契约校验：{path}"
ALERT_RULES_FILE_NOT_MAPPING_MESSAGE = "告警规则文件根节点必须是映射结构：{path}"


class AlertRuleCatalogLoadError(ValueError):
    """
    告警规则目录加载异常。
    """


@dataclass(frozen=True, slots=True)
class AlertRuleCatalogLoader:
    """
    告警规则目录加载器。

    以 safe load 方式读取 YAML 规则文件，并经 ``AlertRuleCatalogEnvelope``
    契约模型完成结构与取值校验。

    :ivar path: 告警规则 YAML 文件路径。
    :vartype path: Path
    """

    path: Path

    def load(self) -> AlertRuleCatalogEnvelope:
        """
        加载并校验告警规则目录。

        :returns: 已通过契约校验的告警规则目录信封。
        :rtype: AlertRuleCatalogEnvelope
        :raises AlertRuleCatalogLoadError: 当文件缺失、根节点非映射或契约校验失败时抛出。
        """

        if not self.path.is_file():
            raise AlertRuleCatalogLoadError(ALERT_RULES_FILE_MISSING_MESSAGE.format(path=self.path))
        raw_document = yaml.safe_load(self.path.read_text(encoding=ALERT_RULES_FILE_ENCODING))
        if not isinstance(raw_document, dict):
            raise AlertRuleCatalogLoadError(
                ALERT_RULES_FILE_NOT_MAPPING_MESSAGE.format(path=self.path)
            )
        try:
            return AlertRuleCatalogEnvelope.model_validate(raw_document)
        except ValidationError as exc:
            raise AlertRuleCatalogLoadError(
                ALERT_RULES_FILE_INVALID_MESSAGE.format(path=self.path)
            ) from exc
