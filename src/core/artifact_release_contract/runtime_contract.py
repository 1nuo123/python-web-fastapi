"""制品发布运行时配置。"""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHA256_HEX_LENGTH = 64


class ArtifactReleaseRuntimeSettings(BaseModel):
    """TUF、下载、暂存和回滚边界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    trusted_root_path: str = Field(min_length=1)
    repository_url: str = Field(min_length=1)
    repository_host_allowlist: tuple[str, ...] = Field(min_length=1)
    authenticode_signer_sha256_allowlist: tuple[str, ...] = ()
    max_download_bytes: int = Field(gt=0)
    request_timeout_seconds: int = Field(gt=0, le=600)
    staging_root: str = Field(min_length=1)
    retained_versions: int = Field(ge=1, le=20)
    health_timeout_seconds: int = Field(gt=0, le=600)
    rollback_budget: int = Field(ge=1, le=10)
    minimum_security_version: str | None = Field(default=None, max_length=128)

    @field_validator("repository_url")
    @classmethod
    def validate_repository_url(cls, value: str) -> str:
        """只允许 HTTPS 制品仓库。"""

        normalized = value.rstrip("/")
        parsed = urlsplit(normalized)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise ValueError("制品仓库必须使用HTTPS。")
        if parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise ValueError("制品仓库URL不允许携带凭据或fragment。")
        hostname = parsed.hostname.rstrip(".").lower()
        if (
            hostname == "localhost"
            or hostname == "example.com"
            or hostname.endswith(
                (".localhost", ".local", ".example.com", ".example", ".invalid", ".test")
            )
        ):
            raise ValueError("制品仓库必须使用公网主机。")
        try:
            address = ip_address(hostname)
        except ValueError:
            return normalized
        if not address.is_global:
            raise ValueError("制品仓库必须使用公网IP地址。")
        return normalized

    @field_validator("repository_host_allowlist")
    @classmethod
    def validate_repository_hosts(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.rstrip(".").lower() for value in values)
        if any(not value or "://" in value or "/" in value or "@" in value for value in normalized):
            raise ValueError("制品仓库allowlist只允许规范化主机名。")
        return normalized

    @field_validator("authenticode_signer_sha256_allowlist")
    @classmethod
    def validate_signer_allowlist(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.lower() for value in values)
        if any(
            len(value) != SHA256_HEX_LENGTH
            or any(character not in "0123456789abcdef" for character in value)
            for value in normalized
        ):
            raise ValueError("Authenticode签名证书指纹必须是SHA-256十六进制。")
        return normalized

    @model_validator(mode="after")
    def validate_repository_host_membership(self) -> ArtifactReleaseRuntimeSettings:
        hostname = urlsplit(self.repository_url).hostname
        if hostname is None or hostname.rstrip(".").lower() not in self.repository_host_allowlist:
            raise ValueError("制品仓库主机必须存在于allowlist中。")
        if self.enabled and not self.authenticode_signer_sha256_allowlist:
            raise ValueError("启用制品更新时必须固定Authenticode签名证书指纹。")
        return self
