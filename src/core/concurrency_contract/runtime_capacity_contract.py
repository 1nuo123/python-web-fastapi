"""运行时容量策略核心契约模块。"""

from __future__ import annotations

from enum import StrEnum
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RUNTIME_CAPACITY_SCHEMA_VERSION: Final = "1.0"
RUNTIME_CAPACITY_HEADER_KIND: Final = "runtime_capacity_header"
BOUNDED_RUNTIME_CAPACITY_DETAIL_KIND: Final = "bounded_runtime_capacity"
CAPACITY_MINIMUM = 1
CAPACITY_ZERO = 0


class CapacityExhaustionBehavior(StrEnum):
    """容量耗尽行为枚举。"""

    REJECT = "reject"


class RuntimeCapacityHeader(BaseModel):
    """运行时容量策略公共头。

    :ivar kind: 公共头类型。
    :vartype kind: Literal["runtime_capacity_header"]
    :ivar schema_version: 契约版本。
    :vartype schema_version: Literal["1.0"]
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["runtime_capacity_header"] = RUNTIME_CAPACITY_HEADER_KIND
    schema_version: Literal["1.0"] = RUNTIME_CAPACITY_SCHEMA_VERSION


class BoundedRuntimeCapacityDetail(BaseModel):
    """有界运行时容量扩展字段。

    :ivar database_connection_limit: 单实例数据库最大连接数。
    :vartype database_connection_limit: int
    :ivar request_worker_limit: 同步请求工作线程上限。
    :vartype request_worker_limit: int
    :ivar request_pending_limit: 等待进入线程池的请求上限。
    :vartype request_pending_limit: int
    :ivar outbound_http_connection_limit: 对外 HTTP 连接上限。
    :vartype outbound_http_connection_limit: int
    :ivar cache_connection_limit: 缓存连接或内存条目上限。
    :vartype cache_connection_limit: int
    :ivar task_worker_limit: 当前节点任务消费者上限。
    :vartype task_worker_limit: int
    :ivar message_queue_limit: 本地消息保留队列上限。
    :vartype message_queue_limit: int
    :ivar log_queue_limit: 异步日志写队列上限。
    :vartype log_queue_limit: int
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["bounded_runtime_capacity"] = BOUNDED_RUNTIME_CAPACITY_DETAIL_KIND
    schema_version: Literal["1.0"] = RUNTIME_CAPACITY_SCHEMA_VERSION
    database_connection_limit: int = Field(ge=CAPACITY_MINIMUM)
    request_worker_limit: int = Field(ge=CAPACITY_ZERO)
    request_pending_limit: int = Field(ge=CAPACITY_ZERO)
    request_queue_wait_timeout_seconds: int = Field(ge=CAPACITY_ZERO)
    request_offload_timeout_seconds: int = Field(ge=CAPACITY_ZERO)
    outbound_http_connection_limit: int = Field(ge=CAPACITY_MINIMUM)
    outbound_http_keepalive_limit: int = Field(ge=CAPACITY_MINIMUM)
    outbound_http_timeout_seconds: int = Field(ge=CAPACITY_MINIMUM)
    cache_connection_limit: int = Field(ge=CAPACITY_MINIMUM)
    task_worker_limit: int = Field(ge=CAPACITY_ZERO)
    message_queue_limit: int = Field(ge=CAPACITY_MINIMUM)
    log_queue_limit: int = Field(ge=CAPACITY_MINIMUM)
    exhaustion_behavior: CapacityExhaustionBehavior = CapacityExhaustionBehavior.REJECT


class RuntimeCapacityPolicy(BaseModel):
    """统一运行时容量策略信封。

    :ivar header: 公共头字段。
    :vartype header: RuntimeCapacityHeader
    :ivar detail: 有界资源容量扩展字段。
    :vartype detail: BoundedRuntimeCapacityDetail
    """

    model_config = ConfigDict(extra="forbid")

    header: RuntimeCapacityHeader
    detail: BoundedRuntimeCapacityDetail

    @model_validator(mode="after")
    def validate_capacity_contract(self) -> RuntimeCapacityPolicy:
        """校验容量策略公共头与扩展字段版本一致。

        :returns: 当前容量策略。
        :rtype: RuntimeCapacityPolicy
        :raises ValueError: 当契约版本不一致时抛出。
        """

        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("运行时容量策略 header 与 detail 版本不一致。")
        if self.detail.outbound_http_keepalive_limit > self.detail.outbound_http_connection_limit:
            raise ValueError("HTTP 保活连接上限不能超过总连接上限。")
        return self
