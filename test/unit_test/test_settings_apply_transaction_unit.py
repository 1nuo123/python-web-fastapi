"""
热更新事务执行器单元测试模块。
"""

from __future__ import annotations

from src.infrastructure.settings.settings_apply_contract import (
    HttpResourceSwitchDetail,
    SettingsApplyOperationEnvelope,
    SettingsApplyOperationHeader,
)
from src.infrastructure.settings.settings_apply_transaction import (
    SettingsApplyTransaction,
)

SENSITIVE_APPLY_FAILURE_REASON = "切换失败 password=plain-password"
SENSITIVE_ROLLBACK_FAILURE_REASON = "恢复失败 secret_key=plain-secret"
REDACTED_APPLY_FAILURE_REASON = "切换失败 password=***"
REDACTED_ROLLBACK_FAILURE_REASON = "恢复失败 secret_key=***"


class TestSettingsApplyTransactionUnit:
    """
    热更新事务执行器单元测试集合。
    """

    def test_execute_when_commit_success_should_return_active_snapshot(self) -> None:
        """
        验证事务执行器当提交成功应返回成功结果。
        """

        commit_calls: list[str] = []
        rollback_calls: list[str] = []
        transaction = SettingsApplyTransaction(
            operation=self._build_operation(),
            active_snapshot_id="snapshot-v2",
            commit_action=lambda: commit_calls.append("commit"),
            rollback_action=lambda: rollback_calls,
        )

        result = transaction.execute()

        assert result.success is True
        assert result.rolled_back is False
        assert result.active_snapshot_id == "snapshot-v2"
        assert commit_calls == ["commit"]
        assert rollback_calls == []

    def test_execute_when_commit_fail_should_return_rollback_result(self) -> None:
        """
        验证事务执行器当提交失败且回滚成功应返回回滚结果。
        """

        restored_resources = ["shared_http_client", "shared_task_dispatcher"]
        transaction = SettingsApplyTransaction(
            operation=self._build_operation(),
            active_snapshot_id="snapshot-v2",
            commit_action=self._raise_apply_failure,
            rollback_action=lambda: restored_resources,
        )

        result = transaction.execute()

        assert result.success is False
        assert result.rolled_back is True
        assert result.active_snapshot_id is None
        assert result.restored_resources == restored_resources
        assert result.failure_reason == "切换失败"

    def test_execute_when_rollback_fail_should_return_combined_failure_reason(self) -> None:
        """
        验证事务执行器当提交失败且回滚失败应返回组合失败原因。
        """

        transaction = SettingsApplyTransaction(
            operation=self._build_operation(),
            active_snapshot_id="snapshot-v2",
            commit_action=self._raise_apply_failure,
            rollback_action=self._raise_rollback_failure,
        )

        result = transaction.execute()

        assert result.success is False
        assert result.rolled_back is False
        assert result.active_snapshot_id is None
        assert result.restored_resources == []
        assert result.failure_reason == "切换失败；回滚失败：恢复失败"

    def test_execute_when_failure_contains_sensitive_value_should_redact_reason(
        self,
    ) -> None:
        """
        验证事务失败原因包含敏感键值时应先脱敏再返回。
        """

        transaction = SettingsApplyTransaction(
            operation=self._build_operation(),
            active_snapshot_id="snapshot-v2",
            commit_action=self._raise_sensitive_apply_failure,
            rollback_action=self._raise_sensitive_rollback_failure,
        )

        result = transaction.execute()

        assert result.failure_reason == (
            f"{REDACTED_APPLY_FAILURE_REASON}；回滚失败：{REDACTED_ROLLBACK_FAILURE_REASON}"
        )
        assert "plain-password" not in str(result.failure_reason)
        assert "plain-secret" not in str(result.failure_reason)

    def _build_operation(self) -> SettingsApplyOperationEnvelope:
        """
        构建热更新事务操作契约。
        """

        return SettingsApplyOperationEnvelope(
            header=SettingsApplyOperationHeader(
                operation_name="apply_settings",
                target_resource="shared_resource_mount",
                candidate_version="snapshot-v2",
            ),
            detail=HttpResourceSwitchDetail(
                switched_resources=["shared_http_client", "shared_task_dispatcher"],
                rollback_resources=["shared_http_client", "shared_task_dispatcher"],
            ),
        )

    def _raise_apply_failure(self) -> None:
        """
        模拟提交阶段失败。
        """

        raise RuntimeError("切换失败")

    def _raise_rollback_failure(self) -> list[str]:
        """
        模拟回滚阶段失败。
        """

        raise RuntimeError("恢复失败")

    def _raise_sensitive_apply_failure(self) -> None:
        """
        模拟包含敏感值的提交阶段失败。
        """

        raise RuntimeError(SENSITIVE_APPLY_FAILURE_REASON)

    def _raise_sensitive_rollback_failure(self) -> list[str]:
        """
        模拟包含敏感值的回滚阶段失败。
        """

        raise RuntimeError(SENSITIVE_ROLLBACK_FAILURE_REASON)
