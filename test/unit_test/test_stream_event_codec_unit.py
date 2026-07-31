"""流事件编解码器单元测试。"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from src.api.testing.streaming_test_route_binder import (
    TestStreamDetail,
    TestStreamItemDetail,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.stream_contract.stream_event_contract import (
    StreamEventEnvelope,
    StreamEventHeader,
)
from src.infrastructure.streaming.stream_event_codec import StreamEventCodec


class TestStreamEventCodecUnit:
    """流事件编解码器单元测试集合。"""

    def test_encode_and_decode_when_contract_valid_should_round_trip(self) -> None:
        """验证合法事件应完成强类型往返。"""

        codec = self._build_codec(max_event_bytes=4096)
        event = self._build_event(text="中文事件")

        encoded = codec.encode(event)
        decoded = codec.decode(encoded)

        assert decoded == event
        assert b"test_stream_item" in encoded

    def test_encode_when_event_exceeds_limit_should_raise_http_fault(self) -> None:
        """验证事件超过字节限制应返回稳定故障。"""

        codec = self._build_codec(max_event_bytes=32)

        with pytest.raises(HttpFaultException):
            codec.encode(self._build_event(text="过长" * 64))

    def test_decode_when_extra_field_present_should_reject(self) -> None:
        """验证扩展额外字段应被拒绝。"""

        payload = self._build_event(text="合法").model_dump(mode="json")
        payload["detail"]["unexpected"] = True

        with pytest.raises(ValueError):
            self._build_codec(max_event_bytes=4096).decode(
                TypeAdapter(dict[str, object]).dump_json(payload)
            )

    def _build_codec(self, *, max_event_bytes: int) -> StreamEventCodec[TestStreamDetail]:
        """构建测试编解码器。"""

        return StreamEventCodec(
            adapter=TypeAdapter(StreamEventEnvelope[TestStreamDetail]),
            max_event_bytes=max_event_bytes,
        )

    def _build_event(self, *, text: str) -> StreamEventEnvelope[TestStreamDetail]:
        """构建测试业务事件。"""

        return StreamEventEnvelope[TestStreamDetail](
            header=StreamEventHeader(
                stream_id="stream-1",
                event_id="event-1",
                sequence=0,
                event_kind="test_stream_item",
                request_id="request-1",
                trace_id="trace-1",
            ),
            detail=TestStreamItemDetail(index=0, text=text),
        )
