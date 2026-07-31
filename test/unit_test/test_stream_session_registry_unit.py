"""流会话注册表单元测试。"""

from __future__ import annotations

import asyncio

import pytest

from src.core.stream_contract.stream_event_contract import StreamTransport
from src.infrastructure.streaming.stream_session_registry import (
    StreamSessionAdmissionError,
    StreamSessionIdentity,
    StreamSessionQuota,
    StreamSessionRegistry,
)


class TestStreamSessionRegistryUnit:
    """流会话注册表单元测试集合。"""

    @pytest.mark.asyncio
    async def test_acquire_and_release_should_track_active_sessions_idempotently(self) -> None:
        """验证租约释放幂等且活跃数归零。"""

        registry = self._build_registry()
        lease = await registry.acquire(identity=self._build_identity("subject-1"))

        assert registry.active_count() == 1
        await lease.release()
        await lease.release()

        assert registry.active_count() == 0

    @pytest.mark.asyncio
    async def test_acquire_when_subject_quota_exceeded_should_reject(self) -> None:
        """验证主体维度配额生效。"""

        registry = self._build_registry()
        lease = await registry.acquire(identity=self._build_identity("subject-1"))
        try:
            with pytest.raises(StreamSessionAdmissionError):
                await registry.acquire(identity=self._build_identity("subject-1"))
        finally:
            await lease.release()

    @pytest.mark.asyncio
    async def test_draining_should_reject_new_and_notify_existing_session(self) -> None:
        """验证排空状态拒绝新会话并通知存量租约。"""

        registry = self._build_registry()
        lease = await registry.acquire(identity=self._build_identity("subject-1"))
        registry.begin_draining()
        await registry.notify_shutdown()

        assert lease.shutdown_event.is_set() is True
        assert registry.is_draining() is True
        with pytest.raises(StreamSessionAdmissionError):
            await registry.acquire(identity=self._build_identity("subject-2"))
        await lease.release()
        assert await registry.wait_until_empty(timeout_seconds=0.1) is True

    @pytest.mark.asyncio
    async def test_cancel_remaining_should_call_cancel_callback(self) -> None:
        """验证强制排空调用取消回调并清理注册记录。"""

        cancelled: list[bool] = []
        registry = self._build_registry()
        lease = await registry.acquire(
            identity=self._build_identity("subject-1"),
        )

        def cancel_lease() -> None:
            cancelled.append(True)
            asyncio.create_task(lease.release())

        await lease.set_cancel_callback(cancel_lease)

        await registry.cancel_remaining()

        assert cancelled == [True]
        assert registry.active_count() == 0

    def _build_registry(self) -> StreamSessionRegistry:
        """构建小配额注册表。"""

        return StreamSessionRegistry(
            quota=StreamSessionQuota(
                maximum_total=2,
                maximum_per_subject=1,
                maximum_per_ip=2,
                maximum_per_operation=2,
            )
        )

    def _build_identity(self, subject_id: str) -> StreamSessionIdentity:
        """构建测试会话身份。"""

        return StreamSessionIdentity(
            subject_id=subject_id,
            client_ip="127.0.0.1",
            operation_name="test_operation",
            transport=StreamTransport.SSE,
        )
