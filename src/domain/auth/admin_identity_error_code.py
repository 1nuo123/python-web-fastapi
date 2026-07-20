"""
管理员身份错误编码领域模块。
"""

from __future__ import annotations

from enum import StrEnum


class AdminIdentityErrorCode(StrEnum):
    """
    管理员身份错误编码枚举。

    :cvar NOT_FOUND: 管理员身份目标不存在。
    :vartype NOT_FOUND: str
    :cvar CONFLICT: 管理员身份写入冲突。
    :vartype CONFLICT: str
    :cvar INVALID: 管理员身份请求不满足业务约束。
    :vartype INVALID: str
    :cvar SELF_LOCK_BLOCKED: 操作者自锁保护拦截。
    :vartype SELF_LOCK_BLOCKED: str
    """

    NOT_FOUND = "auth.admin_identity.not_found"
    CONFLICT = "auth.admin_identity.conflict"
    INVALID = "auth.admin_identity.invalid"
    SELF_LOCK_BLOCKED = "auth.admin_identity.self_lock_blocked"
