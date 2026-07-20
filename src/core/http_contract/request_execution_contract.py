"""
请求执行策略契约核心模块。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

REQUEST_EXECUTION_SCHEMA_VERSION: Final = "1.0"
REQUEST_EXECUTION_ENVELOPE_KIND: Final = "request_execution_envelope"
REQUEST_EXECUTION_HEADER_KIND: Final = "request_execution_header"
THREADPOOL_EXECUTION_DETAIL_KIND: Final = "threadpool"
NATIVE_ASYNC_EXECUTION_DETAIL_KIND: Final = "native_async"
REQUEST_EXECUTION_THREADPOOL_MODE = "threadpool"
REQUEST_EXECUTION_NATIVE_ASYNC_MODE = "native_async"
DEFAULT_SYNC_REQUEST_EXECUTION_NAME = "default_sync_usecase"
REQUEST_EXECUTION_NAME_MINIMUM_LENGTH = 1
REQUEST_EXECUTION_OFFLOAD_TIMEOUT_MINIMUM = 1
REQUEST_EXECUTION_CAPACITY_MINIMUM = 1
REQUEST_EXECUTION_QUEUE_WAIT_TIMEOUT_MINIMUM_SECONDS = 1


class RequestExecutionMode(StrEnum):
    """
    请求执行模式枚举。

    ``THREADPOOL`` 表示把同步用例卸载到线程池执行。
    ``NATIVE_ASYNC`` 表示直接等待原生异步函数，避免重复线程切换。
    """

    THREADPOOL = REQUEST_EXECUTION_THREADPOOL_MODE
    NATIVE_ASYNC = REQUEST_EXECUTION_NATIVE_ASYNC_MODE


class RequestExecutionHeader(BaseModel):
    """
    请求执行公共头。

    :ivar kind: 公共头类型标识。约束：固定为 ``request_execution_header``。默认值：``REQUEST_EXECUTION_HEADER_KIND``。取值语义：用于判定公共头结构类型。
    :vartype kind: Literal[REQUEST_EXECUTION_HEADER_KIND]
    :ivar schema_version: 契约版本。约束：固定为 ``1.0``。默认值：``REQUEST_EXECUTION_SCHEMA_VERSION``。取值语义：用于约束头部与扩展字段的版本一致性。
    :vartype schema_version: Literal[REQUEST_EXECUTION_SCHEMA_VERSION]
    :ivar execution_name: 执行策略名称。约束：最小长度为 ``1``。默认值：无，必须显式提供。取值语义：用于把路由调用点和运行时策略显式绑定。
    :vartype execution_name: str
    :ivar enabled: 是否启用显式执行策略。约束：需符合 ``bool`` 注解。默认值：无，必须显式提供。取值语义：``True`` 表示按配置策略执行，``False`` 表示退回默认线程池兜底。
    :vartype enabled: bool
    :ivar mode: 请求执行模式。约束：需符合 ``RequestExecutionMode`` 注解。默认值：无，必须显式提供。取值语义：决定使用线程池卸载还是原生异步执行。
    :vartype mode: RequestExecutionMode
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["request_execution_header"] = REQUEST_EXECUTION_HEADER_KIND
    schema_version: Literal["1.0"] = REQUEST_EXECUTION_SCHEMA_VERSION
    execution_name: str = Field(min_length=REQUEST_EXECUTION_NAME_MINIMUM_LENGTH)
    enabled: bool
    mode: RequestExecutionMode


