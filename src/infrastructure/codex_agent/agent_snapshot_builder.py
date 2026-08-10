"""Agent 重连状态快照构建器。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final, Literal, cast
from uuid import UUID

from pydantic import JsonValue

from src.core.codex_contract.agent_command_contract import AgentCommandJournalState
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentStateSnapshot,
    CodexAgentWorkspaceSnapshot,
)
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentPendingApprovalSnapshot,
    AgentPendingCommandSnapshot,
    AgentSnapshotOmission,
    AgentStateSnapshotV2Detail,
    AgentThreadSnapshot,
    AgentWorkspaceSnapshot,
)
from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerMessageTooLargeError,
)
from src.infrastructure.codex_agent.agent_command_journal import AgentCommandJournal
from src.infrastructure.codex_agent.agent_thread_history_capacity_registry import (
    AgentThreadHistoryCapacityRegistry,
)
from src.infrastructure.codex_agent.agent_workspace_registry import AgentWorkspaceRegistry
from src.infrastructure.codex_agent.app_server_jsonrpc_client import AppServerJsonRpcClient

THREAD_LIST_PAGE_SIZE: Final = 20
THREAD_SNAPSHOT_LIMIT: Final = 100


class AgentSnapshotBuilder:
    """从本地白名单与 App Server 构建不含绝对路径的重连快照。"""

    def __init__(
        self,
        *,
        host_id: UUID,
        workspace_registry: AgentWorkspaceRegistry,
        client: AppServerJsonRpcClient,
        app_server_instance_id: str,
        journal: AgentCommandJournal | None = None,
        history_capacity_registry: AgentThreadHistoryCapacityRegistry | None = None,
    ) -> None:
        self._host_id = host_id
        self._workspace_registry = workspace_registry
        self._client = client
        self._app_server_instance_id = app_server_instance_id
        self._journal = journal
        self._history_capacity_registry = history_capacity_registry

    async def build(self) -> CodexAgentStateSnapshot:
        """逐工作区查询 thread/list，并标注本地 workspace_key。"""

        workspace_snapshots: list[CodexAgentWorkspaceSnapshot] = []
        thread_snapshots: list[dict[str, JsonValue]] = []
        omitted_thread_workspace_keys: list[str] = []
        for workspace in self._workspace_registry.list_workspaces():
            workspace_snapshots.append(
                CodexAgentWorkspaceSnapshot(
                    key=workspace.key,
                    display_name=workspace.display_name,
                    repo_fingerprint=self._workspace_registry.build_repo_fingerprint(workspace.key),
                    allow_write=workspace.allow_write,
                )
            )
            try:
                workspace_threads = await self._list_workspace_threads(workspace.key)
            except AppServerMessageTooLargeError:
                omitted_thread_workspace_keys.append(workspace.key)
                continue
            thread_snapshots.extend(workspace_threads)
        return CodexAgentStateSnapshot(
            host_id=self._host_id,
            app_server_instance_id=self._app_server_instance_id,
            workspaces=workspace_snapshots,
            threads=thread_snapshots,
            omitted_thread_workspace_keys=omitted_thread_workspace_keys,
            pending_commands=[
                {
                    "command_id": record.identity.command_id,
                    "operation_id": record.identity.operation_id,
                    "command_type": record.identity.command_type,
                    "state": record.state.value,
                    "result_summary": (
                        record.result_summary.model_dump(mode="json")
                        if record.result_summary is not None
                        else None
                    ),
                }
                for record in (
                    self._journal.list_recovery_records() if self._journal is not None else []
                )
            ],
            captured_at=datetime.now(UTC),
        )

    async def build_v2(
        self,
        *,
        page_index: int,
        page_size: int,
        pending_approvals: tuple[AgentPendingApprovalSnapshot, ...] = (),
    ) -> AgentStateSnapshotV2Detail:
        """把权威快照收敛为分页强类型 v2 detail。"""

        if page_index < 0:
            raise ValueError("Agent快照页码不得小于零。")
        if page_size <= 0:
            raise ValueError("Agent快照页容量必须大于零。")
        legacy = await self.build()
        all_threads = tuple(self._to_v2_thread(item) for item in legacy.threads)
        start = page_index * page_size
        page = all_threads[start : start + page_size]
        continuation = str(page_index + 1) if start + page_size < len(all_threads) else None
        omissions: tuple[AgentSnapshotOmission, ...] = ()
        if continuation is not None:
            omissions = (
                AgentSnapshotOmission(
                    section="threads",
                    omitted_count=len(all_threads) - start - len(page),
                    reason="page_capacity",
                ),
            )
        return AgentStateSnapshotV2Detail(
            app_server_instance_id=UUID(legacy.app_server_instance_id),
            page_index=page_index,
            continuation_token=continuation,
            workspaces=tuple(
                AgentWorkspaceSnapshot(
                    workspace_key=item.key,
                    display_name=item.display_name,
                    repo_fingerprint=item.repo_fingerprint,
                    default_branch=item.default_branch,
                    allow_write=item.allow_write,
                )
                for item in legacy.workspaces
            ),
            threads=page,
            pending_commands=tuple(
                AgentPendingCommandSnapshot(
                    command_id=UUID(str(item["command_id"])),
                    operation_id=UUID(str(item["operation_id"])),
                    command_kind=str(item["command_type"]),
                    state=self._read_v2_journal_state(str(item["state"])),
                    recovery_required=str(item["state"])
                    not in {
                        AgentCommandJournalState.COMPLETED.value,
                        AgentCommandJournalState.FAILED.value,
                    },
                )
                for item in legacy.pending_commands
            ),
            pending_approvals=pending_approvals,
            omissions=omissions,
            captured_at=legacy.captured_at,
        )

    def _to_v2_thread(self, item: dict[str, JsonValue]) -> AgentThreadSnapshot:
        status_value = item.get("status")
        if isinstance(status_value, Mapping):
            raw_type = cast(Mapping[str, object], status_value).get("type")
            status = raw_type if isinstance(raw_type, str) else "unknown"
        else:
            status = status_value if isinstance(status_value, str) else "unknown"
        updated_value = item.get("updatedAt")
        updated_at = (
            datetime.fromtimestamp(float(updated_value), tz=UTC)
            if isinstance(updated_value, (int, float)) and not isinstance(updated_value, bool)
            else None
        )
        return AgentThreadSnapshot(
            thread_id=str(item["id"]),
            workspace_key=str(item["workspaceKey"]),
            display_name=(str(item["name"]) if isinstance(item.get("name"), str) else None),
            status=status,
            active_turn_id=None,
            updated_at=updated_at,
        )

    def _read_v2_journal_state(
        self,
        value: str,
    ) -> Literal["received", "executing", "completed", "failed", "unknown"]:
        if value in {
            AgentCommandJournalState.RECEIVED.value,
            AgentCommandJournalState.EXECUTING.value,
            AgentCommandJournalState.COMPLETED.value,
            AgentCommandJournalState.FAILED.value,
            AgentCommandJournalState.UNKNOWN.value,
        }:
            return cast(
                Literal["received", "executing", "completed", "failed", "unknown"],
                value,
            )
        return "unknown"

    async def _list_workspace_threads(self, workspace_key: str) -> list[dict[str, JsonValue]]:
        """从状态库分页读取有界线程元数据，不扫描或转发历史正文。"""

        root = self._workspace_registry.resolve_root(workspace_key)
        snapshots: list[dict[str, JsonValue]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while len(snapshots) < THREAD_SNAPSHOT_LIMIT:
            params: dict[str, JsonValue] = {
                "cwd": str(root),
                "limit": min(THREAD_LIST_PAGE_SIZE, THREAD_SNAPSHOT_LIMIT - len(snapshots)),
                "useStateDbOnly": True,
            }
            if cursor is not None:
                params["cursor"] = cursor
            result = await self._client.request(
                "thread/list",
                params,
                timeout_seconds=15.0,
            )
            threads, next_cursor = self._read_thread_page(result)
            snapshots.extend(
                self._build_thread_metadata(thread, workspace_key) for thread in threads
            )
            if next_cursor is None:
                break
            if next_cursor in seen_cursors:
                raise ValueError("thread/list响应重复nextCursor。")
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        return snapshots

    def _build_thread_metadata(
        self,
        thread: Mapping[str, JsonValue],
        workspace_key: str,
    ) -> dict[str, JsonValue]:
        """只保留控制面索引所需字段，排除路径、preview 和 turns。"""

        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("thread/list响应线程缺少id。")
        if self._history_capacity_registry is not None:
            self._history_capacity_registry.register(thread_id, thread.get("path"))
        snapshot: dict[str, JsonValue] = {
            "id": thread_id,
            "workspaceKey": workspace_key,
        }
        name = thread.get("name")
        if isinstance(name, str) and name:
            snapshot["name"] = name[:256]
        model_provider = thread.get("modelProvider")
        if isinstance(model_provider, str):
            snapshot["modelProvider"] = model_provider[:128]
        status = thread.get("status")
        if isinstance(status, str):
            snapshot["status"] = status
        elif isinstance(status, Mapping):
            status_type = cast(Mapping[str, object], status).get("type")
            if isinstance(status_type, str):
                snapshot["status"] = {"type": status_type}
        for field_name in ("createdAt", "updatedAt"):
            value = thread.get(field_name)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                snapshot[field_name] = value
        return snapshot

    def _read_thread_page(
        self,
        result: JsonValue,
    ) -> tuple[list[Mapping[str, JsonValue]], str | None]:
        """收窄 thread/list 的 data 与 nextCursor。"""

        if not isinstance(result, Mapping):
            raise ValueError("thread/list响应不是对象。")
        data = cast(Mapping[str, object], result).get("data")
        if not isinstance(data, list):
            raise ValueError("thread/list响应缺少data数组。")
        threads: list[Mapping[str, JsonValue]] = []
        for item in data:
            if not isinstance(item, Mapping):
                raise ValueError("thread/list响应包含非对象线程。")
            threads.append(cast(Mapping[str, JsonValue], item))
        next_cursor = cast(Mapping[str, object], result).get("nextCursor")
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise ValueError("thread/list响应nextCursor不是字符串。")
        return threads, next_cursor
