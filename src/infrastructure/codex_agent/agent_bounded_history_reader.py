"""公开 items/turns 分页到完整编码预算内的产品历史页。"""

import asyncio
import hashlib
import json
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from src.core.codex_contract.agent_content_contract import ContentErrorCode, ContentReadError
from src.core.codex_contract.agent_history_window_contract import (
    AgentBoundedHistoryWindowRequest,
    AgentHistoryWindowResult,
    AgentHistoryWindowStaleError,
)
from src.core.codex_contract.app_server_jsonrpc_contract import AppServerRpcClientPort
from src.core.codex_contract.app_server_product_contract import (
    AppServerThreadReadProductResult,
    AppServerProductTimelineItem,
)
from src.infrastructure.codex_agent.agent_content_reader import AgentContentReader
from src.infrastructure.codex_agent.agent_thread_history_window_cache import (
    AgentThreadHistoryWindowCache,
)
from src.infrastructure.codex_agent.app_server_protocol_adapter import AppServerProtocolAdapter
from src.infrastructure.codex_agent.agent_timeline_store import AgentTimelineStore


class _Position(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    cursor: str | None = Field(default=None, max_length=4096)
    item_cursor: str | None = Field(default=None, max_length=4096)
    consumed: int = Field(default=0, ge=0)
    digest: str | None = None
    strategy: str


class AgentBoundedHistoryReader:
    def __init__(
        self,
        *,
        client: AppServerRpcClientPort,
        cache: AgentThreadHistoryWindowCache,
        timeline_store: AgentTimelineStore | None = None,
        sanitize_source: Callable[[str, dict[str, JsonValue]], dict[str, JsonValue]],
        strategy: str,
        sanitize: Callable[[AppServerThreadReadProductResult], AppServerThreadReadProductResult],
    ) -> None:
        self._timeline_store = timeline_store
        self._client = client
        self._cache = cache
        self._content = AgentContentReader(cache)
        self._strategy = strategy
        self._sanitize = sanitize
        self._sanitize_source = sanitize_source
        self._adapter = AppServerProtocolAdapter()

    async def read(
        self,
        *,
        workspace_key: str,
        thread_id: str,
        request: AgentBoundedHistoryWindowRequest,
        deadline: float,
        operation_id: str,
        max_bytes: int,
        encoded_size: Callable[[AppServerThreadReadProductResult], int],
    ) -> AppServerThreadReadProductResult:
        if self._strategy not in {"items_page", "turns_page"}:
            raise ContentReadError(ContentErrorCode.CAPABILITY_UNAVAILABLE)
        generation = self._cache.invalidation_generation

        async def query(method: str, params: dict[str, JsonValue]) -> dict[str, JsonValue]:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("历史读取超过deadline。")
            value = await self._client.request(
                method, params, timeout_seconds=remaining, operation_id=operation_id
            )
            if not isinstance(value, dict):
                raise ValueError("历史源响应不是对象。")
            return value

        metadata = await query("thread/read", {"threadId": thread_id, "includeTurns": False})
        thread = metadata.get("thread")
        if not isinstance(thread, dict) or thread.get("id") != thread_id:
            raise ValueError("历史源线程不匹配。")
        revision = hashlib.sha256(
            json.dumps(
                [thread_id, thread.get("updatedAt"), thread.get("status")],
                sort_keys=True,
            ).encode()
        ).hexdigest()
        if request.revision is not None and request.revision != revision:
            raise AgentHistoryWindowStaleError("历史已变化。")
        position = (
            _Position.model_validate_json(request.cursor)
            if request.cursor
            else _Position(strategy=self._strategy)
        )
        if position.strategy != self._strategy:
            raise AgentHistoryWindowStaleError("上游分页能力已变化。")
        turns: list[JsonValue] = []
        count = 0
        seen: set[str] = set()

        async def restore_source_item(
            product: AppServerProductTimelineItem, params: dict[str, JsonValue]
        ) -> dict[str, JsonValue] | None:
            """仅对本机未保留的完整正文查源；精确版本证明不改变消息身份。"""
            descriptor = product.content
            if descriptor is None:
                return None
            source_params = dict(params)
            if self._strategy == "items_page":
                source_params.pop("itemsView", None)
                source_params.pop("cursor", None)
            else:
                source_params.pop("turnId", None)
                source_params["itemsView"] = "full"
            cursors: set[str] = set()
            while True:
                source = await query(
                    "thread/items/list" if self._strategy == "items_page" else "thread/turns/list",
                    source_params,
                )
                entries = source.get("data", [])
                if not isinstance(entries, list) or len(entries) > 1:
                    raise ValueError("正文源分页无效。")
                raw_items = []
                for entry in entries:
                    if isinstance(entry, dict):
                        raw_items.extend(
                            [entry.get("item")]
                            if self._strategy == "items_page"
                            else entry.get("items", [])
                        )
                for raw in raw_items:
                    if not isinstance(raw, dict):
                        continue
                    described = self._content.describe_item(
                        {**self._sanitize_source(thread_id, raw), "id": product.item_id},
                        workspace_key=workspace_key,
                        thread_id=thread_id,
                        expected_generation=generation,
                    )
                    candidate = described.get("contentDescriptor")
                    if (
                        isinstance(candidate, dict)
                        and candidate.get("revision") == descriptor.revision
                        and candidate.get("field") == descriptor.field
                    ):
                        return described
                following = source.get("nextCursor") if self._strategy == "items_page" else None
                if following is None:
                    return None
                if not isinstance(following, str) or following in cursors:
                    raise ValueError("正文源cursor循环。")
                cursors.add(following)
                source_params["cursor"] = following

        def build(next_position: _Position | None) -> AppServerThreadReadProductResult:
            if self._cache.invalidation_generation != generation:
                raise AgentHistoryWindowStaleError("读取期间历史已变化。")
            grouped: dict[str, dict[str, JsonValue]] = {}
            for selected in reversed(turns):
                if not isinstance(selected, dict):
                    continue
                identity = str(selected["id"])
                if identity not in grouped:
                    grouped[identity] = {**selected, "items": [], "productItems": []}
                grouped[identity]["items"].extend(selected["items"])
                grouped[identity]["productItems"].extend(selected.get("productItems", []))
            result = self._adapter.adapt_thread_read_result(
                {
                    **metadata,
                    "thread": {**thread, "turns": list(grouped.values())},
                    "historyWindow": AgentHistoryWindowResult(
                        revision=revision,
                        has_more=next_position is not None,
                        cursor=next_position.model_dump_json() if next_position else None,
                    ).model_dump(mode="json"),
                }
            )
            return self._sanitize(
                result.model_copy(
                    update={
                        "covered_item_ids": tuple(
                            item["item_id"]
                            for selected in turns
                            if isinstance(selected, dict)
                            for item in selected.get("productItems", [])
                        ),
                    }
                )
            )

        current_turn_cursor: str | None = None
        current_turn_page: dict[str, JsonValue] | None = None
        current_full_turn: dict[str, JsonValue] | None = None
        while True:
            params: dict[str, JsonValue] = {
                "threadId": thread_id,
                "limit": 1,
                "sortDirection": "desc",
                "itemsView": "notLoaded",
            }
            if position.cursor is not None:
                params["cursor"] = position.cursor
            if current_turn_page is None or current_turn_cursor != position.cursor:
                current_turn_page = await query("thread/turns/list", params)
                current_turn_cursor = position.cursor
                current_full_turn = None
            page = current_turn_page
            data, next_cursor = page.get("data"), page.get("nextCursor")
            if (
                not isinstance(data, list)
                or len(data) > 1
                or (next_cursor is not None and not isinstance(next_cursor, str))
            ):
                raise ValueError("上游没有遵守单项分页契约。")
            next_turn = (
                _Position(cursor=next_cursor, strategy=self._strategy) if next_cursor else None
            )
            if data:
                turn = data[0]
                if not isinstance(turn, dict) or not isinstance(turn.get("id"), str):
                    raise ValueError("上游turn无效。")
                turn_id = turn["id"]
                local = (
                    self._timeline_store.read_history_window(
                        thread_id,
                        turn_id,
                        offset=position.consumed,
                        limit=1,
                    )
                    if self._timeline_store
                    else None
                )
                if local is not None:
                    digest = local.revision
                    if position.digest is not None and position.digest != digest:
                        raise AgentHistoryWindowStaleError("本机历史已变化。")
                    if position.consumed > local.total_items:
                        raise AgentHistoryWindowStaleError("本机历史边界已变化。")
                    after = (
                        _Position(
                            cursor=position.cursor,
                            consumed=position.consumed + 1,
                            digest=digest,
                            strategy=self._strategy,
                        )
                        if position.consumed + 1 < local.total_items
                        else next_turn
                    )
                    selected = None
                    if local.items:
                        product = local.items[0]
                        if not request.item_ids or product.item_id in request.item_ids:
                            product = self._content.describe_product_item(
                                product,
                                workspace_key=workspace_key,
                                thread_id=thread_id,
                                expected_generation=generation,
                            )
                            restored = (
                                await restore_source_item(product, {**params, "turnId": turn_id})
                                if local.items[0].content is not None
                                else None
                            )
                            if restored is not None:
                                product = product.model_copy(
                                    update={
                                        "content": self._adapter.adapt_timeline_item(
                                            restored
                                        ).content
                                    }
                                )
                            selected = {
                                **turn,
                                "items": [],
                                "productItems": [product.model_dump(mode="json")],
                            }
                else:
                    source_params = dict(params)
                    if self._strategy == "items_page":
                        source_params.pop("itemsView")
                        source_params.pop("cursor", None)
                        source_params["turnId"] = turn_id
                        if position.item_cursor is not None:
                            source_params["cursor"] = position.item_cursor
                        source = await query("thread/items/list", source_params)
                        entries = source.get("data")
                        following = source.get("nextCursor")
                        if (
                            not isinstance(entries, list)
                            or len(entries) > 1
                            or (following is not None and not isinstance(following, str))
                        ):
                            raise ValueError("上游item分页无效。")
                        raw_items = [
                            entry.get("item") for entry in entries if isinstance(entry, dict)
                        ]
                        after = (
                            _Position(
                                cursor=position.cursor,
                                item_cursor=following,
                                strategy=self._strategy,
                            )
                            if following
                            else next_turn
                        )
                        index = 0
                    else:
                        source_params["itemsView"] = "full"
                        if current_full_turn is None:
                            current_full_turn = await query("thread/turns/list", source_params)
                        source = current_full_turn
                        entries = source.get("data")
                        if (
                            not isinstance(entries, list)
                            or len(entries) != 1
                            or not isinstance(entries[0], dict)
                            or entries[0].get("id") != turn_id
                            or not isinstance(entries[0].get("items"), list)
                        ):
                            raise AgentHistoryWindowStaleError("历史turn已变化。")
                        raw_items = list(reversed(entries[0]["items"]))
                        digest = hashlib.sha256(
                            json.dumps(raw_items, sort_keys=True, ensure_ascii=False).encode()
                        ).hexdigest()
                        if position.digest is not None and position.digest != digest:
                            raise AgentHistoryWindowStaleError("历史turn已变化。")
                        if position.consumed > len(raw_items):
                            raise AgentHistoryWindowStaleError("历史边界已变化。")
                        index = position.consumed
                        after = (
                            _Position(
                                cursor=position.cursor,
                                consumed=index + 1,
                                digest=digest,
                                strategy=self._strategy,
                            )
                            if index + 1 < len(raw_items)
                            else next_turn
                        )
                    selected = None
                    if index < len(raw_items):
                        raw_item = raw_items[index]
                        if not isinstance(raw_item, dict):
                            raise ValueError("上游item无效。")
                        if not request.item_ids or raw_item.get("id") in request.item_ids:
                            item = self._content.describe_item(
                                self._sanitize_source(thread_id, raw_item),
                                workspace_key=workspace_key,
                                thread_id=thread_id,
                                expected_generation=generation,
                            )
                            selected = {**turn, "items": [item]}
                if selected is not None:
                    turns.append(selected)
                    candidate = build(after)
                    if encoded_size(candidate) > max_bytes:
                        turns.pop()
                        if count == 0 or request.item_ids:
                            raise ContentReadError(ContentErrorCode.MESSAGE_TOO_LARGE)
                        return build(position)
                    count += 1
                    if count >= (len(request.item_ids) if request.item_ids else request.limit):
                        return candidate
            else:
                after = next_turn
            if after is None:
                result = build(None)
                if encoded_size(result) > max_bytes:
                    raise ContentReadError(ContentErrorCode.MESSAGE_TOO_LARGE)
                return result
            identity = after.model_dump_json()
            if identity in seen:
                raise ValueError("历史cursor循环。")
            seen.add(identity)
            position = after
