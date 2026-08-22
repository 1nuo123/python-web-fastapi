"""
出站 URL 安全传输层模块。
"""

from __future__ import annotations

import ssl
from collections.abc import Callable, Iterable
from http import HTTPStatus

import httpx
from httpcore._backends.anyio import AnyIOBackend
from httpcore._backends.base import SOCKET_OPTION, AsyncNetworkStream, NetworkStream
from httpcore._backends.sync import SyncBackend

from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.security_contract.outbound_url_safety_contract import (
    OutboundUrlSafetyAction,
    OutboundUrlSafetyDecision,
)
from src.infrastructure.security.outbound_url_safety_validator import (
    SSRF_PEER_ADDRESS_UNAVAILABLE_REASON,
    OutboundUrlSafetyValidator,
)

SERVER_ADDRESS_EXTRA_INFO_KEY = "server_addr"
SERVER_ADDRESS_HOST_INDEX = 0
OUTBOUND_CONNECTION_BLOCKED_MESSAGE = "出站 URL 连接目标被安全策略拒绝。"
OUTBOUND_HTTP_TRANSPORT_POOL_FIELD = "_pool"
OUTBOUND_HTTP_TRANSPORT_NETWORK_BACKEND_FIELD = "_network_backend"


class SyncOutboundUrlSafetyNetworkBackend(SyncBackend):
    """
    同步出站 URL 安全网络后端。
    """

    def __init__(
        self,
        *,
        validator_getter: Callable[[], OutboundUrlSafetyValidator | None],
        denial_event_emitter_getter: Callable[
            [], Callable[[OutboundUrlSafetyDecision], None] | None
        ]
        | None = None,
    ) -> None:
        """
        初始化同步网络后端。
        """

        self._validator_getter = validator_getter
        self._denial_event_emitter_getter = denial_event_emitter_getter

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> NetworkStream:
        """
        解析并固定安全目标 IP 后建立 TCP 连接。
        """

        pinned_host = self._resolve_pinned_host(host=host, port=port)
        stream = super().connect_tcp(
            host=pinned_host,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )
        try:
            self._validate_peer_address(
                host=host,
                expected_address=pinned_host,
                stream=stream,
            )
        except Exception:
            stream.close()
            raise
        return stream

    def _resolve_pinned_host(self, *, host: str, port: int) -> str:
        """
        解析连接目标并返回固定后的 IP 地址。
        """

        validator = self._validator_getter()
        if validator is None:
            return host
        decision = validator.validate_connection_target(host=host, port=port)
        if decision.action == OutboundUrlSafetyAction.DENY:
            self._emit_denied_event(decision)
            raise self._build_blocked_fault(decision.reason_code)
        return decision.resolved_address or host

    def _validate_peer_address(
        self,
        *,
        host: str,
        expected_address: str,
        stream: NetworkStream,
    ) -> None:
        """
        校验已连接 socket 的真实 peer IP。
        """

        validator = self._validator_getter()
        if validator is None:
            return
        extractor = OutboundPeerAddressExtractor()
        peer_address = extractor.extract(stream.get_extra_info(SERVER_ADDRESS_EXTRA_INFO_KEY))
        if peer_address is None:
            decision = validator.build_peer_address_unavailable_decision(host=host)
            self._emit_denied_event(decision)
            raise self._build_blocked_fault(SSRF_PEER_ADDRESS_UNAVAILABLE_REASON)
        decision = validator.validate_peer_address(
            host=host,
            peer_address=peer_address,
            expected_address=expected_address,
        )
        if decision.action == OutboundUrlSafetyAction.DENY:
            self._emit_denied_event(decision)
            raise self._build_blocked_fault(decision.reason_code)

    def _emit_denied_event(self, decision: OutboundUrlSafetyDecision) -> None:
        """
        写入连接层拒绝安全事件。

        :param decision: 出站 URL 安全拒绝决策。
        :type decision: OutboundUrlSafetyDecision
        :returns: 无返回值。
        :rtype: None
        """

        if self._denial_event_emitter_getter is None:
            return
        denial_event_emitter = self._denial_event_emitter_getter()
        if denial_event_emitter is None:
            return
        denial_event_emitter(decision)

    def _build_blocked_fault(self, reason_code: str) -> HttpFaultException:
        """
        构建连接层阻断异常。
        """

        return HttpFaultException(
            status_code=HTTPStatus.BAD_REQUEST,
            error_code=CoreErrorCode.REQUEST_INVALID,
            message=OUTBOUND_CONNECTION_BLOCKED_MESSAGE,
            detail=reason_code,
        )


