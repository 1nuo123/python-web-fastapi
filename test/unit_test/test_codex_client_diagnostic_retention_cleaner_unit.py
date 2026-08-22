"""Codex 客户端诊断留存清理器的隔离单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import Mock, patch

import pytest

from src.core.logging_contract.log_event_contract import CODEX_CLIENT_DIAGNOSTIC_LOG_DETAIL_KIND
from src.infrastructure.codex.codex_client_diagnostic_retention_cleaner import (
    CODEX_CLIENT_PERFORMANCE_LOG_DETAIL_KIND,
    CodexClientDiagnosticRetentionCleaner,
)

FIXED_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=UTC)


def test_cleanup_expired_records_should_delete_each_category_and_commit_once() -> None:
    """错误按 14 天、性能按 30 天删除，并由同一 UoW 原子提交。"""

    control_port = Mock()
    unit_of_work = Mock()
    control_port.create_unit_of_work.return_value = unit_of_work
    with patch(
        "src.infrastructure.codex.codex_client_diagnostic_retention_cleaner.LogRecordRepositoryImpl"
    ) as repository_type:
        repository = repository_type.return_value
        repository.delete_records_by_detail_kind_before.side_effect = [3, 5]
        cleaner = CodexClientDiagnosticRetentionCleaner(
            control_port=control_port,
            error_retention_days=14,
            performance_retention_days=30,
            utc_now=lambda: FIXED_NOW,
        )

        result = cleaner.cleanup_expired_records()

    assert result.deleted_error_record_count == 3
    assert result.deleted_performance_record_count == 5
    assert repository.delete_records_by_detail_kind_before.call_args_list[0].kwargs == {
        "detail_kind": CODEX_CLIENT_DIAGNOSTIC_LOG_DETAIL_KIND,
        "occurred_before": datetime(2026, 8, 5, 12, 0, tzinfo=UTC),
    }
    assert repository.delete_records_by_detail_kind_before.call_args_list[1].kwargs == {
        "detail_kind": CODEX_CLIENT_PERFORMANCE_LOG_DETAIL_KIND,
        "occurred_before": datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
    }
    unit_of_work.commit.assert_called_once_with()
    unit_of_work.rollback.assert_not_called()
    unit_of_work.dispose.assert_called_once_with()


def test_cleanup_expired_records_when_repository_fails_should_rollback_and_dispose() -> None:
    """数据库错误不被吞掉，后台循环可据此在下一个周期重试。"""

    control_port = Mock()
    unit_of_work = Mock()
    control_port.create_unit_of_work.return_value = unit_of_work
    with patch(
        "src.infrastructure.codex.codex_client_diagnostic_retention_cleaner.LogRecordRepositoryImpl"
    ) as repository_type:
        repository_type.return_value.delete_records_by_detail_kind_before.side_effect = (
            RuntimeError("database unavailable")
        )
        cleaner = CodexClientDiagnosticRetentionCleaner(
            control_port=control_port,
            error_retention_days=14,
            performance_retention_days=30,
            utc_now=lambda: FIXED_NOW,
        )

        with pytest.raises(RuntimeError, match="database unavailable"):
            cleaner.cleanup_expired_records()

    unit_of_work.commit.assert_not_called()
    unit_of_work.rollback.assert_called_once_with()
    unit_of_work.dispose.assert_called_once_with()
