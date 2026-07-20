"""
SQLAlchemy元数据注册表基础设施模块。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

INDEX_NAMING_PATTERN = "ix_%(table_name)s_%(column_0_name)s"
UNIQUE_CONSTRAINT_NAMING_PATTERN = "uq_%(table_name)s_%(column_0_name)s"
CHECK_CONSTRAINT_NAMING_PATTERN = "ck_%(table_name)s_%(constraint_name)s"
FOREIGN_KEY_NAMING_PATTERN = "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
PRIMARY_KEY_NAMING_PATTERN = "pk_%(table_name)s"

ORM_MODEL_METADATA = MetaData(
    naming_convention={
        "ix": INDEX_NAMING_PATTERN,
        "uq": UNIQUE_CONSTRAINT_NAMING_PATTERN,
        "ck": CHECK_CONSTRAINT_NAMING_PATTERN,
        "fk": FOREIGN_KEY_NAMING_PATTERN,
        "pk": PRIMARY_KEY_NAMING_PATTERN,
    }
)


class OrmModelBase(DeclarativeBase):
    """
    ORM模型基础类型，用于封装当前模块中的相关行为或状态。

    :ivar metadata: ``metadata`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`ORM_MODEL_METADATA`。取值语义：用于承载当前对象中的业务状态。
    :vartype metadata: Any
    """

    metadata = ORM_MODEL_METADATA


class AuditTimestampMixin:
    """
    审计时间戳混入类型，用于封装当前模块中的相关行为或状态。

    :ivar created_at: ``created_at`` 字段。约束：需符合 ``Mapped[datetime]`` 注解。默认值：`mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())`。取值语义：用于承载当前对象中的业务状态。
    :vartype created_at: Mapped[datetime]
    :ivar updated_at: ``updated_at`` 字段。约束：需符合 ``Mapped[datetime]`` 注解。默认值：`mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())`。取值语义：用于承载当前对象中的业务状态。
    :vartype updated_at: Mapped[datetime]
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
