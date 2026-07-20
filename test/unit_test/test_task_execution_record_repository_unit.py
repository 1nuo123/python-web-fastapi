"""
任务执行记录仓储单元测试模块。
"""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionStage,
    TaskExecutionStatus,
)
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.persistence.repository_impl.task_execution_record_repository_impl import (
    TaskExecutionRecordRepositoryImpl,
    TaskExecutionRecordUpdatePayload,
)
from src.infrastructure.testing.task_execution_test_support import (
    TEST_QUEUE_NAME,
    TaskExecutionRecordBuilder,
    TaskExecutionStoreTestFactory,
)

INTEGRITY_ERROR_STATEMENT = "INSERT INTO task_execution_record"
TASK_EXECUTION_DEDUPE_UNIQUE_NAME = "uq_task_execution_record_job_kind_deduplication_key"
TASK_EXECUTION_RECORD_ID_UNIQUE_NAME = "uq_task_execution_record_record_id"
TEST_RECORD_ID_FIRST = "record-1"
TEST_RECORD_ID_SECOND = "record-2"
TEST_EXISTING_TASK_ID = "task-query-1"
TEST_RESERVED_TASK_ID = "task-query-2"
TEST_EXISTING_DEDUPLICATION_KEY = "dedupe-query-1"
TEST_RESERVED_DEDUPLICATION_KEY = "dedupe-query-2"
TEST_CREATED_AT_EPOCH_FIRST = 10
TEST_CREATED_AT_EPOCH_SECOND = 20
TEST_SORT_RECORD_ID_FIRST = "record-sort-1"
TEST_SORT_RECORD_ID_SECOND = "record-sort-2"
TEST_SORT_TASK_ID_FIRST = "task-sort-1"
TEST_SORT_TASK_ID_SECOND = "task-sort-2"
TEST_SORT_DEDUPLICATION_KEY_FIRST = "dedupe-sort-1"
TEST_SORT_DEDUPLICATION_KEY_SECOND = "dedupe-sort-2"
TEST_SORT_CREATED_AT_EPOCH = 30
TEST_QUERY_LIMIT = 10
TEST_NEGATIVE_LIMIT = -10
TEST_ATTEMPT_COUNT = 1
TEST_NEXT_RETRY_AT_EPOCH = 10
TEST_ERROR_TYPE = "RuntimeError"
TEST_ERROR_MESSAGE = "执行失败"


class IntegrityErrorDiagnostics:
    """
    完整性异常诊断信息测试替身。
    """

    def __init__(self, constraint_name: str) -> None:
        """
        初始化诊断信息。
        """

        self.constraint_name = constraint_name


class IntegrityErrorOriginal:
    """
    完整性异常原始错误测试替身。
    """

    def __init__(self, constraint_name: str) -> None:
        """
        初始化原始错误。
        """

        self.diag = IntegrityErrorDiagnostics(constraint_name)


