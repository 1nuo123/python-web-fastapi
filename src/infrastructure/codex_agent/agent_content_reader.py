"""受控缓存正文的单块 UTF-8 范围读取与原始条目摘要。"""

import hashlib
from collections.abc import Callable

from pydantic import JsonValue

from src.core.codex_contract.agent_content_contract import (
    AgentContentReadRequest,
    CodexContentChunk,
    ContentErrorCode,
    ContentField,
    ContentReadError,
    CONTENT_PREVIEW_CHARS,
    UnavailableContentDescriptor,
)
from src.infrastructure.codex_agent.agent_thread_history_window_cache import (
    AgentThreadHistoryWindowCache,
)
from src.core.codex_contract.app_server_product_contract import AppServerProductTimelineItem


class AgentContentReader:
    def __init__(self, cache: AgentThreadHistoryWindowCache) -> None:
        self._cache = cache

    def describe_product_item(
        self,
        item: AppServerProductTimelineItem,
        *,
        workspace_key: str,
        thread_id: str,
        expected_generation: int,
    ) -> AppServerProductTimelineItem:
        """已有时间线保留稳定身份；只在传输时生成正文描述。"""
        if item.content is not None:
            return item
        name = {"command": "output", "diff": "unified_diff", "plan": "explanation"}.get(
            item.kind, "text"
        )
        body = getattr(item, name, None)
        if not isinstance(body, str) or len(body) <= CONTENT_PREVIEW_CHARS:
            return item
        field = {"output": ContentField.OUTPUT, "unified_diff": ContentField.DIFF}.get(
            name, ContentField.TEXT
        )
        descriptor = self._cache.retain_content(
            workspace_key=workspace_key,
            thread_id=thread_id,
            item_id=item.item_id,
            field=field,
            text=body,
            expected_generation=expected_generation,
        ) or UnavailableContentDescriptor(
            field=field,
            revision=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            total_bytes=len(body.encode("utf-8")),
            preview=body[:CONTENT_PREVIEW_CHARS],
            unavailable_reason=ContentErrorCode.REFERENCE_EXPIRED,
        )
        update = {name: descriptor.preview, "content": descriptor}
        if item.kind == "diff":
            update["changes"] = tuple(
                change.model_copy(update={"diff": ""}) for change in item.changes
            )
        return item.model_copy(update=update)

    def describe_item(
        self,
        item: dict[str, JsonValue],
        *,
        workspace_key: str,
        thread_id: str,
        expected_generation: int,
    ) -> dict[str, JsonValue]:
        """只摘要可展开文本；命令、路径和审批参数不参与裁剪。"""
        item_type = item.get("type")
        field = ContentField.TEXT
        if item_type in {"agentMessage", "plan"}:
            body = item.get("text")
        elif item_type == "commandExecution":
            field, body = ContentField.OUTPUT, item.get("aggregatedOutput")
        elif item_type == "userMessage":
            parts = item.get("content")
            body = (
                "\n".join(
                    part["text"]
                    for part in parts
                    if isinstance(part, dict)
                    and part.get("type") == "text"
                    and isinstance(part.get("text"), str)
                )
                if isinstance(parts, list)
                else None
            )
        elif item_type == "reasoning":
            parts = item.get("summary")
            body = (
                "\n".join(part for part in parts if isinstance(part, str))
                if isinstance(parts, list)
                else None
            )
        elif item_type == "fileChange":
            field = ContentField.DIFF
            changes = item.get("changes")
            body = (
                "\n".join(
                    "### " + str(change.get("path", "")) + "\n" + str(change.get("diff", ""))
                    for change in changes
                    if isinstance(change, dict)
                )
                if isinstance(changes, list)
                else None
            )
        else:
            return item
        item_id = item.get("id")
        if (
            not isinstance(body, str)
            or len(body) <= CONTENT_PREVIEW_CHARS
            or not isinstance(item_id, str)
        ):
            return item
        descriptor = self._cache.retain_content(
            workspace_key=workspace_key,
            thread_id=thread_id,
            item_id=item_id,
            field=field,
            text=body,
            expected_generation=expected_generation,
        )
        if descriptor is None:
            descriptor = UnavailableContentDescriptor(
                field=field,
                revision=hashlib.sha256(body.encode("utf-8")).hexdigest(),
                total_bytes=len(body.encode("utf-8")),
                preview=body[:CONTENT_PREVIEW_CHARS],
                unavailable_reason=ContentErrorCode.REFERENCE_EXPIRED,
            )
        result = {**item, "contentDescriptor": descriptor.model_dump(mode="json")}
        if item_type == "userMessage":
            result["content"] = [{"type": "text", "text": descriptor.preview}]
        elif item_type == "reasoning":
            result["summary"] = [descriptor.preview]
        elif item_type == "fileChange":
            result["changes"] = [
                {**change, "diff": ""} for change in item["changes"] if isinstance(change, dict)
            ]
        else:
            result["aggregatedOutput" if item_type == "commandExecution" else "text"] = (
                descriptor.preview
            )
        return result

    def read(
        self,
        request: AgentContentReadRequest,
        *,
        max_message_bytes: int,
        encoded_size: Callable[[CodexContentChunk], int],
    ) -> CodexContentChunk:
        """按实际结果 envelope 缩块，返回值从不切断码点或停在原 offset。"""
        body = self._cache.read_content(request)
        offset = request.offset
        if offset > len(body) or (offset < len(body) and body[offset] & 0xC0 == 0x80):
            raise ContentReadError(ContentErrorCode.RANGE_INVALID)
        size = min(request.requested_bytes, len(body) - offset)
        while True:
            piece = bytes(body[offset : offset + size]).decode("utf-8", errors="ignore")
            next_offset = offset + len(piece.encode("utf-8"))
            chunk = CodexContentChunk(
                revision=request.revision,
                offset=offset,
                next_offset=next_offset,
                text=piece,
                eof=next_offset == len(body),
                total_bytes=len(body),
            )
            if encoded_size(chunk) <= max_message_bytes and (chunk.eof or next_offset > offset):
                return chunk
            if size <= 4:
                raise ContentReadError(ContentErrorCode.MESSAGE_TOO_LARGE)
            size //= 2
