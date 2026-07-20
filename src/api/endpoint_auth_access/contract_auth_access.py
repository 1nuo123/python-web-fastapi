"""
契约鉴权访问API 接口层模块。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator

AUTH_USERNAME_MIN_LENGTH = 1
AUTH_USERNAME_MAX_LENGTH = 128
AUTH_PASSWORD_MIN_LENGTH = 1
AUTH_PASSWORD_MAX_LENGTH = 256
AUTH_REFRESH_TOKEN_MIN_LENGTH = 16
AUTH_REFRESH_TOKEN_MAX_LENGTH = 4096
AUTH_TOKEN_PATTERN = r"^[A-Za-z0-9._~+/=-]+$"


class TokenIssueRequest(BaseModel):
    """
    令牌签发Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar username: 登录用户名。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype username: str
    :ivar password: ``password`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载密码原文、哈希或相关算法配置。
    :vartype password: str
    """

    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=AUTH_USERNAME_MIN_LENGTH,
        max_length=AUTH_USERNAME_MAX_LENGTH,
    )
    password: str = Field(
        min_length=AUTH_PASSWORD_MIN_LENGTH,
        max_length=AUTH_PASSWORD_MAX_LENGTH,
    )

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        """
        规范化登录用户名。

        :param value: 原始用户名。
        :type value: str
        :returns: 去除首尾空白后的用户名。
        :rtype: str
        :raises ValueError: 当用户名为空时抛出。
        """

        normalized_value = value.strip()
        if normalized_value == "":
            raise ValueError("登录用户名不能为空。")
        return normalized_value


class TokenRefreshRequest(BaseModel):
    """
    令牌刷新Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar refresh_token: ``refresh_token`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype refresh_token: str
    """

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(
        min_length=AUTH_REFRESH_TOKEN_MIN_LENGTH,
        max_length=AUTH_REFRESH_TOKEN_MAX_LENGTH,
        pattern=AUTH_TOKEN_PATTERN,
    )


class TokenRevokeRequest(BaseModel):
    """
    令牌撤销Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar refresh_token: ``refresh_token`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype refresh_token: str
    """

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(
        min_length=AUTH_REFRESH_TOKEN_MIN_LENGTH,
        max_length=AUTH_REFRESH_TOKEN_MAX_LENGTH,
        pattern=AUTH_TOKEN_PATTERN,
    )
