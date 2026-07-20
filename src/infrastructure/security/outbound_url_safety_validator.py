"""
出站 URL 安全校验器模块。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from src.core.security_contract.outbound_url_safety_contract import (
    OUTBOUND_URL_SAFETY_DEFAULT_SENTINEL_HOST_DIGEST,
    OUTBOUND_URL_SAFETY_EVENT_TYPE,
    OutboundUrlSafetyAction,
    OutboundUrlSafetyDecision,
    OutboundUrlSafetyEnvelope,
)
from src.infrastructure.key_management.sensitive_digest_service import SensitiveDigestService

LOCALHOST_HOSTNAME = "localhost"
METADATA_ADDRESS = "169.254.169.254"
SSRF_ALLOWED_REASON = "ssrf.allowed"
SSRF_INVALID_SCHEME_REASON = "ssrf.invalid_scheme"
SSRF_INVALID_PORT_REASON = "ssrf.invalid_port"
SSRF_EMPTY_HOST_REASON = "ssrf.empty_host"
SSRF_BLOCKED_HOST_REASON = "ssrf.blocked_host"
SSRF_DENY_HOSTNAME_REASON = "ssrf.deny_hostname"
SSRF_HOST_NOT_ALLOWED_REASON = "ssrf.host_not_allowed"
SSRF_DENY_CIDR_REASON = "ssrf.deny_cidr"
SSRF_NON_GLOBAL_ADDRESS_REASON = "ssrf.non_global_address"
SSRF_PEER_ADDRESS_MISMATCH_REASON = "ssrf.peer_address_mismatch"
SSRF_PEER_ADDRESS_UNAVAILABLE_REASON = "ssrf.peer_address_unavailable"


class OutboundUrlSafetyValidator:
    """
    出站 URL 安全校验器。
    """

    def __init__(
        self,
        *,
        policy: OutboundUrlSafetyEnvelope,
        digest_service: SensitiveDigestService,
    ) -> None:
        """
        初始化出站 URL 校验器。
        """

        self._policy = policy
        self._digest_service = digest_service

    def validate_url(self, url: str) -> OutboundUrlSafetyDecision:
        """
        校验出站 URL。
        """

        parsed_url = urlparse(url)
        if not self._policy.enabled:
            return OutboundUrlSafetyDecision(
                action=OutboundUrlSafetyAction.ALLOW,
                reason_code=SSRF_ALLOWED_REASON,
                host_digest=(
                    self._build_sentinel_host_digest()
                    if parsed_url.hostname is None
                    else self._digest_service.digest(parsed_url.hostname)
                ),
            )
        if parsed_url.scheme not in self._policy.allowed_schemes:
            return self._deny(SSRF_INVALID_SCHEME_REASON, parsed_url.hostname)
        if parsed_url.hostname is None or parsed_url.hostname.strip() == "":
            return self._deny(SSRF_EMPTY_HOST_REASON, parsed_url.hostname)
        try:
            parsed_url.port
        except ValueError:
            return self._deny(SSRF_INVALID_PORT_REASON, parsed_url.hostname)
        blocked_reason = self._resolve_blocked_host_reason(
            host=parsed_url.hostname,
            port=parsed_url.port,
        )
        if blocked_reason is not None:
            return self._deny(blocked_reason, parsed_url.hostname)
        return OutboundUrlSafetyDecision(
            action=OutboundUrlSafetyAction.ALLOW,
            reason_code=SSRF_ALLOWED_REASON,
            host_digest=self._digest_service.digest(parsed_url.hostname),
        )

    def validate_connection_target(
        self,
        *,
        host: str,
        port: int,
    ) -> OutboundUrlSafetyDecision:
        """
        校验连接层目标并返回已固定的安全 IP 地址。
        """

        if not self._policy.enabled:
            return OutboundUrlSafetyDecision(
                action=OutboundUrlSafetyAction.ALLOW,
                reason_code=SSRF_ALLOWED_REASON,
                host_digest=self._digest_service.digest(host),
                resolved_address=host,
            )
        normalized_host = host.strip().lower()
        if normalized_host == "":
            return self._deny(SSRF_EMPTY_HOST_REASON, host)
        blocked_reason = self._resolve_static_host_blocked_reason(normalized_host)
        if blocked_reason is not None:
            return self._deny(blocked_reason, host)
        addresses = self._resolve_addresses(normalized_host, port)
        if len(addresses) == 0:
            return self._deny(SSRF_BLOCKED_HOST_REASON, host)
        for address in addresses:
            blocked_reason = self._resolve_blocked_address_reason(address)
            if blocked_reason is not None:
                return self._deny(blocked_reason, host)
        return OutboundUrlSafetyDecision(
            action=OutboundUrlSafetyAction.ALLOW,
            reason_code=SSRF_ALLOWED_REASON,
            host_digest=self._digest_service.digest(host),
            resolved_address=str(addresses[0]),
        )

    def _resolve_static_host_blocked_reason(self, host: str) -> str | None:
        """
        判断无需 DNS 解析即可确认的 host 阻断原因。
        """

        normalized_host = host.lower()
        deny_hostnames = {deny_hostname.lower() for deny_hostname in self._policy.deny_hostnames}
        if normalized_host in deny_hostnames:
            return SSRF_DENY_HOSTNAME_REASON
        if normalized_host == LOCALHOST_HOSTNAME:
            return SSRF_BLOCKED_HOST_REASON
        allowed_hostnames = {
            allowed_hostname.lower() for allowed_hostname in self._policy.allowed_hostnames
        }
        if self._policy.enforce_allowed_hostnames and normalized_host not in allowed_hostnames:
            return SSRF_HOST_NOT_ALLOWED_REASON
        return None

    def _resolve_blocked_host_reason(
        self,
        *,
        host: str,
        port: int | None,
    ) -> str | None:
        """
        判断 host 是否命中禁止策略并返回原因。
        """

        normalized_host = host.lower()
        blocked_reason = self._resolve_static_host_blocked_reason(normalized_host)
        if blocked_reason is not None:
            return blocked_reason
        addresses = self._resolve_addresses(normalized_host, port)
        if not addresses:
            return SSRF_BLOCKED_HOST_REASON
        for address in addresses:
            blocked_reason = self._resolve_blocked_address_reason(address)
            if blocked_reason is not None:
                return blocked_reason
        return None

    def validate_peer_address(
        self,
        *,
        host: str,
        peer_address: str,
        expected_address: str | None = None,
    ) -> OutboundUrlSafetyDecision:
        """
        校验连接建立后的真实 peer IP。
        """

        if not self._policy.enabled:
            return OutboundUrlSafetyDecision(
                action=OutboundUrlSafetyAction.ALLOW,
                reason_code=SSRF_ALLOWED_REASON,
                host_digest=self._digest_service.digest(host),
                resolved_address=peer_address,
            )
        blocked_reason = self._resolve_static_host_blocked_reason(host.strip().lower())
        if blocked_reason is not None:
            return self._deny(blocked_reason, host)
        try:
            address = ipaddress.ip_address(peer_address)
        except ValueError:
            return self._deny(SSRF_PEER_ADDRESS_MISMATCH_REASON, host)
        if expected_address is not None:
            try:
                expected = ipaddress.ip_address(expected_address)
            except ValueError:
                return self._deny(SSRF_PEER_ADDRESS_MISMATCH_REASON, host)
            if address != expected:
                return self._deny(SSRF_PEER_ADDRESS_MISMATCH_REASON, host)
        blocked_reason = self._resolve_blocked_address_reason(address)
        if blocked_reason is not None:
            return self._deny(blocked_reason, host)
        return OutboundUrlSafetyDecision(
            action=OutboundUrlSafetyAction.ALLOW,
            reason_code=SSRF_ALLOWED_REASON,
            host_digest=self._digest_service.digest(host),
            resolved_address=peer_address,
        )

    def build_peer_address_unavailable_decision(
        self,
        *,
        host: str,
    ) -> OutboundUrlSafetyDecision:
        """
        构建连接 peer 地址不可用拒绝决策。

        :param host: 原始连接目标主机。
        :type host: str
        :returns: 出站 URL 安全拒绝决策。
        :rtype: OutboundUrlSafetyDecision
        """

        return self._deny(SSRF_PEER_ADDRESS_UNAVAILABLE_REASON, host)

    def _deny(self, reason_code: str, host: str | None) -> OutboundUrlSafetyDecision:
        """
        构建拒绝决策。
        """

        return OutboundUrlSafetyDecision(
            action=OutboundUrlSafetyAction.DENY,
            reason_code=reason_code,
            event_type=OUTBOUND_URL_SAFETY_EVENT_TYPE,
            host_digest=(
                self._build_sentinel_host_digest()
                if host is None
                else self._digest_service.digest(host)
            ),
        )

    def _resolve_blocked_address_reason(
        self,
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ) -> str | None:
        """
        判断 IP 地址是否命中禁止策略。
        """

        deny_networks = [
            ipaddress.ip_network(cidr_block, strict=False)
            for cidr_block in self._policy.deny_cidr_blocks
        ]
        if any(address in network for network in deny_networks):
            return SSRF_DENY_CIDR_REASON
        if str(address) == METADATA_ADDRESS and self._policy.deny_metadata_address:
            return SSRF_BLOCKED_HOST_REASON
        if self._policy.deny_private_networks and not address.is_global:
            return SSRF_NON_GLOBAL_ADDRESS_REASON
        if self._policy.deny_private_networks and (
            address.is_loopback
            or address.is_private
            or address.is_link_local
            or address.is_reserved
        ):
            return SSRF_BLOCKED_HOST_REASON
        return None

    def _build_sentinel_host_digest(self) -> str:
        """
        构建缺失 host 的哨兵摘要。
        """

        return self._digest_service.digest(OUTBOUND_URL_SAFETY_DEFAULT_SENTINEL_HOST_DIGEST)

    def _resolve_addresses(
        self,
        host: str,
        port: int | None,
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        """
        解析 host 或直接读取 IP 地址。
        """

        try:
            return [ipaddress.ip_address(host)]
        except ValueError:
            return self._resolve_host(host=host, port=port)

    def _resolve_host(
        self,
        *,
        host: str,
        port: int | None,
    ) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
        """
        解析 host 地址。
        """

        resolved: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
        try:
            address_infos = socket.getaddrinfo(host, port)
        except socket.gaierror:
            return resolved
        for family, _type, _proto, _canonname, sockaddr in address_infos:
            if family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            resolved.append(ipaddress.ip_address(sockaddr[0]))
        return resolved
