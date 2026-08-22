"""Codex Host Agent 的生产与开发部署 profile 路径隔离。"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class AgentDeploymentProfile(StrEnum):
    """Agent 实例的独立部署身份。

    production 保留已发布客户端的目录和 URI；development 仅在其独立目录中创建
    配置、设备密钥、锁和发布缓存，避免本地验收影响生产实例。
    """

    PRODUCTION = "production"
    DEVELOPMENT = "development"


@dataclass(frozen=True, slots=True)
class AgentDeploymentPaths:
    """同一 profile 下所有可变本地资源的确定性位置。"""

    profile: AgentDeploymentProfile
    state_directory: Path
    config_path: Path
    state_database: Path
    device_key_directory: Path
    log_directory: Path
    lock_path: Path
    temporary_directory: Path
    pid_path: Path
    release_directory: Path
    scheduled_task_suffix: str
    uri_scheme: str


def resolve_agent_deployment_paths(
    profile: AgentDeploymentProfile,
    *,
    local_app_data: Path | None = None,
) -> AgentDeploymentPaths:
    """解析 profile 的本地状态树，不读取另一个 profile 的任何路径。"""

    resolved_local_app_data = local_app_data or Path(
        os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
    )
    production_root = resolved_local_app_data / "CodexRemoteAgent"
    is_development = profile is AgentDeploymentProfile.DEVELOPMENT
    state_directory = production_root / "Development" if is_development else production_root
    return AgentDeploymentPaths(
        profile=profile,
        state_directory=state_directory,
        config_path=state_directory / "agent.toml",
        state_database=state_directory / "state.sqlite",
        device_key_directory=state_directory / "keys",
        log_directory=state_directory / "logs",
        lock_path=state_directory / "state.lock",
        temporary_directory=state_directory / "tmp",
        pid_path=state_directory / "agent.pid",
        release_directory=state_directory / "releases",
        scheduled_task_suffix="Development" if is_development else "",
        uri_scheme="codexremote-dev" if is_development else "codexremote",
    )
