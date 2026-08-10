"""官方 App Server notification 到产品契约的窄 adapter。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from pydantic import JsonValue, ValidationError

from src.core.codex_contract.app_server_product_contract import (
    APP_SERVER_PRODUCT_MAX_TEXT_CHARS,
    AppServerAgentMessageItem,
    AppServerCommandItem,
    AppServerDiffChangedDetail,
    AppServerDiffItem,
    AppServerItemChangedDetail,
    AppServerItemDeltaDetail,
    AppServerNoticeItem,
    AppServerPlanChangedDetail,
    AppServerPlanItem,
    AppServerPlanStep,
    AppServerProductNotification,
    AppServerProductNotificationHeader,
    AppServerProductTimelineItem,
    AppServerProtocolAdaptationResult,
    AppServerProtocolWarningReason,
    AppServerThreadChangedDetail,
    AppServerThreadProductSnapshot,
    AppServerThreadReadProductResult,
    AppServerTurnChangedDetail,
    AppServerTurnProductSnapshot,
    AppServerUserMessageItem,
    AppServerWarningDetail,
)
from src.core.codex_contract.app_server_schema_manifest_contract import (
    AppServerNotificationName,
)
from src.core.codex_contract.thread_contract import CodexPlanStepStatus

APP_SERVER_RESPONSE_HISTORY_STATUS_FIELD = "historyStatus"
APP_SERVER_RESPONSE_HISTORY_OMITTED = "omitted_too_large"
APP_SERVER_RESPONSE_HISTORY_COMPLETE = "complete"
APP_SERVER_PRODUCT_TEXT_TRUNCATION_MARKER = "\n\n[内容已截断，请在本机 Codex 中查看完整内容。]"


class AppServerProtocolAdapter:
    """只映射产品 catalog 中已审核的通知字段。"""

    def adapt_notification(
        self,
        *,
        method: str,
        params: JsonValue,
        emitted_at_ms: int | None = None,
    ) -> AppServerProtocolAdaptationResult:
        """未知或损坏 payload 只返回原因码，不携带原始正文。"""

        try:
            notification_method = AppServerNotificationName(method)
        except ValueError:
            return AppServerProtocolAdaptationResult(
                warning_reason=AppServerProtocolWarningReason.UNKNOWN_NOTIFICATION,
                warning_method=method,
            )
        if not isinstance(params, Mapping):
            return self._malformed(method)
        mapping = cast(Mapping[str, JsonValue], params)
        try:
            detail = self._build_detail(notification_method, mapping)
            return AppServerProtocolAdaptationResult(
                notification=AppServerProductNotification(
                    header=AppServerProductNotificationHeader(
                        method=notification_method,
                        emitted_at_ms=emitted_at_ms,
                    ),
                    detail=detail,
                )
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            return self._malformed(method)

    def adapt_thread_read_result(self, result: JsonValue) -> AppServerThreadReadProductResult:
        """把官方 thread/read 响应收窄为不含本机路径的强类型结果。"""

        if not isinstance(result, Mapping):
            raise ValueError("thread/read响应必须是对象。")
        mapping = cast(Mapping[str, JsonValue], result)
        thread = self._read_mapping(mapping, "thread")
        thread_id = self._read_string(thread, "id")
        raw_turns = thread.get("turns")
        if not isinstance(raw_turns, list):
            raise ValueError("thread/read响应缺少turns数组。")
        turns = tuple(
            self._to_thread_read_turn(cast(Mapping[str, JsonValue], raw_turn))
            for raw_turn in raw_turns
            if isinstance(raw_turn, Mapping)
        )
        history_status = (
            APP_SERVER_RESPONSE_HISTORY_OMITTED
            if mapping.get(APP_SERVER_RESPONSE_HISTORY_STATUS_FIELD)
            == APP_SERVER_RESPONSE_HISTORY_OMITTED
            else APP_SERVER_RESPONSE_HISTORY_COMPLETE
        )
        return AppServerThreadReadProductResult(
            thread=self._to_thread_snapshot(thread, thread_id),
            turns=turns,
            history_status=cast(
                Literal["complete", "omitted_too_large"],
                history_status,
            ),
        )

    def _build_detail(
        self,
        method: AppServerNotificationName,
        params: Mapping[str, JsonValue],
    ) -> (
        AppServerThreadChangedDetail
        | AppServerTurnChangedDetail
        | AppServerItemChangedDetail
        | AppServerItemDeltaDetail
        | AppServerPlanChangedDetail
        | AppServerDiffChangedDetail
        | AppServerWarningDetail
    ):
        if method in {
            AppServerNotificationName.THREAD_STARTED,
            AppServerNotificationName.THREAD_STATUS_CHANGED,
        }:
            thread = self._read_mapping(params, "thread")
            thread_id = self._read_string(params, "threadId", fallback=thread.get("id"))
            status = self._read_status(params.get("status", thread.get("status")))
            return AppServerThreadChangedDetail(
                thread=self._to_thread_snapshot(thread, thread_id, status=status)
            )
        if method in {
            AppServerNotificationName.TURN_STARTED,
            AppServerNotificationName.TURN_COMPLETED,
        }:
            turn = self._read_mapping(params, "turn")
            return AppServerTurnChangedDetail(
                thread_id=self._read_string(params, "threadId"),
                turn_id=self._read_string(turn, "id"),
                status=self._read_status(turn.get("status")),
            )
        if method in {
            AppServerNotificationName.ITEM_STARTED,
            AppServerNotificationName.ITEM_COMPLETED,
        }:
            item = self._read_mapping(params, "item")
            return AppServerItemChangedDetail(
                thread_id=self._read_string(params, "threadId"),
                turn_id=self._read_optional_string(params.get("turnId")),
                status=(
                    "completed" if method == AppServerNotificationName.ITEM_COMPLETED else "started"
                ),
                item=self._to_timeline_item(item),
            )
        if method in {
            AppServerNotificationName.AGENT_MESSAGE_DELTA,
            AppServerNotificationName.COMMAND_OUTPUT_DELTA,
            AppServerNotificationName.FILE_OUTPUT_DELTA,
        }:
            return AppServerItemDeltaDetail(
                thread_id=self._read_string(params, "threadId"),
                turn_id=self._read_string(params, "turnId"),
                item_id=self._read_string(params, "itemId"),
                delta=self._read_string(params, "delta"),
            )
        if method == AppServerNotificationName.TURN_PLAN_UPDATED:
            plan = params.get("plan")
            if not isinstance(plan, list):
                raise ValueError("App Server计划字段必须是数组。")
            return AppServerPlanChangedDetail(
                thread_id=self._read_string(params, "threadId"),
                turn_id=self._read_string(params, "turnId"),
                explanation=self._bounded_optional_text(params.get("explanation")),
                steps=self._to_plan_steps(plan),
            )
        if method == AppServerNotificationName.TURN_DIFF_UPDATED:
            diff = params.get("diff")
            if not isinstance(diff, str):
                raise ValueError("App Server diff字段必须是字符串。")
            return AppServerDiffChangedDetail(
                thread_id=self._read_string(params, "threadId"),
                turn_id=self._read_string(params, "turnId"),
                unified_diff=self._bounded_text(diff),
                truncated=len(diff) > APP_SERVER_PRODUCT_MAX_TEXT_CHARS,
            )
        error_code = self._read_optional_string(params.get("code"))
        return AppServerWarningDetail(reason_code=method.value, error_code=error_code)

    def _read_mapping(
        self,
        mapping: Mapping[str, JsonValue],
        key: str,
    ) -> Mapping[str, JsonValue]:
        value = mapping.get(key)
        if value is None:
            return {}
        if not isinstance(value, Mapping):
            raise ValueError("App Server字段必须是对象。")
        return cast(Mapping[str, JsonValue], value)

    def _read_string(
        self,
        mapping: Mapping[str, JsonValue],
        key: str,
        *,
        fallback: JsonValue | None = None,
    ) -> str:
        value = mapping.get(key, fallback)
        if not isinstance(value, str) or not value:
            raise ValueError("App Server字段缺少非空字符串。")
        return value

    def _read_optional_string(self, value: JsonValue | None) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            raise ValueError("App Server可选字段不是非空字符串。")
        return value

    def _read_status(self, value: JsonValue | None) -> str:
        if isinstance(value, str) and value:
            return value
        if isinstance(value, Mapping):
            status_type = cast(Mapping[str, object], value).get("type")
            if isinstance(status_type, str) and status_type:
                return status_type
        raise ValueError("App Server状态字段不受支持。")

    def _to_thread_snapshot(
        self,
        thread: Mapping[str, JsonValue],
        thread_id: str,
        *,
        status: str | None = None,
    ) -> AppServerThreadProductSnapshot:
        """只提取浏览器线程索引需要的官方字段。"""

        return AppServerThreadProductSnapshot(
            thread_id=thread_id,
            display_name=self._read_optional_string(thread.get("name") or thread.get("preview")),
            model_provider=self._read_optional_string(thread.get("modelProvider")),
            status=status or self._read_status(thread.get("status")),
            created_at=self._read_optional_timestamp(thread.get("createdAt")),
            updated_at=self._read_optional_timestamp(thread.get("updatedAt")),
        )

    def _to_thread_read_turn(
        self,
        turn: Mapping[str, JsonValue],
    ) -> AppServerTurnProductSnapshot:
        """把一个官方 turn 转为有界产品正文。"""

        raw_items = turn.get("items")
        if not isinstance(raw_items, list):
            raise ValueError("thread/read turn缺少items数组。")
        error = turn.get("error")
        error_message = None
        if isinstance(error, Mapping):
            error_mapping = cast(Mapping[str, JsonValue], error)
            error_message = self._bounded_optional_text(error_mapping.get("message"), limit=512)
        return AppServerTurnProductSnapshot(
            turn_id=self._read_string(turn, "id"),
            status=self._read_status(turn.get("status")),
            started_at=self._read_optional_timestamp(turn.get("startedAt")),
            completed_at=self._read_optional_timestamp(turn.get("completedAt")),
            error_message=error_message,
            items=tuple(
                self._to_timeline_item(cast(Mapping[str, JsonValue], raw_item))
                for raw_item in raw_items
                if isinstance(raw_item, Mapping)
            ),
        )

    def _to_timeline_item(
        self,
        item: Mapping[str, JsonValue],
    ) -> AppServerProductTimelineItem:
        """映射已审核的官方 item 联合并隐藏路径类字段。"""

        item_id = self._read_string(item, "id")
        item_type = self._read_string(item, "type")
        if item_type == "userMessage":
            return AppServerUserMessageItem(
                item_id=item_id,
                text=self._read_user_message_text(item.get("content")),
            )
        if item_type == "agentMessage":
            return AppServerAgentMessageItem(
                item_id=item_id,
                text=self._bounded_text(self._read_optional_string(item.get("text")) or ""),
            )
        if item_type == "reasoning":
            summary = item.get("summary")
            summary_text = (
                "\n".join(value for value in summary if isinstance(value, str))
                if isinstance(summary, list)
                else ""
            )
            return AppServerNoticeItem(
                item_id=item_id,
                label="reasoning",
                text=self._bounded_text(summary_text),
            )
        if item_type == "plan":
            return AppServerPlanItem(
                item_id=item_id,
                explanation=self._bounded_text(self._read_optional_string(item.get("text")) or ""),
            )
        if item_type == "commandExecution":
            return AppServerCommandItem(
                item_id=item_id,
                command=self._bounded_text(self._read_optional_string(item.get("command")) or ""),
                output=self._bounded_text(
                    self._read_optional_string(item.get("aggregatedOutput")) or ""
                ),
                exit_code=self._read_optional_int(item.get("exitCode")),
            )
        if item_type == "fileChange":
            changes = item.get("changes")
            diffs: list[str] = []
            if isinstance(changes, list):
                for change in changes:
                    if isinstance(change, Mapping):
                        diff = cast(Mapping[str, JsonValue], change).get("diff")
                        if isinstance(diff, str):
                            diffs.append(diff)
            return AppServerDiffItem(
                item_id=item_id,
                unified_diff=self._bounded_text("\n".join(diffs)),
            )
        return AppServerNoticeItem(item_id=item_id, label=item_type, text="")

    def _to_plan_steps(self, values: list[JsonValue]) -> tuple[AppServerPlanStep, ...]:
        """把官方计划数组转换为封闭状态集合。"""

        steps: list[AppServerPlanStep] = []
        for value in values:
            if not isinstance(value, Mapping):
                continue
            mapping = cast(Mapping[str, JsonValue], value)
            status = CodexPlanStepStatus(self._read_string(mapping, "status"))
            steps.append(
                AppServerPlanStep(
                    step=self._bounded_text(self._read_string(mapping, "step"), limit=4_096),
                    status=status,
                )
            )
        return tuple(steps)

    def _read_user_message_text(self, value: JsonValue | None) -> str:
        """只保留用户输入联合中的 text 项。"""

        if not isinstance(value, list):
            raise ValueError("用户消息content必须是数组。")
        parts: list[str] = []
        for raw_item in value:
            if not isinstance(raw_item, Mapping):
                raise ValueError("用户消息content条目必须是对象。")
            item = cast(Mapping[str, JsonValue], raw_item)
            if item.get("type") == "text":
                parts.append(self._read_string(item, "text"))
        return self._bounded_text("\n".join(parts))

    def _bounded_optional_text(
        self,
        value: JsonValue | None,
        *,
        limit: int = APP_SERVER_PRODUCT_MAX_TEXT_CHARS,
    ) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("App Server文本字段必须是字符串。")
        return self._bounded_text(value, limit=limit)

    def _bounded_text(
        self,
        value: str,
        *,
        limit: int = APP_SERVER_PRODUCT_MAX_TEXT_CHARS,
    ) -> str:
        if len(value) <= limit:
            return value
        marker = APP_SERVER_PRODUCT_TEXT_TRUNCATION_MARKER
        return f"{value[: max(0, limit - len(marker))]}{marker}"

    def _read_optional_timestamp(self, value: JsonValue | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            raise ValueError("App Server时间戳字段不受支持。")
        return float(value)

    def _read_optional_int(self, value: JsonValue | None) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("App Server整数字段不受支持。")
        return value

    def _malformed(self, method: str) -> AppServerProtocolAdaptationResult:
        return AppServerProtocolAdaptationResult(
            warning_reason=AppServerProtocolWarningReason.MALFORMED_PAYLOAD,
            warning_method=method,
        )
