"""App Server 产品 notification 适配器单元测试。"""

from __future__ import annotations

from pydantic import JsonValue

from src.core.codex_contract.app_server_product_contract import (
    AppServerAgentMessageItem,
    AppServerContextCompactionItem,
    AppServerDiffChangedDetail,
    AppServerItemChangedDetail,
    AppServerItemDeltaDetail,
    AppServerPlanChangedDetail,
    AppServerProtocolWarningReason,
    AppServerThreadChangedDetail,
    AppServerTurnChangedDetail,
    AppServerUserMessageItem,
    AppServerWarningDetail,
)
from src.infrastructure.codex_agent.app_server_protocol_adapter import (
    AppServerProtocolAdapter,
)

THREAD_ID = "thread-adapter"
TURN_ID = "turn-adapter"
ITEM_ID = "item-adapter"


class TestAppServerProtocolAdapterUnit:
    """覆盖受审通知目录与损坏载荷的失败关闭策略。"""

    def test_thread_turn_and_item_notifications_should_map_typed_details(self) -> None:
        adapter = AppServerProtocolAdapter()
        thread_started = adapter.adapt_notification(
            method="thread/started",
            params={"thread": {"id": THREAD_ID, "status": {"type": "active"}}},
            emitted_at_ms=123,
        )
        thread_status = adapter.adapt_notification(
            method="thread/status/changed",
            params={"threadId": THREAD_ID, "status": "idle"},
        )
        turn_started = adapter.adapt_notification(
            method="turn/started",
            params={
                "threadId": THREAD_ID,
                "turn": {"id": TURN_ID, "status": {"type": "inProgress"}},
            },
        )
        item_started = adapter.adapt_notification(
            method="item/started",
            params={
                "threadId": THREAD_ID,
                "item": {"id": ITEM_ID, "type": "agentMessage"},
            },
        )
        item_completed = adapter.adapt_notification(
            method="item/completed",
            params={
                "threadId": THREAD_ID,
                "turnId": TURN_ID,
                "item": {"id": ITEM_ID, "type": "agentMessage"},
            },
        )

        assert thread_started.notification is not None
        assert thread_started.notification.header.emitted_at_ms == 123
        assert isinstance(thread_started.notification.detail, AppServerThreadChangedDetail)
        assert thread_started.notification.detail.thread.status == "active"
        assert thread_status.notification is not None
        assert isinstance(thread_status.notification.detail, AppServerThreadChangedDetail)
        assert thread_status.notification.detail.thread.status == "idle"
        assert turn_started.notification is not None
        assert isinstance(turn_started.notification.detail, AppServerTurnChangedDetail)
        assert turn_started.notification.detail.turn_id == TURN_ID
        assert item_started.notification is not None
        assert isinstance(item_started.notification.detail, AppServerItemChangedDetail)
        assert item_started.notification.detail.turn_id is None
        assert item_started.notification.detail.status == "started"
        assert item_completed.notification is not None
        assert isinstance(item_completed.notification.detail, AppServerItemChangedDetail)
        assert item_completed.notification.detail.status == "completed"

    def test_delta_plan_diff_and_warning_notifications_should_map_capacity_summary(self) -> None:
        adapter = AppServerProtocolAdapter()
        for method in (
            "item/agentMessage/delta",
            "item/commandExecution/outputDelta",
            "item/fileChange/outputDelta",
        ):
            result = adapter.adapt_notification(
                method=method,
                params={
                    "threadId": THREAD_ID,
                    "turnId": TURN_ID,
                    "itemId": ITEM_ID,
                    "delta": "text",
                },
            )
            assert result.notification is not None
            assert isinstance(result.notification.detail, AppServerItemDeltaDetail)
            assert result.notification.detail.delta == "text"

        plan = adapter.adapt_notification(
            method="turn/plan/updated",
            params={
                "threadId": THREAD_ID,
                "turnId": TURN_ID,
                "plan": [
                    {"step": "done", "status": "completed"},
                    {"step": "next", "status": "pending"},
                    "ignored",
                ],
                "explanation": "执行计划",
            },
        )
        empty_plan = adapter.adapt_notification(
            method="turn/plan/updated",
            params={"threadId": THREAD_ID, "turnId": TURN_ID, "plan": []},
        )
        diff = adapter.adapt_notification(
            method="turn/diff/updated",
            params={
                "threadId": THREAD_ID,
                "turnId": TURN_ID,
                "diff": "diff --git a/a.py b/a.py",
            },
        )

        assert plan.notification is not None
        assert isinstance(plan.notification.detail, AppServerPlanChangedDetail)
        assert plan.notification.detail.explanation == "执行计划"
        assert len(plan.notification.detail.steps) == 2
        assert plan.notification.detail.steps[0].status.value == "completed"
        assert empty_plan.notification is not None
        assert isinstance(empty_plan.notification.detail, AppServerPlanChangedDetail)
        assert empty_plan.notification.detail.steps == ()
        assert diff.notification is not None
        assert isinstance(diff.notification.detail, AppServerDiffChangedDetail)
        assert diff.notification.detail.unified_diff == "diff --git a/a.py b/a.py"
        assert diff.notification.detail.truncated is False

        for method in (
            "warning",
            "guardianWarning",
            "configWarning",
            "deprecationNotice",
            "error",
        ):
            warning = adapter.adapt_notification(
                method=method,
                params={"code": "upstream.code"},
            )
            assert warning.notification is not None
            assert isinstance(warning.notification.detail, AppServerWarningDetail)
            assert warning.notification.detail.reason_code == method
            assert warning.notification.detail.error_code == "upstream.code"

        remote_status = adapter.adapt_notification(
            method="remoteControl/status/changed",
            params={
                "installationId": "installation-1",
                "serverName": "DESKTOP",
                "status": "connected",
                "environmentId": None,
            },
        )
        assert remote_status.notification is not None
        assert isinstance(remote_status.notification.detail, AppServerWarningDetail)
        assert remote_status.notification.detail.reason_code == "remoteControl/status/changed"
        assert remote_status.notification.detail.error_code == "connected"
        malformed_remote_status = adapter.adapt_notification(
            method="remoteControl/status/changed",
            params={"installationId": "installation-1", "serverName": "DESKTOP"},
        )
        assert malformed_remote_status.notification is None
        assert (
            malformed_remote_status.warning_reason
            is AppServerProtocolWarningReason.MALFORMED_PAYLOAD
        )

        mcp_startup_status = adapter.adapt_notification(
            method="mcpServer/startupStatus/updated",
            params={
                "threadId": None,
                "name": "configured-mcp",
                "status": "ready",
                "error": None,
                "failureReason": None,
            },
        )
        assert mcp_startup_status.notification is not None
        assert isinstance(mcp_startup_status.notification.detail, AppServerWarningDetail)
        assert (
            mcp_startup_status.notification.detail.reason_code == "mcpServer/startupStatus/updated"
        )
        assert mcp_startup_status.notification.detail.error_code == "ready"
        malformed_mcp_startup_status = adapter.adapt_notification(
            method="mcpServer/startupStatus/updated",
            params={"name": "configured-mcp", "status": "not-a-status"},
        )
        assert malformed_mcp_startup_status.notification is None
        assert (
            malformed_mcp_startup_status.warning_reason
            is AppServerProtocolWarningReason.MALFORMED_PAYLOAD
        )

        rate_limits_updated = adapter.adapt_notification(
            method="account/rateLimits/updated",
            params={
                "rateLimits": {
                    "limitId": None,
                    "limitName": None,
                    "primary": None,
                    "secondary": None,
                    "credits": None,
                    "individualLimit": None,
                    "spendControlReached": None,
                    "planType": "pro",
                    "rateLimitReachedType": None,
                }
            },
        )
        assert rate_limits_updated.notification is not None
        assert isinstance(rate_limits_updated.notification.detail, AppServerWarningDetail)
        assert rate_limits_updated.notification.detail.reason_code == "account/rateLimits/updated"
        assert rate_limits_updated.notification.detail.error_code is None
        malformed_rate_limits = adapter.adapt_notification(
            method="account/rateLimits/updated",
            params={"rateLimits": {"limitId": None}},
        )
        assert malformed_rate_limits.notification is None
        assert (
            malformed_rate_limits.warning_reason is AppServerProtocolWarningReason.MALFORMED_PAYLOAD
        )

    def test_unknown_and_malformed_notifications_should_return_reason_without_payload(self) -> None:
        adapter = AppServerProtocolAdapter()
        unknown = adapter.adapt_notification(method="future/event", params={"secret": "hidden"})
        non_mapping = adapter.adapt_notification(method="warning", params="invalid")
        malformed_cases: tuple[tuple[str, JsonValue], ...] = (
            ("thread/started", {"thread": "invalid"}),
            ("thread/status/changed", {"threadId": "", "status": "idle"}),
            ("turn/completed", {"threadId": THREAD_ID, "turn": {"id": TURN_ID}}),
            (
                "item/completed",
                {
                    "threadId": THREAD_ID,
                    "turnId": 1,
                    "item": {"id": ITEM_ID, "type": "agentMessage"},
                },
            ),
            ("error", {"code": ""}),
        )

        assert unknown.notification is None
        assert unknown.warning_reason is AppServerProtocolWarningReason.UNKNOWN_NOTIFICATION
        assert non_mapping.notification is None
        assert non_mapping.warning_reason is AppServerProtocolWarningReason.MALFORMED_PAYLOAD
        for method, params in malformed_cases:
            result = adapter.adapt_notification(method=method, params=params)
            assert result.notification is None
            assert result.warning_reason is AppServerProtocolWarningReason.MALFORMED_PAYLOAD
            assert result.warning_method == method

        unknown_item = adapter.adapt_notification(
            method="item/completed",
            params={
                "threadId": THREAD_ID,
                "turnId": TURN_ID,
                "item": {"id": ITEM_ID, "type": "futureInternalItem"},
            },
        )
        assert unknown_item.notification is None
        assert unknown_item.warning_reason is AppServerProtocolWarningReason.UNKNOWN_ENUM

    def test_thread_read_should_preserve_typed_turn_and_item_content(self) -> None:
        adapter = AppServerProtocolAdapter()

        result = adapter.adapt_thread_read_result(
            {
                "thread": {
                    "id": THREAD_ID,
                    "preview": "远程线程",
                    "modelProvider": "openai",
                    "status": "idle",
                    "createdAt": 1_700_000_000,
                    "updatedAt": 1_700_000_001,
                    "turns": [
                        {
                            "id": TURN_ID,
                            "status": "completed",
                            "startedAt": 1_700_000_000,
                            "completedAt": 1_700_000_001,
                            "error": None,
                            "items": [
                                {
                                    "id": ITEM_ID,
                                    "type": "agentMessage",
                                    "text": "REMOTE_CODEX_OK",
                                },
                                {
                                    "id": "context-compaction",
                                    "type": "contextCompaction",
                                },
                                {
                                    "id": "future-item",
                                    "type": "futureInternalItem",
                                    "secret": "never-expose",
                                },
                            ],
                        }
                    ],
                }
            }
        )

        assert result.thread.thread_id == THREAD_ID
        assert result.turns[0].turn_id == TURN_ID
        assert isinstance(result.turns[0].items[0], AppServerAgentMessageItem)
        assert result.turns[0].items[0].text == "REMOTE_CODEX_OK"
        assert isinstance(result.turns[0].items[1], AppServerContextCompactionItem)
        assert len(result.turns[0].items) == 2

    def test_user_message_client_id_should_only_accept_product_uuid_v4(self) -> None:
        """官方可选 clientId 仅能成为受控的产品操作 ID。"""

        adapter = AppServerProtocolAdapter()
        valid_operation_id = "11111111-1111-4111-8111-111111111111"
        valid = adapter.adapt_notification(
            method="item/completed",
            params={
                "threadId": THREAD_ID,
                "turnId": TURN_ID,
                "item": {
                    "id": ITEM_ID,
                    "type": "userMessage",
                    "clientId": valid_operation_id,
                    "content": [{"type": "text", "text": "message"}],
                },
            },
        )
        invalid = adapter.adapt_thread_read_result(
            {
                "thread": {
                    "id": THREAD_ID,
                    "status": "idle",
                    "turns": [
                        {
                            "id": TURN_ID,
                            "status": "completed",
                            "items": [
                                {
                                    "id": ITEM_ID,
                                    "type": "userMessage",
                                    "clientId": "upstream-internal-id",
                                    "content": [{"type": "text", "text": "message"}],
                                }
                            ],
                        }
                    ],
                }
            }
        )

        assert valid.notification is not None
        assert isinstance(valid.notification.detail, AppServerItemChangedDetail)
        assert isinstance(valid.notification.detail.item, AppServerUserMessageItem)
        assert str(valid.notification.detail.item.client_operation_id) == valid_operation_id
        assert isinstance(invalid.turns[0].items[0], AppServerUserMessageItem)
        assert invalid.turns[0].items[0].client_operation_id is None
