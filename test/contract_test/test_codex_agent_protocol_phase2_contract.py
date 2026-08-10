"""Phase 2 Agent 产品协议契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.connection_session_contract import CodexConnectionFrame
from src.domain.codex.agent_command_policy import calculate_agent_request_digest


def test_agent_command_when_complete_should_round_trip_without_raw_jsonrpc_fields() -> None:
    params = {"workspace_key": "work", "model": "gpt-5"}
    command = CodexAgentCommand(
        command_id=uuid4(),
        operation_id=uuid4(),
        host_id=uuid4(),
        request_digest=calculate_agent_request_digest("thread.start", params),
        command_type="thread.start",
        params=params,
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )
    frame = CodexConnectionFrame(
        message_id="message-1",
        message_type="command",
        payload=command.model_dump(mode="json"),
    )

    restored = CodexAgentCommand.model_validate(frame.payload)
    assert restored == command
    assert "jsonrpc" not in frame.model_dump_json().lower()


def test_agent_command_when_unknown_field_should_reject() -> None:
    with pytest.raises(ValidationError):
        CodexAgentCommand.model_validate(
            {
                "command_id": str(uuid4()),
                "operation_id": str(uuid4()),
                "host_id": str(uuid4()),
                "request_digest": "a" * 64,
                "command_type": "thread.list",
                "params": {},
                "deadline": datetime.now(UTC).isoformat(),
                "unexpected": True,
            }
        )
