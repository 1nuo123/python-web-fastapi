"""生成 Windows Agent 安装包公开 bootstrap TOML。"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path
from typing import Literal, TypedDict
from urllib.parse import urlsplit

import rtoml
from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.codex_contract.agent_release_manifest_contract import (
    AGENT_RELEASE_MANIFEST_TARGET_PATH,
    parse_agent_release_version,
)
from src.infrastructure.codex_agent.agent_configuration import (
    AgentBootstrapConnectionSettings,
    AgentDevelopmentBootstrapConnectionSettings,
    AgentLocalBootstrapConnectionSettings,
    validate_public_endpoint_url,
)


class AgentBootstrapBuildCommand(BaseModel):
    """bootstrap 生成命令。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    output: Path
    deployment_state: Literal["configured", "development", "local", "unconfigured"] = "configured"
    public_origin: str | None = None
    development_origin: str | None = None
    local_origin: str | None = None
    agent_version: str
    expected_codex_version: str
    app_server_schema_digest: str = Field(min_length=64, max_length=128)
    release_enabled: bool = False
    release_manifest_target_path: Literal["codex-agent-release.json"] = (
        AGENT_RELEASE_MANIFEST_TARGET_PATH
    )
    release_repository_url: str | None = None
    repository_host_allowlist: tuple[str, ...] = ()
    authenticode_signer_sha256_allowlist: tuple[str, ...] = ()
    trusted_root_file_name: str = "root.json"
    minimum_security_version: str | None = None

    @field_validator("authenticode_signer_sha256_allowlist")
    @classmethod
    def validate_signer_allowlist(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Normalize and validate release certificate fingerprints."""

        normalized = tuple(value.lower() for value in values)
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in normalized
        ):
            raise ValueError("Authenticode签名证书指纹必须是SHA-256十六进制。")
        return normalized

    def build_connection_settings(
        self,
    ) -> (
        AgentBootstrapConnectionSettings
        | AgentDevelopmentBootstrapConnectionSettings
        | AgentLocalBootstrapConnectionSettings
    ):
        """构造与部署类型匹配并经过边界校验的控制面入口。"""

        if self.deployment_state == "local":
            if self.local_origin is None:
                raise ValueError("本地验收安装包必须提供回环origin。")
            return AgentLocalBootstrapConnectionSettings.from_local_origin(self.local_origin)
        if self.deployment_state == "development":
            if self.development_origin is None:
                raise ValueError("开发安装包必须提供开发TLS origin。")
            return AgentDevelopmentBootstrapConnectionSettings.from_development_origin(
                self.development_origin
            )
        if self.public_origin is None:
            raise ValueError("正式安装包必须提供公网origin。")
        return AgentBootstrapConnectionSettings.from_public_origin(self.public_origin)

    @model_validator(mode="after")
    def validate_public_release_inputs(self) -> AgentBootstrapBuildCommand:
        if self.deployment_state == "unconfigured":
            if (
                self.public_origin is not None
                or self.development_origin is not None
                or self.local_origin is not None
            ):
                raise ValueError("未配置安装包不得包含服务器地址。")
            if self.release_enabled:
                raise ValueError("未配置安装包不得启用自动更新。")
            return self
        if self.deployment_state == "local":
            if self.public_origin is not None or self.development_origin is not None:
                raise ValueError("本地验收安装包不得包含公网origin。")
            if self.release_enabled:
                raise ValueError("本地验收安装包不得启用自动更新。")
            self.build_connection_settings()
            return self
        if self.deployment_state == "development":
            if self.public_origin is not None or self.local_origin is not None:
                raise ValueError("开发安装包不得包含公网或回环origin。")
            if self.release_enabled:
                raise ValueError("开发安装包不得启用自动更新。")
            self.build_connection_settings()
            return self
        if self.local_origin is not None:
            raise ValueError("正式安装包不得包含本地origin。")
        if self.development_origin is not None:
            raise ValueError("正式安装包不得包含开发origin。")
        self.build_connection_settings()
        if self.release_enabled:
            if not all(
                (
                    self.release_manifest_target_path,
                    self.release_repository_url,
                    self.minimum_security_version,
                )
            ):
                raise ValueError("启用自动更新时必须提供完整发布参数。")
            if not self.repository_host_allowlist:
                raise ValueError("启用自动更新时必须提供发布仓库主机allowlist。")
            if not self.authenticode_signer_sha256_allowlist:
                raise ValueError("启用自动更新时必须固定Authenticode签名证书指纹。")
            if self.release_repository_url is None:
                raise ValueError("自动更新发布地址必须使用HTTPS。")
            validate_public_endpoint_url(
                self.release_repository_url,
                expected_scheme="https",
            )
            repository_host = urlsplit(self.release_repository_url or "").hostname
            if repository_host is None:
                raise ValueError("自动更新发布地址必须包含有效主机名。")
            normalized_allowlist = tuple(
                host.rstrip(".").lower() for host in self.repository_host_allowlist
            )
            if any(
                not host or "://" in host or "/" in host or "@" in host
                for host in normalized_allowlist
            ):
                raise ValueError("发布仓库allowlist只允许规范化主机名。")
            if repository_host.rstrip(".").lower() not in normalized_allowlist:
                raise ValueError("制品仓库主机必须存在于allowlist中。")
            if self.minimum_security_version is not None and (
                parse_agent_release_version(self.minimum_security_version)
                > parse_agent_release_version(self.agent_version)
            ):
                raise ValueError("最低安全版本不得高于安装包Agent版本。")
        return self


class AgentReleasePayload(TypedDict):
    """自动更新 bootstrap 的公开配置。"""

    enabled: bool
    manifest_target_path: Literal["codex-agent-release.json"]
    repository_url: str | None
    repository_host_allowlist: list[str]
    authenticode_signer_sha256_allowlist: list[str]
    trusted_root_file_name: str
    max_download_bytes: int
    request_timeout_seconds: int
    retained_versions: int
    health_timeout_seconds: int
    rollback_budget: int
    minimum_security_version: str | None


class AgentBootstrapPayload(TypedDict, total=False):
    """bootstrap TOML 的强类型序列化结构。"""

    deployment_state: Literal["configured", "development", "local", "unconfigured"]
    connection: dict[str, str]
    agent_version: str
    expected_codex_version: str
    app_server_schema_digest: str
    default_workspace_key: str
    default_workspace_name: str
    release: AgentReleasePayload


class CodexAgentBootstrapBuilder:
    """把发布输入收敛为 AgentBootstrapSettings 可直接加载的 TOML。"""

    def build(self, command: AgentBootstrapBuildCommand) -> None:
        """原子写入不含敏感信息的 bootstrap 文件。"""

        payload: AgentBootstrapPayload = {
            "deployment_state": command.deployment_state,
            "agent_version": command.agent_version,
            "expected_codex_version": command.expected_codex_version,
            "app_server_schema_digest": command.app_server_schema_digest,
            "default_workspace_key": "default",
            "default_workspace_name": "默认工作区",
        }
        if command.deployment_state != "unconfigured":
            connection = command.build_connection_settings()
            payload["connection"] = connection.model_dump(mode="json")
        if command.release_enabled:
            release_payload: AgentReleasePayload = {
                "enabled": True,
                "manifest_target_path": command.release_manifest_target_path,
                "repository_url": command.release_repository_url,
                "repository_host_allowlist": list(command.repository_host_allowlist),
                "authenticode_signer_sha256_allowlist": list(
                    command.authenticode_signer_sha256_allowlist
                ),
                "trusted_root_file_name": command.trusted_root_file_name,
                "max_download_bytes": 536_870_912,
                "request_timeout_seconds": 60,
                "retained_versions": 2,
                "health_timeout_seconds": 60,
                "rollback_budget": 3,
                "minimum_security_version": command.minimum_security_version,
            }
            payload["release"] = release_payload
        command.output.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = command.output.with_suffix(f"{command.output.suffix}.tmp")
        rtoml.dump(payload, temporary_path)
        temporary_path.replace(command.output)


class CodexAgentBootstrapCli:
    """bootstrap 生成命令行入口。"""

    def execute(self, argv: Sequence[str] | None = None) -> int:
        """解析发布参数并生成 bootstrap。"""

        parser = argparse.ArgumentParser(description="生成 Codex Remote Agent bootstrap")
        parser.add_argument("--output", required=True, type=Path)
        parser.add_argument("--unconfigured", action="store_true")
        parser.add_argument("--public-origin")
        parser.add_argument("--development-origin")
        parser.add_argument("--local-origin")
        parser.add_argument("--agent-version", required=True)
        parser.add_argument("--expected-codex-version", required=True)
        parser.add_argument("--app-server-schema-digest", required=True)
        parser.add_argument("--enable-release", action="store_true")
        parser.add_argument("--release-repository-url")
        parser.add_argument("--repository-host", action="append", default=[])
        parser.add_argument(
            "--authenticode-signer-sha256",
            action="append",
            default=[],
        )
        parser.add_argument("--trusted-root-file-name", default="root.json")
        parser.add_argument("--minimum-security-version")
        arguments = parser.parse_args(argv)
        deployment_state: Literal["configured", "development", "local", "unconfigured"] = (
            "configured"
        )
        if arguments.unconfigured:
            deployment_state = "unconfigured"
        elif arguments.local_origin is not None:
            deployment_state = "local"
        elif arguments.development_origin is not None:
            deployment_state = "development"
        command = AgentBootstrapBuildCommand(
            output=arguments.output,
            deployment_state=deployment_state,
            public_origin=arguments.public_origin,
            development_origin=arguments.development_origin,
            local_origin=arguments.local_origin,
            agent_version=arguments.agent_version,
            expected_codex_version=arguments.expected_codex_version,
            app_server_schema_digest=arguments.app_server_schema_digest,
            release_enabled=arguments.enable_release,
            release_repository_url=arguments.release_repository_url,
            repository_host_allowlist=tuple(arguments.repository_host),
            authenticode_signer_sha256_allowlist=tuple(arguments.authenticode_signer_sha256),
            trusted_root_file_name=arguments.trusted_root_file_name,
            minimum_security_version=arguments.minimum_security_version,
        )
        CodexAgentBootstrapBuilder().build(command)
        logger.info("Agent bootstrap 已生成：{}", command.output)
        return 0


if __name__ == "__main__":
    raise SystemExit(CodexAgentBootstrapCli().execute())
