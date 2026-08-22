"""Agent 对 App Server 稳定审批 server request 的真实回复语义测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID, uuid4

from pydantic import JsonValue

from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentApprovalOpened,
    CodexAgentCommand,
)
from src.core.codex_contract.approval_contract import CodexApprovalDecision
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


def _build_approval_test_channel(
    *,
    host_id: UUID,
    sender: _RecordingSender,
    client: _RecordingClient,
) -> AgentControlChannel:
    """构造只覆盖审批收发边界的 Agent 通道，避免启动真实进程和网络。"""

    channel = AgentControlChannel.__new__(AgentControlChannel)
    setattr(channel, "_settings", SimpleNamespace(agent=SimpleNamespace(host_id=host_id)))
    setattr(
        channel,
        "_supervisor",
        SimpleNamespace(handle=SimpleNamespace(instance_id="app-server-1", client=client)),
    )
    setattr(channel, "_pending_approvals", {})
    setattr(channel, "_protocol_version", CodexConnectionProtocolVersion.V1)

    async def send_frame(
        frame: CodexConnectionFrame,
        *,
        seq: int | None = None,
        retain_until_ack: bool = False,
    ) -> None:
        """记录审批打开事件，忽略断线重放专用元数据。"""

        del seq, retain_until_ack
        await sender.send(frame)

    setattr(channel, "_send_or_buffer", send_frame)
    return channel


def test_approval_action_generation_hides_missing_amendment() -> None:
    """没有上游 amendment proposal 时不能向浏览器扩展命令动作。"""

    channel = AgentControlChannel.__new__(AgentControlChannel)

    assert channel._allowed_approval_actions(
        approval_kind="command",
        mapping={},
    ) == (
        CodexApprovalDecision.ACCEPT,
        CodexApprovalDecision.ACCEPT_FOR_SESSION,
        CodexApprovalDecision.DECLINE,
        CodexApprovalDecision.CANCEL,
    )
    assert channel._allowed_approval_actions(
        approval_kind="file_change",
        mapping={},
    ) == (
        CodexApprovalDecision.ACCEPT,
        CodexApprovalDecision.ACCEPT_FOR_SESSION,
        CodexApprovalDecision.DECLINE,
        CodexApprovalDecision.CANCEL,
    )


def test_command_and_file_change_base_decisions_reply_with_official_value() -> None:
    """不带 proposal 的 command/file change 决定逐一保持冻结字符串值。"""

    async def scenario() -> None:
        cases = (
            ("item/commandExecution/requestApproval", "accept"),
            ("item/commandExecution/requestApproval", "acceptForSession"),
            ("item/commandExecution/requestApproval", "decline"),
            ("item/commandExecution/requestApproval", "cancel"),
            ("item/fileChange/requestApproval", "accept"),
            ("item/fileChange/requestApproval", "acceptForSession"),
            ("item/fileChange/requestApproval", "decline"),
            ("item/fileChange/requestApproval", "cancel"),
        )
        for request_id, (method, decision) in enumerate(cases, start=20):
            host_id = uuid4()
            sender = _RecordingSender()
            client = _RecordingClient()
            channel = _build_approval_test_channel(
                host_id=host_id,
                sender=sender,
                client=client,
            )
            await channel._accept_app_server_request(
                request_id,
                method,
                {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "itemId": "item-1",
                },
            )
            opened = CodexAgentApprovalOpened.model_validate(sender.frames[0].payload)
            await channel._reply_approval(
                CodexAgentCommand(
                    command_id=uuid4(),
                    operation_id=uuid4(),
                    host_id=host_id,
                    request_digest="f" * 64,
                    command_type="approval.decision",
                    params={"approvalId": str(opened.approval_id), "decision": decision},
                    deadline=opened.expires_at,
                )
            )
            assert client.replies == [(request_id, {"decision": decision})]

    asyncio.run(scenario())


def test_permissions_accept_once_maps_to_turn_scope() -> None:
    async def scenario() -> None:
        host_id = uuid4()
        sender = _RecordingSender()
        client = _RecordingClient()
        channel = _build_approval_test_channel(
            host_id=host_id,
            sender=sender,
            client=client,
        )
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
        assert opened.display_summary.allowed_actions == (
            "accept",
            "acceptForSession",
            "decline",
        )

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
                },
            )
        ]

    asyncio.run(scenario())


def test_permissions_accept_session_maps_to_session_scope() -> None:
    async def scenario() -> None:
        host_id = uuid4()
        sender = _RecordingSender()
        client = _RecordingClient()
        channel = _build_approval_test_channel(
            host_id=host_id,
            sender=sender,
            client=client,
        )

        await channel._accept_app_server_request(
            8,
            "item/permissions/requestApproval",
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "cwd": "C:\\workspace",
                "permissions": {"network": {"enabled": True}},
            },
        )
        opened = CodexAgentApprovalOpened.model_validate(sender.frames[0].payload)
        await channel._reply_approval(
            CodexAgentCommand(
                command_id=uuid4(),
                operation_id=uuid4(),
                host_id=host_id,
                request_digest="b" * 64,
                command_type="approval.decision",
                params={
                    "approvalId": str(opened.approval_id),
                    "decision": "acceptForSession",
                },
                deadline=opened.expires_at,
            )
        )

        assert client.replies == [
            (8, {"permissions": {"network": {"enabled": True}}, "scope": "session"})
        ]

    asyncio.run(scenario())


def test_permissions_decline_maps_to_empty_profile() -> None:
    async def scenario() -> None:
        host_id = uuid4()
        sender = _RecordingSender()
        client = _RecordingClient()
        channel = _build_approval_test_channel(
            host_id=host_id,
            sender=sender,
            client=client,
        )

        await channel._accept_app_server_request(
            11,
            "item/permissions/requestApproval",
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "cwd": "C:\\workspace",
                "permissions": {"network": {"enabled": True}},
            },
        )
        opened = CodexAgentApprovalOpened.model_validate(sender.frames[0].payload)
        await channel._reply_approval(
            CodexAgentCommand(
                command_id=uuid4(),
                operation_id=uuid4(),
                host_id=host_id,
                request_digest="e" * 64,
                command_type="approval.decision",
                params={
                    "approvalId": str(opened.approval_id),
                    "decision": "decline",
                },
                deadline=opened.expires_at,
            )
        )

        assert client.replies == [(11, {"permissions": {}, "scope": "turn"})]

    asyncio.run(scenario())


def test_command_amendment_reply_uses_only_the_pending_official_proposal() -> None:
    async def scenario() -> None:
        host_id = uuid4()
        sender = _RecordingSender()
        client = _RecordingClient()
        channel = _build_approval_test_channel(
            host_id=host_id,
            sender=sender,
            client=client,
        )

        await channel._accept_app_server_request(
            9,
            "item/commandExecution/requestApproval",
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "command": "npm test",
                "proposedExecpolicyAmendment": ["npm test"],
            },
        )
        opened = CodexAgentApprovalOpened.model_validate(sender.frames[0].payload)
        assert "acceptWithExecpolicyAmendment" in opened.display_summary.allowed_actions
        await channel._reply_approval(
            CodexAgentCommand(
                command_id=uuid4(),
                operation_id=uuid4(),
                host_id=host_id,
                request_digest="c" * 64,
                command_type="approval.decision",
                params={
                    "approvalId": str(opened.approval_id),
                    "decision": "acceptWithExecpolicyAmendment",
                },
                deadline=opened.expires_at,
            )
        )

        assert client.replies == [
            (
                9,
                {
                    "decision": {
                        "acceptWithExecpolicyAmendment": {"execpolicy_amendment": ["npm test"]}
                    }
                },
            )
        ]

    asyncio.run(scenario())


def test_command_network_amendment_reply_uses_the_single_official_proposal() -> None:
    async def scenario() -> None:
        host_id = uuid4()
        sender = _RecordingSender()
        client = _RecordingClient()
        channel = _build_approval_test_channel(
            host_id=host_id,
            sender=sender,
            client=client,
        )

        await channel._accept_app_server_request(
            10,
            "item/commandExecution/requestApproval",
            {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "item-1",
                "command": "curl https://api.example.com",
                "proposedNetworkPolicyAmendments": [{"action": "allow", "host": "api.example.com"}],
            },
        )
        opened = CodexAgentApprovalOpened.model_validate(sender.frames[0].payload)
        assert "applyNetworkPolicyAmendment" in opened.display_summary.allowed_actions
        await channel._reply_approval(
            CodexAgentCommand(
                command_id=uuid4(),
                operation_id=uuid4(),
                host_id=host_id,
                request_digest="d" * 64,
                command_type="approval.decision",
                params={
                    "approvalId": str(opened.approval_id),
                    "decision": "applyNetworkPolicyAmendment",
                },
                deadline=opened.expires_at,
            )
        )

        assert client.replies == [
            (
                10,
                {
                    "decision": {
                        "applyNetworkPolicyAmendment": {
                            "network_policy_amendment": {
                                "action": "allow",
                                "host": "api.example.com",
                            }
                        }
                    }
                },
            )
        ]

    asyncio.run(scenario())
