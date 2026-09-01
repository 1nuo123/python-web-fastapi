"""App Server JSON-RPC 关联客户端单元测试。"""

from __future__ import annotations

import asyncio
import json
from typing import cast

import pytest
from pydantic import JsonValue

from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerMessageTooLargeError,
    AppServerProtocolError,
    JsonRpcId,
)
from src.infrastructure.codex_agent.app_server_jsonrpc_client import AppServerJsonRpcClient


class FakeLineReader:
    def __init__(self) -> None:
        self.lines: asyncio.Queue[bytes] = asyncio.Queue()

    async def readline(self) -> bytes:
        return await self.lines.get()


class FakeLineWriter:
    def __init__(self) -> None:
        self.messages: asyncio.Queue[dict[str, JsonValue]] = asyncio.Queue()

    def write(self, data: bytes) -> None:
        self.messages.put_nowait(cast(dict[str, JsonValue], json.loads(data)))

    async def drain(self) -> None:
        return


@pytest.mark.asyncio
async def test_request_when_responses_out_of_order_should_match_original_futures() -> None:
    reader = FakeLineReader()
    writer = FakeLineWriter()

    async def ignore_notification(_method: str, _params: JsonValue) -> None:
        return

    async def ignore_request(_id: JsonRpcId, _method: str, _params: JsonValue) -> None:
        return

    async def ignore_warning(_warning: str) -> None:
        return

    client = AppServerJsonRpcClient(
        reader=reader,
        writer=writer,
        max_line_bytes=1024,
        notification_handler=ignore_notification,
        request_handler=ignore_request,
        warning_handler=ignore_warning,
    )
    await client.start()
    first = asyncio.create_task(client.request("thread/list", {}, timeout_seconds=1))
    second = asyncio.create_task(client.request("model/list", {}, timeout_seconds=1))
    first_message = await writer.messages.get()
    second_message = await writer.messages.get()
    await reader.lines.put(
        json.dumps({"id": second_message["id"], "result": {"value": "second"}}).encode() + b"\n"
    )
    await reader.lines.put(
        json.dumps({"id": first_message["id"], "result": {"value": "first"}}).encode() + b"\n"
    )
    assert await first == {"value": "first"}
    assert await second == {"value": "second"}
    await client.close()


@pytest.mark.asyncio
async def test_read_loop_when_invalid_json_should_fail_pending_and_surface_protocol_error() -> None:
    reader = FakeLineReader()
    writer = FakeLineWriter()

    async def ignore_notification(_method: str, _params: JsonValue) -> None:
        return

    async def ignore_request(_id: JsonRpcId, _method: str, _params: JsonValue) -> None:
        return

    async def ignore_warning(_warning: str) -> None:
        return

    client = AppServerJsonRpcClient(
        reader=reader,
        writer=writer,
        max_line_bytes=32,
        notification_handler=ignore_notification,
        request_handler=ignore_request,
        warning_handler=ignore_warning,
    )
    await client.start()
    pending = asyncio.create_task(client.request("thread/list", {}, timeout_seconds=1))
    await writer.messages.get()
    await reader.lines.put(b"not-json\n")
    with pytest.raises(AppServerProtocolError):
        await pending
    with pytest.raises(AppServerProtocolError):
        await client.wait_stopped()
    await client.close()


@pytest.mark.asyncio
async def test_read_loop_when_message_exceeds_limit_should_reject_only_inflight_request() -> None:
    reader = FakeLineReader()
    writer = FakeLineWriter()
    warnings: list[str] = []

    async def ignore_notification(_method: str, _params: JsonValue) -> None:
        return

    async def ignore_request(_id: JsonRpcId, _method: str, _params: JsonValue) -> None:
        return

    async def record_warning(warning: str) -> None:
        warnings.append(warning)

    client = AppServerJsonRpcClient(
        reader=reader,
        writer=writer,
        max_line_bytes=64,
        notification_handler=ignore_notification,
        request_handler=ignore_request,
        warning_handler=record_warning,
    )
    await client.start()
    oversized = asyncio.create_task(client.request("thread/read", {}, timeout_seconds=1))
    await writer.messages.get()
    await reader.lines.put(b"x" * 65 + b"\n")
    with pytest.raises(AppServerMessageTooLargeError):
        await oversized

    following = asyncio.create_task(client.request("model/list", {}, timeout_seconds=1))
    following_message = await writer.messages.get()
    await reader.lines.put(
        json.dumps({"id": following_message["id"], "result": {"data": []}}).encode() + b"\n"
    )

    assert await following == {"data": []}
    assert client.running is True
    assert warnings == ["App Server单条输出超过4 MiB，已省略该消息，连接继续可用。"]
    await client.close()


@pytest.mark.asyncio
async def test_response_unknown_field_should_warn_and_preserve_known_result() -> None:
    reader = FakeLineReader()
    writer = FakeLineWriter()
    warnings: list[str] = []

    async def ignore_notification(_method: str, _params: JsonValue) -> None:
        return

    async def ignore_request(_id: JsonRpcId, _method: str, _params: JsonValue) -> None:
        return

    async def record_warning(warning: str) -> None:
        warnings.append(warning)

    client = AppServerJsonRpcClient(
        reader=reader,
        writer=writer,
        max_line_bytes=1024,
        notification_handler=ignore_notification,
        request_handler=ignore_request,
        warning_handler=record_warning,
    )
    await client.start()
    pending = asyncio.create_task(client.request("model/list", {}, timeout_seconds=1))
    request = await writer.messages.get()
    await reader.lines.put(
        json.dumps(
            {
                "id": request["id"],
                "result": {"data": []},
                "futureEnvelopeField": {"ignored": True},
            }
        ).encode()
        + b"\n"
    )

    assert await pending == {"data": []}
    assert warnings == ["App Server消息包含未知字段，已忽略。"]
    await client.close()
