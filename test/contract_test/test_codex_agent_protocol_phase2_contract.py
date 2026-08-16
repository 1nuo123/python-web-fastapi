"""Phase 2 Agent 产品协议契约测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.connection_session_contract import CodexConnectionFrame
from src.core.codex_contract.host_contract import CodexApprovalPolicy, CodexSandboxMode
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.infrastructure.codex.agent_protocol_codec import AgentCommandV2Mapper


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


class TestCodexAgentExecutionPolicyContract:
    """验证执行策略参与摘要且可在 v1/v2 间无损映射。"""

    def test_request_digest_should_change_when_execution_restriction_changes(self) -> None:
        params = {"workspace_key": "work"}

        workspace_write_digest = calculate_agent_request_digest(
            "thread.start",
            params,
            sandbox_mode=CodexSandboxMode.WORKSPACE_WRITE.value,
            approval_policy=CodexApprovalPolicy.ON_REQUEST.value,
        )
        read_only_digest = calculate_agent_request_digest(
            "thread.start",
            params,
            sandbox_mode=CodexSandboxMode.READ_ONLY.value,
            approval_policy=CodexApprovalPolicy.ON_REQUEST.value,
        )

        assert workspace_write_digest != read_only_digest

    def test_thread_start_should_round_trip_execution_policy_between_v1_and_v2(self) -> None:
        host_id = uuid4()
        params = {"workspace_key": "work", "model": "gpt-5"}
        command = CodexAgentCommand(
            command_id=uuid4(),
            operation_id=uuid4(),
            host_id=host_id,
            request_digest=calculate_agent_request_digest(
                "thread.start",
                params,
                sandbox_mode=CodexSandboxMode.READ_ONLY.value,
                approval_policy=CodexApprovalPolicy.UNTRUSTED.value,
            ),
            command_type="thread.start",
            params=params,
            deadline=datetime.now(UTC) + timedelta(seconds=10),
            sandbox_mode=CodexSandboxMode.READ_ONLY,
            approval_policy=CodexApprovalPolicy.UNTRUSTED,
        )

        mapper = AgentCommandV2Mapper()
        v2_command = mapper.from_v1_command(command)
        restored = mapper.to_v1_command(host_id=host_id, command=v2_command)

        assert restored == command
        assert v2_command.detail.sandbox_mode is CodexSandboxMode.READ_ONLY
        assert v2_command.detail.approval_policy is CodexApprovalPolicy.UNTRUSTED

    def test_thread_start_when_execution_fields_missing_should_reject_v2_mapping(self) -> None:
        params = {"workspace_key": "work"}
        command = CodexAgentCommand(
            command_id=uuid4(),
            operation_id=uuid4(),
            host_id=uuid4(),
            request_digest=calculate_agent_request_digest("thread.start", params),
            command_type="thread.start",
            params=params,
            deadline=datetime.now(UTC) + timedelta(seconds=10),
        )

        with pytest.raises(ValueError, match="沙箱限制"):
            AgentCommandV2Mapper().from_v1_command(command)
