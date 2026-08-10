"""Agent命令去重账本单元测试。"""

from __future__ import annotations

import pytest

from src.core.codex_contract.agent_command_contract import (
    AgentCommandClaimKind,
    AgentCommandIdentity,
    AgentCommandJournalState,
    AgentCommandResultSummary,
)
from src.infrastructure.codex_agent.agent_command_journal import (
    AgentCommandDigestConflictError,
    AgentCommandJournal,
    AgentCommandStateConflictError,
)


class TestAgentCommandJournalUnit:
    """首次登记、结果回放和冲突测试。"""

    def test_claim_after_accepted_should_replay_original_result(self) -> None:
        """验证ack丢失后的同id重投不会形成新命令。"""

        journal = AgentCommandJournal(":memory:")
        identity = self._build_identity()
        try:
            first = journal.claim(identity)
            journal.mark_executing(identity.command_id)
            accepted = journal.mark_accepted(
                identity.command_id,
                result_summary=self._accepted_summary(),
            )

            replay = journal.claim(identity)

            assert first.kind is AgentCommandClaimKind.NEW
            assert accepted.state is AgentCommandJournalState.ACCEPTED
            assert replay.kind is AgentCommandClaimKind.REPLAY
            assert replay.record.result_summary == self._accepted_summary()
        finally:
            journal.close()

    def test_claim_when_same_command_has_different_digest_should_reject(self) -> None:
        """验证command_id不能被替换成另一项副作用。"""

        journal = AgentCommandJournal(":memory:")
        try:
            journal.claim(self._build_identity())
            with pytest.raises(AgentCommandDigestConflictError):
                journal.claim(self._build_identity(request_digest="different"))
        finally:
            journal.close()

    def test_completed_command_should_reject_second_execution_transition(self) -> None:
        """验证终态命令不能再次进入executing。"""

        journal = AgentCommandJournal(":memory:")
        identity = self._build_identity()
        try:
            journal.claim(identity)
            journal.mark_executing(identity.command_id)
            journal.mark_completed(
                identity.command_id,
                result_summary=self._accepted_summary(),
            )

            with pytest.raises(AgentCommandStateConflictError):
                journal.mark_executing(identity.command_id)
        finally:
            journal.close()

    def _build_identity(self, *, request_digest: str = "digest-1") -> AgentCommandIdentity:
        """构建稳定测试命令身份。"""

        return AgentCommandIdentity(
            command_id="command-1",
            operation_id="operation-1",
            command_type="turn.start",
            request_digest=request_digest,
        )

    def _accepted_summary(self) -> AgentCommandResultSummary:
        """构建不含正文的上游接受摘要。"""

        return AgentCommandResultSummary(
            outcome_code="accepted",
            upstream_thread_id="thread-1",
            upstream_turn_id="turn-1",
        )
