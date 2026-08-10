"""Agent 对 App Server 稳定审批 server request 的真实回复语义测试。"""

from __future__ import annotations

import asyncio
from collections import deque
from types import SimpleNamespace
from uuid import uuid4

from pydantic import JsonValue

from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentApprovalOpened,
    CodexAgentCommand,
)
from src.core.codex_contract.connection_session_contract import (
    CodexConnectionFrame,
    CodexConnectionProtocolVersion,
)
from src.infrastructure.codex_agent.agent_control_channel import AgentControlChannel


class _RecordingSender:
    def __init__(self) -> None:
        self.frames: list[CodexConnectionFrame] = []

    async def send(self, frame: CodexConnectionFrame) -> None:
        self.frames.append(frame)


class _RecordingClient:
    def __init__(self) -> None:
        self.replies: list[tuple[object, JsonValue]] = []

    async def reply(self, request_id: object, result: JsonValue) -> None:
        self.replies.append((request_id, result))

    async def reply_error(
        self,
        _request_id: object,
        *,
        code: int,
        message: str,
    ) -> None:
        raise AssertionError(f"unexpected error reply: {code} {message}")


def test_permissions_approval_should_keep_paths_local_and_grant_only_current_turn() -> None:
    async def scenario() -> None:
        host_id = uuid4()
        sender = _RecordingSender()
        client = _RecordingClient()
        channel = AgentControlChannel.__new__(AgentControlChannel)
        channel._settings = SimpleNamespace(agent=SimpleNamespace(host_id=host_id))
        channel._supervisor = SimpleNamespace(
            handle=SimpleNamespace(instance_id="app-server-1", client=client)
        )
        channel._pending_approvals = {}
        channel._active_sender = sender
        channel._event_buffer = deque(maxlen=4)
        channel._event_gap = False
        channel._protocol_version = CodexConnectionProtocolVersion.V1
        channel._send_or_buffer = sender.send
        requested_permissions: dict[str, JsonValue] = {
            "network": {"enabled": True},
            "fileSystem": {
                "write": ["C:\\private\\outside-workspace"],
            },
        }

        await channel._accept_app_server_request(
            7,
            "item/permissions/requestApproval",
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "cwd": "C:\\private\\workspace",
                "reason": "需要额外权限",
                "permissions": requested_permissions,
            },
        )
        opened = CodexAgentApprovalOpened.model_validate(sender.frames[0].payload)
        assert opened.approval_kind == "permissions"
        assert opened.risk_level == "high"
        assert "private" not in opened.model_dump_json()

        await channel._reply_approval(
            CodexAgentCommand(
                command_id=uuid4(),
                operation_id=uuid4(),
                host_id=host_id,
                request_digest="a" * 64,
                command_type="approval.decision",
                params={"approvalId": str(opened.approval_id), "decision": "accept"},
                deadline=opened.expires_at,
            )
        )

        assert client.replies == [
            (
                7,
                {
                    "permissions": requested_permissions,
                    "scope": "turn",
                    "strictAutoReview": True,
                },
            )
        ]

    asyncio.run(scenario())
