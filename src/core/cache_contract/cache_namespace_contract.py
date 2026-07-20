"""
缓存命名空间契约核心契约模块。
"""

from __future__ import annotations

from enum import StrEnum

CACHE_KEY_SEGMENT_SEPARATOR = ":"


class CacheNamespace(StrEnum):
    """
    缓存命名空间枚举，用于约束可选取值。

    :cvar AUTH_THROTTLE: ``AUTH_THROTTLE`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'auth_throttle'`。取值语义：用于承载当前对象中的业务状态。
    :vartype AUTH_THROTTLE: str
    :cvar RATE_LIMIT: ``RATE_LIMIT`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'rate_limit'`。取值语义：用于承载限流类缓存状态。
    :vartype RATE_LIMIT: str
    :cvar QUERY_RESULT: ``QUERY_RESULT`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'query_result'`。取值语义：用于承载普通查询缓存结果。
    :vartype QUERY_RESULT: str
    """

    AUTH_THROTTLE = "auth_throttle"
    RATE_LIMIT = "rate_limit"
    QUERY_RESULT = "query_result"
    IP_BLOCK = "ip_block"
    DISTRIBUTED_LOCK = "distributed_lock"
    KEY_RING = "key_ring"
    TOKEN_BINDING = "token_binding"
    RISK_SIGNAL = "risk_signal"
