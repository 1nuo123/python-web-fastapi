"""流式运行时资源工厂与停机编排。"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel
from redis.asyncio import Redis

from src.application.ports.stream_state_store_port import StreamStateStorePort
from src.application.streaming.stream_access_ticket_service import StreamAccessTicketService
from src.application.streaming.stream_execution_orchestrator import (
    StreamExecutionOrchestrator,
    StreamExecutionPolicy,
)
from src.core.concurrency_contract.fenced_lease_contract import FencedLeasePort
from src.core.stream_contract.stream_delivery_contract import StreamCollectionLimit
from src.core.stream_contract.stream_runtime_contract import (
    RedisStreamRuntimeDetail,
    StreamRuntimeEnvelope,
)
from src.infrastructure.concurrency.memory_fenced_lease_store import MemoryFencedLeaseStore
from src.infrastructure.concurrency.redis_fenced_lease_store import RedisFencedLeaseStore
from src.infrastructure.observability.prometheus_metrics_registry import PrometheusMetricsRegistry
from src.infrastructure.streaming.memory_stream_state_store import MemoryStreamStateStore
from src.infrastructure.streaming.redis_stream_state_store import RedisStreamStateStore
from src.infrastructure.streaming.sse_response_presenter import SseResponsePresenter
from src.infrastructure.streaming.stream_event_codec import StreamEventCodec
from src.infrastructure.streaming.stream_session_registry import (
    StreamSessionQuota,
    StreamSessionRegistry,
)
from src.infrastructure.streaming.websocket_connection_guard import WebSocketConnectionGuard
from src.infrastructure.streaming.websocket_session_handler import WebSocketSessionHandler


@dataclass(frozen=True, slots=True)
class StreamShutdownPolicy:
    """流运行时停机排空策略。"""

    grace_seconds: float


@dataclass(frozen=True, slots=True)
class StreamTransportRuntimeConfig:
    """SSE 与 WebSocket 适配器共享的强类型运行参数。"""

    sse_heartbeat_seconds: int
    sse_retry_milliseconds: int
    websocket_max_message_bytes: int
    replay_ttl_seconds: int
    replay_max_events: int


@dataclass(frozen=True, slots=True)
class StreamingOperationComponentSet:
    """单个生产流绑定复用的完整执行与传输组件。"""

    orchestrator: StreamExecutionOrchestrator[BaseModel, BaseModel]
    codec: StreamEventCodec[BaseModel]
    sse_presenter: SseResponsePresenter[BaseModel]
    websocket_guard: WebSocketConnectionGuard | None
    websocket_handler: WebSocketSessionHandler[BaseModel, BaseModel, BaseModel] | None


@dataclass(frozen=True, slots=True)
class StreamingRuntimeResourceSet:
    """统一流式运行时资源集。"""

    session_registry: StreamSessionRegistry
    state_store: StreamStateStorePort
    fenced_lease_store: FencedLeasePort
    ticket_service: StreamAccessTicketService
    shutdown_policy: StreamShutdownPolicy
    execution_policy: StreamExecutionPolicy
    collection_limit: StreamCollectionLimit
    transport_config: StreamTransportRuntimeConfig
    operation_components: tuple[StreamingOperationComponentSet, ...] = ()


class StreamingRuntimeFactory:
    """按强类型运行时配置构建流资源。"""

    async def build(
        self,
        runtime: StreamRuntimeEnvelope,
        *,
        metrics_registry: PrometheusMetricsRegistry | None = None,
        redis_client: Redis | None = None,
    ) -> StreamingRuntimeResourceSet:
        """构建并打开流运行时资源。

        :param runtime: 流运行时信封。
        :type runtime: StreamRuntimeEnvelope
        :returns: 已打开的流运行时资源集。
        :rtype: StreamingRuntimeResourceSet
        """

        detail = runtime.detail
        state_store: StreamStateStorePort
        if isinstance(detail, RedisStreamRuntimeDetail):
            if redis_client is None:
                raise RuntimeError("Redis流运行时缺少共享异步Redis client。")
            state_store = RedisStreamStateStore(
                client=redis_client,
                key_prefix=detail.redis_key_prefix,
            )
            fenced_lease_store: FencedLeasePort = RedisFencedLeaseStore(
                client=redis_client,
                key_prefix=detail.redis_key_prefix,
            )
        else:
            state_store = MemoryStreamStateStore()
            fenced_lease_store = MemoryFencedLeaseStore()
        await state_store.open()
        registry = StreamSessionRegistry(
            quota=StreamSessionQuota(
                maximum_total=detail.max_sessions,
                maximum_per_subject=detail.max_sessions_per_subject,
                maximum_per_ip=detail.max_sessions_per_ip,
                maximum_per_operation=detail.max_sessions_per_operation,
            ),
            metrics_registry=metrics_registry,
        )
        return StreamingRuntimeResourceSet(
            session_registry=registry,
            state_store=state_store,
            fenced_lease_store=fenced_lease_store,
            ticket_service=StreamAccessTicketService(
                state_store=state_store,
                ttl_seconds=detail.ticket_ttl_seconds,
            ),
            shutdown_policy=StreamShutdownPolicy(
                grace_seconds=detail.shutdown_grace_seconds,
            ),
            execution_policy=StreamExecutionPolicy(
                queue_capacity=detail.queue_capacity,
                send_timeout_seconds=detail.send_timeout_seconds,
                max_duration_seconds=detail.max_duration_seconds,
                max_event_bytes=detail.max_event_bytes,
            ),
            collection_limit=StreamCollectionLimit(
                max_events=detail.collection_max_events,
                max_bytes=detail.collection_max_bytes,
                timeout_seconds=detail.collection_timeout_seconds,
            ),
            transport_config=StreamTransportRuntimeConfig(
                sse_heartbeat_seconds=detail.sse_heartbeat_seconds,
                sse_retry_milliseconds=detail.sse_retry_milliseconds,
                websocket_max_message_bytes=detail.websocket_max_message_bytes,
                replay_ttl_seconds=detail.replay_ttl_seconds,
                replay_max_events=detail.replay_max_events,
            ),
        )

    async def shutdown(self, resources: StreamingRuntimeResourceSet) -> None:
        """按冻结顺序排空并关闭流资源。

        :param resources: 流运行时资源集。
        :type resources: StreamingRuntimeResourceSet
        """

        resources.session_registry.begin_draining()
        await resources.session_registry.notify_shutdown()
        await resources.session_registry.wait_until_empty(
            timeout_seconds=resources.shutdown_policy.grace_seconds,
        )
        await resources.session_registry.cancel_remaining(
            timeout_seconds=resources.shutdown_policy.grace_seconds,
        )
        await resources.state_store.close()
