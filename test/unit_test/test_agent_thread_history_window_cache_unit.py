"""Agent thread/read 完整历史窗口缓存单元测试。"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import JsonValue

from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentCommand,
    CodexAgentCommandAck,
    CodexAgentCommandResult,
)
from src.core.codex_contract.app_server_product_contract import AppServerTurnChangedDetail
from src.domain.codex.agent_command_policy import AgentCommandPolicy, calculate_agent_request_digest
from src.infrastructure.codex_agent.agent_command_executor import AgentCommandExecutor
from src.infrastructure.codex_agent.agent_command_journal import AgentCommandJournal
from src.infrastructure.codex_agent.agent_control_channel import AgentControlChannel
from src.infrastructure.codex_agent.agent_thread_history_window_cache import (
    AgentThreadHistoryWindowCache,
    AgentThreadHistoryWindowCacheKey,
)
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentWorkspaceDefinition,
    AgentWorkspaceRegistry,
)


class HistoryWindowRecordingClient:
    """按预设顺序返回受控结果，避免缓存测试访问真实 App Server。"""

    def __init__(
        self,
        responses: list[JsonValue | BaseException],
        *,
        before_first_response: Callable[[], None] | None = None,
    ) -> None:
        self._responses = responses
        self._before_first_response = before_first_response
        self.calls: list[tuple[str, JsonValue]] = []

    async def request(
        self,
        method: str,
        params: JsonValue,
        *,
        timeout_seconds: float,
        operation_id: str | None = None,
    ) -> JsonValue:
        """记录请求后返回下一条结果；超时用于验证未知结果不写入缓存。"""

        del timeout_seconds, operation_id
        self.calls.append((method, params))
        if self._before_first_response is not None:
            callback = self._before_first_response
            self._before_first_response = None
            callback()
        response = self._responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _history_key(workspace_key: str, thread_id: str) -> AgentThreadHistoryWindowCacheKey:
    """构造显式工作区边界的内存缓存键。"""

    return AgentThreadHistoryWindowCacheKey(
        workspace_key=workspace_key,
        thread_id=thread_id,
    )


def _history_response(marker: str, *, omitted: bool = False) -> dict[str, JsonValue]:
    """构造最小完整 thread/read 响应；marker 仅用于断言 LRU 结果。"""

    response: dict[str, JsonValue] = {
        "thread": {
            "id": "thread-1",
            "turns": [{"id": "turn-1", "marker": marker}],
        }
    }
    if omitted:
        response["historyStatus"] = "omitted_too_large"
    return response


def _thread_read_command() -> CodexAgentCommand:
    """构造一次明确请求完整历史的独立 command，避免账本重放影响缓存断言。"""

    params: dict[str, JsonValue] = {
        "workspace_key": "work",
        "threadId": "thread-1",
        "includeTurns": True,
    }
    return CodexAgentCommand(
        command_id=uuid4(),
        operation_id=uuid4(),
        host_id=uuid4(),
        request_digest=calculate_agent_request_digest("thread.read", params),
        command_type="thread.read",
        params=params,
        deadline=datetime.now(UTC) + timedelta(seconds=10),
    )


class TestAgentThreadHistoryWindowCacheUnit:
    """验证正文只在 Agent 内存中以 TTL 和 LRU 边界存在。"""

    def test_get_when_ttl_reaches_boundary_should_expire_window(self) -> None:
        now = [0.0]
        cache = AgentThreadHistoryWindowCache(
            ttl_seconds=300,
            max_total_bytes=1024 * 1024,
            clock=lambda: now[0],
        )
        key = _history_key("work", "thread-1")

        assert cache.store(key, _history_response("first")) is True
        now[0] = 299.999
        assert cache.get(key) == _history_response("first")

        now[0] = 300.0

        assert cache.get(key) is None
        assert cache.entry_count == 0
        assert cache.total_bytes == 0

    def test_store_when_budget_reached_should_evict_least_recently_used_window(self) -> None:
        now = [0.0]
        first = _history_response("a" * 64)
        payload_size = len(
            json.dumps(first, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        cache = AgentThreadHistoryWindowCache(
            ttl_seconds=300,
            max_total_bytes=payload_size * 2,
            clock=lambda: now[0],
        )
        first_key = _history_key("work", "thread-1")
        second_key = _history_key("work", "thread-2")
        third_key = _history_key("work", "thread-3")

        assert cache.store(first_key, first) is True
        assert cache.store(second_key, _history_response("b" * 64)) is True
        assert cache.get(first_key) == first

        assert cache.store(third_key, _history_response("c" * 64)) is True

        assert cache.get(second_key) is None
        assert cache.get(first_key) == first
        assert cache.get(third_key) == _history_response("c" * 64)
        assert cache.total_bytes <= payload_size * 2

    @pytest.mark.asyncio
    async def test_executor_when_history_is_failed_or_omitted_should_not_cache_until_complete(
        self,
        tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        registry = AgentWorkspaceRegistry(
            [AgentWorkspaceDefinition("work", "Work", workspace, False)]
        )
        journal = AgentCommandJournal(tmp_path / "state.sqlite")
        client = HistoryWindowRecordingClient(
            [
                TimeoutError(),
                _history_response("omitted", omitted=True),
                _history_response("complete"),
            ]
        )
        results: list[CodexAgentCommandResult] = []
        cache = AgentThreadHistoryWindowCache(clock=lambda: 0.0)

        async def ignore_ack(_ack: CodexAgentCommandAck) -> None:
            return

        async def record_result(result: CodexAgentCommandResult) -> None:
            results.append(result)

        executor = AgentCommandExecutor(
            journal=journal,
            client=client,
            command_policy=AgentCommandPolicy(registry),
            ack_sender=ignore_ack,
            result_sender=record_result,
            history_window_cache=cache,
        )
        try:
            await executor.execute(_thread_read_command())
            await executor.execute(_thread_read_command())
            await executor.execute(_thread_read_command())
            await executor.execute(_thread_read_command())
        finally:
            journal.close()

        assert [result.outcome for result in results] == [
            "unknown",
            "completed",
            "completed",
            "completed",
        ]
        assert len(client.calls) == 3
        assert cache.entry_count == 1

    @pytest.mark.asyncio
    async def test_executor_when_thread_changes_during_history_read_should_not_cache_stale_response(
        self,
        tmp_path: Path,
    ) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        registry = AgentWorkspaceRegistry(
            [AgentWorkspaceDefinition("work", "Work", workspace, False)]
        )
        journal = AgentCommandJournal(tmp_path / "state.sqlite")
        cache = AgentThreadHistoryWindowCache(clock=lambda: 0.0)
        client = HistoryWindowRecordingClient(
            [_history_response("stale")],
            before_first_response=lambda: cache.invalidate_thread("thread-1"),
        )

        async def ignore_ack(_ack: CodexAgentCommandAck) -> None:
            return

        async def ignore_result(_result: CodexAgentCommandResult) -> None:
            return

        executor = AgentCommandExecutor(
            journal=journal,
            client=client,
            command_policy=AgentCommandPolicy(registry),
            ack_sender=ignore_ack,
            result_sender=ignore_result,
            history_window_cache=cache,
        )
        try:
            await executor.execute(_thread_read_command())
        finally:
            journal.close()

        assert len(client.calls) == 1
        assert cache.entry_count == 0

    @pytest.mark.asyncio
    async def test_executor_when_history_window_is_invalidated_should_reload_upstream(
        self,
        tmp_path: Path,
    ) -> None:
        """上游事件失效窗口后，下一次读取必须绕过旧正文并重新请求权威历史。"""

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        registry = AgentWorkspaceRegistry(
            [AgentWorkspaceDefinition("work", "Work", workspace, False)]
        )
        journal = AgentCommandJournal(tmp_path / "state.sqlite")
        client = HistoryWindowRecordingClient(
            [_history_response("before-invalidation"), _history_response("refreshed")]
        )
        cache = AgentThreadHistoryWindowCache(clock=lambda: 0.0)

        async def ignore_ack(_ack: CodexAgentCommandAck) -> None:
            return

        async def ignore_result(_result: CodexAgentCommandResult) -> None:
            return

        executor = AgentCommandExecutor(
            journal=journal,
            client=client,
            command_policy=AgentCommandPolicy(registry),
            ack_sender=ignore_ack,
            result_sender=ignore_result,
            history_window_cache=cache,
        )
        try:
            await executor.execute(_thread_read_command())
            cache.invalidate_thread("thread-1")
            await executor.execute(_thread_read_command())
        finally:
            journal.close()

        assert len(client.calls) == 2
        assert cache.get(_history_key("work", "thread-1")) == _history_response("refreshed")

    def test_invalidate_thread_should_clear_all_workspaces_without_retaining_body(self) -> None:
        cache = AgentThreadHistoryWindowCache(clock=lambda: 0.0)
        first_key = _history_key("work-a", "thread-1")
        second_key = _history_key("work-b", "thread-1")

        assert cache.store(first_key, _history_response("first")) is True
        assert cache.store(second_key, _history_response("second")) is True
        cache.invalidate_thread("thread-1")

        assert cache.get(first_key) is None
        assert cache.get(second_key) is None
        assert cache.total_bytes == 0

    def test_control_channel_when_thread_event_arrives_should_invalidate_history_window(
        self,
    ) -> None:
        cache = AgentThreadHistoryWindowCache(clock=lambda: 0.0)
        key = _history_key("work", "thread-1")
        channel = object.__new__(AgentControlChannel)
        channel._history_window_cache = cache
        assert cache.store(key, _history_response("stale")) is True

        channel._invalidate_history_window_for_notification(
            AppServerTurnChangedDetail(
                thread_id="thread-1",
                turn_id="turn-1",
                status="inProgress",
            )
        )

        assert cache.get(key) is None
