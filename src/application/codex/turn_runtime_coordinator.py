"""Codex turn 权威阶段、fenced lease 与停滞判定协调器。"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_protocol_contract import (
    CodexAgentApprovalOpened,
    CodexAgentHeartbeat,
    CodexAgentRealtimeEvent,
)
from src.core.codex_contract.agent_protocol_v2_contract import (
    AgentApprovalOpenedEventDetail,
    AgentDiffChangedEventDetail,
    AgentItemChangedEventDetail,
    AgentItemDeltaEventDetail,
    AgentPlanChangedEventDetail,
    AgentTurnChangedEventDetail,
)
from src.core.codex_contract.app_server_schema_manifest_contract import AppServerNotificationName
from src.core.codex_contract.approval_contract import CodexApprovalAuditSnapshot, CodexApprovalState
from src.core.codex_contract.thread_contract import (
    CodexActiveTurnUpdateMode,
    CodexThreadIndexSnapshot,
    CodexThreadStatus,
)
from src.core.codex_contract.turn_runtime_contract import CodexTurnPhase, CodexTurnRuntime
from src.core.concurrency_contract.fenced_lease_contract import (
    FencedLease,
    FencedLeasePort,
    FencedLeaseRequest,
)
from src.domain.codex.thread_execution_state import (
    TERMINAL_TURN_PHASES,
    thread_status_for_phase,
)

TURN_RUNTIME_STALLED_REASON = "lease_expired_no_activity"


@dataclass(frozen=True, slots=True)
class TurnRuntimeEventOutcome:
    """实时事件的 fenced runtime 写入结果。"""

    handled: bool
    accepted: bool
    thread: CodexThreadIndexSnapshot | None


@dataclass(frozen=True, slots=True)
class TurnRuntimeSignal:
    """从 Agent 事件提取的最小 turn 生命周期语义。"""

    thread_id: str
    turn_id: str
    phase: CodexTurnPhase | None
    terminal: bool


class CodexTurnRuntimeCoordinator:
    """维护服务端运行态；Redis token 从不进入浏览器或 PostgreSQL。"""

    def __init__(
        self,
        *,
        control_port: CodexControlPort,
        lease_store: FencedLeasePort,
        lease_ttl_seconds: int,
        stalled_after_seconds: int,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._control_port = control_port
        self._lease_store = lease_store
        self._lease_ttl_seconds = lease_ttl_seconds
        self._stalled_after_seconds = stalled_after_seconds
        self._clock = clock or (lambda: datetime.now(UTC))

    async def observe_agent_event(
        self,
        event: CodexAgentRealtimeEvent,
        principal: AgentDevicePrincipal,
    ) -> TurnRuntimeEventOutcome:
        """把带 turn 定位的 Agent 事件收敛为唯一的 fenced 状态迁移。"""

        signal = self._read_event_signal(event)
        if signal is None:
            return TurnRuntimeEventOutcome(handled=False, accepted=True, thread=None)
        return await self._apply_signal(
            host_id=event.host_id,
            owner_subject_id=principal.owner_subject_id,
            agent_owner=self._build_agent_owner(principal, event.app_server_instance_id),
            signal=signal,
            occurred_at=event.occurred_at,
        )

    async def observe_approval_opened(
        self,
        approval: CodexAgentApprovalOpened,
        principal: AgentDevicePrincipal,
    ) -> CodexThreadIndexSnapshot | None:
        """审批等待是活动态，必须阻止 watchdog 将其错误标记为 stalled。"""

        outcome = await self._apply_signal(
            host_id=approval.host_id,
            owner_subject_id=principal.owner_subject_id,
            agent_owner=self._build_agent_owner(principal, approval.app_server_instance_id),
            signal=TurnRuntimeSignal(
                thread_id=approval.thread_id,
                turn_id=approval.turn_id,
                phase=CodexTurnPhase.AWAITING_APPROVAL,
                terminal=False,
            ),
            occurred_at=self._clock(),
        )
        return outcome.thread if outcome.accepted else None

    async def renew_heartbeat_leases(
        self,
        heartbeat: CodexAgentHeartbeat,
        principal: AgentDevicePrincipal,
    ) -> tuple[CodexThreadIndexSnapshot, ...]:
        """只续租连接持有的 turn，不把连接存活记为任务实际进展。"""

        candidates = await asyncio.to_thread(
            self._list_active_turn_runtimes,
            heartbeat.host_id,
            principal.owner_subject_id,
        )
        agent_owner = self._build_agent_owner(principal, heartbeat.app_server_instance_id)
        updated: list[CodexThreadIndexSnapshot] = []
        for thread in candidates:
            runtime = thread.turn_runtime
            if runtime is None:
                continue
            resource_key = self._build_resource_key(
                principal.owner_subject_id,
                heartbeat.host_id,
                runtime.thread_id,
                runtime.turn_id,
            )
            lease = await self._lease_store.read(resource_key)
            if not self._matches_lease(lease, agent_owner, runtime.lease_generation):
                continue
            if lease is None:
                continue
            renewed = await self._lease_store.renew(lease, self._lease_ttl_seconds)
            if renewed is None:
                continue
            refreshed_runtime = runtime.model_copy(
                update={
                    "lease_expires_at": renewed.expires_at,
                }
            )
            persisted = await asyncio.to_thread(
                self._apply_runtime,
                host_id=heartbeat.host_id,
                owner_subject_id=principal.owner_subject_id,
                runtime=refreshed_runtime,
                status=self._status_for_phase(refreshed_runtime.phase),
                active_turn_mode=CodexActiveTurnUpdateMode.SET,
                expected_lease_generation=runtime.lease_generation,
            )
            if persisted is not None:
                updated.append(persisted)
        return tuple(updated)

    async def observe_approval_resolved(
        self, approval: CodexApprovalAuditSnapshot
    ) -> CodexThreadIndexSnapshot | None:
        """Resume a turn only after all its pending requests have settled."""

        return await asyncio.to_thread(self._resume_after_approval, approval)

    def _resume_after_approval(
        self, approval: CodexApprovalAuditSnapshot
    ) -> CodexThreadIndexSnapshot | None:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = self._control_port.create_codex_thread_repository(session)
            thread = repository.get_by_upstream_id_and_owner(
                approval.host_id, approval.thread_id, approval.owner_subject_id
            )
            if thread is None or thread.turn_runtime is None:
                return None
            runtime = thread.turn_runtime
            if runtime.turn_id != approval.turn_id or runtime.phase is not CodexTurnPhase.AWAITING_APPROVAL:
                return None
            now = self._clock()
            pending = self._control_port.create_codex_approval_repository(session).list_by_owner(
                approval.owner_subject_id
            )
            if any(
                item.host_id == approval.host_id
                and item.thread_id == approval.thread_id
                and item.turn_id == approval.turn_id
                and item.state in {
                    CodexApprovalState.PENDING,
                    CodexApprovalState.CLAIMED,
                    CodexApprovalState.DELIVERY_FAILED,
                }
                and (item.expires_at is None or item.expires_at > now)
                for item in pending
            ):
                return None
            observed = thread.model_copy(update={
                "status": CodexThreadStatus.ACTIVE,
                "turn_runtime": runtime.model_copy(update={
                    "phase": CodexTurnPhase.RUNNING,
                    "last_activity_at": max(runtime.last_activity_at, approval.updated_at),
                }),
            })
            updated = repository.reconcile_execution(
                expected=thread, observed=observed, synchronized_at=now
            )
            unit_of_work.commit()
            return updated
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    async def mark_expired_turns_stalled(self) -> tuple[CodexThreadIndexSnapshot, ...]:
        """仅在 lease 已消失且活动超时后标记 stalled，绝不自动创建新 turn。"""

        now = self._clock()
        candidates = await asyncio.to_thread(
            self._list_stalled_candidates,
            now,
        )
        updated: list[CodexThreadIndexSnapshot] = []
        for thread in candidates:
            runtime = thread.turn_runtime
            if runtime is None:
                continue
            resource_key = self._build_resource_key(
                thread.owner_subject_id,
                thread.host_id,
                runtime.thread_id,
                runtime.turn_id,
            )
            if await self._lease_store.read(resource_key) is not None:
                continue
            stalled_runtime = runtime.model_copy(
                update={
                    "phase": CodexTurnPhase.STALLED,
                    "stalled_reason": TURN_RUNTIME_STALLED_REASON,
                    "lease_expires_at": None,
                }
            )
            persisted = await asyncio.to_thread(
                self._apply_runtime,
                host_id=thread.host_id,
                owner_subject_id=thread.owner_subject_id,
                runtime=stalled_runtime,
                status=CodexThreadStatus.ACTIVE,
                active_turn_mode=CodexActiveTurnUpdateMode.SET,
                expected_lease_generation=runtime.lease_generation,
            )
            if persisted is not None:
                updated.append(persisted)
        return tuple(updated)

    async def _apply_signal(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
        agent_owner: str,
        signal: TurnRuntimeSignal,
        occurred_at: datetime,
    ) -> TurnRuntimeEventOutcome:
        """检查 Redis owner 后写入带代次条件的线程运行态。"""

        current = await asyncio.to_thread(
            self._read_thread,
            host_id,
            signal.thread_id,
            owner_subject_id,
        )
        if current is None:
            return TurnRuntimeEventOutcome(handled=True, accepted=False, thread=None)
        current_runtime = current.turn_runtime
        if (
            current_runtime is not None
            and current_runtime.turn_id == signal.turn_id
            and current_runtime.phase in TERMINAL_TURN_PHASES
            and not signal.terminal
        ):
            return TurnRuntimeEventOutcome(handled=True, accepted=False, thread=None)
        if (
            signal.phase is CodexTurnPhase.RUNNING
            and current_runtime is not None
            and current_runtime.turn_id != signal.turn_id
        ):
            if (
                current_runtime.phase
                not in {
                    CodexTurnPhase.COMPLETED,
                    CodexTurnPhase.FAILED,
                    CodexTurnPhase.INTERRUPTED,
                }
                or occurred_at <= current_runtime.last_activity_at
            ):
                return TurnRuntimeEventOutcome(handled=True, accepted=False, thread=None)
        if (
            signal.phase is None
            and current_runtime is not None
            and current_runtime.turn_id != signal.turn_id
        ):
            return TurnRuntimeEventOutcome(handled=True, accepted=False, thread=None)
        resource_key = self._build_resource_key(
            owner_subject_id,
            host_id,
            signal.thread_id,
            signal.turn_id,
        )
        lease, expected_generation = await self._resolve_event_lease(
            resource_key=resource_key,
            agent_owner=agent_owner,
            current_runtime=current_runtime,
            signal=signal,
        )
        if expected_generation is None:
            return TurnRuntimeEventOutcome(handled=True, accepted=False, thread=None)
        phase = signal.phase
        if phase is None and current_runtime is not None:
            phase = current_runtime.phase
        if phase is None:
            return TurnRuntimeEventOutcome(handled=True, accepted=False, thread=None)
        runtime = CodexTurnRuntime(
            turn_id=signal.turn_id,
            thread_id=signal.thread_id,
            phase=phase,
            last_activity_at=self._latest_activity_at(
                current_runtime.last_activity_at if current_runtime is not None else occurred_at,
                occurred_at,
            ),
            stalled_reason=None,
            lease_generation=(lease.fencing_token if lease is not None else expected_generation),
            lease_expires_at=None if signal.terminal else lease.expires_at if lease else None,
        )
        claim_generation = (
            None
            if current_runtime is None
            or current_runtime.turn_id != runtime.turn_id
            or runtime.lease_generation > current_runtime.lease_generation
            else expected_generation
        )
        persisted = await asyncio.to_thread(
            self._apply_runtime,
            host_id=host_id,
            owner_subject_id=owner_subject_id,
            runtime=runtime,
            status=self._status_for_phase(phase),
            active_turn_mode=(
                CodexActiveTurnUpdateMode.CLEAR
                if signal.terminal
                else CodexActiveTurnUpdateMode.SET
            ),
            expected_lease_generation=claim_generation,
        )
        if persisted is None:
            return TurnRuntimeEventOutcome(handled=True, accepted=False, thread=None)
        if signal.terminal and lease is not None:
            await self._lease_store.release(lease)
        return TurnRuntimeEventOutcome(handled=True, accepted=True, thread=persisted)

    async def _resolve_event_lease(
        self,
        *,
        resource_key: str,
        agent_owner: str,
        current_runtime: CodexTurnRuntime | None,
        signal: TurnRuntimeSignal,
    ) -> tuple[FencedLease | None, int | None]:
        """为事件取得当前 fenced lease，终态允许在到期后按旧代次收敛。"""

        lease = await self._lease_store.read(resource_key)
        if lease is not None:
            if current_runtime is None or not self._matches_lease(
                lease,
                agent_owner,
                current_runtime.lease_generation,
            ):
                return None, None
            renewed = await self._lease_store.renew(lease, self._lease_ttl_seconds)
            if renewed is None:
                return None, None
            return renewed, current_runtime.lease_generation
        if signal.terminal and current_runtime is not None:
            if current_runtime.turn_id != signal.turn_id:
                return None, None
            return None, current_runtime.lease_generation
        acquired = await self._lease_store.acquire(
            FencedLeaseRequest(
                resource_key=resource_key,
                owner=agent_owner,
                ttl_seconds=self._lease_ttl_seconds,
            )
        )
        if acquired is None:
            return None, None
        return acquired, current_runtime.lease_generation if current_runtime is not None else 0

    def _read_event_signal(self, event: CodexAgentRealtimeEvent) -> TurnRuntimeSignal | None:
        """仅解析带稳定 thread/turn 标识的官方产品事件。"""

        detail = event.detail
        if isinstance(detail, AgentTurnChangedEventDetail):
            if detail.method is AppServerNotificationName.TURN_STARTED:
                return TurnRuntimeSignal(
                    thread_id=detail.thread_id,
                    turn_id=detail.turn_id,
                    phase=CodexTurnPhase.RUNNING,
                    terminal=False,
                )
            return TurnRuntimeSignal(
                thread_id=detail.thread_id,
                turn_id=detail.turn_id,
                phase=self._phase_for_terminal_status(detail.status),
                terminal=True,
            )
        if isinstance(detail, AgentApprovalOpenedEventDetail):
            return TurnRuntimeSignal(
                thread_id=detail.approval.thread_id,
                turn_id=detail.approval.turn_id,
                phase=CodexTurnPhase.AWAITING_APPROVAL,
                terminal=False,
            )
        if isinstance(
            detail,
            (
                AgentItemChangedEventDetail,
                AgentItemDeltaEventDetail,
                AgentPlanChangedEventDetail,
                AgentDiffChangedEventDetail,
            ),
        ):
            if detail.turn_id is None:
                return None
            return TurnRuntimeSignal(
                thread_id=detail.thread_id,
                turn_id=detail.turn_id,
                phase=None,
                terminal=False,
            )
        return None

    def _read_thread(
        self,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
    ) -> CodexThreadIndexSnapshot | None:
        """读取所有权已约束的线程索引，不在查询路径产生副作用。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            return self._control_port.create_codex_thread_repository(
                unit_of_work.get_session()
            ).get_by_upstream_id_and_owner(host_id, upstream_thread_id, owner_subject_id)
        finally:
            unit_of_work.dispose()

    def _apply_runtime(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
        runtime: CodexTurnRuntime,
        status: CodexThreadStatus,
        active_turn_mode: CodexActiveTurnUpdateMode,
        expected_lease_generation: int | None,
    ) -> CodexThreadIndexSnapshot | None:
        """在一个 UoW 内提交 fenced runtime 写入，失败时完整回滚。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            thread = self._control_port.create_codex_thread_repository(
                unit_of_work.get_session()
            ).apply_turn_runtime(
                host_id=host_id,
                upstream_thread_id=runtime.thread_id,
                owner_subject_id=owner_subject_id,
                runtime=runtime,
                status=status,
                active_turn_mode=active_turn_mode,
                synchronized_at=self._clock(),
                expected_lease_generation=expected_lease_generation,
            )
            unit_of_work.commit()
            return thread
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _list_active_turn_runtimes(
        self,
        host_id: UUID,
        owner_subject_id: str,
    ) -> tuple[CodexThreadIndexSnapshot, ...]:
        """读取心跳续租范围。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            return self._control_port.create_codex_thread_repository(
                unit_of_work.get_session()
            ).list_active_turn_runtimes(
                host_id=host_id,
                owner_subject_id=owner_subject_id,
            )
        finally:
            unit_of_work.dispose()

    def _list_stalled_candidates(
        self,
        now: datetime,
    ) -> tuple[CodexThreadIndexSnapshot, ...]:
        """读取 watchdog 候选，审批等待态由仓储查询显式排除。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            return self._control_port.create_codex_thread_repository(
                unit_of_work.get_session()
            ).list_stalled_turn_runtime_candidates(
                activity_before=now - timedelta(seconds=self._stalled_after_seconds),
                lease_expired_before=now,
            )
        finally:
            unit_of_work.dispose()

    @staticmethod
    def _phase_for_terminal_status(status: str) -> CodexTurnPhase:
        """把 App Server 终态收敛为产品可展示的运行阶段。"""

        if status in {"interrupted", "cancelled"}:
            return CodexTurnPhase.INTERRUPTED
        if status in {"failed", "systemError"}:
            return CodexTurnPhase.FAILED
        return CodexTurnPhase.COMPLETED

    @staticmethod
    def _status_for_phase(phase: CodexTurnPhase) -> CodexThreadStatus:
        """保持旧线程状态契约，同时让 runtime phase 承担更细粒度语义。"""

        return thread_status_for_phase(phase)

    @staticmethod
    def _matches_lease(
        lease: FencedLease | None,
        agent_owner: str,
        generation: int,
    ) -> bool:
        """比较不可泄漏的 Agent owner 摘要与 fencing token。"""

        return (
            lease is not None and lease.owner == agent_owner and lease.fencing_token == generation
        )

    @staticmethod
    def _latest_activity_at(current: datetime, candidate: datetime) -> datetime:
        """活动时间只能前进，乱序事件不得回退会话排序。"""

        return max(current.astimezone(UTC), candidate.astimezone(UTC))

    @staticmethod
    def _build_agent_owner(
        principal: AgentDevicePrincipal,
        app_server_instance_id: str,
    ) -> str:
        """生成 Redis 内可比较但不可反推设备凭据的 owner 摘要。"""

        raw = f"{principal.credential_id}:{app_server_instance_id}".encode()
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _build_resource_key(
        owner_subject_id: str,
        host_id: UUID,
        thread_id: str,
        turn_id: str,
    ) -> str:
        """以摘要隔离所有者与实体维度，防止 Redis key 暴露会话标识。"""

        digest = hashlib.sha256(f"{owner_subject_id}:{thread_id}:{turn_id}".encode()).hexdigest()
        return f"codex_turn_runtime:{host_id}:{digest}"
