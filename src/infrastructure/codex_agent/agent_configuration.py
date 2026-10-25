"""Windows Codex Host Agent 本地配置。"""

from __future__ import annotations

import ssl
import tomllib
from collections.abc import Mapping
from ipaddress import ip_address
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.codex_contract.agent_release_manifest_contract import (
    AGENT_RELEASE_MANIFEST_TARGET_PATH,
)
from src.core.codex_contract.connection_session_contract import (
    CodexConnectionProtocolVersion,
)
from src.core.codex_contract.execution_root_binding_contract import WorktreeIsolationMode
from src.core.codex_contract.workspace_contract import ProjectExecutionOverrides
from src.domain.codex.agent_command_policy import AgentAppServerSecurityPolicy
from src.infrastructure.codex_agent.agent_deployment_profile import (
    AgentDeploymentProfile,
    resolve_agent_deployment_paths,
)
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentConfigPermissionVerifierPort,
    AgentWorkspaceDefinition,
)

DEFAULT_AGENT_STATE_DIRECTORY: Final = resolve_agent_deployment_paths(
    AgentDeploymentProfile.PRODUCTION
).state_directory
MAX_APP_SERVER_LINE_BYTES: Final = 4 * 1024 * 1024
DEFAULT_AGENT_EVENT_BATCH_WINDOW_MILLISECONDS: Final = 25
DEFAULT_AGENT_EVENT_BATCH_MAX_BYTES: Final = 16 * 1024
DEFAULT_AGENT_WRITER_QUEUE_CAPACITY: Final = 256
DEFAULT_AGENT_SNAPSHOT_PAGE_SIZE: Final = 100
MAX_AGENT_SNAPSHOT_PAGE_SIZE: Final = 500
SHA256_HEX_LENGTH: Final = 64
AGENT_WEBSOCKET_PATH: Final = "/internal/codex-agents/connect"
AGENT_VERIFICATION_PATH: Final = "/codex/verify-device"


def build_agent_tls_context(
    *,
    deployment_profile: AgentDeploymentProfile,
    development_ca_certificate_path: Path | None,
) -> ssl.SSLContext | None:
    """为开发 Agent 构建额外 CA 的严格 TLS 上下文。"""

    if development_ca_certificate_path is None:
        return None
    if deployment_profile is not AgentDeploymentProfile.DEVELOPMENT:
        raise ValueError("仅development Agent允许配置development_ca_certificate_path。")
    if not development_ca_certificate_path.is_absolute():
        raise ValueError("development_ca_certificate_path必须是绝对路径。")
    if not development_ca_certificate_path.is_file():
        raise ValueError("development_ca_certificate_path必须指向可读取的CA证书文件。")

    # 仅在系统默认信任链之上增加开发 CA，绝不关闭服务端证书校验。
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=str(development_ca_certificate_path))
    return context


def validate_public_endpoint_url(value: str, *, expected_scheme: str) -> str:
    """Validate a credential-free public URL with the required TLS scheme."""

    normalized = value.rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() != expected_scheme or not parsed.hostname:
        raise ValueError(f"Agent正式入口必须使用{expected_scheme.upper()}。")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Agent正式入口不允许在URL中携带凭据。")
    if parsed.fragment:
        raise ValueError("Agent正式入口不允许携带fragment。")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith((".localhost", ".lan", ".local")):
        raise ValueError("Agent正式入口不能使用本地主机名。")
    if hostname == "example.com" or hostname.endswith(
        (".example.com", ".example", ".invalid", ".test")
    ):
        raise ValueError("Agent正式入口不能使用示例或保留域名。")
    try:
        address = ip_address(hostname)
    except ValueError:
        return normalized
    if not address.is_global:
        raise ValueError("Agent正式入口不能使用非公网IP地址。")
    return normalized


