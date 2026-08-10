"""
契约鉴权访问API 接口层模块。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from src.core.auth_contract.step_up_grant_contract import StepUpGrantPurpose

AUTH_USERNAME_MIN_LENGTH = 1
AUTH_USERNAME_MAX_LENGTH = 128
AUTH_PASSWORD_MIN_LENGTH = 1
AUTH_PASSWORD_MAX_LENGTH = 256
AUTH_REGISTRATION_USERNAME_MIN_LENGTH = 3
AUTH_REGISTRATION_USERNAME_MAX_LENGTH = 64
AUTH_REGISTRATION_USERNAME_PATTERN = r"^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$"
AUTH_REGISTRATION_PASSWORD_MIN_LENGTH = 12
AUTH_REGISTRATION_PASSWORD_MAX_LENGTH = 128
AUTH_REFRESH_TOKEN_MIN_LENGTH = 16
AUTH_REFRESH_TOKEN_MAX_LENGTH = 4096
AUTH_TOKEN_PATTERN = r"^[A-Za-z0-9._~+/=-]+$"
BROWSER_TOKEN_ISSUE_KIND = "browser_token_issue"
BROWSER_TOKEN_SCHEMA_VERSION = "1.0"


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


class UserRegistrationRequest(BaseModel):
    """普通用户注册请求。"""

    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=AUTH_REGISTRATION_USERNAME_MIN_LENGTH,
        max_length=AUTH_REGISTRATION_USERNAME_MAX_LENGTH,
        pattern=AUTH_REGISTRATION_USERNAME_PATTERN,
    )
    password: SecretStr = Field(
        min_length=AUTH_REGISTRATION_PASSWORD_MIN_LENGTH,
        max_length=AUTH_REGISTRATION_PASSWORD_MAX_LENGTH,
    )

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value: object) -> object:
        """去除用户名首尾空白。"""

        return value.strip() if isinstance(value, str) else value


class UserRegistrationPayload(BaseModel):
    """普通用户注册响应。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["user_registration"] = "user_registration"
    schema_version: Literal["1.0"] = "1.0"
    subject_id: str
    username: str


class BrowserTokenIssuePayload(BaseModel):
    """浏览器令牌响应，只暴露内存使用的 access token。"""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["browser_token_issue"] = "browser_token_issue"
    schema_version: Literal["1.0"] = "1.0"
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in_seconds: int = Field(gt=0)


class StepUpGrantRequest(BaseModel):
    """增强验证请求；密码只在当前请求内使用。"""

    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=AUTH_PASSWORD_MIN_LENGTH, max_length=AUTH_PASSWORD_MAX_LENGTH)
    purpose: StepUpGrantPurpose


class StepUpGrantPayload(BaseModel):
    """短时一次性增强授权 grant。"""

    model_config = ConfigDict(extra="forbid")

    grant_token: str = Field(min_length=32, max_length=512)
    expires_at: datetime
