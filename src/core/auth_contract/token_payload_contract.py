"""
令牌载荷契约核心契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

TOKEN_SCHEMA_VERSION: Final = "1.1"
TOKEN_PAYLOAD_KIND: Final = "token"
TOKEN_ISSUE_KIND: Final = "token_issue"
TOKEN_REVOKE_KIND: Final = "token_revoke"
TOKEN_BEARER_TYPE: Final = "Bearer"


class TokenUse(StrEnum):
    """
    令牌用途枚举，用于约束可选取值。

    :cvar ACCESS: ``ACCESS`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'access'`。取值语义：用于承载当前对象中的业务状态。
    :vartype ACCESS: str
    :cvar REFRESH: ``REFRESH`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'refresh'`。取值语义：用于承载当前对象中的业务状态。
    :vartype REFRESH: str
    """

    ACCESS = "access"
    REFRESH = "refresh"


class TokenPayload(BaseModel):
    """
    令牌Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``Literal[TOKEN_PAYLOAD_KIND]`` 注解；取值固定为 ``TOKEN_PAYLOAD_KIND``。默认值：`TOKEN_PAYLOAD_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: Literal[TOKEN_PAYLOAD_KIND]
    :ivar schema_version: 结构模式版本。约束：需符合 ``Literal[TOKEN_SCHEMA_VERSION]`` 注解；取值固定为 ``TOKEN_SCHEMA_VERSION``。默认值：`TOKEN_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: Literal[TOKEN_SCHEMA_VERSION]
    :ivar token_id: ``token_id`` 字段。约束：需符合 ``UUID`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype token_id: UUID
    :ivar token_session_id: 令牌会话标识。约束：需符合 ``UUID`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype token_session_id: UUID
    :ivar subject_id: 认证主体标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype subject_id: str
    :ivar username: 登录用户名。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype username: str
    :ivar roles: 角色键列表。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于描述角色标识或角色关联关系。
    :vartype roles: list[str]
    :ivar scopes: 作用域编码列表。约束：需符合 ``list[str]`` 注解；按实现使用有序列表承载。默认值：无，必须显式提供。取值语义：用于声明授权作用域或请求作用域。
    :vartype scopes: list[str]
    :ivar token_use: ``token_use`` 字段。约束：需符合 ``TokenUse`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype token_use: TokenUse
    :ivar issued_at_epoch: ``issued_at_epoch`` 字段。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达 Unix 时间戳秒值。
    :vartype issued_at_epoch: int
    :ivar expires_at_epoch: ``expires_at_epoch`` 字段。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达 Unix 时间戳秒值。
    :vartype expires_at_epoch: int
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["token"] = TOKEN_PAYLOAD_KIND
    schema_version: Literal["1.1"] = TOKEN_SCHEMA_VERSION
    token_id: UUID
    token_session_id: UUID
    subject_id: str
    username: str
    roles: list[str]
    scopes: list[str]
    token_use: TokenUse
    issued_at_epoch: int
    expires_at_epoch: int


class TokenIssuePayload(BaseModel):
    """
    令牌签发Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``Literal[TOKEN_ISSUE_KIND]`` 注解；取值固定为 ``TOKEN_ISSUE_KIND``。默认值：`TOKEN_ISSUE_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: Literal[TOKEN_ISSUE_KIND]
    :ivar schema_version: 结构模式版本。约束：需符合 ``Literal[TOKEN_SCHEMA_VERSION]`` 注解；取值固定为 ``TOKEN_SCHEMA_VERSION``。默认值：`TOKEN_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: Literal[TOKEN_SCHEMA_VERSION]
    :ivar access_token: 访问令牌原文。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype access_token: str
    :ivar refresh_token: ``refresh_token`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype refresh_token: str
    :ivar token_type: 令牌类型。约束：需符合 ``Literal[TOKEN_BEARER_TYPE]`` 注解；取值固定为 ``TOKEN_BEARER_TYPE``。默认值：`TOKEN_BEARER_TYPE`。取值语义：用于表达访问令牌、刷新令牌或令牌会话信息。
    :vartype token_type: Literal[TOKEN_BEARER_TYPE]
    :ivar expires_in_seconds: 访问令牌有效期秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype expires_in_seconds: int
    :ivar refresh_expires_in_seconds: 刷新令牌有效期秒数。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype refresh_expires_in_seconds: int
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["token_issue"] = TOKEN_ISSUE_KIND
    schema_version: Literal["1.1"] = TOKEN_SCHEMA_VERSION
    access_token: str
    refresh_token: str
    token_type: Literal["Bearer"] = TOKEN_BEARER_TYPE
    expires_in_seconds: int
    refresh_expires_in_seconds: int


class TokenRevokePayload(BaseModel):
    """
    令牌撤销Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``Literal[TOKEN_REVOKE_KIND]`` 注解；取值固定为 ``TOKEN_REVOKE_KIND``。默认值：`TOKEN_REVOKE_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: Literal[TOKEN_REVOKE_KIND]
    :ivar schema_version: 结构模式版本。约束：需符合 ``Literal[TOKEN_SCHEMA_VERSION]`` 注解；取值固定为 ``TOKEN_SCHEMA_VERSION``。默认值：`TOKEN_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: Literal[TOKEN_SCHEMA_VERSION]
    :ivar revoked: 令牌是否已经撤销。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype revoked: bool
    :ivar revoked_at_epoch: ``revoked_at_epoch`` 字段。约束：需符合 ``int`` 注解。默认值：无，必须显式提供。取值语义：用于表达 Unix 时间戳秒值。
    :vartype revoked_at_epoch: int
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["token_revoke"] = TOKEN_REVOKE_KIND
    schema_version: Literal["1.1"] = TOKEN_SCHEMA_VERSION
    revoked: bool
    revoked_at_epoch: int
