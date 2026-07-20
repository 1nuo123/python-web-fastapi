"""
任务执行异常测试模块。
"""

from __future__ import annotations

import pytest

from src.core.task_contract.task_execution_record_contract import TaskExecutionStage
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.task.task_execution_store import (
    TASK_EXECUTION_RECORD_NOT_FOUND_MESSAGE,
    TaskExecutionRecordNotFoundError,
)
from src.infrastructure.testing.task_execution_test_support import (
    TEST_QUEUE_NAME,
    TaskExecutionStoreTestFactory,
)

MISSING_JOB_KIND = "missing_job"
MISSING_DEDUPLICATION_KEY = "missing_key"
MISSING_ATTEMPT_COUNT = 1
MISSING_FAILED_AT_EPOCH = 10
MISSING_LAST_ERROR_TYPE = "RuntimeError"
MISSING_LAST_ERROR_MESSAGE = "失败"


class TestTaskExecutionException:
    """
    任务执行异常测试集合。
    """

    def test_mark_failed_when_record_missing_should_raise_not_found_error(self) -> None:
        """
        验证标记失败时若记录不存在应抛出专用异常。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        try:
            with pytest.raises(TaskExecutionRecordNotFoundError) as exc_info:
                test_context.store.mark_failed(
                    job_kind=MISSING_JOB_KIND,
                    deduplication_key=MISSING_DEDUPLICATION_KEY,
                    attempt_count=MISSING_ATTEMPT_COUNT,
                    failed_at_epoch=MISSING_FAILED_AT_EPOCH,
                    last_error_type=MISSING_LAST_ERROR_TYPE,
                    last_error_message=MISSING_LAST_ERROR_MESSAGE,
                    backend=TaskBackend.LOCAL,
                    queue_name=TEST_QUEUE_NAME,
                    stage=TaskExecutionStage.LOCAL_EXECUTION,
                )

            assert TASK_EXECUTION_RECORD_NOT_FOUND_MESSAGE in str(exc_info.value)
        finally:
            test_context.close()

    def test_try_mark_failed_when_record_missing_should_return_none(self) -> None:
        """
        验证宽容失败标记在记录缺失时返回空值。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        try:
            result = test_context.store.try_mark_failed(
                job_kind=MISSING_JOB_KIND,
                deduplication_key=MISSING_DEDUPLICATION_KEY,
                attempt_count=MISSING_ATTEMPT_COUNT,
                failed_at_epoch=MISSING_FAILED_AT_EPOCH,
                last_error_type=MISSING_LAST_ERROR_TYPE,
                last_error_message=MISSING_LAST_ERROR_MESSAGE,
                backend=TaskBackend.LOCAL,
                queue_name=TEST_QUEUE_NAME,
                stage=TaskExecutionStage.LOCAL_EXECUTION,
            )

            assert result is None
        finally:
            test_context.close()
