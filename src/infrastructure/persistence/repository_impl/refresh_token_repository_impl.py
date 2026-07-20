"""
刷新令牌仓储实现基础设施模块。
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from src.core.auth_contract.token_session_status_contract import TokenSessionStatusPayload
from src.core.persistence_contract.refresh_token_repository_contract import (
    RefreshTokenRepository,
    RefreshTokenSessionPayload,
)
from src.infrastructure.persistence.affected_rows_result_reader import AffectedRowsResultReader
from src.infrastructure.persistence.orm_model.auth_refresh_token_orm_model import (
    AuthRefreshTokenOrmModel,
)


class RefreshTokenRepositoryImpl(RefreshTokenRepository):
    """
    刷新令牌仓储实现，负责提供持久化访问逻辑。
    """

    def __init__(self, session: Session) -> None:
        """
        初始化刷新令牌仓储实现。

        :param session: 当前数据库会话，生命周期由工作单元控制。约束：需符合 ``Session`` 注解。
        :type session: Session
        :returns: 无返回值。
        :rtype: None
        """

        self._session = session

    def ping(self) -> bool:
        """
        探测刷新令牌仓储依赖是否可用。

        :returns: ``True`` 表示当前数据库会话可执行基础查询。
        :rtype: bool
        """

        self._session.execute(select(1))
        return True

    def create(self, refresh_token_session: RefreshTokenSessionPayload) -> None:
        """
        处理创建。

        :param refresh_token_session: 刷新令牌会话实体。约束：需符合 ``RefreshTokenSessionPayload`` 注解。
        :type refresh_token_session: RefreshTokenSessionPayload
        :returns: 无返回值。
        :rtype: None
        """

        self._session.add(
            AuthRefreshTokenOrmModel(
                refresh_token_id=refresh_token_session.refresh_token_id,
                token_session_id=refresh_token_session.token_session_id,
                user_id=refresh_token_session.user_id,
                subject_id=refresh_token_session.subject_id,
                issued_at=refresh_token_session.issued_at,
                expires_at=refresh_token_session.expires_at,
                revoked_at=refresh_token_session.revoked_at,
                rotated_to_token_id=refresh_token_session.rotated_to_token_id,
            )
        )

    def get_by_token_id(self, refresh_token_id: UUID) -> RefreshTokenSessionPayload | None:
        """
        获取按令牌标识。

        :param refresh_token_id: 刷新令牌标识。约束：需符合 ``UUID`` 注解。
        :type refresh_token_id: UUID
        :returns: 返回读取到的对象或状态快照。
        :rtype: RefreshTokenSessionPayload | None
        """

        statement = select(AuthRefreshTokenOrmModel).where(
            AuthRefreshTokenOrmModel.refresh_token_id == refresh_token_id
        )
        refresh_token = self._session.scalars(statement).one_or_none()
        if refresh_token is None:
            return None
        return self._build_payload(refresh_token)

    def get_by_token_id_for_update(
        self,
        refresh_token_id: UUID,
    ) -> RefreshTokenSessionPayload | None:
        """
        获取按令牌标识用于更新。

        :param refresh_token_id: 刷新令牌标识。约束：需符合 ``UUID`` 注解。
        :type refresh_token_id: UUID
        :returns: 返回读取到的对象或状态快照。
        :rtype: RefreshTokenSessionPayload | None
        """

        statement = (
            select(AuthRefreshTokenOrmModel)
            .where(AuthRefreshTokenOrmModel.refresh_token_id == refresh_token_id)
            .with_for_update()
        )
        refresh_token = self._session.scalars(statement).one_or_none()
        if refresh_token is None:
            return None
        return self._build_payload(refresh_token)

    def get_token_session_status(
        self,
        token_session_id: UUID,
    ) -> TokenSessionStatusPayload | None:
        """
        获取令牌会话状态。

        :param token_session_id: 令牌会话标识，用于串联一组访问令牌与刷新令牌。约束：需符合 ``UUID`` 注解。
        :type token_session_id: UUID
        :returns: 返回读取到的对象或状态快照。
        :rtype: TokenSessionStatusPayload | None
        """

        statement = (
            select(
                AuthRefreshTokenOrmModel.token_session_id,
                AuthRefreshTokenOrmModel.subject_id,
                func.max(
                    case(
                        (AuthRefreshTokenOrmModel.revoked_at.is_(None), 1),
                        else_=0,
                    )
                ).label("has_active_token"),
                func.sum(
                    case(
                        (AuthRefreshTokenOrmModel.revoked_at.is_(None), 1),
                        else_=0,
                    )
                ).label("active_token_count"),
                func.max(
                    case(
                        (
                            AuthRefreshTokenOrmModel.revoked_at.is_(None)
                            & (AuthRefreshTokenOrmModel.expires_at > func.now()),
                            1,
                        ),
                        else_=0,
                    )
                ).label("has_unexpired_active_token"),
                func.max(AuthRefreshTokenOrmModel.expires_at).label("expires_at"),
                func.max(AuthRefreshTokenOrmModel.revoked_at).label("revoked_at"),
            )
            .where(AuthRefreshTokenOrmModel.token_session_id == token_session_id)
            .group_by(
                AuthRefreshTokenOrmModel.token_session_id,
                AuthRefreshTokenOrmModel.subject_id,
            )
        )
        rows = self._session.execute(statement).all()
        if len(rows) == 0:
            return None
        row = rows[0]
        is_inconsistent = len(rows) > 1 or row.active_token_count > 1
        revoked_at_epoch = None
        if row.revoked_at is not None and row.has_active_token == 0:
            normalized_revoked_at = self._normalize_utc(row.revoked_at)
            if normalized_revoked_at is not None:
                revoked_at_epoch = int(normalized_revoked_at.timestamp())
        return TokenSessionStatusPayload(
            token_session_id=str(row.token_session_id),
            subject_id=row.subject_id,
            is_revoked=is_inconsistent or row.has_active_token == 0,
            is_expired=row.has_unexpired_active_token == 0,
            is_inconsistent=is_inconsistent,
            revoked_at_epoch=revoked_at_epoch,
        )

    def mark_token_rotated(
        self,
        *,
        refresh_token_id: UUID,
        rotated_to_token_id: UUID,
        revoked_at: datetime,
    ) -> None:
        """
        标记令牌轮换。

        :param refresh_token_id: 刷新令牌标识。约束：需符合 ``UUID`` 注解。
        :type refresh_token_id: UUID
        :param rotated_to_token_id: 轮换后的新刷新令牌标识。约束：需符合 ``UUID`` 注解。
        :type rotated_to_token_id: UUID
        :param revoked_at: 撤销时间。约束：需符合 ``datetime`` 注解。
        :type revoked_at: datetime
        :returns: 无返回值。
        :rtype: None
        """

        statement = (
            update(AuthRefreshTokenOrmModel)
            .where(AuthRefreshTokenOrmModel.refresh_token_id == refresh_token_id)
            .values(
                rotated_to_token_id=rotated_to_token_id,
                revoked_at=revoked_at,
            )
        )
        self._session.flush()
        self._session.execute(statement)
        self._session.expire_all()

    def revoke_token_session(
        self,
        *,
        token_session_id: UUID,
        revoked_at: datetime,
    ) -> int:
        """
        撤销令牌会话。

        :param token_session_id: 令牌会话标识，用于串联一组访问令牌与刷新令牌。约束：需符合 ``UUID`` 注解。
        :type token_session_id: UUID
        :param revoked_at: 撤销时间。约束：需符合 ``datetime`` 注解。
        :type revoked_at: datetime
        :returns: 返回当前操作结果。
        :rtype: int
        """

        statement = (
            update(AuthRefreshTokenOrmModel)
            .where(AuthRefreshTokenOrmModel.token_session_id == token_session_id)
            .where(AuthRefreshTokenOrmModel.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
        self._session.flush()
        result = self._session.execute(statement)
        self._session.expire_all()
        return AffectedRowsResultReader.read(result)

    def revoke_active_token_sessions_by_subject_id(
        self,
        *,
        subject_id: str,
        revoked_at: datetime,
    ) -> int:
        """
        按主体标识撤销全部活跃刷新令牌记录。

        :param subject_id: 认证主体标识。
        :type subject_id: str
        :param revoked_at: 撤销时间。
        :type revoked_at: datetime
        :returns: 返回被撤销的记录数量。
        :rtype: int
        """

        statement = (
            update(AuthRefreshTokenOrmModel)
            .where(AuthRefreshTokenOrmModel.subject_id == subject_id)
            .where(AuthRefreshTokenOrmModel.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
        self._session.flush()
        result = self._session.execute(statement)
        self._session.expire_all()
        return AffectedRowsResultReader.read(result)

    def revoke_all_active_token_sessions(self, *, revoked_at: datetime) -> int:
        """
        撤销全部活跃刷新令牌记录。

        :param revoked_at: 撤销时间。约束：需符合 ``datetime`` 注解。
        :type revoked_at: datetime
        :returns: 返回被撤销的记录数量。
        :rtype: int
        """

        statement = (
            update(AuthRefreshTokenOrmModel)
            .where(AuthRefreshTokenOrmModel.revoked_at.is_(None))
            .values(revoked_at=revoked_at)
        )
        self._session.flush()
        result = self._session.execute(statement)
        self._session.expire_all()
        return AffectedRowsResultReader.read(result)

    def _build_payload(
        self,
        refresh_token: AuthRefreshTokenOrmModel,
    ) -> RefreshTokenSessionPayload:
        """
        构建载荷。

        :param refresh_token: 刷新令牌原文。约束：需符合 ``AuthRefreshTokenOrmModel`` 注解。
        :type refresh_token: AuthRefreshTokenOrmModel
        :returns: 返回当前操作结果。
        :rtype: RefreshTokenSessionPayload
        """

        return RefreshTokenSessionPayload(
            refresh_token_id=refresh_token.refresh_token_id,
            token_session_id=refresh_token.token_session_id,
            user_id=refresh_token.user_id,
            subject_id=refresh_token.subject_id,
            issued_at=self._normalize_required_utc(refresh_token.issued_at),
            expires_at=self._normalize_required_utc(refresh_token.expires_at),
            revoked_at=self._normalize_utc(refresh_token.revoked_at),
            rotated_to_token_id=refresh_token.rotated_to_token_id,
        )

    @staticmethod
    def _normalize_required_utc(value: datetime) -> datetime:
        """将持久化时间统一恢复为 UTC 时区感知时间。"""

        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @classmethod
    def _normalize_utc(cls, value: datetime | None) -> datetime | None:
        """将可空持久化时间统一恢复为 UTC 时区感知时间。"""

        if value is None:
            return None
        return cls._normalize_required_utc(value)
