"""Agent command v2 可选字段路径测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import JsonValue

from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.agent_protocol_v2_contract import AgentCommandV2Detail
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.infrastructure.codex.agent_protocol_codec import (
    AgentCommandV2Mapper,
    AgentProtocolCodecRegistry,
)

OPTIONAL_FIELD_CASES: tuple[tuple[str, dict[str, JsonValue]], ...] = (
    ("thread.list", {"workspace_key": "work"}),
    ("thread.list", {"workspace_key": "work", "limit": 50, "cursor": None}),
    ("thread.start", {"workspace_key": "work"}),
    (
        "turn.start",
        {
            "workspace_key": "work",
            "threadId": "thread-1",
            "input": [{"type": "text", "text": "消息", "text_elements": []}],
        },
    ),
)


class TestAgentCommandV2MapperPath:
    """覆盖可选字段缺省与显式提供两条路径。"""

    @pytest.mark.parametrize(("command_type", "params"), OPTIONAL_FIELD_CASES)
    def test_optional_fields_should_keep_original_presence_after_wire_round_trip(
        self,
        command_type: str,
        params: dict[str, JsonValue],
    ) -> None:
        command = self._build_command(command_type, params)
        mapper = AgentCommandV2Mapper()
        registry = AgentProtocolCodecRegistry()
        frame = registry.encode_v2(
            host_id=command.host_id,
            message_id=uuid4(),
            detail=mapper.from_v1_command(command),
        )
        decoded = registry.decode(frame)

        assert decoded.v2 is not None
        assert isinstance(decoded.v2.detail, AgentCommandV2Detail)
        restored = mapper.to_v1_command(
            host_id=command.host_id,
            command=decoded.v2.detail,
        )
        assert restored.params == params

    @staticmethod
    def _build_command(
        command_type: str,
        params: dict[str, JsonValue],
    ) -> CodexAgentCommand:
        """构建可选字段路径命令。"""

        return CodexAgentCommand(
            command_id=uuid4(),
            operation_id=uuid4(),
            host_id=uuid4(),
            request_digest=calculate_agent_request_digest(command_type, params),
            command_type=command_type,
            params=params,
            deadline=datetime.now(UTC) + timedelta(seconds=30),
        )
