"""
鉴权用户ORM模型基础设施模块。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Boolean, String, Text
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

SUBJECT_ID_MAX_LENGTH = 128
USERNAME_MAX_LENGTH = 128

if TYPE_CHECKING:
    from src.infrastructure.persistence.orm_model.auth_refresh_token_orm_model import (
        AuthRefreshTokenOrmModel,
    )
    from src.infrastructure.persistence.orm_model.auth_user_role_orm_model import (
        AuthUserRoleOrmModel,
    )
    from src.infrastructure.persistence.orm_model.auth_user_scope_orm_model import (
        AuthUserScopeOrmModel,
    )


class AuthUserOrmModel(AuditTimestampMixin, OrmModelBase):
    """
    鉴权用户ORM 模型，定义数据库表结构映射。

    :ivar __tablename__: ORM 模型对应的数据库表名。约束：需满足当前实现中的类型与状态约束。默认值：`'auth_user'`。取值语义：用于决定 ORM 模型最终映射到的物理表。
    :vartype __tablename__: str
    :ivar user_id: 用户主键标识。约束：需符合 ``Mapped[UUID]`` 注解。默认值：`mapped_column(PostgresqlUuid(as_uuid=True), primary_key=True, default=uuid4)`。取值语义：用于唯一标识对应实体。
    :vartype user_id: Mapped[UUID]
    :ivar subject_id: 认证主体标识。约束：需符合 ``Mapped[str]`` 注解。默认值：`mapped_column(String(SUBJECT_ID_MAX_LENGTH), nullable=False, unique=True)`。取值语义：用于唯一标识对应实体。
    :vartype subject_id: Mapped[str]
    :ivar username: 登录用户名。约束：需符合 ``Mapped[str]`` 注解。默认值：`mapped_column(String(USERNAME_MAX_LENGTH), nullable=False, unique=True)`。取值语义：用于承载当前对象中的业务状态。
    :vartype username: Mapped[str]
    :ivar password_hash: 密码哈希值。约束：需符合 ``Mapped[str]`` 注解。默认值：`mapped_column(Text(), nullable=False)`。取值语义：用于承载密码原文、哈希或相关算法配置。
    :vartype password_hash: Mapped[str]
    :ivar is_active: 主体是否处于激活状态。约束：需符合 ``Mapped[bool]`` 注解。默认值：`mapped_column(Boolean(), nullable=False, default=True)`。取值语义：``True`` 表示当前状态成立，``False`` 表示当前状态不成立。
    :vartype is_active: Mapped[bool]
    :ivar user_roles: ``user_roles`` 字段。约束：需符合 ``Mapped[list['AuthUserRoleOrmModel']]`` 注解。默认值：`relationship(back_populates='user', cascade='all, delete-orphan')`。取值语义：用于描述角色标识或角色关联关系。
    :vartype user_roles: Mapped[list['AuthUserRoleOrmModel']]
    :ivar refresh_tokens: ``refresh_tokens`` 字段。约束：需符合 ``Mapped[list['AuthRefreshTokenOrmModel']]`` 注解。默认值：`relationship(back_populates='user', cascade='all, delete-orphan')`。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype refresh_tokens: Mapped[list['AuthRefreshTokenOrmModel']]
    """

    __tablename__ = "auth_user"

    user_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    subject_id: Mapped[str] = mapped_column(
        String(SUBJECT_ID_MAX_LENGTH),
        nullable=False,
        unique=True,
    )
    username: Mapped[str] = mapped_column(
        String(USERNAME_MAX_LENGTH),
        nullable=False,
        unique=True,
    )
    password_hash: Mapped[str] = mapped_column(Text(), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
    user_roles: Mapped[list[AuthUserRoleOrmModel]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    user_scopes: Mapped[list[AuthUserScopeOrmModel]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
    )
    refresh_tokens: Mapped[list[AuthRefreshTokenOrmModel]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        foreign_keys="AuthRefreshTokenOrmModel.user_id",
    )