class AsyncOutboundUrlSafetyNetworkBackend(AnyIOBackend):
    """
    异步出站 URL 安全网络后端。
    """

    def __init__(
        self,
        *,
        validator_getter: Callable[[], OutboundUrlSafetyValidator | None],
        denial_event_emitter_getter: Callable[
            [], Callable[[OutboundUrlSafetyDecision], None] | None
        ]
        | None = None,
    ) -> None:
        """
        初始化异步网络后端。
        """

        self._validator_getter = validator_getter
        self._denial_event_emitter_getter = denial_event_emitter_getter

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> AsyncNetworkStream:
        """
        解析并固定安全目标 IP 后建立异步 TCP 连接。
        """

        pinned_host = self._resolve_pinned_host(host=host, port=port)
        stream = await super().connect_tcp(
            host=pinned_host,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )
        try:
            self._validate_peer_address(
                host=host,
                expected_address=pinned_host,
                stream=stream,
            )
        except Exception:
            await stream.aclose()
            raise
        return stream

    def _resolve_pinned_host(self, *, host: str, port: int) -> str:
        """
        解析连接目标并返回固定后的 IP 地址。
        """

        validator = self._validator_getter()
        if validator is None:
            return host
        decision = validator.validate_connection_target(host=host, port=port)
        if decision.action == OutboundUrlSafetyAction.DENY:
            self._emit_denied_event(decision)
            raise self._build_blocked_fault(decision.reason_code)
        return decision.resolved_address or host

    def _validate_peer_address(
        self,
        *,
        host: str,
        expected_address: str,
        stream: AsyncNetworkStream,
    ) -> None:
        """
        校验已连接 socket 的真实 peer IP。
        """

        validator = self._validator_getter()
        if validator is None:
            return
        extractor = OutboundPeerAddressExtractor()
        peer_address = extractor.extract(stream.get_extra_info(SERVER_ADDRESS_EXTRA_INFO_KEY))
        if peer_address is None:
            decision = validator.build_peer_address_unavailable_decision(host=host)
            self._emit_denied_event(decision)
            raise self._build_blocked_fault(SSRF_PEER_ADDRESS_UNAVAILABLE_REASON)
        decision = validator.validate_peer_address(
            host=host,
            peer_address=peer_address,
            expected_address=expected_address,
        )
        if decision.action == OutboundUrlSafetyAction.DENY:
            self._emit_denied_event(decision)
            raise self._build_blocked_fault(decision.reason_code)

    def _emit_denied_event(self, decision: OutboundUrlSafetyDecision) -> None:
        """
        写入连接层拒绝安全事件。

        :param decision: 出站 URL 安全拒绝决策。
        :type decision: OutboundUrlSafetyDecision
        :returns: 无返回值。
        :rtype: None
        """

        if self._denial_event_emitter_getter is None:
            return
        denial_event_emitter = self._denial_event_emitter_getter()
        if denial_event_emitter is None:
            return
        denial_event_emitter(decision)

    def _build_blocked_fault(self, reason_code: str) -> HttpFaultException:
        """
        构建连接层阻断异常。
        """

        return HttpFaultException(
            status_code=HTTPStatus.BAD_REQUEST,
            error_code=CoreErrorCode.REQUEST_INVALID,
            message=OUTBOUND_CONNECTION_BLOCKED_MESSAGE,
            detail=reason_code,
        )