class ThreadpoolExecutionDetail(BaseModel):
    """
    线程池执行扩展。

    :ivar kind: 扩展字段类型标识。约束：固定为 ``threadpool``。默认值：``THREADPOOL_EXECUTION_DETAIL_KIND``。取值语义：用于判别联合选择线程池扩展模型。
    :vartype kind: Literal[THREADPOOL_EXECUTION_DETAIL_KIND]
    :ivar schema_version: 扩展字段版本。约束：固定为 ``1.0``。默认值：``REQUEST_EXECUTION_SCHEMA_VERSION``。取值语义：必须与外层和公共头版本保持一致。
    :vartype schema_version: Literal[REQUEST_EXECUTION_SCHEMA_VERSION]
    :ivar offload_timeout_seconds: 线程池卸载超时秒数。约束：最小值为 ``1``。默认值：无，必须显式提供。取值语义：用于控制同步用例在事件循环外执行的最长等待时间。
    :vartype offload_timeout_seconds: int
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["threadpool"] = THREADPOOL_EXECUTION_DETAIL_KIND
    schema_version: Literal["1.0"] = REQUEST_EXECUTION_SCHEMA_VERSION
    offload_timeout_seconds: int = Field(ge=REQUEST_EXECUTION_OFFLOAD_TIMEOUT_MINIMUM)
    max_workers: int = Field(ge=REQUEST_EXECUTION_CAPACITY_MINIMUM)
    max_pending_requests: int = Field(ge=REQUEST_EXECUTION_CAPACITY_MINIMUM)
    queue_wait_timeout_seconds: int = Field(ge=REQUEST_EXECUTION_QUEUE_WAIT_TIMEOUT_MINIMUM_SECONDS)


class NativeAsyncExecutionDetail(BaseModel):
    """
    原生异步执行扩展。

    :ivar kind: 扩展字段类型标识。约束：固定为 ``native_async``。默认值：``NATIVE_ASYNC_EXECUTION_DETAIL_KIND``。取值语义：用于判别联合选择原生异步扩展模型。
    :vartype kind: Literal[NATIVE_ASYNC_EXECUTION_DETAIL_KIND]
    :ivar schema_version: 扩展字段版本。约束：固定为 ``1.0``。默认值：``REQUEST_EXECUTION_SCHEMA_VERSION``。取值语义：必须与外层和公共头版本保持一致。
    :vartype schema_version: Literal[REQUEST_EXECUTION_SCHEMA_VERSION]
    :ivar propagate_cancellation: 是否向目标协程传播取消信号。约束：需符合 ``bool`` 注解。默认值：``True``。取值语义：``True`` 表示直接等待协程，``False`` 表示用 ``asyncio.shield`` 隔离取消。
    :vartype propagate_cancellation: bool
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["native_async"] = NATIVE_ASYNC_EXECUTION_DETAIL_KIND
    schema_version: Literal["1.0"] = REQUEST_EXECUTION_SCHEMA_VERSION
    propagate_cancellation: bool = True


RequestExecutionDetailUnion = Annotated[
    ThreadpoolExecutionDetail | NativeAsyncExecutionDetail,
    Field(discriminator="kind"),
]


class RequestExecutionEnvelope(BaseModel):
    """
    请求执行策略信封。

    :ivar envelope_kind: 外层信封类型标识。约束：固定为 ``request_execution_envelope``。默认值：``REQUEST_EXECUTION_ENVELOPE_KIND``。取值语义：用于判定当前配置块属于请求执行策略。
    :vartype envelope_kind: Literal[REQUEST_EXECUTION_ENVELOPE_KIND]
    :ivar schema_version: 外层信封版本。约束：固定为 ``1.0``。默认值：``REQUEST_EXECUTION_SCHEMA_VERSION``。取值语义：必须与公共头和扩展字段版本保持一致。
    :vartype schema_version: Literal[REQUEST_EXECUTION_SCHEMA_VERSION]
    :ivar header: 公共头字段。约束：需符合 ``RequestExecutionHeader`` 注解。默认值：无，必须显式提供。取值语义：承载对全部执行模式通用的名称、启用状态和模式标识。
    :vartype header: RequestExecutionHeader
    :ivar detail: 强类型扩展字段。约束：需符合 ``RequestExecutionDetailUnion`` 判别联合，且 ``kind`` 与 ``header.mode`` 一致。默认值：无，必须显式提供。取值语义：承载当前执行模式专属的运行参数。
    :vartype detail: RequestExecutionDetailUnion
    """

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["request_execution_envelope"] = REQUEST_EXECUTION_ENVELOPE_KIND
    schema_version: Literal["1.0"] = REQUEST_EXECUTION_SCHEMA_VERSION
    header: RequestExecutionHeader
    detail: RequestExecutionDetailUnion

    @model_validator(mode="after")
    def validate_execution_contract(self) -> RequestExecutionEnvelope:
        """
        校验执行契约一致性。

        :returns: 返回通过一致性校验后的当前信封对象。
        :rtype: RequestExecutionEnvelope
        :raises ValueError: 当外层版本、公共头模式或扩展字段类型不一致时抛出。
        """

        if self.header.schema_version != self.detail.schema_version:
            raise ValueError(
                "runtime.web.request_execution.header.schema_version 与 detail.schema_version 不一致。"
            )
        if self.header.mode.value != self.detail.kind:
            raise ValueError("runtime.web.request_execution.header.mode 与 detail.kind 不一致。")
        if self.schema_version != self.detail.schema_version:
            raise ValueError(
                "runtime.web.request_execution.schema_version 与 detail.schema_version 不一致。"
            )
        return self
