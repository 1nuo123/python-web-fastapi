"""
鉴权角色ORM模型基础设施模块。
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import String
from sqlalchemy.dialects.postgresql import UUID as PostgresqlUuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

ROLE_KEY_MAX_LENGTH = 64
ROLE_NAME_MAX_LENGTH = 128

if TYPE_CHECKING:
    from src.infrastructure.persistence.orm_model.auth_role_scope_orm_model import (
        AuthRoleScopeOrmModel,
    )
    from src.infrastructure.persistence.orm_model.auth_user_role_orm_model import (
        AuthUserRoleOrmModel,
    )


class AuthRoleOrmModel(AuditTimestampMixin, OrmModelBase):
    """
    鉴权角色ORM 模型，定义数据库表结构映射。

    :ivar __tablename__: ORM 模型对应的数据库表名。约束：需满足当前实现中的类型与状态约束。默认值：`'auth_role'`。取值语义：用于决定 ORM 模型最终映射到的物理表。
    :vartype __tablename__: str
    :ivar role_id: ``role_id`` 字段。约束：需符合 ``Mapped[UUID]`` 注解。默认值：`mapped_column(PostgresqlUuid(as_uuid=True), primary_key=True, default=uuid4)`。取值语义：用于唯一标识对应实体。
    :vartype role_id: Mapped[UUID]
    :ivar role_key: ``role_key`` 字段。约束：需符合 ``Mapped[str]`` 注解。默认值：`mapped_column(String(ROLE_KEY_MAX_LENGTH), nullable=False, unique=True)`。取值语义：用于描述角色标识或角色关联关系。
    :vartype role_key: Mapped[str]
    :ivar role_name: ``role_name`` 字段。约束：需符合 ``Mapped[str]`` 注解。默认值：`mapped_column(String(ROLE_NAME_MAX_LENGTH), nullable=False)`。取值语义：用于描述角色标识或角色关联关系。
    :vartype role_name: Mapped[str]
    :ivar role_scopes: ``role_scopes`` 字段。约束：需符合 ``Mapped[list['AuthRoleScopeOrmModel']]`` 注解。默认值：`relationship(back_populates='role', cascade='all, delete-orphan')`。取值语义：用于声明授权作用域或请求作用域。
    :vartype role_scopes: Mapped[list['AuthRoleScopeOrmModel']]
    :ivar user_roles: ``user_roles`` 字段。约束：需符合 ``Mapped[list['AuthUserRoleOrmModel']]`` 注解。默认值：`relationship(back_populates='role', cascade='all, delete-orphan')`。取值语义：用于描述角色标识或角色关联关系。
    :vartype user_roles: Mapped[list['AuthUserRoleOrmModel']]
    """

    __tablename__ = "auth_role"

    role_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    role_key: Mapped[str] = mapped_column(
        String(ROLE_KEY_MAX_LENGTH),
        nullable=False,
        unique=True,
    )
    role_name: Mapped[str] = mapped_column(
        String(ROLE_NAME_MAX_LENGTH),
        nullable=False,
    )
    role_scopes: Mapped[list[AuthRoleScopeOrmModel]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
    )
    user_roles: Mapped[list[AuthUserRoleOrmModel]] = relationship(
        back_populates="role",
        cascade="all, delete-orphan",
    )
