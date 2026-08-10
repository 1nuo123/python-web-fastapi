"""控制面 Agent 实时事件有界缓冲单元测试。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_protocol_contract import CodexAgentRealtimeEvent
from src.infrastructure.codex.codex_agent_event_buffer import CodexAgentEventBuffer


@pytest.mark.asyncio
async def test_publish_when_capacity_overflows_should_keep_tail_and_mark_gap() -> None:
    host_id = uuid4()
    principal = AgentDevicePrincipal(
        credential_id="credential-1",
        host_id=str(host_id),
        owner_subject_id="owner-1",
    )
    buffer = CodexAgentEventBuffer(capacity=2)
    for index in range(3):
        await buffer.publish(
            CodexAgentRealtimeEvent(
                host_id=host_id,
                app_server_instance_id="instance-1",
                method="item/agentMessage/delta",
                params={"delta": str(index)},
            ),
            principal,
        )

    snapshot = await buffer.read(host_id)
    assert [item.sequence for item in snapshot.events] == [2, 3]
    assert snapshot.gap_detected is True


@pytest.mark.asyncio
async def test_publish_when_host_mismatches_principal_should_reject() -> None:
    buffer = CodexAgentEventBuffer(capacity=2)
    event = CodexAgentRealtimeEvent(
        host_id=uuid4(),
        app_server_instance_id="instance-1",
        method="turn/completed",
        params={},
    )
    principal = AgentDevicePrincipal(
        credential_id="credential-1",
        host_id=str(uuid4()),
        owner_subject_id="owner-1",
    )

    with pytest.raises(PermissionError):
        await buffer.publish(event, principal)
