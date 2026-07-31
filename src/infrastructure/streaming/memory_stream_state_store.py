"""进程内流状态存储。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from src.application.ports.stream_state_store_port import StreamStateStorePort
from src.core.stream_contract.stream_access_contract import (
    StreamAccessTicketRecord,
    StreamReplayEventRecord,
    StreamReplayWindow,
    StreamResumeRequest,
    StreamTicketConsumptionRequest,
)


class MemoryStreamStateStore(StreamStateStorePort):
    """用于开发和确定性测试的内存状态存储。"""

    def __init__(self, *, opened: bool = False) -> None:
        """初始化空状态存储。"""

        self._tickets: dict[str, StreamAccessTicketRecord] = {}
        self._events: dict[str, list[StreamReplayEventRecord]] = {}
        self._lock = asyncio.Lock()
        self._opened = opened

    async def open(self) -> None:
        """打开状态存储。"""

        self._opened = True

    async def close(self) -> None:
        """关闭并清空状态存储。"""

        async with self._lock:
            self._tickets.clear()
            self._events.clear()
            self._opened = False

    async def store_ticket(self, record: StreamAccessTicketRecord) -> None:
        """保存票据摘要记录。

        :param record: 票据摘要记录。
        :type record: StreamAccessTicketRecord
        """

        self._assert_opened()
        async with self._lock:
            self._tickets[record.ticket_digest] = record

    async def consume_ticket(self, request: StreamTicketConsumptionRequest) -> bool:
        """原子校验并消费单次票据。

        :param request: 票据消费请求。
        :type request: StreamTicketConsumptionRequest
        :returns: 首次合法消费返回 ``True``。
        :rtype: bool
        """

        self._assert_opened()
        async with self._lock:
            record = self._tickets.get(request.ticket_digest)
            if record is None:
                return False
            if request.consumed_at >= record.expires_at:
                self._tickets.pop(request.ticket_digest, None)
                return False
            if record.subject_id != request.subject_id:
                return False
            if record.operation_name != request.operation_name:
                return False
            if record.client_ip is not None and record.client_ip != request.client_ip:
                return False
            self._tickets.pop(request.ticket_digest, None)
            return True

    async def append_event(
        self,
        record: StreamReplayEventRecord,
        *,
        max_events: int,
    ) -> None:
        """追加事件并裁剪到有限窗口。

        :param record: 重放事件记录。
        :type record: StreamReplayEventRecord
        :param max_events: 最大窗口事件数。
        :type max_events: int
        """

        self._assert_opened()
        async with self._lock:
            records = self._events.setdefault(record.stream_id, [])
            if records:
                latest = records[-1]
                if (
                    latest.subject_id != record.subject_id
                    or latest.operation_name != record.operation_name
                ):
                    raise ValueError("同一 stream_id 的恢复事件主体与操作必须一致。")
                if record.sequence != latest.sequence + 1:
                    raise ValueError("恢复事件 sequence 必须连续递增。")
            records.append(record)
            if len(records) > max_events:
                del records[: len(records) - max_events]

    async def load_replay_window(self, request: StreamResumeRequest) -> StreamReplayWindow:
        """读取并鉴权有限重放窗口。

        :param request: 恢复请求。
        :type request: StreamResumeRequest
        :returns: 恢复窗口。
        :rtype: StreamReplayWindow
        """

        self._assert_opened()
        now = datetime.now(UTC)
        async with self._lock:
            records = [
                record
                for record in self._events.get(request.stream_id, [])
                if record.expires_at > now
            ]
            self._events[request.stream_id] = records
            if not records:
                return StreamReplayWindow(
                    stream_id=request.stream_id,
                    events=[],
                    earliest_event_id=None,
                    latest_event_id=None,
                    expired=True,
                )
            if any(
                record.subject_id != request.subject_id
                or record.operation_name != request.operation_name
                for record in records
            ):
                return StreamReplayWindow(
                    stream_id=request.stream_id,
                    events=[],
                    earliest_event_id=None,
                    latest_event_id=None,
                    expired=True,
                )
            matching_index = next(
                (
                    index
                    for index, record in enumerate(records)
                    if record.event_id == request.last_event_id
                ),
                None,
            )
            if matching_index is None:
                return StreamReplayWindow(
                    stream_id=request.stream_id,
                    events=[],
                    earliest_event_id=None,
                    latest_event_id=None,
                    expired=True,
                )
            replay_events = records[matching_index + 1 :]
            return StreamReplayWindow(
                stream_id=request.stream_id,
                events=replay_events,
                earliest_event_id=(replay_events[0].event_id if replay_events else None),
                latest_event_id=(replay_events[-1].event_id if replay_events else None),
                expired=False,
            )

    async def purge_expired(self) -> int:
        """清理全部过期记录。

        :returns: 清理记录数。
        :rtype: int
        """

        self._assert_opened()
        now = datetime.now(UTC)
        async with self._lock:
            expired_tickets = [
                digest for digest, record in self._tickets.items() if record.expires_at <= now
            ]
            for digest in expired_tickets:
                self._tickets.pop(digest, None)
            expired_events = 0
            for stream_id, records in tuple(self._events.items()):
                active_records = [record for record in records if record.expires_at > now]
                expired_events += len(records) - len(active_records)
                if active_records:
                    self._events[stream_id] = active_records
                else:
                    self._events.pop(stream_id, None)
            return len(expired_tickets) + expired_events

    def _assert_opened(self) -> None:
        """断言状态存储已打开。

        :raises RuntimeError: 尚未打开或已经关闭时抛出。
        """

        if not self._opened:
            raise RuntimeError("流状态存储尚未打开。")
