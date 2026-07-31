"""
错误编码目录契约核心契约模块。
"""

from __future__ import annotations

from enum import StrEnum


class SuccessCode(StrEnum):
    """
    成功编码枚举，用于约束可选取值。

    :cvar OK: ``OK`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system.success.ok'`。取值语义：用于承载当前对象中的业务状态。
    :vartype OK: str
    """

    OK = "system.success.ok"


class CoreErrorCode(StrEnum):
    """
    核心错误编码枚举，用于约束可选取值。

    :cvar REQUEST_INVALID: ``REQUEST_INVALID`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system.request.invalid'`。取值语义：用于承载当前对象中的业务状态。
    :vartype REQUEST_INVALID: str
    :cvar REQUEST_PAYLOAD_TOO_LARGE: ``REQUEST_PAYLOAD_TOO_LARGE`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system.request.payload_too_large'`。取值语义：用于承载当前对象中的业务状态。
    :vartype REQUEST_PAYLOAD_TOO_LARGE: str
    :cvar REQUEST_TIMEOUT: ``REQUEST_TIMEOUT`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system.request.timeout'`。取值语义：用于承载当前对象中的业务状态。
    :vartype REQUEST_TIMEOUT: str
    :cvar CONFIG_INVALID: ``CONFIG_INVALID`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system.config.invalid'`。取值语义：用于承载当前对象中的业务状态。
    :vartype CONFIG_INVALID: str
    :cvar INTERNAL_UNEXPECTED: ``INTERNAL_UNEXPECTED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system.internal.unexpected'`。取值语义：用于承载当前对象中的业务状态。
    :vartype INTERNAL_UNEXPECTED: str
    :cvar RESOURCE_NOT_READY: ``RESOURCE_NOT_READY`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system.resource.not_ready'`。取值语义：用于承载当前对象中的业务状态。
    :vartype RESOURCE_NOT_READY: str
    :cvar RELOAD_REJECTED: ``RELOAD_REJECTED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system.reload.rejected'`。取值语义：用于承载当前对象中的业务状态。
    :vartype RELOAD_REJECTED: str
    :cvar RELOAD_FAILED: ``RELOAD_FAILED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system.reload.failed'`。取值语义：用于承载当前对象中的业务状态。
    :vartype RELOAD_FAILED: str
    :cvar TASK_FAILED: ``TASK_FAILED`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system.task.failed'`。取值语义：用于承载当前对象中的业务状态。
    :vartype TASK_FAILED: str
    :cvar DATABASE_UNAVAILABLE: ``DATABASE_UNAVAILABLE`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system.database.unavailable'`。取值语义：用于承载当前对象中的业务状态。
    :vartype DATABASE_UNAVAILABLE: str
    :cvar CACHE_UNAVAILABLE: ``CACHE_UNAVAILABLE`` 字段。约束：需满足当前实现中的类型与状态约束。默认值：`'system.cache.unavailable'`。取值语义：用于承载当前对象中的业务状态。
    :vartype CACHE_UNAVAILABLE: str
    """

    REQUEST_INVALID = "system.request.invalid"
    REQUEST_PAYLOAD_TOO_LARGE = "system.request.payload_too_large"
    REQUEST_TIMEOUT = "system.request.timeout"
    CAPACITY_EXHAUSTED = "system.capacity.exhausted"
    CONFIG_INVALID = "system.config.invalid"
    INTERNAL_UNEXPECTED = "system.internal.unexpected"
    RESOURCE_NOT_READY = "system.resource.not_ready"
    RELOAD_REJECTED = "system.reload.rejected"
    RELOAD_FAILED = "system.reload.failed"
    TASK_FAILED = "system.task.failed"
    DATABASE_UNAVAILABLE = "system.database.unavailable"
    CACHE_UNAVAILABLE = "system.cache.unavailable"
    STREAM_PROTOCOL_INVALID = "system.stream.protocol_invalid"
    STREAM_REPLAY_UNAVAILABLE = "system.stream.replay_unavailable"
    STREAM_TICKET_INVALID = "system.stream.ticket_invalid"
    STREAM_SLOW_CONSUMER = "system.stream.slow_consumer"
