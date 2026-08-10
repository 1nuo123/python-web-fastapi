"""应用 lifespan 流资源的延迟访问适配器。"""

from __future__ import annotations

from collections.abc import Callable

from src.application.ports.stream_state_store_port import StreamStateStorePort
from src.core.concurrency_contract.fenced_lease_contract import (
    FencedLease,
    FencedLeasePort,
    FencedLeaseRequest,
)
from src.core.stream_contract.cursor_stream_contract import (
    CursorStreamAppendRequest,
    CursorStreamAppendResult,
    CursorStreamReadRequest,
    CursorStreamWindow,
)
from src.core.stream_contract.stream_access_contract import (
    StreamAccessTicketRecord,
    StreamReplayEventRecord,
    StreamReplayWindow,
    StreamResumeRequest,
    StreamTicketConsumptionRequest,
    StreamTicketLookupRequest,
)
from src.infrastructure.streaming.stream_session_registry import (
    StreamSessionIdentity,
    StreamSessionLease,
)
from src.infrastructure.streaming.streaming_runtime_factory import StreamingRuntimeResourceSet


class DeferredStreamStateStore(StreamStateStorePort):
    """在请求执行时解析 lifespan 管理的状态存储。"""

    def __init__(self, *, resources_provider: Callable[[], StreamingRuntimeResourceSet]) -> None:
        """初始化共享资源提供者。"""

        self._resources_provider = resources_provider

    async def open(self) -> None:
        """共享状态存储由应用 lifespan 打开。"""

    async def close(self) -> None:
        """共享状态存储由应用 lifespan 关闭。"""

    async def store_ticket(self, record: StreamAccessTicketRecord) -> None:
        """保存票据摘要。"""

        await self._resources_provider().state_store.store_ticket(record)

    async def consume_ticket(self, request: StreamTicketConsumptionRequest) -> bool:
        """原子消费单次票据。"""

        return await self._resources_provider().state_store.consume_ticket(request)

    async def consume_ticket_record(
        self,
        request: StreamTicketLookupRequest,
    ) -> StreamAccessTicketRecord | None:
        """原子消费并返回服务端绑定票据记录。"""

        return await self._resources_provider().state_store.consume_ticket_record(request)

    async def append_event(
        self,
        record: StreamReplayEventRecord,
        *,
        max_events: int,
    ) -> None:
        """追加有限重放事件。"""

        await self._resources_provider().state_store.append_event(record, max_events=max_events)

    async def load_replay_window(self, request: StreamResumeRequest) -> StreamReplayWindow:
        """读取有限重放窗口。"""

        return await self._resources_provider().state_store.load_replay_window(request)

    async def purge_expired(self) -> int:
        """清理过期状态。"""

        return await self._resources_provider().state_store.purge_expired()

    async def append_cursor_event(
        self,
        request: CursorStreamAppendRequest,
    ) -> CursorStreamAppendResult:
        return await self._resources_provider().state_store.append_cursor_event(request)

    async def read_cursor_window(
        self,
        request: CursorStreamReadRequest,
    ) -> CursorStreamWindow:
        return await self._resources_provider().state_store.read_cursor_window(request)


class DeferredStreamSessionRegistry:
    """在请求执行时解析 lifespan 管理的会话注册表。"""

    def __init__(self, *, resources_provider: Callable[[], StreamingRuntimeResourceSet]) -> None:
        """初始化共享资源提供者。"""

        self._resources_provider = resources_provider

    async def acquire(
        self,
        *,
        identity: StreamSessionIdentity,
        cancel_callback: Callable[[], None] | None = None,
    ) -> StreamSessionLease:
        """从共享注册表申请会话租约。"""

        return await self._resources_provider().session_registry.acquire(
            identity=identity,
            cancel_callback=cancel_callback,
        )


class DeferredFencedLeaseStore(FencedLeasePort):
    """延迟解析 streaming resource set 中的唯一 fenced lease store。"""

    def __init__(self, *, resources_provider: Callable[[], StreamingRuntimeResourceSet]) -> None:
        self._resources_provider = resources_provider

    async def acquire(self, request: FencedLeaseRequest) -> FencedLease | None:
        return await self._resources_provider().fenced_lease_store.acquire(request)

    async def renew(self, lease: FencedLease, ttl_seconds: int) -> FencedLease | None:
        return await self._resources_provider().fenced_lease_store.renew(lease, ttl_seconds)

    async def release(self, lease: FencedLease) -> bool:
        return await self._resources_provider().fenced_lease_store.release(lease)

    async def read(self, resource_key: str) -> FencedLease | None:
        return await self._resources_provider().fenced_lease_store.read(resource_key)
