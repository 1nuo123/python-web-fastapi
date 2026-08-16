"""Agent 执行根绑定存储单元测试。"""

from __future__ import annotations

from pathlib import Path

from src.core.codex_contract.execution_root_binding_contract import ExecutionRootBinding
from src.infrastructure.codex_agent.agent_execution_root_store import (
    EXECUTION_ROOT_CORRUPT_SUFFIX,
    AgentExecutionRootStore,
    ExecutionRootBindingMissingError,
)


class TestAgentExecutionRootStoreUnit:
    """验证原子保存、重启恢复、删除与损坏隔离。"""

    def test_store_should_persist_and_restore_binding(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        store_path = tmp_path / "execution-roots.json"
        binding = ExecutionRootBinding.for_workspace(
            thread_id="thread-1",
            workspace_key="workspace",
            execution_root=workspace,
        )

        AgentExecutionRootStore(store_path).save(binding)
        restored = AgentExecutionRootStore(store_path).require("thread-1")

        assert restored == binding
        assert not store_path.with_name(f".{store_path.name}.tmp").exists()

    def test_store_should_delete_invalid_binding_and_raise_stable_error(
        self,
        tmp_path: Path,
    ) -> None:
        store = AgentExecutionRootStore(tmp_path / "execution-roots.json")

        try:
            store.require("missing-thread")
        except ExecutionRootBindingMissingError as exc:
            assert "不存在或已失效" in str(exc)
        else:
            raise AssertionError("缺失绑定未抛出稳定异常。")

    def test_store_should_quarantine_corrupt_file_and_recover(self, tmp_path: Path) -> None:
        store_path = tmp_path / "execution-roots.json"
        store_path.write_text("{", encoding="utf-8")
        store = AgentExecutionRootStore(store_path)

        assert store.load("thread-1") is None
        assert store_path.with_name(store_path.name + EXECUTION_ROOT_CORRUPT_SUFFIX).is_file()

        workspace = tmp_path / "workspace"
        workspace.mkdir()
        store.save(
            ExecutionRootBinding.for_workspace(
                thread_id="thread-1",
                workspace_key="workspace",
                execution_root=workspace,
            )
        )
        assert store.require("thread-1").execution_root == workspace
