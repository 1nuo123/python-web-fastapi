"""Agent command v2 强类型字段边界测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import uuid4

import pytest
from pydantic import JsonValue, ValidationError

from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.host_contract import CodexApprovalPolicy, CodexSandboxMode
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.infrastructure.codex.agent_protocol_codec import (
    THREAD_START_COMMAND_TYPE,
    TURN_START_COMMAND_TYPE,
    AgentCommandV2Mapper,
)

MAXIMUM_MESSAGE_LENGTH = 200_000
EXECUTION_POLICY_COMMAND_TYPES: Final = frozenset(
    {THREAD_START_COMMAND_TYPE, TURN_START_COMMAND_TYPE}
)


class TestAgentCommandV2MapperBoundary:
    """覆盖消息长度和分页大小的上下界。"""

    @pytest.mark.parametrize("message_length", (1, MAXIMUM_MESSAGE_LENGTH))
    def test_turn_message_when_within_boundary_should_accept(self, message_length: int) -> None:
        params = self._turn_params("x" * message_length)

        detail = AgentCommandV2Mapper().from_v1_command(self._build_command("turn.start", params))

        assert detail.detail.message == "x" * message_length

    @pytest.mark.parametrize("message_length", (0, MAXIMUM_MESSAGE_LENGTH + 1))
    def test_turn_message_when_outside_boundary_should_reject(self, message_length: int) -> None:
        params = self._turn_params("x" * message_length)

        with pytest.raises((ValueError, ValidationError)):
            AgentCommandV2Mapper().from_v1_command(self._build_command("turn.start", params))

    @pytest.mark.parametrize("limit", (1, 200))
    def test_thread_list_limit_when_within_boundary_should_accept(self, limit: int) -> None:
        params: dict[str, JsonValue] = {"workspace_key": "work", "limit": limit}

        detail = AgentCommandV2Mapper().from_v1_command(self._build_command("thread.list", params))

        assert detail.detail.limit == limit

    @pytest.mark.parametrize("limit", (0, 201))
    def test_thread_list_limit_when_outside_boundary_should_reject(self, limit: int) -> None:
        params: dict[str, JsonValue] = {"workspace_key": "work", "limit": limit}

        with pytest.raises(ValidationError):
            AgentCommandV2Mapper().from_v1_command(self._build_command("thread.list", params))

    @staticmethod
    def _turn_params(message: str) -> dict[str, JsonValue]:
        """构建冻结文本输入。"""

        return {
            "workspace_key": "work",
            "threadId": "thread-1",
            "input": [{"type": "text", "text": message, "text_elements": []}],
        }

    @staticmethod
    def _build_command(
        command_type: str,
        params: dict[str, JsonValue],
    ) -> CodexAgentCommand:
        """构建边界命令。"""

        has_execution_policy = command_type in EXECUTION_POLICY_COMMAND_TYPES
        sandbox_mode = CodexSandboxMode.WORKSPACE_WRITE if has_execution_policy else None
        approval_policy = CodexApprovalPolicy.ON_REQUEST if has_execution_policy else None
        return CodexAgentCommand(
            command_id=uuid4(),
            operation_id=uuid4(),
            host_id=uuid4(),
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
