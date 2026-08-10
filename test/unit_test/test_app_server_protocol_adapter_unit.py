"""App Server 产品 notification 适配器单元测试。"""

from __future__ import annotations

from pydantic import JsonValue

from src.core.codex_contract.app_server_product_contract import (
    AppServerAgentMessageItem,
    AppServerDiffChangedDetail,
    AppServerItemChangedDetail,
    AppServerItemDeltaDetail,
    AppServerPlanChangedDetail,
    AppServerProtocolWarningReason,
    AppServerThreadChangedDetail,
    AppServerTurnChangedDetail,
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
                                }
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