def validate_development_endpoint_url(value: str, *, expected_scheme: str) -> str:
    """校验仅供 Development 安装包使用的 TLS 控制面地址。

    开发控制面仍必须使用 HTTPS/WSS，且不能接收 localhost 或任意 IP。``.lan``
    域名只会由 Development profile 消费，生产 bootstrap 仍使用严格的公网校验器。
    """

    normalized = value.rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() != expected_scheme or not parsed.hostname:
        raise ValueError(f"Agent开发入口必须使用{expected_scheme.upper()}。")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Agent开发入口不允许在URL中携带凭据。")
    if parsed.fragment:
        raise ValueError("Agent开发入口不允许携带fragment。")
    hostname = parsed.hostname.rstrip(".").lower()
    try:
        ip_address(hostname)
    except ValueError:
        if not hostname.endswith(".lan"):
            raise ValueError("Agent开发入口只能使用受控.lan主机名。") from None
    else:
        raise ValueError("Agent开发入口不能使用IP地址。")
    return normalized


def _normalize_public_origin_url(value: str) -> str:
    """Normalize one credential-free public HTTPS origin."""

    normalized = validate_public_endpoint_url(value, expected_scheme="https")
    parsed = urlsplit(normalized)
    if parsed.path not in ("", "/") or parsed.query:
        raise ValueError("Agent公网origin只能包含scheme、主机和可选端口。")
    return f"https://{parsed.netloc}"


def _normalize_development_origin_url(value: str) -> str:
    """规范化 Development profile 的单一 TLS origin。"""

    normalized = validate_development_endpoint_url(value, expected_scheme="https")
    parsed = urlsplit(normalized)
    if parsed.path not in ("", "/") or parsed.query:
        raise ValueError("Agent开发origin只能包含scheme、主机和可选端口。")
    return f"https://{parsed.netloc}"


def validate_local_endpoint_url(value: str, *, expected_scheme: str) -> str:
    """Validate a credential-free loopback URL for local acceptance builds."""

    normalized = value.rstrip("/")
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() != expected_scheme or not parsed.hostname:
        raise ValueError(f"Agent本地入口必须使用{expected_scheme.upper()}。")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Agent本地入口不允许在URL中携带凭据。")
    if parsed.fragment:
        raise ValueError("Agent本地入口不允许携带fragment。")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost":
        return normalized
    try:
        address = ip_address(hostname)
    except ValueError as exc:
        raise ValueError("Agent本地入口只允许localhost、127.0.0.1或::1。") from exc
    if str(address) not in {"127.0.0.1", "::1"}:
        raise ValueError("Agent本地入口只允许localhost、127.0.0.1或::1。")
    return normalized


def _normalize_local_origin_url(value: str) -> str:
    """Normalize one credential-free loopback HTTP origin."""

    normalized = validate_local_endpoint_url(value, expected_scheme="http")
    parsed = urlsplit(normalized)
    if parsed.path not in ("", "/") or parsed.query:
        raise ValueError("Agent本地origin只能包含scheme、主机和可选端口。")
    return f"http://{parsed.netloc}"


def _resolve_tls_authority(value: str) -> tuple[str, int]:
    """Resolve the canonical host and port shared by HTTPS and WSS."""

    parsed = urlsplit(value)
    if parsed.hostname is None:
        raise ValueError("Agent正式入口必须包含有效主机名。")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Agent正式入口端口无效。") from exc
    return parsed.hostname.rstrip(".").lower(), port or 443


def _resolve_local_authority(value: str) -> tuple[str, int]:
    """Resolve the canonical loopback host and port shared by HTTP and WS."""

    parsed = urlsplit(value)
    if parsed.hostname is None:
        raise ValueError("Agent本地入口必须包含有效主机名。")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Agent本地入口端口无效。") from exc
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname != "localhost":
        hostname = str(ip_address(hostname))
    return hostname, port or 80


