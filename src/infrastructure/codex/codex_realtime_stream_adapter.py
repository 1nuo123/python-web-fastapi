"""Codex 浏览器事件到通用 cursor stream 的薄适配器。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.application.ports.stream_state_store_port import StreamStateStorePort
from src.core.codex_contract.realtime_event_contract import CodexRealtimeEvent
from src.core.stream_contract.cursor_stream_contract import (
    CursorStreamAppendRequest,
    CursorStreamEvent,
    CursorStreamReadRequest,
    CursorStreamWindow,
)

CODEX_OWNER_EVENT_NAMESPACE = "codex:owner_events"


class CodexRealtimeStreamAdapter:
    """写入和读取两端都显式要求 owner。"""

    def __init__(
        self,
        *,
        store: StreamStateStorePort,
        ttl_seconds: int,
        max_events: int,
    ) -> None:
        self._store = store
        self._ttl_seconds = ttl_seconds
        self._max_events = max_events

    async def append(
        self,
        *,
        owner_subject_id: str,
        event: CodexRealtimeEvent,
    ) -> str:
        result = await self._store.append_cursor_event(
            CursorStreamAppendRequest(
                event=CursorStreamEvent(
                    stream_key=self._stream_key(owner_subject_id),
                    owner_subject_id=owner_subject_id,
                    event_id=UUID(event.header.event_id),
                    payload=event.model_dump_json().encode(),
                    expires_at=datetime.now(UTC) + timedelta(seconds=self._ttl_seconds),
                ),
                max_events=self._max_events,
            )
        )
        return result.cursor

    async def read(
        self,
        *,
        owner_subject_id: str,
        after_cursor: str | None,
        limit: int,
        through_cursor: str | None = None,
    ) -> CursorStreamWindow:
        return await self._store.read_cursor_window(
            CursorStreamReadRequest(
                stream_key=self._stream_key(owner_subject_id),
                owner_subject_id=owner_subject_id,
                after_cursor=after_cursor,
                limit=limit,
                through_cursor=through_cursor,
            )
        )

    def _stream_key(self, owner_subject_id: str) -> str:
        return f"{CODEX_OWNER_EVENT_NAMESPACE}:{owner_subject_id}"
