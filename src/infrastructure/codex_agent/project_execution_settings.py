"""项目执行设置：本机持久覆盖、官方基线解析和实际 RPC 参数共用入口。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import portalocker
import tomllib
from pydantic import JsonValue

from src.core.codex_contract.workspace_contract import (
    CodexWorkspaceExecutionPreferences,
    ProjectExecutionOverrides,
    ProjectExecutionSettingsApply,
    ProjectSandboxWriteOptions,
)
from src.core.codex_contract.host_contract import CodexSandboxMode
from src.infrastructure.codex_agent.agent_configuration import (
    CodexHostAgentSettings,
    AgentWorkspaceSettings,
)
from src.infrastructure.codex_agent.agent_config_store import AgentConfigStore
from src.infrastructure.codex_agent.windows_dpapi_device_key_store import (
    WindowsCurrentUserAclEnforcer,
)
from src.infrastructure.codex_agent.app_server_jsonrpc_client import AppServerJsonRpcClient
from src.infrastructure.codex_agent.app_server_model_catalog import read_model_catalog


class ProjectExecutionSettings:
    """目录白名单负责执行起点；完全访问不承诺文件系统隔离。"""

    def __init__(self, config_path: Path) -> None:
        self._path = config_path
        self._store = AgentConfigStore(config_path, WindowsCurrentUserAclEnforcer())
        self._applied: dict[str, tuple[int, str | None, str | None, str, str, str]] = {}

    def _load(self) -> CodexHostAgentSettings:
        with self._path.open("rb") as stream:
            return CodexHostAgentSettings.model_validate(tomllib.load(stream))

    def read_workspace(self, key: str) -> AgentWorkspaceSettings:
        workspace = next((item for item in self._load().workspaces if item.key == key), None)
        if workspace is None:
            raise ValueError("项目已删除，不能继续执行。")
        return workspace

    async def resolve(
        self,
        key: str,
        client: AppServerJsonRpcClient,
        requested: ProjectExecutionOverrides | None = None,
    ) -> CodexWorkspaceExecutionPreferences:
        workspace = await asyncio.to_thread(self.read_workspace, key)
        return await self.resolve_workspace(workspace, client, requested)

    async def resolve_workspace(
        self,
        workspace: AgentWorkspaceSettings,
        client: AppServerJsonRpcClient,
        requested: ProjectExecutionOverrides | None = None,
    ) -> CodexWorkspaceExecutionPreferences:
        """网页提交、原生草稿与真实执行共享同一有效值解析和限制校验。"""
        key = workspace.key
        overrides = requested or workspace.execution_overrides
        response = await client.request(
            "config/read", {"cwd": str(workspace.root), "includeLayers": False}, timeout_seconds=10
        )
        requirements_response = await client.request(
            "configRequirements/read", {}, timeout_seconds=10
        )
        if not isinstance(response, dict) or not isinstance(response.get("config"), dict):
            raise ValueError("无法读取当前项目的本机有效配置。")
        config = response["config"]
        requirements = (
            requirements_response.get("requirements")
            if isinstance(requirements_response, dict)
            else None
        )
        catalog = await read_model_catalog(client)
        if catalog.state != "ready":
            raise ValueError("本机模型能力不可读取。")
        default = next((item for item in catalog.models if item.is_default), None)
        model = overrides.model or config.get("model") or (default.model if default else None)
        capability = next((item for item in catalog.models if item.model == model), None)
        inherited_model = overrides.model is None and model == config.get("model")
        if capability is None and not inherited_model:
            raise ValueError("当前项目模型不可用，请选择可用模型。")
        effort = (
            overrides.reasoning_effort
            or config.get("model_reasoning_effort")
            or (capability.default_reasoning_effort if capability else None)
        )
        if (
            effort is not None
            and capability is not None
            and effort not in capability.reasoning_efforts
        ):
            raise ValueError("继承或覆盖的推理档位不适用于当前模型，请明确选择档位。")
        if (
            capability is None
            and overrides.reasoning_effort is not None
            and overrides.reasoning_effort != config.get("model_reasoning_effort")
        ):
            raise ValueError("本机自定义模型未公布可选档位，请继承本机配置。")
        if overrides.permission_mode == "full_access":
            sandbox, approval = "danger-full-access", "never"
        elif overrides.permission_mode == "restricted":
            sandbox, approval = (
                ("workspace-write" if workspace.allow_write else "read-only"),
                "untrusted",
            )
        else:
            sandbox, approval = config.get("sandbox_mode"), config.get("approval_policy")
            if sandbox is None or approval is None:
                raise ValueError("本机有效权限基线未返回，不能猜测继承设置。")
        if not workspace.allow_write and sandbox != "read-only":
            raise PermissionError("本机项目只读限制与请求权限冲突。")
        if isinstance(requirements, dict):
            for field, value in (
                ("allowedSandboxModes", sandbox),
                ("allowedApprovalPolicies", approval),
            ):
                allowed = requirements.get(field)
                if isinstance(allowed, list) and value not in allowed:
                    raise PermissionError("项目设置被组织策略限制：" + field)
        preferences = CodexWorkspaceExecutionPreferences.model_validate(
            {
                "model": model,
                "reasoning_effort": effort,
                "sandbox_mode": sandbox,
                "approval_policy": approval,
                "requested": overrides.model_dump(),
                "local_revision": workspace.execution_revision,
                "applied_state": "saved",
                "sandbox_options": ProjectSandboxWriteOptions.model_validate(
                    config.get("sandbox_workspace_write") or {}
                    if overrides.permission_mode == "inherit"
                    else {}
                ),
            }
        )
        signature = (
            preferences.local_revision,
            preferences.model,
            preferences.reasoning_effort,
            preferences.sandbox_mode.value,
            preferences.approval_policy.value,
            preferences.sandbox_options.model_dump_json(),
        )
        if self._applied.get(key) == signature:
            preferences = preferences.model_copy(update={"applied_state": "applied"})
        return preferences

    async def apply(
        self, key: str, request: ProjectExecutionSettingsApply, client: AppServerJsonRpcClient
    ) -> CodexWorkspaceExecutionPreferences:
        await self.resolve(key, client, request.requested)
        await asyncio.to_thread(self._persist, key, request)
        return await self.resolve(key, client)

    def _persist(self, key: str, request: ProjectExecutionSettingsApply) -> None:
        with portalocker.Lock(self._path.with_suffix(".edit.lock"), timeout=10):
            current = self._load()
            workspace = next((item for item in current.workspaces if item.key == key), None)
            if workspace is None:
                raise ValueError("项目已删除。")
            if workspace.execution_revision != request.expected_revision:
                raise ValueError("项目设置版本冲突，请重新读取后应用。")
            if workspace.execution_overrides == request.requested:
                return
            updated_workspace = workspace.model_copy(
                update={
                    "execution_overrides": request.requested,
                    "execution_revision": workspace.execution_revision + 1,
                }
            )
            updated = current.model_copy(
                update={
                    "workspaces": [
                        updated_workspace if item.key == key else item
                        for item in current.workspaces
                    ]
                }
            )
            self._store.write(self._store.serialize(updated))

    def confirm(self, key: str, preferences: CodexWorkspaceExecutionPreferences) -> None:
        self._applied[key] = (
            preferences.local_revision,
            preferences.model,
            preferences.reasoning_effort,
            preferences.sandbox_mode.value,
            preferences.approval_policy.value,
            preferences.sandbox_options.model_dump_json(),
        )

    def build_parameters(
        self, method: str, preferences: CodexWorkspaceExecutionPreferences, cwd: str
    ) -> dict[str, JsonValue]:
        sandbox = preferences.sandbox_mode
        params: dict[str, JsonValue] = {
            "model": preferences.model,
            "approvalPolicy": preferences.approval_policy.value,
        }
        if method in {"thread/start", "thread/resume"}:
            params["sandbox"] = sandbox.value
            params["config"] = {
                "model_reasoning_effort": preferences.reasoning_effort,
                "sandbox_workspace_write": preferences.sandbox_options.model_dump(mode="json"),
            }
        else:
            params["effort"] = preferences.reasoning_effort
            params["sandboxPolicy"] = (
                {"type": "dangerFullAccess"}
                if sandbox is CodexSandboxMode.DANGER_FULL_ACCESS
                else {"type": "readOnly", "networkAccess": False}
                if sandbox is CodexSandboxMode.READ_ONLY
                else {
                    "type": "workspaceWrite",
                    "writableRoots": list(
                        dict.fromkeys([cwd, *preferences.sandbox_options.writable_roots])
                    ),
                    "networkAccess": preferences.sandbox_options.network_access,
                    "excludeTmpdirEnvVar": preferences.sandbox_options.exclude_tmpdir_env_var,
                    "excludeSlashTmp": preferences.sandbox_options.exclude_slash_tmp,
                }
            )
        return params
