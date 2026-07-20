"""
任务执行 Outbox 仓储实现模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from src.core.persistence_contract.repository_contract import Repository
from src.infrastructure.persistence.orm_model.task_execution_outbox_orm_model import (
    TaskExecutionOutboxOrmModel,
    TaskExecutionOutboxStatus,
)

TASK_EXECUTION_OUTBOX_LIST_MIN_LIMIT = 1
TASK_EXECUTION_OUTBOX_LIST_MAX_LIMIT = 200


@dataclass(slots=True)
class TaskExecutionOutboxInsertResult:
    """
    任务执行 Outbox 写入结果。
    """

    record: TaskExecutionOutboxOrmModel


class TaskExecutionOutboxUpdatePayload(BaseModel):
    """
    任务执行 Outbox 更新载荷。
    """

    model_config = ConfigDict(extra="forbid")

    status: TaskExecutionOutboxStatus | None = None
    published_at_epoch: int | None = None
    failed_at_epoch: int | None = None
    failure_reason: str | None = None


class TaskExecutionOutboxRepositoryImpl(Repository):
    """
    任务执行 Outbox 仓储实现。
    """

    def __init__(self, session: Session) -> None:
        """
        初始化任务执行 Outbox 仓储。
        """

        self._session = session

    def ping(self) -> bool:
        """
        探测任务执行 Outbox 仓储依赖是否可用。

        :returns: ``True`` 表示当前数据库会话可执行基础查询。
        :rtype: bool
        """

        self._session.execute(select(1))
        return True

    def insert(
        self,
        record: TaskExecutionOutboxOrmModel,
    ) -> TaskExecutionOutboxInsertResult:
        """
        写入任务执行 Outbox 记录。
        """

        self._session.add(record)
        self._session.flush()
        return TaskExecutionOutboxInsertResult(record=record)

    def get_by_message_id(self, message_id: str) -> TaskExecutionOutboxOrmModel | None:
        """
        按消息标识读取 Outbox 记录。
        """

        statement: Select[tuple[TaskExecutionOutboxOrmModel]] = select(
            TaskExecutionOutboxOrmModel
        ).where(TaskExecutionOutboxOrmModel.message_id == message_id)
        return self._session.execute(statement).scalar_one_or_none()

    def list_reserved(
        self,
        *,
        limit: int,
        created_before_epoch: int | None = None,
    ) -> list[TaskExecutionOutboxOrmModel]:
        """
        列出待发布 Outbox 记录。
        """

        effective_limit = self._normalize_limit(limit)
        statement: Select[tuple[TaskExecutionOutboxOrmModel]] = select(
            TaskExecutionOutboxOrmModel
        ).where(TaskExecutionOutboxOrmModel.status == TaskExecutionOutboxStatus.RESERVED.value)
        if created_before_epoch is not None:
            statement = statement.where(
                TaskExecutionOutboxOrmModel.created_at_epoch <= created_before_epoch
            )
        statement = statement.order_by(
            TaskExecutionOutboxOrmModel.created_at_epoch.asc(),
            TaskExecutionOutboxOrmModel.message_id.asc(),
        ).limit(effective_limit)
        return list(self._session.execute(statement).scalars().all())

    def update_fields(
        self,
        record: TaskExecutionOutboxOrmModel,
        patch: TaskExecutionOutboxUpdatePayload,
    ) -> TaskExecutionOutboxOrmModel:
        """
        更新 Outbox 记录字段。
        """

        for field_name, field_value in patch.model_dump(exclude_none=True).items():
            if isinstance(field_value, Enum):
                setattr(record, field_name, field_value.value)
                continue
            setattr(record, field_name, field_value)
        self._session.flush()
        return record

    def _normalize_limit(self, limit: int) -> int:
        """
        归一化列表限制。
        """

        if limit < TASK_EXECUTION_OUTBOX_LIST_MIN_LIMIT:
            return TASK_EXECUTION_OUTBOX_LIST_MIN_LIMIT
        return min(limit, TASK_EXECUTION_OUTBOX_LIST_MAX_LIMIT)
