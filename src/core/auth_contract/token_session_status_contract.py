"""
令牌会话状态契约核心契约模块。
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

TOKEN_SESSION_STATUS_KIND: Final = "token_session_status"
TOKEN_SESSION_STATUS_SCHEMA_VERSION: Final = "1.0"


class TokenSessionStatusPayload(BaseModel):
    """
    令牌会话状态Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``Literal[TOKEN_SESSION_STATUS_KIND]`` 注解；取值固定为 ``TOKEN_SESSION_STATUS_KIND``。默认值：`TOKEN_SESSION_STATUS_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: Literal[TOKEN_SESSION_STATUS_KIND]
    :ivar schema_version: 结构模式版本。约束：需符合 ``Literal[TOKEN_SESSION_STATUS_SCHEMA_VERSION]`` 注解；取值固定为 ``TOKEN_SESSION_STATUS_SCHEMA_VERSION``。默认值：`TOKEN_SESSION_STATUS_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: Literal[TOKEN_SESSION_STATUS_SCHEMA_VERSION]
    :ivar token_session_id: 令牌会话标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype token_session_id: str
    :ivar subject_id: 认证主体标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype subject_id: str
    :ivar is_revoked: 令牌会话是否已经撤销。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示当前状态成立，``False`` 表示当前状态不成立。
    :vartype is_revoked: bool
    :ivar revoked_at_epoch: ``revoked_at_epoch`` 字段。约束：需符合 ``int | None`` 注解；允许为空值。默认值：无，必须显式提供。取值语义：用于表达 Unix 时间戳秒值。
    :vartype revoked_at_epoch: int | None
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["token_session_status"] = TOKEN_SESSION_STATUS_KIND
    schema_version: Literal["1.0"] = TOKEN_SESSION_STATUS_SCHEMA_VERSION
    token_session_id: str
    subject_id: str
    is_revoked: bool
    is_expired: bool = False
    is_inconsistent: bool = False
    revoked_at_epoch: int | None
