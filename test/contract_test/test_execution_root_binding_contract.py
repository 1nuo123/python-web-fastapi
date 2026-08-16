"""执行根绑定公共头与强类型扩展契约测试。"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from src.core.codex_contract.execution_root_binding_contract import (
    EXECUTION_ROOT_BINDING_KIND,
    EXECUTION_ROOT_BINDING_SCHEMA_VERSION,
    ExecutionRootBinding,
    ExecutionRootExtension,
    IsolatedWorktreeExecutionRootExtension,
    RootKind,
    WorkspaceExecutionRootExtension,
)


class TestExecutionRootBindingContract:
    """验证判别联合、版本与执行根类型一致性。"""

    def test_workspace_binding_should_build_versioned_extension(self, tmp_path: Path) -> None:
        binding = ExecutionRootBinding.for_workspace(
            thread_id="thread-workspace",
            workspace_key="workspace",
            execution_root=tmp_path,
        )

        assert binding.kind == EXECUTION_ROOT_BINDING_KIND
        assert binding.schema_version == EXECUTION_ROOT_BINDING_SCHEMA_VERSION
        assert binding.root_kind is RootKind.WORKSPACE
        assert isinstance(binding.extension, WorkspaceExecutionRootExtension)

    def test_worktree_binding_should_reject_outer_inner_kind_mismatch(
        self,
        tmp_path: Path,
    ) -> None:
        with pytest.raises(ValidationError, match="root_kind"):
            ExecutionRootBinding(
                thread_id="thread-worktree",
                workspace_key="workspace",
                execution_root=tmp_path,
                root_kind=RootKind.WORKSPACE,
                extension=IsolatedWorktreeExecutionRootExtension(
                    worktree_id="worktree-1"
                ),
            )

    def test_extension_should_use_discriminator_and_forbid_extra_fields(self) -> None:
        adapter = TypeAdapter(ExecutionRootExtension)

        parsed = adapter.validate_python(
            {
                "kind": RootKind.ISOLATED_WORKTREE.value,
                "schema_version": EXECUTION_ROOT_BINDING_SCHEMA_VERSION,
                "worktree_id": "worktree-1",
            }
        )
        assert isinstance(parsed, IsolatedWorktreeExecutionRootExtension)

        with pytest.raises(ValidationError, match="extra_forbidden"):
            adapter.validate_python(
                {
                    "kind": RootKind.WORKSPACE.value,
                    "schema_version": EXECUTION_ROOT_BINDING_SCHEMA_VERSION,
                    "metadata": {},
                }
            )

    def test_binding_should_reject_relative_execution_root(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationError, match="绝对路径"):
            ExecutionRootBinding.for_workspace(
                thread_id="thread-relative",
                workspace_key="workspace",
                execution_root=Path("relative"),
            )
        assert tmp_path.is_absolute()