class TestTaskExecutionRecordRepositoryUnit:
    """
    任务执行记录仓储单元测试集合。
    """

    def test_repository_when_insert_first_time_should_create_record(self) -> None:
        """
        验证仓储首次写入应创建记录。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        session = test_context.session_factory.create_session()
        try:
            repository = TaskExecutionRecordRepositoryImpl(session)
            result = repository.insert(TaskExecutionRecordBuilder().build())
            session.commit()

            assert result.created is True
            assert result.record.job_kind == "demo_task"
            assert result.record.backend == TaskBackend.LOCAL.value
        finally:
            session.close()
            test_context.close()

    def test_repository_when_duplicate_job_and_deduplication_key_should_raise(
        self,
    ) -> None:
        """
        验证仓储遇到重复任务键与去重键时把冲突交给外层工作单元处理。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        first_session = test_context.session_factory.create_session()
        second_session = test_context.session_factory.create_session()
        try:
            repository = TaskExecutionRecordRepositoryImpl(first_session)
            repository.insert(TaskExecutionRecordBuilder().build(record_id=TEST_RECORD_ID_FIRST))
            first_session.commit()

            duplicate_repository = TaskExecutionRecordRepositoryImpl(second_session)
            with pytest.raises(IntegrityError):
                duplicate_repository.insert(
                    TaskExecutionRecordBuilder().build(record_id=TEST_RECORD_ID_SECOND)
                )
            second_session.rollback()
        finally:
            first_session.close()
            second_session.close()
            test_context.close()

    def test_repository_should_query_by_task_id_and_list_records(self) -> None:
        """
        验证任务执行记录仓储支持正式查询面。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        session = test_context.session_factory.create_session()
        try:
            repository = TaskExecutionRecordRepositoryImpl(session)
            first_record = repository.insert(
                TaskExecutionRecordBuilder().build(
                    record_id=TEST_RECORD_ID_FIRST,
                    task_id=TEST_EXISTING_TASK_ID,
                    deduplication_key=TEST_EXISTING_DEDUPLICATION_KEY,
                    created_at_epoch=TEST_CREATED_AT_EPOCH_FIRST,
                    status=TaskExecutionStatus.SUCCESS,
                )
            ).record
            repository.insert(
                TaskExecutionRecordBuilder().build(
                    record_id=TEST_RECORD_ID_SECOND,
                    task_id=TEST_RESERVED_TASK_ID,
                    deduplication_key=TEST_RESERVED_DEDUPLICATION_KEY,
                    created_at_epoch=TEST_CREATED_AT_EPOCH_SECOND,
                    status=TaskExecutionStatus.RESERVED,
                )
            )
            session.commit()

            found_record = repository.get_by_task_id(TEST_EXISTING_TASK_ID)
            reserved_records = repository.list_records(
                limit=TEST_QUERY_LIMIT,
                status=TaskExecutionStatus.RESERVED,
            )

            assert found_record is not None
            assert found_record.record_id == first_record.record_id
            assert [record.task_id for record in reserved_records] == [TEST_RESERVED_TASK_ID]
        finally:
            session.close()
            test_context.close()

    def test_repository_list_should_normalize_limit_and_keep_stable_order(self) -> None:
        """
        验证任务执行记录列表查询会限制 limit 并保持稳定排序。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        session = test_context.session_factory.create_session()
        try:
            repository = TaskExecutionRecordRepositoryImpl(session)
            repository.insert(
                TaskExecutionRecordBuilder().build(
                    record_id=TEST_SORT_RECORD_ID_FIRST,
                    task_id=TEST_SORT_TASK_ID_FIRST,
                    deduplication_key=TEST_SORT_DEDUPLICATION_KEY_FIRST,
                    created_at_epoch=TEST_SORT_CREATED_AT_EPOCH,
                    status=TaskExecutionStatus.RESERVED,
                )
            )
            repository.insert(
                TaskExecutionRecordBuilder().build(
                    record_id=TEST_SORT_RECORD_ID_SECOND,
                    task_id=TEST_SORT_TASK_ID_SECOND,
                    deduplication_key=TEST_SORT_DEDUPLICATION_KEY_SECOND,
                    created_at_epoch=TEST_SORT_CREATED_AT_EPOCH,
                    status=TaskExecutionStatus.RESERVED,
                )
            )
            session.commit()

            records = repository.list_records(limit=TEST_NEGATIVE_LIMIT)

            assert [record.record_id for record in records] == [TEST_SORT_RECORD_ID_SECOND]
        finally:
            session.close()
            test_context.close()

    def test_repository_should_classify_dedupe_unique_constraint(self) -> None:
        """
        验证仓储只识别任务去重唯一约束冲突。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        session = test_context.session_factory.create_session()
        try:
            repository = TaskExecutionRecordRepositoryImpl(session)

            assert repository.is_dedupe_unique_constraint_violation(
                self._build_integrity_error(TASK_EXECUTION_DEDUPE_UNIQUE_NAME)
            )
            assert not repository.is_dedupe_unique_constraint_violation(
                self._build_integrity_error(TASK_EXECUTION_RECORD_ID_UNIQUE_NAME)
            )
        finally:
            session.close()
            test_context.close()

    def test_repository_when_update_fields_should_persist_status_and_stage(self) -> None:
        """
        验证仓储更新字段时应持久化状态、阶段和发布时间。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        session = test_context.session_factory.create_session()
        try:
            repository = TaskExecutionRecordRepositoryImpl(session)
            record = repository.insert(TaskExecutionRecordBuilder().build()).record
            repository.update_fields(
                record,
                TaskExecutionRecordUpdatePayload(
                    status=TaskExecutionStatus.RETRYING,
                    backend=TaskBackend.LOCAL,
                    stage=TaskExecutionStage.LOCAL_EXECUTION,
                    queue_name=TEST_QUEUE_NAME,
                    attempt_count=TEST_ATTEMPT_COUNT,
                    next_retry_at_epoch=TEST_NEXT_RETRY_AT_EPOCH,
                    published_at_epoch=TEST_CREATED_AT_EPOCH_SECOND,
                    last_error_type=TEST_ERROR_TYPE,
                    last_error_message=TEST_ERROR_MESSAGE,
                ),
            )
            session.commit()

            assert record.status == TaskExecutionStatus.RETRYING.value
            assert record.backend == TaskBackend.LOCAL.value
            assert record.stage == TaskExecutionStage.LOCAL_EXECUTION.value
            assert record.attempt_count == TEST_ATTEMPT_COUNT
            assert record.published_at_epoch == TEST_CREATED_AT_EPOCH_SECOND
        finally:
            session.close()
            test_context.close()

    def _build_integrity_error(self, constraint_name: str) -> IntegrityError:
        """
        构建完整性异常测试替身。
        """

        return IntegrityError(
            statement=INTEGRITY_ERROR_STATEMENT,
            params={},
            orig=IntegrityErrorOriginal(constraint_name),
        )
