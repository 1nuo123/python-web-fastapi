"""
任务执行记录仓储实现模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import cast

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.core.persistence_contract.repository_contract import Repository
from src.core.task_contract.task_execution_record_contract import (
    TaskExecutionStage,
    TaskExecutionStatus,
)
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.persistence.orm_model.task_execution_record_orm_model import (
    TASK_EXECUTION_RECORD_UNIQUE_NAME,
    TaskExecutionRecordOrmModel,
)

TASK_EXECUTION_RECORD_LIST_MIN_LIMIT = 1
TASK_EXECUTION_RECORD_LIST_MAX_LIMIT = 200
TASK_EXECUTION_DEDUPE_CONFLICT_MESSAGE = "任务执行记录唯一键冲突后未能回查到既有记录。"
TASK_EXECUTION_DEDUPE_JOB_KIND_COLUMN_NAME = "job_kind"
TASK_EXECUTION_DEDUPE_KEY_COLUMN_NAME = "deduplication_key"
SQLALCHEMY_ORIGINAL_EXCEPTION_ATTRIBUTE = "orig"
PSYCOPG_DIAGNOSTICS_ATTRIBUTE = "diag"
PSYCOPG_CONSTRAINT_NAME_ATTRIBUTE = "constraint_name"


class TaskExecutionDedupeConflictLookupError(RuntimeError):
    """
    任务执行去重冲突回查失败错误。
    """


@dataclass(slots=True)
class TaskExecutionRecordUpsertResult:
    """
    任务执行记录写入结果。
    """

    record: TaskExecutionRecordOrmModel
    created: bool


class TaskExecutionRecordUpdatePayload(BaseModel):
    """
    任务执行记录更新载荷。
    """

    model_config = ConfigDict(extra="forbid")

    status: TaskExecutionStatus | None = None
    backend: TaskBackend | None = None
    stage: TaskExecutionStage | None = None
    queue_name: str | None = None
    attempt_count: int | None = None
    next_retry_at_epoch: int | None = None
    started_at_epoch: int | None = None
    finished_at_epoch: int | None = None
    failed_at_epoch: int | None = None
    published_at_epoch: int | None = None
    last_error_type: str | None = None
    last_error_message: str | None = None


class TaskExecutionRecordRepositoryImpl(Repository):
    """
    任务执行记录仓储实现。
    """

    def __init__(self, session: Session) -> None:
        """
        初始化任务执行记录仓储。
        """

        self._session = session

    def ping(self) -> bool:
        """
        探测仓储依赖是否可用。
        """

        self._session.execute(select(1))
        return True

    def get_by_job_and_deduplication_key(
        self,
        *,
        job_kind: str,
        deduplication_key: str,
        lock_for_update: bool = False,
    ) -> TaskExecutionRecordOrmModel | None:
        """
        根据任务键与去重键获取执行记录。
        """

        statement: Select[tuple[TaskExecutionRecordOrmModel]] = select(
            TaskExecutionRecordOrmModel
        ).where(
            TaskExecutionRecordOrmModel.job_kind == job_kind,
            TaskExecutionRecordOrmModel.deduplication_key == deduplication_key,
        )
        if lock_for_update:
            statement = statement.with_for_update()
        return self._session.execute(statement).scalar_one_or_none()

    def get_by_task_id(self, task_id: str) -> TaskExecutionRecordOrmModel | None:
        """
        按任务标识获取执行记录。
        """

        statement: Select[tuple[TaskExecutionRecordOrmModel]] = (
            select(TaskExecutionRecordOrmModel)
            .where(TaskExecutionRecordOrmModel.task_id == task_id)
            .limit(1)
        )
        return self._session.execute(statement).scalars().first()

    def list_records(
        self,
        *,
        limit: int,
        status: TaskExecutionStatus | None = None,
        job_kind: str | None = None,
    ) -> list[TaskExecutionRecordOrmModel]:
        """
        查询任务执行记录。
        """

        effective_limit = self._normalize_limit(limit)
        statement: Select[tuple[TaskExecutionRecordOrmModel]] = (
            select(TaskExecutionRecordOrmModel)
            .order_by(
                TaskExecutionRecordOrmModel.created_at_epoch.desc(),
                TaskExecutionRecordOrmModel.record_id.desc(),
            )
            .limit(effective_limit)
        )
        if status is not None:
            statement = statement.where(TaskExecutionRecordOrmModel.status == status.value)
        if job_kind is not None:
            statement = statement.where(TaskExecutionRecordOrmModel.job_kind == job_kind)
        return list(self._session.execute(statement).scalars().all())

    def _normalize_limit(self, limit: int) -> int:
        if limit < TASK_EXECUTION_RECORD_LIST_MIN_LIMIT:
            return TASK_EXECUTION_RECORD_LIST_MIN_LIMIT
        return min(limit, TASK_EXECUTION_RECORD_LIST_MAX_LIMIT)

    def insert(
        self,
        record: TaskExecutionRecordOrmModel,
    ) -> TaskExecutionRecordUpsertResult:
        """
        写入任务执行记录，唯一键冲突交由外层工作单元处理。
        """

        self._session.add(record)
        self._session.flush()
        return TaskExecutionRecordUpsertResult(record=record, created=True)

    def update_fields(
        self,
        record: TaskExecutionRecordOrmModel,
        patch: TaskExecutionRecordUpdatePayload,
    ) -> TaskExecutionRecordOrmModel:
        """
        更新记录字段。
        """

        for field_name, field_value in patch.model_dump(exclude_none=True).items():
            if isinstance(field_value, Enum):
                setattr(record, field_name, field_value.value)
                continue
            setattr(record, field_name, field_value)
        self._session.flush()
        return record

    def update_fields_when_status_in(
        self,
        record: TaskExecutionRecordOrmModel,
        patch: TaskExecutionRecordUpdatePayload,
        allowed_statuses: frozenset[TaskExecutionStatus],
    ) -> bool:
        """仅在当前数据库状态允许时原子更新记录字段。"""

        patch_values: dict[str, object] = {}
        for field_name, field_value in patch.model_dump(exclude_none=True).items():
            patch_values[field_name] = (
                field_value.value if isinstance(field_value, Enum) else field_value
            )
        statement = (
            update(TaskExecutionRecordOrmModel)
            .where(
                TaskExecutionRecordOrmModel.task_execution_record_id
                == record.task_execution_record_id,
                TaskExecutionRecordOrmModel.status.in_(status.value for status in allowed_statuses),
            )
            .values(**patch_values)
        )
        result = cast(
            CursorResult[tuple[object]],
            self._session.execute(statement),
        )
        self._session.flush()
        self._session.refresh(record)
        return result.rowcount > 0

    def is_dedupe_unique_constraint_violation(self, exc: IntegrityError) -> bool:
        """
        判断完整性异常是否来自任务去重唯一约束。
        """

        constraint_name = self._read_integrity_constraint_name(exc)
        if constraint_name is not None:
            return constraint_name == TASK_EXECUTION_RECORD_UNIQUE_NAME
        original_message = str(getattr(exc, SQLALCHEMY_ORIGINAL_EXCEPTION_ATTRIBUTE, exc))
        return TASK_EXECUTION_RECORD_UNIQUE_NAME in original_message or (
            TASK_EXECUTION_DEDUPE_JOB_KIND_COLUMN_NAME in original_message
            and TASK_EXECUTION_DEDUPE_KEY_COLUMN_NAME in original_message
        )

    def _read_integrity_constraint_name(self, exc: IntegrityError) -> str | None:
        """
        读取数据库驱动暴露的约束名称。
        """

        original_error = getattr(exc, SQLALCHEMY_ORIGINAL_EXCEPTION_ATTRIBUTE, None)
        diagnostics = getattr(
            original_error,
            PSYCOPG_DIAGNOSTICS_ATTRIBUTE,
            None,
        )
        constraint_name = getattr(
            diagnostics,
            PSYCOPG_CONSTRAINT_NAME_ATTRIBUTE,
            None,
        )
        if constraint_name is None:
            return None
        return str(constraint_name)
