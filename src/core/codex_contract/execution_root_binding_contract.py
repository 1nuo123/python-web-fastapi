"""Codex Agent 执行根绑定的公共头与强类型扩展契约。"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EXECUTION_ROOT_BINDING_KIND: Final = "codex_execution_root_binding"
EXECUTION_ROOT_BINDING_SCHEMA_VERSION: Final = "1.0"
EXECUTION_ROOT_THREAD_ID_MAXIMUM_LENGTH: Final = 256
EXECUTION_ROOT_WORKSPACE_KEY_MAXIMUM_LENGTH: Final = 128
EXECUTION_ROOT_WORKTREE_ID_MAXIMUM_LENGTH: Final = 128


class RootKind(StrEnum):
    """执行根的封闭类型集合。"""

    WORKSPACE = "workspace"
    GIT_REPOSITORY = "git_repository"
    ISOLATED_WORKTREE = "isolated_worktree"


class WorktreeIsolationMode(StrEnum):
    """工作区是否允许使用 Git worktree 隔离。"""

    DISABLED = "disabled"
    ENABLED = "enabled"


class WorkspaceExecutionRootExtension(BaseModel):
    """普通工作区执行根扩展。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["workspace"] = RootKind.WORKSPACE.value
    schema_version: Literal["1.0"] = EXECUTION_ROOT_BINDING_SCHEMA_VERSION


class GitRepositoryExecutionRootExtension(BaseModel):
    """Git 仓库执行根扩展。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["git_repository"] = RootKind.GIT_REPOSITORY.value
    schema_version: Literal["1.0"] = EXECUTION_ROOT_BINDING_SCHEMA_VERSION


class IsolatedWorktreeExecutionRootExtension(BaseModel):
    """隔离 worktree 执行根扩展。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["isolated_worktree"] = RootKind.ISOLATED_WORKTREE.value
    schema_version: Literal["1.0"] = EXECUTION_ROOT_BINDING_SCHEMA_VERSION
    worktree_id: str = Field(
        min_length=1,
        max_length=EXECUTION_ROOT_WORKTREE_ID_MAXIMUM_LENGTH,
    )


ExecutionRootExtension = Annotated[
    WorkspaceExecutionRootExtension
    | GitRepositoryExecutionRootExtension
    | IsolatedWorktreeExecutionRootExtension,
    Field(discriminator="kind"),
]


class ExecutionRootBinding(BaseModel):
    """线程与本机执行根之间的持久化绑定。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["codex_execution_root_binding"] = EXECUTION_ROOT_BINDING_KIND
    schema_version: Literal["1.0"] = EXECUTION_ROOT_BINDING_SCHEMA_VERSION
    thread_id: str = Field(
        min_length=1,
        max_length=EXECUTION_ROOT_THREAD_ID_MAXIMUM_LENGTH,
    )
    workspace_key: str = Field(
        min_length=1,
        max_length=EXECUTION_ROOT_WORKSPACE_KEY_MAXIMUM_LENGTH,
    )
    execution_root: Path
    root_kind: RootKind
    extension: ExecutionRootExtension | None = None

    @field_validator("execution_root")
    @classmethod
    def validate_absolute_execution_root(cls, value: Path) -> Path:
        """拒绝依赖进程当前目录解释的相对执行根。"""

        if not value.is_absolute():
            raise ValueError("执行根必须是绝对路径。")
        return value

    @model_validator(mode="after")
    def validate_extension(self) -> ExecutionRootBinding:
        """确保外层 root_kind/schema_version 与扩展完全一致。"""

        expected_extension_kind = self.root_kind.value
        extension = self.extension
        if extension is None:
            extension = self._build_default_extension()
            object.__setattr__(self, "extension", extension)
        if extension.kind != expected_extension_kind:
            raise ValueError("执行根绑定root_kind与扩展kind不一致。")
        if extension.schema_version != self.schema_version:
            raise ValueError("执行根绑定schema_version与扩展版本不一致。")
        return self

    def _build_default_extension(self) -> ExecutionRootExtension:
        if self.root_kind is RootKind.WORKSPACE:
            return WorkspaceExecutionRootExtension()
        if self.root_kind is RootKind.GIT_REPOSITORY:
            return GitRepositoryExecutionRootExtension()
        return IsolatedWorktreeExecutionRootExtension(worktree_id=self.thread_id)

    @classmethod
    def for_workspace(
        cls,
        *,
        thread_id: str,
        workspace_key: str,
        execution_root: Path,
        root_kind: RootKind = RootKind.WORKSPACE,
    ) -> ExecutionRootBinding:
        """构造普通 workspace 或 Git repository 执行根绑定。"""

        if root_kind is RootKind.ISOLATED_WORKTREE:
            raise ValueError("隔离worktree必须使用for_worktree构造。")
        return cls(
            thread_id=thread_id,
            workspace_key=workspace_key,
            execution_root=execution_root,
            root_kind=root_kind,
        )

    @classmethod
    def for_worktree(
        cls,
        *,
        thread_id: str,
        workspace_key: str,
        execution_root: Path,
        worktree_id: str,
    ) -> ExecutionRootBinding:
        """构造隔离 worktree 执行根绑定。"""

        return cls(
            thread_id=thread_id,
            workspace_key=workspace_key,
            execution_root=execution_root,
            root_kind=RootKind.ISOLATED_WORKTREE,
            extension=IsolatedWorktreeExecutionRootExtension(worktree_id=worktree_id),
        )
