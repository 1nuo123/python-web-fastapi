"""
响应信封契约核心契约模块。
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from src.core.http_contract.request_scope_contract import RequestScope

RESPONSE_SCHEMA_VERSION = "1.0"

T_ResponsePayload = TypeVar("T_ResponsePayload", bound=BaseModel)


class ResponseHeader(BaseModel):
    """
    响应头Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar code: 统一响应码。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype code: str
    :ivar message: 消息文本。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype message: str
    :ivar request_id: 请求唯一标识。约束：需符合 ``str`` 注解。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype request_id: str
    :ivar trace_id: 链路追踪标识。约束：需符合 ``str | None`` 注解；允许为空值。默认值：无，必须显式提供。取值语义：用于唯一标识对应实体。
    :vartype trace_id: str | None
    """

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    request_id: str
    trace_id: str | None


class ResponseEnvelope(BaseModel, Generic[T_ResponsePayload]):
    """
    响应信封Pydantic 模型，用于承载并校验结构化数据。

    :ivar model_config: Pydantic 模型配置对象。约束：需满足当前实现中的类型与状态约束。默认值：`ConfigDict(extra='forbid')`。取值语义：用于控制 Pydantic 模型的额外字段和校验行为。
    :vartype model_config: ConfigDict
    :ivar header: 统一响应头。约束：需符合 ``ResponseHeader`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype header: ResponseHeader
    :ivar data: 业务数据对象。约束：需符合 ``T_ResponsePayload`` 注解。默认值：无，必须显式提供。取值语义：用于承载当前对象中的业务状态。
    :vartype data: T_ResponsePayload
    """

    model_config = ConfigDict(extra="forbid")

    header: ResponseHeader
    data: T_ResponsePayload


class ResponseEnvelopeFactory:
    """
    响应信封工厂，负责构建目标对象。
    """

    def build(
        self,
        *,
        code: str,
        message: str,
        request_scope: RequestScope,
        data: T_ResponsePayload,
    ) -> ResponseEnvelope[T_ResponsePayload]:
        """
        处理构建。

        :param code: 统一响应码。约束：需符合 ``str`` 注解。
        :type code: str
        :param message: 消息对象或消息文本。约束：需符合 ``str`` 注解。
        :type message: str
        :param request_scope: 当前请求作用域快照，用于回填统一响应头和链路信息。约束：需符合 ``RequestScope`` 注解。
        :type request_scope: RequestScope
        :param data: 统一响应中的业务数据。约束：需符合 ``T_ResponsePayload`` 注解。
        :type data: T_ResponsePayload
        :returns: 返回当前操作结果。
        :rtype: ResponseEnvelope[T_ResponsePayload]
        """

        return ResponseEnvelope[T_ResponsePayload](
            header=ResponseHeader(
                code=code,
                message=message,
                request_id=request_scope.request_id,
                trace_id=request_scope.trace_id,
            ),
            data=data,
        )
