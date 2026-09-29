"""统一 wakeup、rescan、错误隔离和 shutdown 的同步 Outbox runner。"""

from __future__ import annotations

import asyncio
import logging
import threading
from time import time
from typing import Generic, TypeVar

from src.core.outbox_contract.reliable_outbox_contract import (
    AsyncReliableOutboxAdapterPort,
    OutboxDeliveryOutcome,
    ReliableOutboxAdapterPort,
    ReliableOutboxRunResult,
)

OutboxRecord = TypeVar("OutboxRecord")
OUTBOX_FAILURE_REASON_MAX_LENGTH = 512


class ReliableOutboxRunner(Generic[OutboxRecord]):
    """单 writer 重扫 runner；业务状态语义全部由 adapter 表达。"""

    def __init__(
        self,
        *,
        adapter: ReliableOutboxAdapterPort[OutboxRecord],
        logger: logging.Logger,
        worker_name: str,
        interval_seconds: float,
        stale_seconds: int,
        batch_limit: int,
    ) -> None:
        self._adapter = adapter
        self._logger = logger
        self._worker_name = worker_name
        self._interval_seconds = interval_seconds
        self._stale_seconds = stale_seconds
        self._batch_limit = batch_limit
        self._run_lock = threading.Lock()
        self._wakeup = threading.Event()
        self._stop = threading.Event()
        self._worker: threading.Thread | None = None

    def run_once(
        self,
        *,
        limit: int,
        stale_before_epoch: int | None,
    ) -> ReliableOutboxRunResult:
        with self._run_lock:
            records = self._adapter.claim(
                limit=limit,
                stale_before_epoch=stale_before_epoch,
            )
            delivered = deferred = unknown = failed = permanently_failed = 0
            for record in records:
                try:
                    outcome = self._adapter.deliver(record)
                    if outcome == OutboxDeliveryOutcome.DELIVERED:
                        delivered += 1
                    elif outcome == OutboxDeliveryOutcome.DEFERRED:
                        deferred += 1
                    elif outcome == OutboxDeliveryOutcome.FAILED_PERMANENT:
                        permanently_failed += 1
                    else:
                        unknown += 1
                except Exception as exc:
                    self._adapter.record_failure(
                        record,
                        str(exc)[:OUTBOX_FAILURE_REASON_MAX_LENGTH],
                    )
                    failed += 1
            return ReliableOutboxRunResult(
                scanned_count=len(records),
                delivered_count=delivered,
                deferred_count=deferred,
                unknown_count=unknown,
                failed_count=failed,
                permanently_failed_count=permanently_failed,
            )

    def start(self) -> None:
        if self._worker is not None:
            return
        self._worker = threading.Thread(
            target=self._run,
            name=self._worker_name,
            daemon=True,
        )
        self._worker.start()

    def notify(self) -> None:
        """唤醒 runner 立即重扫。"""

        self._wakeup.set()

    def shutdown(self) -> None:
        self._stop.set()
        self._wakeup.set()
        if self._worker is not None:
            self._worker.join()
            self._worker = None

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wakeup.wait(self._interval_seconds)
            self._wakeup.clear()
            if self._stop.is_set():
                return
            try:
                self.run_once(
                    limit=self._batch_limit,
                    stale_before_epoch=int(time()) - self._stale_seconds,
                )
            except Exception:
                self._logger.exception("可靠Outbox后台重扫失败。")


class AsyncReliableOutboxRunner(Generic[OutboxRecord]):
    """异步 I/O adapter 复用的有界重扫与 shutdown runner。"""

    def __init__(
        self,
        *,
        adapter: AsyncReliableOutboxAdapterPort[OutboxRecord],
        logger: logging.Logger,
        interval_seconds: float,
        stale_seconds: int,
        batch_limit: int,
    ) -> None:
        self._adapter = adapter
        self._logger = logger
        self._interval_seconds = interval_seconds
        self._stale_seconds = stale_seconds
        self._batch_limit = batch_limit
        self._wakeup = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def run_once(
        self,
        *,
        limit: int,
        stale_before_epoch: int | None,
    ) -> ReliableOutboxRunResult:
        async with self._lock:
            records = await self._adapter.claim(
                limit=limit,
                stale_before_epoch=stale_before_epoch,
            )
            delivered = deferred = unknown = failed = permanently_failed = 0
            for record in records:
                try:
                    outcome = await self._adapter.deliver(record)
                    if outcome == OutboxDeliveryOutcome.DELIVERED:
                        delivered += 1
                    elif outcome == OutboxDeliveryOutcome.DEFERRED:
                        deferred += 1
                    elif outcome == OutboxDeliveryOutcome.FAILED_PERMANENT:
                        permanently_failed += 1
                    else:
                        unknown += 1
                except Exception as exc:
                    await self._adapter.record_failure(
                        record,
                        str(exc)[:OUTBOX_FAILURE_REASON_MAX_LENGTH],
                    )
                    failed += 1
            return ReliableOutboxRunResult(
                scanned_count=len(records),
                delivered_count=delivered,
                deferred_count=deferred,
                unknown_count=unknown,
                failed_count=failed,
                permanently_failed_count=permanently_failed,
            )

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run_loop())

    def notify(self) -> None:
        self._wakeup.set()

    async def shutdown(self) -> None:
        self._stop.set()
        self._wakeup.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def _run_loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._wakeup.wait(), timeout=self._interval_seconds)
            except TimeoutError:
                pass
            self._wakeup.clear()
            if self._stop.is_set():
                return
            try:
                await self.run_once(
                    limit=self._batch_limit,
                    stale_before_epoch=int(time()) - self._stale_seconds,
                )
            except Exception:
                self._logger.exception("异步可靠Outbox后台重扫失败。")
