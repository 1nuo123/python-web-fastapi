"""Codex Agent 生产与开发 profile 隔离契约。"""

from __future__ import annotations

from pathlib import Path

from src.infrastructure.codex_agent.agent_deployment_profile import (
    AgentDeploymentProfile,
    resolve_agent_deployment_paths,
)


def test_development_profile_should_use_a_fully_separate_local_state_tree() -> None:
    """开发 profile 不能复用生产状态、锁、密钥或发布缓存。"""

    local_app_data = Path("C:/Users/example/AppData/Local")
    production = resolve_agent_deployment_paths(
        AgentDeploymentProfile.PRODUCTION,
        local_app_data=local_app_data,
    )
    development = resolve_agent_deployment_paths(
        AgentDeploymentProfile.DEVELOPMENT,
        local_app_data=local_app_data,
    )

    assert production.state_directory == local_app_data / "CodexRemoteAgent"
    assert development.state_directory == production.state_directory / "Development"
    assert development.config_path != production.config_path
    assert development.state_database != production.state_database
    assert development.device_key_directory != production.device_key_directory
    assert development.log_directory != production.log_directory
    assert development.lock_path != production.lock_path
    assert development.temporary_directory != production.temporary_directory
    assert development.pid_path != production.pid_path
    assert development.release_directory != production.release_directory
    assert development.scheduled_task_suffix == "Development"
    assert development.uri_scheme == "codexremote-dev"


def test_production_profile_should_keep_the_existing_public_identity() -> None:
    """生产 profile 的目录、任务后缀和 URI 必须保持发布兼容。"""

    paths = resolve_agent_deployment_paths(
        AgentDeploymentProfile.PRODUCTION,
        local_app_data=Path("C:/Users/example/AppData/Local"),
    )

    assert paths.scheduled_task_suffix == ""
    assert paths.uri_scheme == "codexremote"
