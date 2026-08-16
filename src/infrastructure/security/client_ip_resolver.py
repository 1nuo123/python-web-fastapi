"""
统一客户端 IP 解析器模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from ipaddress import ip_address, ip_network
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.requests import HTTPConnection

CLIENT_IP_RESOLUTION_SCHEMA_VERSION: Final = "1.0"
CLIENT_IP_RESOLUTION_HEADER_KIND: Final = "client_ip_resolution"
CLIENT_IP_DIRECT_KIND: Final = "direct"
CLIENT_IP_TRUSTED_PROXY_FORWARDED_KIND: Final = "trusted_proxy_forwarded"
UNKNOWN_CLIENT_IP = "unknown"
FORWARDED_HEADER_NAME = "forwarded"
X_FORWARDED_FOR_HEADER_NAME = "x-forwarded-for"
FORWARDED_FOR_KEY = "for"
FORWARDED_PAIR_SEPARATOR = ";"
FORWARDED_VALUE_SEPARATOR = ","
FORWARDED_KEY_VALUE_SEPARATOR = "="
X_FORWARDED_FOR_SEPARATOR = ","
CLIENT_IP_BRACKET_LEFT = "["
CLIENT_IP_BRACKET_RIGHT = "]"
CLIENT_IP_PORT_SEPARATOR = ":"
TRUSTED_LOOPBACK_IPV4 = "127.0.0.0/8"
TRUSTED_LOOPBACK_IPV6 = "::1/128"


class ClientIpResolutionKind(StrEnum):
    """
    客户端 IP 解析来源枚举。
    """

    DIRECT = CLIENT_IP_DIRECT_KIND
    TRUSTED_PROXY_FORWARDED = CLIENT_IP_TRUSTED_PROXY_FORWARDED_KIND


class ClientIpResolutionHeader(BaseModel):
    """
    客户端 IP 解析公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["client_ip_resolution"] = CLIENT_IP_RESOLUTION_HEADER_KIND
    schema_version: Literal["1.0"] = CLIENT_IP_RESOLUTION_SCHEMA_VERSION
    source: ClientIpResolutionKind


class DirectClientIpResolutionDetail(BaseModel):
    """
    直连客户端 IP 解析扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["direct"] = CLIENT_IP_DIRECT_KIND
    schema_version: Literal["1.0"] = CLIENT_IP_RESOLUTION_SCHEMA_VERSION
    client_ip: str
    remote_ip: str


class TrustedProxyForwardedClientIpResolutionDetail(BaseModel):
    """
    可信代理转发客户端 IP 解析扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["trusted_proxy_forwarded"] = CLIENT_IP_TRUSTED_PROXY_FORWARDED_KIND
    schema_version: Literal["1.0"] = CLIENT_IP_RESOLUTION_SCHEMA_VERSION
    client_ip: str
    remote_ip: str
    header_name: str


ClientIpResolutionDetailUnion = Annotated[
    DirectClientIpResolutionDetail | TrustedProxyForwardedClientIpResolutionDetail,
    Field(discriminator="kind"),
]


