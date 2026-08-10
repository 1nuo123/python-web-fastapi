"""基于通用原子状态的 Codex Agent 撤销信号适配器。"""

from __future__ import annotations

from uuid import UUID, uuid4

from src.application.ports.codex_agent_revocation_signal_port import (
    CodexAgentRevocationSignalPort,
)
from src.core.codex_contract.instance_control_contract import (
    CodexInstanceControlSignal,
    CodexRevokeSignalDetail,
)
from src.core.codex_contract.presence_contract import CodexHostPresence
from src.core.distributed_state_contract.atomic_state_contract import (
    AtomicStatePort,
    AtomicStateRecord,
)
from src.infrastructure.codex.codex_connection_registry import CodexConnectionRegistry
from src.infrastructure.codex.codex_host_presence_adapter import CodexHostPresenceAdapter
from src.infrastructure.codex.codex_instance_control_signal_adapter import (
    CodexInstanceControlSignalAdapter,
)

CODEX_REVOCATION_GENERATION_KEY_NAMESPACE = "codex:revocation_generation"
CODEX_REVOCATION_INITIAL_GENERATION = 1
CODEX_REVOCATION_CAS_RETRY_LIMIT = 8


class CodexAgentRevocationSignal(CodexAgentRevocationSignalPort):
    """持久化撤销代次并关闭当前实例上的旧连接。"""

    def __init__(
        self,
        *,
        state: AtomicStatePort,
        connection_registry: CodexConnectionRegistry,
        presence: CodexHostPresenceAdapter | None = None,
        signal_adapter: CodexInstanceControlSignalAdapter | None = None,
        instance_id: UUID | None = None,
    ) -> None:
        self._state = state
        self._connection_registry = connection_registry
        self._presence = presence
        self._signal_adapter = signal_adapter
        self._instance_id = instance_id

    async def read_generation(self, host_id: UUID) -> int:
        record = await self._state.read(self._key(host_id))
        return 0 if record is None else int(record.value)

    async def revoke(self, host_id: UUID) -> int:
        key = self._key(host_id)
        presence = await self._presence.read(host_id) if self._presence is not None else None
        for _attempt in range(CODEX_REVOCATION_CAS_RETRY_LIMIT):
            current = await self._state.read(key)
            if current is None:
                created = await self._state.create(
                    AtomicStateRecord(
                        key=key,
                        value=str(CODEX_REVOCATION_INITIAL_GENERATION),
                        version=CODEX_REVOCATION_INITIAL_GENERATION,
                    )
                )
                if created:
                    await self._notify_revoke(
                        host_id, CODEX_REVOCATION_INITIAL_GENERATION, presence
                    )
                    return CODEX_REVOCATION_INITIAL_GENERATION
                continue
            generation = int(current.value) + 1
            changed = await self._state.compare_and_set(
                key=key,
                expected_version=current.version,
                next_value=str(generation),
                expires_at=None,
            )
            if changed is not None:
                await self._notify_revoke(host_id, generation, presence)
                return generation
        raise RuntimeError("Agent撤销代次更新达到并发重试上限。")

    async def _notify_revoke(
        self,
        host_id: UUID,
        generation: int,
        presence: CodexHostPresence | None,
    ) -> None:
        """本实例立即关闭；远端实例通过 cursor stream 接收撤销。"""

        await self._connection_registry.revoke(host_id)
        if (
            self._signal_adapter is None
            or self._instance_id is None
            or presence is None
            or presence.owner.instance_id == self._instance_id
        ):
            return
        await self._signal_adapter.publish(
            CodexInstanceControlSignal(
                signal_id=uuid4(),
                target_instance_id=presence.owner.instance_id,
                detail=CodexRevokeSignalDetail(
                    host_id=host_id,
                    revocation_generation=generation,
                ),
            )
        )

    def _key(self, host_id: UUID) -> str:
        return f"{CODEX_REVOCATION_GENERATION_KEY_NAMESPACE}:{host_id}"
