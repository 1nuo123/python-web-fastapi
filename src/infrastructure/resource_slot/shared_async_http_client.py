"""
共享异步HTTP客户端基础设施模块。
"""

from __future__ import annotations

import ssl
from threading import Thread

import anyio
import httpx

from src.core.http_contract.outbound_http_client_contract import AsyncHttpClientDetail
from src.infrastructure.security.outbound_url_safety_httpx_hook import (
    AsyncOutboundUrlSafetyHook,
)
from src.infrastructure.security.outbound_url_safety_transport import (
    OutboundUrlSafetyAsyncHttpTransport,
)


class SharedAsyncHttpClient:
    """
    共享异步HTTP客户端类型，用于封装当前模块中的相关行为或状态。

    该资源只负责维护进程级复用的 ``httpx.AsyncClient``，
    供真正的异步 I/O 边界按需获取，不改变领域层与用例层的同步主干。
    """

    def __init__(
        self,
        detail: AsyncHttpClientDetail,
        *,
        tls_context: ssl.SSLContext | None = None,
    ) -> None:
        """
        初始化共享异步HTTP客户端。

        :param detail: 已完成契约校验的异步 HTTP 客户端扩展配置。
        :type detail: AsyncHttpClientDetail
        :returns: 无返回值。
        :rtype: None
        """

        self._detail = detail
        limits = httpx.Limits(
            max_connections=detail.max_connections,
            max_keepalive_connections=detail.max_keepalive_connections,
        )
        self._transport = OutboundUrlSafetyAsyncHttpTransport(
            limits=limits,
            tls_context=tls_context,
        )
        self._client = httpx.AsyncClient(
            timeout=detail.timeout_seconds,
            transport=self._transport,
        )

    def get_client(self) -> httpx.AsyncClient:
        """
        获取客户端。

        :returns: 返回进程级共享的异步 HTTP 客户端实例。
        :rtype: httpx.AsyncClient
        """

        return self._client

    def install_url_safety_hook(self, hook: AsyncOutboundUrlSafetyHook) -> None:
        """
        安装出站 URL 安全钩子。
        """

        self._transport.set_validator(hook.get_validator())
        self._transport.set_denial_event_emitter(hook.emit_denied_event)
        self._client.event_hooks["request"].append(hook)

    async def close(self) -> None:
        """
        关闭异步客户端。

        :returns: 无返回值。
        :rtype: None
        """

        await self._client.aclose()

    def close_sync(self) -> None:
        """
        以同步方式关闭异步客户端。

        该入口用于同步启动/关闭生命周期中安全回收异步资源，
        避免把整个资源释放链条改造成异步。

        :returns: 无返回值。
        :rtype: None
        """

        thread = Thread(target=lambda: anyio.run(self.close), daemon=True)
        thread.start()
        thread.join()
