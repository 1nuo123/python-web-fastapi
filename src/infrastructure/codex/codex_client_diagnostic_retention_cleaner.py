"""Codex 客户端诊断日志的幂等留存清理实现。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy.orm import Session

from src.application.ports.codex_control_port import CodexControlPort
from src.core.logging_contract.log_event_contract import (
    CODEX_CLIENT_DIAGNOSTIC_LOG_DETAIL_KIND,
    CODEX_CLIENT_PERFORMANCE_LOG_DETAIL_KIND,
)
from src.infrastructure.persistence.repository_impl.log_record_repository_impl import (
    LogRecordRepositoryImpl,
)


@dataclass(frozen=True, slots=True)
class CodexClientDiagnosticRetentionResult:
    """一次留存清理的无敏感结果快照。"""

    deleted_error_record_count: int
    deleted_performance_record_count: int


class CodexClientDiagnosticRetentionCleaner:
    """复用日志仓储与 UoW 清理客户端诊断和性能样本。"""

    def __init__(
        self,
        *,
        control_port: CodexControlPort,
        error_retention_days: int,
        performance_retention_days: int,
        utc_now: Callable[[], datetime] | None = None,
    ) -> None:
        """
        初始化诊断留存清理器。

        清理器不维护任务状态或删除游标：删除条件完全由固定详情类型与截止时间定义，
        因而进程重启、失败重试和多实例并发都会自然收敛为幂等删除。事务仍仅由
        既有 UoW 控制，仓储不会自行提交或回滚。

        :param control_port: 提供既有 UoW 的 Codex 控制面端口。
        :type control_port: CodexControlPort
        :param error_retention_days: 客户端错误诊断最长留存天数。
        :type error_retention_days: int
        :param performance_retention_days: 客户端性能样本最长留存天数。
        :type performance_retention_days: int
        :param utc_now: 可注入的 UTC 时间源，用于确定性边界测试。
        :type utc_now: Callable[[], datetime] | None
        """

        self._control_port = control_port
        self._error_retention_days = error_retention_days
        self._performance_retention_days = performance_retention_days
        self._utc_now = utc_now or self._read_utc_now

    def cleanup_expired_records(self) -> CodexClientDiagnosticRetentionResult:
        """
        在同一事务中删除超过错误和性能留存期限的记录。

        :returns: 两类记录各自的删除计数。
        :rtype: CodexClientDiagnosticRetentionResult
        :raises BaseException: 数据库异常由调用方的后台循环记录并在下个周期重试。
        """

        now = self._utc_now()
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = LogRecordRepositoryImpl(cast(Session, unit_of_work.get_session()))
            deleted_error_record_count = repository.delete_records_by_detail_kind_before(
                detail_kind=CODEX_CLIENT_DIAGNOSTIC_LOG_DETAIL_KIND,
                occurred_before=now - timedelta(days=self._error_retention_days),
            )
            deleted_performance_record_count = repository.delete_records_by_detail_kind_before(
                detail_kind=CODEX_CLIENT_PERFORMANCE_LOG_DETAIL_KIND,
                occurred_before=now - timedelta(days=self._performance_retention_days),
            )
            unit_of_work.commit()
            return CodexClientDiagnosticRetentionResult(
                deleted_error_record_count=deleted_error_record_count,
                deleted_performance_record_count=deleted_performance_record_count,
            )
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    @staticmethod
    def _read_utc_now() -> datetime:
        """提供时区明确的默认时间源，避免本地时区影响留存边界。"""

        return datetime.now(UTC)
