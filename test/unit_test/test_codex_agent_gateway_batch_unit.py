"""Codex Agent v2 批次观察器的边界测试。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest

from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_protocol_contract import CodexAgentRealtimeEvent
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentEventBatchV2Detail,
    AgentEventRecord,
    AgentItemChangedEventDetail,
    AgentItemDeltaEventDetail,
    AgentProtocolMessageType,
    AgentProtocolV2Envelope,
    AgentProtocolV2Header,
)
from src.core.codex_contract.app_server_product_contract import AppServerUserMessageItem
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerNotificationName,
)
from src.infrastructure.codex.agent_protocol_codec import AgentProtocolCodecRegistry
from src.infrastructure.codex.codex_agent_event_cursor_store import CodexAgentEventCursorStore
from src.infrastructure.codex.codex_agent_gateway import CodexAgentGatewayHandler

TEST_HOST_ID = UUID("00000000-0000-0000-0000-000000000001")
TEST_EVENT_EPOCH = UUID("00000000-0000-0000-0000-000000000002")


@dataclass(slots=True)
class _RecordingCursorStore:
    """记录网关在批次观察成功后推进的累计 ACK。"""

    advances: list[int] = field(default_factory=list)

    async def advance(
        self,
        *,
        host_id: UUID,
        event_epoch: UUID,
        after_seq: int,
    ) -> int:
        assert host_id == TEST_HOST_ID
        assert event_epoch == TEST_EVENT_EPOCH
        self.advances.append(after_seq)
        return after_seq


@dataclass(slots=True)
class _PassthroughCodec:
    """避免协议编码细节干扰批次观察器的顺序断言。"""

    def encode_v2(self, **kwargs: object) -> object:
        return kwargs["detail"]


@dataclass(slots=True)
class _RecordingSender:
    """捕获网关生成的累计 ACK。"""

    sent: list[object] = field(default_factory=list)

    async def send(self, frame: object) -> None:
        self.sent.append(frame)


def _record(sequence: int) -> AgentEventRecord:
    """构造同一 Agent epoch 中连续的文本 delta。"""

    return AgentEventRecord(
        agent_event_epoch=TEST_EVENT_EPOCH,
        seq=sequence,
        event_id=uuid4(),
        app_server_instance_id=UUID("00000000-0000-0000-0000-000000000003"),
        occurred_at=datetime(2026, 8, 19, tzinfo=UTC),
        detail=AgentItemDeltaEventDetail(
            method=AppServerNotificationName.AGENT_MESSAGE_DELTA,
            thread_id="thread-1",
            turn_id="turn-1",
            item_id="item-1",
            delta=str(sequence),
        ),
    )


@pytest.mark.asyncio
async def test_v2_batch_should_invoke_batch_observer_once_before_cumulative_ack() -> None:
    """网关不能将一个 Agent batch 重新拆成多次应用层 observer 调用。"""

    observed: list[tuple[str, ...]] = []

    async def observe_batch(
        events: tuple[CodexAgentRealtimeEvent, ...],
        _principal: AgentDevicePrincipal,
    ) -> None:
        observed.append(
            tuple(
                event.detail.delta
                for event in events
                if isinstance(event.detail, AgentItemDeltaEventDetail)
            )
        )

    handler = object.__new__(CodexAgentGatewayHandler)
    handler._agent_event_epoch = TEST_EVENT_EPOCH  # noqa: SLF001
    handler._last_event_seq = 0  # noqa: SLF001
    handler._event_batch_observer = observe_batch  # noqa: SLF001
    cursor_store = _RecordingCursorStore()
    handler._event_cursor_store = cast(CodexAgentEventCursorStore, cursor_store)  # noqa: SLF001
    handler._shutdown_event = None  # noqa: SLF001
    handler._codec = cast(AgentProtocolCodecRegistry, _PassthroughCodec())  # noqa: SLF001
    handler._principal = AgentDevicePrincipal(  # noqa: SLF001
        credential_id="credential-1",
        host_id=str(TEST_HOST_ID),
        owner_subject_id="owner-1",
    )
    sender = _RecordingSender()
    batch = AgentEventBatchV2Detail(
        agent_event_epoch=TEST_EVENT_EPOCH,
        first_seq=1,
        last_seq=2,
        events=(_record(1), _record(2)),
    )

    await handler._accept_event_batch(TEST_HOST_ID, batch, sender)  # noqa: SLF001

    assert observed == [("1", "2")]
    assert cursor_store.advances == [1, 2]
    assert len(sender.sent) == 1


def test_v2_event_batch_should_round_trip_user_message_client_operation_id() -> None:
    """新版 Agent 用户消息幂等键必须能被控制面完整解析，不能触发断连。"""

    client_operation_id = UUID("00000000-0000-4000-8000-000000000004")
    envelope = AgentProtocolV2Envelope(
        header=AgentProtocolV2Header(
            message_id=UUID("00000000-0000-4000-8000-000000000005"),
            message_type=AgentProtocolMessageType.EVENT_BATCH,
            detail_kind=AgentProtocolMessageType.EVENT_BATCH,
            host_id=TEST_HOST_ID,
            sent_at=datetime(2026, 8, 20, tzinfo=UTC),
        ),
        detail=AgentEventBatchV2Detail(
            agent_event_epoch=TEST_EVENT_EPOCH,
            first_seq=1,
            last_seq=1,
            events=(
                AgentEventRecord(
                    agent_event_epoch=TEST_EVENT_EPOCH,
                    seq=1,
                    event_id=UUID("00000000-0000-4000-8000-000000000006"),
                    app_server_instance_id=UUID("00000000-0000-4000-8000-000000000007"),
                    occurred_at=datetime(2026, 8, 20, tzinfo=UTC),
                    detail=AgentItemChangedEventDetail(
                        method=AppServerNotificationName.ITEM_STARTED,
                        thread_id="thread-1",
                        turn_id="turn-1",
                        status="started",
                        item=AppServerUserMessageItem(
                            item_id="item-1",
                            text="只回复 TEST_OK",
                            client_operation_id=client_operation_id,
                        ),
                    ),
                ),
            ),
        ),
    )

    decoded = AgentProtocolV2Envelope.model_validate(envelope.model_dump(mode="json"))

    assert isinstance(decoded.detail, AgentEventBatchV2Detail)
    item_event = decoded.detail.events[0].detail
    assert isinstance(item_event, AgentItemChangedEventDetail)
    assert isinstance(item_event.item, AppServerUserMessageItem)
    assert item_event.item.client_operation_id == client_operation_id
