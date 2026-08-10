"""假 App Server 子进程与 JSON-RPC 客户端集成测试。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, JsonValue

from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerMessageTooLargeError,
    JsonRpcId,
)
from src.infrastructure.codex_agent.app_server_jsonrpc_client import (
    AppServerJsonRpcClient,
    BoundedAppServerLineReader,
)


class InitializeResponse(BaseModel):
    """initialize 响应测试子集。"""

    model_config = ConfigDict(extra="allow")

    platformOs: str


class ThreadListResponse(BaseModel):
    """thread/list 响应测试子集。"""

    model_config = ConfigDict(extra="allow")

    data: list[JsonValue]


class TurnIdentityResponse(BaseModel):
    """turn 标识响应。"""

    id: str


class TurnStartResponse(BaseModel):
    """turn/start 响应测试子集。"""

    model_config = ConfigDict(extra="allow")

    turn: TurnIdentityResponse


@pytest.mark.asyncio
async def test_fake_app_server_when_notifications_interleave_should_complete_requests() -> None:
    fixture = Path("test/fixtures/fake_codex_app_server.py").resolve()
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(fixture),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    notifications: list[str] = []

    async def record_notification(method: str, _params: JsonValue) -> None:
        notifications.append(method)

    async def reject_request(_id: JsonRpcId, _method: str, _params: JsonValue) -> None:
        raise AssertionError("本场景不应收到server request。")

    async def ignore_warning(_warning: str) -> None:
        return

    client = AppServerJsonRpcClient(
        reader=process.stdout,
        writer=process.stdin,
        max_line_bytes=4096,
        notification_handler=record_notification,
        request_handler=reject_request,
        warning_handler=ignore_warning,
    )
    try:
        await client.start()
        initialized = InitializeResponse.model_validate(await client.initialize())
        threads = ThreadListResponse.model_validate(
            await client.request("thread/list", {}, timeout_seconds=1)
        )
        turn = TurnStartResponse.model_validate(
            await client.request(
                "turn/start",
                {"threadId": "thread-1", "input": []},
                timeout_seconds=1,
            )
        )
        await asyncio.sleep(0)

        assert initialized.platformOs == "windows"
        assert threads.data == []
        assert turn.turn.id == "turn-1"
        assert notifications == ["warning", "turn/started", "turn/completed"]
    finally:
        await client.close()
        process.terminate()
        await process.wait()


@pytest.mark.asyncio
async def test_fake_app_server_when_response_exceeds_limit_should_keep_transport_available() -> (
    None
):
    fixture = Path("test/fixtures/fake_codex_app_server.py").resolve()
    max_line_bytes = 4096
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(fixture),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=max_line_bytes + 1,
    )
    assert process.stdin is not None
    assert process.stdout is not None

    async def ignore_notification(_method: str, _params: JsonValue) -> None:
        return

    async def reject_request(_id: JsonRpcId, _method: str, _params: JsonValue) -> None:
        raise AssertionError("本场景不应收到server request。")

    warnings: list[str] = []

    async def record_warning(warning: str) -> None:
        warnings.append(warning)

    client = AppServerJsonRpcClient(
        reader=BoundedAppServerLineReader(
            process.stdout,
            max_line_bytes=max_line_bytes,
        ),
        writer=process.stdin,
        max_line_bytes=max_line_bytes,
        notification_handler=ignore_notification,
        request_handler=reject_request,
        warning_handler=record_warning,
    )
    try:
        await client.start()
        with pytest.raises(AppServerMessageTooLargeError):
            await client.request(
                "thread/read",
                {"testResponseSize": max_line_bytes * 4},
                timeout_seconds=2,
            )
        assert await client.request("model/list", {}, timeout_seconds=2) == {"data": []}
        assert client.running is True
        assert len(warnings) == 1
    finally:
        await client.close()
        process.terminate()
        await process.wait()
