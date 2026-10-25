"""Agent运行期持有执行许可；连接重建不能延长已有许可。"""

import asyncio
import time
from collections.abc import Callable
from uuid import UUID, uuid4

from src.core.codex_contract.agent_connection_contract import AgentCommandAdmissionClosed
from src.core.codex_contract.agent_protocol_v2_contract import AgentExecutionLeaseV2Detail


class AgentExecutionLease:
    """唯一许可事实，使用请求时刻计算期限并保留跨连接代次。"""

    def __init__(
        self,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._monotonic = monotonic
        self._wall_clock = wall_clock
        self.last_response_at = monotonic()
        self.enabled = False
        self.generation = 0
        self.deadline = 0.0
        self.wall_deadline = 0.0
        self.ready = asyncio.Event()
        self._requests: dict[UUID, tuple[float, float]] = {}

    @property
    def valid(self) -> bool:
        return self.enabled and self.remaining_seconds > 0

    @property
    def remaining_seconds(self) -> float:
        return max(
            0.0, min(self.deadline - self._monotonic(), self.wall_deadline - self._wall_clock())
        )

    def begin_connection(self) -> None:
        self.ready.clear()
        self._requests.clear()

    def begin_request(self) -> UUID:
        now = self._monotonic()
        self._requests = {
            key: value for key, value in self._requests.items() if now - value[0] < 60
        }
        request = uuid4()
        self._requests[request] = (now, self._wall_clock())
        return request

    def accept(self, lease: AgentExecutionLeaseV2Detail) -> bool:
        if lease.generation < self.generation:
            return False
        requested = (
            self._requests.pop(lease.request_id, None) if lease.request_id is not None else None
        )
        if lease.enabled and requested is None:
            raise PermissionError("执行许可没有对应的当前连接请求。")
        # 同代迟到响应不能缩短较新的许可，也不能按接收时间延长许可。
        deadline = requested[0] + lease.valid_for_seconds if requested else 0.0
        if lease.enabled and lease.generation == self.generation and deadline < self.deadline:
            return False
        self.generation = lease.generation
        self.deadline = deadline
        self.wall_deadline = requested[1] + lease.valid_for_seconds if requested else 0.0
        self.enabled = lease.enabled
        self.last_response_at = self._monotonic()
        self.ready.set()
        return True

    def disable(self) -> None:
        self.enabled = False

    def require(self, generation: int | None) -> None:
        if not self.valid or generation != self.generation:
            raise AgentCommandAdmissionClosed("当前电脑的执行许可已失效。")