class AgentProtocolSettings(BaseModel):
    """Agent 与控制面/App Server 的版本边界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_schema_version: CodexConnectionProtocolVersion
    agent_version: str = Field(default="0.1.0", min_length=1, max_length=64)
    expected_codex_version: str = Field(min_length=1, max_length=64)
    app_server_schema_digest: str = Field(min_length=64, max_length=128)
    allow_experimental_api: bool = True


class AgentReleaseBootstrapSettings(BaseModel):
    """安装包内公开的可信更新入口与本地边界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    manifest_target_path: Literal["codex-agent-release.json"] = AGENT_RELEASE_MANIFEST_TARGET_PATH
    repository_url: str = Field(min_length=1, max_length=2_048)
    repository_host_allowlist: tuple[str, ...] = Field(min_length=1)
    authenticode_signer_sha256_allowlist: tuple[str, ...] = Field(min_length=1)
    trusted_root_file_name: str = Field(min_length=1, max_length=128)
    max_download_bytes: int = Field(gt=0)
    request_timeout_seconds: int = Field(gt=0, le=600)
    retained_versions: int = Field(ge=1, le=20)
    health_timeout_seconds: int = Field(gt=0, le=600)
    rollback_budget: int = Field(ge=1, le=10)
    minimum_security_version: str = Field(min_length=1, max_length=64)

    @field_validator("repository_url")
    @classmethod
    def validate_https_url(cls, value: str) -> str:
        """更新入口必须使用 HTTPS。"""

        return validate_public_endpoint_url(value, expected_scheme="https")

    @field_validator("repository_host_allowlist")
    @classmethod
    def validate_repository_hosts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Allow only normalized host names in the update allowlist."""

        normalized = tuple(value.rstrip(".").lower() for value in values)
        if any(not value or "://" in value or "/" in value or "@" in value for value in normalized):
            raise ValueError("发布仓库allowlist只允许规范化主机名。")
        return normalized

    @field_validator("authenticode_signer_sha256_allowlist")
    @classmethod
    def validate_signer_allowlist(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Pin Authenticode signing certificates by SHA-256 fingerprint."""

        normalized = tuple(value.lower() for value in values)
        if any(
            len(value) != SHA256_HEX_LENGTH
            or any(character not in "0123456789abcdef" for character in value)
            for value in normalized
        ):
            raise ValueError("Authenticode签名证书指纹必须是SHA-256十六进制。")
        return normalized

    @field_validator("trusted_root_file_name")
    @classmethod
    def validate_trusted_root_file_name(cls, value: str) -> str:
        """可信根必须是安装目录中的单一文件名。"""

        if Path(value).name != value:
            raise ValueError("TUF可信根只允许使用安装目录文件名。")
        return value

    @model_validator(mode="after")
    def validate_repository_boundary(self) -> AgentReleaseBootstrapSettings:
        """Keep the repository on the explicit trusted host allowlist."""

        repository_host = urlsplit(self.repository_url).hostname
        if repository_host is None:
            raise ValueError("自动更新发布地址必须包含有效主机名。")
        if repository_host.rstrip(".").lower() not in self.repository_host_allowlist:
            raise ValueError("制品仓库主机必须存在于allowlist中。")
        return self


