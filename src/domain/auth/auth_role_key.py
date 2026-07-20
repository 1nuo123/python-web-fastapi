"""
鉴权角色键领域模块。
"""

from __future__ import annotations

from enum import StrEnum


class AuthRoleKey(StrEnum):
    """
    鉴权角色键枚举，用于约束可选取值。

    :cvar ADMIN: ``ADMIN`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'admin'`。取值语义：用于承载当前对象中的业务状态。
    :vartype ADMIN: str
    """

    ADMIN = "admin"
