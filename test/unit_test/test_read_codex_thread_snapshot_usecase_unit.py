"""Codex 已回收历史正文精确重载单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

from src.application.codex.read_thread_snapshot_usecase import (
    ReadCodexThreadSnapshotUsecase,
)
from src.application.ports.codex_agent_command_dispatch_port import (
    CodexAgentCommandDispatchPort,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.agent_protocol_contract import CodexAgentCommandResult
from src.core.codex_contract.thread_contract import (
    CodexThreadHistoryQuery,
    CodexThreadIndexSnapshot,
    CodexThreadStatus,
    CodexThreadTitleSource,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode

HOST_ID = UUID("11111111-1111-1111-1111-111111111111")
WORKSPACE_ID = UUID("22222222-2222-2222-2222-222222222222")
OWNER_SUBJECT_ID = "subject-1"
THREAD_ID = "thread-1"
BASE_TIME = datetime(2026, 8, 19, tzinfo=UTC)


def _thread() -> CodexThreadIndexSnapshot:
    """构造已由控制面授权的索引线程。"""

    return CodexThreadIndexSnapshot(
        thread_index_id=uuid4(),
        host_id=HOST_ID,
        workspace_id=WORKSPACE_ID,
        owner_subject_id=OWNER_SUBJECT_ID,
        upstream_thread_id=THREAD_ID,
        display_name="历史窗口",
        title_source=CodexThreadTitleSource.NEW_CONVERSATION,
        model=None,
        model_provider=None,
        reasoning_effort=None,
        status=CodexThreadStatus.IDLE,
        active_turn_id=None,
        turn_runtime=None,
        archived=False,
        is_pinned=False,
        source_kind="app_server",
        created_at=BASE_TIME,
        recency_at=BASE_TIME,
        updated_at=BASE_TIME,
        last_synced_at=BASE_TIME,
    )


def _thread_read_result(command_id: UUID, operation_id: UUID) -> CodexAgentCommandResult:
    """返回当前权威历史，额外条目用于证明重载路径不会泄露完整窗口。"""

    return CodexAgentCommandResult(
        command_id=command_id,
        operation_id=operation_id,
        outcome="completed",
        result={
            "thread": {
                "id": THREAD_ID,
                "name": "历史窗口",
                "status": {"type": "notLoaded"},
                "createdAt": 1_700_000_000,
                "updatedAt": 1_700_000_001,
                "turns": [
                    {
                        "id": "turn-1",
                        "status": "completed",
                        "startedAt": 1_700_000_000,
                        "completedAt": 1_700_000_001,
                        "error": None,
                        "items": [
                            {
                                "type": "agentMessage",
                                "id": "item-unrequested",
                                "text": "未请求正文",
                            },
                            {
                                "type": "agentMessage",
                                "id": "item-2",
                                "text": "第二条正文",
                            },
                            {
                                "type": "agentMessage",
                                "id": "item-3",
                                "text": "第三条正文",
                            },
                        ],
                    }
                ],
            }
        },
    )


def _usecase(dispatch_port: AsyncMock) -> ReadCodexThreadSnapshotUsecase:
    """构造仅替代授权读取与 Agent 命令边界的用例实例。"""

    control_port = Mock()
    unit_of_work = Mock()
    session = object()
    thread_repository = Mock()
    workspace_repository = Mock()
    control_port.create_unit_of_work.return_value = unit_of_work
    unit_of_work.get_session.return_value = session
    control_port.create_codex_thread_repository.return_value = thread_repository
    control_port.create_codex_workspace_repository.return_value = workspace_repository
    thread_repository.get_by_upstream_id_and_owner.return_value = _thread()
    workspace_repository.get_by_id_and_owner.return_value = SimpleNamespace(
        enabled=True,
        agent_workspace_key="workspace-key",
    )
    return ReadCodexThreadSnapshotUsecase(
        control_port=cast(CodexControlPort, control_port),
        dispatch_port=cast(CodexAgentCommandDispatchPort, dispatch_port),
        timeout_seconds=10,
        history_cursor_signing_key=b"history-item-reload-test-signing-key",
    )


@pytest.mark.parametrize(
    ("indexed_status", "active_turn_id"),
    [
        (CodexThreadStatus.IDLE, None),
        (CodexThreadStatus.ACTIVE, "active-turn"),
        (CodexThreadStatus.INTERRUPTED, None),
        (CodexThreadStatus.FAILED, None),
    ],
)
def test_not_loaded_authority_snapshot_should_preserve_indexed_thread_status(
    indexed_status: CodexThreadStatus,
    active_turn_id: str | None,
) -> None:
    """未加载的上游状态不能覆盖控制面已经确认的稳定线程状态。"""

    indexed = _thread().model_copy(
        update={"status": indexed_status, "active_turn_id": active_turn_id}
    )

    merged = ReadCodexThreadSnapshotUsecase._merge_authoritative_thread(
        indexed,
        {"status": "notLoaded"},
        [],
    )

    assert merged.status is indexed_status
    assert merged.active_turn_id == active_turn_id


@pytest.mark.asyncio
async def test_history_item_reload_should_return_only_requested_current_items_and_missing_ids() -> (
    None
):
    """正文回收恢复只能按稳定 ID 过滤当前权威历史，并显式报告不存在的 ID。"""

    dispatch_port = AsyncMock()

    async def dispatch_result(command: object, **_: object) -> CodexAgentCommandResult:
        command_id = getattr(command, "command_id")
        operation_id = getattr(command, "operation_id")
        return _thread_read_result(command_id, operation_id)

    dispatch_port.dispatch_and_wait_result.side_effect = dispatch_result
    usecase = _usecase(dispatch_port)

    reloaded = await usecase.read_history_items(
        host_id=HOST_ID,
        upstream_thread_id=THREAD_ID,
        owner_subject_id=OWNER_SUBJECT_ID,
        item_ids=["item-3", "item-missing", "item-2"],
    )

    assert [item.header.item_id for item in reloaded.items] == ["item-2", "item-3"]
    assert reloaded.missing_item_ids == ["item-missing"]
    dispatched_command = dispatch_port.dispatch_and_wait_result.await_args.args[0]
    assert dispatched_command.command_type == "thread.read"
    assert dispatched_command.params == {
        "threadId": THREAD_ID,
        "includeTurns": True,
        "workspace_key": "workspace-key",
    }


@pytest.mark.asyncio
async def test_history_stale_cursor_returns_rebase_signal() -> None:
    """篡改的签名游标必须转换为明确的 HTTP stale 信号，而不是 offset 回退。"""

    dispatch_port = AsyncMock()

    async def dispatch_result(command: object, **_: object) -> CodexAgentCommandResult:
        command_id = getattr(command, "command_id")
        operation_id = getattr(command, "operation_id")
        return _thread_read_result(command_id, operation_id)

    dispatch_port.dispatch_and_wait_result.side_effect = dispatch_result
    usecase = _usecase(dispatch_port)
    first_page = await usecase.read_history_page(
        host_id=HOST_ID,
        upstream_thread_id=THREAD_ID,
        owner_subject_id=OWNER_SUBJECT_ID,
        query=CodexThreadHistoryQuery(limit=1),
    )
    assert first_page.before_cursor is not None

    with pytest.raises(HttpFaultException) as exc_info:
        await usecase.read_history_page(
            host_id=HOST_ID,
            upstream_thread_id=THREAD_ID,
            owner_subject_id=OWNER_SUBJECT_ID,
            query=CodexThreadHistoryQuery(
                before_cursor=f"{first_page.before_cursor}x",
                limit=1,
            ),
        )

    assert exc_info.value.status_code == HTTPStatus.CONFLICT
    assert exc_info.value.error_code is CodexErrorCode.HISTORY_CURSOR_STALE
