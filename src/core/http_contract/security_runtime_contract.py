"""
安全运行时契约核心模块。
"""

from __future__ import annotations

from enum import StrEnum
from ipaddress import ip_network
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.core.security_contract.outbound_url_safety_contract import (
    OutboundUrlSafetyEnvelope,
)
from src.core.security_contract.rate_limit_policy_contract import (
    RateLimitPolicyEnvelope,
)
from src.core.security_contract.token_binding_contract import (
    TokenBindingEnvelope,
    TokenBindingMode,
)

SECURITY_RUNTIME_SCHEMA_VERSION: Final = "1.0"
SECURITY_RUNTIME_HEADER_KIND: Final = "security_runtime_header"
SECURITY_RUNTIME_ENVELOPE_KIND: Final = "security_runtime_envelope"
DEVELOPMENT_SECURITY_KIND: Final = "development_security"
PRODUCTION_SECURITY_KIND: Final = "production_security"
SECURITY_POLICY_NAME_MINIMUM_LENGTH = 1
SECURITY_LIMIT_MINIMUM_VALUE = 1
SECURITY_WINDOW_MINIMUM_SECONDS = 1
SECURITY_BLOCK_MINIMUM_SECONDS = 1
SECURITY_CACHE_TTL_MINIMUM_SECONDS = 1
SECURITY_BODY_SCHEME_HTTP = "http"
SECURITY_BODY_SCHEME_HTTPS = "https"
SECURITY_RATE_LIMIT_FAIL_CLOSED = "fail_closed"
TRUSTED_LOOPBACK_IPV4_CIDR = "127.0.0.0/8"
TRUSTED_LOOPBACK_IPV6_CIDR = "::1/128"
CLIENT_IP_TRUSTED_PROXY_CIDR_BLOCKS_MIN_LENGTH = 0
CLIENT_IP_TRUSTED_PROXY_CIDR_BLANK_MESSAGE = (
    "client_ip.trusted_proxy_cidr_blocks 不允许包含空白值。"
)


class RateLimitFailMode(StrEnum):
    """
    限流缓存故障处理模式枚举。
    """

    FAIL_CLOSED = SECURITY_RATE_LIMIT_FAIL_CLOSED


class FlowControlRuntimeDetail(BaseModel):
    """
    流控运行时扩展字段模型。

    :ivar enabled: 是否启用通用流控。
    :vartype enabled: bool
    :ivar default_limit: 默认窗口内允许请求数。
    :vartype default_limit: int
    :ivar default_window_seconds: 默认窗口秒数。
    :vartype default_window_seconds: int
    :ivar fail_mode: 缓存故障时的失败模式。
    :vartype fail_mode: RateLimitFailMode
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    default_limit: int = Field(default=120, ge=SECURITY_LIMIT_MINIMUM_VALUE)
    default_window_seconds: int = Field(
        default=60,
        ge=SECURITY_WINDOW_MINIMUM_SECONDS,
    )
    fail_mode: RateLimitFailMode = RateLimitFailMode.FAIL_CLOSED
    policies: list[RateLimitPolicyEnvelope] = Field(default_factory=list)


class RiskControlRuntimeDetail(BaseModel):
    """
    风控运行时扩展字段模型。

    :ivar enabled: 是否启用轻量风险信号。
    :vartype enabled: bool
    :ivar password_spray_limit: 密码喷洒疑似阈值。
    :vartype password_spray_limit: int
    :ivar password_spray_window_seconds: 密码喷洒疑似统计窗口。
    :vartype password_spray_window_seconds: int
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    password_spray_limit: int = Field(default=10, ge=SECURITY_LIMIT_MINIMUM_VALUE)
    password_spray_window_seconds: int = Field(
        default=300,
        ge=SECURITY_WINDOW_MINIMUM_SECONDS,
    )


