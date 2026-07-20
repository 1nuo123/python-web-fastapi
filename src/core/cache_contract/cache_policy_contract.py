"""
缓存策略契约核心契约模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.cache_contract.cache_namespace_contract import CacheNamespace

CACHE_POLICY_SCHEMA_VERSION: Final = "1.0"
CACHE_POLICY_HEADER_KIND: Final = "cache_policy"
AUTH_THROTTLE_CACHE_POLICY_DETAIL_KIND: Final = "auth_throttle_cache_policy"
RATE_LIMIT_CACHE_POLICY_DETAIL_KIND: Final = "rate_limit_cache_policy"
QUERY_RESULT_CACHE_POLICY_DETAIL_KIND: Final = "query_result_cache_policy"
CACHE_POLICY_TTL_MINIMUM_SECONDS = 1


class CacheFailureMode(StrEnum):
    """
    缓存故障处理模式枚举，用于约束 Redis 不可用时的运行策略。

    :cvar FAIL_OPEN: 失败开放。Redis 不可用时普通查询缓存按未命中处理。
    :vartype FAIL_OPEN: str
    :cvar FAIL_CLOSED: 失败关闭。Redis 不可用时关键链路继续抛出缓存不可用异常。
    :vartype FAIL_CLOSED: str
    """

    FAIL_OPEN = "fail_open"
    FAIL_CLOSED = "fail_closed"


class CachePolicyHeader(BaseModel):
    """
    缓存策略公共头Pydantic 模型，用于约束策略信封外层公共字段。

    :ivar model_config: Pydantic 模型配置对象。
    :vartype model_config: ConfigDict
    :ivar kind: 公共头类型标识。
    :vartype kind: Literal[CACHE_POLICY_HEADER_KIND]
    :ivar schema_version: 策略结构版本。
    :vartype schema_version: Literal[CACHE_POLICY_SCHEMA_VERSION]
    :ivar detail_kind: 扩展字段类型标识。
    :vartype detail_kind: str
    :ivar namespace: 策略所属缓存命名空间。
    :vartype namespace: CacheNamespace
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["cache_policy"] = CACHE_POLICY_HEADER_KIND
    schema_version: Literal["1.0"] = CACHE_POLICY_SCHEMA_VERSION
    detail_kind: str
    namespace: CacheNamespace


class AuthThrottleCachePolicyDetail(BaseModel):
    """
    鉴权节流缓存策略扩展Pydantic 模型，用于固定认证失败节流的缓存策略。

    :ivar model_config: Pydantic 模型配置对象。
    :vartype model_config: ConfigDict
    :ivar kind: 扩展字段类型标识。
    :vartype kind: Literal[AUTH_THROTTLE_CACHE_POLICY_DETAIL_KIND]
    :ivar schema_version: 策略结构版本。
    :vartype schema_version: Literal[CACHE_POLICY_SCHEMA_VERSION]
    :ivar namespace: 策略所属缓存命名空间。
    :vartype namespace: Literal[CacheNamespace.AUTH_THROTTLE]
    :ivar default_ttl_seconds: 当前命名空间默认缓存 TTL 秒数。
    :vartype default_ttl_seconds: int
    :ivar failure_mode: Redis 不可用时的失败处理模式，固定为失败关闭。
    :vartype failure_mode: Literal[CacheFailureMode.FAIL_CLOSED]
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["auth_throttle_cache_policy"] = AUTH_THROTTLE_CACHE_POLICY_DETAIL_KIND
    schema_version: Literal["1.0"] = CACHE_POLICY_SCHEMA_VERSION
    namespace: Literal[CacheNamespace.AUTH_THROTTLE] = CacheNamespace.AUTH_THROTTLE
    default_ttl_seconds: int = Field(ge=CACHE_POLICY_TTL_MINIMUM_SECONDS)
    failure_mode: Literal[CacheFailureMode.FAIL_CLOSED] = CacheFailureMode.FAIL_CLOSED


class RateLimitCachePolicyDetail(BaseModel):
    """
    限流缓存策略扩展Pydantic 模型，用于固定限流类缓存的故障处理策略。

    :ivar model_config: Pydantic 模型配置对象。
    :vartype model_config: ConfigDict
    :ivar kind: 扩展字段类型标识。
    :vartype kind: Literal[RATE_LIMIT_CACHE_POLICY_DETAIL_KIND]
    :ivar schema_version: 策略结构版本。
    :vartype schema_version: Literal[CACHE_POLICY_SCHEMA_VERSION]
    :ivar namespace: 策略所属缓存命名空间。
    :vartype namespace: Literal[CacheNamespace.RATE_LIMIT]
    :ivar default_ttl_seconds: 当前命名空间默认缓存 TTL 秒数。
    :vartype default_ttl_seconds: int
    :ivar failure_mode: Redis 不可用时的失败处理模式，固定为失败关闭。
    :vartype failure_mode: Literal[CacheFailureMode.FAIL_CLOSED]
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["rate_limit_cache_policy"] = RATE_LIMIT_CACHE_POLICY_DETAIL_KIND
    schema_version: Literal["1.0"] = CACHE_POLICY_SCHEMA_VERSION
    namespace: Literal[CacheNamespace.RATE_LIMIT] = CacheNamespace.RATE_LIMIT
    default_ttl_seconds: int = Field(ge=CACHE_POLICY_TTL_MINIMUM_SECONDS)
    failure_mode: Literal[CacheFailureMode.FAIL_CLOSED] = CacheFailureMode.FAIL_CLOSED


