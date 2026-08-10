"""制品发布运行时配置。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ArtifactReleaseRuntimeSettings(BaseModel):
    """TUF、下载、暂存和回滚边界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = True
    trusted_root_path: str = Field(min_length=1)
    repository_url: str = Field(min_length=1)
    repository_host_allowlist: tuple[str, ...] = Field(min_length=1)
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

        if not value.startswith("https://"):
            raise ValueError("制品仓库必须使用HTTPS。")
        return value.rstrip("/")