class AgentBootstrapConnectionSettings(BaseModel):
    """安装包内不含凭据的正式控制面入口。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_url: str = Field(min_length=1, max_length=2_048)
    websocket_url: str = Field(min_length=1, max_length=2_048)
    verification_url: str = Field(min_length=1, max_length=2_048)
    website_url: str = Field(min_length=1, max_length=2_048)

    @field_validator("api_url", "verification_url", "website_url")
    @classmethod
    def validate_https_url(cls, value: str) -> str:
        """正式浏览器和 API 入口必须是公开 HTTPS URL。"""

        return validate_public_endpoint_url(value, expected_scheme="https")

    @field_validator("websocket_url")
    @classmethod
    def validate_websocket_url(cls, value: str) -> str:
        """正式控制通道必须是公开 WSS URL。"""

        return validate_public_endpoint_url(value, expected_scheme="wss")

    @model_validator(mode="after")
    def validate_single_origin_boundary(self) -> AgentBootstrapConnectionSettings:
        """Require one public TLS origin and the production endpoint paths."""

        endpoints = (
            ("API", self.api_url, ""),
            ("WebSocket", self.websocket_url, AGENT_WEBSOCKET_PATH),
            ("设备验证", self.verification_url, AGENT_VERIFICATION_PATH),
            ("网站", self.website_url, ""),
        )
        for endpoint_name, endpoint_url, expected_path in endpoints:
            parsed = urlsplit(endpoint_url)
            actual_path = parsed.path.rstrip("/")
            if actual_path != expected_path or parsed.query:
                raise ValueError(f"Agent{endpoint_name}入口路径或查询参数不符合发布契约。")
        authorities = {_resolve_tls_authority(endpoint_url) for _, endpoint_url, _ in endpoints}
        if len(authorities) != 1:
            raise ValueError("Agent所有正式入口必须属于同一公网origin。")
        return self

    @classmethod
    def from_public_origin(cls, public_origin: str) -> AgentBootstrapConnectionSettings:
        """Derive every production endpoint from one public HTTPS origin."""

        normalized_origin = _normalize_public_origin_url(public_origin)
        authority = urlsplit(normalized_origin).netloc
        return cls(
            api_url=normalized_origin,
            websocket_url=f"wss://{authority}{AGENT_WEBSOCKET_PATH}",
            verification_url=f"{normalized_origin}{AGENT_VERIFICATION_PATH}",
            website_url=normalized_origin,
        )


class AgentDevelopmentBootstrapConnectionSettings(BaseModel):
    """Development MSI 的受限 TLS 控制面入口。

    本类型仅允许 ``.lan`` 主机名。它不能被 production profile 消费，从而既保留
    开发 Caddy 的 HTTPS/WSS 验收能力，也不会放宽正式发布包的公网边界。
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_url: str = Field(min_length=1, max_length=2_048)
    websocket_url: str = Field(min_length=1, max_length=2_048)
    verification_url: str = Field(min_length=1, max_length=2_048)
    website_url: str = Field(min_length=1, max_length=2_048)

    @field_validator("api_url", "verification_url", "website_url")
    @classmethod
    def validate_https_url(cls, value: str) -> str:
        """开发浏览器和 API 入口仍必须使用 TLS。"""

        return validate_development_endpoint_url(value, expected_scheme="https")

    @field_validator("websocket_url")
    @classmethod
    def validate_websocket_url(cls, value: str) -> str:
        """开发 Agent 控制通道仍必须使用 WSS。"""

        return validate_development_endpoint_url(value, expected_scheme="wss")

    @model_validator(mode="after")
    def validate_single_origin_boundary(self) -> AgentDevelopmentBootstrapConnectionSettings:
        """要求全部 Development endpoint 来自同一受控 TLS origin。"""

        endpoints = (
            ("API", self.api_url, ""),
            ("WebSocket", self.websocket_url, AGENT_WEBSOCKET_PATH),
            ("设备验证", self.verification_url, AGENT_VERIFICATION_PATH),
            ("网站", self.website_url, ""),
        )
        for endpoint_name, endpoint_url, expected_path in endpoints:
            parsed = urlsplit(endpoint_url)
            actual_path = parsed.path.rstrip("/")
            if actual_path != expected_path or parsed.query:
                raise ValueError(f"Agent开发{endpoint_name}入口路径或查询参数不符合发布契约。")
        authorities = {_resolve_tls_authority(endpoint_url) for _, endpoint_url, _ in endpoints}
        if len(authorities) != 1:
            raise ValueError("Agent所有开发入口必须属于同一TLS origin。")
        return self

    @classmethod
    def from_development_origin(cls, value: str) -> AgentDevelopmentBootstrapConnectionSettings:
        """从单一开发 HTTPS origin 推导 API、WSS 与验证 endpoint。"""

        normalized_origin = _normalize_development_origin_url(value)
        authority = urlsplit(normalized_origin).netloc
        return cls(
            api_url=normalized_origin,
            websocket_url=f"wss://{authority}{AGENT_WEBSOCKET_PATH}",
            verification_url=f"{normalized_origin}{AGENT_VERIFICATION_PATH}",
            website_url=normalized_origin,
        )


