"""Codex App Server 0.145 事件到稳定浏览器产品事件的转换。"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import UUID

from pydantic import JsonValue

from src.core.codex_contract.agent_protocol_contract import CodexAgentRealtimeEvent
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentApprovalOpenedEventDetail,
    AgentDiffChangedEventDetail,
    AgentGapEventDetail,
    AgentItemChangedEventDetail,
    AgentItemDeltaEventDetail,
    AgentPlanChangedEventDetail,
    AgentProtocolWarningEventDetail,
    AgentThreadChangedEventDetail,
    AgentThreadMetadataChangedEventDetail,
    AgentTurnChangedEventDetail,
)
from src.core.codex_contract.app_server_product_contract import (
    AppServerAgentMessageItem,
    AppServerCommandItem,
    AppServerContextCompactionItem,
    AppServerDiffItem,
    AppServerNoticeItem,
    AppServerPlanItem,
    AppServerProductTimelineItem,
    AppServerUserMessageItem,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerNotificationName,
)
from src.core.codex_contract.realtime_event_contract import CodexRealtimeEventType
from src.core.codex_contract.thread_contract import (
    CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
    CodexDiffChangeKind,
    CodexDiffFileSnapshot,
    CodexDiffHunkSnapshot,
    CodexDiffLineKind,
    CodexDiffLineSnapshot,
    CodexDiffSnapshot,
    CodexPlanStepSnapshot,
    CodexPlanStepStatus,
    CodexTimelineItemEnvelope,
)

MAX_PRODUCT_TEXT_CHARS = 1_048_576
MAX_PRODUCT_DELTA_CHARS = 64 * 1024
MAX_PRODUCT_DIFF_FILES = 200
MAX_PRODUCT_DIFF_LINES_PER_FILE = 5_000
MAX_PRODUCT_DIFF_LINE_CHARS = 4_096
DIFF_HUNK_HEADER_PATTERN = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,\d+)?\s+\+(?P<new_start>\d+)(?:,\d+)?\s+@@"
)
HIDDEN_DIFF_PATH = "[路径已隐藏]"


@dataclass(frozen=True, slots=True)
class CodexProductEvent:
    """尚未绑定浏览器连接 epoch/seq 的产品事件。"""

    host_id: UUID
    workspace_id: UUID | None
    thread_id: str | None
    turn_id: str | None
    item_id: str | None
    event_type: CodexRealtimeEventType
    payload: dict[str, JsonValue]
    occurred_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class CodexMappedThreadSnapshot:
    """App Server thread/read 转换后的内部强类型结果。"""

    thread: dict[str, JsonValue]
    turns: list[dict[str, JsonValue]]
    items: list[CodexTimelineItemEnvelope]


class CodexProtocolMapper:
    """集中隔离 App Server 字段和版本差异，前端不接触 method/params。"""

    def map_event(
        self,
        event: CodexAgentRealtimeEvent,
        *,
        workspace_id: UUID | None,
    ) -> CodexProductEvent | None:
        if event.detail is not None:
            return self._map_typed_event(event, workspace_id=workspace_id)
        params = self._mapping(event.params)
        if params is None:
            return self._warning(event, "App Server事件参数不是对象。")
        method = event.method
        if method == "internal/event.gap":
            return self._event(
                event,
                workspace_id,
                None,
                None,
                None,
                CodexRealtimeEventType.STREAM_GAP_DETECTED,
                {"reason": "agent_buffer_overflow"},
            )
        if method == "internal/protocol.warning":
            warning = params.get("warning")
            return self._warning(event, str(warning or "Agent协议告警。"))
        thread_id = self._string(params, "threadId")
        turn_id = self._string(params, "turnId")
        item_id = self._string(params, "itemId")
        if method == "thread/started":
            thread = self._mapping(params.get("thread"))
            if thread is None:
                return self._warning(event, "thread/started缺少thread。")
            thread_id = self._string(thread, "id")
            return self._event(
                event,
                workspace_id,
                thread_id,
                None,
                None,
                CodexRealtimeEventType.THREAD_UPDATED,
                {"thread": self.to_thread(thread, event.host_id, workspace_id)},
            )
        if method == "thread/status/changed":
            if thread_id is None:
                return self._warning(event, "thread/status/changed缺少threadId。")
            return self._event(
                event,
                workspace_id,
                thread_id,
                None,
                None,
                CodexRealtimeEventType.THREAD_UPDATED,
                {
                    "thread": {
                        "host_id": str(event.host_id),
                        "workspace_id": str(workspace_id) if workspace_id else "",
                        "upstream_thread_id": thread_id,
                        "status": self._status(params.get("status")),
                    }
                },
            )
        if method in {"turn/started", "turn/completed"}:
            turn = self._mapping(params.get("turn"))
            if turn is None or thread_id is None:
                return self._warning(event, f"{method}缺少thread或turn。")
            turn_payload = self.to_turn(turn, thread_id)
            turn_id = cast(str, turn_payload["turn_id"])
            event_type = self._turn_event_type(method, cast(str, turn_payload["status"]))
            return self._event(
                event,
                workspace_id,
                thread_id,
                turn_id,
                None,
                event_type,
                {"turn": turn_payload},
            )
        if method in {"item/started", "item/completed"}:
            item = self._mapping(params.get("item"))
            if item is None or thread_id is None:
                return self._warning(event, f"{method}缺少item或threadId。")
            mapped_item = self.to_item(
                item,
                thread_id=thread_id,
                turn_id=turn_id,
                completed=method == "item/completed",
            )
            if mapped_item is None:
                return None
            item_id = mapped_item.header.item_id
            return self._event(
                event,
                workspace_id,
                thread_id,
                turn_id,
                item_id,
                CodexRealtimeEventType.ITEM_UPSERT,
                {"item": mapped_item.model_dump(mode="json")},
            )
        if method in {
            "item/agentMessage/delta",
            "item/plan/delta",
            "item/reasoning/summaryTextDelta",
            "item/reasoning/textDelta",
            "item/commandExecution/outputDelta",
            "item/fileChange/outputDelta",
        }:
            delta = params.get("delta")
            if not all(isinstance(value, str) for value in (thread_id, item_id, delta)):
                return self._warning(event, f"{method}缺少delta定位字段。")
            return self._event(
                event,
                workspace_id,
                thread_id,
                turn_id,
                item_id,
                CodexRealtimeEventType.ITEM_DELTA,
                {
                    "item_id": item_id,
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "delta": self._bounded(cast(str, delta), MAX_PRODUCT_DELTA_CHARS),
                },
            )
        if method == "turn/plan/updated":
            plan = params.get("plan")
            if thread_id is None or turn_id is None or not isinstance(plan, list):
                return self._warning(event, "turn/plan/updated缺少定位字段。")
            return self._event(
                event,
                workspace_id,
                thread_id,
                turn_id,
                f"plan-{turn_id}",
                CodexRealtimeEventType.TURN_PLAN_UPDATED,
                {
                    "item_id": f"plan-{turn_id}",
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "explanation": params.get("explanation"),
                    "steps": [item.model_dump(mode="json") for item in self._map_plan_steps(plan)],
                },
            )
        if method == "turn/diff/updated":
            diff = params.get("diff")
            if thread_id is None or turn_id is None or not isinstance(diff, str):
                return self._warning(event, "turn/diff/updated缺少定位字段。")
            return self._event(
                event,
                workspace_id,
                thread_id,
                turn_id,
                f"diff-{turn_id}",
                CodexRealtimeEventType.TURN_DIFF_UPDATED,
                {
                    "item_id": f"diff-{turn_id}",
                    "thread_id": thread_id,
                    "turn_id": turn_id,
                    "diff": self._parse_diff(diff).model_dump(mode="json"),
                },
            )
        if method in {"warning", "guardianWarning", "configWarning", "deprecationNotice"}:
            message = params.get("message") or params.get("warning") or method
            return self._warning(event, str(message))
        if method == "error":
            message = params.get("message") or "Codex App Server报告错误。"
            return self._warning(event, str(message))
        return None

    def _map_typed_event(
        self,
        event: CodexAgentRealtimeEvent,
        *,
        workspace_id: UUID | None,
    ) -> CodexProductEvent | None:
        """直接消费 v2 判别联合，避免回退到有损字典协议。"""

        detail = event.detail
        if isinstance(detail, AgentGapEventDetail):
            return self._event(
                event,
                workspace_id,
                None,
                None,
                None,
                CodexRealtimeEventType.STREAM_GAP_DETECTED,
                {"reason": "agent_event_buffer_overflow"},
            )
        if isinstance(detail, AgentProtocolWarningEventDetail):
            return self._warning(event, f"Agent协议告警：{detail.reason_code}")
        if isinstance(detail, AgentThreadChangedEventDetail):
            thread = detail.thread
            return self._event(
                event,
                workspace_id,
                thread.thread_id,
                None,
                None,
                CodexRealtimeEventType.THREAD_UPDATED,
                {
                    "thread": {
                        "host_id": str(event.host_id),
                        "workspace_id": str(workspace_id) if workspace_id else "",
                        "upstream_thread_id": thread.thread_id,
                        "display_name": thread.display_name,
                        "title_source": "app_server" if thread.display_name else None,
                        "model": thread.model_id,
                        "model_provider": thread.model_provider,
                        "status": self._thread_status(thread.status),
                        "archived": thread.archived,
                        "created_at": self._iso_epoch(thread.created_at),
                        "recency_at": self._iso_epoch(
                            thread.recency_at
                            if thread.recency_at is not None
                            else thread.updated_at
                        ),
                        "updated_at": self._iso_epoch(thread.updated_at),
                    }
                },
            )
        if isinstance(detail, AgentThreadMetadataChangedEventDetail):
            return self._event(
                event,
                workspace_id,
                detail.thread_id,
                None,
                None,
                CodexRealtimeEventType.THREAD_UPDATED,
                {
                    "thread": {
                        "host_id": str(event.host_id),
                        "workspace_id": str(workspace_id) if workspace_id else "",
                        "upstream_thread_id": detail.thread_id,
                        "display_name": detail.display_name,
                        "title_source": "app_server" if detail.display_name else None,
                        "archived": detail.archived,
                    }
                },
            )
        if isinstance(detail, AgentTurnChangedEventDetail):
            event_type = self._turn_event_type(detail.method.value, detail.status)
            return self._event(
                event,
                workspace_id,
                detail.thread_id,
                detail.turn_id,
                None,
                event_type,
                {
                    "turn": {
                        "turn_id": detail.turn_id,
                        "thread_id": detail.thread_id,
                        "status": detail.status,
                        "started_at": event.occurred_at.isoformat()
                        if detail.method is AppServerNotificationName.TURN_STARTED
                        else None,
                        "completed_at": event.occurred_at.isoformat()
                        if detail.method is AppServerNotificationName.TURN_COMPLETED
                        else None,
                        "error_message": None,
                    }
                },
            )
        if isinstance(detail, AgentItemChangedEventDetail):
            item = self._to_product_timeline_item(
                detail.item,
                thread_id=detail.thread_id,
                turn_id=detail.turn_id,
                completed=detail.status == "completed",
            )
            return self._event(
                event,
                workspace_id,
                detail.thread_id,
                detail.turn_id,
                detail.item.item_id,
                CodexRealtimeEventType.ITEM_UPSERT,
                {"item": item.model_dump(mode="json")},
            )
        if isinstance(detail, AgentItemDeltaEventDetail):
            return self._event(
                event,
                workspace_id,
                detail.thread_id,
                detail.turn_id,
                detail.item_id,
                CodexRealtimeEventType.ITEM_DELTA,
                {
                    "item_id": detail.item_id,
                    "thread_id": detail.thread_id,
                    "turn_id": detail.turn_id,
                    "delta": detail.delta,
                },
            )
        if isinstance(detail, AgentPlanChangedEventDetail):
            return self._event(
                event,
                workspace_id,
                detail.thread_id,
                detail.turn_id,
                f"plan-{detail.turn_id}",
                CodexRealtimeEventType.TURN_PLAN_UPDATED,
                {
                    "item_id": f"plan-{detail.turn_id}",
                    "thread_id": detail.thread_id,
                    "turn_id": detail.turn_id,
                    "explanation": detail.explanation or "",
                    "steps": [step.model_dump(mode="json") for step in detail.steps],
                },
            )
        if isinstance(detail, AgentDiffChangedEventDetail):
            return self._event(
                event,
                workspace_id,
                detail.thread_id,
                detail.turn_id,
                f"diff-{detail.turn_id}",
                CodexRealtimeEventType.TURN_DIFF_UPDATED,
                {
                    "item_id": f"diff-{detail.turn_id}",
                    "thread_id": detail.thread_id,
                    "turn_id": detail.turn_id,
                    "diff": self._parse_diff(detail.unified_diff).model_dump(mode="json"),
                },
            )
        if isinstance(detail, AgentApprovalOpenedEventDetail):
            return None
        return None

    def _to_product_timeline_item(
        self,
        item: AppServerProductTimelineItem,
        *,
        thread_id: str,
        turn_id: str | None,
        completed: bool,
    ) -> CodexTimelineItemEnvelope:
        """把 Agent 强类型产品条目映射为浏览器时间线判别联合。"""

        header: dict[str, JsonValue] = {
            "item_id": item.item_id,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
            "status": "completed" if completed else "streaming",
        }
        if isinstance(item, AppServerUserMessageItem):
            payload: dict[str, JsonValue] = {
                "kind": "user_message",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "text": item.text,
            }
        elif isinstance(item, AppServerAgentMessageItem):
            payload = {
                "kind": "agent_message",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "text": item.text,
            }
        elif isinstance(item, AppServerNoticeItem):
            payload = {
                "kind": "notice",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "label": "推理摘要" if item.label == "reasoning" else item.label,
                "text": item.text,
            }
        elif isinstance(item, AppServerContextCompactionItem):
            payload = {
                "kind": "context_compaction",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "label": "上下文已压缩",
            }
        elif isinstance(item, AppServerPlanItem):
            payload = {
                "kind": "plan",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "explanation": item.explanation,
                "steps": [step.model_dump(mode="json") for step in item.steps],
            }
        elif isinstance(item, AppServerCommandItem):
            payload = {
                "kind": "command",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "command": item.command,
                "output": item.output,
                "exit_code": item.exit_code,
            }
        elif isinstance(item, AppServerDiffItem):
            payload = {
                "kind": "diff",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "diff": self._parse_diff(item.unified_diff).model_dump(mode="json"),
            }
        header["detail_kind"] = cast(str, payload["kind"])
        return CodexTimelineItemEnvelope.model_validate(
            {"header": header, "detail": payload}
        )

    def to_thread(
        self,
        thread: Mapping[str, JsonValue],
        host_id: UUID,
        workspace_id: UUID | None,
    ) -> dict[str, JsonValue]:
        thread_id = self._string(thread, "id") or "unknown"
        display_name = thread.get("name")
        return {
            "host_id": str(host_id),
            "workspace_id": str(workspace_id) if workspace_id else "",
            "upstream_thread_id": thread_id,
            "display_name": display_name if isinstance(display_name, str) and display_name else None,
            "title_source": "app_server"
            if isinstance(display_name, str) and display_name
            else None,
            "model": None,
            "model_provider": thread.get("modelProvider"),
            "status": self._thread_status(thread.get("status")),
            "active_turn_id": self._active_turn_id(thread),
            "archived": False,
            "created_at": self._iso_epoch(thread.get("createdAt")),
            "recency_at": self._iso_epoch(
                thread.get("recencyAt")
                if thread.get("recencyAt") is not None
                else thread.get("updatedAt")
            ),
            "updated_at": self._iso_epoch(thread.get("updatedAt")),
        }

    def to_turn(
        self,
        turn: Mapping[str, JsonValue],
        thread_id: str,
    ) -> dict[str, JsonValue]:
        return {
            "turn_id": self._string(turn, "id") or "unknown",
            "thread_id": thread_id,
            "status": self._status(turn.get("status")),
            "started_at": self._iso_epoch(turn.get("startedAt")),
            "completed_at": self._iso_epoch(turn.get("completedAt")),
            "error_message": self._error_message(turn.get("error")),
        }

    def to_item(
        self,
        item: Mapping[str, JsonValue],
        *,
        thread_id: str,
        turn_id: str | None,
        completed: bool,
    ) -> CodexTimelineItemEnvelope | None:
        item_id = self._string(item, "id")
        item_type = self._string(item, "type")
        if item_id is None or item_type is None:
            return None
        status = "completed" if completed else "streaming"
        header: dict[str, JsonValue] = {
            "item_id": item_id,
            "thread_id": thread_id,
            "turn_id": turn_id,
            "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
            "status": status,
        }
        if item_type == "userMessage":
            detail: dict[str, JsonValue] = {
                "kind": "user_message",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "text": self._bounded(
                    self._user_message_text(item.get("content")), MAX_PRODUCT_TEXT_CHARS
                ),
            }
        elif item_type == "agentMessage":
            detail = {
                "kind": "agent_message",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "text": self._bounded(str(item.get("text") or ""), MAX_PRODUCT_TEXT_CHARS),
            }
        elif item_type == "reasoning":
            summaries = item.get("summary")
            text = (
                "\n".join(str(value) for value in summaries) if isinstance(summaries, list) else ""
            )
            detail = {
                "kind": "notice",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "label": "推理摘要",
                "text": self._bounded(text, MAX_PRODUCT_TEXT_CHARS),
            }
        elif item_type == "contextCompaction":
            detail = {
                "kind": "context_compaction",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "label": "上下文已压缩",
            }
        elif item_type == "plan":
            detail = {
                "kind": "plan",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "explanation": self._bounded(
                    str(item.get("text") or ""), MAX_PRODUCT_TEXT_CHARS
                ),
                "steps": [],
            }
        elif item_type == "commandExecution":
            detail = {
                "kind": "command",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "command": self._bounded(
                    str(item.get("command") or ""), MAX_PRODUCT_TEXT_CHARS
                ),
                "output": self._bounded(
                    str(item.get("aggregatedOutput") or ""),
                    MAX_PRODUCT_TEXT_CHARS,
                ),
                "exit_code": item.get("exitCode"),
            }
        elif item_type == "fileChange":
            changes = item.get("changes")
            diffs = []
            if isinstance(changes, list):
                for change in changes:
                    mapping = self._mapping(change)
                    if mapping is not None and isinstance(mapping.get("diff"), str):
                        diffs.append(cast(str, mapping["diff"]))
            detail = {
                "kind": "diff",
                "schema_version": CODEX_TIMELINE_ITEM_SCHEMA_VERSION,
                "diff": self._parse_diff("\n".join(diffs)).model_dump(mode="json"),
            }
        else:
            return None
        header["detail_kind"] = cast(str, detail["kind"])
        return CodexTimelineItemEnvelope.model_validate(
            {"header": header, "detail": detail}
        )

    def to_thread_snapshot(
        self,
        raw: JsonValue,
        *,
        host_id: UUID,
        workspace_id: UUID,
    ) -> CodexMappedThreadSnapshot:
        response = self._mapping(raw)
        thread = self._mapping(response.get("thread")) if response is not None else None
        if thread is None:
            raise ValueError("thread/read响应缺少thread。")
        thread_id = self._string(thread, "id")
        if thread_id is None:
            raise ValueError("thread/read响应缺少thread.id。")
        turns_payload: list[dict[str, JsonValue]] = []
        items_payload: list[CodexTimelineItemEnvelope] = []
        turns = thread.get("turns")
        if isinstance(turns, list):
            for raw_turn in turns:
                turn = self._mapping(raw_turn)
                if turn is None:
                    continue
                mapped_turn = self.to_turn(turn, thread_id)
                turn_id = cast(str, mapped_turn["turn_id"])
                turns_payload.append(mapped_turn)
                items = turn.get("items")
                if isinstance(items, list):
                    for raw_item in items:
                        item = self._mapping(raw_item)
                        if item is None:
                            continue
                        mapped_item = self.to_item(
                            item,
                            thread_id=thread_id,
                            turn_id=turn_id,
                            completed=True,
                        )
                        if mapped_item is not None:
                            items_payload.append(mapped_item)
        return CodexMappedThreadSnapshot(
            thread=self.to_thread(thread, host_id, workspace_id),
            turns=turns_payload,
            items=items_payload,
        )

    def _event(
        self,
        source: CodexAgentRealtimeEvent,
        workspace_id: UUID | None,
        thread_id: str | None,
        turn_id: str | None,
        item_id: str | None,
        event_type: CodexRealtimeEventType,
        payload: dict[str, JsonValue],
    ) -> CodexProductEvent:
        return CodexProductEvent(
            host_id=source.host_id,
            workspace_id=workspace_id,
            thread_id=thread_id,
            turn_id=turn_id,
            item_id=item_id,
            event_type=event_type,
            payload=payload,
            occurred_at=source.occurred_at,
        )

    def _warning(self, source: CodexAgentRealtimeEvent, warning: str) -> CodexProductEvent:
        return self._event(
            source,
            None,
            None,
            None,
            None,
            CodexRealtimeEventType.PROTOCOL_WARNING,
            {"warning": warning[:512]},
        )

    def _turn_event_type(self, method: str, status: str) -> CodexRealtimeEventType:
        if method == "turn/started":
            return CodexRealtimeEventType.TURN_STARTED
        if status == "failed":
            return CodexRealtimeEventType.TURN_FAILED
        if status in {"interrupted", "cancelled"}:
            return CodexRealtimeEventType.TURN_INTERRUPTED
        return CodexRealtimeEventType.TURN_COMPLETED

    def _mapping(self, value: object) -> Mapping[str, JsonValue] | None:
        return cast(Mapping[str, JsonValue], value) if isinstance(value, Mapping) else None

    def _string(self, mapping: Mapping[str, JsonValue], key: str) -> str | None:
        value = mapping.get(key)
        return value if isinstance(value, str) and value else None

    def _status(self, value: JsonValue | None) -> str:
        if isinstance(value, str):
            return value
        mapping = self._mapping(value)
        if mapping is not None:
            status_type = mapping.get("type")
            if isinstance(status_type, str):
                return "failed" if status_type == "systemError" else status_type
        return "unknown"

    def _thread_status(self, value: JsonValue | None) -> str:
        """把上游运行时状态收敛为控制面会话状态。"""

        status = self._status(value)
        if status in {"active", "inProgress"}:
            return "active"
        if status in {"interrupted", "cancelled"}:
            return "interrupted"
        if status in {"failed", "systemError"}:
            return "failed"
        if status in {"idle", "completed"}:
            return "idle"
        return "unknown"

    def _active_turn_id(self, thread: Mapping[str, JsonValue]) -> str | None:
        turns = thread.get("turns")
        if not isinstance(turns, list):
            return None
        for raw_turn in reversed(turns):
            turn = self._mapping(raw_turn)
            if turn is not None and self._status(turn.get("status")) in {"active", "inProgress"}:
                return self._string(turn, "id")
        return None

    def _iso_epoch(self, value: JsonValue | None) -> str | None:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return None
        from datetime import UTC, datetime

        return datetime.fromtimestamp(value, tz=UTC).isoformat()

    def _user_message_text(self, value: JsonValue | None) -> str:
        if not isinstance(value, list):
            return ""
        parts: list[str] = []
        for raw in value:
            item = self._mapping(raw)
            if (
                item is not None
                and item.get("type") == "text"
                and isinstance(item.get("text"), str)
            ):
                parts.append(cast(str, item["text"]))
        return "\n".join(parts)

    def _error_message(self, value: JsonValue | None) -> str | None:
        mapping = self._mapping(value)
        if mapping is None:
            return None
        message = mapping.get("message")
        return str(message)[:512] if message is not None else None

    def _bounded(self, value: str, limit: int) -> str:
        """限制浏览器产品事件正文，避免单个上游 item 造成无界内存。"""

        if len(value) <= limit:
            return value
        marker = "\n\n[内容已截断，请在本机 Codex 中查看完整内容。]"
        return f"{value[: max(0, limit - len(marker))]}{marker}"

    def _map_plan_steps(self, values: list[JsonValue]) -> tuple[CodexPlanStepSnapshot, ...]:
        """把官方 plan 数组收敛为稳定步骤状态。"""

        steps: list[CodexPlanStepSnapshot] = []
        for value in values:
            mapping = self._mapping(value)
            if mapping is None:
                continue
            step = mapping.get("step")
            status = mapping.get("status")
            if not isinstance(step, str) or not step:
                continue
            try:
                typed_status = CodexPlanStepStatus(str(status))
            except ValueError:
                typed_status = CodexPlanStepStatus.PENDING
            steps.append(
                CodexPlanStepSnapshot(
                    step=self._bounded(step, 4_096),
                    status=typed_status,
                )
            )
        return tuple(steps)

    def _parse_diff(self, value: str) -> CodexDiffSnapshot:
        """把官方 unified diff 解析为按文件和 hunk 分组的产品模型。"""

        source = value[:MAX_PRODUCT_TEXT_CHARS]
        source_truncated = len(value) > len(source)
        lines = source.splitlines()
        file_segments: list[list[str]] = []
        current: list[str] = []
        for line in lines:
            if line.startswith("diff --git ") and current:
                file_segments.append(current)
                current = []
            current.append(line)
        if current:
            file_segments.append(current)
        files = tuple(
            self._parse_diff_file(segment) for segment in file_segments[:MAX_PRODUCT_DIFF_FILES]
        )
        return CodexDiffSnapshot(
            files=files,
            total_characters=len(value),
            truncated=(
                source_truncated
                or len(file_segments) > MAX_PRODUCT_DIFF_FILES
                or any(item.truncated for item in files)
            ),
        )

    def _parse_diff_file(self, lines: list[str]) -> CodexDiffFileSnapshot:
        """解析单个 unified diff 文件段并计算行号。"""

        old_path = self._read_diff_header_path(lines, "--- ")
        new_path = self._read_diff_header_path(lines, "+++ ")
        change_kind = CodexDiffChangeKind.MODIFIED
        if old_path == "/dev/null":
            change_kind = CodexDiffChangeKind.ADDED
        elif new_path == "/dev/null":
            change_kind = CodexDiffChangeKind.DELETED
        elif any(line.startswith("rename from ") for line in lines):
            change_kind = CodexDiffChangeKind.RENAMED
        path = new_path if new_path not in {None, "/dev/null"} else old_path
        sanitized_path = self._sanitize_diff_path(path)
        sanitized_old_path = (
            self._sanitize_diff_path(old_path) if old_path not in {None, "/dev/null"} else None
        )
        binary = any(
            line.startswith("Binary files ") or line == "GIT binary patch" for line in lines
        )
        hunks: list[CodexDiffHunkSnapshot] = []
        index = 0
        while index < len(lines):
            match = DIFF_HUNK_HEADER_PATTERN.match(lines[index])
            if match is None:
                index += 1
                continue
            header = lines[index][:512]
            old_line = int(match.group("old_start"))
            new_line = int(match.group("new_start"))
            index += 1
            parsed_lines: list[CodexDiffLineSnapshot] = []
            while index < len(lines) and not lines[index].startswith("@@ "):
                raw_line = lines[index]
                if raw_line.startswith("diff --git "):
                    break
                if raw_line.startswith("+") and not raw_line.startswith("+++"):
                    parsed_lines.append(
                        CodexDiffLineSnapshot(
                            kind=CodexDiffLineKind.ADDITION,
                            content=raw_line[1:][:MAX_PRODUCT_DIFF_LINE_CHARS],
                            new_line_number=max(new_line, 1),
                        )
                    )
                    new_line += 1
                elif raw_line.startswith("-") and not raw_line.startswith("---"):
                    parsed_lines.append(
                        CodexDiffLineSnapshot(
                            kind=CodexDiffLineKind.DELETION,
                            content=raw_line[1:][:MAX_PRODUCT_DIFF_LINE_CHARS],
                            old_line_number=max(old_line, 1),
                        )
                    )
                    old_line += 1
                elif not raw_line.startswith("\\ No newline"):
                    content = raw_line[1:] if raw_line.startswith(" ") else raw_line
                    parsed_lines.append(
                        CodexDiffLineSnapshot(
                            kind=CodexDiffLineKind.CONTEXT,
                            content=content[:MAX_PRODUCT_DIFF_LINE_CHARS],
                            old_line_number=max(old_line, 1),
                            new_line_number=max(new_line, 1),
                        )
                    )
                    old_line += 1
                    new_line += 1
                index += 1
            hunks.append(
                CodexDiffHunkSnapshot(
                    header=header,
                    old_start=int(match.group("old_start")),
                    new_start=int(match.group("new_start")),
                    lines=tuple(parsed_lines[:MAX_PRODUCT_DIFF_LINES_PER_FILE]),
                )
            )
        total_lines = sum(len(item.lines) for item in hunks)
        return CodexDiffFileSnapshot(
            path=sanitized_path,
            old_path=sanitized_old_path,
            change_kind=change_kind,
            binary=binary,
            large=(
                len("\n".join(lines)) > MAX_PRODUCT_TEXT_CHARS
                or total_lines > MAX_PRODUCT_DIFF_LINES_PER_FILE
            ),
            truncated=total_lines > MAX_PRODUCT_DIFF_LINES_PER_FILE,
            hunks=tuple(hunks),
        )

    def _read_diff_header_path(self, lines: list[str], prefix: str) -> str | None:
        for line in lines:
            if line.startswith(prefix):
                return line[len(prefix) :].split("\t", maxsplit=1)[0]
        return None

    def _sanitize_diff_path(self, value: str | None) -> str:
        if value is None:
            return HIDDEN_DIFF_PATH
        normalized = value.replace("\\", "/")
        if normalized.startswith(("a/", "b/")):
            normalized = normalized[2:]
        path_parts = normalized.split("/")
        if (
            normalized.startswith("/")
            or ":" in path_parts[0]
            or any(part in {"", ".", ".."} for part in path_parts)
        ):
            return HIDDEN_DIFF_PATH
        return normalized[:1_024]
