"""跨 ASGI 生命周期传递的流会话观测状态。"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.stream_contract.stream_event_contract import StreamCloseReason, StreamTransport

STREAM_ACCESS_OBSERVATION_STATE_KEY = "stream_access_observation"


@dataclass(slots=True)
class StreamAccessObservation:
    """不包含令牌、票据、正文和高基数流标识的访问事实。"""

    operation_name: str
    transport: StreamTransport
    subject_digest: str
    event_count: int = 0
    close_reason: StreamCloseReason = StreamCloseReason.INTERNAL_ERROR