class OutboundUrlSafetyHttpTransport(httpx.HTTPTransport):
    """
    支持连接层 IP 固定的同步 HTTP 传输。
    """

    def __init__(self, *, limits: httpx.Limits) -> None:
        """
        初始化同步 HTTP 传输。
        """

        self._validator: OutboundUrlSafetyValidator | None = None
        self._denial_event_emitter: Callable[[OutboundUrlSafetyDecision], None] | None = None
        self._network_backend = SyncOutboundUrlSafetyNetworkBackend(
            validator_getter=self._get_validator,
            denial_event_emitter_getter=self._get_denial_event_emitter,
        )
        super().__init__(limits=limits)
        pool = getattr(self, OUTBOUND_HTTP_TRANSPORT_POOL_FIELD)
        setattr(
            pool,
            OUTBOUND_HTTP_TRANSPORT_NETWORK_BACKEND_FIELD,
            self._network_backend,
        )

    def set_validator(self, validator: OutboundUrlSafetyValidator) -> None:
        """
        设置连接层 URL 安全校验器。
        """

        self._validator = validator

    def set_denial_event_emitter(
        self,
        denial_event_emitter: Callable[[OutboundUrlSafetyDecision], None],
    ) -> None:
        """
        设置连接层拒绝安全事件写入器。

        :param denial_event_emitter: 拒绝安全事件写入入口。
        :type denial_event_emitter: Callable[[OutboundUrlSafetyDecision], None]
        :returns: 无返回值。
        :rtype: None
        """

        self._denial_event_emitter = denial_event_emitter

    def _get_validator(self) -> OutboundUrlSafetyValidator | None:
        """
        读取当前校验器。
        """

        return self._validator

    def _get_denial_event_emitter(
        self,
    ) -> Callable[[OutboundUrlSafetyDecision], None] | None:
        """
        读取连接层拒绝安全事件写入器。

        :returns: 拒绝安全事件写入入口。
        :rtype: Callable[[OutboundUrlSafetyDecision], None] | None
        """

        return self._denial_event_emitter


class OutboundUrlSafetyAsyncHttpTransport(httpx.AsyncHTTPTransport):
    """
    支持连接层 IP 固定的异步 HTTP 传输。
    """

    def __init__(
        self,
        *,
        limits: httpx.Limits,
        tls_context: ssl.SSLContext | None = None,
    ) -> None:
        """
        初始化异步 HTTP 传输。
        """

        self._validator: OutboundUrlSafetyValidator | None = None
        self._denial_event_emitter: Callable[[OutboundUrlSafetyDecision], None] | None = None
        self._network_backend = AsyncOutboundUrlSafetyNetworkBackend(
            validator_getter=self._get_validator,
            denial_event_emitter_getter=self._get_denial_event_emitter,
        )
        super().__init__(
            limits=limits,
            verify=tls_context if tls_context is not None else True,
        )
        pool = getattr(self, OUTBOUND_HTTP_TRANSPORT_POOL_FIELD)
        setattr(
            pool,
            OUTBOUND_HTTP_TRANSPORT_NETWORK_BACKEND_FIELD,
            self._network_backend,
        )

    def set_validator(self, validator: OutboundUrlSafetyValidator) -> None:
        """
        设置连接层 URL 安全校验器。
        """

        self._validator = validator

    def set_denial_event_emitter(
        self,
        denial_event_emitter: Callable[[OutboundUrlSafetyDecision], None],
    ) -> None:
        """
        设置连接层拒绝安全事件写入器。

        :param denial_event_emitter: 拒绝安全事件写入入口。
        :type denial_event_emitter: Callable[[OutboundUrlSafetyDecision], None]
        :returns: 无返回值。
        :rtype: None
        """

        self._denial_event_emitter = denial_event_emitter

    def _get_validator(self) -> OutboundUrlSafetyValidator | None:
        """
        读取当前校验器。
        """

        return self._validator

    def _get_denial_event_emitter(
        self,
    ) -> Callable[[OutboundUrlSafetyDecision], None] | None:
        """
        读取连接层拒绝安全事件写入器。

        :returns: 拒绝安全事件写入入口。
        :rtype: Callable[[OutboundUrlSafetyDecision], None] | None
        """

        return self._denial_event_emitter


class OutboundPeerAddressExtractor:
    """
    出站连接 peer 地址提取器。
    """

    def extract(self, peer_info: object) -> str | None:
        """
        提取 socket peer 地址。
        """

        if not isinstance(peer_info, tuple) or len(peer_info) == 0:
            return None
        peer_host = peer_info[SERVER_ADDRESS_HOST_INDEX]
        if not isinstance(peer_host, str):
            return None
        return peer_host
