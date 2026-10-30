"""Agent command journal 与 App Server 调用编排。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import JsonValue

from src.application.ports.git_worktree_port import GitWorktreePort
from src.core.codex_contract.agent_command_contract import (
    AgentCommandClaimKind,
    AgentCommandIdentity,
    AgentCommandJournalState,
    AgentCommandResultSummary,
)
from src.core.codex_contract.agent_connection_contract import AgentCommandAdmissionClosed
from src.core.codex_contract.agent_history_window_contract import (
    AgentHistoryWindowRequest,
    AgentHistoryWindowStaleError,
)
from src.core.codex_contract.agent_protocol_contract import (
    CODEX_AGENT_PROTOCOL_VERSION,
    CodexAgentCommand,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
)
from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerMessageTooLargeError,
    AppServerOverloadBudgetExceededError,
    AppServerRpcClientPort,
    AppServerRpcError,
)
from src.core.codex_contract.app_server_schema_manifest_contract import AppServerMethodName
from src.core.codex_contract.execution_root_binding_contract import (
    ExecutionRootBinding,
    RootKind,
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
from src.infrastructure.codex_agent.agent_execution_root_store import (
    AgentExecutionRootStore,
)
from src.infrastructure.codex_agent.agent_thread_history_capacity_registry import (
    AgentThreadHistoryCapacityRegistry,
)
from src.infrastructure.codex_agent.agent_thread_history_reader import read_thread_history_window
from src.infrastructure.codex_agent.agent_thread_history_window_cache import (
    AgentThreadHistoryWindowCache,
    AgentThreadHistoryWindowCacheKey,
)
from src.infrastructure.codex_agent.agent_timeline_store import AgentTimelineStore
from src.infrastructure.codex_agent.agent_workspace_registry import AgentWorkspaceRegistry

AgentCommandAckSender = Callable[[CodexAgentCommandAck], Awaitable[None]]
AgentCommandResultSender = Callable[[CodexAgentCommandResult], Awaitable[None]]
AgentApprovalReplyHandler = Callable[[CodexAgentCommand], Awaitable[JsonValue]]
THREAD_TURNS_LIST_PAGE_SIZE: Final = 100
HISTORY_INVALIDATING_COMMAND_TYPES: Final = frozenset(
    {
        "thread.start",
        "thread.resume",
        "thread.name_set",
        "thread.archive",
        "thread.unarchive",
        "thread.compact",
        "turn.start",
        "turn.steer",
        "turn.interrupt",
    }
)


@dataclass(frozen=True, slots=True)
class AgentWorktreeExecutionContext:
    """单条 Agent 命令使用的受管 worktree 上下文。"""

    workspace_key: str
    worktree_id: str
    root: Path
    created: bool
    root_kind: RootKind = RootKind.WORKSPACE


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
        admission_check: Callable[[], None] | None = None,
        approval_reply_handler: AgentApprovalReplyHandler | None = None,
        history_capacity_registry: AgentThreadHistoryCapacityRegistry | None = None,
        history_window_cache: AgentThreadHistoryWindowCache | None = None,
        timeline_store: AgentTimelineStore | None = None,
        worktree_port: GitWorktreePort | None = None,
        execution_root_store: AgentExecutionRootStore | None = None,
        workspace_registry: AgentWorkspaceRegistry | None = None,
        allow_experimental_api: bool = False,
        workspace_settings_handler: AgentApprovalReplyHandler | None = None,
        execution_settings_resolver: Callable[[str, str, str], Awaitable[dict[str, JsonValue]]]
        | None = None,
    ) -> None:
        self._admission_check = admission_check
        self._timeline_store = timeline_store
        self._side_effect_started = False
        self._journal = journal
        self._client = client
        self._command_policy = command_policy
        self._ack_sender = ack_sender
        self._result_sender = result_sender
        self._approval_reply_handler = approval_reply_handler
        self._history_capacity_registry = history_capacity_registry
        self._history_window_cache = history_window_cache
        self._worktree_port = worktree_port
        self._execution_root_store = execution_root_store
        self._workspace_registry = workspace_registry
        self._allow_experimental_api = allow_experimental_api
        self._workspace_settings_handler = workspace_settings_handler
        self._execution_settings_resolver = execution_settings_resolver

    async def execute(self, command: CodexAgentCommand) -> None:
        """生命周期取消必须收束已登记命令；网络投递不改变本地终态。"""
        self._side_effect_started = False
        try:
            await self._execute(command)
        except asyncio.CancelledError:
            record = self._journal.read(str(command.command_id))
            if record is not None and record.state in {
                AgentCommandJournalState.RECEIVED,
                AgentCommandJournalState.EXECUTING,
                AgentCommandJournalState.ACCEPTED,
            }:
                summary = AgentCommandResultSummary(
                    outcome_code="execution_cancelled_unknown"
                    if self._side_effect_started
                    else "cancelled_before_start",
                    upstream_thread_id=record.result_summary.upstream_thread_id
                    if record.result_summary
                    else None,
                    upstream_turn_id=record.result_summary.upstream_turn_id
                    if record.result_summary
                    else None,
                )
                if self._side_effect_started:
                    self._journal.mark_unknown(str(command.command_id), result_summary=summary)
                else:
                    self._journal.mark_failed(str(command.command_id), result_summary=summary)
            raise

    def _require_admission(self) -> None:
        if self._admission_check is not None:
            self._admission_check()

    async def _execute(self, command: CodexAgentCommand) -> None:
        """登记后逐副作用核对原连接准入。"""

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
        await self._ack_sender(self._build_ack(command, "executing", replayed=False))
        timeout_seconds = max((command.deadline - datetime.now(UTC)).total_seconds(), 0.001)
        command_deadline = asyncio.get_running_loop().time() + timeout_seconds
        worktree_context: AgentWorktreeExecutionContext | None = None
        try:
            self._require_admission()
            if command.command_type == "workspace.settings":
                if self._workspace_settings_handler is None:
                    raise RuntimeError("项目设置通道未装配。")
                self._side_effect_started = True
                result = await self._workspace_settings_handler(command)
            elif command.command_type == "approval.decision":
                if self._approval_reply_handler is None:
                    raise RuntimeError("Agent审批回复处理器未装配。")
                self._side_effect_started = True
                result = await self._approval_reply_handler(command)
            else:
                worktree_context = await self._prepare_worktree(command)
                self._require_admission()
                request = self._command_policy.build_request(
                    command_type=command.command_type,
                    params=command.params,
                    cwd_override=(worktree_context.root if worktree_context is not None else None),
                )
                history_omitted = False
                if command.command_type in {"thread.start", "thread.resume", "turn.start"}:
                    if self._execution_settings_resolver is None:
                        raise RuntimeError("项目执行设置未装配，不能使用旧线程默认值。")
                    key = command.params.get("workspace_key")
                    cwd = request.params.get("cwd")
                    if not isinstance(key, str) or not isinstance(cwd, str):
                        raise ValueError("项目执行身份不完整。")
                    self._require_admission()
                    self._side_effect_started = True
                    resolved = await self._execution_settings_resolver(key, request.method, cwd)
                    if command.command_type in {"thread.start", "thread.resume", "turn.start"}:
                        sandbox = resolved.get("sandbox")
                        policy = resolved.get("sandboxPolicy")
                        if isinstance(policy, dict) and isinstance(policy.get("type"), str):
                            sandbox = {
                                "readOnly": "read-only",
                                "workspaceWrite": "workspace-write",
                                "dangerFullAccess": "danger-full-access",
                            }.get(str(policy["type"]))
                        if (
                            command.sandbox_mode is None
                            or sandbox != command.sandbox_mode.value
                            or command.approval_policy is None
                            or resolved.get("approvalPolicy") != command.approval_policy.value
                        ):
                            raise PermissionError("项目权限已变化，请刷新设置并重新确认后执行。")
                    request.params.update(resolved)
                thread_id = command.params.get("threadId")
                if (
                    command.command_type == "thread.read"
                    and isinstance(thread_id, str)
                    and self._history_capacity_registry is not None
                    and command.params.get("history_window") is None
                    and self._history_capacity_registry.should_omit(thread_id)
                ):
                    request.params["includeTurns"] = False
                    history_omitted = True
                history_cache_key = self._build_history_cache_key(command)
                history_cache_generation = (
                    self._history_window_cache.invalidation_generation
                    if (
                        history_cache_key is not None
                        and not history_omitted
                        and self._history_window_cache is not None
                    )
                    else None
                )
                cached_history = (
                    self._history_window_cache.get(history_cache_key)
                    if (
                        history_cache_key is not None
                        and not history_omitted
                        and self._history_window_cache is not None
                    )
                    else None
                )
                if cached_history is None:
                    if (
                        command.command_type == "thread.read"
                        and request.params.get("includeTurns") is True
                        and isinstance(thread_id, str)
                        and self._allow_experimental_api
                    ):
                        # Codex 0.145 rejects thread/read(includeTurns=true)
                        # for paginated threads. Read metadata first, then use
                        # the audited turns/list pagination method and return
                        # the existing thread/read result shape to consumers.
                        remaining = command_deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            raise TimeoutError("thread/read分页读取超时。")
                        metadata_request = dict(request.params)
                        metadata_request["includeTurns"] = False
                        self._require_admission()
                        self._side_effect_started = True
                        metadata = await self._client.request(
                            request.method,
                            metadata_request,
                            timeout_seconds=remaining,
                            operation_id=str(command.operation_id),
                        )
                        if command.params.get("history_window") is not None:
                            result = await read_thread_history_window(
                                self._client,
                                metadata,
                                thread_id=thread_id,
                                request=AgentHistoryWindowRequest.model_validate(
                                    command.params["history_window"]
                                ),
                                timeline_store=self._timeline_store,
                                deadline=command_deadline,
                                operation_id=str(command.operation_id),
                            )
                        else:
                            result = await self._read_thread_turn_pages(
                                metadata,
                                thread_id=thread_id,
                                deadline=command_deadline,
                                operation_id=str(command.operation_id),
                            )
                    else:
                        self._require_admission()
                        self._side_effect_started = True
                        remaining = command_deadline - asyncio.get_running_loop().time()
                        if remaining <= 0:
                            raise TimeoutError("命令准备已超过截止时间。")
                        result = await self._client.request(
                            request.method,
                            request.params,
                            timeout_seconds=remaining,
                            operation_id=str(command.operation_id),
                        )
                    if (
                        history_cache_key is not None
                        and not history_omitted
                        and self._history_window_cache is not None
                        and history_cache_generation is not None
                        and self._is_complete_history_response(result)
                    ):
                        self._history_window_cache.store_if_current_generation(
                            history_cache_key,
                            result,
                            expected_generation=history_cache_generation,
                        )
                else:
                    result = cached_history
                if history_omitted and isinstance(result, Mapping):
                    result = dict(result)
                    result["historyStatus"] = "omitted_too_large"
        except AgentCommandAdmissionClosed:
            summary = AgentCommandResultSummary(
                outcome_code="admission_lost_unknown"
                if self._side_effect_started
                else "connection_lost_before_start"
            )
            if self._side_effect_started:
                self._journal.mark_unknown(str(command.command_id), result_summary=summary)
            else:
                await self._cleanup_failed_worktree(worktree_context)
                self._journal.mark_failed(str(command.command_id), result_summary=summary)
            await self._send_summary_result(
                command, summary, outcome="unknown" if self._side_effect_started else "failed"
            )
            return
        except AgentHistoryWindowStaleError:
            summary = AgentCommandResultSummary(outcome_code="history_cursor_stale")
            self._journal.mark_failed(str(command.command_id), result_summary=summary)
            await self._ack_sender(self._build_ack(command, "failed", replayed=False))
            await self._result_sender(
                CodexAgentCommandResult(
                    command_id=command.command_id,
                    operation_id=command.operation_id,
                    outcome="failed",
                    error_code="history_cursor_stale",
                    error_message="历史版本已变化，请重新读取窗口。",
                )
            )
            return
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
        except (FileNotFoundError, PermissionError, RuntimeError, ValueError) as exc:
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
        except (ConnectionError, TimeoutError) as exc:
            if command.command_type in {"thread.list", "thread.read"}:
                code = (
                    "query_overloaded"
                    if isinstance(exc, AppServerOverloadBudgetExceededError)
                    else "query_timeout"
                )
                summary = AgentCommandResultSummary(outcome_code=code)
                self._journal.mark_failed(str(command.command_id), result_summary=summary)
                await self._ack_sender(self._build_ack(command, "failed", replayed=False))
                await self._result_sender(
                    CodexAgentCommandResult(
                        command_id=command.command_id,
                        operation_id=command.operation_id,
                        outcome="failed",
                        error_code=code,
                        error_message="读取未在预算内完成，可重新查询。",
                    )
                )
                return
            # 请求可能已生效，不删除仍被执行进程使用的工作树。
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
        self._journal.mark_accepted(
            str(command.command_id),
            result_summary=AgentCommandResultSummary(
                outcome_code="upstream_accepted",
                upstream_thread_id=thread_id,
                upstream_turn_id=turn_id,
            ),
        )
        try:
            if (
                command.command_type in {"thread.archive", "thread.unarchive", "thread.resume"}
                and self._worktree_port is not None
                and worktree_context is not None
                and worktree_context.root_kind is RootKind.ISOLATED_WORKTREE
            ):
                await asyncio.to_thread(
                    self._worktree_port.set_archived,
                    worktree_context.workspace_key,
                    str(command.params["threadId"]),
                    command.command_type == "thread.archive",
                )
            await self._bind_created_worktree(worktree_context, thread_id)
        except (OSError, RuntimeError, ValueError):
            # 上游已经成功，不得宣称写操作失败并邀请重放；保留真实身份供核对。
            self._journal.mark_unknown(
                str(command.command_id),
                result_summary=AgentCommandResultSummary(
                    outcome_code="local_lifecycle_unconfirmed",
                    upstream_thread_id=thread_id,
                    upstream_turn_id=turn_id,
                ),
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
                    result=result,
                    error_code="local_lifecycle_unconfirmed",
                    error_message="Codex 已接受操作，本机工作树收尾未确认，请核对原会话，不要重复创建。",
                )
            )
            return
        self._invalidate_history_after_success(command, thread_id)
        summary = AgentCommandResultSummary(
            outcome_code="completed",
            upstream_thread_id=thread_id,
            upstream_turn_id=turn_id,
        )
        self._journal.mark_completed(str(command.command_id), result_summary=summary)
        await self._ack_sender(self._build_ack(command, "completed", replayed=False))
        await self._result_sender(
            CodexAgentCommandResult(
                command_id=command.command_id,
                operation_id=command.operation_id,
                outcome="completed",
                result=result,
            )
        )

    async def _read_thread_turn_pages(
        self,
        metadata: JsonValue,
        *,
        thread_id: str,
        deadline: float,
        operation_id: str,
    ) -> JsonValue:
        """将 0.145 的 turns/list 分页合成为既有 thread/read 结果。"""

        if not isinstance(metadata, Mapping):
            raise ValueError("thread/read元数据响应必须是对象。")
        thread = metadata.get("thread")
        if not isinstance(thread, Mapping):
            raise ValueError("thread/read元数据响应缺少thread。")

        cursor: str | None = None
        seen_cursors: set[str] = set()
        turns: list[JsonValue] = []
        page_count = 0
        total_bytes = 0
        while True:
            page_count += 1
            if page_count > 8:
                raise AppServerMessageTooLargeError("旧协议历史超过有界页数，需支持窗口协议。")
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("thread/turns/list分页读取超时。")
            params: dict[str, JsonValue] = {
                "threadId": thread_id,
                "itemsView": "full",
                "sortDirection": "asc",
                "limit": THREAD_TURNS_LIST_PAGE_SIZE,
            }
            if cursor is not None:
                params["cursor"] = cursor
            page = await self._client.request(
                AppServerMethodName.THREAD_TURNS_LIST.value,
                params,
                timeout_seconds=remaining,
                operation_id=operation_id,
            )
            if not isinstance(page, Mapping):
                raise ValueError("thread/turns/list响应必须是对象。")
            page_turns = page.get("data")
            if not isinstance(page_turns, list):
                raise ValueError("thread/turns/list响应缺少data数组。")
            total_bytes += len(json.dumps(page_turns, ensure_ascii=False).encode("utf-8"))
            if total_bytes > 2 * 1024 * 1024:
                raise AppServerMessageTooLargeError("旧协议历史超过字节预算。")
            turns.extend(page_turns)
            next_cursor = page.get("nextCursor")
            if next_cursor is None:
                break
            if not isinstance(next_cursor, str) or not next_cursor:
                raise ValueError("thread/turns/list响应包含无效nextCursor。")
            if next_cursor in seen_cursors:
                raise ValueError("thread/turns/list响应cursor循环。")
            seen_cursors.add(next_cursor)
            cursor = next_cursor

        merged_thread = dict(thread)
        merged_thread["turns"] = turns
        merged = dict(metadata)
        merged["thread"] = merged_thread
        return merged

    @staticmethod
    def _build_history_cache_key(
        command: CodexAgentCommand,
    ) -> AgentThreadHistoryWindowCacheKey | None:
        """只为明确请求完整历史的 thread/read 构造受限进程内缓存键。"""

        if command.command_type != "thread.read":
            return None
        workspace_key = command.params.get("workspace_key")
        thread_id = command.params.get("threadId")
        include_turns = command.params.get("includeTurns")
        if (
            not isinstance(workspace_key, str)
            or not workspace_key
            or not isinstance(thread_id, str)
            or not thread_id
            or include_turns is not True
        ):
            return None
        window = (
            AgentHistoryWindowRequest.model_validate(command.params["history_window"])
            if command.params.get("history_window") is not None
            else None
        )
        return AgentThreadHistoryWindowCacheKey(
            workspace_key=workspace_key,
            thread_id=thread_id,
            cursor=window.cursor if window else None,
            revision=window.revision if window else None,
            limit=window.limit if window else None,
        )

    @staticmethod
    def _is_complete_history_response(result: JsonValue) -> bool:
        """确认上游返回完整 turns，省略或畸形响应绝不进入正文缓存。"""

        if not isinstance(result, Mapping) or result.get("historyStatus") == "omitted_too_large":
            return False
        thread = result.get("thread")
        return isinstance(thread, Mapping) and isinstance(thread.get("turns"), list)

    def _invalidate_history_after_success(
        self,
        command: CodexAgentCommand,
        upstream_thread_id: str | None,
    ) -> None:
        """本机成功改变会话后立即失效对应完整历史，避免 TTL 内回显旧窗口。"""

        cache = self._history_window_cache
        if cache is None or command.command_type not in HISTORY_INVALIDATING_COMMAND_TYPES:
            return
        workspace_key = command.params.get("workspace_key")
        requested_thread_id = command.params.get("threadId")
        thread_id = upstream_thread_id or requested_thread_id
        if (
            isinstance(workspace_key, str)
            and workspace_key
            and isinstance(thread_id, str)
            and thread_id
        ):
            cache.invalidate(
                AgentThreadHistoryWindowCacheKey(
                    workspace_key=workspace_key,
                    thread_id=thread_id,
                )
            )

    def _validate_command(self, command: CodexAgentCommand) -> None:
        """验证协议版本及控制面提供的请求摘要。"""

        if command.expected_protocol_version != CODEX_AGENT_PROTOCOL_VERSION:
            raise ValueError("Agent命令协议版本不兼容。")
        expected_digest = calculate_agent_request_digest(
            command.command_type,
            command.params,
            sandbox_mode=(command.sandbox_mode.value if command.sandbox_mode is not None else None),
            approval_policy=(
                command.approval_policy.value if command.approval_policy is not None else None
            ),
        )
        if command.request_digest != expected_digest:
            raise ValueError("Agent命令request_digest不匹配。")

    async def _prepare_worktree(
        self,
        command: CodexAgentCommand,
    ) -> AgentWorktreeExecutionContext | None:
        port = self._worktree_port
        workspace_key = command.params.get("workspace_key")
        if not isinstance(workspace_key, str) or not workspace_key:
            return None
        registry = self._workspace_registry
        if registry is None:
            return None
        workspace_root = registry.resolve_root(workspace_key)
        if command.command_type == "thread.start":
            policy_payload = command.params.get("worktree_policy")
            if policy_payload is not None:
                policy = GitWorktreePolicy.model_validate(policy_payload)
                if policy.enabled:
                    if port is None:
                        raise RuntimeError("隔离工作树适配器未装配。")
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
                        root_kind=RootKind.ISOLATED_WORKTREE,
                    )
            return AgentWorktreeExecutionContext(
                workspace_key=workspace_key,
                worktree_id=str(command.command_id),
                root=workspace_root,
                created=False,
                root_kind=registry.resolve_root_kind(workspace_key),
            )
        thread_id = command.params.get("threadId")
        if not isinstance(thread_id, str) or not thread_id:
            return None
        store = self._execution_root_store
        if store is None:
            return AgentWorktreeExecutionContext(
                workspace_key=workspace_key,
                worktree_id=thread_id,
                root=workspace_root,
                created=False,
                root_kind=registry.resolve_root_kind(workspace_key),
            )
        binding = store.load(thread_id)
        if binding is None:
            return AgentWorktreeExecutionContext(
                workspace_key=workspace_key,
                worktree_id=thread_id,
                root=workspace_root,
                created=False,
                root_kind=registry.resolve_root_kind(workspace_key),
            )
        if binding.workspace_key != workspace_key:
            raise RuntimeError("线程执行根与当前工作区不匹配。")
        workspace_root = registry.resolve_root(workspace_key)
        try:
            selected_root = binding.execution_root.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError(
                "线程执行根已失效；请在本机恢复原目录或创建新会话，不能回退到原仓库。"
            ) from exc
        if selected_root != workspace_root and not selected_root.is_relative_to(workspace_root):
            raise RuntimeError("线程执行根逃出工作区白名单。")
        extension_worktree_id = getattr(binding.extension, "worktree_id", None)
        worktree_id = extension_worktree_id if isinstance(extension_worktree_id, str) else thread_id
        return AgentWorktreeExecutionContext(
            workspace_key=workspace_key,
            worktree_id=worktree_id,
            root=selected_root,
            created=False,
            root_kind=binding.root_kind,
        )

    async def _bind_created_worktree(
        self,
        context: AgentWorktreeExecutionContext | None,
        thread_id: str | None,
    ) -> None:
        port = self._worktree_port
        if context is None:
            return
        if thread_id is None:
            await self._cleanup_failed_worktree(context)
            return
        if context.created:
            if port is None:
                raise RuntimeError("隔离工作树适配器未装配。")
            result = await asyncio.to_thread(
                port.bind_thread,
                GitWorktreeBindRequest(
                    workspace_key=context.workspace_key,
                    worktree_id=context.worktree_id,
                    thread_id=thread_id,
                ),
            )
            if not result.success or result.snapshot is None:
                raise RuntimeError(result.message or "隔离工作树线程绑定失败。")
            binding = ExecutionRootBinding.for_worktree(
                thread_id=thread_id,
                workspace_key=context.workspace_key,
                execution_root=result.snapshot.path,
                worktree_id=result.snapshot.worktree_id,
            )
        elif context.root_kind is RootKind.ISOLATED_WORKTREE:
            binding = ExecutionRootBinding.for_worktree(
                thread_id=thread_id,
                workspace_key=context.workspace_key,
                execution_root=context.root,
                worktree_id=context.worktree_id,
            )
        else:
            binding = ExecutionRootBinding.for_workspace(
                thread_id=thread_id,
                workspace_key=context.workspace_key,
                execution_root=context.root,
                root_kind=context.root_kind,
            )
        store = self._execution_root_store
        if store is not None:
            store.save(binding)

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
        outcome: Literal["completed", "failed", "unknown"],
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
