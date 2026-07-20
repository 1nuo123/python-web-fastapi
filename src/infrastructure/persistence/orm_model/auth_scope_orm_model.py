"""
鉴权作用域 ORM 模型基础设施模块。
"""

from __future__ import annotations

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.infrastructure.persistence.sqlalchemy_metadata_registry import (
    AuditTimestampMixin,
    OrmModelBase,
)

SCOPE_CODE_MAX_LENGTH = 128
SCOPE_NAME_MAX_LENGTH = 128
SCOPE_KIND_MAX_LENGTH = 32


class AuthScopeOrmModel(AuditTimestampMixin, OrmModelBase):
    """
    鉴权作用域 ORM 模型，定义 scope 目录持久化结构。

    :ivar scope_code: 作用域编码。
    :vartype scope_code: Mapped[str]
    :ivar scope_name: 作用域展示名称。
    :vartype scope_name: Mapped[str]
    :ivar description: 作用域说明。
    :vartype description: Mapped[str | None]
    :ivar scope_kind: 作用域类型。
    :vartype scope_kind: Mapped[str]
    :ivar enabled: 是否启用。
    :vartype enabled: Mapped[bool]
    """

    __tablename__ = "auth_scope"

    scope_code: Mapped[str] = mapped_column(
        String(SCOPE_CODE_MAX_LENGTH),
        primary_key=True,
    )
    scope_name: Mapped[str] = mapped_column(
        String(SCOPE_NAME_MAX_LENGTH),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    scope_kind: Mapped[str] = mapped_column(
        String(SCOPE_KIND_MAX_LENGTH),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True)