class ClientIpResolutionEnvelope(BaseModel):
    """
    客户端 IP 解析信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: ClientIpResolutionHeader
    detail: ClientIpResolutionDetailUnion

    @model_validator(mode="after")
    def validate_resolution_contract(self) -> ClientIpResolutionEnvelope:
        """
        校验客户端 IP 解析公共头与扩展字段一致。
        """

        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("客户端 IP 解析 schema_version 必须一致。")
        if self.header.source.value != self.detail.kind:
            raise ValueError("客户端 IP 解析 source 必须与 detail.kind 一致。")
        return self


@dataclass(frozen=True, slots=True)
class TrustedProxyPolicy:
    """
    可信代理策略。
    """

    cidr_blocks: tuple[str, ...] = (
        TRUSTED_LOOPBACK_IPV4,
        TRUSTED_LOOPBACK_IPV6,
    )


class ClientIpResolver:
    """
    客户端 IP 解析器。
    """

    def __init__(
        self,
        *,
        trusted_proxy_policy: TrustedProxyPolicy | None = None,
    ) -> None:
        """
        初始化客户端 IP 解析器。
        """

        policy = trusted_proxy_policy or TrustedProxyPolicy()
        self._trusted_networks = tuple(
            ip_network(cidr_block, strict=False) for cidr_block in policy.cidr_blocks
        )

    def resolve(self, request: HTTPConnection) -> ClientIpResolutionEnvelope:
        """
        解析客户端 IP。
        """

        remote_ip = self._read_remote_ip(request)
        if self._is_trusted_proxy(remote_ip):
            forwarded_ip = self._read_forwarded_header_ip(request)
            if forwarded_ip is not None:
                return self._build_forwarded_result(
                    client_ip=forwarded_ip,
                    remote_ip=remote_ip,
                    header_name=FORWARDED_HEADER_NAME,
                )
            x_forwarded_ip = self._read_x_forwarded_for_ip(request)
            if x_forwarded_ip is not None:
                return self._build_forwarded_result(
                    client_ip=x_forwarded_ip,
                    remote_ip=remote_ip,
                    header_name=X_FORWARDED_FOR_HEADER_NAME,
                )
        return self._build_direct_result(remote_ip=remote_ip)

    def resolve_client_ip(self, request: HTTPConnection) -> str:
        """
        解析客户端 IP 字符串。
        """

        return self.resolve(request).detail.client_ip

    def is_trusted_proxy(self, request: HTTPConnection) -> bool:
        """Return whether the direct peer may provide proxy metadata."""

        return self._is_trusted_proxy(self._read_remote_ip(request))

    def _read_remote_ip(self, request: HTTPConnection) -> str:
        """
        读取直连远端 IP。
        """

        if request.client is None:
            return UNKNOWN_CLIENT_IP
        return request.client.host

    def _is_trusted_proxy(self, remote_ip: str) -> bool:
        """
        判断直连远端是否为可信代理。
        """

        try:
            parsed_ip = ip_address(remote_ip)
        except ValueError:
            return False
        return any(parsed_ip in network for network in self._trusted_networks)

    def _read_forwarded_header_ip(self, request: HTTPConnection) -> str | None:
        """
        从 Forwarded 头读取客户端 IP。
        """

        header_value = request.headers.get(FORWARDED_HEADER_NAME)
        if header_value is None:
            return None
        first_forwarded = header_value.split(FORWARDED_VALUE_SEPARATOR)[0]
        for part in first_forwarded.split(FORWARDED_PAIR_SEPARATOR):
            key, separator, value = part.partition(FORWARDED_KEY_VALUE_SEPARATOR)
            if separator == "" or key.strip().lower() != FORWARDED_FOR_KEY:
                continue
            return self._normalize_candidate_ip(value)
        return None

    def _read_x_forwarded_for_ip(self, request: HTTPConnection) -> str | None:
        """
        从 X-Forwarded-For 头读取客户端 IP。
        """

        header_value = request.headers.get(X_FORWARDED_FOR_HEADER_NAME)
        if header_value is None:
            return None
        return self._normalize_candidate_ip(header_value.split(X_FORWARDED_FOR_SEPARATOR)[0])

    def _normalize_candidate_ip(self, value: str) -> str | None:
        """
        归一化并校验候选客户端 IP。
        """

        candidate = value.strip().strip('"')
        if candidate.startswith(CLIENT_IP_BRACKET_LEFT):
            closing_index = candidate.find(CLIENT_IP_BRACKET_RIGHT)
            if closing_index > 0:
                candidate = candidate[1:closing_index]
        elif candidate.count(CLIENT_IP_PORT_SEPARATOR) == 1:
            host, port = candidate.rsplit(CLIENT_IP_PORT_SEPARATOR, maxsplit=1)
            if port.isdigit():
                candidate = host
        try:
            return str(ip_address(candidate))
        except ValueError:
            return None

    def _build_direct_result(self, *, remote_ip: str) -> ClientIpResolutionEnvelope:
        """
        构建直连解析结果。
        """

        return ClientIpResolutionEnvelope(
            header=ClientIpResolutionHeader(source=ClientIpResolutionKind.DIRECT),
            detail=DirectClientIpResolutionDetail(
                client_ip=remote_ip,
                remote_ip=remote_ip,
            ),
        )

    def _build_forwarded_result(
        self,
        *,
        client_ip: str,
        remote_ip: str,
        header_name: str,
    ) -> ClientIpResolutionEnvelope:
        """
        构建可信代理转发解析结果。
        """

        return ClientIpResolutionEnvelope(
            header=ClientIpResolutionHeader(source=ClientIpResolutionKind.TRUSTED_PROXY_FORWARDED),
            detail=TrustedProxyForwardedClientIpResolutionDetail(
                client_ip=client_ip,
                remote_ip=remote_ip,
                header_name=header_name,
            ),
        )
