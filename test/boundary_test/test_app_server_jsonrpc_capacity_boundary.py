"""App Server JSONL 固定容量边界测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerMessageTooLargeError,
)
from src.infrastructure.codex_agent.agent_configuration import MAX_APP_SERVER_LINE_BYTES
from src.infrastructure.codex_agent.agent_thread_history_capacity_registry import (
    AgentThreadHistoryCapacityRegistry,
)
from src.infrastructure.codex_agent.app_server_jsonrpc_client import (
    BoundedAppServerLineReader,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("line_bytes", [MAX_APP_SERVER_LINE_BYTES - 1, MAX_APP_SERVER_LINE_BYTES])
async def test_bounded_reader_when_line_at_or_below_limit_should_return_line(
    line_bytes: int,
) -> None:
    stream = asyncio.StreamReader(limit=MAX_APP_SERVER_LINE_BYTES + 1)
    expected = b"x" * (line_bytes - 1) + b"\n"
    stream.feed_data(expected)
    reader = BoundedAppServerLineReader(
        stream,
        max_line_bytes=MAX_APP_SERVER_LINE_BYTES,
    )

    assert await reader.readline() == expected


@pytest.mark.asyncio
async def test_bounded_reader_when_line_exceeds_four_mib_should_reject_and_continue() -> None:
    stream = asyncio.StreamReader(limit=MAX_APP_SERVER_LINE_BYTES + 1)
    stream.feed_data(b"x" * MAX_APP_SERVER_LINE_BYTES + b"\nnext\n")
    reader = BoundedAppServerLineReader(
        stream,
        max_line_bytes=MAX_APP_SERVER_LINE_BYTES,
    )

    with pytest.raises(AppServerMessageTooLargeError) as captured:
        await reader.readline()

    assert captured.value.max_line_bytes == MAX_APP_SERVER_LINE_BYTES
    assert await reader.readline() == b"next\n"


def test_history_registry_when_source_crosses_limit_should_omit_only_above_boundary(
    tmp_path: Path,
) -> None:
    registry = AgentThreadHistoryCapacityRegistry(max_source_bytes=64)
    rollout = tmp_path / "rollout.jsonl"
    rollout.write_bytes(b"x" * 64)
    registry.register("thread-1", str(rollout))
    assert registry.should_omit("thread-1") is False

    rollout.write_bytes(b"x" * 65)
    registry.register("thread-1", str(rollout))
    assert registry.should_omit("thread-1") is True


@pytest.mark.asyncio
async def test_bounded_reader_when_separator_is_far_beyond_buffer_should_discard_in_chunks() -> (
    None
):
    max_line_bytes = 64
    stream = asyncio.StreamReader(limit=max_line_bytes + 1)
    stream.feed_data(b"x" * (max_line_bytes * 8) + b"\nnext\n")
    reader = BoundedAppServerLineReader(stream, max_line_bytes=max_line_bytes)

    with pytest.raises(AppServerMessageTooLargeError):
        await reader.readline()

    assert await reader.readline() == b"next\n"
