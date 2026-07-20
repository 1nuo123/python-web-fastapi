"""
鉴权刷新令牌ORM模型基础设施模块。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

SUBJECT_ID_MAX_LENGTH = 128

if TYPE_CHECKING:
    from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel


class AuthRefreshTokenOrmModel(AuditTimestampMixin, OrmModelBase):
    """
    鉴权刷新令牌ORM 模型，定义数据库表结构映射。

    :ivar __tablename__: ORM 模型对应的数据库表名。约束：需满足当前实现中的类型与状态约束。默认值：`'auth_refresh_token'`。取值语义：用于决定 ORM 模型最终映射到的物理表。
    :vartype __tablename__: str
    :ivar refresh_token_id: 刷新令牌标识。约束：需符合 ``Mapped[UUID]`` 注解。默认值：`mapped_column(PostgresqlUuid(as_uuid=True), primary_key=True, default=uuid4)`。取值语义：用于唯一标识对应实体。
    :vartype refresh_token_id: Mapped[UUID]
    :ivar token_session_id: 令牌会话标识。约束：需符合 ``Mapped[UUID]`` 注解。默认值：`mapped_column(PostgresqlUuid(as_uuid=True), nullable=False, index=True)`。取值语义：用于唯一标识对应实体。
    :vartype token_session_id: Mapped[UUID]
    :ivar user_id: 用户主键标识。约束：需符合 ``Mapped[UUID]`` 注解。默认值：`mapped_column(PostgresqlUuid(as_uuid=True), ForeignKey('auth_user.user_id', ondelete='CASCADE'), nullable=False, index=True)`。取值语义：用于唯一标识对应实体。
    :vartype user_id: Mapped[UUID]
    :ivar subject_id: 认证主体标识。约束：需符合 ``Mapped[str]`` 注解。默认值：`mapped_column(String(SUBJECT_ID_MAX_LENGTH), nullable=False, index=True)`。取值语义：用于唯一标识对应实体。
    :vartype subject_id: Mapped[str]
    :ivar issued_at: 签发时间。约束：需符合 ``Mapped[datetime]`` 注解。默认值：`mapped_column(DateTime(timezone=True), nullable=False)`。取值语义：用于承载当前对象中的业务状态。
    :vartype issued_at: Mapped[datetime]
    :ivar expires_at: 过期时间。约束：需符合 ``Mapped[datetime]`` 注解。默认值：`mapped_column(DateTime(timezone=True), nullable=False, index=True)`。取值语义：用于承载当前对象中的业务状态。
    :vartype expires_at: Mapped[datetime]
    :ivar revoked_at: 撤销时间。约束：需符合 ``Mapped[datetime | None]`` 注解；允许为空值。默认值：`mapped_column(DateTime(timezone=True), nullable=True)`。取值语义：用于承载当前对象中的业务状态。
    :vartype revoked_at: Mapped[datetime | None]
    :ivar rotated_to_token_id: 轮换后的新刷新令牌标识。约束：需符合 ``Mapped[UUID | None]`` 注解；允许为空值。默认值：`mapped_column(PostgresqlUuid(as_uuid=True), nullable=True, index=True)`。取值语义：用于唯一标识对应实体。
    :vartype rotated_to_token_id: Mapped[UUID | None]
    :ivar user: ``user`` 字段。约束：需符合 ``Mapped['AuthUserOrmModel']`` 注解。默认值：`relationship(back_populates='refresh_tokens')`。取值语义：用于承载当前对象中的业务状态。
    :vartype user: Mapped['AuthUserOrmModel']
    """

    __tablename__ = "auth_refresh_token"

    refresh_token_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    token_session_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("auth_user.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[str] = mapped_column(
        String(SUBJECT_ID_MAX_LENGTH),
        ForeignKey("auth_user.subject_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    rotated_to_token_id: Mapped[UUID | None] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("auth_refresh_token.refresh_token_id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    user: Mapped[AuthUserOrmModel] = relationship(
        back_populates="refresh_tokens",
        foreign_keys=[user_id],
    )
