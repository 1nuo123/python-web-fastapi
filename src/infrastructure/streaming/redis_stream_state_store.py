"""Redis 流状态存储。"""

from __future__ import annotations

import base64
import json
from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Final, cast
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import RedisError

from src.application.ports.stream_state_store_port import StreamStateStorePort
from src.core.stream_contract.cursor_stream_contract import (
    CursorStreamAppendRequest,
    CursorStreamAppendResult,
    CursorStreamEvent,
    CursorStreamReadRequest,
    CursorStreamWindow,
    OpaqueStreamCursorCodec,
)
from src.core.stream_contract.stream_access_contract import (
    StreamAccessTicketRecord,
    StreamReplayEventRecord,
    StreamReplayWindow,
    StreamResumeRequest,
    StreamTicketConsumptionRequest,
    StreamTicketLookupRequest,
)

REDIS_STREAM_TEXT_ENCODING: Final = "utf-8"
REDIS_TICKET_NAMESPACE: Final = "ticket"
REDIS_EVENT_NAMESPACE: Final = "events"
REDIS_CURSOR_NAMESPACE: Final = "cursor"
REDIS_KEY_SEPARATOR: Final = ":"
REDIS_NULL_CLIENT_IP: Final = ""
REDIS_TICKET_CONSUME_SCRIPT: Final = """
local payload = redis.call('GET', KEYS[1])
if not payload then return 0 end
local record = cjson.decode(payload)
if tonumber(record.expires_at_epoch) <= tonumber(ARGV[1]) then
    redis.call('DEL', KEYS[1])
    return 0
end
if record.subject_id ~= ARGV[2] or record.operation_name ~= ARGV[3] then return 0 end
if record.client_ip ~= '' and record.client_ip ~= ARGV[4] then return 0 end
redis.call('DEL', KEYS[1])
return 1
"""
REDIS_TICKET_LOOKUP_SCRIPT: Final = """
local payload = redis.call('GET', KEYS[1])
if not payload then return nil end
local record = cjson.decode(payload)
if tonumber(record.expires_at_epoch) <= tonumber(ARGV[1]) then
    redis.call('DEL', KEYS[1])
    return nil
end
if record.operation_name ~= ARGV[2] then return nil end
if record.client_ip ~= '' and record.client_ip ~= ARGV[3] then return nil end
redis.call('DEL', KEYS[1])
return payload
"""
REDIS_EVENT_APPEND_SCRIPT: Final = """
local latest_payload = redis.call('LINDEX', KEYS[1], -1)
local current = cjson.decode(ARGV[1])
if latest_payload then
    local latest = cjson.decode(latest_payload)
    if latest.subject_id ~= current.subject_id then return 0 end
    if latest.operation_name ~= current.operation_name then return 0 end
    if tonumber(current.sequence) ~= tonumber(latest.sequence) + 1 then return 0 end
end
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('LTRIM', KEYS[1], -tonumber(ARGV[2]), -1)
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return 1
"""
REDIS_STREAM_UNAVAILABLE_MESSAGE: Final = "Redis 流状态存储不可用。"
REDIS_CURSOR_INITIAL_ID: Final = "0-0"
REDIS_CURSOR_FIELD_OWNER: Final = "owner_subject_id"
REDIS_CURSOR_FIELD_EVENT_ID: Final = "event_id"
REDIS_CURSOR_FIELD_PAYLOAD: Final = "payload"
REDIS_CURSOR_FIELD_EXPIRES_AT: Final = "expires_at"