class QueryResultCachePolicyDetail(BaseModel):
    """
    查询结果缓存策略扩展Pydantic 模型，用于约束普通查询缓存的故障处理策略。

    :ivar model_config: Pydantic 模型配置对象。
    :vartype model_config: ConfigDict
    :ivar kind: 扩展字段类型标识。
    :vartype kind: Literal[QUERY_RESULT_CACHE_POLICY_DETAIL_KIND]
    :ivar schema_version: 策略结构版本。
    :vartype schema_version: Literal[CACHE_POLICY_SCHEMA_VERSION]
    :ivar namespace: 策略所属缓存命名空间。
    :vartype namespace: Literal[CacheNamespace.QUERY_RESULT]
    :ivar default_ttl_seconds: 当前命名空间默认缓存 TTL 秒数。
    :vartype default_ttl_seconds: int
    :ivar failure_mode: Redis 不可用时的失败处理模式，默认失败开放。
    :vartype failure_mode: CacheFailureMode
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["query_result_cache_policy"] = QUERY_RESULT_CACHE_POLICY_DETAIL_KIND
    schema_version: Literal["1.0"] = CACHE_POLICY_SCHEMA_VERSION
    namespace: Literal[CacheNamespace.QUERY_RESULT] = CacheNamespace.QUERY_RESULT
    default_ttl_seconds: int = Field(ge=CACHE_POLICY_TTL_MINIMUM_SECONDS)
    failure_mode: CacheFailureMode = CacheFailureMode.FAIL_OPEN


CachePolicyDetailUnion = Annotated[
    AuthThrottleCachePolicyDetail | RateLimitCachePolicyDetail | QueryResultCachePolicyDetail,
    Field(discriminator="kind"),
]


class CachePolicyEnvelope(BaseModel):
    """
    缓存策略信封Pydantic 模型，用于校验公共头字段与强类型扩展字段一致。

    :ivar model_config: Pydantic 模型配置对象。
    :vartype model_config: ConfigDict
    :ivar header: 缓存策略公共头。
    :vartype header: CachePolicyHeader
    :ivar detail: 缓存策略强类型扩展字段。
    :vartype detail: CachePolicyDetailUnion
    """

    model_config = ConfigDict(extra="forbid")

    header: CachePolicyHeader
    detail: CachePolicyDetailUnion

    @model_validator(mode="after")
    def validate_policy_contract(self) -> CachePolicyEnvelope:
        """
        校验策略公共头与扩展字段一致。

        :returns: 返回当前缓存策略信封。
        :rtype: CachePolicyEnvelope
        :raises ValueError: 当公共头与扩展字段不一致时抛出。
        """

        if self.header.detail_kind != self.detail.kind:
            raise ValueError("缓存策略 header.detail_kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("缓存策略 header.schema_version 必须与 detail.schema_version 一致。")
        if self.header.namespace != self.detail.namespace:
            raise ValueError("缓存策略 header.namespace 必须与 detail.namespace 一致。")
        return self