class AgentLocalBootstrapConnectionSettings(BaseModel):
    """仅供本机验收使用的回环控制面入口。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    api_url: str = Field(min_length=1, max_length=2_048)
    websocket_url: str = Field(min_length=1, max_length=2_048)
    verification_url: str = Field(min_length=1, max_length=2_048)
    website_url: str = Field(min_length=1, max_length=2_048)

    @field_validator("api_url", "verification_url", "website_url")
    @classmethod
    def validate_http_url(cls, value: str) -> str:
        """本地浏览器和 API 入口只能使用回环 HTTP URL。"""

        return validate_local_endpoint_url(value, expected_scheme="http")

    @field_validator("websocket_url")
    @classmethod
    def validate_websocket_url(cls, value: str) -> str:
        """本地控制通道只能使用回环 WS URL。"""

        return validate_local_endpoint_url(value, expected_scheme="ws")

    @model_validator(mode="after")
    def validate_single_origin_boundary(self) -> AgentLocalBootstrapConnectionSettings:
        """Require one loopback origin and the production endpoint paths."""

        endpoints = (
            ("API", self.api_url, ""),
            ("WebSocket", self.websocket_url, AGENT_WEBSOCKET_PATH),
            ("设备验证", self.verification_url, AGENT_VERIFICATION_PATH),
            ("网站", self.website_url, ""),
        )
        for endpoint_name, endpoint_url, expected_path in endpoints:
            parsed = urlsplit(endpoint_url)
            actual_path = parsed.path.rstrip("/")
            if actual_path != expected_path or parsed.query:
                raise ValueError(f"Agent本地{endpoint_name}入口路径或查询参数不符合发布契约。")
        authorities = {_resolve_local_authority(endpoint_url) for _, endpoint_url, _ in endpoints}
        if len(authorities) != 1:
            raise ValueError("Agent所有本地入口必须属于同一回环origin。")
        return self

    @classmethod
    def from_local_origin(
        cls,
        local_origin: str,
    ) -> AgentLocalBootstrapConnectionSettings:
        """Derive every local endpoint from one loopback HTTP origin."""

        normalized_origin = _normalize_local_origin_url(local_origin)
        authority = urlsplit(normalized_origin).netloc
        return cls(
            api_url=normalized_origin,
            websocket_url=f"ws://{authority}{AGENT_WEBSOCKET_PATH}",
            verification_url=f"{normalized_origin}{AGENT_VERIFICATION_PATH}",
            website_url=normalized_origin,
        )


class AgentBootstrapSettings(BaseModel):
    """安装包写入的首次连接公开配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    deployment_state: Literal["configured", "development", "local", "unconfigured"]
    connection: (
        AgentBootstrapConnectionSettings
        | AgentDevelopmentBootstrapConnectionSettings
        | AgentLocalBootstrapConnectionSettings
        | None
    ) = None
    agent_version: str = Field(min_length=1, max_length=64)
    expected_codex_version: str = Field(min_length=1, max_length=64)
    app_server_schema_digest: str = Field(min_length=64, max_length=128)
    default_workspace_key: str = Field(default="default", min_length=1, max_length=128)
    default_workspace_name: str = Field(default="默认工作区", min_length=1, max_length=128)
    release: AgentReleaseBootstrapSettings | None = None

    @model_validator(mode="after")
    def validate_deployment_state(self) -> AgentBootstrapSettings:
        """未配置包不得暗含入口或开启自动更新。"""

        if self.deployment_state == "configured":
            if not isinstance(self.connection, AgentBootstrapConnectionSettings):
                raise ValueError("已配置Agent安装包必须包含正式控制面入口。")
            return self
        if self.deployment_state == "development":
            if not isinstance(self.connection, AgentDevelopmentBootstrapConnectionSettings):
                raise ValueError("开发Agent安装包必须包含受控开发TLS入口。")
            if self.release is not None:
                raise ValueError("开发Agent安装包不得启用自动更新。")
            return self
        if self.deployment_state == "local":
            if not isinstance(self.connection, AgentLocalBootstrapConnectionSettings):
                raise ValueError("本地验收Agent安装包必须包含回环控制面入口。")
            if self.release is not None:
                raise ValueError("本地验收Agent安装包不得启用自动更新。")
            return self
        if self.connection is not None or self.release is not None:
            raise ValueError("未配置Agent安装包不得包含控制面或自动更新入口。")
        return self

    def require_connection(
        self,
    ) -> (
        AgentBootstrapConnectionSettings
        | AgentDevelopmentBootstrapConnectionSettings
        | AgentLocalBootstrapConnectionSettings
    ):
        """返回已验证的控制面入口；未配置包以明确错误拒绝注册。"""

        if self.connection is None:
            raise ValueError("安装包尚未配置正式服务器地址，请安装正式发布版本。")
        return self.connection

    def validate_deployment_profile(self, deployment_profile: AgentDeploymentProfile) -> None:
        """阻止开发 bootstrap 被生产 Agent 消费，反之亦然。"""

        is_development_bootstrap = self.deployment_state == "development"
        is_development_profile = deployment_profile is AgentDeploymentProfile.DEVELOPMENT
        if is_development_bootstrap and not is_development_profile:
            raise ValueError("开发Agent安装包只能由development profile启动。")
        if is_development_profile and not is_development_bootstrap:
            raise ValueError("development profile只能使用开发Agent安装包。")

    def require_connection_for_profile(
        self,
        deployment_profile: AgentDeploymentProfile,
    ) -> (
        AgentBootstrapConnectionSettings
        | AgentDevelopmentBootstrapConnectionSettings
        | AgentLocalBootstrapConnectionSettings
    ):
        """先校验 profile 隔离边界，再返回当前安装包的控制面入口。"""

        self.validate_deployment_profile(deployment_profile)
        return self.require_connection()


