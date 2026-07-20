"""
SSRF URL 校验器单元测试模块。
"""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import cast

import httpx
import pytest
from httpcore._backends.base import AsyncNetworkStream, NetworkStream

from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.security_contract.outbound_url_safety_contract import (
    OUTBOUND_URL_SAFETY_EVENT_TYPE,
    OutboundUrlSafetyAction,
    OutboundUrlSafetyDecision,
    OutboundUrlSafetyEnvelope,
)
from src.core.security_contract.security_event_contract import SecurityEventEnvelope
from src.infrastructure.context.request_context_manager_impl import (
    RequestContextManagerImpl,
)
from src.infrastructure.key_management.sensitive_digest_service import (
    SensitiveDigestService,
)
from src.infrastructure.resource_slot.shared_http_client import SharedHttpClient
from src.infrastructure.security.outbound_url_safety_httpx_hook import (
    AsyncOutboundUrlSafetyHook,
    SyncOutboundUrlSafetyHook,
)
from src.infrastructure.security.outbound_url_safety_transport import (
    SSRF_PEER_ADDRESS_UNAVAILABLE_REASON,
    AsyncOutboundUrlSafetyNetworkBackend,
    OutboundPeerAddressExtractor,
    OutboundUrlSafetyAsyncHttpTransport,
    OutboundUrlSafetyHttpTransport,
    SyncOutboundUrlSafetyNetworkBackend,
)
from src.infrastructure.security.outbound_url_safety_validator import (
    SSRF_HOST_NOT_ALLOWED_REASON,
    SSRF_PEER_ADDRESS_MISMATCH_REASON,
    OutboundUrlSafetyValidator,
)
from src.infrastructure.security.security_event_builder import SecurityEventBuilder

DNS_LOOPBACK_ADDRESS = "127.0.0.1"
DNS_PRIVATE_ADDRESS = "10.1.2.3"
DNS_LINK_LOCAL_ADDRESS = "169.254.10.10"
DNS_METADATA_ADDRESS = "169.254.169.254"
DNS_GLOBAL_ADDRESS = "93.184.216.34"
DNS_OTHER_GLOBAL_ADDRESS = "93.184.216.35"
DNS_HTTP_PORT = 80
DNS_TEST_HOST = "private.example"
DNS_ALLOWED_HOST = "allowed.example"
DNS_BLOCKED_HOST = "blocked.example"
DNS_TEST_URL = f"http://{DNS_TEST_HOST}/internal"
DNS_ALLOWED_URL = f"https://{DNS_ALLOWED_HOST}/resource"
DNS_BLOCKED_URL = f"https://{DNS_BLOCKED_HOST}/resource"
INVALID_SCHEME_URL = "ftp://example.com/resource"
INVALID_PORT_URL = "http://example.com:invalid/path"
EMPTY_HOST_URL = "http:///internal"
DENIED_LOOPBACK_URL = "http://127.0.0.1/internal"
DENIED_METADATA_URL = "http://169.254.169.254/latest/meta-data"
SSRF_DENIED_EVENT_COUNT = 3
SSRF_INVALID_URL_DENIED_EVENT_COUNT = 2


@dataclass(frozen=True)
class FakeHttpxRequest:
    """
    测试用 httpx 请求替身。
    """

    url: str


class FakeSecurityEventEmitter:
    """
    测试安全事件写入器。
    """

    def __init__(self) -> None:
        """
        初始化测试写入器。
        """

        self.events: list[SecurityEventEnvelope] = []

    def emit_security_event(self, event: SecurityEventEnvelope) -> None:
        """
        写入测试安全事件。
        """

        self.events.append(event)


class MissingPeerInfoStream:
    """
    缺少 peer 地址的网络流测试替身。
    """

    def get_extra_info(self, info: str) -> object:
        """
        返回缺失的 peer 扩展信息。
        """

        _ = info
        return None


