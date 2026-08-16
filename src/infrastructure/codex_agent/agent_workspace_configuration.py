"""Windows Agent 项目配置的原子更新与回滚。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final
from uuid import uuid4

import rtoml

from src.infrastructure.codex_agent.agent_configuration import (
    AgentWorkspaceSettings,
    CodexHostAgentSettings,
    CodexHostAgentSettingsLoader,
)
from src.infrastructure.codex_agent.windows_agent_task import (
    WindowsAgentTaskController,
)
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import (
    WindowsCurrentUserAclEnforcer,
)

WORKSPACE_KEY_PREFIX: Final = "workspace"


class AgentWorkspaceConfigurationError(OSError):
    """项目配置无法提交或恢复。"""


class WindowsAgentWorkspaceConfiguration:
    """管理项目白名单，并在提交后可靠重启 Agent。"""

    def __init__(
        self,
        *,
        config_path: Path,
        settings_loader: CodexHostAgentSettingsLoader,
        acl_enforcer: WindowsCurrentUserAclEnforcer,
        task_controller: WindowsAgentTaskController,
    ) -> None:
        self._config_path = config_path
        self._settings_loader = settings_loader
        self._acl_enforcer = acl_enforcer
        self._task_controller = task_controller

    def load(self) -> CodexHostAgentSettings:
        if not self._config_path.exists():
            raise FileNotFoundError("Agent尚未完成设备连接。")
        return self._settings_loader.load(self._config_path)

    def add(
        self,
        workspaces: list[AgentWorkspaceSettings],
        root: Path,
    ) -> list[AgentWorkspaceSettings]:
        resolved_root = root.resolve(strict=True)
        if not resolved_root.is_dir():
            raise ValueError("项目必须是已经存在的目录。")
        normalized_root = self._normalize_root(resolved_root)
        if any(self._normalize_root(workspace.root) == normalized_root for workspace in workspaces):
            raise ValueError("该项目目录已经存在。")
        workspace = AgentWorkspaceSettings(
            key=self._next_key(workspaces),
            display_name=resolved_root.name or str(resolved_root),
            root=resolved_root,
            allow_write=True,
        )
        return [*workspaces, workspace]

    def remove(
        self,
        workspaces: list[AgentWorkspaceSettings],
        workspace_key: str,
    ) -> list[AgentWorkspaceSettings]:
        if len(workspaces) <= 1:
            raise ValueError("至少需要保留一个项目。")
        remaining = [workspace for workspace in workspaces if workspace.key != workspace_key]
        if len(remaining) == len(workspaces):
            raise ValueError("选择的项目不存在。")
        return remaining

    def apply(self, workspaces: list[AgentWorkspaceSettings]) -> CodexHostAgentSettings:
        if not workspaces:
            raise ValueError("至少需要保留一个项目。")
        current = self.load()
        updated = current.model_copy(update={"workspaces": workspaces})
        previous_content = self._config_path.read_bytes()
        try:
            self._replace_content(self._serialize(updated))
        except (OSError, PermissionError, ValueError) as exc:
            self._restore(previous_content)
            raise AgentWorkspaceConfigurationError("项目配置保存失败，旧配置已经恢复。") from exc
        try:
            self._task_controller.restart()
        except OSError as exc:
            self._restore(previous_content)
            try:
                self._task_controller.restart()
            except OSError as rollback_exc:
                raise AgentWorkspaceConfigurationError(
                    "新项目配置启动失败，旧配置已恢复，但 Agent 重新启动失败。"
                ) from rollback_exc
            raise AgentWorkspaceConfigurationError(
                "新项目配置启动失败，已恢复旧配置并重新启动 Agent。"
            ) from exc
        return updated

    def _restore(self, content: bytes) -> None:
        try:
            self._replace_content(content)
        except (OSError, PermissionError) as restore_exc:
            raise AgentWorkspaceConfigurationError(
                "项目配置失败且旧配置无法恢复。"
            ) from restore_exc

    def _replace_content(self, content: bytes) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._config_path.with_name(f".{self._config_path.name}.{uuid4().hex}.tmp")
        try:
            with temporary_path.open("xb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            self._acl_enforcer.enforce(temporary_path)
            os.replace(temporary_path, self._config_path)
            self._acl_enforcer.enforce(self._config_path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _serialize(self, settings: CodexHostAgentSettings) -> bytes:
        payload = settings.model_dump(mode="json", exclude_none=True)
        return rtoml.dumps(payload).encode("utf-8")

    def _next_key(self, workspaces: list[AgentWorkspaceSettings]) -> str:
        existing_keys = {workspace.key for workspace in workspaces}
        index = 1
        while f"{WORKSPACE_KEY_PREFIX}-{index}" in existing_keys:
            index += 1
        return f"{WORKSPACE_KEY_PREFIX}-{index}"

    def _normalize_root(self, root: Path) -> str:
        return str(root.resolve()).casefold()