class AgentBootstrapSettingsLoader:
    """加载安装包内不含敏感信息的首次连接配置。"""

    def load(self, path: str | Path) -> AgentBootstrapSettings:
        """读取并校验首次连接 TOML。"""

        with Path(path).open("rb") as stream:
            return AgentBootstrapSettings.model_validate(tomllib.load(stream))


class AgentProcessSettings(BaseModel):
    """Agent 进程、连接和本地状态配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    host_id: UUID
    key_id: UUID | None = None
    legacy_credential_id: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    deployment_profile: AgentDeploymentProfile = AgentDeploymentProfile.PRODUCTION
    control_plane_url: str = Field(min_length=1)
    control_plane_api_url: str = Field(min_length=1)
    development_ca_certificate_path: Path | None = None
    codex_binary: str = Field(default="codex", min_length=1)
    network_mode: Literal["system", "direct", "explicit"] = "system"
    proxy_url: str | None = Field(default=None, repr=False)
    ca_certificate_path: Path | None = None
    heartbeat_seconds: int = Field(default=15, ge=15, le=15)
    send_enqueue_timeout_seconds: float = Field(default=1.0, gt=0)
    send_timeout_seconds: float = Field(default=10.0, gt=0)
    close_timeout_seconds: float = Field(default=3.0, gt=0)
    connection_attempt_timeout_seconds: float = Field(default=20.0, gt=0)
    ping_timeout_seconds: float = Field(default=30.0, gt=0)
    renewal_response_timeout_seconds: float = Field(default=30.0, gt=15)
    writer_queue_max_bytes: int = Field(default=16 * 1024 * 1024, gt=0)
    reconnect_min_seconds: int = Field(default=1, gt=0)
    reconnect_max_seconds: int = Field(default=5, gt=0)
    max_buffered_events: int = Field(default=2000, gt=0)
    writer_queue_capacity: int = Field(
        default=DEFAULT_AGENT_WRITER_QUEUE_CAPACITY,
        ge=16,
        le=65_536,
    )
    event_batch_window_milliseconds: int = Field(
        default=DEFAULT_AGENT_EVENT_BATCH_WINDOW_MILLISECONDS,
        ge=10,
        le=1_000,
    )
    event_batch_max_bytes: int = Field(
        default=DEFAULT_AGENT_EVENT_BATCH_MAX_BYTES,
        ge=256,
        le=65_536,
    )
    snapshot_page_size: int = Field(
        default=DEFAULT_AGENT_SNAPSHOT_PAGE_SIZE,
        ge=1,
        le=MAX_AGENT_SNAPSHOT_PAGE_SIZE,
    )
    reconnect_jitter_ratio: float = Field(default=0.2, ge=0, le=1)
    max_app_server_line_bytes: int = Field(
        default=MAX_APP_SERVER_LINE_BYTES,
        gt=0,
        le=MAX_APP_SERVER_LINE_BYTES,
    )
    state_database: Path = Field(
        default_factory=lambda: (
            resolve_agent_deployment_paths(AgentDeploymentProfile.PRODUCTION).state_database
        )
    )

    @model_validator(mode="before")
    @classmethod
    def default_state_database_for_deployment_profile(cls, value: object) -> object:
        """按 profile 补齐状态库，避免开发配置隐式复用生产状态。"""

        if not isinstance(value, Mapping):
            return value
        if "state_database" in value:
            return value
        profile_value = value.get("deployment_profile", AgentDeploymentProfile.PRODUCTION)
        try:
            profile = AgentDeploymentProfile(profile_value)
        except ValueError:
            return value
        resolved = dict(value)
        resolved["state_database"] = resolve_agent_deployment_paths(profile).state_database
        return resolved

    @field_validator("control_plane_url")
    @classmethod
    def validate_control_plane_url(cls, value: str) -> str:
        """只允许 WebSocket URL，生产 URL 必须使用 TLS。"""

        if not value.startswith(("ws://", "wss://")):
            raise ValueError("control_plane_url必须使用ws://或wss://。")
        return value

    @field_validator("control_plane_api_url")
    @classmethod
    def validate_control_plane_api_url(cls, value: str) -> str:
        """只允许 HTTP API URL，生产环境由安装配置固定为 HTTPS。"""

        if not value.startswith(("http://", "https://")):
            raise ValueError("control_plane_api_url必须使用http://或https://。")
        return value

    @model_validator(mode="after")
    def validate_reconnect_boundaries(self) -> AgentProcessSettings:
        """校验退避边界与开发 TLS 信任范围。"""

        if self.reconnect_max_seconds < self.reconnect_min_seconds:
            raise ValueError("reconnect_max_seconds不得小于reconnect_min_seconds。")
        if (self.network_mode == "explicit") != (self.proxy_url is not None):
            raise ValueError("仅explicit网络模式必须配置proxy_url。")
        if self.proxy_url is not None:
            proxy = urlsplit(self.proxy_url)
            if proxy.scheme not in {"http", "https"} or not proxy.hostname:
                raise ValueError("proxy_url必须是HTTP或HTTPS代理地址。")
        if self.ca_certificate_path is not None:
            if self.development_ca_certificate_path is not None:
                raise ValueError("CA来源只能配置一处。")
            if not self.ca_certificate_path.is_absolute() or not self.ca_certificate_path.is_file():
                raise ValueError("ca_certificate_path必须是可读取的绝对路径。")
        if self.writer_queue_max_bytes < 2 * self.max_app_server_line_bytes:
            raise ValueError("发送队列必须预留控制帧空间。")
        if self.event_batch_max_bytes >= self.max_app_server_line_bytes:
            raise ValueError("event_batch_max_bytes必须小于Agent单帧上限。")
        if self.development_ca_certificate_path is not None:
            build_agent_tls_context(
                deployment_profile=self.deployment_profile,
                development_ca_certificate_path=self.development_ca_certificate_path,
            )
        return self


class AgentWorkspaceSettings(BaseModel):
    """本地 TOML 中的一项工作区白名单。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    root: Path
    allow_write: bool = False
    worktree_isolation_mode: WorktreeIsolationMode = WorktreeIsolationMode.DISABLED
    execution_overrides: ProjectExecutionOverrides = Field(
        default_factory=ProjectExecutionOverrides
    )
    execution_revision: int = Field(default=0, ge=0)

    @field_validator("root")
    @classmethod
    def validate_absolute_root(cls, value: Path) -> Path:
        """拒绝依赖 Agent 当前目录解释的相对工作区。"""

        if not value.is_absolute():
            raise ValueError("工作区root必须是绝对路径。")
        return value

    def to_definition(self) -> AgentWorkspaceDefinition:
        """转换为不依赖 Pydantic 的本地 registry 对象。"""

        return AgentWorkspaceDefinition(
            key=self.key,
            display_name=self.display_name,
            root=self.root,
            allow_write=self.allow_write,
            worktree_isolation_mode=self.worktree_isolation_mode,
        )


