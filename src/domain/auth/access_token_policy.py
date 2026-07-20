"""
访问令牌策略领域模块。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AccessTokenPolicy:
    """
    访问令牌策略数据对象，用于承载当前流程的结构化字段。

    :ivar jwt_secret: JWT 签名密钥。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype jwt_secret: str
    :ivar jwt_algorithm: JWT 签名算法。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype jwt_algorithm: str
    :ivar access_token_expires_in_seconds: 访问令牌有效期秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype access_token_expires_in_seconds: int
    :ivar refresh_token_expires_in_seconds: 刷新令牌有效期秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype refresh_token_expires_in_seconds: int
    :ivar issuer: JWT 签发方。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype issuer: str
    :ivar audience: JWT 受众。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype audience: str
    :ivar refresh_token_rotation_enabled: 是否启用刷新令牌轮换。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype refresh_token_rotation_enabled: bool
    """

    jwt_secret: str
    jwt_algorithm: str
    access_token_expires_in_seconds: int
    refresh_token_expires_in_seconds: int
    issuer: str
    audience: str
    refresh_token_rotation_enabled: bool
