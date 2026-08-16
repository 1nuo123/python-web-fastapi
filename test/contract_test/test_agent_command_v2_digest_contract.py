"""Agent command v2 wire 往返摘要契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue

from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.agent_protocol_v2_contract import AgentCommandV2Detail
from src.core.codex_contract.connection_session_contract import CodexConnectionProtocolVersion
from src.core.codex_contract.host_contract import CodexApprovalPolicy, CodexSandboxMode
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.infrastructure.codex.agent_protocol_codec import (
    THREAD_START_COMMAND_TYPE,
    TURN_START_COMMAND_TYPE,
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
EXECUTION_POLICY_COMMAND_TYPES: Final = frozenset(
    {THREAD_START_COMMAND_TYPE, TURN_START_COMMAND_TYPE}
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
            sandbox_mode=(
                restored.sandbox_mode.value if restored.sandbox_mode is not None else None
            ),
            approval_policy=(
                restored.approval_policy.value if restored.approval_policy is not None else None
            ),
        )

    @staticmethod
    def _build_command(
        host_id: UUID,
        command_type: str,
        params: dict[str, JsonValue],
    ) -> CodexAgentCommand:
        """构建具有真实摘要的命令。"""

        has_execution_policy = command_type in EXECUTION_POLICY_COMMAND_TYPES
        sandbox_mode = CodexSandboxMode.WORKSPACE_WRITE if has_execution_policy else None
        approval_policy = CodexApprovalPolicy.ON_REQUEST if has_execution_policy else None
        return CodexAgentCommand(
            command_id=uuid4(),
            operation_id=uuid4(),
            host_id=host_id,
            request_digest=calculate_agent_request_digest(
                command_type,
                params,
                sandbox_mode=sandbox_mode.value if sandbox_mode is not None else None,
                approval_policy=approval_policy.value if approval_policy is not None else None,
            ),
            command_type=command_type,
            params=params,
            deadline=datetime.now(UTC) + timedelta(seconds=30),
            sandbox_mode=sandbox_mode,
            approval_policy=approval_policy,
        )
