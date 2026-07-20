"""
配置应用事务执行器基础设施模块。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from src.infrastructure.logging.sensitive_text_redactor import SensitiveTextRedactor
from src.infrastructure.settings.settings_apply_contract import (
    SettingsApplyOperationEnvelope,
    SettingsApplyResultPayload,
)

ROLLBACK_FAILURE_MESSAGE = "回滚失败"


@dataclass(slots=True)
class SettingsApplyTransaction:
    """
    配置应用事务执行器。
    """

    operation: SettingsApplyOperationEnvelope
    active_snapshot_id: str
    commit_action: Callable[[], None]
    rollback_action: Callable[[], list[str]]
    sensitive_text_redactor: SensitiveTextRedactor = field(default_factory=SensitiveTextRedactor)

    def execute(self) -> SettingsApplyResultPayload:
        """
        执行配置应用事务。

        :returns: 返回配置应用结果载荷。
        :rtype: SettingsApplyResultPayload
        """

        try:
            self.commit_action()
            return SettingsApplyResultPayload(
                success=True,
                rolled_back=False,
                active_snapshot_id=self.active_snapshot_id,
            )
        except Exception as exc:
            rollback_error: Exception | None = None
            restored_resources: list[str] = []
            try:
                restored_resources = self.rollback_action()
            except Exception as restore_exc:
                rollback_error = restore_exc
            return SettingsApplyResultPayload(
                success=False,
                rolled_back=rollback_error is None,
                active_snapshot_id=None,
                restored_resources=restored_resources,
                failure_reason=self._build_failure_reason(
                    apply_error=exc,
                    rollback_error=rollback_error,
                ),
            )

    def _build_failure_reason(
        self,
        *,
        apply_error: Exception,
        rollback_error: Exception | None,
    ) -> str:
        """
        构建失败原因文本。

        :param apply_error: 配置应用阶段抛出的异常。
        :type apply_error: Exception
        :param rollback_error: 回滚阶段抛出的异常。默认值：``None``。
        :type rollback_error: Exception | None
        :returns: 返回失败原因文本。
        :rtype: str
        """

        apply_reason = self.sensitive_text_redactor.redact(str(apply_error))
        if rollback_error is None:
            return apply_reason or ""
        rollback_reason = self.sensitive_text_redactor.redact(str(rollback_error))
        return f"{apply_reason}；{ROLLBACK_FAILURE_MESSAGE}：{rollback_reason}"
