"""CodexRealtimeBatch 与 authority snapshot 契约测试。"""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.core.codex_contract.agent_protocol_v2_contract import AgentEventBatchV2Detail
from src.core.codex_contract.realtime_batch_contract import CodexRealtimeBatch
from src.core.codex_contract.realtime_event_contract import (
    CodexHostStatusChangedDetail,
    CodexItemDeltaDetail,
    CodexRealtimeEvent,
    CodexRealtimeEventHeader,
    CodexRealtimeEventType,
)

SHARED_BATCH_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "codex_realtime_batch_contract.json"
)
SHARED_STREAM_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "codex_stream_contract.json"
)


def _event(*, cursor: str, stream_epoch: str = "epoch-1") -> CodexRealtimeEvent:
    host_id = uuid4()
    return CodexRealtimeEvent(
        header=CodexRealtimeEventHeader(
            event_id=f"event-{cursor}",
            occurred_at=datetime.now(UTC),
            host_id=host_id,
            detail_kind=CodexRealtimeEventType.HOST_STATUS_CHANGED,
            stream_epoch=stream_epoch,
            cursor=cursor,
        ),
        detail=CodexHostStatusChangedDetail(host_id=host_id, status="online"),
    )


def test_batch_should_preserve_event_boundaries() -> None:
    batch = CodexRealtimeBatch(
        stream_epoch="epoch-1",
        first_cursor="1",
        last_cursor="2",
        events=(_event(cursor="1"), _event(cursor="2")),
    )

    assert batch.protocol_version == 2
    assert batch.model_dump(mode="json")["events"][0]["header"]["cursor"] == "1"


def test_batch_should_reject_cross_epoch_events() -> None:
    with pytest.raises(ValidationError):
        CodexRealtimeBatch(
            stream_epoch="epoch-1",
            first_cursor="1",
            last_cursor="2",
            events=(_event(cursor="1"), _event(cursor="2", stream_epoch="epoch-2")),
        )


def test_barrier_batch_should_reject_normal_delta() -> None:
    with pytest.raises(ValidationError):
        CodexRealtimeBatch(
            stream_epoch="epoch-1",
            first_cursor="1",
            last_cursor="1",
            barrier=True,
            events=(_event(cursor="1"),),
        )


def test_shared_agent_fastapi_browser_batch_fixture_should_validate() -> None:
    """同一 fixture 必须同时符合 Agent 输入和 FastAPI 输出的封闭批次契约。"""

    payload = json.loads(SHARED_BATCH_FIXTURE_PATH.read_text(encoding="utf-8"))
    agent_batch = AgentEventBatchV2Detail.model_validate(payload["agent_batch"])
    browser_batches = tuple(
        CodexRealtimeBatch.model_validate(batch) for batch in payload["browser_batches"]
    )

    assert (agent_batch.first_seq, agent_batch.last_seq) == (1, 2)
    assert [batch.barrier for batch in browser_batches] == [False, True]
    assert [batch.events[0].header.detail_kind for batch in browser_batches] == [
        CodexRealtimeEventType.ITEM_DELTA,
        CodexRealtimeEventType.PROTOCOL_WARNING,
    ]


def test_shared_stream_fixture_has_repeatable_event_order_and_projection() -> None:
    """后端必须按共享 fixture 的顺序折叠 delta，并得到固定最终投影。"""

    payload = json.loads(SHARED_STREAM_FIXTURE_PATH.read_text(encoding="utf-8"))
    events = tuple(CodexRealtimeEvent.model_validate(event) for event in payload["events"])
    expected = payload["expected_projection"]

    assert [event.header.event_id for event in events] == expected["event_ids"]
    assert [event.header.cursor for event in events] == expected["cursors"]
    assert all(event.header.stream_epoch == "fixture-epoch-1" for event in events)
    deltas = tuple(
        event.detail for event in events if isinstance(event.detail, CodexItemDeltaDetail)
    )
    assert "".join(detail.delta for detail in deltas) == expected["text"]
