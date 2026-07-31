"""进程内流会话配额与排空注册表。"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from time import perf_counter
from typing import Protocol

from src.core.stream_contract.stream_event_contract import StreamCloseReason, StreamTransport
from src.infrastructure.observability.prometheus_metrics_registry import (
    PrometheusMetricsRegistry,
    StreamMetricOutcome,
    StreamSessionMetric,
)

STREAM_REGISTRY_DRAINING_MESSAGE = "流会话注册表正在排空。"
STREAM_REGISTRY_CAPACITY_MESSAGE = "流会话连接配额已耗尽。"
STREAM_FORCE_CANCEL_WAIT_SECONDS = 1.0


class StreamSessionAdmissionReason(StrEnum):
    """流会话申请拒绝原因。"""

    DRAINING = "draining"
    CAPACITY_EXHAUSTED = "capacity_exhausted"


class StreamSessionAdmissionError(RuntimeError):
    """流会话申请被稳定策略拒绝。"""

    def __init__(self, *, reason: StreamSessionAdmissionReason, message: str) -> None:
        """初始化带封闭原因的会话申请异常。"""

        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class StreamSessionQuota:
    """四级流会话配额。"""

    maximum_total: int
    maximum_per_subject: int
    maximum_per_ip: int
    maximum_per_operation: int


@dataclass(frozen=True, slots=True)
class StreamSessionIdentity:
    """流会话配额维度标识。"""

    subject_id: str
    client_ip: str
    operation_name: str
    transport: StreamTransport


@dataclass(slots=True)
class StreamSessionEntry:
    """注册表内部会话记录。"""

    session_id: str
    identity: StreamSessionIdentity
    shutdown_event: asyncio.Event
    cancel_callback: Callable[[], None] | None
    started_at: float


class StreamSessionLease:
    """可幂等释放的流会话租约。"""

    def __init__(self, *, registry: StreamSessionRegistry, entry: StreamSessionEntry) -> None:
        """初始化租约。"""

        self._registry = registry
        self._entry = entry
        self._released = False

    @property
    def session_id(self) -> str:
        """读取会话标识。"""

        return self._entry.session_id

    @property
    def shutdown_event(self) -> asyncio.Event:
        """读取服务停机通知事件。"""

        return self._entry.shutdown_event

    async def release(
        self,
        reason: StreamCloseReason = StreamCloseReason.COMPLETED,
    ) -> None:
        """幂等释放租约。"""

        if self._released:
            return
        self._released = True
        await self._registry.release(self._entry.session_id, reason=reason)

    async def set_cancel_callback(self, callback: Callable[[], None]) -> None:
        """登记强制排空时调用的真实取消回调。"""

        await self._registry.set_cancel_callback(self._entry.session_id, callback)

    async def __aenter__(self) -> StreamSessionLease:
        """进入租约上下文。"""

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool:
        """退出租约上下文并释放配额。"""

        await self.release()
        return False


class StreamSessionRegistryPort(Protocol):
    """传输适配器所需的最小会话注册表端口。"""

    async def acquire(
        self,
        *,
        identity: StreamSessionIdentity,
        cancel_callback: Callable[[], None] | None = None,
    ) -> StreamSessionLease:
        """申请流会话租约。"""

        ...


class StreamSessionRegistry:
    """执行全局、主体、IP、操作四级配额的会话注册表。"""

    def __init__(
        self,
        *,
        quota: StreamSessionQuota,
        metrics_registry: PrometheusMetricsRegistry | None = None,
    ) -> None:
        """初始化会话注册表。"""

        self._quota = quota
        self._entries: dict[str, StreamSessionEntry] = {}
        self._lock = asyncio.Lock()
        self._empty_condition = asyncio.Condition(self._lock)
        self._draining = False
        self._metrics_registry = metrics_registry

    async def acquire(
        self,
        *,
        identity: StreamSessionIdentity,
        cancel_callback: Callable[[], None] | None = None,
    ) -> StreamSessionLease:
        """校验配额并申请会话租约。

        :param identity: 会话配额维度。
        :type identity: StreamSessionIdentity
        :param cancel_callback: 强制排空时调用的取消回调。
        :type cancel_callback: Callable[[], None] | None
        :returns: 会话租约。
        :rtype: StreamSessionLease
        :raises RuntimeError: 注册表排空或配额耗尽时抛出。
        """

        async with self._lock:
            if self._draining:
                raise StreamSessionAdmissionError(
                    reason=StreamSessionAdmissionReason.DRAINING,
                    message=STREAM_REGISTRY_DRAINING_MESSAGE,
                )
            if self._would_exceed_quota(identity):
                raise StreamSessionAdmissionError(
                    reason=StreamSessionAdmissionReason.CAPACITY_EXHAUSTED,
                    message=STREAM_REGISTRY_CAPACITY_MESSAGE,
                )
            entry = StreamSessionEntry(
                session_id=str(uuid.uuid4()),
                identity=identity,
                shutdown_event=asyncio.Event(),
                cancel_callback=cancel_callback,
                started_at=perf_counter(),
            )
            self._entries[entry.session_id] = entry
            self._set_active_metric(identity.transport)
            return StreamSessionLease(registry=self, entry=entry)

    async def set_cancel_callback(
        self,
        session_id: str,
        callback: Callable[[], None],
    ) -> None:
        """为仍存活的会话登记强制取消回调。"""

        async with self._lock:
            entry = self._entries.get(session_id)
            if entry is not None:
                entry.cancel_callback = callback

    async def release(
        self,
        session_id: str,
        *,
        reason: StreamCloseReason = StreamCloseReason.COMPLETED,
    ) -> None:
        """幂等释放指定会话。

        :param session_id: 会话标识。
        :type session_id: str
        """

        async with self._empty_condition:
            entry = self._entries.pop(session_id, None)
            if entry is not None and self._metrics_registry is not None:
                self._metrics_registry.record_stream_session(
                    StreamSessionMetric(
                        transport=entry.identity.transport,
                        outcome=self._resolve_metric_outcome(reason),
                        reason=reason,
                        duration_seconds=perf_counter() - entry.started_at,
                    )
                )
                self._set_active_metric(entry.identity.transport)
            if not self._entries:
                self._empty_condition.notify_all()

    def begin_draining(self) -> None:
        """标记排空并拒绝新会话。"""

        self._draining = True

    async def notify_shutdown(self) -> None:
        """通知全部存量会话服务即将停机。"""

        async with self._lock:
            for entry in self._entries.values():
                entry.shutdown_event.set()

    async def wait_until_empty(self, *, timeout_seconds: float) -> bool:
        """等待全部会话释放。

        :param timeout_seconds: 最大等待秒数。
        :type timeout_seconds: float
        :returns: 排空成功返回 ``True``。
        :rtype: bool
        """

        async with self._empty_condition:
            if not self._entries:
                return True
            try:
                await asyncio.wait_for(
                    self._empty_condition.wait_for(lambda: not self._entries),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                return False
            return True

    async def cancel_remaining(
        self,
        *,
        timeout_seconds: float = STREAM_FORCE_CANCEL_WAIT_SECONDS,
    ) -> None:
        """强制取消仍存活的会话并释放注册记录。"""

        async with self._lock:
            entries = tuple(self._entries.values())
        for entry in entries:
            if entry.cancel_callback is not None:
                entry.cancel_callback()
        await self.wait_until_empty(timeout_seconds=timeout_seconds)
        async with self._lock:
            remaining_entries = tuple(self._entries.values())
            self._entries.clear()
        for entry in remaining_entries:
            if self._metrics_registry is not None:
                self._metrics_registry.record_stream_session(
                    StreamSessionMetric(
                        transport=entry.identity.transport,
                        outcome=StreamMetricOutcome.FAILED,
                        reason=StreamCloseReason.SERVICE_SHUTDOWN,
                        duration_seconds=perf_counter() - entry.started_at,
                    )
                )
                self._set_active_metric(entry.identity.transport)
        async with self._empty_condition:
            self._empty_condition.notify_all()

    def active_count(self) -> int:
        """读取当前活跃会话数。"""

        return len(self._entries)

    def is_draining(self) -> bool:
        """读取排空状态。"""

        return self._draining

    def _would_exceed_quota(self, identity: StreamSessionIdentity) -> bool:
        """判断申请是否超过任一配额。"""

        entries = tuple(self._entries.values())
        return (
            len(entries) >= self._quota.maximum_total
            or sum(entry.identity.subject_id == identity.subject_id for entry in entries)
            >= self._quota.maximum_per_subject
            or sum(entry.identity.client_ip == identity.client_ip for entry in entries)
            >= self._quota.maximum_per_ip
            or sum(entry.identity.operation_name == identity.operation_name for entry in entries)
            >= self._quota.maximum_per_operation
        )

    def _set_active_metric(self, transport: StreamTransport) -> None:
        """刷新指定传输的当前活跃会话数。"""

        if self._metrics_registry is None:
            return
        count = sum(entry.identity.transport is transport for entry in self._entries.values())
        self._metrics_registry.set_stream_active_sessions(transport=transport, count=count)

    def _resolve_metric_outcome(self, reason: StreamCloseReason) -> StreamMetricOutcome:
        """把终止原因归一化为低基数会话结果。"""

        if reason is StreamCloseReason.COMPLETED:
            return StreamMetricOutcome.SUCCESS
        if reason is StreamCloseReason.CLIENT_DISCONNECTED:
            return StreamMetricOutcome.DISCONNECTED
        if reason in {
            StreamCloseReason.CLIENT_CANCELLED,
            StreamCloseReason.POLICY_REJECTED,
            StreamCloseReason.SLOW_CONSUMER,
        }:
            return StreamMetricOutcome.REJECTED
        return StreamMetricOutcome.FAILED