class AgentAppServerSecuritySettings(BaseModel):
    """冻结 Agent 对本机 App Server 的最低安全执行策略。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_policy: Literal["untrusted", "on-request", "never"] = "untrusted"
    approvals_reviewer: Literal["user"] = "user"
    sandbox_mode: Literal["workspace-write"] = "workspace-write"

    def to_policy(self) -> AgentAppServerSecurityPolicy:
        """转换为命令策略使用的领域值对象。"""

        return AgentAppServerSecurityPolicy(
            approval_policy=self.approval_policy,
            approvals_reviewer=self.approvals_reviewer,
            sandbox_mode=self.sandbox_mode,
        )


class CodexHostAgentSettings(BaseModel):
    """Agent 本地完整强类型配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent: AgentProcessSettings
    protocol: AgentProtocolSettings
    app_server_security: AgentAppServerSecuritySettings = Field(
        default_factory=AgentAppServerSecuritySettings
    )
    workspaces: list[AgentWorkspaceSettings] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_workspace_keys(self) -> CodexHostAgentSettings:
        """拒绝歧义工作区 key。"""

        keys = [workspace.key for workspace in self.workspaces]
        if len(keys) != len(set(keys)):
            raise ValueError("workspaces.key不允许重复。")
        roots = [str(workspace.root.resolve()).casefold() for workspace in self.workspaces]
        if len(roots) != len(set(roots)):
            raise ValueError("同一真实项目目录不允许重复配置。")
        if self.protocol.agent_schema_version == CodexConnectionProtocolVersion.V2:
            if self.agent.key_id is None:
                raise ValueError("Agent v2配置必须包含设备key_id。")
        elif self.agent.legacy_credential_id is None:
            raise ValueError("Agent v1迁移配置必须包含legacy_credential_id。")
        return self


class CodexHostAgentSettingsLoader:
    """校验文件权限后加载 Agent TOML。"""

    def __init__(self, permission_verifier: AgentConfigPermissionVerifierPort) -> None:
        self._permission_verifier = permission_verifier

    def load(self, path: str | Path) -> CodexHostAgentSettings:
        """读取本地配置；设备 token 不属于该文件契约。"""

        config_path = Path(path)
        self._permission_verifier.verify(config_path)
        with config_path.open("rb") as stream:
            raw_settings = tomllib.load(stream)
        return CodexHostAgentSettings.model_validate(raw_settings)
