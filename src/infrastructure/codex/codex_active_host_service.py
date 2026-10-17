"""复用原子状态 CAS 管理账号级活动主机；未确认旧执行停止绝不授予新主机。"""

import asyncio
from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.active_host_contract import CodexActiveHostState
from src.core.distributed_state_contract.atomic_state_contract import (
    AtomicStatePort,
    AtomicStateRecord,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode


class CodexActiveHostService:
    def __init__(self, state: AtomicStatePort, control: CodexControlPort) -> None:
        self._state = state
        self._control = control

    def _key(self, owner: str) -> str:
        return f"codex:active_host:{owner}"

    async def read(self, owner: str) -> CodexActiveHostState:
        record = await self._state.read(self._key(owner))
        if record is None:
            return CodexActiveHostState()
        current = CodexActiveHostState.model_validate_json(record.value).model_copy(
            update={"version": record.version}
        )
        return current

    async def switch(
        self, owner: str, host_id: UUID, expected_version: int
    ) -> CodexActiveHostState:
        await asyncio.to_thread(self._require_owned, owner, host_id)
        current = await self.read(owner)
        if current.version != expected_version or current.draining_host_id is not None:
            raise self._conflict("连接选择已变化或旧电脑仍在收尾，请刷新后重试。")
        if current.active_host_id == host_id:
            return current
        now = datetime.now(UTC)
        next_state = CodexActiveHostState(
            active_host_id=host_id if current.active_host_id is None else None,
            draining_host_id=current.active_host_id,
            target_host_id=host_id if current.active_host_id is not None else None,
            activated_at=now if current.active_host_id is None else None,
            drain_until=None,
        )
        if current.version == 0:
            created = await self._state.create(
                AtomicStateRecord(
                    key=self._key(owner), value=next_state.model_dump_json(), version=1
                )
            )
            if not created:
                raise self._conflict("另一个窗口已选择连接，请刷新。")
        else:
            changed = await self._state.compare_and_set(
                key=self._key(owner),
                expected_version=current.version,
                next_value=next_state.model_dump_json(),
                expires_at=None,
            )
            if changed is None:
                raise self._conflict("另一个窗口已选择连接，请刷新。")
        return await self.read(owner)

    async def acknowledge_stopped(self, owner: str, host_id: UUID, generation: int) -> None:
        current = await self.read(owner)
        if current.version != generation or current.draining_host_id != host_id:
            return
        if current.target_host_id is not None:
            await asyncio.to_thread(self._require_owned, owner, current.target_host_id)
        next_state = CodexActiveHostState(
            active_host_id=current.target_host_id, activated_at=datetime.now(UTC)
        )
        await self._state.compare_and_set(
            key=self._key(owner),
            expected_version=generation,
            next_value=next_state.model_dump_json(),
            expires_at=None,
        )

    async def permits(self, owner: str, host_id: UUID, created_at: datetime | None = None) -> bool:
        current = await self.read(owner)
        return current.active_host_id == host_id and (
            created_at is None
            or current.activated_at is not None
            and created_at >= current.activated_at
        )

    async def revoke(self, owner: str, host_id: UUID) -> None:
        while True:
            current = await self.read(owner)
            if current.active_host_id == host_id:
                next_state = CodexActiveHostState(draining_host_id=host_id)
            elif current.target_host_id == host_id:
                next_state = current.model_copy(update={"target_host_id": None})
            else:
                return
            changed = await self._state.compare_and_set(
                key=self._key(owner),
                expected_version=current.version,
                next_value=next_state.model_dump_json(),
                expires_at=None,
            )
            if changed is not None:
                return

    def _is_owned(self, owner: str, host_id: UUID) -> bool:
        unit = self._control.create_unit_of_work()
        try:
            host = self._control.create_codex_host_repository(
                unit.get_session()
            ).get_by_id_and_owner(host_id, owner)
            return host is not None and host.revoked_at is None
        finally:
            unit.dispose()

    def _require_owned(self, owner: str, host_id: UUID) -> None:
        if not self._is_owned(owner, host_id):
            raise HttpFaultException(
                status_code=HTTPStatus.NOT_FOUND,
                error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
                message="电脑不存在或已撤销。",
            )

    def _conflict(self, message: str) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.CONFLICT,
            error_code=CodexErrorCode.STATE_CONFLICT,
            message=message,
        )
