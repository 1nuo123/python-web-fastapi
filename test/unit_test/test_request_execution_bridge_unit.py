"""
请求执行桥接器单元测试模块。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import pytest

from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_execution_contract import (
    DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
    RequestExecutionEnvelope,
    RequestExecutionHeader,
    RequestExecutionMode,
    ThreadpoolExecutionDetail,
)
from src.infrastructure.request_execution_bridge import RequestExecutionBridge

TEST_MAX_WORKERS = 1
TEST_MAX_PENDING_REQUESTS = 1
TEST_QUEUE_WAIT_TIMEOUT_SECONDS = 1
TEST_CAPACITY_OFFLOAD_TIMEOUT_SECONDS = 5
TEST_TASK_START_DELAY_SECONDS = 0.1


class TestRequestExecutionBridgeUnit:
    """
    请求执行桥接器单元测试集合。
    """

    @pytest.mark.anyio
    async def test_run_sync_when_threadpool_strategy_should_return_value(self) -> None:
        """
        验证桥接器在线程池策略下应返回同步执行结果。
        """

        bridge = RequestExecutionBridge(
            envelope=RequestExecutionEnvelope(
                envelope_kind="request_execution_envelope",
                schema_version="1.0",
                header=RequestExecutionHeader(
                    execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                    enabled=True,
                    mode=RequestExecutionMode.THREADPOOL,
                ),
                detail=ThreadpoolExecutionDetail(
                    offload_timeout_seconds=2,
                    max_workers=TEST_MAX_WORKERS,
                    max_pending_requests=TEST_MAX_PENDING_REQUESTS,
                    queue_wait_timeout_seconds=TEST_QUEUE_WAIT_TIMEOUT_SECONDS,
                ),
            ),
            logger=logging.getLogger("test_request_execution_bridge"),
        )
        try:
            result = await bridge.run_sync(
                execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                callable_object=lambda *, value: value,
                value="ok",
            )
        finally:
            bridge.close()

        assert result == "ok"

    @pytest.mark.anyio
    async def test_run_sync_when_execution_timeout_should_raise_http_fault(
        self,
    ) -> None:
        """
        验证桥接器当同步执行超时应抛出统一故障。
        """

        bridge = RequestExecutionBridge(
            envelope=RequestExecutionEnvelope(
                envelope_kind="request_execution_envelope",
                schema_version="1.0",
                header=RequestExecutionHeader(
                    execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                    enabled=True,
                    mode=RequestExecutionMode.THREADPOOL,
                ),
                detail=ThreadpoolExecutionDetail(
                    offload_timeout_seconds=1,
                    max_workers=TEST_MAX_WORKERS,
                    max_pending_requests=TEST_MAX_PENDING_REQUESTS,
                    queue_wait_timeout_seconds=TEST_QUEUE_WAIT_TIMEOUT_SECONDS,
                ),
            ),
            logger=logging.getLogger("test_request_execution_bridge"),
        )

        def slow_callable() -> str:
            time.sleep(2)
            return "never"

        try:
            with pytest.raises(HttpFaultException) as exc_info:
                await bridge.run_sync(
                    execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                    callable_object=slow_callable,
                )
        finally:
            bridge.close()

        assert exc_info.value.message == "请求执行超时。"
        assert exc_info.value.error_code == "system.request.timeout"

    @pytest.mark.anyio
    async def test_run_sync_when_native_async_target_should_await_result(self) -> None:
        """
        验证桥接器在原生异步模式下应等待异步结果。
        """

        bridge = RequestExecutionBridge(
            envelope=RequestExecutionEnvelope(
                envelope_kind="request_execution_envelope",
                schema_version="1.0",
                header=RequestExecutionHeader(
                    execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                    enabled=True,
                    mode=RequestExecutionMode.NATIVE_ASYNC,
                ),
                detail={
                    "kind": "native_async",
                    "schema_version": "1.0",
                    "propagate_cancellation": True,
                },
            ),
            logger=logging.getLogger("test_request_execution_bridge"),
        )

        async def async_callable(*, value: str) -> str:
            await asyncio.sleep(0)
            return value

        try:
            result = await bridge.run_sync(
                execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                callable_object=async_callable,
                value="async-ok",
            )
        finally:
            bridge.close()

        assert result == "async-ok"

    @pytest.mark.anyio
    async def test_run_sync_when_native_async_cancelled_should_propagate_and_release(self) -> None:
        """验证原生异步取消按契约传播且桥接器仍可确定关闭。"""

        started = asyncio.Event()
        bridge = RequestExecutionBridge(
            envelope=RequestExecutionEnvelope(
                envelope_kind="request_execution_envelope",
                schema_version="1.0",
                header=RequestExecutionHeader(
                    execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                    enabled=True,
                    mode=RequestExecutionMode.NATIVE_ASYNC,
                ),
                detail={
                    "kind": "native_async",
                    "schema_version": "1.0",
                    "propagate_cancellation": True,
                },
            ),
            logger=logging.getLogger("test_request_execution_cancellation"),
        )

        async def wait_for_cancellation() -> str:
            started.set()
            await asyncio.Event().wait()
            return "不可达"

        task = asyncio.create_task(
            bridge.run_sync(
                execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                callable_object=wait_for_cancellation,
            )
        )
        try:
            await started.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            bridge.close()

        assert task.cancelled()

    @pytest.mark.anyio
    async def test_run_sync_when_capacity_exhausted_should_reject_request(self) -> None:
        """验证线程池和等待队列均占满时应按契约拒绝新请求。"""

        release_event = threading.Event()
        bridge = RequestExecutionBridge(
            envelope=RequestExecutionEnvelope(
                envelope_kind="request_execution_envelope",
                schema_version="1.0",
                header=RequestExecutionHeader(
                    execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                    enabled=True,
                    mode=RequestExecutionMode.THREADPOOL,
                ),
                detail=ThreadpoolExecutionDetail(
                    offload_timeout_seconds=TEST_CAPACITY_OFFLOAD_TIMEOUT_SECONDS,
                    max_workers=TEST_MAX_WORKERS,
                    max_pending_requests=TEST_MAX_PENDING_REQUESTS,
                    queue_wait_timeout_seconds=TEST_QUEUE_WAIT_TIMEOUT_SECONDS,
                ),
            ),
            logger=logging.getLogger("test_request_execution_capacity"),
        )

        def blocked_callable() -> str:
            release_event.wait()
            return "released"

        first_task = asyncio.create_task(
            bridge.run_sync(
                execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                callable_object=blocked_callable,
            )
        )
        second_task = asyncio.create_task(
            bridge.run_sync(
                execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                callable_object=blocked_callable,
            )
        )
        try:
            await asyncio.sleep(TEST_TASK_START_DELAY_SECONDS)
            with pytest.raises(HttpFaultException) as exc_info:
                await bridge.run_sync(
                    execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                    callable_object=blocked_callable,
                )
            assert exc_info.value.error_code == "system.capacity.exhausted"
        finally:
            release_event.set()
            await asyncio.gather(first_task, second_task)
            bridge.close()

    @pytest.mark.anyio
    async def test_run_sync_when_native_async_mode_receives_sync_callable_should_not_execute_twice(
        self,
    ) -> None:
        """
        验证桥接器在原生异步模式下接收到同步函数时应只执行一次并退回线程池。
        """

        execution_count = 0
        bridge = RequestExecutionBridge(
            envelope=RequestExecutionEnvelope(
                envelope_kind="request_execution_envelope",
                schema_version="1.0",
                header=RequestExecutionHeader(
                    execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                    enabled=True,
                    mode=RequestExecutionMode.NATIVE_ASYNC,
                ),
                detail={
                    "kind": "native_async",
                    "schema_version": "1.0",
                    "propagate_cancellation": True,
                },
            ),
            logger=logging.getLogger("test_request_execution_bridge"),
        )

        def sync_callable(*, value: str) -> str:
            nonlocal execution_count
            execution_count += 1
            return value

        try:
            result = await bridge.run_sync(
                execution_name=DEFAULT_SYNC_REQUEST_EXECUTION_NAME,
                callable_object=sync_callable,
                value="sync-fallback",
            )
        finally:
            bridge.close()

        assert result == "sync-fallback"
        assert execution_count == 1
