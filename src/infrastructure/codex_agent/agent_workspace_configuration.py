"""Windows Agent 项目配置的原子更新与回滚。"""

from __future__ import annotations

import portalocker

from pathlib import Path
from typing import Final
from src.core.codex_contract.workspace_contract import CodexWorkspaceExecutionPreferences
from uuid import uuid4

from src.infrastructure.codex_agent.agent_config_store import AgentConfigStore

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
        self._store = AgentConfigStore(config_path, acl_enforcer)

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

    def apply(
        self,
        workspaces: list[AgentWorkspaceSettings],
        *,
        expected: list[AgentWorkspaceSettings] | None = None,
    ) -> CodexHostAgentSettings:
        """与网页设置共用文件锁，草稿基线变化时拒绝覆盖。"""
        with portalocker.Lock(self._config_path.with_suffix(".edit.lock"), timeout=10):
            current = self.load()
            if expected is not None and current.workspaces != expected:
                raise ValueError("项目已被其它窗口修改，请重新打开管理项目后应用。")
            if not workspaces:
                raise ValueError("至少需要保留一个项目。")
            previous = {item.key: item for item in current.workspaces}
            revised = []
            for item in workspaces:
                old = previous.get(item.key)
                if old is not None and self._normalize_root(old.root) != self._normalize_root(
                    item.root
                ):
                    raise ValueError("不能把已有项目身份绑定到不同目录；请删除并重新添加。")
                revision = old.execution_revision if old else 0
                if old and old.execution_overrides != item.execution_overrides:
                    revision += 1
                revised.append(item.model_copy(update={"execution_revision": revision}))
            updated = CodexHostAgentSettings.model_validate(
                {**current.model_dump(), "workspaces": revised}
            )
            if current == updated:
                return current
            changed_execution = [
                item
                for item in revised
                if item.key not in previous
                or item.execution_overrides != previous[item.key].execution_overrides
            ]
            if changed_execution:
                self.read_execution_settings(changed_execution, settings=current)
            restart_required = [
                item.model_dump(exclude={"execution_overrides", "execution_revision"})
                for item in current.workspaces
            ] != [
                item.model_dump(exclude={"execution_overrides", "execution_revision"})
                for item in revised
            ]
            try:
                self._store.write(self._store.serialize(updated))
            except (OSError, ValueError) as exc:
                raise AgentWorkspaceConfigurationError("项目配置未保存，旧配置未改变。") from exc
        # 写盘已提交；启动失败保留真实状态，不回滚覆盖其它客户端的新配置。
        if not restart_required:
            return updated
        try:
            self._task_controller.restart()
        except OSError as exc:
            raise AgentWorkspaceConfigurationError(
                "项目配置已保存，但 Agent 未能重启；请点击启动 Agent。"
            ) from exc
        return updated

    def read_execution_settings(
        self,
        workspaces: list[AgentWorkspaceSettings],
        *,
        settings: CodexHostAgentSettings | None = None,
    ) -> list[CodexWorkspaceExecutionPreferences]:
        """提交前只读本机能力；不更改运行中线程、CLI 配置或登录。"""
        import asyncio
        import logging
        from src.infrastructure.codex_agent.app_server_process_supervisor import (
            AppServerProcessSupervisor,
        )
        from src.infrastructure.codex_agent.project_execution_settings import (
            ProjectExecutionSettings,
        )

        settings = settings or self.load()

        async def validate() -> list[CodexWorkspaceExecutionPreferences]:
            async def ignore(*_args: object) -> None:
                return None

            supervisor = AppServerProcessSupervisor(
                codex_binary=settings.agent.codex_binary,
                allowed_versions=[settings.protocol.expected_codex_version],
                max_line_bytes=settings.agent.max_app_server_line_bytes,
                allow_experimental_api=settings.protocol.allow_experimental_api,
                notification_handler=ignore,
                request_handler=ignore,
                warning_handler=ignore,
                logger=logging.getLogger(__name__),
            )
            try:
                handle = await supervisor.start()
                resolver = ProjectExecutionSettings(self._config_path)
                return [
                    await resolver.resolve_workspace(workspace, handle.client)
                    for workspace in workspaces
                ]
            finally:
                await supervisor.stop()

        return asyncio.run(validate())

    def _next_key(self, workspaces: list[AgentWorkspaceSettings]) -> str:
        return f"{WORKSPACE_KEY_PREFIX}-{uuid4().hex}"

    def _normalize_root(self, root: Path) -> str:
        return str(root.resolve()).casefold()
