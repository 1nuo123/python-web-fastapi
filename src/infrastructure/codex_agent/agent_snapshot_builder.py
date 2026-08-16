"""Agent 重连状态快照构建器。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Final, Literal, cast
from uuid import UUID

from pydantic import JsonValue

from src.core.codex_contract.agent_command_contract import AgentCommandJournalState
from src.core.codex_contract.agent_protocol_contract import (
    AgentConversationSnapshotDetail,
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
from src.domain.codex.thread_title_policy import CodexThreadTitlePolicy
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
        thread_snapshots: list[AgentConversationSnapshotDetail] = []
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
                active_threads = await self._list_workspace_threads(
                    workspace.key,
                    archived=False,
                    limit=THREAD_SNAPSHOT_LIMIT,
                )
                remaining = THREAD_SNAPSHOT_LIMIT - len(active_threads)
                archived_threads = (
                    await self._list_workspace_threads(
                        workspace.key,
                        archived=True,
                        limit=remaining,
                    )
                    if remaining > 0
                    else []
                )
            except AppServerMessageTooLargeError:
                omitted_thread_workspace_keys.append(workspace.key)
                continue
            thread_snapshots.extend((*active_threads, *archived_threads))
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

    def _to_v2_thread(
        self,
        item: AgentConversationSnapshotDetail,
    ) -> AgentThreadSnapshot:
        """把 v1 会话索引扩展转换为同语义 v2 快照。"""

        return AgentThreadSnapshot(
            thread_id=item.thread_id,
            workspace_key=item.workspace_key,
            display_name=item.display_name,
            title_source=item.title_source,
            status=item.status,
            active_turn_id=item.active_turn_id,
            archived=item.archived,
            model_id=item.model_id,
            model_provider=item.model_provider,
            created_at=item.created_at,
            recency_at=item.recency_at,
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

    async def _list_workspace_threads(
        self,
        workspace_key: str,
        *,
        archived: bool,
        limit: int,
    ) -> list[AgentConversationSnapshotDetail]:
        """从状态库分页读取有界线程元数据，不扫描或转发历史正文。"""

        root = self._workspace_registry.resolve_root(workspace_key)
        snapshots: list[AgentConversationSnapshotDetail] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        while len(snapshots) < limit:
            params: dict[str, JsonValue] = {
                "cwd": str(root),
                "limit": min(THREAD_LIST_PAGE_SIZE, limit - len(snapshots)),
                "useStateDbOnly": True,
                "sortKey": "recency_at",
                "sortDirection": "desc",
                "archived": archived,
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
                self._build_thread_metadata(
                    thread,
                    workspace_key,
                    archived=archived,
                )
                for thread in threads
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
        *,
        archived: bool,
    ) -> AgentConversationSnapshotDetail:
        """本地消费 preview 后只输出有界标题与索引字段。"""

        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("thread/list响应线程缺少id。")
        if self._history_capacity_registry is not None:
            self._history_capacity_registry.register(thread_id, thread.get("path"))
        created_at = self._read_timestamp(thread.get("createdAt"))
        updated_at = self._read_timestamp(thread.get("updatedAt"))
        recency_at = self._read_timestamp(thread.get("recencyAt"))
        if created_at is None:
            created_at = updated_at
        if created_at is None:
            raise ValueError("thread/list响应线程缺少有效createdAt。")
        if recency_at is None:
            recency_at = updated_at or created_at
        name_value = thread.get("name")
        name = name_value if isinstance(name_value, str) else None
        preview_value = thread.get("preview")
        preview = preview_value if isinstance(preview_value, str) else None
        title = CodexThreadTitlePolicy().resolve(
            created_at=created_at,
            app_server_title=name,
            first_user_message=preview,
        )
        model_provider = thread.get("modelProvider")
        status = thread.get("status")
        if isinstance(status, str):
            normalized_status = status
        elif isinstance(status, Mapping):
            status_type = cast(Mapping[str, object], status).get("type")
            normalized_status = status_type if isinstance(status_type, str) else "unknown"
        else:
            normalized_status = "unknown"
        return AgentConversationSnapshotDetail(
            thread_id=thread_id,
            workspace_key=workspace_key,
            display_name=title.display_name,
            title_source=title.source,
            model_id=None,
            model_provider=(
                model_provider[:128] if isinstance(model_provider, str) else None
            ),
            status=normalized_status,
            active_turn_id=None,
            archived=archived,
            created_at=created_at,
            recency_at=recency_at,
        )

    def _read_timestamp(self, value: JsonValue | None) -> datetime | None:
        """把 App Server 秒级时间戳收敛为 UTC 时间。"""

        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        return datetime.fromtimestamp(float(value), tz=UTC)

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
