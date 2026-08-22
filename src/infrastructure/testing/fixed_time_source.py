"""可推进的固定时间源，仅供确定性测试和回放夹具使用。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class FixedTimeSource:
    """同时提供 wall-clock 与 monotonic 时间，禁止测试依赖系统时间。"""

    def __init__(self, initial: datetime | None = None) -> None:
        self._current = (initial or datetime(2026, 1, 1, tzinfo=UTC)).astimezone(UTC)
        self._monotonic = 0.0

    def now(self) -> datetime:
        """返回当前固定 UTC 时间。"""

        return self._current

    def monotonic(self) -> float:
        """返回可重复推进的单调时间。"""

        return self._monotonic

    def advance(self, seconds: float) -> None:
        """推进时间；负数会被拒绝以避免回放游标倒退。"""

        if seconds < 0:
            raise ValueError("固定时间源不允许倒退。")
        self._current += timedelta(seconds=seconds)
        self._monotonic += seconds
