"""Agent command v2 wire 往返摘要契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue

from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.agent_protocol_v2_contract import AgentCommandV2Detail
from src.core.codex_contract.connection_session_contract import CodexConnectionProtocolVersion
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.infrastructure.codex.agent_protocol_codec import (
    AgentCommandV2Mapper,
    AgentProtocolCodecRegistry,
)

WORKSPACE_KEY = "fastapi-work"
THREAD_ID = "thread-contract"
TURN_ID = "turn-contract"
APPROVAL_ID = UUID("11111111-1111-1111-1111-111111111111")
COMMAND_ROUND_TRIP_CASES: tuple[tuple[str, dict[str, JsonValue]], ...] = (
    ("thread.list", {"workspace_key": WORKSPACE_KEY}),
    (
        "thread.read",
        {
            "workspace_key": WORKSPACE_KEY,
            "threadId": THREAD_ID,
            "includeTurns": False,
        },
    ),
    (
        "thread.start",
        {
            "workspace_key": WORKSPACE_KEY,
            "model": "gpt-5",
            "worktree_policy": {
                "enabled": True,
                "managed_root": None,
                "base_branch": "HEAD",
                "max_active": 4,
                "retention_seconds": 604800,
                "disk_watermark_percent": 85,
            },
        },
    ),
    ("thread.resume", {"workspace_key": WORKSPACE_KEY, "threadId": THREAD_ID}),
    ("thread.compact", {"workspace_key": WORKSPACE_KEY, "threadId": THREAD_ID}),
    (
        "turn.start",
        {
            "workspace_key": WORKSPACE_KEY,
            "threadId": THREAD_ID,
            "input": [{"type": "text", "text": "你好", "text_elements": []}],
            "model": "gpt-5",
            "effort": "medium",
        },
    ),
    (
        "turn.steer",
        {
            "workspace_key": WORKSPACE_KEY,
            "threadId": THREAD_ID,
            "expectedTurnId": TURN_ID,
            "input": [{"type": "text", "text": "继续", "text_elements": []}],
        },
    ),
    (
        "turn.interrupt",
        {
            "workspace_key": WORKSPACE_KEY,
            "threadId": THREAD_ID,
            "turnId": TURN_ID,
        },
    ),
    (
        "approval.decision",
        {
            "approvalId": str(APPROVAL_ID),
            "decision": "accept",
            "approvalVersion": 3,
        },
    ),
)


class TestAgentCommandV2DigestContract:
    """冻结所有受支持命令的参数形态与摘要语义。"""

    @pytest.mark.parametrize(("command_type", "params"), COMMAND_ROUND_TRIP_CASES)
    def test_command_when_round_trip_over_v2_wire_should_preserve_digest(
        self,
        command_type: str,
        params: dict[str, JsonValue],
    ) -> None:
        host_id = uuid4()
        command = self._build_command(host_id, command_type, params)
        mapper = AgentCommandV2Mapper()
        registry = AgentProtocolCodecRegistry()

        frame = registry.encode_v2(
            host_id=host_id,
            message_id=uuid4(),
            detail=mapper.from_v1_command(command),
        )
        decoded = registry.decode(frame)

        assert decoded.protocol_version is CodexConnectionProtocolVersion.V2
        assert decoded.v2 is not None
        assert isinstance(decoded.v2.detail, AgentCommandV2Detail)
        restored = mapper.to_v1_command(host_id=host_id, command=decoded.v2.detail)
        assert restored.params == params
        assert restored.request_digest == calculate_agent_request_digest(
            restored.command_type,
            restored.params,
        )

    @staticmethod
    def _build_command(
        host_id: UUID,
        command_type: str,
        params: dict[str, JsonValue],
    ) -> CodexAgentCommand:
        """构建具有真实摘要的命令。"""

        return CodexAgentCommand(
            command_id=uuid4(),
            operation_id=uuid4(),
            host_id=host_id,
            request_digest=calculate_agent_request_digest(command_type, params),
            command_type=command_type,
            params=params,
            deadline=datetime.now(UTC) + timedelta(seconds=30),
        )
