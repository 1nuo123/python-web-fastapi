"""
任务执行记录契约测试模块。
"""

from __future__ import annotations

import pytest

from src.core.task_contract.task_execution_record_contract import (
    TASK_EXECUTION_DEDUPE_CREATED_DETAIL_KIND,
    TASK_EXECUTION_DEDUPE_EXISTING_DETAIL_KIND,
    TASK_EXECUTION_PENDING_DETAIL_KIND,
    TASK_EXECUTION_PUBLISHED_DETAIL_KIND,
    TASK_EXECUTION_RESERVED_DETAIL_KIND,
    TaskExecutionCreatedDetail,
    TaskExecutionDedupeDetailKind,
    TaskExecutionDedupeHeader,
    TaskExecutionDedupeResult,
    TaskExecutionExistingDetail,
    TaskExecutionFailedDetail,
    TaskExecutionPendingDetail,
    TaskExecutionPublishedDetail,
    TaskExecutionRecordDetailKind,
    TaskExecutionRecordEnvelope,
    TaskExecutionRecordHeader,
    TaskExecutionReservedDetail,
    TaskExecutionStage,
    TaskExecutionStatus,
    TaskExecutionSuccessDetail,
)
from src.core.task_contract.task_runtime_contract import TaskBackend

TEST_RECORD_ID = "record-1"
TEST_TASK_ID = "task-1"
TEST_JOB_KIND = "demo_task"
TEST_DEDUPLICATION_KEY = "dedupe-1"
TEST_REQUEST_ID = "request-1"
TEST_TRACE_ID = "trace-1"
TEST_QUEUE_NAME = "demo_task"
TEST_CREATED_AT_EPOCH = 1
TEST_PUBLISHED_AT_EPOCH = 2
TEST_EMPTY_ATTEMPT_COUNT = 0
UNEXPECTED_FIELD_NAME = "unexpected"


