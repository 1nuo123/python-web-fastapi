"""
请求执行桥接器基础设施模块。
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from http import HTTPStatus
from threading import Thread, current_thread
from typing import TypeVar, cast

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.http_contract.request_execution_contract import (
    NativeAsyncExecutionDetail,
    RequestExecutionEnvelope,
    RequestExecutionMode,
    ThreadpoolExecutionDetail,
)

REQUEST_EXECUTION_THREAD_NAME_PREFIX = "request-execution"
REQUEST_EXECUTION_MAX_WORKERS = 8
REQUEST_EXECUTION_MAX_PENDING_REQUESTS = 32
REQUEST_EXECUTION_DEFAULT_TIMEOUT_SECONDS = 15
REQUEST_EXECUTION_DEFAULT_QUEUE_WAIT_TIMEOUT_SECONDS = 2
REQUEST_EXECUTION_SYNC_FALLBACK_MESSAGE = "请求执行策略已退回线程池卸载。"
REQUEST_EXECUTION_TIMEOUT_MESSAGE = "请求执行超时。"
REQUEST_EXECUTION_NAME_MISMATCH_MESSAGE = "请求执行名称与配置不一致，已按线程池策略兜底执行。"
REQUEST_EXECUTION_DISABLED_MESSAGE = "请求执行策略已禁用，已按线程池策略兜底执行。"
REQUEST_EXECUTION_NATIVE_ASYNC_FALLBACK_MESSAGE = (
    "原生异步策略目标函数为同步函数，已退回线程池卸载。"
)
REQUEST_EXECUTION_CAPACITY_EXHAUSTED_MESSAGE = "请求执行容量已耗尽。"
T_RequestExecutionResult = TypeVar("T_RequestExecutionResult")


class RequestExecutionBridge:
    """
    请求执行桥接器。

    该桥接器用于在 ``async`` Web 路由与同步主干用例之间建立稳定边界。
    当运行时选择线程池策略时，同步调用会被卸载到专用线程池。
    当运行时选择原生异步策略时，仅对真正的协程目标执行直接等待。
    """

    def __init__(self, *, envelope: RequestExecutionEnvelope, logger: logging.Logger) -> None:
        """
        初始化请求执行桥接器。

        :param envelope: 已通过契约校验的请求执行策略配置。
        :type envelope: RequestExecutionEnvelope
        :param logger: 当前桥接器使用的日志记录器。
        :type logger: logging.Logger
        :returns: 无返回值。
        :rtype: None
        """

        self._envelope = envelope
        self._logger = logger
        detail = envelope.detail
        max_workers = (
            detail.max_workers
            if isinstance(detail, ThreadpoolExecutionDetail)
            else REQUEST_EXECUTION_MAX_WORKERS
        )
        max_pending_requests = (
            detail.max_pending_requests
            if isinstance(detail, ThreadpoolExecutionDetail)
            else REQUEST_EXECUTION_MAX_PENDING_REQUESTS
        )
        self._queue_wait_timeout_seconds = (
            detail.queue_wait_timeout_seconds
            if isinstance(detail, ThreadpoolExecutionDetail)
            else REQUEST_EXECUTION_DEFAULT_QUEUE_WAIT_TIMEOUT_SECONDS
        )
        self._capacity = asyncio.BoundedSemaphore(max_workers + max_pending_requests)
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=REQUEST_EXECUTION_THREAD_NAME_PREFIX,
        )

    async def run_sync(
        self,
        *,
        execution_name: str,
        callable_object: Callable[..., T_RequestExecutionResult],
        **kwargs: object,
    ) -> T_RequestExecutionResult:
        """
        执行同步主干调用。

        :param execution_name: 调用点声明的执行名称，用于和运行时配置做显式匹配。
        :type execution_name: str
        :param callable_object: 目标可调用对象，可以是同步函数，也可以是原生异步函数。
        :type callable_object: Callable[..., object]
        :param kwargs: 透传给目标对象的关键字参数。
        :type kwargs: object
        :returns: 返回目标调用的执行结果。
        :rtype: object
        :raises HttpFaultException: 当线程池卸载超时或运行时资源不可用时抛出。
        """

        if not self._envelope.header.enabled:
            self._logger.warning("%s %s", REQUEST_EXECUTION_DISABLED_MESSAGE, execution_name)
            return await self._run_with_default_threadpool(
                execution_name=execution_name,
                callable_object=callable_object,
                **kwargs,
            )
        if self._envelope.header.execution_name != execution_name:
            self._logger.warning(
                "%s %s -> %s",
                REQUEST_EXECUTION_NAME_MISMATCH_MESSAGE,
                self._envelope.header.execution_name,
                execution_name,
            )
            return await self._run_with_default_threadpool(
                execution_name=execution_name,
                callable_object=callable_object,
                **kwargs,
            )
        if self._envelope.header.mode == RequestExecutionMode.THREADPOOL:
            return await self._run_in_threadpool(
                execution_name=execution_name,
                callable_object=callable_object,
                **kwargs,
            )
        return await self._run_native_async(
            execution_name=execution_name,
            callable_object=callable_object,
            **kwargs,
        )

    async def _run_in_threadpool(
        self,
        *,
        execution_name: str,
        callable_object: Callable[..., T_RequestExecutionResult],
        **kwargs: object,
    ) -> T_RequestExecutionResult:
        """
        按线程池策略执行调用。

        :param execution_name: 调用点声明的执行名称。
        :type execution_name: str
        :param callable_object: 目标同步可调用对象。
        :type callable_object: Callable[..., object]
        :param kwargs: 透传给目标对象的关键字参数。
        :type kwargs: object
        :returns: 返回目标调用的执行结果。
        :rtype: object
        :raises HttpFaultException: 当线程池卸载超时或底层资源异常时抛出。
        """

        detail = self._envelope.detail
        if not isinstance(detail, ThreadpoolExecutionDetail):
            self._logger.warning("%s %s", REQUEST_EXECUTION_SYNC_FALLBACK_MESSAGE, execution_name)
            return await self._run_with_default_threadpool(
                execution_name=execution_name,
                callable_object=callable_object,
                **kwargs,
            )
        self._logger.debug("开始线程池卸载：%s", execution_name)
        return await self._run_in_executor(
            execution_name=execution_name,
            callable_object=callable_object,
            timeout_seconds=detail.offload_timeout_seconds,
            **kwargs,
        )

    async def _run_with_default_threadpool(
        self,
        *,
        execution_name: str,
        callable_object: Callable[..., T_RequestExecutionResult],
        **kwargs: object,
    ) -> T_RequestExecutionResult:
        """
        使用默认线程池策略兜底执行。

        :param execution_name: 调用点声明的执行名称。
        :type execution_name: str
        :param callable_object: 目标同步可调用对象。
        :type callable_object: Callable[..., object]
        :param kwargs: 透传给目标对象的关键字参数。
        :type kwargs: object
        :returns: 返回目标调用的执行结果。
        :rtype: object
        :raises HttpFaultException: 当默认线程池执行超时或底层资源异常时抛出。
        """

        return await self._run_in_executor(
            execution_name=execution_name,
            callable_object=callable_object,
            timeout_seconds=REQUEST_EXECUTION_DEFAULT_TIMEOUT_SECONDS,
            **kwargs,
        )

    async def _run_in_executor(
        self,
        *,
        execution_name: str,
        callable_object: Callable[..., T_RequestExecutionResult],
        timeout_seconds: int,
        **kwargs: object,
    ) -> T_RequestExecutionResult:
        """
        在线程池执行器中运行目标调用。

        :param execution_name: 调用点声明的执行名称。
        :type execution_name: str
        :param callable_object: 目标同步可调用对象。
        :type callable_object: Callable[..., object]
        :param timeout_seconds: 当前调用允许的最长等待秒数。
        :type timeout_seconds: int
        :param kwargs: 透传给目标对象的关键字参数。
        :type kwargs: object
        :returns: 返回目标调用的执行结果。
        :rtype: object
        :raises HttpFaultException: 当执行超时被转换为统一 HTTP 故障时抛出。
        """

        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(
                self._capacity.acquire(),
                timeout=self._queue_wait_timeout_seconds,
            )
        except TimeoutError as exc:
            self._logger.warning("请求执行容量耗尽：%s", execution_name)
            raise HttpFaultException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                error_code=CoreErrorCode.CAPACITY_EXHAUSTED,
                message=REQUEST_EXECUTION_CAPACITY_EXHAUSTED_MESSAGE,
                detail=execution_name,
            ) from exc
        try:
            executor_future = loop.run_in_executor(
                self._executor,
                partial(callable_object, **kwargs),
            )
        except BaseException:
            self._capacity.release()
            raise
        executor_future.add_done_callback(lambda completed_future: self._capacity.release())
        try:
            return await asyncio.wait_for(
                asyncio.shield(executor_future),
                timeout=timeout_seconds,
            )
        except TimeoutError as exc:
            self._logger.error("请求执行超时：%s", execution_name)
            raise HttpFaultException(
                status_code=HTTPStatus.GATEWAY_TIMEOUT,
                error_code=CoreErrorCode.REQUEST_TIMEOUT,
                message=REQUEST_EXECUTION_TIMEOUT_MESSAGE,
                detail=execution_name,
            ) from exc

    async def _run_native_async(
        self,
        *,
        execution_name: str,
        callable_object: Callable[..., T_RequestExecutionResult],
        **kwargs: object,
    ) -> T_RequestExecutionResult:
        """
        执行原生异步调用。

        :param execution_name: 调用点声明的执行名称。
        :type execution_name: str
        :param callable_object: 目标可调用对象，预期应返回 awaitable。
        :type callable_object: Callable[..., object]
        :param kwargs: 透传给目标对象的关键字参数。
        :type kwargs: object
        :returns: 返回目标调用的执行结果。
        :rtype: object
        :raises HttpFaultException: 当后续兜底线程池执行超时或底层资源异常时抛出。
        """

        detail = self._envelope.detail
        if isinstance(detail, NativeAsyncExecutionDetail):
            if inspect.iscoroutinefunction(callable_object) or inspect.iscoroutinefunction(
                getattr(callable_object, "__call__", None)
            ):
                result = cast(
                    Awaitable[T_RequestExecutionResult],
                    callable_object(**kwargs),
                )
                self._logger.debug("开始原生异步调用：%s", execution_name)
                if detail.propagate_cancellation:
                    return await result
                return await asyncio.shield(result)
        self._logger.warning(REQUEST_EXECUTION_NATIVE_ASYNC_FALLBACK_MESSAGE)
        return await self._run_with_default_threadpool(
            execution_name=execution_name,
            callable_object=callable_object,
            **kwargs,
        )

    def close(self) -> None:
        """
        关闭执行桥接器。

        :returns: 无返回值。
        :rtype: None
        """

        self._executor.shutdown(
            wait=not self._is_current_executor_worker(),
            cancel_futures=True,
        )

    def _is_current_executor_worker(self) -> bool:
        """
        判断当前线程是否属于本执行桥接器的线程池。

        :returns: 当前线程属于本执行桥接器线程池时返回 ``True``。
        :rtype: bool
        """

        worker_threads = cast(set[Thread], getattr(self._executor, "_threads", set()))
        return current_thread() in worker_threads
