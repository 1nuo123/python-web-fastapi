"""
缓存载荷契约核心契约模块。
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.auth_contract.auth_throttle_state_contract import AuthThrottleStatePayload
from src.core.cache_contract.cache_namespace_contract import CacheNamespace

CACHE_ENTRY_TTL_MINIMUM_SECONDS = 1

CachePayload = Annotated[
    AuthThrottleStatePayload,
    Field(discriminator="kind"),
]


class CacheEntryHeader(BaseModel):
    """
    缓存入口头Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar namespace: 缓存命名空间。约束：需符合 ``CacheNamespace`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype namespace: CacheNamespace
    :ivar key: ``key`` 字段。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype key: str
    :ivar ttl_seconds: 缓存 TTL 秒数。约束：需符合 ``int`` 注解；最小值为 ``CACHE_ENTRY_TTL_MINIMUM_SECONDS``。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype ttl_seconds: int
    :ivar value_kind: 缓存值的类型标签。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype value_kind: str
    """

    model_config = ConfigDict(extra="forbid")

    namespace: CacheNamespace
    key: str
    ttl_seconds: int = Field(ge=CACHE_ENTRY_TTL_MINIMUM_SECONDS)
    value_kind: str


class CacheEnvelope(BaseModel):
    """
    缓存信封Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar header: 统一响应头。约束：需符合 ``CacheEntryHeader`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype header: CacheEntryHeader
    :ivar data: 业务数据对象。约束：需符合 ``CachePayload`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype data: CachePayload
    """

    model_config = ConfigDict(extra="forbid")

    header: CacheEntryHeader
    data: CachePayload

    @model_validator(mode="after")
    def validate_value_kind(self) -> CacheEnvelope:
        """
        校验值类型。

        :returns: 返回当前操作结果。
        :rtype: 'CacheEnvelope'
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        if self.header.value_kind != self.data.kind:
            raise ValueError("缓存公共头字段 value_kind 必须与扩展字段 kind 一致。")
        return self
