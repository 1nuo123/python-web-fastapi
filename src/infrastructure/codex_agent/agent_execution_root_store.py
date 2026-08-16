"""Codex Agent 线程执行根绑定的原子本地存储。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final

from src.core.codex_contract.execution_root_binding_contract import ExecutionRootBinding

EXECUTION_ROOT_STORE_VERSION: Final = "1.0"
EXECUTION_ROOT_STORE_FILE_NAME: Final = "execution-roots.json"
EXECUTION_ROOT_CORRUPT_SUFFIX: Final = ".corrupt"


class AgentExecutionRootStoreError(OSError):
    """执行根绑定存储无法读取或写入。"""


class ExecutionRootBindingMissingError(AgentExecutionRootStoreError):
    """请求的线程没有可恢复执行根绑定。"""


class AgentExecutionRootStore:
    """以单文件 JSON 记录线程绑定，并使用替换写入保证原子性。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    @classmethod
    def from_state_directory(cls, state_directory: Path) -> AgentExecutionRootStore:
        """从 Agent 状态目录构造绑定存储。"""

        return cls(state_directory / EXECUTION_ROOT_STORE_FILE_NAME)

    def save(self, binding: ExecutionRootBinding) -> None:
        """原子保存一个线程绑定。"""

        entries = self._read_entries(recover_corrupt=True)
        entries[binding.thread_id] = binding.model_dump(mode="json")
        self._write_entries(entries)

    def load(self, thread_id: str) -> ExecutionRootBinding | None:
        """读取线程绑定；不存在时返回None。"""

        payload = self._read_entries(recover_corrupt=True).get(thread_id)
        if payload is None:
            return None
        try:
            return ExecutionRootBinding.model_validate(payload)
        except ValueError:
            self.delete(thread_id)
            return None

    def require(self, thread_id: str) -> ExecutionRootBinding:
        """读取线程绑定；缺失或损坏时抛出稳定异常。"""

        binding = self.load(thread_id)
        if binding is None:
            raise ExecutionRootBindingMissingError("线程执行根绑定不存在或已失效。")
        return binding

    def delete(self, thread_id: str) -> None:
        """删除单条线程绑定。"""

        entries = self._read_entries(recover_corrupt=True)
        if thread_id in entries:
            del entries[thread_id]
            self._write_entries(entries)

    def clear(self) -> None:
        """清空所有本地绑定。"""

        self._write_entries({})

    def list_bindings(self) -> tuple[ExecutionRootBinding, ...]:
        """返回当前可解析的全部绑定。"""

        bindings: list[ExecutionRootBinding] = []
        for thread_id in tuple(self._read_entries(recover_corrupt=True)):
            binding = self.load(thread_id)
            if binding is not None:
                bindings.append(binding)
        return tuple(bindings)

    def _read_entries(self, *, recover_corrupt: bool) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {}
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("执行根绑定存储顶层必须是对象。")
            version = payload.get("schema_version")
            entries = payload.get("bindings")
            if version != EXECUTION_ROOT_STORE_VERSION or not isinstance(entries, dict):
                raise ValueError("执行根绑定存储版本或bindings字段无效。")
            return {
                str(thread_id): dict(value)
                for thread_id, value in entries.items()
                if isinstance(value, dict)
            }
        except (OSError, UnicodeError, TypeError, ValueError, json.JSONDecodeError) as exc:
            if not recover_corrupt:
                raise AgentExecutionRootStoreError("执行根绑定存储损坏。") from exc
            corrupt_path = self._path.with_name(self._path.name + EXECUTION_ROOT_CORRUPT_SUFFIX)
            try:
                os.replace(self._path, corrupt_path)
            except OSError as replace_exc:
                raise AgentExecutionRootStoreError("执行根绑定存储损坏且无法隔离。") from replace_exc
            return {}

    def _write_entries(self, entries: dict[str, dict[str, object]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_name(f".{self._path.name}.tmp")
        payload = {
            "kind": "codex_execution_root_store",
            "schema_version": EXECUTION_ROOT_STORE_VERSION,
            "bindings": entries,
        }
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self._path)
        except (OSError, TypeError, ValueError) as exc:
            raise AgentExecutionRootStoreError("执行根绑定保存失败。") from exc
        finally:
            temporary_path.unlink(missing_ok=True)
