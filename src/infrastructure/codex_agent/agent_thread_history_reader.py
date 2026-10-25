"""单次有界读取上游turn窗口，保留跨页游标并校验局部内容版本。"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from src.core.codex_contract.agent_history_window_contract import (
    AgentHistoryWindowRequest,
    AgentHistoryWindowResult,
    AgentHistoryWindowStaleError,
)
from src.core.codex_contract.app_server_jsonrpc_contract import (
    AppServerMessageTooLargeError,
    AppServerRpcClientPort,
)
from src.core.codex_contract.app_server_schema_manifest_contract import AppServerMethodName
from src.infrastructure.codex_agent.agent_timeline_store import AgentTimelineStore

HISTORY_WINDOW_MAX_PAGES = 8
HISTORY_WINDOW_MAX_BYTES = 2 * 1024 * 1024


class _HistoryPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    upstream_cursor: str | None = Field(default=None, max_length=4096)
    consumed_items: int = Field(default=0, ge=0)
    page_digest: str | None = None


async def read_thread_history_window(
    client: AppServerRpcClientPort,
    metadata: JsonValue,
    *,
    thread_id: str,
    request: AgentHistoryWindowRequest,
    deadline: float,
    operation_id: str,
    timeline_store: AgentTimelineStore | None = None,
) -> JsonValue:
    """最多8个上游页、200个item和2MiB；空页也返回可继续前进的游标。"""
    if not isinstance(metadata, dict) or not isinstance(metadata.get("thread"), dict):
        raise ValueError("历史窗口缺少thread元数据。")
    thread = cast(dict[str, JsonValue], metadata["thread"])
    revision = hashlib.sha256(
        json.dumps(
            [thread_id, thread.get("updatedAt"), thread.get("status")],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    if request.revision is not None and request.revision != revision:
        raise AgentHistoryWindowStaleError("历史版本已变化。")
    position = (
        _HistoryPosition.model_validate_json(request.cursor)
        if request.cursor
        else _HistoryPosition()
    )
    turns: list[JsonValue] = []
    item_count = 0
    byte_count = len(json.dumps(metadata, ensure_ascii=False).encode("utf-8"))
    next_position: _HistoryPosition | None = position
    seen_cursors: set[str | None] = set()
    for _ in range(HISTORY_WINDOW_MAX_PAGES):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("历史窗口读取超过总预算。")
        params: dict[str, JsonValue] = {
            "threadId": thread_id,
            "itemsView": "full",
            "sortDirection": "desc",
            "limit": 1,
        }
        if position.upstream_cursor is not None:
            params["cursor"] = position.upstream_cursor
        page = await client.request(
            AppServerMethodName.THREAD_TURNS_LIST.value,
            params,
            timeout_seconds=remaining,
            operation_id=operation_id,
        )
        if not isinstance(page, Mapping) or not isinstance(page.get("data"), list):
            raise ValueError("历史分页响应缺少data。")
        data = page["data"]
        if len(data) > 1:
            raise ValueError("上游没有遵守历史分页容量。")
        digest = hashlib.sha256(
            json.dumps(data, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        upstream_next = page.get("nextCursor")
        if upstream_next is not None and (not isinstance(upstream_next, str) or not upstream_next):
            raise ValueError("历史分页nextCursor无效。")
        next_position = (
            _HistoryPosition(upstream_cursor=upstream_next) if upstream_next is not None else None
        )
        if data:
            turn = data[0]
            if not isinstance(turn, dict) or not isinstance(turn.get("items"), list):
                raise ValueError("历史turn缺少items。")
            local = (
                timeline_store.read_history_window(
                    thread_id,
                    str(turn["id"]),
                    offset=position.consumed_items,
                    limit=request.limit - item_count,
                )
                if timeline_store
                else None
            )
            if local is not None:
                digest = local.revision
                candidates = [item.model_dump(mode="json") for item in local.items]
                total = local.total_items
            else:
                items = cast(list[JsonValue], turn["items"])
                total = len(items)
                candidates = list(reversed(items[: total - position.consumed_items]))
            if position.page_digest is not None and position.page_digest != digest:
                raise AgentHistoryWindowStaleError("历史分页内容已变化。")
            if position.consumed_items > total:
                raise AgentHistoryWindowStaleError("历史item边界已变化。")
            selected_items: list[JsonValue] = []
            for item in candidates:
                if item_count >= request.limit:
                    break
                size = len(json.dumps(item, ensure_ascii=False).encode("utf-8"))
                if byte_count + size > HISTORY_WINDOW_MAX_BYTES:
                    if item_count == 0:
                        raise AppServerMessageTooLargeError("单个历史item超过窗口字节预算。")
                    break
                selected_items.append(item)
                byte_count += size
                item_count += 1
            selected = dict(turn)
            selected["items"] = [] if local is not None else list(reversed(selected_items))
            if local is not None:
                selected["productItems"] = list(reversed(selected_items))
            turns.append(selected)
            consumed = position.consumed_items + len(selected_items)
            if consumed < total:
                next_position = _HistoryPosition(
                    upstream_cursor=position.upstream_cursor,
                    consumed_items=consumed,
                    page_digest=digest,
                )
                break
        if next_position is None or item_count >= request.limit:
            break
        if next_position.upstream_cursor in seen_cursors:
            raise ValueError("历史分页cursor循环。")
        seen_cursors.add(next_position.upstream_cursor)
        position = next_position
    result_thread = dict(thread)
    result_thread["turns"] = list(reversed(turns))
    result = dict(metadata)
    result["thread"] = result_thread
    result["historyWindow"] = AgentHistoryWindowResult(
        cursor=next_position.model_dump_json() if next_position else None,
        revision=revision,
        has_more=next_position is not None,
    ).model_dump(mode="json")
    return result
