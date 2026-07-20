"""
鉴权用户角色ORM模型基础设施模块。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

if TYPE_CHECKING:
    from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
    from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel


class AuthUserRoleOrmModel(AuditTimestampMixin, OrmModelBase):
    """
    鉴权用户角色ORM 模型，定义数据库表结构映射。

    :ivar __tablename__: ORM 模型对应的数据库表名。约束：需满足当前实现中的类型与状态约束。默认值：`'auth_user_role'`。取值语义：用于决定 ORM 模型最终映射到的物理表。
    :vartype __tablename__: str
    :ivar user_id: 用户主键标识。约束：需符合 ``Mapped[UUID]`` 注解。默认值：`mapped_column(PostgresqlUuid(as_uuid=True), ForeignKey('auth_user.user_id', ondelete='CASCADE'), primary_key=True)`。取值语义：用于唯一标识对应实体。
    :vartype user_id: Mapped[UUID]
    :ivar role_id: ``role_id`` 字段。约束：需符合 ``Mapped[UUID]`` 注解。默认值：`mapped_column(PostgresqlUuid(as_uuid=True), ForeignKey('auth_role.role_id', ondelete='CASCADE'), primary_key=True)`。取值语义：用于唯一标识对应实体。
    :vartype role_id: Mapped[UUID]
    :ivar user: ``user`` 字段。约束：需符合 ``Mapped['AuthUserOrmModel']`` 注解。默认值：`relationship(back_populates='user_roles')`。取值语义：用于承载当前对象中的业务状态。
    :vartype user: Mapped['AuthUserOrmModel']
    :ivar role: ``role`` 字段。约束：需符合 ``Mapped['AuthRoleOrmModel']`` 注解。默认值：`relationship(back_populates='user_roles')`。取值语义：用于描述角色标识或角色关联关系。
    :vartype role: Mapped['AuthRoleOrmModel']
    """

    __tablename__ = "auth_user_role"

    user_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("auth_user.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("auth_role.role_id", ondelete="CASCADE"),
        primary_key=True,
    )
    user: Mapped[AuthUserOrmModel] = relationship(back_populates="user_roles")
    role: Mapped[AuthRoleOrmModel] = relationship(back_populates="user_roles")
