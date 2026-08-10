"""Agent命令账本进程重启去重集成测试。"""

from __future__ import annotations

from pathlib import Path

from src.core.codex_contract.agent_command_contract import (
    AgentCommandClaimKind,
    AgentCommandIdentity,
    AgentCommandJournalState,
    AgentCommandResultSummary,
)
from src.infrastructure.codex_agent.agent_command_journal import (
    AGENT_COMMAND_RESTARTED_OUTCOME_CODE,
    AgentCommandJournal,
)


class TestAgentCommandJournalIntegration:
    """真实SQLite重开连接后的副作用去重测试。"""

    def test_restart_after_accepted_should_require_recovery_without_reexecution(
        self,
        tmp_path: Path,
    ) -> None:
        """验证已接受但未终态的命令在重启后进入待恢复状态。"""

        database_path = tmp_path / "state.sqlite"
        identity = self._build_identity()
        app_server_call_count = 0
        first_journal = AgentCommandJournal(database_path)
        try:
            claim = first_journal.claim(identity)
            if claim.kind is AgentCommandClaimKind.NEW:
                first_journal.mark_executing(identity.command_id)
                app_server_call_count += 1
                first_journal.mark_accepted(
                    identity.command_id,
                    result_summary=self._accepted_summary(),
                )
        finally:
            first_journal.close()

        restarted_journal = AgentCommandJournal(database_path)
        try:
            replay = restarted_journal.claim(identity)
            if replay.kind is AgentCommandClaimKind.NEW:
                app_server_call_count += 1

            assert replay.kind is AgentCommandClaimKind.REPLAY
            assert replay.record.state is AgentCommandJournalState.UNKNOWN
            assert replay.record.result_summary == AgentCommandResultSummary(
                outcome_code=AGENT_COMMAND_RESTARTED_OUTCOME_CODE,
            )
            assert app_server_call_count == 1
        finally:
            restarted_journal.close()

    def test_restart_while_executing_should_require_recovery_not_reexecute(
        self,
        tmp_path: Path,
    ) -> None:
        """验证崩溃时executing命令只能核对，不能自动再次调用App Server。"""

        database_path = tmp_path / "state.sqlite"
        identity = self._build_identity()
        first_journal = AgentCommandJournal(database_path)
        try:
            first_journal.claim(identity)
            first_journal.mark_executing(identity.command_id)
        finally:
            first_journal.close()

        restarted_journal = AgentCommandJournal(database_path)
        try:
            replay = restarted_journal.claim(identity)

            assert replay.kind is AgentCommandClaimKind.REPLAY
            assert replay.record.state is AgentCommandJournalState.UNKNOWN
            assert replay.record.result_summary == AgentCommandResultSummary(
                outcome_code=AGENT_COMMAND_RESTARTED_OUTCOME_CODE,
            )
        finally:
            restarted_journal.close()

    def _build_identity(self) -> AgentCommandIdentity:
        """构建集成测试命令身份。"""

        return AgentCommandIdentity(
            command_id="command-restart-1",
            operation_id="operation-restart-1",
            command_type="turn.start",
            request_digest="digest-restart-1",
        )

    def _accepted_summary(self) -> AgentCommandResultSummary:
        """构建已接受结果摘要。"""

        return AgentCommandResultSummary(
            outcome_code="accepted",
            upstream_thread_id="thread-restart-1",
            upstream_turn_id="turn-restart-1",
        )
