"""Agent command v2 强类型 mapper 单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.core.codex_contract.agent_protocol_contract import CodexAgentCommand
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentApprovalReplyCommandDetail,
    AgentThreadStartCommandDetail,
    AgentTurnSteerCommandDetail,
)
from src.domain.codex.agent_command_policy import calculate_agent_request_digest
from src.infrastructure.codex.agent_protocol_codec import AgentCommandV2Mapper


class TestAgentCommandV2MapperUnit:
    """验证业务字段进入对应强类型扩展字段。"""

    def test_thread_start_when_worktree_enabled_should_preserve_strong_policy(self) -> None:
        params: dict[str, JsonValue] = {
            "workspace_key": "work",
            "worktree_policy": {
                "enabled": True,
                "managed_root": None,
                "base_branch": "main",
                "max_active": 8,
                "retention_seconds": 3600,
                "disk_watermark_percent": 90,
            },
        }

        detail = (
            AgentCommandV2Mapper()
            .from_v1_command(self._build_command("thread.start", params))
            .detail
        )

        assert isinstance(detail, AgentThreadStartCommandDetail)
        assert detail.worktree_policy is not None
        assert detail.worktree_policy.base_branch == "main"
        assert detail.worktree_policy.max_active == 8

    def test_turn_steer_should_preserve_expected_turn_identity(self) -> None:
        params: dict[str, JsonValue] = {
            "workspace_key": "work",
            "threadId": "thread-1",
            "expectedTurnId": "turn-1",
            "input": [{"type": "text", "text": "继续", "text_elements": []}],
        }

        detail = (
            AgentCommandV2Mapper().from_v1_command(self._build_command("turn.steer", params)).detail
        )

        assert isinstance(detail, AgentTurnSteerCommandDetail)
        assert detail.turn_id == "turn-1"

    def test_approval_decision_should_preserve_approval_version(self) -> None:
        approval_id = UUID("22222222-2222-2222-2222-222222222222")
        params: dict[str, JsonValue] = {
            "approvalId": str(approval_id),
            "decision": "decline",
            "approvalVersion": 7,
        }

        detail = (
            AgentCommandV2Mapper()
            .from_v1_command(self._build_command("approval.decision", params))
            .detail
        )

        assert isinstance(detail, AgentApprovalReplyCommandDetail)
        assert detail.approval_id == approval_id
        assert detail.approval_version == 7

    @staticmethod
    def _build_command(
        command_type: str,
        params: dict[str, JsonValue],
    ) -> CodexAgentCommand:
        """构建 mapper 输入命令。"""

        return CodexAgentCommand(
            command_id=uuid4(),
            operation_id=uuid4(),
            host_id=uuid4(),
            request_digest=calculate_agent_request_digest(command_type, params),
            command_type=command_type,
            params=params,
            deadline=datetime.now(UTC) + timedelta(seconds=30),
        )
