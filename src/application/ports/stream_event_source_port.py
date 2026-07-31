"""协议无关的流事件源端口。"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from src.core.stream_contract.stream_event_contract import StreamTransport

STREAM_CONTEXT_TEXT_MINIMUM_LENGTH = 1


class StreamExecutionContext(BaseModel):
    """流执行上下文。

    :ivar request_id: 请求标识。
    :ivar trace_id: 链路标识。
    :ivar subject_id: 主体标识。
    :ivar client_ip: 客户端 IP。
    :ivar operation_name: 操作名。
    :ivar transport: 交付传输。
    :ivar resumable: 是否启用有限恢复。
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=STREAM_CONTEXT_TEXT_MINIMUM_LENGTH)
    trace_id: str | None
    subject_id: str = Field(min_length=STREAM_CONTEXT_TEXT_MINIMUM_LENGTH)
    client_ip: str = Field(min_length=STREAM_CONTEXT_TEXT_MINIMUM_LENGTH)
    operation_name: str = Field(min_length=STREAM_CONTEXT_TEXT_MINIMUM_LENGTH)
    transport: StreamTransport
    resumable: bool
    deadline: datetime


T_StreamCommand = TypeVar("T_StreamCommand", bound=BaseModel, contravariant=True)
T_StreamDetail = TypeVar("T_StreamDetail", bound=BaseModel, covariant=True)


class StreamEventSourcePort(Protocol[T_StreamCommand, T_StreamDetail]):
    """业务流事件源端口。

    业务实现只产生强类型扩展事件，不感知 HTTP、SSE 或 WebSocket。
    """

    def open(
        self,
        *,
        command: T_StreamCommand,
        context: StreamExecutionContext,
    ) -> AsyncGenerator[T_StreamDetail, None]:
        """打开业务事件源。

        :param command: 强类型业务命令。
        :type command: T_StreamCommand
        :param context: 流执行上下文。
        :type context: StreamExecutionContext
        :returns: 强类型业务事件异步迭代器。
        :rtype: AsyncIterator[T_StreamDetail]
        """

        ...
