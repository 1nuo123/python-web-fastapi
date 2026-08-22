"""Codex 控制运行时到浏览器 hub 的批次边界测试。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from src.application.codex.sync_agent_state_usecase import SyncCodexAgentStateUsecase
from src.application.codex.turn_runtime_coordinator import (
    CodexTurnRuntimeCoordinator,
    TurnRuntimeEventOutcome,
)
from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_protocol_contract import CodexAgentRealtimeEvent
from src.core.codex_contract.agent_protocol_v2_contract import AgentProtocolWarningEventDetail
from src.infrastructure.codex.codex_agent_event_buffer import CodexAgentEventBuffer
from src.infrastructure.codex.codex_browser_event_hub import CodexBrowserEventHub
from src.infrastructure.codex.codex_control_runtime import CodexControlRuntime
from src.infrastructure.codex.codex_protocol_mapper import CodexProductEvent, CodexProtocolMapper

TEST_HOST_ID = UUID("00000000-0000-0000-0000-000000000001")


@dataclass(slots=True)
class _TurnRuntimeCoordinator:
    """将协议告警保留给普通控制面同步。"""

    async def observe_agent_event(
        self,
        _event: CodexAgentRealtimeEvent,
        _principal: AgentDevicePrincipal,
    ) -> TurnRuntimeEventOutcome:
        return TurnRuntimeEventOutcome(handled=False, accepted=True, thread=None)


@dataclass(slots=True)
class _EventBuffer:
    """测试中不会触发有界缓冲溢出。"""

    async def publish(
        self,
        _event: CodexAgentRealtimeEvent,
        _principal: AgentDevicePrincipal,
    ) -> bool:
        return False


@dataclass(slots=True)
class _StateSynchronizer:
    """记录应用层接收的完整 Agent 批次。"""

    accepted: list[tuple[CodexAgentRealtimeEvent, ...]] = field(default_factory=list)

    def accept_realtime_events(
        self,
        events: tuple[CodexAgentRealtimeEvent, ...],
        _principal: AgentDevicePrincipal,
    ) -> tuple[None, ...]:
        self.accepted.append(events)
        return tuple(None for _ in events)


@dataclass(slots=True)
class _BrowserHub:
    """记录运行时调用 hub 的次数和产品事件顺序。"""

    published: list[tuple[str, tuple[CodexProductEvent, ...]]] = field(default_factory=list)

    async def publish_batch(
        self,
        owner_subject_id: str,
        events: tuple[CodexProductEvent, ...],
    ) -> None:
        self.published.append((owner_subject_id, events))


def _event(reason_code: str) -> CodexAgentRealtimeEvent:
    """构造不触发数据库线程读取的强类型协议告警。"""

    return CodexAgentRealtimeEvent(
        host_id=TEST_HOST_ID,
        app_server_instance_id="instance-1",
        occurred_at=datetime(2026, 8, 19, tzinfo=UTC),
        method="protocol.warning",
        params={},
        detail=AgentProtocolWarningEventDetail(reason_code=reason_code),
    )


@pytest.mark.asyncio
async def test_runtime_should_sync_agent_batch_then_publish_to_hub_once() -> None:
    """应用同步完成前不 fan-out，且一个 Agent batch 只调用一次 hub 批接口。"""

    runtime = object.__new__(CodexControlRuntime)
    state_synchronizer = _StateSynchronizer()
    browser_hub = _BrowserHub()
    runtime.turn_runtime_coordinator = cast(CodexTurnRuntimeCoordinator, _TurnRuntimeCoordinator())
    runtime.event_buffer = cast(CodexAgentEventBuffer, _EventBuffer())
    runtime.state_synchronizer = cast(SyncCodexAgentStateUsecase, state_synchronizer)
    runtime.protocol_mapper = CodexProtocolMapper()
    runtime.browser_event_hub = cast(CodexBrowserEventHub, browser_hub)
    principal = AgentDevicePrincipal(
        credential_id="credential-1",
        host_id=str(TEST_HOST_ID),
        owner_subject_id="owner-1",
    )

    await runtime.publish_agent_events((_event("first"), _event("second")), principal)

    assert [
        [
            detail.reason_code
            for event in batch
            if isinstance((detail := event.detail), AgentProtocolWarningEventDetail)
        ]
        for batch in state_synchronizer.accepted
    ] == [["first", "second"]]
    assert len(browser_hub.published) == 1
    owner_subject_id, product_events = browser_hub.published[0]
    assert owner_subject_id == "owner-1"
    assert [event.payload["warning"] for event in product_events] == [
        "Agent协议告警：first",
        "Agent协议告警：second",
    ]
