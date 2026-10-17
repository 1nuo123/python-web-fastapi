"""诊断、连接与更新共用的本机状态投影。"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import portalocker
import psutil

from src.core.codex_contract.agent_runtime_health_contract import AgentRuntimeStatus


class AgentRuntimeStatusStore:
    def __init__(self, state_database: Path) -> None:
        self._path = state_database.with_name("runtime-status.json")

    def read(self) -> AgentRuntimeStatus | None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            created_at = payload.pop("_process_created_at", None)
            status = AgentRuntimeStatus.model_validate(payload)
            if status.connection_state in (None, "stopped"):
                return status
            fresh = (
                status.connection_updated_at is not None
                and 0 <= (datetime.now(UTC) - status.connection_updated_at).total_seconds() <= 120
            )
            alive = False
            if status.process_id and created_at is not None:
                try:
                    alive = psutil.Process(status.process_id).create_time() == created_at
                except psutil.Error:
                    pass
            if not alive or not fresh:
                return status.model_copy(
                    update={
                        "connection_state": "stopped",
                        "process_id": None,
                        "connection_reason": "process_not_running"
                        if not alive
                        else "status_expired",
                    }
                )
            return status
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def update(self, updates: dict[str, object]) -> None:
        """多个进程只更新各自拥有的字段，原子发布完整状态。"""

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with portalocker.Lock(self._path.with_suffix(".lock"), timeout=10):
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
                created_at = payload.pop("_process_created_at", None)
                previous = AgentRuntimeStatus.model_validate(payload)
            except (OSError, ValueError, TypeError, AttributeError):
                previous, created_at = AgentRuntimeStatus(), None
            status = AgentRuntimeStatus.model_validate({**previous.model_dump(), **updates})
            if updates.get("process_id") == os.getpid():
                created_at = psutil.Process().create_time()
            temporary = self._path.with_name(f".{self._path.name}.tmp")
            try:
                payload = {**status.model_dump(mode="json"), "_process_created_at": created_at}
                temporary.write_text(json.dumps(payload) + "\n", encoding="utf-8")
                temporary.replace(self._path)
            finally:
                temporary.unlink(missing_ok=True)
