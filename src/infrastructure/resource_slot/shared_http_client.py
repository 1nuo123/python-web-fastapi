"""
共享HTTP客户端基础设施模块。
"""

from __future__ import annotations

import httpx

from src.core.http_contract.outbound_http_client_contract import SyncHttpClientDetail
from src.infrastructure.security.outbound_url_safety_httpx_hook import (
    SyncOutboundUrlSafetyHook,
)
from src.infrastructure.security.outbound_url_safety_transport import (
    OutboundUrlSafetyHttpTransport,
)

DEFAULT_SYNC_HTTP_TIMEOUT_SECONDS = 5
DEFAULT_SYNC_HTTP_MAX_CONNECTIONS = 64
DEFAULT_SYNC_HTTP_MAX_KEEPALIVE_CONNECTIONS = 16


class SharedHttpClient:
    """
    共享HTTP客户端类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self, detail: SyncHttpClientDetail | None = None) -> None:
        """
        初始化共享HTTP客户端。

        :returns: 无返回值。
        :rtype: None
        """

        self._detail = detail
        timeout_seconds = (
            detail.timeout_seconds if detail is not None else DEFAULT_SYNC_HTTP_TIMEOUT_SECONDS
        )
        max_connections = (
            detail.max_connections if detail is not None else DEFAULT_SYNC_HTTP_MAX_CONNECTIONS
        )
        max_keepalive_connections = (
            detail.max_keepalive_connections
            if detail is not None
            else DEFAULT_SYNC_HTTP_MAX_KEEPALIVE_CONNECTIONS
        )
        limits = httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        )
        self._transport = OutboundUrlSafetyHttpTransport(limits=limits)
        self._client = httpx.Client(timeout=timeout_seconds, transport=self._transport)

    def get_client(self) -> httpx.Client:
        """
        获取客户端。

        :returns: 返回读取到的对象或状态快照。
        :rtype: httpx.Client
        """

        return self._client

    def install_url_safety_hook(self, hook: SyncOutboundUrlSafetyHook) -> None:
        """
        安装出站 URL 安全钩子。
        """

        self._transport.set_validator(hook.get_validator())
        self._transport.set_denial_event_emitter(hook.emit_denied_event)
        self._client.event_hooks["request"].append(hook)

    def close(self) -> None:
        """
        处理关闭。

        :returns: 无返回值。
        :rtype: None
        """

        self._client.close()