class RedisStreamStateStore(StreamStateStorePort):
    """提供原子单次票据与有限事件窗口的 Redis 状态存储。"""

    def __init__(
        self,
        *,
        client: Redis,
        key_prefix: str,
    ) -> None:
        """初始化 Redis 状态存储配置。"""

        self._client = client
        self._key_prefix = key_prefix

    async def open(self) -> None:
        """建立连接池并探测 Redis。"""

        try:
            await cast(Awaitable[bool], self._get_client().ping())
        except RedisError as exc:
            raise RuntimeError(REDIS_STREAM_UNAVAILABLE_MESSAGE) from exc

    async def close(self) -> None:
        """关闭 Redis 连接池。"""

        return None

    async def store_ticket(self, record: StreamAccessTicketRecord) -> None:
        """保存带 TTL 的票据摘要记录。"""

        ttl_seconds = max(1, int((record.expires_at - datetime.now(UTC)).total_seconds()))
        payload = json.dumps(
            {
                "subject_id": record.subject_id,
                "operation_name": record.operation_name,
                "client_ip": record.client_ip or REDIS_NULL_CLIENT_IP,
                "expires_at_epoch": record.expires_at.timestamp(),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        try:
            await cast(
                Awaitable[bool],
                self._get_client().set(
                    self._build_key(REDIS_TICKET_NAMESPACE, record.ticket_digest),
                    payload,
                    ex=ttl_seconds,
                ),
            )
        except RedisError as exc:
            raise RuntimeError(REDIS_STREAM_UNAVAILABLE_MESSAGE) from exc

    async def consume_ticket(self, request: StreamTicketConsumptionRequest) -> bool:
        """原子校验并消费单次票据。"""

        try:
            result = await cast(
                Awaitable[int],
                self._get_client().eval(
                    REDIS_TICKET_CONSUME_SCRIPT,
                    1,
                    self._build_key(REDIS_TICKET_NAMESPACE, request.ticket_digest),
                    request.consumed_at.timestamp(),
                    request.subject_id,
                    request.operation_name,
                    request.client_ip or REDIS_NULL_CLIENT_IP,
                ),
            )
        except RedisError as exc:
            raise RuntimeError(REDIS_STREAM_UNAVAILABLE_MESSAGE) from exc
        return int(result) == 1

    async def consume_ticket_record(
        self,
        request: StreamTicketLookupRequest,
    ) -> StreamAccessTicketRecord | None:
        """原子取出票据记录，使浏览器 URL 无需携带主体标识。"""

        try:
            payload = await cast(
                Awaitable[str | None],
                self._get_client().eval(
                    REDIS_TICKET_LOOKUP_SCRIPT,
                    1,
                    self._build_key(REDIS_TICKET_NAMESPACE, request.ticket_digest),
                    request.consumed_at.timestamp(),
                    request.operation_name,
                    request.client_ip or REDIS_NULL_CLIENT_IP,
                ),
            )
        except RedisError as exc:
            raise RuntimeError(REDIS_STREAM_UNAVAILABLE_MESSAGE) from exc
        if payload is None:
            return None
        decoded = cast(dict[str, object], json.loads(payload))
        return StreamAccessTicketRecord(
            ticket_digest=request.ticket_digest,
            subject_id=str(decoded["subject_id"]),
            operation_name=str(decoded["operation_name"]),
            client_ip=(str(decoded["client_ip"]) or None),
            expires_at=datetime.fromtimestamp(
                float(str(decoded["expires_at_epoch"])),
                tz=UTC,
            ),
        )

    async def append_event(
        self,
        record: StreamReplayEventRecord,
        *,
        max_events: int,
    ) -> None:
        """原子追加并裁剪有限事件窗口。"""

        key = self._build_key(REDIS_EVENT_NAMESPACE, record.stream_id)
        ttl_seconds = max(1, int((record.expires_at - datetime.now(UTC)).total_seconds()))
        try:
            result = await cast(
                Awaitable[int],
                self._get_client().eval(
                    REDIS_EVENT_APPEND_SCRIPT,
                    1,
                    key,
                    record.model_dump_json(),
                    max_events,
                    ttl_seconds,
                ),
            )
        except RedisError as exc:
            raise RuntimeError(REDIS_STREAM_UNAVAILABLE_MESSAGE) from exc
        if int(result) != 1:
            raise ValueError("Redis 恢复事件主体、操作或 sequence 不连续。")

    async def load_replay_window(self, request: StreamResumeRequest) -> StreamReplayWindow:
        """读取并鉴权有限重放窗口。"""

        try:
            payloads = await cast(
                Awaitable[list[str]],
                self._get_client().lrange(
                    self._build_key(REDIS_EVENT_NAMESPACE, request.stream_id),
                    0,
                    -1,
                ),
            )
        except RedisError as exc:
            raise RuntimeError(REDIS_STREAM_UNAVAILABLE_MESSAGE) from exc
        records = [StreamReplayEventRecord.model_validate_json(payload) for payload in payloads]
        now = datetime.now(UTC)
        records = [record for record in records if record.expires_at > now]
        if not records or any(
            record.subject_id != request.subject_id
            or record.operation_name != request.operation_name
            for record in records
        ):
            return self._build_empty_window(request.stream_id)
        matching_index = next(
            (
                index
                for index, record in enumerate(records)
                if record.event_id == request.last_event_id
            ),
            None,
        )
        if matching_index is None:
            return self._build_empty_window(request.stream_id)
        events = records[matching_index + 1 :]
        return StreamReplayWindow(
            stream_id=request.stream_id,
            events=events,
            earliest_event_id=events[0].event_id if events else None,
            latest_event_id=events[-1].event_id if events else None,
            expired=False,
        )

    async def purge_expired(self) -> int:
        """依赖 Redis TTL 清理过期记录。

        :returns: Redis 自动清理模式固定返回零。
        :rtype: int
        """

        return 0

    async def append_cursor_event(
        self,
        request: CursorStreamAppendRequest,
    ) -> CursorStreamAppendResult:
        """用 Redis Streams 原子追加并按长度裁剪。"""

        key = self._build_key(REDIS_CURSOR_NAMESPACE, request.event.stream_key)
        ttl_seconds = max(
            1,
            int((request.event.expires_at - datetime.now(UTC)).total_seconds()),
        )
        fields: dict[
            bytes | bytearray | memoryview[int] | str | int | float,
            bytes | bytearray | memoryview[int] | str | int | float,
        ] = {
            REDIS_CURSOR_FIELD_OWNER: request.event.owner_subject_id,
            REDIS_CURSOR_FIELD_EVENT_ID: str(request.event.event_id),
            REDIS_CURSOR_FIELD_PAYLOAD: base64.b64encode(request.event.payload).decode("ascii"),
            REDIS_CURSOR_FIELD_EXPIRES_AT: request.event.expires_at.isoformat(),
        }
        try:
            stream_id = await cast(
                Awaitable[str],
                self._get_client().xadd(
                    key,
                    fields,
                    maxlen=request.max_events,
                    approximate=False,
                ),
            )
            await cast(Awaitable[bool], self._get_client().expire(key, ttl_seconds))
        except RedisError as exc:
            raise RuntimeError(REDIS_STREAM_UNAVAILABLE_MESSAGE) from exc
        return CursorStreamAppendResult(
            stream_key=request.event.stream_key,
            event_id=request.event.event_id,
            cursor=OpaqueStreamCursorCodec.encode(stream_id),
        )

    async def read_cursor_window(
        self,
        request: CursorStreamReadRequest,
    ) -> CursorStreamWindow:
        """按 owner 读取 opaque cursor 后的有限 Redis Stream 窗口。"""

        key = self._build_key(REDIS_CURSOR_NAMESPACE, request.stream_key)
        after_id = (
            REDIS_CURSOR_INITIAL_ID
            if request.after_cursor is None
            else OpaqueStreamCursorCodec.decode(request.after_cursor)
        )
        try:
            first = await cast(
                Awaitable[list[tuple[str, dict[str, str]]]],
                self._get_client().xrange(key, min="-", max="+", count=1),
            )
            if (
                request.after_cursor is not None
                and first
                and self._stream_id_before(after_id, first[0][0])
            ):
                return CursorStreamWindow(
                    stream_key=request.stream_key,
                    events=(),
                    cursors=(),
                    gap=True,
                    snapshot_required=True,
                )
            response = await cast(
                Awaitable[list[tuple[str, list[tuple[str, dict[str, str]]]]]],
                self._get_client().xread({key: after_id}, count=request.limit),
            )
        except RedisError as exc:
            raise RuntimeError(REDIS_STREAM_UNAVAILABLE_MESSAGE) from exc
        if not response:
            return CursorStreamWindow(
                stream_key=request.stream_key,
                events=(),
                cursors=(),
                next_cursor=request.after_cursor,
            )
        now = datetime.now(UTC)
        records: list[CursorStreamEvent] = []
        cursors: list[str] = []
        for stream_id, fields in response[0][1]:
            if fields.get(REDIS_CURSOR_FIELD_OWNER) != request.owner_subject_id:
                raise PermissionError("cursor流owner校验失败。")
            expires_at = datetime.fromisoformat(fields[REDIS_CURSOR_FIELD_EXPIRES_AT])
            if expires_at <= now:
                continue
            records.append(
                CursorStreamEvent(
                    stream_key=request.stream_key,
                    owner_subject_id=request.owner_subject_id,
                    event_id=UUID(fields[REDIS_CURSOR_FIELD_EVENT_ID]),
                    payload=base64.b64decode(fields[REDIS_CURSOR_FIELD_PAYLOAD], validate=True),
                    expires_at=expires_at,
                )
            )
            cursors.append(OpaqueStreamCursorCodec.encode(stream_id))
        return CursorStreamWindow(
            stream_key=request.stream_key,
            events=tuple(records),
            cursors=tuple(cursors),
            next_cursor=cursors[-1] if cursors else request.after_cursor,
        )

    def _stream_id_before(self, left: str, right: str) -> bool:
        """只在 Redis adapter 内比较 Redis stream id。"""

        try:
            left_time, left_sequence = (int(value) for value in left.split("-", maxsplit=1))
            right_time, right_sequence = (int(value) for value in right.split("-", maxsplit=1))
        except ValueError as exc:
            raise ValueError("Redis stream cursor结构无效。") from exc
        return (left_time, left_sequence) < (right_time, right_sequence)

    def _get_client(self) -> Redis:
        """获取延迟创建的异步 Redis 客户端。"""

        return self._client

    def _build_key(self, namespace: str, identifier: str) -> str:
        """构建 Redis 键。"""

        return REDIS_KEY_SEPARATOR.join((self._key_prefix, namespace, identifier))

    def _build_empty_window(self, stream_id: str) -> StreamReplayWindow:
        """构建过期或不可恢复的空窗口。"""

        return StreamReplayWindow(
            stream_id=stream_id,
            events=[],
            earliest_event_id=None,
            latest_event_id=None,
            expired=True,
        )