class IpBlockRuntimeDetail(BaseModel):
    """
    IP 封禁运行时扩展字段模型。

    :ivar enabled: 是否启用 IP 封禁。
    :vartype enabled: bool
    :ivar cache_ttl_seconds: 封禁缓存 TTL 秒数。
    :vartype cache_ttl_seconds: int
    :ivar default_block_seconds: 默认封禁秒数。
    :vartype default_block_seconds: int
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    cache_ttl_seconds: int = Field(
        default=60,
        ge=SECURITY_CACHE_TTL_MINIMUM_SECONDS,
    )
    default_block_seconds: int = Field(
        default=900,
        ge=SECURITY_BLOCK_MINIMUM_SECONDS,
    )


class ClientIpRuntimeDetail(BaseModel):
    """
    客户端 IP 解析运行时扩展字段模型。

    :ivar trusted_proxy_cidr_blocks: 可信代理 CIDR 列表；空列表表示不信任任何代理头。
    :vartype trusted_proxy_cidr_blocks: list[str]
    """

    model_config = ConfigDict(extra="forbid")

    trusted_proxy_cidr_blocks: list[str] = Field(
        default_factory=lambda: [
            TRUSTED_LOOPBACK_IPV4_CIDR,
            TRUSTED_LOOPBACK_IPV6_CIDR,
        ],
        min_length=CLIENT_IP_TRUSTED_PROXY_CIDR_BLOCKS_MIN_LENGTH,
    )

    @model_validator(mode="after")
    def validate_trusted_proxy_cidr_blocks(self) -> ClientIpRuntimeDetail:
        """
        校验并归一化可信代理 CIDR 列表。
        """

        normalized_blocks: list[str] = []
        for cidr_block in self.trusted_proxy_cidr_blocks:
            normalized_block = cidr_block.strip()
            if normalized_block == "":
                raise ValueError(CLIENT_IP_TRUSTED_PROXY_CIDR_BLANK_MESSAGE)
            normalized_blocks.append(str(ip_network(normalized_block, strict=False)))
        self.trusted_proxy_cidr_blocks = normalized_blocks
        return self


class SecurityProtectionRuntimeDetail(BaseModel):
    """
    安全防护组合运行时配置。

    :ivar flow_control: 流控配置。
    :vartype flow_control: FlowControlRuntimeDetail
    :ivar risk_control: 风控配置。
    :vartype risk_control: RiskControlRuntimeDetail
    :ivar ip_block: IP 封禁配置。
    :vartype ip_block: IpBlockRuntimeDetail
    :ivar token_binding: Token-IP 绑定配置。
    :vartype token_binding: TokenBindingEnvelope
    :ivar outbound_url_safety: 出站 URL 安全配置。
    :vartype outbound_url_safety: OutboundUrlSafetyEnvelope
    """

    model_config = ConfigDict(extra="forbid")

    flow_control: FlowControlRuntimeDetail = Field(default_factory=FlowControlRuntimeDetail)
    risk_control: RiskControlRuntimeDetail = Field(default_factory=RiskControlRuntimeDetail)
    client_ip: ClientIpRuntimeDetail = Field(default_factory=ClientIpRuntimeDetail)
    ip_block: IpBlockRuntimeDetail = Field(default_factory=IpBlockRuntimeDetail)
    token_binding: TokenBindingEnvelope = Field(
        default_factory=lambda: TokenBindingEnvelope(
            enabled=False,
            mode=TokenBindingMode.HIGH_RISK_ONLY,
            ip_digest_ttl_seconds=900,
        )
    )
    outbound_url_safety: OutboundUrlSafetyEnvelope = Field(
        default_factory=lambda: OutboundUrlSafetyEnvelope(
            enabled=True,
            allowed_schemes=[SECURITY_BODY_SCHEME_HTTP, SECURITY_BODY_SCHEME_HTTPS],
            deny_private_networks=True,
            deny_metadata_address=True,
            deny_cidr_blocks=[],
            deny_hostnames=[],
        )
    )


class SecurityRuntimeMode(StrEnum):
    """
    安全运行时模式枚举。
    """

    DEVELOPMENT = DEVELOPMENT_SECURITY_KIND
    PRODUCTION = PRODUCTION_SECURITY_KIND


class SecurityRuntimeHeader(BaseModel):
    """
    安全运行时公共头字段模型。

    :ivar kind: 公共头类型标识。
    :vartype kind: Literal[SECURITY_RUNTIME_HEADER_KIND]
    :ivar schema_version: 结构模式版本。
    :vartype schema_version: Literal[SECURITY_RUNTIME_SCHEMA_VERSION]
    :ivar mode: 安全运行时模式。
    :vartype mode: SecurityRuntimeMode
    :ivar enabled: 安全策略是否启用。
    :vartype enabled: bool
    :ivar policy_name: 安全策略名称。
    :vartype policy_name: str
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["security_runtime_header"] = SECURITY_RUNTIME_HEADER_KIND
    schema_version: Literal["1.0"] = SECURITY_RUNTIME_SCHEMA_VERSION
    mode: SecurityRuntimeMode
    enabled: bool
    policy_name: str = Field(min_length=SECURITY_POLICY_NAME_MINIMUM_LENGTH)


