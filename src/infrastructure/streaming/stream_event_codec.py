"""流事件强类型编解码器。"""

from __future__ import annotations

from http import HTTPStatus
from typing import Generic, TypeVar

import orjson
from pydantic import BaseModel, TypeAdapter

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.stream_contract.stream_event_contract import StreamEventEnvelope

STREAM_EVENT_SIZE_LIMIT_MESSAGE = "流事件超过最大字节限制。"

T_StreamDetail = TypeVar("T_StreamDetail", bound=BaseModel)


class StreamEventCodec(Generic[T_StreamDetail]):
    """使用业务事件联合执行强类型 JSON 编解码。"""

    def __init__(
        self,
        *,
        adapter: TypeAdapter[StreamEventEnvelope[T_StreamDetail]],
        max_event_bytes: int,
    ) -> None:
        """初始化事件编解码器。

        :param adapter: 业务事件信封适配器。
        :type adapter: TypeAdapter[StreamEventEnvelope[T_StreamDetail]]
        :param max_event_bytes: 最大事件字节数。
        :type max_event_bytes: int
        """

        self._adapter = adapter
        self._max_event_bytes = max_event_bytes

    def encode(self, event: StreamEventEnvelope[T_StreamDetail]) -> bytes:
        """校验并编码完整事件信封。

        :param event: 流事件信封。
        :type event: StreamEventEnvelope[T_StreamDetail]
        :returns: UTF-8 JSON 字节串。
        :rtype: bytes
        :raises HttpFaultException: 编码结果超过限制时抛出。
        """

        validated = self._adapter.validate_python(event)
        payload = orjson.dumps(validated.model_dump(mode="json"))
        self._validate_size(payload)
        return payload

    def decode(self, payload: bytes | str) -> StreamEventEnvelope[T_StreamDetail]:
        """解码并校验完整事件信封。

        :param payload: JSON 字节串或文本。
        :type payload: bytes | str
        :returns: 强类型事件信封。
        :rtype: StreamEventEnvelope[T_StreamDetail]
        """

        encoded = payload.encode("utf-8") if isinstance(payload, str) else payload
        self._validate_size(encoded)
        return self._adapter.validate_json(encoded)

    def _validate_size(self, payload: bytes) -> None:
        """校验事件字节上限。"""

        if len(payload) > self._max_event_bytes:
            raise HttpFaultException(
                status_code=HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                error_code=CoreErrorCode.REQUEST_PAYLOAD_TOO_LARGE,
                message=STREAM_EVENT_SIZE_LIMIT_MESSAGE,
            )
