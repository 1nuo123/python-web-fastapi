"""
鉴权错误编码领域模块。
"""

from __future__ import annotations

from enum import StrEnum


class AuthErrorCode(StrEnum):
    """
    鉴权错误编码枚举，用于约束可选取值。

    :cvar INVALID_CREDENTIALS: ``INVALID_CREDENTIALS`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'auth.access.invalid_credentials'`。取值语义：用于承载当前对象中的业务状态。
    :vartype INVALID_CREDENTIALS: str
    :cvar ACCOUNT_DISABLED: ``ACCOUNT_DISABLED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'auth.access.account_disabled'`。取值语义：用于承载当前对象中的业务状态。
    :vartype ACCOUNT_DISABLED: str
    :cvar TOKEN_INVALID: ``TOKEN_INVALID`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'auth.token.invalid'`。取值语义：用于承载当前对象中的业务状态。
    :vartype TOKEN_INVALID: str
    :cvar TOKEN_EXPIRED: ``TOKEN_EXPIRED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'auth.token.expired'`。取值语义：用于承载当前对象中的业务状态。
    :vartype TOKEN_EXPIRED: str
    :cvar TOKEN_REVOKED: ``TOKEN_REVOKED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'auth.token.revoked'`。取值语义：用于承载当前对象中的业务状态。
    :vartype TOKEN_REVOKED: str
    :cvar TOKEN_REUSED: ``TOKEN_REUSED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'auth.token.reused'`。取值语义：用于承载当前对象中的业务状态。
    :vartype TOKEN_REUSED: str
    :cvar PERMISSION_DENIED: ``PERMISSION_DENIED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'auth.authorization.permission_denied'`。取值语义：用于承载当前对象中的业务状态。
    :vartype PERMISSION_DENIED: str
    :cvar REQUEST_THROTTLED: ``REQUEST_THROTTLED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'auth.request.throttled'`。取值语义：用于承载当前对象中的业务状态。
    :vartype REQUEST_THROTTLED: str
    """

    INVALID_CREDENTIALS = "auth.access.invalid_credentials"
    ACCOUNT_DISABLED = "auth.access.account_disabled"
    TOKEN_INVALID = "auth.token.invalid"
    TOKEN_EXPIRED = "auth.token.expired"
    TOKEN_REVOKED = "auth.token.revoked"
    TOKEN_REUSED = "auth.token.reused"
    PERMISSION_DENIED = "auth.authorization.permission_denied"
    REQUEST_THROTTLED = "auth.request.throttled"
