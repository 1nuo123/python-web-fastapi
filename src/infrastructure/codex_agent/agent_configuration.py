"""Windows Codex Host Agent 本地配置。"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Final, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.core.codex_contract.connection_session_contract import (
    CodexConnectionProtocolVersion,
)
from src.domain.codex.agent_command_policy import AgentAppServerSecurityPolicy
from src.infrastructure.codex_agent.agent_workspace_registry import (
    AgentConfigPermissionVerifierPort,
    AgentWorkspaceDefinition,
)

DEFAULT_AGENT_STATE_DIRECTORY: Final = Path.home() / "AppData" / "Local" / "CodexRemoteAgent"
MAX_APP_SERVER_LINE_BYTES: Final = 4 * 1024 * 1024
DEFAULT_AGENT_EVENT_BATCH_WINDOW_MILLISECONDS: Final = 75
DEFAULT_AGENT_EVENT_BATCH_MAX_CHARS: Final = 4_096
DEFAULT_AGENT_WRITER_QUEUE_CAPACITY: Final = 256
DEFAULT_AGENT_SNAPSHOT_PAGE_SIZE: Final = 100
MAX_AGENT_SNAPSHOT_PAGE_SIZE: Final = 500


class AgentProtocolSettings(BaseModel):
    """Agent 与控制面/App Server 的版本边界。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_schema_version: CodexConnectionProtocolVersion
    expected_codex_version: str = Field(min_length=1, max_length=64)
    app_server_schema_digest: str = Field(min_length=64, max_length=128)
    allow_experimental_api: bool = False


class AgentProcessSettings(BaseModel):
    """Agent 进程、连接和本地状态配置。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    host_id: UUID
    key_id: UUID | None = None
    legacy_credential_id: str | None = Field(default=None, min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    control_plane_url: str = Field(min_length=1)
    control_plane_api_url: str = Field(min_length=1)
    codex_binary: str = Field(default="codex", min_length=1)
    heartbeat_seconds: int = Field(default=10, gt=0)
    reconnect_min_seconds: int = Field(default=1, gt=0)
    reconnect_max_seconds: int = Field(default=30, gt=0)
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
    event_batch_max_chars: int = Field(
        default=DEFAULT_AGENT_EVENT_BATCH_MAX_CHARS,
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
    state_database: Path = DEFAULT_AGENT_STATE_DIRECTORY / "state.sqlite"

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
        """校验指数退避边界。"""

        if self.reconnect_max_seconds < self.reconnect_min_seconds:
            raise ValueError("reconnect_max_seconds不得小于reconnect_min_seconds。")
        if self.event_batch_max_chars >= self.max_app_server_line_bytes:
            raise ValueError("event_batch_max_chars必须小于Agent单帧上限。")
        return self


class AgentWorkspaceSettings(BaseModel):
    """本地 TOML 中的一项工作区白名单。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)
    root: Path
    allow_write: bool = False

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
        )


class AgentAppServerSecuritySettings(BaseModel):
    """冻结 Agent 对本机 App Server 的最低安全执行策略。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_policy: Literal["untrusted"] = "untrusted"
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