class DevelopmentSecurityRuntimeDetail(BaseModel):
    """
    开发安全运行时扩展字段模型。

    :ivar kind: 扩展字段类型标识。
    :vartype kind: Literal[DEVELOPMENT_SECURITY_KIND]
    :ivar schema_version: 结构模式版本。
    :vartype schema_version: Literal[SECURITY_RUNTIME_SCHEMA_VERSION]
    :ivar expose_openapi: 是否允许暴露 OpenAPI。
    :vartype expose_openapi: bool
    :ivar expose_system_info: 是否允许匿名暴露系统信息。
    :vartype expose_system_info: bool
    :ivar require_external_jwt_secret: 是否要求 JWT 密钥来自外部注入。
    :vartype require_external_jwt_secret: bool
    :ivar require_distributed_auth_throttle: 是否要求分布式鉴权节流。
    :vartype require_distributed_auth_throttle: bool
    :ivar enable_hsts: 是否启用 HSTS。
    :vartype enable_hsts: bool
    :ivar enable_csp: 是否启用 CSP。
    :vartype enable_csp: bool
    :ivar protection: 安全防护策略配置。
    :vartype protection: SecurityProtectionRuntimeDetail
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["development_security"] = DEVELOPMENT_SECURITY_KIND
    schema_version: Literal["1.0"] = SECURITY_RUNTIME_SCHEMA_VERSION
    expose_openapi: bool
    expose_system_info: bool
    require_external_jwt_secret: bool
    require_distributed_auth_throttle: bool
    enable_hsts: bool
    enable_csp: bool
    protection: SecurityProtectionRuntimeDetail = Field(
        default_factory=SecurityProtectionRuntimeDetail
    )


class ProductionSecurityRuntimeDetail(BaseModel):
    """
    生产安全运行时扩展字段模型。

    :ivar kind: 扩展字段类型标识。
    :vartype kind: Literal[PRODUCTION_SECURITY_KIND]
    :ivar schema_version: 结构模式版本。
    :vartype schema_version: Literal[SECURITY_RUNTIME_SCHEMA_VERSION]
    :ivar expose_openapi: 是否允许暴露 OpenAPI。
    :vartype expose_openapi: bool
    :ivar expose_system_info: 是否允许匿名暴露系统信息。
    :vartype expose_system_info: bool
    :ivar require_external_jwt_secret: 是否要求 JWT 密钥来自外部注入。
    :vartype require_external_jwt_secret: bool
    :ivar require_distributed_auth_throttle: 是否要求分布式鉴权节流。
    :vartype require_distributed_auth_throttle: bool
    :ivar enable_hsts: 是否启用 HSTS。
    :vartype enable_hsts: bool
    :ivar enable_csp: 是否启用 CSP。
    :vartype enable_csp: bool
    :ivar protection: 安全防护策略配置。
    :vartype protection: SecurityProtectionRuntimeDetail
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["production_security"] = PRODUCTION_SECURITY_KIND
    schema_version: Literal["1.0"] = SECURITY_RUNTIME_SCHEMA_VERSION
    expose_openapi: bool = False
    expose_system_info: bool = False
    require_external_jwt_secret: bool = True
    require_distributed_auth_throttle: bool = True
    enable_hsts: bool = True
    enable_csp: bool = True
    protection: SecurityProtectionRuntimeDetail = Field(
        default_factory=SecurityProtectionRuntimeDetail
    )


SecurityRuntimeDetailUnion = Annotated[
    DevelopmentSecurityRuntimeDetail | ProductionSecurityRuntimeDetail,
    Field(discriminator="kind"),
]


class SecurityRuntimeEnvelope(BaseModel):
    """
    安全运行时信封模型。

    :ivar envelope_kind: 外层信封类型标识。
    :vartype envelope_kind: Literal[SECURITY_RUNTIME_ENVELOPE_KIND]
    :ivar schema_version: 外层信封版本。
    :vartype schema_version: Literal[SECURITY_RUNTIME_SCHEMA_VERSION]
    :ivar header: 安全运行时公共头字段。
    :vartype header: SecurityRuntimeHeader
    :ivar detail: 安全运行时强类型扩展字段。
    :vartype detail: SecurityRuntimeDetailUnion
    """

    model_config = ConfigDict(extra="forbid")

    envelope_kind: Literal["security_runtime_envelope"] = SECURITY_RUNTIME_ENVELOPE_KIND
    schema_version: Literal["1.0"] = SECURITY_RUNTIME_SCHEMA_VERSION
    header: SecurityRuntimeHeader
    detail: SecurityRuntimeDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> SecurityRuntimeEnvelope:
        """
        校验公共头字段与扩展字段一致性。

        :returns: 当前模型实例。
        :rtype: SecurityRuntimeEnvelope
        :raises ValueError: 当模式或版本不一致时抛出。
        """

        if self.header.mode.value != self.detail.kind:
            raise ValueError("安全运行时 mode 必须与 detail.kind 一致。")
        if self.schema_version != self.header.schema_version:
            raise ValueError(
                "安全运行时 envelope schema_version 必须与 header.schema_version 一致。"
            )
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("安全运行时 header.schema_version 必须与 detail.schema_version 一致。")
        return self
