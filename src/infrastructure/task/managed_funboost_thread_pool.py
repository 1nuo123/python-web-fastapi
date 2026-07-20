"""可显式关闭的 Funboost 线程池适配器。"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import ParamSpec, TypeVar

from funboost.concurrent_pool import FunboostBaseConcurrentPool

FUNBOOST_WORKER_THREAD_PREFIX = "funboost-worker"

_P = ParamSpec("_P")
_R = TypeVar("_R")


class ManagedFunboostThreadPool(FunboostBaseConcurrentPool):
    """使用标准线程池承载任务，并提供确定性的关闭语义。"""

    def __init__(self, *, max_workers: int) -> None:
        """
        初始化线程池。

        :param max_workers: 最大并发线程数。
        :type max_workers: int
        """

        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix=FUNBOOST_WORKER_THREAD_PREFIX,
        )

    def submit(
        self,
        function: Callable[_P, _R],
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> Future[_R]:
        """提交任务到受管线程池。"""

        return self._executor.submit(function, *args, **kwargs)

    def shutdown(self) -> None:
        """等待在途任务结束并取消尚未开始的任务。"""

        self._executor.shutdown(wait=True, cancel_futures=True)
