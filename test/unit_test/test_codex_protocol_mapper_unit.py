"""Codex App Server 产品事件映射单元测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue

from src.application.codex.codex_protocol_mapper import (
    HIDDEN_DIFF_PATH,
    MAX_PRODUCT_DELTA_CHARS,
    CodexProtocolMapper,
)
from src.core.codex_contract.agent_protocol_contract import CodexAgentRealtimeEvent
from src.core.codex_contract.agent_protocol_v2_contract import AgentItemChangedEventDetail
from src.core.codex_contract.app_server_product_contract import (
    AppServerContextCompactionItem,
    AppServerUserMessageItem,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerNotificationName,
)
from src.core.codex_contract.realtime_event_contract import CodexRealtimeEventType

APP_SERVER_INSTANCE_ID = "app-server-mapper"
THREAD_ID = "thread-mapper"
TURN_ID = "turn-mapper"
ITEM_ID = "item-mapper"


class TestCodexProtocolMapperUnit:
    """覆盖冻结通知目录、快照、计划与 diff 映射。"""

    def test_map_event_should_handle_internal_thread_and_turn_notifications(self) -> None:
        mapper = CodexProtocolMapper()
        host_id = uuid4()
        workspace_id = uuid4()

        invalid = mapper.map_event(
            self._event(host_id, "thread/started", "invalid"),
            workspace_id=workspace_id,
        )
        gap = mapper.map_event(
            self._event(host_id, "internal/event.gap", {}),
            workspace_id=workspace_id,
        )
        protocol_warning = mapper.map_event(
            self._event(host_id, "internal/protocol.warning", {"warning": "schema drift"}),
            workspace_id=workspace_id,
        )
        thread_warning = mapper.map_event(
            self._event(host_id, "thread/started", {}),
            workspace_id=workspace_id,
        )
        thread_started = mapper.map_event(
            self._event(
                host_id,
                "thread/started",
                {
                    "thread": {
                        "id": THREAD_ID,
                        "name": "映射线程",
                        "modelProvider": "openai",
                        "status": {"type": "active"},
                        "createdAt": 1_700_000_000,
                        "updatedAt": 1_700_000_001.5,
                        "turns": [{"id": TURN_ID, "status": "inProgress"}],
                    }
                },
            ),
            workspace_id=workspace_id,
        )
        missing_thread_id = mapper.map_event(
            self._event(host_id, "thread/status/changed", {"status": "idle"}),
            workspace_id=workspace_id,
        )
        thread_status = mapper.map_event(
            self._event(
                host_id,
                "thread/status/changed",
                {"threadId": THREAD_ID, "status": {"type": "systemError"}},
            ),
            workspace_id=None,
        )

        assert invalid is not None
        assert invalid.event_type is CodexRealtimeEventType.PROTOCOL_WARNING
        assert gap is not None
        assert gap.event_type is CodexRealtimeEventType.STREAM_GAP_DETECTED
        assert protocol_warning is not None
        assert protocol_warning.payload["warning"] == "schema drift"
        assert thread_warning is not None
        assert missing_thread_id is not None
        assert thread_started is not None
        assert thread_started.thread_id == THREAD_ID
        started_thread_payload = self._mapping(thread_started.payload["thread"])
        assert started_thread_payload["active_turn_id"] == TURN_ID
        created_at = started_thread_payload["created_at"]
        assert isinstance(created_at, str)
        assert created_at.endswith("+00:00")
        assert thread_status is not None
        status_thread_payload = self._mapping(thread_status.payload["thread"])
        assert status_thread_payload["status"] == "failed"
        assert status_thread_payload["workspace_id"] == ""

        for method, status, expected_type in (
            ("turn/started", "active", CodexRealtimeEventType.TURN_STARTED),
            ("turn/completed", "failed", CodexRealtimeEventType.TURN_FAILED),
            ("turn/completed", "interrupted", CodexRealtimeEventType.TURN_INTERRUPTED),
            ("turn/completed", "cancelled", CodexRealtimeEventType.TURN_INTERRUPTED),
            ("turn/completed", "completed", CodexRealtimeEventType.TURN_COMPLETED),
        ):
            mapped = mapper.map_event(
                self._event(
                    host_id,
                    method,
                    {
                        "threadId": THREAD_ID,
                        "turn": {
                            "id": TURN_ID,
                            "status": status,
                            "startedAt": 1_700_000_000,
                            "completedAt": True,
                            "error": {"message": "failed"},
                        },
                    },
                ),
                workspace_id=workspace_id,
            )
            assert mapped is not None
            assert mapped.event_type is expected_type
            turn_payload = self._mapping(mapped.payload["turn"])
            assert turn_payload["completed_at"] is None
            assert turn_payload["error_message"] == "failed"

        turn_warning = mapper.map_event(
            self._event(host_id, "turn/completed", {"threadId": THREAD_ID}),
            workspace_id=workspace_id,
        )
        assert turn_warning is not None
        assert turn_warning.event_type is CodexRealtimeEventType.PROTOCOL_WARNING

    def test_map_event_should_consume_typed_v2_detail_without_lossy_params(self) -> None:
        mapper = CodexProtocolMapper()
        host_id = uuid4()
        workspace_id = uuid4()
        event = CodexAgentRealtimeEvent(
            host_id=host_id,
            app_server_instance_id=APP_SERVER_INSTANCE_ID,
            occurred_at=datetime.now(UTC),
            method=AppServerNotificationName.ITEM_COMPLETED.value,
            params={"threadId": "wrong-thread", "secret": "never-use"},
            detail=AgentItemChangedEventDetail(
                method=AppServerNotificationName.ITEM_COMPLETED,
                thread_id=THREAD_ID,
                turn_id=TURN_ID,
                status="completed",
                item=AppServerContextCompactionItem(item_id=ITEM_ID),
            ),
        )

        mapped = mapper.map_event(event, workspace_id=workspace_id)

        assert mapped is not None
        assert mapped.thread_id == THREAD_ID
        item = self._mapping(mapped.payload["item"])
        detail = self._mapping(item["detail"])
        assert detail == {
            "kind": "context_compaction",
            "schema_version": "1.0",
            "label": "上下文已压缩",
        }

    def test_map_event_should_propagate_typed_user_message_operation_id(self) -> None:
        """实时产品事件必须保留已验证的乐观消息对账 ID。"""

        mapper = CodexProtocolMapper()
        host_id = uuid4()
        workspace_id = uuid4()
        client_operation_id = UUID("11111111-1111-4111-8111-111111111111")
        event = CodexAgentRealtimeEvent(
            host_id=host_id,
            app_server_instance_id=APP_SERVER_INSTANCE_ID,
            occurred_at=datetime.now(UTC),
            method=AppServerNotificationName.ITEM_COMPLETED.value,
            params={},
            detail=AgentItemChangedEventDetail(
                method=AppServerNotificationName.ITEM_COMPLETED,
                thread_id=THREAD_ID,
                turn_id=TURN_ID,
                status="completed",
                item=AppServerUserMessageItem(
                    item_id=ITEM_ID,
                    text="message",
                    client_operation_id=client_operation_id,
                ),
            ),
        )

        mapped = mapper.map_event(event, workspace_id=workspace_id)

        assert mapped is not None
        item = self._mapping(mapped.payload["item"])
        header = self._mapping(item["header"])
        assert header["client_operation_id"] == str(client_operation_id)

    def test_map_event_should_handle_item_delta_plan_diff_and_warning_catalog(self) -> None:
        mapper = CodexProtocolMapper()
        host_id = uuid4()
        workspace_id = uuid4()
        item_payloads: tuple[dict[str, JsonValue], ...] = (
            {
                "id": "user",
                "type": "userMessage",
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "image", "url": "ignored"},
                    {"type": "text", "text": "second"},
                ],
            },
            {"id": "agent", "type": "agentMessage", "text": "answer"},
            {"id": "reasoning", "type": "reasoning", "summary": ["a", "b"]},
            {"id": "plan", "type": "plan", "text": "plan text"},
            {
                "id": "command",
                "type": "commandExecution",
                "command": "uv run pytest",
                "aggregatedOutput": "passed",
                "exitCode": 0,
            },
            {
                "id": "file-change",
                "type": "fileChange",
                "changes": [
                    {"diff": "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-old\n+new"},
                    "ignored",
                ],
            },
            {"id": "compaction", "type": "contextCompaction"},
        )

        kinds: list[str] = []
        for item in item_payloads:
            mapped = mapper.map_event(
                self._event(
                    host_id,
                    "item/completed",
                    {"threadId": THREAD_ID, "turnId": TURN_ID, "item": item},
                ),
                workspace_id=workspace_id,
            )
            assert mapped is not None
            item_payload = self._mapping(mapped.payload["item"])
            item_detail = self._mapping(item_payload["detail"])
            kinds.append(str(item_detail["kind"]))
        assert kinds == [
            "user_message",
            "agent_message",
            "notice",
            "plan",
            "command",
            "diff",
            "context_compaction",
        ]

        unknown_item = mapper.map_event(
            self._event(
                host_id,
                "item/completed",
                {
                    "threadId": THREAD_ID,
                    "turnId": TURN_ID,
                    "item": {"id": "unknown", "type": "webSearch"},
                },
            ),
            workspace_id=workspace_id,
        )
        assert unknown_item is None

        invalid_item = mapper.map_event(
            self._event(
                host_id,
                "item/started",
                {"threadId": THREAD_ID, "item": {"id": ITEM_ID}},
            ),
            workspace_id=workspace_id,
        )
        missing_item = mapper.map_event(
            self._event(host_id, "item/completed", {"threadId": THREAD_ID}),
            workspace_id=workspace_id,
        )
        assert invalid_item is None
        assert missing_item is not None

        delta = mapper.map_event(
            self._event(
                host_id,
                "item/agentMessage/delta",
                {
                    "threadId": THREAD_ID,
                    "turnId": TURN_ID,
                    "itemId": ITEM_ID,
                    "delta": "x" * (MAX_PRODUCT_DELTA_CHARS + 10),
                },
            ),
            workspace_id=workspace_id,
        )
        bad_delta = mapper.map_event(
            self._event(
                host_id,
                "item/plan/delta",
                {"threadId": THREAD_ID, "itemId": ITEM_ID, "delta": 1},
            ),
            workspace_id=workspace_id,
        )
        assert delta is not None
        assert len(str(delta.payload["delta"])) == MAX_PRODUCT_DELTA_CHARS
        assert bad_delta is not None
        assert bad_delta.event_type is CodexRealtimeEventType.PROTOCOL_WARNING

        plan = mapper.map_event(
            self._event(
                host_id,
                "turn/plan/updated",
                {
                    "threadId": THREAD_ID,
                    "turnId": TURN_ID,
                    "explanation": "next",
                    "plan": [
                        {"step": "done", "status": "completed"},
                        {"step": "unknown", "status": "future"},
                        {"step": "", "status": "pending"},
                        "ignored",
                    ],
                },
            ),
            workspace_id=workspace_id,
        )
        bad_plan = mapper.map_event(
            self._event(host_id, "turn/plan/updated", {"threadId": THREAD_ID}),
            workspace_id=workspace_id,
        )
        assert plan is not None
        steps = self._sequence(plan.payload["steps"])
        assert [self._mapping(step)["status"] for step in steps] == [
            "completed",
            "pending",
        ]
        assert bad_plan is not None

        diff_text = "\n".join(
            (
                "diff --git a/old.py b/new.py",
                "similarity index 100%",
                "rename from old.py",
                "rename to new.py",
                "--- a/old.py",
                "+++ b/new.py",
                "@@ -1,2 +1,2 @@ section",
                " same",
                "-old",
                "+new",
                "\\ No newline at end of file",
                "diff --git a/image.bin b/image.bin",
                "--- /dev/null",
                "+++ b/image.bin",
                "Binary files /dev/null and b/image.bin differ",
            )
        )
        diff = mapper.map_event(
            self._event(
                host_id,
                "turn/diff/updated",
                {"threadId": THREAD_ID, "turnId": TURN_ID, "diff": diff_text},
            ),
            workspace_id=workspace_id,
        )
        bad_diff = mapper.map_event(
            self._event(
                host_id,
                "turn/diff/updated",
                {"threadId": THREAD_ID, "turnId": TURN_ID, "diff": 1},
            ),
            workspace_id=workspace_id,
        )
        assert diff is not None
        diff_payload = self._mapping(diff.payload["diff"])
        files = self._sequence(diff_payload["files"])
        first_file = self._mapping(files[0])
        second_file = self._mapping(files[1])
        hunks = self._sequence(first_file["hunks"])
        first_hunk = self._mapping(hunks[0])
        lines = self._sequence(first_hunk["lines"])
        assert first_file["change_kind"] == "renamed"
        assert self._mapping(lines[1])["kind"] == "deletion"
        assert second_file["change_kind"] == "added"
        assert second_file["binary"] is True
        assert bad_diff is not None

        for method in ("warning", "guardianWarning", "configWarning", "deprecationNotice"):
            warning = mapper.map_event(
                self._event(host_id, method, {"message": "notice"}),
                workspace_id=workspace_id,
            )
            assert warning is not None
            assert warning.payload["warning"] == "notice"
        error = mapper.map_event(
            self._event(host_id, "error", {}),
            workspace_id=workspace_id,
        )
        unknown = mapper.map_event(
            self._event(host_id, "future/event", {}),
            workspace_id=workspace_id,
        )
        assert error is not None
        assert unknown is None

    def test_thread_snapshot_should_map_nested_items_and_reject_missing_identity(self) -> None:
        mapper = CodexProtocolMapper()
        host_id = uuid4()
        workspace_id = uuid4()
        snapshot = mapper.to_thread_snapshot(
            {
                "thread": {
                    "id": THREAD_ID,
                    "preview": "snapshot",
                    "status": None,
                    "turns": [
                        {
                            "id": TURN_ID,
                            "status": {"type": "completed"},
                            "items": [
                                {"id": ITEM_ID, "type": "agentMessage", "text": "done"},
                                {"type": "invalid"},
                                "ignored",
                            ],
                        },
                        "ignored",
                    ],
                }
            },
            host_id=host_id,
            workspace_id=workspace_id,
        )

        assert snapshot.thread["upstream_thread_id"] == THREAD_ID
        assert snapshot.thread["status"] == "unknown"
        assert snapshot.thread["active_turn_id"] is None
        assert len(snapshot.turns) == 1
        assert [item.header.item_id for item in snapshot.items] == [ITEM_ID]

        with pytest.raises(ValueError, match="缺少thread"):
            mapper.to_thread_snapshot({}, host_id=host_id, workspace_id=workspace_id)
        with pytest.raises(ValueError, match="thread.id"):
            mapper.to_thread_snapshot(
                {"thread": {}},
                host_id=host_id,
                workspace_id=workspace_id,
            )

    def test_diff_path_sanitization_should_hide_absolute_and_parent_paths(self) -> None:
        mapper = CodexProtocolMapper()
        hidden_values = (None, "/root/file", "C:/secret.txt", "../secret.txt", "a//b")

        assert [mapper._sanitize_diff_path(value) for value in hidden_values] == [  # noqa: SLF001
            HIDDEN_DIFF_PATH,
            HIDDEN_DIFF_PATH,
            HIDDEN_DIFF_PATH,
            HIDDEN_DIFF_PATH,
            HIDDEN_DIFF_PATH,
        ]
        assert mapper._sanitize_diff_path("a/src/main.py") == "src/main.py"  # noqa: SLF001

    def _event(
        self,
        host_id: UUID,
        method: str,
        params: JsonValue,
    ) -> CodexAgentRealtimeEvent:
        """构建最小上游事件。"""

        return CodexAgentRealtimeEvent(
            host_id=host_id,
            app_server_instance_id=APP_SERVER_INSTANCE_ID,
            occurred_at=datetime.now(UTC),
            method=method,
            params=params,
        )

    @staticmethod
    def _mapping(value: JsonValue) -> dict[str, JsonValue]:
        """把已知对象载荷收窄为强类型映射。"""

        assert isinstance(value, dict)
        return value

    @staticmethod
    def _sequence(value: JsonValue) -> list[JsonValue]:
        """把已知数组载荷收窄为强类型序列。"""

        assert isinstance(value, list)
        return value
