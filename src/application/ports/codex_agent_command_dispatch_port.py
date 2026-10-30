"""控制面向在线 Agent 投递稳定命令的应用端口。"""

from __future__ import annotations

from typing import Protocol
from src.core.codex_contract.agent_content_contract import AgentContentBudgets
from uuid import UUID

from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentCommand,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
)


class CodexAgentCommandDispatchPort(Protocol):
    """只等待 Agent/App Server 接受确认，不等待 turn 完成。"""

    async def read_content_budgets(self, host_id: UUID) -> AgentContentBudgets | None: ...

    async def supports_history_windows(self, host_id: UUID) -> bool: ...

    async def dispatch(
        self,
        command: CodexAgentCommand,
        *,
        ack_timeout_seconds: float,
    ) -> CodexAgentCommandAck: ...

    async def dispatch_and_wait_result(
        self,
        command: CodexAgentCommand,
        *,
        ack_timeout_seconds: float,
        result_timeout_seconds: float,
    ) -> CodexAgentCommandResult: ...
