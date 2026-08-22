"""Codex 历史分页的签名游标与稳定窗口计算。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.core.codex_contract.thread_contract import (
    CODEX_HISTORY_REVISION_LENGTH,
    CodexThreadHistoryPage,
    CodexTimelineItemEnvelope,
)

HISTORY_CURSOR_SCHEMA_VERSION = "1"
HISTORY_CURSOR_HMAC_DIGEST = hashlib.sha256


class CodexHistoryCursorStaleError(ValueError):
    """游标已过期、被篡改或不再匹配当前历史窗口。"""


class CodexHistoryCursorClaims(BaseModel):
    """签名游标的最小可验证声明，不包含任何会话正文。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(default=HISTORY_CURSOR_SCHEMA_VERSION, pattern=r"^1$")
    owner_subject_id: str = Field(min_length=1, max_length=128)
    host_id: UUID
    upstream_thread_id: str = Field(min_length=1, max_length=256)
    history_revision: str = Field(
        min_length=CODEX_HISTORY_REVISION_LENGTH,
        max_length=CODEX_HISTORY_REVISION_LENGTH,
        pattern=r"^[0-9a-f]{64}$",
    )
    boundary_item_id: str = Field(min_length=1, max_length=256)
    expires_at_epoch_seconds: int = Field(ge=0)


class SignedCodexHistoryCursorCodec:
    """使用域隔离 HMAC 生成并验证短期历史游标。"""

    def __init__(
        self,
        *,
        signing_key: bytes,
        ttl_seconds: int,
        clock: Callable[[], datetime],
    ) -> None:
        if len(signing_key) < 32:
            raise ValueError("历史游标签名密钥至少需要32字节。")
        if ttl_seconds <= 0:
            raise ValueError("历史游标有效期必须大于零。")
        self._signing_key = signing_key
        self._ttl_seconds = ttl_seconds
        self._clock = clock

    def encode(
        self,
        *,
        owner_subject_id: str,
        host_id: UUID,
        upstream_thread_id: str,
        history_revision: str,
        boundary_item_id: str,
    ) -> str:
        """签发绑定当前历史版本和分页边界的游标。"""

        expires_at = self._now().timestamp() + self._ttl_seconds
        claims = CodexHistoryCursorClaims(
            owner_subject_id=owner_subject_id,
            host_id=host_id,
            upstream_thread_id=upstream_thread_id,
            history_revision=history_revision,
            boundary_item_id=boundary_item_id,
            expires_at_epoch_seconds=int(expires_at),
        )
        payload = json.dumps(
            claims.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        signature = hmac.new(self._signing_key, payload, HISTORY_CURSOR_HMAC_DIGEST).digest()
        return f"{self._encode_segment(payload)}.{self._encode_segment(signature)}"

    def decode(self, cursor: str) -> CodexHistoryCursorClaims:
        """验证签名和过期时间；所有失败统一收敛为 stale 语义。"""

        try:
            encoded_payload, encoded_signature = cursor.split(".", maxsplit=1)
            payload = self._decode_segment(encoded_payload)
            supplied_signature = self._decode_segment(encoded_signature)
            expected_signature = hmac.new(
                self._signing_key,
                payload,
                HISTORY_CURSOR_HMAC_DIGEST,
            ).digest()
            if not hmac.compare_digest(supplied_signature, expected_signature):
                raise CodexHistoryCursorStaleError
            claims = CodexHistoryCursorClaims.model_validate_json(payload)
            if claims.expires_at_epoch_seconds <= int(self._now().timestamp()):
                raise CodexHistoryCursorStaleError
            return claims
        except (
            ValueError,
            UnicodeDecodeError,
            binascii.Error,
            ValidationError,
            CodexHistoryCursorStaleError,
        ) as exc:
            raise CodexHistoryCursorStaleError("Codex历史游标已失效。") from exc

    @staticmethod
    def _encode_segment(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_segment(value: str) -> bytes:
        padding = "=" * (-len(value) % 4)
        return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))

    def _now(self) -> datetime:
        """归一化测试时钟，避免 naive 时间破坏过期判断。"""

        now = self._clock()
        return now if now.tzinfo is not None else now.replace(tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CodexHistoryPageResolver:
    """以 item ID 为边界计算 newest-first 请求对应的历史页。"""

    cursor_codec: SignedCodexHistoryCursorCodec

    def build_page(
        self,
        *,
        owner_subject_id: str,
        host_id: UUID,
        upstream_thread_id: str,
        items: list[CodexTimelineItemEnvelope],
        before_cursor: str | None,
        limit: int,
    ) -> CodexThreadHistoryPage:
        """返回一页历史和供下一次向前请求使用的稳定边界。"""

        history_revision = self._build_history_revision(items)
        page_end = len(items)
        if before_cursor is not None:
            claims = self.cursor_codec.decode(before_cursor)
            self._validate_claims(
                claims,
                owner_subject_id=owner_subject_id,
                host_id=host_id,
                upstream_thread_id=upstream_thread_id,
                history_revision=history_revision,
            )
            item_positions = {item.header.item_id: index for index, item in enumerate(items)}
            page_end = item_positions.get(claims.boundary_item_id, -1)
            if page_end < 0:
                raise CodexHistoryCursorStaleError("Codex历史边界已不存在。")
        page_start = max(0, page_end - limit)
        page_items = items[page_start:page_end]
        has_more = page_start > 0
        next_before_cursor = (
            self.cursor_codec.encode(
                owner_subject_id=owner_subject_id,
                host_id=host_id,
                upstream_thread_id=upstream_thread_id,
                history_revision=history_revision,
                boundary_item_id=page_items[0].header.item_id,
            )
            if has_more and page_items
            else None
        )
        return CodexThreadHistoryPage(
            items=page_items,
            before_cursor=next_before_cursor,
            has_more=has_more,
            history_revision=history_revision,
        )

    @staticmethod
    def _build_history_revision(items: list[CodexTimelineItemEnvelope]) -> str:
        """仅用稳定标识和状态计算版本，避免把正文放入游标或日志。"""

        identities = "\n".join(
            f"{item.header.item_id}:{item.header.turn_id or ''}:{item.header.status.value}"
            for item in items
        )
        return hashlib.sha256(identities.encode("utf-8")).hexdigest()

    @staticmethod
    def _validate_claims(
        claims: CodexHistoryCursorClaims,
        *,
        owner_subject_id: str,
        host_id: UUID,
        upstream_thread_id: str,
        history_revision: str,
    ) -> None:
        """拒绝跨用户、主机、线程或历史版本复用的有效签名游标。"""

        if (
            claims.owner_subject_id != owner_subject_id
            or claims.host_id != host_id
            or claims.upstream_thread_id != upstream_thread_id
            or claims.history_revision != history_revision
        ):
            raise CodexHistoryCursorStaleError("Codex历史游标不属于当前读取范围。")
