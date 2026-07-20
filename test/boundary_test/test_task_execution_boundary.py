"""
任务执行边界测试模块。
"""

from __future__ import annotations

import pytest

from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionReservedDetail,
    TaskExecutionRetryingDetail,
    TaskExecutionStage,
)
from src.infrastructure.task.local_task_dispatcher import LocalTaskDispatcher

TEST_EMPTY_ATTEMPT_COUNT = 0
TEST_NEGATIVE_ATTEMPT_COUNT = -1
TEST_RETRY_DELAY_SECONDS = 5
TEST_RETRY_BACKOFF_MULTIPLIER = 4
TEST_RETRY_MAX_DELAY_SECONDS = 12
TEST_RETRY_ATTEMPT_COUNT = 3
TEST_RETRY_LIMIT = 10
TEST_NEXT_RETRY_AT_EPOCH = 10


class TestTaskExecutionBoundary:
    """
    任务执行边界测试集合。
    """

    def test_task_execution_reserved_detail_when_attempt_count_zero_should_pass(
        self,
    ) -> None:
        """
        验证预占态扩展在重试次数为零时应通过。
        """

        detail = TaskExecutionReservedDetail(attempt_count=TEST_EMPTY_ATTEMPT_COUNT)
        assert detail.attempt_count == TEST_EMPTY_ATTEMPT_COUNT

    def test_task_execution_retrying_detail_when_attempt_count_negative_should_fail(
        self,
    ) -> None:
        """
        验证重试态扩展在重试次数为负数时应失败。
        """

        with pytest.raises(ValueError):
            TaskExecutionRetryingDetail(
                attempt_count=TEST_NEGATIVE_ATTEMPT_COUNT,
                stage=TaskExecutionStage.LOCAL_EXECUTION,
                next_retry_at_epoch=TEST_NEXT_RETRY_AT_EPOCH,
                last_error_type="RuntimeError",
                last_error_message="失败",
            )

    def test_local_task_dispatcher_when_retry_delay_exceeds_max_should_cap_delay(
        self,
    ) -> None:
        """
        验证本地分发器当退避时间超上限时应截断。
        """

        dispatcher = object.__new__(LocalTaskDispatcher)
        dispatcher._retry_delay_seconds = TEST_RETRY_DELAY_SECONDS  # noqa: SLF001
        dispatcher._retry_backoff_multiplier = TEST_RETRY_BACKOFF_MULTIPLIER  # noqa: SLF001
        dispatcher._retry_max_delay_seconds = TEST_RETRY_MAX_DELAY_SECONDS  # noqa: SLF001

        delay_seconds = dispatcher._resolve_retry_delay(  # noqa: SLF001
            attempt_count=TEST_RETRY_ATTEMPT_COUNT,
            retry_limit=TEST_RETRY_LIMIT,
        )

        assert delay_seconds == TEST_RETRY_MAX_DELAY_SECONDS
