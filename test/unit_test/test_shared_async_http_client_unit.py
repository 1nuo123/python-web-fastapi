"""
共享异步 HTTP 客户端单元测试模块。
"""

from __future__ import annotations

import pytest

from src.core.http_contract.outbound_http_client_contract import AsyncHttpClientDetail
from src.infrastructure.resource_slot.shared_async_http_client import SharedAsyncHttpClient


class TestSharedAsyncHttpClientUnit:
    """
    共享异步 HTTP 客户端单元测试集合。
    """

    @pytest.mark.anyio
    async def test_client_should_keep_runtime_limits_and_close(self) -> None:
        """
        验证共享异步 HTTP 客户端应保持连接限制并可关闭。
        """

        shared_client = SharedAsyncHttpClient(
            AsyncHttpClientDetail(
                timeout_seconds=5,
                max_connections=12,
                max_keepalive_connections=6,
            )
        )
        client = shared_client.get_client()
        try:
            assert client.timeout.connect == 5
            assert client.is_closed is False
        finally:
            await shared_client.close()

        assert client.is_closed is True

    def test_close_sync_should_release_async_client(self) -> None:
        """
        验证同步关闭入口应释放异步 HTTP 客户端。
        """

        shared_client = SharedAsyncHttpClient(
            AsyncHttpClientDetail(
                timeout_seconds=5,
                max_connections=8,
                max_keepalive_connections=4,
            )
        )
        client = shared_client.get_client()

        shared_client.close_sync()

        assert client.is_closed is True
