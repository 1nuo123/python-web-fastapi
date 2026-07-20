"""
安全 IP 封禁仓储模块。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.core.persistence_contract.repository_contract import Repository
from src.core.security_contract.security_ip_block_contract import (
    SecurityIpBlockReason,
    SecurityIpBlockStatus,
)
from src.infrastructure.persistence.affected_rows_result_reader import AffectedRowsResultReader
from src.infrastructure.persistence.orm_model.security_ip_block_record_orm_model import (
    SecurityIpBlockRecordOrmModel,
)


class SecurityIpBlockRepository(Repository):
    """
    安全 IP 封禁仓储。
    """

    def __init__(self, session: Session) -> None:
        """
        初始化安全 IP 封禁仓储。
        """

        self._session = session

    def ping(self) -> bool:
        """
        探测仓储是否可用。
        """

        self._session.execute(select(SecurityIpBlockRecordOrmModel).limit(1))
        return True

    def get_active_by_ip_digest(
        self,
        ip_digest: str,
        *,
        current_epoch: int,
    ) -> SecurityIpBlockRecordOrmModel | None:
        """
        按 IP 摘要读取有效封禁记录。
        """

        statement = (
            select(SecurityIpBlockRecordOrmModel)
            .where(SecurityIpBlockRecordOrmModel.ip_digest == ip_digest)
            .where(SecurityIpBlockRecordOrmModel.status == SecurityIpBlockStatus.ACTIVE.value)
            .where(SecurityIpBlockRecordOrmModel.blocked_until_epoch > current_epoch)
            .order_by(SecurityIpBlockRecordOrmModel.blocked_until_epoch.desc())
            .limit(1)
        )
        return self._session.execute(statement).scalars().first()

    def get_by_record_id(
        self,
        record_id: UUID,
    ) -> SecurityIpBlockRecordOrmModel | None:
        """
        按记录 ID 读取封禁记录。

        :param record_id: 封禁记录 ID。
        :type record_id: UUID
        :returns: 封禁记录或 ``None``。
        :rtype: SecurityIpBlockRecordOrmModel | None
        """

        statement = (
            select(SecurityIpBlockRecordOrmModel)
            .where(SecurityIpBlockRecordOrmModel.record_id == record_id)
            .limit(1)
        )
        return self._session.execute(statement).scalars().first()

    def list_records(
        self,
        *,
        limit: int,
        status: str | None = None,
        ip_digest: str | None = None,
    ) -> list[SecurityIpBlockRecordOrmModel]:
        """
        查询封禁记录。
        """

        statement = (
            select(SecurityIpBlockRecordOrmModel)
            .order_by(SecurityIpBlockRecordOrmModel.blocked_until_epoch.desc())
            .limit(limit)
        )
        if status is not None:
            statement = statement.where(SecurityIpBlockRecordOrmModel.status == status)
        if ip_digest is not None:
            statement = statement.where(SecurityIpBlockRecordOrmModel.ip_digest == ip_digest)
        return list(self._session.execute(statement).scalars().all())

    def create_block_record(
        self,
        *,
        ip_digest: str,
        reason: SecurityIpBlockReason,
        blocked_until_epoch: int,
    ) -> SecurityIpBlockRecordOrmModel:
        """
        创建封禁记录。
        """

        record = SecurityIpBlockRecordOrmModel(
            ip_digest=ip_digest,
            reason=reason.value,
            status=SecurityIpBlockStatus.ACTIVE.value,
            blocked_until_epoch=blocked_until_epoch,
        )
        self._session.add(record)
        self._session.flush()
        return record

    def release_active_by_ip_digest(
        self,
        *,
        ip_digest: str,
        released_reason: str,
    ) -> int:
        """
        释放 IP 摘要对应的有效封禁记录。
        """

        statement = (
            update(SecurityIpBlockRecordOrmModel)
            .where(SecurityIpBlockRecordOrmModel.ip_digest == ip_digest)
            .where(SecurityIpBlockRecordOrmModel.status == SecurityIpBlockStatus.ACTIVE.value)
            .values(
                status=SecurityIpBlockStatus.RELEASED.value,
                released_reason=released_reason,
            )
        )
        result = self._session.execute(statement)
        return AffectedRowsResultReader.read(result)
