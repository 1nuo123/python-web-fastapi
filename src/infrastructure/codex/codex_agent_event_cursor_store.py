"""复用通用原子状态持久化 Codex Agent 事件累计确认游标。"""

from __future__ import annotations

from typing import Final
from uuid import UUID

from pydantic import ValidationError

from src.core.codex_contract.agent_event_cursor_contract import (
    CodexAgentEventCursorState,
)
from src.core.distributed_state_contract.atomic_state_contract import (
    AtomicStatePort,
    AtomicStateRecord,
)

CODEX_AGENT_EVENT_CURSOR_KEY_NAMESPACE: Final = "codex:agent_event_cursor"
CODEX_AGENT_EVENT_CURSOR_INITIAL_VERSION: Final = 1
CODEX_AGENT_EVENT_CURSOR_CAS_RETRY_LIMIT: Final = 8


class CodexAgentEventEpochConflictError(ValueError):
    """旧事件 epoch 尝试推进当前主机的新游标。"""


class CodexAgentEventCursorStore:
    """为同一主机保留一个跨连接、跨实例的累计事件游标。"""

    def __init__(self, *, state: AtomicStatePort) -> None:
        self._state = state

    async def load_or_start(self, *, host_id: UUID, event_epoch: UUID) -> int:
        """读取相同 epoch 的累计 ACK，或原子切换到新 epoch。"""

        key = self._key(host_id)
        initial = CodexAgentEventCursorState(
            host_id=host_id,
            agent_event_epoch=event_epoch,
            after_seq=0,
        )
        for _attempt in range(CODEX_AGENT_EVENT_CURSOR_CAS_RETRY_LIMIT):
            current = await self._state.read(key)
            if current is None:
                created = await self._state.create(
                    AtomicStateRecord(
                        key=key,
                        value=initial.model_dump_json(),
                        version=CODEX_AGENT_EVENT_CURSOR_INITIAL_VERSION,
                    )
                )
                if created:
                    return initial.after_seq
                continue
            cursor = self._parse(current.value, expected_host_id=host_id)
            if cursor.agent_event_epoch == event_epoch:
                return cursor.after_seq
            changed = await self._state.compare_and_set(
                key=key,
                expected_version=current.version,
                next_value=initial.model_dump_json(),
                expires_at=None,
            )
            if changed is not None:
                return initial.after_seq
        raise RuntimeError("Agent事件游标初始化达到并发重试上限。")

    async def advance(
        self,
        *,
        host_id: UUID,
        event_epoch: UUID,
        after_seq: int,
    ) -> int:
        """以单调 CAS 推进累计 ACK，并拒绝旧 epoch 覆盖新状态。"""

        candidate = CodexAgentEventCursorState(
            host_id=host_id,
            agent_event_epoch=event_epoch,
            after_seq=after_seq,
        )
        key = self._key(host_id)
        for _attempt in range(CODEX_AGENT_EVENT_CURSOR_CAS_RETRY_LIMIT):
            current = await self._state.read(key)
            if current is None:
                created = await self._state.create(
                    AtomicStateRecord(
                        key=key,
                        value=candidate.model_dump_json(),
                        version=CODEX_AGENT_EVENT_CURSOR_INITIAL_VERSION,
                    )
                )
                if created:
                    return candidate.after_seq
                continue
            cursor = self._parse(current.value, expected_host_id=host_id)
            if cursor.agent_event_epoch != event_epoch:
                raise CodexAgentEventEpochConflictError(
                    "Agent事件epoch已经切换，旧连接不得推进累计游标。"
                )
            if after_seq <= cursor.after_seq:
                return cursor.after_seq
            changed = await self._state.compare_and_set(
                key=key,
                expected_version=current.version,
                next_value=candidate.model_dump_json(),
                expires_at=None,
            )
            if changed is not None:
                return candidate.after_seq
        raise RuntimeError("Agent事件游标推进达到并发重试上限。")

    def _parse(self, value: str, *, expected_host_id: UUID) -> CodexAgentEventCursorState:
        """解析强类型状态并核对主机归属。"""

        try:
            cursor = CodexAgentEventCursorState.model_validate_json(value)
        except ValidationError as exc:
            raise ValueError("Agent事件游标状态不符合契约。") from exc
        if cursor.host_id != expected_host_id:
            raise ValueError("Agent事件游标状态的host_id不匹配。")
        return cursor

    def _key(self, host_id: UUID) -> str:
        return f"{CODEX_AGENT_EVENT_CURSOR_KEY_NAMESPACE}:{host_id}"
