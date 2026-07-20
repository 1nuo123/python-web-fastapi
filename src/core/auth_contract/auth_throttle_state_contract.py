"""
鉴权节流状态契约核心契约模块。
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

AUTH_THROTTLE_STATE_KIND: Final = "auth_throttle_state"
AUTH_THROTTLE_STATE_SCHEMA_VERSION: Final = "1.0"
AUTH_THROTTLE_FAILURE_COUNT_MINIMUM = 1


class AuthThrottleStatePayload(BaseModel):
    """
    鉴权节流状态Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``Literal[AUTH_THROTTLE_STATE_KIND]`` 注解；取值固定为 ``AUTH_THROTTLE_STATE_KIND``。默认值：`AUTH_THROTTLE_STATE_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: Literal[AUTH_THROTTLE_STATE_KIND]
    :ivar schema_version: 结构模式版本。约束：需符合 ``Literal[AUTH_THROTTLE_STATE_SCHEMA_VERSION]`` 注解；取值固定为 ``AUTH_THROTTLE_STATE_SCHEMA_VERSION``。默认值：`AUTH_THROTTLE_STATE_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: Literal[AUTH_THROTTLE_STATE_SCHEMA_VERSION]
    :ivar failure_count: 累计失败次数。约束：需符合 ``int`` 注解；最小值为 ``AUTH_THROTTLE_FAILURE_COUNT_MINIMUM``。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype failure_count: int
    :ivar locked_until_epoch: 节流锁定截止时间戳。约束：需符合 ``int | None`` 注解；允许为空值。默认值：`None`。取值语义：用于表达 Unix 时间戳秒值。
    :vartype locked_until_epoch: int | None
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["auth_throttle_state"] = AUTH_THROTTLE_STATE_KIND
    schema_version: Literal["1.0"] = AUTH_THROTTLE_STATE_SCHEMA_VERSION
    failure_count: int = Field(ge=AUTH_THROTTLE_FAILURE_COUNT_MINIMUM)
    locked_until_epoch: int | None = None
