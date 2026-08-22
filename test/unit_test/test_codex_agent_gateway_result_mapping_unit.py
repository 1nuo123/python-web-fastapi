"""v2 command result 引用映射单元测试。"""

from __future__ import annotations

from uuid import uuid4

from src.application.codex.codex_protocol_mapper import CodexProtocolMapper
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentCommandResultReference,
    AgentThreadReadCommandResult,
)
from src.core.codex_contract.app_server_product_contract import (
    AppServerAgentMessageItem,
    AppServerThreadProductSnapshot,
    AppServerThreadReadProductResult,
    AppServerTurnProductSnapshot,
    AppServerUserMessageItem,
)
from src.infrastructure.codex.codex_agent_gateway import CodexAgentGatewayHandler


class TestCodexAgentGatewayResultMappingUnit:
    """验证 v2 引用可被已有应用层结果读取器消费。"""

    def test_result_reference_when_thread_and_turn_present_should_map_to_nested_ids(self) -> None:
        reference = AgentCommandResultReference(
            upstream_thread_id="thread-1",
            upstream_turn_id="turn-1",
            status="completed",
        )

        result = CodexAgentGatewayHandler._to_v1_command_result(  # noqa: SLF001
            object.__new__(CodexAgentGatewayHandler),
            None,
            reference,
        )

        assert result == {
            "thread": {"id": "thread-1"},
            "turn": {"id": "turn-1"},
            "status": "completed",
        }

    def test_thread_read_result_should_map_typed_content_to_application_fields(self) -> None:
        payload = AgentThreadReadCommandResult(
            snapshot=AppServerThreadReadProductResult(
                thread=AppServerThreadProductSnapshot(
                    thread_id="thread-1",
                    display_name="远程线程",
                    model_provider="openai",
                    status="idle",
                    created_at=1_700_000_000,
                    updated_at=1_700_000_001,
                ),
                turns=(
                    AppServerTurnProductSnapshot(
                        turn_id="turn-1",
                        status="completed",
                        started_at=1_700_000_000,
                        completed_at=1_700_000_001,
                        items=(
                            AppServerUserMessageItem(
                                item_id="item-user",
                                text="user message",
                                client_operation_id="11111111-1111-4111-8111-111111111111",
                            ),
                            AppServerAgentMessageItem(
                                item_id="item-1",
                                text="REMOTE_CODEX_OK",
                            ),
                        ),
                    ),
                ),
            )
        )

        result = CodexAgentGatewayHandler._to_v1_command_result(  # noqa: SLF001
            object.__new__(CodexAgentGatewayHandler),
            payload,
            None,
        )

        assert result["thread"]["id"] == "thread-1"
        assert (
            result["thread"]["turns"][0]["items"][0]["clientId"]
            == "11111111-1111-4111-8111-111111111111"
        )
        assert result["thread"]["turns"][0]["items"][1]["text"] == "REMOTE_CODEX_OK"
        snapshot = CodexProtocolMapper().to_thread_snapshot(
            result,
            host_id=uuid4(),
            workspace_id=None,
        )
        assert (
            str(snapshot.items[0].header.client_operation_id)
            == "11111111-1111-4111-8111-111111111111"
        )
