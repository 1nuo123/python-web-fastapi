"""连接内只读查询的有界并发生命周期；不参与副作用命令序列或持久恢复。"""

import asyncio
from collections.abc import Awaitable, Callable


class AgentQueryScheduler:
    def __init__(self) -> None:
        self._tasks: set[asyncio.Task[None]] = set()
        self._reserved_bytes = 0

    @property
    def active(self) -> bool:
        return bool(self._tasks)

    def submit(
        self,
        *,
        reserve_bytes: int,
        limit_bytes: int,
        operation: Callable[[], Awaitable[None]],
        on_failure: Callable[[], None],
    ) -> bool:
        if self._reserved_bytes + reserve_bytes > limit_bytes or len(self._tasks) >= 32:
            return False
        self._reserved_bytes += reserve_bytes

        async def run() -> None:
            try:
                await operation()
            except asyncio.CancelledError:
                raise
            except (ConnectionError, TimeoutError):
                pass
            except Exception:
                on_failure()

        task = asyncio.create_task(run())
        self._tasks.add(task)

        def finished(done: asyncio.Task[None]) -> None:
            self._reserved_bytes -= reserve_bytes
            self._tasks.discard(done)

        task.add_done_callback(finished)
        return True

    async def cancel_all(self) -> None:
        tasks = tuple(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.difference_update(tasks)
