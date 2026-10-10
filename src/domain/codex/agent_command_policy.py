"""Agent 命令摘要与允许方法的纯策略。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, Protocol, cast

from pydantic import JsonValue


class AgentWorkspaceResolverPort(Protocol):
    """Agent 命令策略使用的本地工作区解析边界。"""

    def resolve_root(self, workspace_key: str, *, require_write: bool = False) -> Path: ...


AGENT_COMMAND_METHODS: Final = {
    "thread.list": "thread/list",
    "thread.read": "thread/read",
    "thread.start": "thread/start",
    "thread.resume": "thread/resume",
    "thread.name_set": "thread/name/set",
    "thread.archive": "thread/archive",
    "thread.unarchive": "thread/unarchive",
    "thread.compact": "thread/compact/start",
    "turn.start": "turn/start",
    "turn.steer": "turn/steer",
    "turn.interrupt": "turn/interrupt",
}
WRITE_COMMAND_TYPES: Final = frozenset(
    {"thread.start", "thread.resume", "turn.start", "turn.steer"}
)
WORKSPACE_COMMAND_TYPES: Final = frozenset(
    {
        "thread.list",
        "thread.read",
        "thread.start",
        "thread.resume",
        "thread.name_set",
        "thread.archive",
        "thread.unarchive",
        "thread.compact",
        "turn.start",
        "turn.steer",
        "turn.interrupt",
    }
)
CWD_INJECT_COMMAND_TYPES: Final = frozenset(
    {"thread.list", "thread.start", "thread.resume", "turn.start"}
)
THREAD_SECURITY_COMMAND_TYPES: Final = frozenset({"thread.start", "thread.resume"})
TURN_SECURITY_COMMAND_TYPES: Final = frozenset({"turn.start"})
APP_SERVER_SECURITY_OVERRIDE_KEYS: Final = frozenset(
    {"approvalPolicy", "approvalsReviewer", "sandbox", "sandboxPolicy"}
)
WORKTREE_POLICY_PARAM: Final = "worktree_policy"


class AgentCommandValidationError(ValueError):
    """控制面命令不满足 Agent 本地安全契约。"""


@dataclass(frozen=True, slots=True)
class AgentAppServerSecurityPolicy:
    """只允许 Windows Agent 向 App Server 注入的安全执行策略。"""

    approval_policy: Literal["untrusted", "on-request", "never"] = "untrusted"
    approvals_reviewer: Literal["user"] = "user"
    sandbox_mode: Literal["read-only", "workspace-write", "danger-full-access"] = "workspace-write"


@dataclass(frozen=True, slots=True)
class AppServerCommandRequest:
    """完成本地路径解析后的 App Server 请求。"""

    method: str
    params: dict[str, JsonValue]


def calculate_agent_request_digest(
    command_type: str,
    params: Mapping[str, JsonValue],
    *,
    sandbox_mode: str | None = None,
    approval_policy: str | None = None,
) -> str:
    """对稳定命令类型和参数计算 SHA-256，阻止同 id 换副作用。"""

    canonical = json.dumps(
        {
            "command_type": command_type,
            "params": params,
            "sandbox_mode": sandbox_mode,
            "approval_policy": approval_policy,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class AgentCommandPolicy:
    """把产品命令限制并映射为冻结的 App Server 方法。"""

    def __init__(
        self,
        workspace_registry: AgentWorkspaceResolverPort,
        security_policy: AgentAppServerSecurityPolicy | None = None,
    ) -> None:
        self._workspace_registry = workspace_registry
        self._security_policy = security_policy or AgentAppServerSecurityPolicy()

    def build_request(
        self,
        *,
        command_type: str,
        params: Mapping[str, JsonValue],
        cwd_override: Path | None = None,
    ) -> AppServerCommandRequest:
        """验证方法白名单，且只从本地 registry 注入 cwd。"""

        try:
            method = AGENT_COMMAND_METHODS[command_type]
        except KeyError as exc:
            raise AgentCommandValidationError("Agent不支持该命令类型。") from exc
        app_server_params = dict(params)
        self._reject_control_plane_security_overrides(app_server_params)
        worktree_policy = app_server_params.pop(WORKTREE_POLICY_PARAM, None)
        if worktree_policy is not None and command_type != "thread.start":
            raise AgentCommandValidationError("worktree策略只能用于创建thread。")
        workspace_key_value = app_server_params.pop("workspace_key", None)
        if command_type in WORKSPACE_COMMAND_TYPES:
            if not isinstance(workspace_key_value, str) or not workspace_key_value:
                raise AgentCommandValidationError("命令缺少有效workspace_key。")
            root = self._workspace_registry.resolve_root(
                workspace_key_value,
                require_write=False,
            )
            if "cwd" in app_server_params:
                raise AgentCommandValidationError("控制面不得直接指定cwd。")
            if command_type in CWD_INJECT_COMMAND_TYPES:
                selected_root = cwd_override.resolve(strict=True) if cwd_override else root
                if selected_root != root and not selected_root.is_relative_to(root):
                    raise AgentCommandValidationError("worktree目录逃出工作区根目录。")
                app_server_params["cwd"] = str(selected_root)
        elif "cwd" in app_server_params or workspace_key_value is not None:
            raise AgentCommandValidationError("该命令不得携带路径或workspace_key。")
        self._inject_app_server_security_policy(command_type, app_server_params)
        return AppServerCommandRequest(method=method, params=app_server_params)

    def _reject_control_plane_security_overrides(self, params: Mapping[str, JsonValue]) -> None:
        """禁止远端控制面降低本机 App Server 的审批或沙箱策略。"""

        supplied = APP_SERVER_SECURITY_OVERRIDE_KEYS.intersection(params)
        if supplied:
            raise AgentCommandValidationError("控制面不得指定App Server审批或沙箱策略。")

    def _inject_app_server_security_policy(
        self,
        command_type: str,
        params: dict[str, JsonValue],
    ) -> None:
        """为新建、恢复和启动 turn 固定本机审批策略。"""

        if command_type in THREAD_SECURITY_COMMAND_TYPES:
            params["approvalPolicy"] = self._security_policy.approval_policy
            params["approvalsReviewer"] = self._security_policy.approvals_reviewer
            params["sandbox"] = self._security_policy.sandbox_mode
            return
        if command_type in TURN_SECURITY_COMMAND_TYPES:
            params["approvalPolicy"] = self._security_policy.approval_policy
            params["approvalsReviewer"] = self._security_policy.approvals_reviewer
            mode = self._security_policy.sandbox_mode
            if mode == "danger-full-access":
                params["sandboxPolicy"] = {"type": "dangerFullAccess"}
            elif mode == "read-only":
                params["sandboxPolicy"] = {"type": "readOnly", "networkAccess": False}
            else:
                params["sandboxPolicy"] = {
                    "type": "workspaceWrite",
                    "writableRoots": [params["cwd"]],
                    "networkAccess": False,
                    "excludeTmpdirEnvVar": False,
                    "excludeSlashTmp": False,
                }


def read_upstream_identifiers(result: JsonValue) -> tuple[str | None, str | None]:
    """从 App Server 响应读取 thread/turn id，不保存其他正文。"""

    if not isinstance(result, Mapping):
        return None, None
    mapping = cast(Mapping[str, object], result)
    thread_id = _read_nested_identifier(mapping, "thread")
    turn_id = _read_nested_identifier(mapping, "turn")
    if thread_id is None:
        value = mapping.get("threadId")
        thread_id = value if isinstance(value, str) else None
    return thread_id, turn_id


def _read_nested_identifier(mapping: Mapping[str, object], key: str) -> str | None:
    value = mapping.get(key)
    if not isinstance(value, Mapping):
        return None
    identifier = cast(Mapping[str, object], value).get("id")
    return identifier if isinstance(identifier, str) else None
