"""Agent 进程内 thread/read 完整历史窗口缓存。"""

from __future__ import annotations

import json
import hashlib
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic
from typing import Final, cast

from pydantic import JsonValue
from src.core.codex_contract.agent_content_contract import (
    AgentContentReadRequest,
    ContentField,
    ContentReadError,
    ContentErrorCode,
    ReadableContentDescriptor,
    CONTENT_PREVIEW_CHARS,
)

DEFAULT_AGENT_THREAD_HISTORY_CACHE_TTL_SECONDS: Final = 5 * 60
DEFAULT_AGENT_THREAD_HISTORY_CACHE_MAX_BYTES: Final = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AgentThreadHistoryWindowCacheKey:
    """一个完整历史窗口的进程内定位键，不会写入日志或持久化介质。"""

    workspace_key: str
    thread_id: str
    cursor: str | None = None
    revision: str | None = None
    limit: int | None = None
    content_handle: str | None = None
    item_id: str | None = None
    field: ContentField | None = None


@dataclass(slots=True)
class _AgentThreadHistoryWindowCacheEntry:
    """缓存的序列化正文与其过期边界；字节串避免共享可变正文对象。"""

    payload: bytes = field(repr=False)
    expires_at_monotonic: float
    revision: str | None = None
    metadata_bytes: int = 0

    @property
    def size_bytes(self) -> int:
        """返回受全局软上限约束的序列化字节数。"""

        return sys.getsizeof(self.payload) + sys.getsizeof(self) + self.metadata_bytes


