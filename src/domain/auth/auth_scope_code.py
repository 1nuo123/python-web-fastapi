"""
鉴权作用域编码领域模块。
"""

from __future__ import annotations

from enum import StrEnum


class AuthScopeCode(StrEnum):
    """
    鉴权作用域编码枚举，用于约束可选取值。

    :cvar AUTH_READ: ``AUTH_READ`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'auth:read'`。取值语义：用于承载当前对象中的业务状态。
    :vartype AUTH_READ: str
    :cvar SYSTEM_READ: ``SYSTEM_READ`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system:read'`。取值语义：用于承载当前对象中的业务状态。
    :vartype SYSTEM_READ: str
    :cvar TASK_DISPATCH: ``TASK_DISPATCH`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'task:dispatch'`。取值语义：用于承载当前对象中的业务状态。
    :vartype TASK_DISPATCH: str
    """

    AUTH_READ = "auth:read"
    AUTH_MANAGE = "auth:manage"
    AUTH_USER_MANAGE = "auth:user_manage"
    AUTH_ROLE_MANAGE = "auth:role_manage"
    AUTH_SCOPE_MANAGE = "auth:scope_manage"
    AUTH_PASSWORD_RESET = "auth:password_reset"
    AUTH_GRANT_ADMIN = "auth:grant_admin"
    SECURITY_MANAGE = "security:manage"
    SYSTEM_READ = "system:read"
    TASK_DISPATCH = "task:dispatch"
