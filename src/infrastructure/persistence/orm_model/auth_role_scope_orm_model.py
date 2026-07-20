"""
鉴权角色作用域ORM模型基础设施模块。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

SCOPE_CODE_MAX_LENGTH = 128

if TYPE_CHECKING:
    from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel


class AuthRoleScopeOrmModel(AuditTimestampMixin, OrmModelBase):
    """
    鉴权角色作用域ORM 模型，定义数据库表结构映射。

    :ivar __tablename__: ORM 模型对应的数据库表名。约束：需满足当前实现中的类型与状态约束。默认值：`'auth_role_scope'`。取值语义：用于决定 ORM 模型最终映射到的物理表。
    :vartype __tablename__: str
    :ivar role_id: ``role_id`` 字段。约束：需符合 ``Mapped[UUID]`` 注解。默认值：`mapped_column(PostgresqlUuid(as_uuid=True), ForeignKey('auth_role.role_id', ondelete='CASCADE'), primary_key=True)`。取值语义：用于唯一标识对应实体。
    :vartype role_id: Mapped[UUID]
    :ivar scope_code: ``scope_code`` 字段。约束：需符合 ``Mapped[str]`` 注解。默认值：`mapped_column(String(SCOPE_CODE_MAX_LENGTH), primary_key=True)`。取值语义：用于声明授权作用域或请求作用域。
    :vartype scope_code: Mapped[str]
    :ivar role: ``role`` 字段。约束：需符合 ``Mapped['AuthRoleOrmModel']`` 注解。默认值：`relationship(back_populates='role_scopes')`。取值语义：用于描述角色标识或角色关联关系。
    :vartype role: Mapped['AuthRoleOrmModel']
    """

    __tablename__ = "auth_role_scope"

    role_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("auth_role.role_id", ondelete="CASCADE"),
        primary_key=True,
    )
    scope_code: Mapped[str] = mapped_column(
        String(SCOPE_CODE_MAX_LENGTH),
        ForeignKey("auth_scope.scope_code", ondelete="RESTRICT"),
        primary_key=True,
    )
    role: Mapped[AuthRoleOrmModel] = relationship(back_populates="role_scopes")
