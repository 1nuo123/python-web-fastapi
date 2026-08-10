"""Windows Agent 本地工作区白名单。"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

WINDOWS_BROAD_ACL_IDENTIFIERS: Final = ("S-1-1-0", "S-1-5-32-545", "Everyone", "BUILTIN\\Users")
WINDOWS_WRITE_ACL_MARKERS: Final = ("(F)", "(M)", "(W)")


class AgentWorkspaceAccessError(PermissionError):
    """请求路径不属于本地白名单工作区。"""


class AgentConfigPermissionError(PermissionError):
    """Agent 配置文件 ACL 允许非预期主体写入。"""


class AgentConfigPermissionVerifierPort(Protocol):
    """Agent 配置文件权限校验边界。"""

    def verify(self, path: Path) -> None: ...


class WindowsAgentConfigPermissionVerifier:
    """使用 icacls 拒绝 Everyone 或普通 Users 的写权限。"""

    def verify(self, path: Path) -> None:
        """校验配置文件只允许受信任 Windows 主体修改。"""

        completed = subprocess.run(
            ["icacls", str(path)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for line in completed.stdout.splitlines():
            if any(
                identifier.lower() in line.lower() for identifier in WINDOWS_BROAD_ACL_IDENTIFIERS
            ):
                if any(marker in line.upper() for marker in WINDOWS_WRITE_ACL_MARKERS):
                    raise AgentConfigPermissionError("Agent配置文件权限过宽。")


@dataclass(frozen=True, slots=True)
class AgentWorkspaceDefinition:
    """本地工作区登记项；绝对路径永不发送到控制面。"""

    key: str
    display_name: str
    root: Path
    allow_write: bool

    def __post_init__(self) -> None:
        if not self.key.strip() or not self.display_name.strip():
            raise ValueError("工作区key和display_name不能为空。")
        if not self.root.is_absolute():
            raise ValueError("工作区root必须是绝对路径。")


class AgentWorkspaceRegistry:
    """解析白名单路径并阻止目录穿越、符号链接和 junction 逃逸。"""

    def __init__(self, workspaces: list[AgentWorkspaceDefinition]) -> None:
        keys = [workspace.key for workspace in workspaces]
        if len(keys) != len(set(keys)):
            raise ValueError("工作区key不允许重复。")
        self._workspaces = {workspace.key: workspace for workspace in workspaces}

    def list_workspaces(self) -> list[AgentWorkspaceDefinition]:
        """返回稳定排序的本地白名单。"""

        return [self._workspaces[key] for key in sorted(self._workspaces)]

    def resolve_root(self, workspace_key: str, *, require_write: bool = False) -> Path:
        """解析工作区根，并按命令性质验证写权限。"""

        workspace = self._read_workspace(workspace_key)
        if require_write and not workspace.allow_write:
            raise AgentWorkspaceAccessError("工作区未授权远程写入。")
        return workspace.root.resolve(strict=True)

    def resolve_path(
        self,
        workspace_key: str,
        relative_path: str | Path,
        *,
        require_write: bool = False,
    ) -> Path:
        """在解析链接后确认候选路径仍位于白名单根内。"""

        root = self.resolve_root(workspace_key, require_write=require_write)
        relative = Path(relative_path)
        if relative.is_absolute():
            raise AgentWorkspaceAccessError("远程路径必须使用工作区相对路径。")
        candidate = (root / relative).resolve(strict=False)
        if candidate != root and not candidate.is_relative_to(root):
            raise AgentWorkspaceAccessError("远程路径逃出工作区白名单。")
        return candidate

    def build_repo_fingerprint(self, workspace_key: str) -> str:
        """生成只用于同一 Agent 内稳定关联的路径摘要。"""

        root = self.resolve_root(workspace_key)
        return hashlib.sha256(str(root).casefold().encode("utf-8")).hexdigest()

    def _read_workspace(self, workspace_key: str) -> AgentWorkspaceDefinition:
        try:
            return self._workspaces[workspace_key]
        except KeyError as exc:
            raise AgentWorkspaceAccessError("工作区不在本地白名单中。") from exc