class AgentThreadHistoryWindowCache:
    """只在 Agent 进程存活期间保留完整 thread/read 响应的 TTL LRU 缓存。

    历史正文绝不进入数据库、磁盘、浏览器存储、诊断或日志。缓存以 JSON
    字节串保存并在读取时重新反序列化，避免调用方修改共享对象而污染后续响应。
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_AGENT_THREAD_HISTORY_CACHE_TTL_SECONDS,
        max_total_bytes: int = DEFAULT_AGENT_THREAD_HISTORY_CACHE_MAX_BYTES,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("历史窗口缓存 TTL 必须大于零。")
        if max_total_bytes <= 0:
            raise ValueError("历史窗口缓存字节上限必须大于零。")
        self._ttl_seconds = ttl_seconds
        self._max_total_bytes = max_total_bytes
        self._clock = clock
        self._entries: OrderedDict[
            AgentThreadHistoryWindowCacheKey,
            _AgentThreadHistoryWindowCacheEntry,
        ] = OrderedDict()
        self._total_bytes = 0
        self._invalidation_generation = 0

    @property
    def entry_count(self) -> int:
        """返回清理过期项后的窗口数量，供确定性测试验证容量边界。"""

        self._discard_expired()
        return len(self._entries)

    @property
    def total_bytes(self) -> int:
        """返回清理过期项后的受控正文缓存字节数。"""

        self._discard_expired()
        return self._total_bytes

    @property
    def invalidation_generation(self) -> int:
        """返回当前失效代次，供异步读取在写入前检测期间并发事件。"""

        return self._invalidation_generation

    def get(self, key: AgentThreadHistoryWindowCacheKey) -> JsonValue | None:
        """读取仍有效的窗口，并将命中项移动到 LRU 队尾。"""

        now = self._clock()
        self._discard_expired(now)
        entry = self._entries.pop(key, None)
        if entry is None:
            return None
        self._entries[key] = entry
        return cast(JsonValue, json.loads(entry.payload))

    def retain_content(
        self,
        *,
        workspace_key: str,
        thread_id: str,
        item_id: str,
        field: ContentField,
        text: str,
        expected_generation: int,
    ) -> ReadableContentDescriptor | None:
        """正文与历史窗口共用硬预算、TTL、LRU及线程失效代次。"""
        if expected_generation != self._invalidation_generation:
            return None
        self._discard_expired()
        payload = text.encode("utf-8")
        if len(payload) > self._max_total_bytes:
            return None
        revision = hashlib.sha256(payload).hexdigest()
        for existing, entry in self._entries.items():
            if (
                existing.workspace_key,
                existing.thread_id,
                existing.item_id,
                existing.field,
                entry.revision,
            ) == (workspace_key, thread_id, item_id, field, revision):
                return ReadableContentDescriptor(
                    field=field,
                    revision=revision,
                    total_bytes=len(payload),
                    preview=text[:CONTENT_PREVIEW_CHARS],
                    content_ref=existing.content_handle,
                    expires_at=datetime.now(UTC)
                    + timedelta(seconds=max(0, entry.expires_at_monotonic - self._clock())),
                )
        key = AgentThreadHistoryWindowCacheKey(
            workspace_key=workspace_key,
            thread_id=thread_id,
            item_id=item_id,
            field=field,
            content_handle=uuid4().hex,
        )
        entry = _AgentThreadHistoryWindowCacheEntry(
            payload=payload,
            expires_at_monotonic=self._clock() + self._ttl_seconds,
            revision=revision,
            metadata_bytes=self._key_bytes(key),
        )
        if entry.size_bytes > self._max_total_bytes:
            return None
        self._evict_for(payload_size=entry.size_bytes)
        self._entries[key] = entry
        self._total_bytes += entry.size_bytes
        return ReadableContentDescriptor(
            field=field,
            revision=revision,
            total_bytes=len(payload),
            preview=text[:CONTENT_PREVIEW_CHARS],
            content_ref=key.content_handle,
            expires_at=datetime.now(UTC) + timedelta(seconds=self._ttl_seconds),
        )

    def read_content(self, request: AgentContentReadRequest) -> memoryview:
        """仅返回受控缓存的只读视图，不复制正文、不刷新生存期。"""
        self._discard_expired()
        key = AgentThreadHistoryWindowCacheKey(
            workspace_key=request.workspace_key,
            thread_id=request.thread_id,
            item_id=request.item_id,
            field=request.field,
            content_handle=request.content_ref,
        )
        entry = self._entries.get(key)
        if entry is None:
            raise ContentReadError(ContentErrorCode.REFERENCE_EXPIRED)
        if entry.revision != request.revision:
            raise ContentReadError(ContentErrorCode.REVISION_STALE)
        self._entries.move_to_end(key)
        return memoryview(entry.payload)

    def store(self, key: AgentThreadHistoryWindowCacheKey, value: JsonValue) -> bool:
        """存入完整成功响应；超出总预算或无法序列化时不保留正文。"""

        self._discard_expired()
        try:
            payload = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError):
            self._remove(key)
            return False
        self._remove(key)
        if len(payload) > self._max_total_bytes:
            return False
        entry = _AgentThreadHistoryWindowCacheEntry(
            payload=payload,
            expires_at_monotonic=self._clock() + self._ttl_seconds,
            metadata_bytes=self._key_bytes(key),
        )
        if entry.size_bytes > self._max_total_bytes:
            return False
        self._evict_for(payload_size=entry.size_bytes)
        self._entries[key] = entry
        self._total_bytes += entry.size_bytes
        return True

    def store_if_current_generation(
        self,
        key: AgentThreadHistoryWindowCacheKey,
        value: JsonValue,
        *,
        expected_generation: int,
    ) -> bool:
        """仅当读取期间没有上游失效事件时写入，阻止乱序响应复活旧窗口。"""

        if expected_generation != self._invalidation_generation:
            return False
        return self.store(key, value)

    def invalidate(self, key: AgentThreadHistoryWindowCacheKey) -> None:
        """删除单个已知工作区会话窗口。"""

        self._invalidation_generation += 1
        for candidate in tuple(self._entries):
            if (
                candidate.workspace_key == key.workspace_key
                and candidate.thread_id == key.thread_id
            ):
                self._remove(candidate)

    def invalidate_thread(self, thread_id: str) -> None:
        """收到上游线程事件时删除所有同名工作区窗口，优先保证实时性。"""

        self._invalidation_generation += 1
        for key in tuple(self._entries):
            if key.thread_id == thread_id:
                self._remove(key)

    def clear(self) -> None:
        """释放全部仅内存正文，供 Agent 生命周期结束或显式失效时调用。"""

        self._invalidation_generation += 1
        self._entries.clear()
        self._total_bytes = 0

    def _discard_expired(self, now: float | None = None) -> None:
        """删除所有过期窗口；不能依赖 LRU 次序推断过期顺序。"""

        current = self._clock() if now is None else now
        for key, entry in tuple(self._entries.items()):
            if entry.expires_at_monotonic <= current:
                self._remove(key)

    @staticmethod
    def _key_bytes(key: AgentThreadHistoryWindowCacheKey) -> int:
        return (
            sys.getsizeof(key)
            + sum(sys.getsizeof(getattr(key, name)) for name in key.__slots__)
            + 128
        )

    def _evict_for(self, *, payload_size: int) -> None:
        """按最近最少使用顺序释放空间，使全局正文缓存不超过软上限。"""

        while self._entries and self._total_bytes + payload_size > self._max_total_bytes:
            _key, entry = self._entries.popitem(last=False)
            self._total_bytes -= entry.size_bytes

    def _remove(self, key: AgentThreadHistoryWindowCacheKey) -> None:
        """删除窗口并同步全局字节计数。"""

        entry = self._entries.pop(key, None)
        if entry is not None:
            self._total_bytes -= entry.size_bytes