class PeerInfoStream:
    """
    携带 peer 地址的网络流测试替身。
    """

    def __init__(self, *, peer_address: str) -> None:
        """
        初始化携带 peer 地址的网络流测试替身。
        """

        self._peer_address = peer_address

    def get_extra_info(self, info: str) -> object:
        """
        返回 peer 扩展信息。
        """

        _ = info
        return (self._peer_address, DNS_HTTP_PORT)


class TestOutboundUrlSafetyValidatorUnit:
    """
    SSRF URL 校验器单元测试集合。
    """

    def test_validate_url_should_block_local_and_metadata_address(self) -> None:
        """
        验证本机和 metadata 地址会被拒绝。
        """

        validator = OutboundUrlSafetyValidator(
            policy=OutboundUrlSafetyEnvelope(
                enabled=True,
                allowed_schemes=["http", "https"],
                deny_private_networks=True,
                deny_metadata_address=True,
            ),
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
        )

        assert (
            validator.validate_url("http://127.0.0.1/internal").action
            == OutboundUrlSafetyAction.DENY
        )
        assert (
            validator.validate_url("http://169.254.169.254/latest/meta-data").action
            == OutboundUrlSafetyAction.DENY
        )
        assert (
            validator.validate_url("http://localhost/internal").action
            == OutboundUrlSafetyAction.DENY
        )
        assert (
            validator.validate_url("http://[::1]/internal").action == OutboundUrlSafetyAction.DENY
        )
        assert (
            validator.validate_url("http://10.0.0.1/internal").action
            == OutboundUrlSafetyAction.DENY
        )
        assert (
            validator.validate_url("http://172.16.0.1/internal").action
            == OutboundUrlSafetyAction.DENY
        )
        assert (
            validator.validate_url("http://192.168.0.1/internal").action
            == OutboundUrlSafetyAction.DENY
        )
        assert validator.validate_url("https://example.com").action == OutboundUrlSafetyAction.ALLOW

    def test_validate_url_should_block_invalid_input_and_dns_private_resolution(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证非法 URL 与解析到私网地址的域名会被拒绝。
        """

        validator = OutboundUrlSafetyValidator(
            policy=OutboundUrlSafetyEnvelope(
                enabled=True,
                allowed_schemes=["http", "https"],
                deny_private_networks=True,
                deny_metadata_address=True,
            ),
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
        )

        def fake_getaddrinfo(host: str, port):
            """
            返回解析到 link-local 的测试地址。
            """

            _ = host
            _ = port
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("169.254.10.10", 80),
                )
            ]

        monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

        denied_decision = validator.validate_url("http://private.example/internal")

        assert validator.validate_url("ftp://example.com").action == OutboundUrlSafetyAction.DENY
        assert validator.validate_url("http://").action == OutboundUrlSafetyAction.DENY
        assert (
            validator.validate_url("http://example.com:invalid").action
            == OutboundUrlSafetyAction.DENY
        )
        assert denied_decision.action == OutboundUrlSafetyAction.DENY
        assert denied_decision.event_type == OUTBOUND_URL_SAFETY_EVENT_TYPE

    def test_validate_url_should_block_dns_loopback_private_link_local_and_metadata(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证 DNS 解析到环回、私网、link-local 和 metadata 地址时拒绝。
        """

        validator = OutboundUrlSafetyValidator(
            policy=OutboundUrlSafetyEnvelope(
                enabled=True,
                allowed_schemes=["http", "https"],
                deny_private_networks=True,
                deny_metadata_address=True,
            ),
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
        )

        for address in [
            DNS_LOOPBACK_ADDRESS,
            DNS_PRIVATE_ADDRESS,
            DNS_LINK_LOCAL_ADDRESS,
            DNS_METADATA_ADDRESS,
        ]:
            monkeypatch.setattr(
                socket,
                "getaddrinfo",
                self._build_dns_answer(address),
            )

            denied_decision = validator.validate_url(DNS_TEST_URL)

            assert denied_decision.action == OutboundUrlSafetyAction.DENY

    def test_validate_peer_address_should_enforce_pinned_address(self) -> None:
        """
        验证连接后 peer 地址必须匹配连接前固定 IP。
        """

        validator = self._build_validator()

        allowed_decision = validator.validate_peer_address(
            host=DNS_TEST_HOST,
            peer_address=DNS_GLOBAL_ADDRESS,
            expected_address=DNS_GLOBAL_ADDRESS,
        )
        denied_decision = validator.validate_peer_address(
            host=DNS_TEST_HOST,
            peer_address=DNS_OTHER_GLOBAL_ADDRESS,
            expected_address=DNS_GLOBAL_ADDRESS,
        )

        assert allowed_decision.action == OutboundUrlSafetyAction.ALLOW
        assert denied_decision.action == OutboundUrlSafetyAction.DENY
        assert denied_decision.reason_code == SSRF_PEER_ADDRESS_MISMATCH_REASON

    def test_validate_url_should_enforce_allowed_hostnames(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证启用目的域名允许清单后只放行显式声明的主机。
        """

        validator = OutboundUrlSafetyValidator(
            policy=OutboundUrlSafetyEnvelope(
                enabled=True,
                allowed_schemes=["http", "https"],
                deny_private_networks=True,
                deny_metadata_address=True,
                allowed_hostnames=[DNS_ALLOWED_HOST],
                enforce_allowed_hostnames=True,
            ),
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
        )
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            self._build_dns_answer(DNS_GLOBAL_ADDRESS),
        )

        allowed_decision = validator.validate_url(DNS_ALLOWED_URL)
        denied_decision = validator.validate_url(DNS_BLOCKED_URL)
        denied_connection_decision = validator.validate_connection_target(
            host=DNS_BLOCKED_HOST,
            port=DNS_HTTP_PORT,
        )
        denied_peer_decision = validator.validate_peer_address(
            host=DNS_BLOCKED_HOST,
            peer_address=DNS_GLOBAL_ADDRESS,
            expected_address=DNS_GLOBAL_ADDRESS,
        )

        assert allowed_decision.action == OutboundUrlSafetyAction.ALLOW
        assert denied_decision.action == OutboundUrlSafetyAction.DENY
        assert denied_decision.reason_code == SSRF_HOST_NOT_ALLOWED_REASON
        assert denied_connection_decision.reason_code == SSRF_HOST_NOT_ALLOWED_REASON
        assert denied_peer_decision.reason_code == SSRF_HOST_NOT_ALLOWED_REASON

    def test_network_backend_when_peer_address_missing_should_fail_closed(self) -> None:
        """
        验证连接层无法读取真实 peer 地址时 fail closed。
        """

        validator = self._build_validator()
        emitter = FakeSecurityEventEmitter()
        hook = SyncOutboundUrlSafetyHook(
            validator=validator,
            request_context_manager=RequestContextManagerImpl(),
            security_event_builder=SecurityEventBuilder(),
            security_event_emitter=emitter,
        )
        backend = SyncOutboundUrlSafetyNetworkBackend(
            validator_getter=hook.get_validator,
            denial_event_emitter_getter=lambda: hook.emit_denied_event,
        )

        with pytest.raises(HttpFaultException) as exc_info:
            backend._validate_peer_address(  # noqa: SLF001
                host=DNS_TEST_HOST,
                expected_address=DNS_GLOBAL_ADDRESS,
                stream=MissingPeerInfoStream(),
            )

        assert exc_info.value.detail == SSRF_PEER_ADDRESS_UNAVAILABLE_REASON
        assert len(emitter.events) == 1
        assert emitter.events[0].detail.reason_code == SSRF_PEER_ADDRESS_UNAVAILABLE_REASON

    def test_network_backend_when_peer_address_mismatch_should_emit_event(self) -> None:
        """
        验证连接层 peer 地址不匹配时写入 SSRF 安全事件。
        """

        validator = self._build_validator()
        emitter = FakeSecurityEventEmitter()
        hook = SyncOutboundUrlSafetyHook(
            validator=validator,
            request_context_manager=RequestContextManagerImpl(),
            security_event_builder=SecurityEventBuilder(),
            security_event_emitter=emitter,
        )
        backend = SyncOutboundUrlSafetyNetworkBackend(
            validator_getter=hook.get_validator,
            denial_event_emitter_getter=lambda: hook.emit_denied_event,
        )

        with pytest.raises(HttpFaultException) as exc_info:
            backend._validate_peer_address(  # noqa: SLF001
                host=DNS_TEST_HOST,
                expected_address=DNS_GLOBAL_ADDRESS,
                stream=PeerInfoStream(peer_address=DNS_OTHER_GLOBAL_ADDRESS),
            )

        assert exc_info.value.detail == SSRF_PEER_ADDRESS_MISMATCH_REASON
        assert len(emitter.events) == 1
        assert emitter.events[0].detail.reason_code == SSRF_PEER_ADDRESS_MISMATCH_REASON

    def test_async_network_backend_should_pin_target_and_validate_peer(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证异步连接层固定解析地址并校验真实 peer。"""

        validator = self._build_validator()
        emitter = FakeSecurityEventEmitter()
        hook = AsyncOutboundUrlSafetyHook(
            validator=validator,
            request_context_manager=RequestContextManagerImpl(),
            security_event_builder=SecurityEventBuilder(),
            security_event_emitter=emitter,
        )
        backend = AsyncOutboundUrlSafetyNetworkBackend(
            validator_getter=hook.get_validator,
            denial_event_emitter_getter=lambda: hook.emit_denied_event,
        )
        monkeypatch.setattr(
            socket,
            "getaddrinfo",
            self._build_dns_answer(DNS_GLOBAL_ADDRESS),
        )

        pinned_host = backend._resolve_pinned_host(  # noqa: SLF001
            host=DNS_TEST_HOST,
            port=DNS_HTTP_PORT,
        )
        backend._validate_peer_address(  # noqa: SLF001
            host=DNS_TEST_HOST,
            expected_address=DNS_GLOBAL_ADDRESS,
            stream=cast(AsyncNetworkStream, PeerInfoStream(peer_address=DNS_GLOBAL_ADDRESS)),
        )

        assert pinned_host == DNS_GLOBAL_ADDRESS
        assert emitter.events == []

    def test_async_network_backend_should_reject_target_and_invalid_peer(self) -> None:
        """验证异步连接层拒绝目标、缺失 peer 和地址漂移。"""

        validator = self._build_validator()
        emitter = FakeSecurityEventEmitter()
        hook = AsyncOutboundUrlSafetyHook(
            validator=validator,
            request_context_manager=RequestContextManagerImpl(),
            security_event_builder=SecurityEventBuilder(),
            security_event_emitter=emitter,
        )
        backend = AsyncOutboundUrlSafetyNetworkBackend(
            validator_getter=hook.get_validator,
            denial_event_emitter_getter=lambda: hook.emit_denied_event,
        )

        with pytest.raises(HttpFaultException):
            backend._resolve_pinned_host(  # noqa: SLF001
                host=DNS_LOOPBACK_ADDRESS,
                port=DNS_HTTP_PORT,
            )
        with pytest.raises(HttpFaultException) as missing_peer_error:
            backend._validate_peer_address(  # noqa: SLF001
                host=DNS_TEST_HOST,
                expected_address=DNS_GLOBAL_ADDRESS,
                stream=cast(AsyncNetworkStream, MissingPeerInfoStream()),
            )
        with pytest.raises(HttpFaultException) as mismatched_peer_error:
            backend._validate_peer_address(  # noqa: SLF001
                host=DNS_TEST_HOST,
                expected_address=DNS_GLOBAL_ADDRESS,
                stream=cast(
                    AsyncNetworkStream,
                    PeerInfoStream(peer_address=DNS_OTHER_GLOBAL_ADDRESS),
                ),
            )

        assert missing_peer_error.value.detail == SSRF_PEER_ADDRESS_UNAVAILABLE_REASON
        assert mismatched_peer_error.value.detail == SSRF_PEER_ADDRESS_MISMATCH_REASON
        assert len(emitter.events) == 3

    def test_network_backends_without_validator_or_emitter_should_allow_target(self) -> None:
        """验证未装配策略时连接层保持透明且不尝试写事件。"""

        sync_backend = SyncOutboundUrlSafetyNetworkBackend(
            validator_getter=lambda: None,
        )
        async_backend = AsyncOutboundUrlSafetyNetworkBackend(
            validator_getter=lambda: None,
            denial_event_emitter_getter=lambda: None,
        )

        assert (
            sync_backend._resolve_pinned_host(  # noqa: SLF001
                host=DNS_TEST_HOST,
                port=DNS_HTTP_PORT,
            )
            == DNS_TEST_HOST
        )
        sync_backend._validate_peer_address(  # noqa: SLF001
            host=DNS_TEST_HOST,
            expected_address=DNS_TEST_HOST,
            stream=cast(NetworkStream, MissingPeerInfoStream()),
        )
        assert (
            async_backend._resolve_pinned_host(  # noqa: SLF001
                host=DNS_TEST_HOST,
                port=DNS_HTTP_PORT,
            )
            == DNS_TEST_HOST
        )
        async_backend._validate_peer_address(  # noqa: SLF001
            host=DNS_TEST_HOST,
            expected_address=DNS_TEST_HOST,
            stream=cast(AsyncNetworkStream, MissingPeerInfoStream()),
        )
        decision = OutboundUrlSafetyDecision(
            action=OutboundUrlSafetyAction.DENY,
            reason_code=SSRF_HOST_NOT_ALLOWED_REASON,
        )
        sync_backend._emit_denied_event(decision)  # noqa: SLF001
        async_backend._emit_denied_event(decision)  # noqa: SLF001

    def test_http_transports_should_install_validator_and_event_emitter(self) -> None:
        """验证同步与异步传输共享连接层安全策略和事件入口。"""

        validator = self._build_validator()
        emitted_decisions: list[OutboundUrlSafetyDecision] = []
        limits = httpx.Limits(max_connections=2, max_keepalive_connections=1)
        sync_transport = OutboundUrlSafetyHttpTransport(limits=limits)
        async_transport = OutboundUrlSafetyAsyncHttpTransport(limits=limits)
        try:
            sync_transport.set_validator(validator)
            sync_transport.set_denial_event_emitter(emitted_decisions.append)
            async_transport.set_validator(validator)
            async_transport.set_denial_event_emitter(emitted_decisions.append)

            assert sync_transport._get_validator() is validator  # noqa: SLF001
            assert async_transport._get_validator() is validator  # noqa: SLF001
            assert sync_transport._get_denial_event_emitter() is not None  # noqa: SLF001
            assert async_transport._get_denial_event_emitter() is not None  # noqa: SLF001
        finally:
            sync_transport.close()
            asyncio.run(async_transport.aclose())

    def test_peer_address_extractor_should_reject_invalid_shape(self) -> None:
        """验证 peer 地址提取只接受首项为字符串的非空元组。"""

        extractor = OutboundPeerAddressExtractor()

        assert extractor.extract(None) is None
        assert extractor.extract(()) is None
        assert extractor.extract((DNS_HTTP_PORT, DNS_HTTP_PORT)) is None
        assert extractor.extract((DNS_GLOBAL_ADDRESS, DNS_HTTP_PORT)) == DNS_GLOBAL_ADDRESS

    def test_shared_http_client_should_block_denied_url_before_network(self) -> None:
        """
        验证共享 HTTP 客户端在发起网络请求前阻断 SSRF URL。
        """

        validator = OutboundUrlSafetyValidator(
            policy=OutboundUrlSafetyEnvelope(
                enabled=True,
                allowed_schemes=["http", "https"],
                deny_private_networks=True,
                deny_metadata_address=True,
            ),
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
        )
        emitter = FakeSecurityEventEmitter()
        shared_client = SharedHttpClient()
        shared_client.install_url_safety_hook(
            SyncOutboundUrlSafetyHook(
                validator=validator,
                request_context_manager=RequestContextManagerImpl(),
                security_event_builder=SecurityEventBuilder(),
                security_event_emitter=emitter,
            )
        )

        try:
            try:
                shared_client.get_client().get("http://127.0.0.1/internal")
            except HttpFaultException:
                blocked = True
            else:
                blocked = False
            assert blocked is True
            assert len(emitter.events) == 1
        finally:
            shared_client.close()

    def test_sync_hook_when_deny_decision_should_emit_event_for_each_url(self) -> None:
        """
        验证同步出站钩子对所有 DENY 决策写入安全事件。
        """

        validator = self._build_validator()
        emitter = FakeSecurityEventEmitter()
        hook = SyncOutboundUrlSafetyHook(
            validator=validator,
            request_context_manager=RequestContextManagerImpl(),
            security_event_builder=SecurityEventBuilder(),
            security_event_emitter=emitter,
        )

        for url in [INVALID_SCHEME_URL, DENIED_LOOPBACK_URL, DENIED_METADATA_URL]:
            with pytest.raises(HttpFaultException):
                hook(httpx.Request("GET", url))

        assert len(emitter.events) == SSRF_DENIED_EVENT_COUNT
        assert all(event.detail.host_digest for event in emitter.events)
        assert all(event.detail.reason_code for event in emitter.events)

    def test_sync_hook_when_invalid_url_should_emit_security_event(self) -> None:
        """
        验证非法端口和空 host 阻断也会写入安全事件。
        """

        validator = self._build_validator()
        emitter = FakeSecurityEventEmitter()
        hook = SyncOutboundUrlSafetyHook(
            validator=validator,
            request_context_manager=RequestContextManagerImpl(),
            security_event_builder=SecurityEventBuilder(),
            security_event_emitter=emitter,
        )

        for request in [
            FakeHttpxRequest(INVALID_PORT_URL),
            FakeHttpxRequest(EMPTY_HOST_URL),
        ]:
            with pytest.raises(HttpFaultException):
                hook(cast(httpx.Request, request))

        assert len(emitter.events) == SSRF_INVALID_URL_DENIED_EVENT_COUNT
        assert all(event.detail.host_digest for event in emitter.events)
        assert all(event.detail.reason_code for event in emitter.events)

    def test_async_hook_should_block_denied_url_and_emit_event(self) -> None:
        """
        验证异步出站钩子阻断 SSRF 并写入安全事件。
        """

        validator = OutboundUrlSafetyValidator(
            policy=OutboundUrlSafetyEnvelope(
                enabled=True,
                allowed_schemes=["http", "https"],
                deny_private_networks=True,
                deny_metadata_address=True,
            ),
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
        )
        emitter = FakeSecurityEventEmitter()
        hook = AsyncOutboundUrlSafetyHook(
            validator=validator,
            request_context_manager=RequestContextManagerImpl(),
            security_event_builder=SecurityEventBuilder(),
            security_event_emitter=emitter,
        )

        with pytest.raises(HttpFaultException):
            asyncio.run(hook(httpx.Request("GET", "http://127.0.0.1/internal")))

        assert len(emitter.events) == 1

    def _build_dns_answer(
        self,
        address: str,
    ) -> Callable[[str, object], list[tuple[int, int, int, str, tuple[str, int]]]]:
        """
        构建 DNS 解析替身。
        """

        def fake_getaddrinfo(
            host: str,
            port: object,
        ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
            """
            返回指定地址的 DNS 解析结果。
            """

            _ = host
            _ = port
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    (address, DNS_HTTP_PORT),
                )
            ]

        return fake_getaddrinfo

    def _build_validator(self) -> OutboundUrlSafetyValidator:
        """
        构建启用 SSRF 策略的测试校验器。
        """

        return OutboundUrlSafetyValidator(
            policy=OutboundUrlSafetyEnvelope(
                enabled=True,
                allowed_schemes=["http", "https"],
                deny_private_networks=True,
                deny_metadata_address=True,
            ),
            digest_service=SensitiveDigestService(salt="unit-test-secret"),
        )
