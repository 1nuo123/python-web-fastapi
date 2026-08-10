"""Agent command v2 无损映射异常测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import JsonValue, ValidationError

from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.infrastructure.codex.agent_protocol_codec import AgentCommandV2Mapper


class TestAgentCommandV2MapperException:
    """拒绝无法由强类型 detail 无损表达的命令。"""

    def test_command_when_unknown_parameter_should_reject(self) -> None:
        params: dict[str, JsonValue] = {
            "workspace_key": "work",
            "unexpected": True,
        }

        with pytest.raises(ValueError, match="不支持的字段"):
            AgentCommandV2Mapper().from_v1_command(self._build_command("thread.start", params))

    @pytest.mark.parametrize(
        "input_item",
        (
            {"type": "text", "text": "消息", "text_elements": ["unexpected"]},
            {
                "type": "text",
                "text": "消息",
                "text_elements": [],
                "unexpected": True,
            },
        ),
    )
    def test_turn_input_when_shape_cannot_round_trip_should_reject(
        self,
        input_item: dict[str, JsonValue],
    ) -> None:
        params: dict[str, JsonValue] = {
            "workspace_key": "work",
            "threadId": "thread-1",
            "input": [input_item],
        }

        with pytest.raises(ValueError, match="input文本项"):
            AgentCommandV2Mapper().from_v1_command(self._build_command("turn.start", params))

    def test_thread_start_when_worktree_policy_invalid_should_reject(self) -> None:
        params: dict[str, JsonValue] = {
            "workspace_key": "work",
            "worktree_policy": {"enabled": True, "max_active": 0},
        }

        with pytest.raises(ValidationError):
            AgentCommandV2Mapper().from_v1_command(self._build_command("thread.start", params))

    @staticmethod
    def _build_command(
        command_type: str,
        params: dict[str, JsonValue],
    ) -> CodexAgentCommand:
        """构建异常路径命令。"""

        return CodexAgentCommand(
            command_id=uuid4(),
            operation_id=uuid4(),
            host_id=uuid4(),
            request_digest=calculate_agent_request_digest(command_type, params),
            command_type=command_type,
            params=params,
            deadline=datetime.now(UTC) + timedelta(seconds=30),
        )
