"""
任务执行记录集成测试模块。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text

from src.cli.run_database_migrations import DatabaseMigrationCli
from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionDedupeDetailKind,
    TaskExecutionStage,
    TaskExecutionStatus,
)
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.persistence.sqlalchemy_engine_factory import (
    SqlAlchemyEngineFactory,
)
from src.infrastructure.persistence.sqlalchemy_session_factory import (
    SqlAlchemySessionFactory,
)
from src.infrastructure.resource_slot.shared_db_session_manager import (
    SharedDbSessionManager,
)
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.task.task_execution_store import (
    TaskExecutionStore,
    TaskExecutionStoreResult,
)
from src.infrastructure.testing.task_execution_test_support import (
    TEST_QUEUE_NAME,
    TaskExecutionRecordBuilder,
    TaskExecutionStoreTestFactory,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
]


TASK_EXECUTION_CONCURRENT_WORKERS = 4
TASK_EXECUTION_CONCURRENT_RECORD_PREFIX = "record-concurrent"
TASK_EXECUTION_CONCURRENT_TASK_PREFIX = "task-concurrent"
TASK_EXECUTION_POSTGRES_RECORD_PREFIX = "record-postgres"
TASK_EXECUTION_POSTGRES_TASK_PREFIX = "task-postgres"
TASK_EXECUTION_POSTGRES_JOB_PREFIX = "postgres_dedup"
TASK_EXECUTION_RECORD_CLEANUP_SQL = "DELETE FROM task_execution_record WHERE job_kind = :job_kind"
JOB_KIND_BIND_NAME = "job_kind"


class TestTaskExecutionRecordIntegration:
    """
    任务执行记录集成测试集合。
    """

    def test_task_execution_store_should_persist_status_transitions(self) -> None:
        """
        验证任务执行记录存储应持久化状态流转。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        try:
            store = test_context.store
            store.reserve(record=TaskExecutionRecordBuilder().build())
            running_record = store.mark_running(
                job_kind="demo_task",
                deduplication_key="demo-deduplication-key",
                attempt_count=0,
                backend=TaskBackend.LOCAL,
                queue_name=TEST_QUEUE_NAME,
                stage=TaskExecutionStage.LOCAL_EXECUTION,
            )
            retrying_record = store.mark_retrying(
                job_kind="demo_task",
                deduplication_key="demo-deduplication-key",
                attempt_count=1,
                next_retry_at_epoch=10,
                last_error_type="RuntimeError",
                last_error_message="首次失败",
                backend=TaskBackend.LOCAL,
                queue_name=TEST_QUEUE_NAME,
                stage=TaskExecutionStage.LOCAL_EXECUTION,
            )
            success_record = store.mark_success(
                job_kind="demo_task",
                deduplication_key="demo-deduplication-key",
                attempt_count=2,
                backend=TaskBackend.LOCAL,
                queue_name=TEST_QUEUE_NAME,
                stage=TaskExecutionStage.LOCAL_EXECUTION,
            )

            assert running_record.status == TaskExecutionStatus.RUNNING.value
            assert retrying_record.status == TaskExecutionStatus.RETRYING.value
            assert success_record.status == TaskExecutionStatus.SUCCESS.value
            assert success_record.backend == TaskBackend.LOCAL.value
            assert success_record.queue_name == TEST_QUEUE_NAME
            assert success_record.stage == TaskExecutionStage.LOCAL_EXECUTION.value
        finally:
            test_context.close()

    def test_task_execution_store_should_reuse_record_when_concurrent_dedup(
        self,
    ) -> None:
        """
        验证并发预占同一去重键时复用同一记录。
        """

        test_context = TaskExecutionStoreTestFactory().create()
        try:
            barrier = Barrier(TASK_EXECUTION_CONCURRENT_WORKERS)
            with ThreadPoolExecutor(max_workers=TASK_EXECUTION_CONCURRENT_WORKERS) as executor:
                futures = [
                    executor.submit(
                        self._reserve_record_with_barrier,
                        store=test_context.store,
                        barrier=barrier,
                        index=index,
                    )
                    for index in range(TASK_EXECUTION_CONCURRENT_WORKERS)
                ]
                results = [future.result() for future in futures]

            record_ids = {result.record.record_id for result in results}
            dedupe_kinds = {result.dedupe_result.header.detail_kind for result in results}

            assert len(record_ids) == 1
            assert [result.created for result in results].count(True) == 1
            assert TaskExecutionDedupeDetailKind.CREATED in dedupe_kinds
            assert TaskExecutionDedupeDetailKind.EXISTING in dedupe_kinds
        finally:
            test_context.close()

    def test_task_execution_store_should_reuse_record_on_migrated_postgresql_schema(
        self,
    ) -> None:
        """
        验证 Alembic 迁移后的 PostgreSQL schema 支持并发去重。
        """

        DatabaseMigrationCli().execute()
        settings = AppSettingsLoader().load()
        engine = SqlAlchemyEngineFactory().build(settings.runtime.database)
        session_manager = SharedDbSessionManager(SqlAlchemySessionFactory(engine))
        store = TaskExecutionStore(session_manager=session_manager)
        job_kind = f"{TASK_EXECUTION_POSTGRES_JOB_PREFIX}_{uuid4().hex}"
        deduplication_key = str(uuid4())
        try:
            barrier = Barrier(TASK_EXECUTION_CONCURRENT_WORKERS)
            with ThreadPoolExecutor(max_workers=TASK_EXECUTION_CONCURRENT_WORKERS) as executor:
                futures = [
                    executor.submit(
                        self._reserve_postgres_record_with_barrier,
                        store=store,
                        barrier=barrier,
                        index=index,
                        job_kind=job_kind,
                        deduplication_key=deduplication_key,
                    )
                    for index in range(TASK_EXECUTION_CONCURRENT_WORKERS)
                ]
                results = [future.result() for future in futures]

            record_ids = {result.record.record_id for result in results}
            dedupe_kinds = {result.dedupe_result.header.detail_kind for result in results}

            assert len(record_ids) == 1
            assert [result.created for result in results].count(True) == 1
            assert TaskExecutionDedupeDetailKind.CREATED in dedupe_kinds
            assert TaskExecutionDedupeDetailKind.EXISTING in dedupe_kinds
        finally:
            with engine.begin() as connection:
                connection.execute(
                    text(TASK_EXECUTION_RECORD_CLEANUP_SQL),
                    {JOB_KIND_BIND_NAME: job_kind},
                )
            session_manager.close()

    def _reserve_record_with_barrier(
        self,
        *,
        store: TaskExecutionStore,
        barrier: Barrier,
        index: int,
    ) -> TaskExecutionStoreResult:
        """
        等待并发屏障后预占任务执行记录。
        """

        barrier.wait()
        return store.reserve(
            record=TaskExecutionRecordBuilder().build(
                record_id=f"{TASK_EXECUTION_CONCURRENT_RECORD_PREFIX}-{index}",
                task_id=f"{TASK_EXECUTION_CONCURRENT_TASK_PREFIX}-{index}",
            )
        )

    def _reserve_postgres_record_with_barrier(
        self,
        *,
        store: TaskExecutionStore,
        barrier: Barrier,
        index: int,
        job_kind: str,
        deduplication_key: str,
    ) -> TaskExecutionStoreResult:
        """
        等待并发屏障后在 PostgreSQL schema 上预占任务执行记录。
        """

        barrier.wait()
        return store.reserve(
            record=TaskExecutionRecordBuilder().build(
                record_id=f"{TASK_EXECUTION_POSTGRES_RECORD_PREFIX}-{index}",
                task_id=f"{TASK_EXECUTION_POSTGRES_TASK_PREFIX}-{index}",
                job_kind=job_kind,
                deduplication_key=deduplication_key,
            )
        )
