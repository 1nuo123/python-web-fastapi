"""诊断、连接与更新共用的本机状态投影。"""

from __future__ import annotations

from pathlib import Path

import portalocker

from src.core.codex_contract.agent_runtime_health_contract import AgentRuntimeStatus


class AgentRuntimeStatusStore:
    def __init__(self, state_database: Path) -> None:
        self._path = state_database.with_name("runtime-status.json")

    def read(self) -> AgentRuntimeStatus | None:
        try:
            return AgentRuntimeStatus.model_validate_json(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def update(self, updates: dict[str, object]) -> None:
        """多个进程只更新各自拥有的字段，原子发布完整状态。"""

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with portalocker.Lock(self._path.with_suffix(".lock"), timeout=10):
            previous = self.read() or AgentRuntimeStatus()
            status = AgentRuntimeStatus.model_validate({**previous.model_dump(), **updates})
            temporary = self._path.with_name(f".{self._path.name}.tmp")
            try:
                temporary.write_text(status.model_dump_json() + "\n", encoding="utf-8")
                temporary.replace(self._path)
            finally:
                temporary.unlink(missing_ok=True)