class TestTaskExecutionContract:
    """
    任务执行记录契约测试集合。
    """

    def test_task_execution_record_envelope_should_accept_pending_detail(self) -> None:
        """
        验证执行记录信封应接收等待态扩展。
        """

        envelope = TaskExecutionRecordEnvelope(
            header=self._build_header(TaskExecutionRecordDetailKind.PENDING),
            detail=TaskExecutionPendingDetail(attempt_count=TEST_EMPTY_ATTEMPT_COUNT),
        )

        assert envelope.detail.status == TaskExecutionStatus.PENDING
        assert envelope.header.backend == TaskBackend.LOCAL
        assert envelope.header.queue_name == TEST_QUEUE_NAME

    def test_task_execution_record_envelope_should_accept_reserved_and_published_detail(
        self,
    ) -> None:
        """
        验证执行记录信封应接收预占态和已发布态扩展。
        """

        reserved_envelope = TaskExecutionRecordEnvelope(
            header=self._build_header(TaskExecutionRecordDetailKind.RESERVED),
            detail=TaskExecutionReservedDetail(
                attempt_count=TEST_EMPTY_ATTEMPT_COUNT,
            ),
        )
        published_envelope = TaskExecutionRecordEnvelope(
            header=self._build_header(TaskExecutionRecordDetailKind.PUBLISHED),
            detail=TaskExecutionPublishedDetail(
                attempt_count=TEST_EMPTY_ATTEMPT_COUNT,
                published_at_epoch=TEST_PUBLISHED_AT_EPOCH,
            ),
        )

        assert reserved_envelope.detail.kind == TASK_EXECUTION_RESERVED_DETAIL_KIND
        assert reserved_envelope.detail.status == TaskExecutionStatus.RESERVED
        assert published_envelope.detail.kind == TASK_EXECUTION_PUBLISHED_DETAIL_KIND
        assert published_envelope.detail.status == TaskExecutionStatus.PUBLISHED

    def test_task_execution_record_envelope_when_schema_version_mismatch_should_fail(
        self,
    ) -> None:
        """
        验证执行记录信封当版本不一致应失败。
        """

        with pytest.raises(ValueError):
            TaskExecutionRecordEnvelope(
                header=self._build_header(TaskExecutionRecordDetailKind.SUCCESS),
                detail=TaskExecutionSuccessDetail.model_validate(
                    {
                        "kind": TaskExecutionRecordDetailKind.SUCCESS.value,
                        "schema_version": "2.0",
                        "status": "SUCCESS",
                        "stage": TaskExecutionStage.LOCAL_EXECUTION.value,
                        "attempt_count": 1,
                        "finished_at_epoch": 2,
                    }
                ),
            )

    def test_task_execution_record_detail_union_should_accept_failed_detail(self) -> None:
        """
        验证执行记录扩展联合应接收失败态扩展。
        """

        detail = TaskExecutionFailedDetail(
            attempt_count=2,
            failed_at_epoch=3,
            last_error_type="RuntimeError",
            last_error_message="执行失败",
            stage=TaskExecutionStage.LOCAL_EXECUTION,
        )

        assert detail.status == TaskExecutionStatus.FAILED
        assert detail.stage == TaskExecutionStage.LOCAL_EXECUTION

    def test_task_execution_record_envelope_when_detail_kind_mismatch_should_fail(
        self,
    ) -> None:
        """
        验证执行记录信封当扩展类型不一致应失败。
        """

        with pytest.raises(ValueError):
            TaskExecutionRecordEnvelope(
                header=self._build_header(TaskExecutionRecordDetailKind.SUCCESS),
                detail=TaskExecutionPendingDetail(
                    attempt_count=TEST_EMPTY_ATTEMPT_COUNT,
                ),
            )

    def test_task_execution_detail_when_extra_field_should_fail(self) -> None:
        """
        验证执行记录扩展字段禁止额外字段。
        """

        with pytest.raises(ValueError):
            TaskExecutionPendingDetail.model_validate(
                {
                    "kind": TASK_EXECUTION_PENDING_DETAIL_KIND,
                    "schema_version": "1.0",
                    "status": TaskExecutionStatus.PENDING.value,
                    "stage": TaskExecutionStage.DISPATCH.value,
                    "attempt_count": TEST_EMPTY_ATTEMPT_COUNT,
                    UNEXPECTED_FIELD_NAME: "value",
                }
            )

    def test_task_execution_dedupe_result_should_validate_created_and_existing(
        self,
    ) -> None:
        """
        验证任务去重结果区分新建记录和已存在记录。
        """

        created_result = TaskExecutionDedupeResult(
            header=self._build_dedupe_header(TaskExecutionDedupeDetailKind.CREATED),
            detail=TaskExecutionCreatedDetail(status=TaskExecutionStatus.RESERVED),
        )
        existing_result = TaskExecutionDedupeResult(
            header=self._build_dedupe_header(TaskExecutionDedupeDetailKind.EXISTING),
            detail=TaskExecutionExistingDetail(status=TaskExecutionStatus.RESERVED),
        )

        assert created_result.detail.kind == TASK_EXECUTION_DEDUPE_CREATED_DETAIL_KIND
        assert created_result.detail.created is True
        assert existing_result.detail.kind == TASK_EXECUTION_DEDUPE_EXISTING_DETAIL_KIND
        assert existing_result.detail.created is False
        assert created_result.header.detail_kind.value == created_result.detail.kind
        assert existing_result.header.detail_kind.value == existing_result.detail.kind

    def test_task_execution_dedupe_result_when_detail_kind_mismatch_should_fail(
        self,
    ) -> None:
        """
        验证任务去重结果公共头与扩展类型不一致时失败。
        """

        with pytest.raises(ValueError):
            TaskExecutionDedupeResult(
                header=self._build_dedupe_header(TaskExecutionDedupeDetailKind.CREATED),
                detail=TaskExecutionExistingDetail(status=TaskExecutionStatus.RESERVED),
            )

    def _build_header(
        self,
        detail_kind: TaskExecutionRecordDetailKind,
    ) -> TaskExecutionRecordHeader:
        """
        构建执行记录公共头。
        """

        return TaskExecutionRecordHeader(
            detail_kind=detail_kind,
            record_id=TEST_RECORD_ID,
            task_id=TEST_TASK_ID,
            job_kind=TEST_JOB_KIND,
            deduplication_key=TEST_DEDUPLICATION_KEY,
            backend=TaskBackend.LOCAL,
            queue_name=TEST_QUEUE_NAME,
            request_id=TEST_REQUEST_ID,
            trace_id=TEST_TRACE_ID,
            created_at_epoch=TEST_CREATED_AT_EPOCH,
        )

    def _build_dedupe_header(
        self,
        detail_kind: TaskExecutionDedupeDetailKind,
    ) -> TaskExecutionDedupeHeader:
        """
        构建任务去重结果公共头。
        """

        return TaskExecutionDedupeHeader(
            detail_kind=detail_kind,
            record_id=TEST_RECORD_ID,
            job_kind=TEST_JOB_KIND,
            deduplication_key=TEST_DEDUPLICATION_KEY,
        )
