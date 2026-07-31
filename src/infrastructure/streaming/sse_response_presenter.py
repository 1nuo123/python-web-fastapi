"""Server-Sent Events 响应适配器。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Generic, TypeVar

from pydantic import BaseModel
from sse_starlette import EventSourceResponse, ServerSentEvent

from src.core.stream_contract.stream_delivery_contract import SseEventMapping
from src.core.stream_contract.stream_event_contract import StreamEventEnvelope
from src.infrastructure.streaming.stream_event_codec import StreamEventCodec

SSE_CACHE_CONTROL_HEADER = "Cache-Control"
SSE_CACHE_CONTROL_VALUE = "no-cache, no-transform"
SSE_ACCEL_BUFFERING_HEADER = "X-Accel-Buffering"
SSE_ACCEL_BUFFERING_DISABLED_VALUE = "no"
SSE_HEARTBEAT_COMMENT = "heartbeat"
SSE_TEXT_ENCODING = "utf-8"

T_StreamDetail = TypeVar("T_StreamDetail", bound=BaseModel)


class SseResponsePresenter(Generic[T_StreamDetail]):
    """将统一事件信封映射为标准 SSE 响应。"""

    def __init__(
        self,
        *,
        codec: StreamEventCodec[T_StreamDetail],
        heartbeat_seconds: int,
        retry_milliseconds: int,
        send_timeout_seconds: float,
    ) -> None:
        """初始化 SSE 响应适配器。"""

        self._codec = codec
        self._heartbeat_seconds = heartbeat_seconds
        self._retry_milliseconds = retry_milliseconds
        self._send_timeout_seconds = send_timeout_seconds

    def create_response(
        self,
        events: AsyncGenerator[StreamEventEnvelope[T_StreamDetail], None],
    ) -> EventSourceResponse:
        """创建禁止代理缓冲的 SSE 响应。

        :param events: 统一事件异步迭代器。
        :type events: AsyncIterator[StreamEventEnvelope[T_StreamDetail]]
        :returns: SSE 响应。
        :rtype: EventSourceResponse
        """

        return EventSourceResponse(
            self.iter_sse_events(events),
            ping=self._heartbeat_seconds,
            ping_message_factory=self._build_ping_event,
            send_timeout=self._send_timeout_seconds,
            headers={
                SSE_CACHE_CONTROL_HEADER: SSE_CACHE_CONTROL_VALUE,
                SSE_ACCEL_BUFFERING_HEADER: SSE_ACCEL_BUFFERING_DISABLED_VALUE,
            },
        )

    async def iter_sse_events(
        self,
        events: AsyncGenerator[StreamEventEnvelope[T_StreamDetail], None],
    ) -> AsyncGenerator[ServerSentEvent, None]:
        """迭代 SSE 事件映射。

        :param events: 统一事件异步迭代器。
        :type events: AsyncIterator[StreamEventEnvelope[T_StreamDetail]]
        :returns: SSE 事件异步迭代器。
        :rtype: AsyncIterator[ServerSentEvent]
        """

        try:
            async for event in events:
                mapping = SseEventMapping(
                    event_id=event.header.event_id,
                    event_kind=event.header.event_kind,
                    data_json=self._codec.encode(event).decode(SSE_TEXT_ENCODING),
                    retry_milliseconds=self._retry_milliseconds,
                )
                yield ServerSentEvent(
                    id=mapping.event_id,
                    event=mapping.event_kind,
                    data=mapping.data_json,
                    retry=mapping.retry_milliseconds,
                )
        finally:
            await events.aclose()

    def _build_ping_event(self) -> ServerSentEvent:
        """构建不占用业务序列的 SSE 注释心跳。"""

        return ServerSentEvent(comment=SSE_HEARTBEAT_COMMENT)
