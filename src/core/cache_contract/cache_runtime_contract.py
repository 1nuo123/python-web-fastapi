"""
缓存运行时契约核心契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.cache_contract.cache_policy_contract import CachePolicyEnvelope

CACHE_TTL_MINIMUM_SECONDS = 1
CACHE_KEY_PREFIX_MINIMUM_LENGTH = 1
MEMORY_CACHE_BACKEND_KIND: Final = "memory_cache_backend"
REDIS_CACHE_BACKEND_KIND: Final = "redis_cache_backend"
CACHE_BACKEND_DETAIL_SCHEMA_VERSION: Final = "1.0"
MEMORY_CACHE_MAX_ENTRIES_MINIMUM = 1
REDIS_SOCKET_CONNECT_TIMEOUT_MINIMUM_SECONDS = 1
REDIS_MAX_CONNECTIONS_MINIMUM = 1


class CacheBackend(StrEnum):
    """
    缓存后端枚举，用于约束可选取值。

    :cvar MEMORY: ``MEMORY`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'memory'`。取值语义：用于承载当前对象中的业务状态。
    :vartype MEMORY: str
    :cvar REDIS: ``REDIS`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'redis'`。取值语义：用于承载当前对象中的业务状态。
    :vartype REDIS: str
    """

    MEMORY = "memory"
    REDIS = "redis"


class MemoryCacheBackendDetail(BaseModel):
    """
    内存缓存后端详情Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``Literal[MEMORY_CACHE_BACKEND_KIND]`` 注解；取值固定为 ``MEMORY_CACHE_BACKEND_KIND``。默认值：`MEMORY_CACHE_BACKEND_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: Literal[MEMORY_CACHE_BACKEND_KIND]
    :ivar schema_version: 结构模式版本。约束：需符合 ``Literal[CACHE_BACKEND_DETAIL_SCHEMA_VERSION]`` 注解；取值固定为 ``CACHE_BACKEND_DETAIL_SCHEMA_VERSION``。默认值：`CACHE_BACKEND_DETAIL_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: Literal[CACHE_BACKEND_DETAIL_SCHEMA_VERSION]
    :ivar max_entries: 内存缓存最大条目数。约束：需符合 ``int`` 注解；最小值为 ``MEMORY_CACHE_MAX_ENTRIES_MINIMUM``。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype max_entries: int
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["memory_cache_backend"] = MEMORY_CACHE_BACKEND_KIND
    schema_version: Literal["1.0"] = CACHE_BACKEND_DETAIL_SCHEMA_VERSION
    max_entries: int = Field(ge=MEMORY_CACHE_MAX_ENTRIES_MINIMUM)


class RedisCacheBackendDetail(BaseModel):
    """
    Redis缓存后端详情Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar kind: 结构版本的具体类型标识。约束：需符合 ``Literal[REDIS_CACHE_BACKEND_KIND]`` 注解；取值固定为 ``REDIS_CACHE_BACKEND_KIND``。默认值：`REDIS_CACHE_BACKEND_KIND`。取值语义：用于承载当前对象中的业务状态。
    :vartype kind: Literal[REDIS_CACHE_BACKEND_KIND]
    :ivar schema_version: 结构模式版本。约束：需符合 ``Literal[CACHE_BACKEND_DETAIL_SCHEMA_VERSION]`` 注解；取值固定为 ``CACHE_BACKEND_DETAIL_SCHEMA_VERSION``。默认值：`CACHE_BACKEND_DETAIL_SCHEMA_VERSION`。取值语义：用于承载当前对象中的业务状态。
    :vartype schema_version: Literal[CACHE_BACKEND_DETAIL_SCHEMA_VERSION]
    :ivar redis_url: Redis 连接地址。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于连接外部资源或数据库。
    :vartype redis_url: str
    :ivar socket_connect_timeout_seconds: Redis 连接超时秒数。约束：需符合 ``int`` 注解；最小值为 ``REDIS_SOCKET_CONNECT_TIMEOUT_MINIMUM_SECONDS``。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype socket_connect_timeout_seconds: int
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["redis_cache_backend"] = REDIS_CACHE_BACKEND_KIND
    schema_version: Literal["1.0"] = CACHE_BACKEND_DETAIL_SCHEMA_VERSION


CacheBackendDetail = Annotated[
    MemoryCacheBackendDetail | RedisCacheBackendDetail,
    Field(discriminator="kind"),
]


class CacheRuntimeSettings(BaseModel):
    """
    缓存运行时Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar backend: 后端类型。约束：需符合 ``CacheBackend`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype backend: CacheBackend
    :ivar default_ttl_seconds: 默认缓存 TTL 秒数。约束：需符合 ``int`` 注解；最小值为 ``CACHE_TTL_MINIMUM_SECONDS``。默认值：无，必须显式提供。取值语义：用于表达秒级持续时间或超时窗口。
    :vartype default_ttl_seconds: int
    :ivar key_prefix: 缓存键前缀。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype key_prefix: str
    :ivar backend_detail: 后端明细配置。约束：需符合 ``CacheBackendDetail`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype backend_detail: CacheBackendDetail
    """

    model_config = ConfigDict(extra="forbid")

    backend: CacheBackend
    default_ttl_seconds: int = Field(ge=CACHE_TTL_MINIMUM_SECONDS)
    key_prefix: str
    backend_detail: CacheBackendDetail
    namespace_policies: list[CachePolicyEnvelope] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_backend_detail(self) -> CacheRuntimeSettings:
        """
        校验后端详情。

        :returns: 返回当前操作结果。
        :rtype: 'CacheRuntimeSettings'
        :raises ValueError: 当输入值或配置值不满足当前实现约束时抛出。
        """

        if len(self.key_prefix.strip()) < CACHE_KEY_PREFIX_MINIMUM_LENGTH:
            raise ValueError("runtime.cache.key_prefix 不能为空。")
        if self.backend == CacheBackend.MEMORY and not isinstance(
            self.backend_detail,
            MemoryCacheBackendDetail,
        ):
            raise ValueError(
                "runtime.cache.backend 为 memory 时，backend_detail 必须是内存缓存扩展配置。"
            )
        if self.backend == CacheBackend.REDIS and not isinstance(
            self.backend_detail,
            RedisCacheBackendDetail,
        ):
            raise ValueError(
                "runtime.cache.backend 为 redis 时，backend_detail 必须是 Redis 缓存扩展配置。"
            )
        return self
