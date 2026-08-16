"""Codex 长期连接运行时的应用端口适配器。"""

from __future__ import annotations

from datetime import datetime

from src.application.ports.codex_agent_command_dispatch_port import (
    CodexAgentCommandDispatchPort,
)
from src.application.ports.codex_realtime_event_port import CodexRealtimeEventPort
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentCommand,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
)
from src.core.codex_contract.approval_contract import CodexApprovalAuditSnapshot
from src.core.codex_contract.realtime_event_contract import CodexRealtimeEventType
from src.core.codex_contract.thread_contract import CodexThreadIndexSnapshot
from src.infrastructure.codex.codex_control_runtime import CodexControlRuntime
from src.infrastructure.codex.codex_protocol_mapper import CodexProductEvent


class CodexRuntimeFacade(CodexAgentCommandDispatchPort, CodexRealtimeEventPort):
    """把应用命令路由到对应 host actor。"""

    def __init__(self, runtime: CodexControlRuntime) -> None:
        self._runtime = runtime

    async def dispatch(
        self,
        command: CodexAgentCommand,
        *,
        ack_timeout_seconds: float,
    ) -> CodexAgentCommandAck:
        """投递命令并返回接受确认。"""

        return await self._runtime.outbox_dispatcher.dispatch_command(command)

    async def dispatch_and_wait_result(
        self,
        command: CodexAgentCommand,
        *,
        ack_timeout_seconds: float,
        result_timeout_seconds: float,
    ) -> CodexAgentCommandResult:
        """向在线 Agent 投递读取命令并等待其最终结构化结果。"""

        return await self._runtime.actor_registry.get(command.host_id).dispatch_and_wait_result(
            command,
            ack_timeout_seconds=ack_timeout_seconds,
            result_timeout_seconds=result_timeout_seconds,
        )

    async def publish_approval_resolved(
        self,
        approval: CodexApprovalAuditSnapshot,
    ) -> None:
        """向同一 owner 的所有浏览器发布审批终态。"""

        await self._runtime.browser_event_hub.publish(
            approval.owner_subject_id,
            CodexProductEvent(
                host_id=approval.host_id,
                workspace_id=approval.workspace_id,
                thread_id=approval.thread_id,
                turn_id=approval.turn_id,
                item_id=approval.item_id,
                event_type=CodexRealtimeEventType.APPROVAL_RESOLVED,
                payload={"approval": approval.model_dump(mode="json")},
            ),
        )

    async def publish_thread_updated(
        self,
        thread: CodexThreadIndexSnapshot,
        *,
        occurred_at: datetime,
    ) -> None:
        """向同一 owner 的所有浏览器发布数据库确认后的会话投影。"""

        await self._runtime.publish_thread_updated(
            owner_subject_id=thread.owner_subject_id,
            thread=thread,
            occurred_at=occurred_at,
        )
