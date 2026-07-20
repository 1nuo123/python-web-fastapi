"""
任务执行记录测试辅助模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.sql.schema import Table

from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionStage,
    TaskExecutionStatus,
)
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.persistence.orm_model.task_execution_outbox_orm_model import (
    TaskExecutionOutboxOrmModel,
)
from src.infrastructure.persistence.orm_model.task_execution_record_orm_model import (
    TaskExecutionRecordOrmModel,
)
from src.infrastructure.persistence.sqlalchemy_session_factory import (
    SqlAlchemySessionFactory,
)
from src.infrastructure.resource_slot.shared_db_session_manager import (
    SharedDbSessionManager,
)
from src.infrastructure.task.task_execution_store import TaskExecutionStore

TEST_TASK_EXECUTION_DATABASE_FILE_NAME = "task_execution_test.sqlite3"
SQLITE_FILE_URL_TEMPLATE = "sqlite+pysqlite:///{database_path}"
TEST_RECORD_ID = "record-1"
TEST_TASK_ID = "task-1"
TEST_JOB_KIND = "demo_task"
TEST_DEDUPLICATION_KEY = "demo-deduplication-key"
TEST_REQUEST_ID = "request-1"
TEST_TRACE_ID = "trace-1"
TEST_QUEUE_NAME = "demo_queue"
TEST_PAYLOAD_KIND = "DemoPayload"
TEST_PAYLOAD_JSON = '{"kind":"demo","schema_version":"1.0"}'
TEST_CREATED_AT_EPOCH = 1
TEST_TASK_BACKEND = TaskBackend.LOCAL
TEST_DEFAULT_ATTEMPT_COUNT = 0


@dataclass(slots=True)
class TaskExecutionTestContext:
    """
    任务执行记录测试上下文。
    """

    store: TaskExecutionStore
    session_manager: SharedDbSessionManager
    session_factory: SqlAlchemySessionFactory
    temporary_directory: TemporaryDirectory[str]

    def close(self) -> None:
        """
        释放测试资源。
        """

        self.session_manager.close()
        self.temporary_directory.cleanup()


class TaskExecutionStoreTestFactory:
    """
    任务执行记录存储测试工厂。
    """

    def create(self) -> TaskExecutionTestContext:
        """
        创建测试上下文。
        """

        temporary_directory = TemporaryDirectory()
        database_path = Path(temporary_directory.name) / TEST_TASK_EXECUTION_DATABASE_FILE_NAME
        engine = create_engine(
            SQLITE_FILE_URL_TEMPLATE.format(database_path=database_path.as_posix()),
        )
        cast(Table, TaskExecutionRecordOrmModel.__table__).create(bind=engine)
        cast(Table, TaskExecutionOutboxOrmModel.__table__).create(bind=engine)
        session_factory = SqlAlchemySessionFactory(engine)
        session_manager = SharedDbSessionManager(session_factory)
        return TaskExecutionTestContext(
            store=TaskExecutionStore(session_manager=session_manager),
            session_manager=session_manager,
            session_factory=session_factory,
            temporary_directory=temporary_directory,
        )


class TaskExecutionRecordBuilder:
    """
    任务执行记录构造器。
    """

    def build(
        self,
        *,
        record_id: str = TEST_RECORD_ID,
        task_id: str = TEST_TASK_ID,
        job_kind: str = TEST_JOB_KIND,
        deduplication_key: str = TEST_DEDUPLICATION_KEY,
        request_id: str = TEST_REQUEST_ID,
        trace_id: str | None = TEST_TRACE_ID,
        created_at_epoch: int = TEST_CREATED_AT_EPOCH,
        status: TaskExecutionStatus = TaskExecutionStatus.RESERVED,
        backend: TaskBackend = TEST_TASK_BACKEND,
        stage: TaskExecutionStage = TaskExecutionStage.DISPATCH,
        attempt_count: int = TEST_DEFAULT_ATTEMPT_COUNT,
        queue_name: str = TEST_QUEUE_NAME,
        payload_kind: str = TEST_PAYLOAD_KIND,
        payload_json: str = TEST_PAYLOAD_JSON,
    ) -> TaskExecutionRecordOrmModel:
        """
        构建执行记录 ORM 对象。
        """

        return TaskExecutionRecordOrmModel(
            task_execution_record_id=uuid4(),
            record_id=record_id,
            task_id=task_id,
            job_kind=job_kind,
            deduplication_key=deduplication_key,
            request_id=request_id,
            trace_id=trace_id,
            created_at_epoch=created_at_epoch,
            backend=backend.value,
            status=status.value,
            stage=stage.value,
            attempt_count=attempt_count,
            queue_name=queue_name,
            payload_kind=payload_kind,
            payload_json=payload_json,
            published_at_epoch=created_at_epoch,
        )
