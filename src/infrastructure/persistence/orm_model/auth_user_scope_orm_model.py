"""鉴权用户直接作用域 ORM 模型。"""

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
    from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel


class AuthUserScopeOrmModel(AuditTimestampMixin, OrmModelBase):
    """用户与直接授权 scope 的多对多关联。"""

    __tablename__ = "auth_user_scope"

    user_id: Mapped[UUID] = mapped_column(
        PostgresqlUuid(as_uuid=True),
        ForeignKey("auth_user.user_id", ondelete="CASCADE"),
        primary_key=True,
    )
    scope_code: Mapped[str] = mapped_column(
        String(SCOPE_CODE_MAX_LENGTH),
        ForeignKey("auth_scope.scope_code", ondelete="RESTRICT"),
        primary_key=True,
    )
    user: Mapped[AuthUserOrmModel] = relationship(back_populates="user_scopes")
