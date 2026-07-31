"""非流式 HTTP 聚合响应适配器。"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

from src.core.exception_contract.error_code_catalog_contract import SuccessCode
from src.core.http_contract.request_scope_contract import RequestScope
from src.core.http_contract.response_envelope_contract import (
    ResponseEnvelope,
    ResponseEnvelopeFactory,
)
from src.core.stream_contract.stream_delivery_contract import (
    StreamBatchEnvelope,
    StreamBatchRejectedDetail,
)

STREAM_BATCH_COMPLETED_MESSAGE = "流操作执行完成。"

T_StreamDetail = TypeVar("T_StreamDetail", bound=BaseModel)


class HttpBatchResponsePresenter(Generic[T_StreamDetail]):
    """将流聚合结果装入现有统一 HTTP 响应信封。"""

    def __init__(self, *, response_factory: ResponseEnvelopeFactory) -> None:
        """初始化非流式响应适配器。"""

        self._response_factory = response_factory

    def present(
        self,
        *,
        request_scope: RequestScope,
        batch: StreamBatchEnvelope[T_StreamDetail],
    ) -> ResponseEnvelope[StreamBatchEnvelope[T_StreamDetail]]:
        """构建统一 HTTP 响应信封。

        :param request_scope: 当前请求作用域。
        :type request_scope: RequestScope
        :param batch: 流聚合结果。
        :type batch: StreamBatchEnvelope[T_StreamDetail]
        :returns: 统一 HTTP 响应信封。
        :rtype: ResponseEnvelope[StreamBatchEnvelope[T_StreamDetail]]
        """

        detail = batch.detail
        return self._response_factory.build(
            code=(
                detail.error_code
                if isinstance(detail, StreamBatchRejectedDetail)
                else SuccessCode.OK
            ),
            message=(
                detail.message
                if isinstance(detail, StreamBatchRejectedDetail)
                else STREAM_BATCH_COMPLETED_MESSAGE
            ),
            request_scope=request_scope,
            data=batch,
        )
