"""Agent command journal 与 App Server 调用编排。"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from src.application.ports.git_worktree_port import GitWorktreePort
from src.core.codex_contract.agent_command_contract import (
    AgentCommandClaimKind,
    AgentCommandIdentity,
    AgentCommandJournalState,
    AgentCommandResultSummary,
)
from src.core.codex_contract.agent_protocol_contract import (
    CODEX_AGENT_PROTOCOL_VERSION,
    CodexAgentCommand,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
)
from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerMessageTooLargeError,
    AppServerRpcClientPort,
    AppServerRpcError,
)
from src.core.worktree_contract.worktree_contract import (
    GitWorktreeBindRequest,
    GitWorktreeCreateRequest,
    GitWorktreePolicy,
    GitWorktreeRemoveRequest,
)
from src.domain.codex.agent_command_policy import (
    AgentCommandPolicy,
    calculate_agent_request_digest,
    read_upstream_identifiers,
)
from src.infrastructure.codex_agent.agent_command_journal import AgentCommandJournal
from src.infrastructure.codex_agent.agent_thread_history_capacity_registry import (
    AgentThreadHistoryCapacityRegistry,
)

AgentCommandAckSender = Callable[[CodexAgentCommandAck], Awaitable[None]]
AgentCommandResultSender = Callable[[CodexAgentCommandResult], Awaitable[None]]
AgentApprovalReplyHandler = Callable[[CodexAgentCommand], Awaitable[JsonValue]]


@dataclass(frozen=True, slots=True)
class AgentWorktreeExecutionContext:
    """单条 Agent 命令使用的受管 worktree 上下文。"""

    workspace_key: str
    worktree_id: str
    root: Path
    created: bool


class AgentCommandExecutor:
    """先持久化稳定 command id，再执行或回放 App Server 调用。"""

    def __init__(
        self,
        *,
        journal: AgentCommandJournal,
        client: AppServerRpcClientPort,
        command_policy: AgentCommandPolicy,
        ack_sender: AgentCommandAckSender,
        result_sender: AgentCommandResultSender,
        approval_reply_handler: AgentApprovalReplyHandler | None = None,
        history_capacity_registry: AgentThreadHistoryCapacityRegistry | None = None,
        worktree_port: GitWorktreePort | None = None,
    ) -> None:
        self._journal = journal
        self._client = client
        self._command_policy = command_policy
        self._ack_sender = ack_sender
        self._result_sender = result_sender
        self._approval_reply_handler = approval_reply_handler
        self._history_capacity_registry = history_capacity_registry
        self._worktree_port = worktree_port

    async def execute(self, command: CodexAgentCommand) -> None:
        """编排 digest 校验、账本登记、ack、RPC 与最终结果。"""

        self._validate_command(command)
        identity = AgentCommandIdentity(
            command_id=str(command.command_id),
            operation_id=str(command.operation_id),
            command_type=command.command_type,
            request_digest=command.request_digest,
        )
        claim = self._journal.claim(identity)
        if claim.kind == AgentCommandClaimKind.REPLAY:
            await self._replay(command, claim.record.state, claim.record.result_summary)
            return
        if command.deadline <= datetime.now(UTC):
            summary = AgentCommandResultSummary(outcome_code="deadline_expired")
            self._journal.mark_failed(str(command.command_id), result_summary=summary)
            await self._ack_sender(self._build_ack(command, "failed", replayed=False))
            await self._send_summary_result(command, summary, outcome="failed")
            return
        self._journal.mark_executing(str(command.command_id))
        timeout_seconds = max((command.deadline - datetime.now(UTC)).total_seconds(), 0.001)
        worktree_context: AgentWorktreeExecutionContext | None = None
        try:
            if command.command_type == "approval.decision":
                if self._approval_reply_handler is None:
                    raise RuntimeError("Agent审批回复处理器未装配。")
                result = await self._approval_reply_handler(command)
            else:
                worktree_context = await self._prepare_worktree(command)
                request = self._command_policy.build_request(
                    command_type=command.command_type,
                    params=command.params,
                    cwd_override=(worktree_context.root if worktree_context is not None else None),
                )
                history_omitted = False
                thread_id = command.params.get("threadId")
                if (
                    command.command_type == "thread.read"
                    and isinstance(thread_id, str)
                    and self._history_capacity_registry is not None
                    and self._history_capacity_registry.should_omit(thread_id)
                ):
                    request.params["includeTurns"] = False
                    history_omitted = True
                result = await self._client.request(
                    request.method,
                    request.params,
                    timeout_seconds=timeout_seconds,
                    operation_id=str(command.operation_id),
                )
                if history_omitted and isinstance(result, Mapping):
                    result = dict(result)
                    result["historyStatus"] = "omitted_too_large"
        except AppServerRpcError as exc:
            await self._cleanup_failed_worktree(worktree_context)
            summary = AgentCommandResultSummary(outcome_code=f"rpc_error_{exc.error.code}")
            self._journal.mark_failed(str(command.command_id), result_summary=summary)
            await self._ack_sender(self._build_ack(command, "failed", replayed=False))
            await self._result_sender(
                CodexAgentCommandResult(
                    command_id=command.command_id,
                    operation_id=command.operation_id,
                    outcome="failed",
                    error_code=str(exc.error.code),
                    error_message=exc.error.message,
                )
            )
            return
        except AppServerMessageTooLargeError:
            await self._cleanup_failed_worktree(worktree_context)
            if command.command_type not in {"thread.list", "thread.read"}:
                summary = AgentCommandResultSummary(outcome_code="response_too_large_unknown")
                self._journal.mark_unknown(
                    str(command.command_id),
                    result_summary=summary,
                )
                await self._ack_sender(
                    self._build_ack(
                        command,
                        AgentCommandJournalState.UNKNOWN.value,
                        replayed=False,
                        recovery_required=True,
                    )
                )
                await self._result_sender(
                    CodexAgentCommandResult(
                        command_id=command.command_id,
                        operation_id=command.operation_id,
                        outcome="unknown",
                        error_code="response_too_large",
                        error_message=(
                            "App Server响应超过4 MiB，写操作结果必须按原command_id核对。"
                        ),
                    )
                )
                return
            summary = AgentCommandResultSummary(outcome_code="response_too_large")
            self._journal.mark_failed(str(command.command_id), result_summary=summary)
            await self._ack_sender(self._build_ack(command, "failed", replayed=False))
            await self._result_sender(
                CodexAgentCommandResult(
                    command_id=command.command_id,
                    operation_id=command.operation_id,
                    outcome="failed",
                    error_code="response_too_large",
                    error_message="App Server响应超过4 MiB，历史正文已省略。",
                )
            )
            return
        except (RuntimeError, ValueError) as exc:
            await self._cleanup_failed_worktree(worktree_context)
            summary = AgentCommandResultSummary(outcome_code="command_rejected")
            self._journal.mark_failed(str(command.command_id), result_summary=summary)
            await self._ack_sender(self._build_ack(command, "failed", replayed=False))
            await self._result_sender(
                CodexAgentCommandResult(
                    command_id=command.command_id,
                    operation_id=command.operation_id,
                    outcome="failed",
                    error_code="command_rejected",
                    error_message=str(exc)[:512],
                )
            )
            return
        except (ConnectionError, TimeoutError):
            await self._cleanup_failed_worktree(worktree_context)
            summary = AgentCommandResultSummary(outcome_code="result_unknown")
            self._journal.mark_unknown(
                str(command.command_id),
                result_summary=summary,
            )
            await self._ack_sender(
                self._build_ack(
                    command,
                    AgentCommandJournalState.UNKNOWN.value,
                    replayed=False,
                    recovery_required=True,
                )
            )
            await self._result_sender(
                CodexAgentCommandResult(
                    command_id=command.command_id,
                    operation_id=command.operation_id,
                    outcome="unknown",
                    error_code="result_unknown",
                    error_message="App Server调用结果未知，必须按原command_id核对。",
                )
            )
            return
        thread_id, turn_id = read_upstream_identifiers(result)
        await self._bind_created_worktree(worktree_context, thread_id)
        summary = AgentCommandResultSummary(
            outcome_code="completed",
            upstream_thread_id=thread_id,
            upstream_turn_id=turn_id,
        )
        self._journal.mark_accepted(str(command.command_id), result_summary=summary)
        await self._ack_sender(self._build_ack(command, "accepted", replayed=False))
        self._journal.mark_completed(str(command.command_id), result_summary=summary)
        await self._result_sender(
            CodexAgentCommandResult(
                command_id=command.command_id,
                operation_id=command.operation_id,
                outcome="completed",
                result=result,
            )
        )

    def _validate_command(self, command: CodexAgentCommand) -> None:
        """验证协议版本及控制面提供的请求摘要。"""

        if command.expected_protocol_version != CODEX_AGENT_PROTOCOL_VERSION:
            raise ValueError("Agent命令协议版本不兼容。")
        expected_digest = calculate_agent_request_digest(command.command_type, command.params)
        if command.request_digest != expected_digest:
            raise ValueError("Agent命令request_digest不匹配。")

    async def _prepare_worktree(
        self,
        command: CodexAgentCommand,
    ) -> AgentWorktreeExecutionContext | None:
        port = self._worktree_port
        if port is None:
            return None
        workspace_key = command.params.get("workspace_key")
        if not isinstance(workspace_key, str) or not workspace_key:
            return None
        if command.command_type == "thread.start":
            policy_payload = command.params.get("worktree_policy")
            if policy_payload is None:
                return None
            policy = GitWorktreePolicy.model_validate(policy_payload)
            result = await asyncio.to_thread(
                port.create,
                GitWorktreeCreateRequest(
                    workspace_key=workspace_key,
                    thread_id=str(command.command_id),
                    policy=policy,
                ),
            )
            if not result.success or result.snapshot is None:
                raise RuntimeError(result.message or "隔离工作树创建失败。")
            return AgentWorktreeExecutionContext(
                workspace_key=workspace_key,
                worktree_id=result.snapshot.worktree_id,
                root=result.snapshot.path,
                created=True,
            )
        thread_id = command.params.get("threadId")
        if not isinstance(thread_id, str) or not thread_id:
            return None
        snapshot = await asyncio.to_thread(
            port.find_by_thread,
            workspace_key,
            thread_id,
        )
        if snapshot is None:
            return None
        return AgentWorktreeExecutionContext(
            workspace_key=workspace_key,
            worktree_id=snapshot.worktree_id,
            root=snapshot.path,
            created=False,
        )

    async def _bind_created_worktree(
        self,
        context: AgentWorktreeExecutionContext | None,
        thread_id: str | None,
    ) -> None:
        port = self._worktree_port
        if port is None or context is None or not context.created:
            return
        if thread_id is None:
            await self._cleanup_failed_worktree(context)
            return
        result = await asyncio.to_thread(
            port.bind_thread,
            GitWorktreeBindRequest(
                workspace_key=context.workspace_key,
                worktree_id=context.worktree_id,
                thread_id=thread_id,
            ),
        )
        if not result.success:
            return

    async def _cleanup_failed_worktree(
        self,
        context: AgentWorktreeExecutionContext | None,
    ) -> None:
        port = self._worktree_port
        if port is None or context is None or not context.created:
            return
        await asyncio.to_thread(
            port.remove,
            GitWorktreeRemoveRequest(
                workspace_key=context.workspace_key,
                worktree_id=context.worktree_id,
                force=False,
            ),
        )

    async def _replay(
        self,
        command: CodexAgentCommand,
        state: AgentCommandJournalState,
        summary: AgentCommandResultSummary | None,
    ) -> None:
        """重复命令只回放账本状态，绝不再次调用 App Server。"""

        recovery_required = state in {
            AgentCommandJournalState.RECEIVED,
            AgentCommandJournalState.EXECUTING,
            AgentCommandJournalState.ACCEPTED,
            AgentCommandJournalState.UNKNOWN,
        }
        await self._ack_sender(
            self._build_ack(
                command,
                state.value,
                replayed=True,
                recovery_required=recovery_required,
            )
        )
        if recovery_required:
            await self._result_sender(
                CodexAgentCommandResult(
                    command_id=command.command_id,
                    operation_id=command.operation_id,
                    outcome="unknown",
                    error_code="reconciliation_required",
                    error_message="命令曾进入执行阶段，禁止自动重复副作用。",
                )
            )
            return
        if summary is None:
            raise RuntimeError("终态Agent命令缺少结果摘要。")
        outcome: Literal["completed", "failed"] = (
            "completed" if state == AgentCommandJournalState.COMPLETED else "failed"
        )
        await self._send_summary_result(command, summary, outcome=outcome)

    def _build_ack(
        self,
        command: CodexAgentCommand,
        state: str,
        *,
        replayed: bool,
        recovery_required: bool = False,
    ) -> CodexAgentCommandAck:
        return CodexAgentCommandAck(
            command_id=command.command_id,
            operation_id=command.operation_id,
            state=state,
            replayed=replayed,
            recovery_required=recovery_required,
        )

    async def _send_summary_result(
        self,
        command: CodexAgentCommand,
        summary: AgentCommandResultSummary,
        *,
        outcome: Literal["completed", "failed"],
    ) -> None:
        result: dict[str, JsonValue] = {
            "outcomeCode": summary.outcome_code,
            "upstreamThreadId": summary.upstream_thread_id,
            "upstreamTurnId": summary.upstream_turn_id,
        }
        await self._result_sender(
            CodexAgentCommandResult(
                command_id=command.command_id,
                operation_id=command.operation_id,
                outcome=outcome,
                result=result,
            )
        )
