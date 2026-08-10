"""流状态存储端口。"""

from __future__ import annotations

from typing import Protocol

from src.core.stream_contract.cursor_stream_contract import (
    CursorStreamAppendRequest,
    CursorStreamAppendResult,
    CursorStreamReadRequest,
    CursorStreamWindow,
)
from src.core.stream_contract.stream_access_contract import (
    StreamAccessTicketRecord,
    StreamReplayEventRecord,
    StreamReplayWindow,
    StreamResumeRequest,
    StreamTicketConsumptionRequest,
    StreamTicketLookupRequest,
)


class StreamStateStorePort(Protocol):
    """票据与有限重放状态存储端口。"""

    async def open(self) -> None:
        """打开状态存储资源。"""

        ...

    async def close(self) -> None:
        """关闭状态存储资源。"""

        ...

    async def store_ticket(self, record: StreamAccessTicketRecord) -> None:
        """保存票据摘要记录。

        :param record: 票据摘要记录。
        :type record: StreamAccessTicketRecord
        """

        ...

    async def consume_ticket(self, request: StreamTicketConsumptionRequest) -> bool:
        """原子校验并消费单次票据。

        :param request: 票据消费请求。
        :type request: StreamTicketConsumptionRequest
        :returns: 消费成功返回 ``True``。
        :rtype: bool
        """

        ...

    async def consume_ticket_record(
        self,
        request: StreamTicketLookupRequest,
    ) -> StreamAccessTicketRecord | None:
        """原子消费票据并返回服务端绑定记录。"""

        ...

    async def append_event(
        self,
        record: StreamReplayEventRecord,
        *,
        max_events: int,
    ) -> None:
        """追加有限重放事件。

        :param record: 重放事件记录。
        :type record: StreamReplayEventRecord
        :param max_events: 单流最大保留事件数。
        :type max_events: int
        """

        ...

    async def load_replay_window(self, request: StreamResumeRequest) -> StreamReplayWindow:
        """读取有限重放窗口。

        :param request: 恢复请求。
        :type request: StreamResumeRequest
        :returns: 重放窗口。
        :rtype: StreamReplayWindow
        """

        ...

    async def purge_expired(self) -> int:
        """清理过期票据和事件。

        :returns: 清理记录数。
        :rtype: int
        """

        ...

    async def append_cursor_event(
        self,
        request: CursorStreamAppendRequest,
    ) -> CursorStreamAppendResult:
        """向 versioned cursor 流追加事件。"""

        ...

    async def read_cursor_window(
        self,
        request: CursorStreamReadRequest,
    ) -> CursorStreamWindow:
        """按所有者和 opaque cursor 读取有限窗口。"""

        ...
