"""Codex 实例控制信号到通用 cursor stream 的薄适配器。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.application.ports.stream_state_store_port import StreamStateStorePort
from src.core.codex_contract.instance_control_contract import CodexInstanceControlSignal
from src.core.stream_contract.cursor_stream_contract import (
    CursorStreamAppendRequest,
    CursorStreamEvent,
    CursorStreamReadRequest,
)

CODEX_INSTANCE_CONTROL_NAMESPACE = "codex:instance_control"


class CodexInstanceControlSignalAdapter:
    """信号只携带引用、fence 和代次，不携带 command payload。"""

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

    async def publish(self, signal: CodexInstanceControlSignal) -> str:
        result = await self._store.append_cursor_event(
            CursorStreamAppendRequest(
                event=CursorStreamEvent(
                    stream_key=self._stream_key(signal.target_instance_id),
                    owner_subject_id=str(signal.target_instance_id),
                    event_id=signal.signal_id,
                    payload=signal.model_dump_json().encode(),
                    expires_at=datetime.now(UTC) + timedelta(seconds=self._ttl_seconds),
                ),
                max_events=self._max_events,
            )
        )
        return result.cursor

    async def read(
        self,
        *,
        instance_id: UUID,
        after_cursor: str | None,
        limit: int,
    ) -> tuple[tuple[CodexInstanceControlSignal, ...], str | None, bool]:
        window = await self._store.read_cursor_window(
            CursorStreamReadRequest(
                stream_key=self._stream_key(instance_id),
                owner_subject_id=str(instance_id),
                after_cursor=after_cursor,
                limit=limit,
            )
        )
        return (
            tuple(
                CodexInstanceControlSignal.model_validate_json(event.payload)
                for event in window.events
            ),
            window.next_cursor,
            window.gap,
        )

    def _stream_key(self, instance_id: UUID) -> str:
        return f"{CODEX_INSTANCE_CONTROL_NAMESPACE}:{instance_id}"
