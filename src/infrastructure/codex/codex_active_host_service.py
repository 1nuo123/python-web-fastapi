"""以同一 CAS 状态关闭续租、等待停止证明或许可到期、授予下一台电脑。"""

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from http import HTTPStatus
from uuid import UUID

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.active_host_contract import CodexActiveHostState
from src.core.codex_contract.agent_connection_contract import AGENT_EXECUTION_LEASE_MAX_SECONDS
from src.core.distributed_state_contract.atomic_state_contract import (
    AtomicStatePort,
    AtomicStateRecord,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode


class CodexActiveHostService:
    def __init__(
        self,
        state: AtomicStatePort,
        control: CodexControlPort,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._state = state
        self._control = control
        self._clock = clock or (lambda: datetime.now(UTC))
        self._logger = logging.getLogger(__name__)

    def _key(self, owner: str) -> str:
        return f"codex:active_host:{owner}"

    async def read(self, owner: str) -> CodexActiveHostState:
        """只读持久状态；需要推进生命周期的入口显式调用 reconcile。"""
        record = await self._state.read(self._key(owner))
        if record is None:
            return CodexActiveHostState()
        return CodexActiveHostState.model_validate_json(record.value).model_copy(
            update={"version": record.version}
        )

    async def reconcile(self, owner: str) -> CodexActiveHostState:
        """持久化收尾期限或完成到期交接；可由请求和心跳重复驱动。"""
        while True:
            current = await self.read(owner)
            if current.draining_host_id is None:
                return current
            now = self._clock()
            if current.drain_until is None:
                # 必须先读到已提交的 draining，再开始完整许可窗口。不能在
                # 关闭续租的 CAS 之前计时：存储延迟可能让那个期限提前失效。
                # Agent 按请求发出时间计许可，迟到的旧响应不会延长此上界。
                next_state = current.model_copy(
                    update={
                        "drain_until": now + timedelta(seconds=AGENT_EXECUTION_LEASE_MAX_SECONDS)
                    }
                )
                saved = await self._save(owner, current, next_state)
                if saved is not None:
                    self._log_transition("drain_started", saved)
                    return saved
            elif now < current.drain_until:
                return current
            else:
                saved = await self._finish_drain(owner, current, reason="lease_expired")
                if saved is not None:
                    return saved

    async def switch(
        self, owner: str, host_id: UUID, expected_version: int
    ) -> CodexActiveHostState:
        await asyncio.to_thread(self._require_owned, owner, host_id)
        current = await self.reconcile(owner)
        if current.active_host_id == host_id or current.target_host_id == host_id:
            return current
        if current.version != expected_version:
            raise self._conflict("连接选择已变化，请刷新后重试。")
        if current.draining_host_id is not None:
            # 允许选定/替换目标，但不能重置旧电脑的收尾期限或提前授予资格。
            next_state = current.model_copy(update={"target_host_id": host_id})
        elif current.active_host_id is not None:
            next_state = CodexActiveHostState(
                draining_host_id=current.active_host_id,
                target_host_id=host_id,
            )
        else:
            next_state = CodexActiveHostState(active_host_id=host_id, activated_at=self._clock())
        saved = await self._save(owner, current, next_state)
        if saved is None:
            raise self._conflict("另一个窗口已选择连接，请刷新。")
        self._log_transition("switch_requested", saved)
        return await self.reconcile(owner)

    async def acknowledge_stopped(self, owner: str, host_id: UUID, generation: int) -> None:
        current = await self.read(owner)
        if current.version != generation or current.draining_host_id != host_id:
            return
        # 过期确认不能推进另一轮切换；CAS 失败交由当前代次心跳/请求推进。
        await self._finish_drain(owner, current, reason="stop_acknowledged")

    async def _finish_drain(
        self, owner: str, current: CodexActiveHostState, *, reason: str
    ) -> CodexActiveHostState | None:
        target = current.target_host_id
        if target is not None and not await asyncio.to_thread(self._is_owned, owner, target):
            target = None
        saved = await self._save(
            owner,
            current,
            CodexActiveHostState(
                active_host_id=target,
                activated_at=self._clock() if target is not None else None,
            ),
        )
        if saved is not None:
            self._logger.info(
                "active_host_drain_completed reason=%s previous_host=%s target_host=%s generation=%s",
                reason,
                current.draining_host_id,
                saved.active_host_id,
                saved.version,
            )
        return saved

    async def permits(self, owner: str, host_id: UUID, created_at: datetime | None = None) -> bool:
        current = await self.reconcile(owner)
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
                await self.reconcile(owner)
                return
            saved = await self._save(owner, current, next_state)
            if saved is not None:
                self._log_transition("host_revoked", saved)
                await self.reconcile(owner)
                return

    async def _save(
        self, owner: str, current: CodexActiveHostState, next_state: CodexActiveHostState
    ) -> CodexActiveHostState | None:
        if current.version == 0:
            record = AtomicStateRecord(
                key=self._key(owner), value=next_state.model_dump_json(), version=1
            )
            if not await self._state.create(record):
                return None
        else:
            record = await self._state.compare_and_set(
                key=self._key(owner),
                expected_version=current.version,
                next_value=next_state.model_dump_json(),
                expires_at=None,
            )
            if record is None:
                return None
        return next_state.model_copy(update={"version": record.version})

    def _log_transition(self, reason: str, state: CodexActiveHostState) -> None:
        self._logger.info(
            "active_host_transition reason=%s active_host=%s draining_host=%s "
            "target_host=%s generation=%s drain_until=%s",
            reason,
            state.active_host_id,
            state.draining_host_id,
            state.target_host_id,
            state.version,
            state.drain_until,
        )

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
