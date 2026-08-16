"""Codex 产品事件正文容量边界测试。"""

from datetime import UTC, datetime
from uuid import uuid4

from src.application.codex.codex_protocol_mapper import (
    MAX_PRODUCT_DELTA_CHARS,
    MAX_PRODUCT_TEXT_CHARS,
    CodexProtocolMapper,
)
from src.core.codex_contract.agent_protocol_contract import CodexAgentRealtimeEvent
from src.core.codex_contract.thread_contract import CodexCommandTimelineDetail

TEN_MEBIBYTES = 10 * 1024 * 1024


def test_map_event_when_delta_is_ten_mebibytes_should_bound_browser_payload() -> None:
    mapped = CodexProtocolMapper().map_event(
        CodexAgentRealtimeEvent(
            host_id=uuid4(),
            app_server_instance_id="instance-1",
            occurred_at=datetime.now(UTC),
            method="item/commandExecution/outputDelta",
            params={
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "delta": "x" * TEN_MEBIBYTES,
            },
        ),
        workspace_id=uuid4(),
    )

    assert mapped is not None
    delta = mapped.payload["delta"]
    assert isinstance(delta, str)
    assert len(delta) == MAX_PRODUCT_DELTA_CHARS


def test_to_item_when_output_is_ten_mebibytes_should_bound_snapshot_payload() -> None:
    item = CodexProtocolMapper().to_item(
        {
            "id": "item-1",
            "type": "commandExecution",
            "command": "echo value",
            "aggregatedOutput": "x" * TEN_MEBIBYTES,
        },
        thread_id="thread-1",
        turn_id="turn-1",
        completed=True,
    )

    assert item is not None
    assert isinstance(item.detail, CodexCommandTimelineDetail)
    assert len(item.detail.output) == MAX_PRODUCT_TEXT_CHARS
