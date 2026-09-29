"""
任务执行 Outbox 仓储实现模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from time import time

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from src.core.persistence_contract.repository_contract import Repository
from src.infrastructure.persistence.orm_model.task_execution_outbox_orm_model import (
    TaskExecutionOutboxOrmModel,
    TaskExecutionOutboxStatus,
)

TASK_EXECUTION_OUTBOX_LIST_MIN_LIMIT = 1
TASK_EXECUTION_OUTBOX_LIST_MAX_LIMIT = 200
TASK_EXECUTION_OUTBOX_CLAIM_LEASE_SECONDS = 60


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
    attempt_count: int | None = Field(default=None, ge=0)
    next_retry_at_epoch: int | None = None
    last_error_type: str | None = None
    last_error_message: str | None = None
    unknown_at_epoch: int | None = None
    claim_owner: str | None = None
    claimed_at_epoch: int | None = None


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
        claim_owner: str | None = None,
        claim_epoch: int | None = None,
    ) -> list[TaskExecutionOutboxOrmModel]:
        """
        列出待发布 Outbox 记录。
        """

        effective_limit = self._normalize_limit(limit)
        now_epoch = int(time())
        due_status = or_(
            TaskExecutionOutboxOrmModel.status == TaskExecutionOutboxStatus.RESERVED.value,
            and_(
                TaskExecutionOutboxOrmModel.status == TaskExecutionOutboxStatus.RETRYING.value,
                or_(
                    TaskExecutionOutboxOrmModel.next_retry_at_epoch.is_(None),
                    TaskExecutionOutboxOrmModel.next_retry_at_epoch <= now_epoch,
                ),
            ),
        )
        if claim_owner is not None:
            due_status = and_(
                due_status,
                or_(
                    TaskExecutionOutboxOrmModel.claim_owner.is_(None),
                    TaskExecutionOutboxOrmModel.claim_owner == claim_owner,
                    TaskExecutionOutboxOrmModel.claimed_at_epoch.is_(None),
                    TaskExecutionOutboxOrmModel.claimed_at_epoch
                    <= now_epoch - TASK_EXECUTION_OUTBOX_CLAIM_LEASE_SECONDS,
                ),
            )
        statement: Select[tuple[TaskExecutionOutboxOrmModel]] = select(
            TaskExecutionOutboxOrmModel
        ).where(due_status)
        if created_before_epoch is not None:
            statement = statement.where(
                or_(
                    TaskExecutionOutboxOrmModel.status != TaskExecutionOutboxStatus.RESERVED.value,
                    TaskExecutionOutboxOrmModel.created_at_epoch <= created_before_epoch,
                )
            )
        statement = statement.order_by(
            TaskExecutionOutboxOrmModel.created_at_epoch.asc(),
            TaskExecutionOutboxOrmModel.message_id.asc(),
        ).limit(effective_limit)
        records = list(self._session.execute(statement).scalars().all())
        if claim_owner is not None and records:
            claimed_at_epoch = claim_epoch if claim_epoch is not None else now_epoch
            for record in records:
                record.claim_owner = claim_owner
                record.claimed_at_epoch = claimed_at_epoch
            self._session.flush()
        return records

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

    def list_by_status(
        self,
        *,
        status: TaskExecutionOutboxStatus,
        limit: int,
    ) -> list[TaskExecutionOutboxOrmModel]:
        """按状态读取 Outbox 记录，用于诊断和受控恢复。"""

        effective_limit = self._normalize_limit(limit)
        statement: Select[tuple[TaskExecutionOutboxOrmModel]] = (
            select(TaskExecutionOutboxOrmModel)
            .where(TaskExecutionOutboxOrmModel.status == status.value)
            .order_by(
                TaskExecutionOutboxOrmModel.updated_at.asc(),
                TaskExecutionOutboxOrmModel.message_id.asc(),
            )
            .limit(effective_limit)
        )
        return list(self._session.execute(statement).scalars().all())

    def _normalize_limit(self, limit: int) -> int:
        """
        归一化列表限制。
        """

        if limit < TASK_EXECUTION_OUTBOX_LIST_MIN_LIMIT:
            return TASK_EXECUTION_OUTBOX_LIST_MIN_LIMIT
        return min(limit, TASK_EXECUTION_OUTBOX_LIST_MAX_LIMIT)
