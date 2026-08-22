"""Codex turn runtime lease、watchdog 与服务端活动时间单元测试。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from uuid import UUID, uuid4

import pytest

from src.application.codex.sync_agent_state_usecase import SyncCodexAgentStateUsecase
from src.application.codex.turn_runtime_coordinator import CodexTurnRuntimeCoordinator
from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.agent_device_auth_contract import AgentDevicePrincipal
from src.core.codex_contract.agent_protocol_contract import (
    AgentConversationSnapshotDetail,
    CodexAgentApprovalOpened,
    CodexAgentHeartbeat,
    CodexAgentRealtimeEvent,
)
from src.core.codex_contract.agent_protocol_v2_contract import AgentTurnChangedEventDetail
from src.core.codex_contract.app_server_schema_manifest_contract import AppServerNotificationName
from src.core.codex_contract.approval_contract import (
    CodexApprovalDisplaySummary,
    CodexApprovalKind,
    CodexApprovalRiskLevel,
)
from src.core.codex_contract.thread_contract import (
    CodexActiveTurnUpdateMode,
    CodexThreadIndexSnapshot,
    CodexThreadStatus,
    CodexThreadTitleSource,
)
from src.core.codex_contract.turn_runtime_contract import CodexTurnPhase, CodexTurnRuntime
from src.core.concurrency_contract.fenced_lease_contract import (
    FencedLease,
    FencedLeaseRequest,
)

HOST_ID = UUID("11111111-1111-1111-1111-111111111111")
BASE_TIME = datetime(2026, 8, 19, 1, 30, tzinfo=UTC)
OWNER_SUBJECT_ID = "turn-runtime-owner"
THREAD_ID = "turn-runtime-thread"
TURN_ID = "turn-runtime-turn"


@dataclass(slots=True)
class InMemoryUnitOfWork:
    """单元测试中记录事务边界但不引入数据库的最小 UoW。"""

    committed: bool = False
    rolled_back: bool = False

    def get_session(self) -> object:
        return self

    def commit(self) -> None:
        self.committed = True

    def flush(self) -> None:
        return None

    def rollback(self) -> None:
        self.rolled_back = True

    def dispose(self) -> None:
        return None


class InMemoryThreadRepository:
    """按真实仓储的 generation 条件模拟单线程持久化结果。"""

    def __init__(self, thread: CodexThreadIndexSnapshot) -> None:
        self.thread = thread

    def get_by_upstream_id_and_owner(
        self,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
    ) -> CodexThreadIndexSnapshot | None:
        if (
            host_id != self.thread.host_id
            or upstream_thread_id != self.thread.upstream_thread_id
            or owner_subject_id != self.thread.owner_subject_id
        ):
            return None
        return self.thread

    def apply_turn_runtime(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
        runtime: CodexTurnRuntime,
        status: CodexThreadStatus,
        active_turn_mode: CodexActiveTurnUpdateMode,
        synchronized_at: datetime,
        expected_lease_generation: int | None,
    ) -> CodexThreadIndexSnapshot | None:
        current = self.get_by_upstream_id_and_owner(
            host_id,
            upstream_thread_id,
            owner_subject_id,
        )
        if current is None:
            return None
        current_runtime = current.turn_runtime
        if expected_lease_generation is None:
            if current_runtime is not None and not (
                runtime.lease_generation > current_runtime.lease_generation
                or (
                    runtime.turn_id != current_runtime.turn_id
                    and current_runtime.phase
                    in {
                        CodexTurnPhase.COMPLETED,
                        CodexTurnPhase.FAILED,
                        CodexTurnPhase.INTERRUPTED,
                    }
                )
            ):
                return None
        elif (
            current_runtime is None
            or current_runtime.turn_id != runtime.turn_id
            or current_runtime.lease_generation != expected_lease_generation
        ):
            return None
        active_turn_id = current.active_turn_id
        if active_turn_mode is CodexActiveTurnUpdateMode.SET:
            active_turn_id = runtime.turn_id
        elif active_turn_mode is CodexActiveTurnUpdateMode.CLEAR:
            active_turn_id = None
        self.thread = current.model_copy(
            update={
                "turn_runtime": runtime,
                "status": status,
                "active_turn_id": active_turn_id,
                "recency_at": max(current.recency_at, runtime.last_activity_at),
                "updated_at": synchronized_at,
                "last_synced_at": synchronized_at,
            }
        )
        return self.thread

    def list_active_turn_runtimes(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
    ) -> tuple[CodexThreadIndexSnapshot, ...]:
        runtime = self.thread.turn_runtime
        if (
            runtime is None
            or host_id != self.thread.host_id
            or owner_subject_id != self.thread.owner_subject_id
            or runtime.phase
            not in {
                CodexTurnPhase.SUBMITTED,
                CodexTurnPhase.STARTING,
                CodexTurnPhase.RUNNING,
                CodexTurnPhase.AWAITING_APPROVAL,
            }
        ):
            return ()
        return (self.thread,)

    def list_stalled_turn_runtime_candidates(
        self,
        *,
        activity_before: datetime,
        lease_expired_before: datetime,
    ) -> tuple[CodexThreadIndexSnapshot, ...]:
        runtime = self.thread.turn_runtime
        if (
            runtime is None
            or runtime.phase
            not in {
                CodexTurnPhase.SUBMITTED,
                CodexTurnPhase.STARTING,
                CodexTurnPhase.RUNNING,
            }
            or runtime.last_activity_at > activity_before
            or runtime.lease_expires_at is None
            or runtime.lease_expires_at > lease_expired_before
        ):
            return ()
        return (self.thread,)


class InMemoryControlPort:
    """协调器测试只暴露线程运行态需要的控制面端口。"""

    def __init__(self, repository: InMemoryThreadRepository) -> None:
        self._repository = repository

    def create_unit_of_work(self) -> InMemoryUnitOfWork:
        return InMemoryUnitOfWork()

    def create_codex_thread_repository(self, _session: object) -> InMemoryThreadRepository:
        return self._repository


class InMemoryFencedLeaseStore:
    """使用可推进固定时钟的 lease store，精确覆盖过期竞态。"""

    def __init__(self, clock: list[datetime]) -> None:
        self._clock = clock
        self._leases: dict[str, FencedLease] = {}
        self._tokens: dict[str, int] = {}

    async def acquire(self, request: FencedLeaseRequest) -> FencedLease | None:
        if await self.read(request.resource_key) is not None:
            return None
        token = self._tokens.get(request.resource_key, 0) + 1
        self._tokens[request.resource_key] = token
        lease = FencedLease(
            resource_key=request.resource_key,
            owner=request.owner,
            fencing_token=token,
            expires_at=self._clock[0] + timedelta(seconds=request.ttl_seconds),
        )
        self._leases[request.resource_key] = lease
        return lease

    async def renew(self, lease: FencedLease, ttl_seconds: int) -> FencedLease | None:
        current = await self.read(lease.resource_key)
        if current != lease:
            return None
        renewed = lease.model_copy(
            update={"expires_at": self._clock[0] + timedelta(seconds=ttl_seconds)}
        )
        self._leases[lease.resource_key] = renewed
        return renewed

    async def release(self, lease: FencedLease) -> bool:
        current = await self.read(lease.resource_key)
        if current != lease:
            return False
        self._leases.pop(lease.resource_key, None)
        return True

    async def read(self, resource_key: str) -> FencedLease | None:
        lease = self._leases.get(resource_key)
        if lease is not None and lease.expires_at <= self._clock[0]:
            self._leases.pop(resource_key, None)
            return None
        return lease


def _thread() -> CodexThreadIndexSnapshot:
    """构造不含任何会话正文的线程索引。"""

    return CodexThreadIndexSnapshot(
        thread_index_id=uuid4(),
        host_id=HOST_ID,
        workspace_id=uuid4(),
        owner_subject_id=OWNER_SUBJECT_ID,
        upstream_thread_id=THREAD_ID,
        display_name="运行态测试会话",
        title_source=CodexThreadTitleSource.NEW_CONVERSATION,
        model=None,
        model_provider=None,
        reasoning_effort=None,
        status=CodexThreadStatus.IDLE,
        active_turn_id=None,
        archived=False,
        is_pinned=False,
        source_kind="remote",
        created_at=BASE_TIME - timedelta(minutes=1),
        recency_at=BASE_TIME - timedelta(minutes=1),
        updated_at=BASE_TIME - timedelta(minutes=1),
        last_synced_at=BASE_TIME - timedelta(minutes=1),
    )


def _principal(credential_id: str) -> AgentDevicePrincipal:
    """构造已绑定测试 host 的 Agent 主体。"""

    return AgentDevicePrincipal(
        credential_id=credential_id,
        host_id=str(HOST_ID),
        owner_subject_id=OWNER_SUBJECT_ID,
    )


def _event(
    *,
    occurred_at: datetime,
    instance_id: str,
    status: str,
) -> CodexAgentRealtimeEvent:
    """构造一个官方 turn 生命周期事件。"""

    method: Literal[
        AppServerNotificationName.TURN_STARTED,
        AppServerNotificationName.TURN_COMPLETED,
    ]
    if status == "inProgress":
        method = AppServerNotificationName.TURN_STARTED
    else:
        method = AppServerNotificationName.TURN_COMPLETED
    return CodexAgentRealtimeEvent(
        host_id=HOST_ID,
        app_server_instance_id=instance_id,
        occurred_at=occurred_at,
        method=method.value,
        params={},
        detail=AgentTurnChangedEventDetail(
            method=method,
            thread_id=THREAD_ID,
            turn_id=TURN_ID,
            status=status,
        ),
    )


def _coordinator(
    clock: list[datetime],
) -> tuple[CodexTurnRuntimeCoordinator, InMemoryThreadRepository]:
    """构造使用同一固定时钟的协调器和可观察仓储。"""

    repository = InMemoryThreadRepository(_thread())
    coordinator = CodexTurnRuntimeCoordinator(
        control_port=cast(CodexControlPort, InMemoryControlPort(repository)),
        lease_store=InMemoryFencedLeaseStore(clock),
        lease_ttl_seconds=60,
        stalled_after_seconds=90,
        clock=lambda: clock[0],
    )
    return coordinator, repository


def test_thread_recency_uses_authoritative_activity() -> None:
    """旧 Agent 快照不得清空实时链路已经确认的运行态或活动时间。"""

    runtime_activity_at = BASE_TIME + timedelta(minutes=1)
    existing = _thread().model_copy(
        update={
            "status": CodexThreadStatus.ACTIVE,
            "active_turn_id": TURN_ID,
            "turn_runtime": CodexTurnRuntime(
                turn_id=TURN_ID,
                thread_id=THREAD_ID,
                phase=CodexTurnPhase.RUNNING,
                last_activity_at=runtime_activity_at,
                stalled_reason=None,
                lease_generation=7,
                lease_expires_at=runtime_activity_at + timedelta(seconds=60),
            ),
            "recency_at": BASE_TIME,
        }
    )

    updated = SyncCodexAgentStateUsecase(
        control_port=cast(CodexControlPort, object()),
        max_workspaces_per_host=8,
    )._build_thread_snapshot(
        raw_thread=AgentConversationSnapshotDetail(
            thread_id=THREAD_ID,
            workspace_key="workspace-key",
            display_name="Agent 过期快照",
            title_source=CodexThreadTitleSource.APP_SERVER,
            model_id=None,
            model_provider=None,
            status="idle",
            active_turn_id=None,
            archived=False,
            source_kind="remote",
            created_at=BASE_TIME,
            recency_at=BASE_TIME,
        ),
        host_id=HOST_ID,
        workspace_id=existing.workspace_id,
        owner_subject_id=OWNER_SUBJECT_ID,
        captured_at=runtime_activity_at + timedelta(minutes=1),
        existing=existing,
    )

    assert updated.turn_runtime == existing.turn_runtime
    assert updated.status is CodexThreadStatus.ACTIVE
    assert updated.active_turn_id == TURN_ID
    assert updated.recency_at == runtime_activity_at


@pytest.mark.parametrize(
    ("existing_status", "active_turn_id"),
    [
        (CodexThreadStatus.IDLE, None),
        (CodexThreadStatus.ACTIVE, TURN_ID),
    ],
)
def test_agent_not_loaded_snapshot_should_preserve_existing_thread_status(
    existing_status: CodexThreadStatus,
    active_turn_id: str | None,
) -> None:
    """索引快照未加载状态时不得把已确认的活动会话标记为中断。"""

    existing = _thread().model_copy(
        update={"status": existing_status, "active_turn_id": active_turn_id}
    )

    updated = SyncCodexAgentStateUsecase(
        control_port=cast(CodexControlPort, object()),
        max_workspaces_per_host=8,
    )._build_thread_snapshot(
        raw_thread=AgentConversationSnapshotDetail(
            thread_id=THREAD_ID,
            workspace_key="workspace-key",
            display_name="未加载快照",
            title_source=CodexThreadTitleSource.APP_SERVER,
            model_id=None,
            model_provider=None,
            status="notLoaded",
            active_turn_id=None,
            archived=False,
            source_kind="remote",
            created_at=BASE_TIME,
            recency_at=BASE_TIME,
        ),
        host_id=HOST_ID,
        workspace_id=existing.workspace_id,
        owner_subject_id=OWNER_SUBJECT_ID,
        captured_at=BASE_TIME + timedelta(minutes=1),
        existing=existing,
    )

    assert updated.status is existing_status
    assert updated.active_turn_id == active_turn_id


def test_agent_thread_snapshot_should_not_reuse_terminal_turn_lease_for_new_turn() -> None:
    """快照发现新 turn 时，旧终态 lease generation 必须被丢弃。"""

    existing = _thread().model_copy(
        update={
            "turn_runtime": CodexTurnRuntime(
                turn_id=TURN_ID,
                thread_id=THREAD_ID,
                phase=CodexTurnPhase.COMPLETED,
                last_activity_at=BASE_TIME,
                stalled_reason=None,
                lease_generation=7,
                lease_expires_at=None,
            )
        }
    )

    updated = SyncCodexAgentStateUsecase(
        control_port=cast(CodexControlPort, object()),
        max_workspaces_per_host=8,
    )._build_thread_snapshot(
        raw_thread=AgentConversationSnapshotDetail(
            thread_id=THREAD_ID,
            workspace_key="workspace-key",
            display_name="新 turn 快照",
            title_source=CodexThreadTitleSource.APP_SERVER,
            model_id=None,
            model_provider=None,
            status="active",
            active_turn_id="new-turn",
            archived=False,
            source_kind="remote",
            created_at=BASE_TIME,
            recency_at=BASE_TIME + timedelta(minutes=1),
        ),
        host_id=HOST_ID,
        workspace_id=existing.workspace_id,
        owner_subject_id=OWNER_SUBJECT_ID,
        captured_at=BASE_TIME + timedelta(minutes=2),
        existing=existing,
    )

    assert updated.turn_runtime is None
    assert updated.status is CodexThreadStatus.ACTIVE
    assert updated.active_turn_id == "new-turn"


class TestCodexTurnRuntimeCoordinatorUnit:
    """验证 runtime 只接受当前 generation 的 Agent 事件。"""

    @pytest.mark.asyncio
    async def test_agent_heartbeat_updates_activity_for_same_turn(self) -> None:
        """同一 turn 的心跳应推进服务端 activity 和 lease 有效期。"""

        clock = [BASE_TIME]
        coordinator, repository = _coordinator(clock)
        principal = _principal("agent-one")
        started = await coordinator.observe_agent_event(
            _event(occurred_at=clock[0], instance_id="instance-one", status="inProgress"),
            principal,
        )
        assert started.accepted is True

        clock[0] += timedelta(seconds=15)
        updated = await coordinator.renew_heartbeat_leases(
            CodexAgentHeartbeat(
                host_id=HOST_ID,
                connection_epoch=1,
                app_server_instance_id="instance-one",
                sent_at=clock[0],
            ),
            principal,
        )

        assert len(updated) == 1
        assert repository.thread.turn_runtime is not None
        assert repository.thread.turn_runtime.last_activity_at == clock[0]
        assert repository.thread.turn_runtime.lease_expires_at == clock[0] + timedelta(seconds=60)
        assert repository.thread.recency_at == clock[0]

    @pytest.mark.asyncio
    async def test_watchdog_expired_lease_marks_only_matching_generation_stalled(self) -> None:
        """过期代次只会将自身对应的长期无活动 turn 标记为 stalled。"""

        clock = [BASE_TIME]
        coordinator, repository = _coordinator(clock)
        principal = _principal("agent-one")
        await coordinator.observe_agent_event(
            _event(occurred_at=clock[0], instance_id="instance-one", status="inProgress"),
            principal,
        )

        clock[0] += timedelta(seconds=91)
        updated = await coordinator.mark_expired_turns_stalled()

        assert len(updated) == 1
        assert repository.thread.turn_runtime is not None
        assert repository.thread.turn_runtime.phase is CodexTurnPhase.STALLED
        assert repository.thread.turn_runtime.stalled_reason == "lease_expired_no_activity"
        assert repository.thread.active_turn_id == TURN_ID

    @pytest.mark.asyncio
    async def test_stale_agent_cannot_overwrite_new_lease(self) -> None:
        """旧 Agent 延迟终态到达时不得覆盖新 owner 已认领的 generation。"""

        clock = [BASE_TIME]
        coordinator, repository = _coordinator(clock)
        first_principal = _principal("agent-one")
        second_principal = _principal("agent-two")
        await coordinator.observe_agent_event(
            _event(occurred_at=clock[0], instance_id="instance-one", status="inProgress"),
            first_principal,
        )

        clock[0] += timedelta(seconds=61)
        second_start = await coordinator.observe_agent_event(
            _event(occurred_at=clock[0], instance_id="instance-two", status="inProgress"),
            second_principal,
        )
        delayed_completion = await coordinator.observe_agent_event(
            _event(
                occurred_at=clock[0] + timedelta(seconds=1),
                instance_id="instance-one",
                status="completed",
            ),
            first_principal,
        )

        assert second_start.accepted is True
        assert delayed_completion.accepted is False
        assert repository.thread.turn_runtime is not None
        assert repository.thread.turn_runtime.phase is CodexTurnPhase.RUNNING
        assert repository.thread.turn_runtime.lease_generation == 2

    @pytest.mark.asyncio
    async def test_approval_wait_is_not_marked_stalled(self) -> None:
        """等待官方审批时即使 lease 到期也不得被 watchdog 标记 stalled。"""

        clock = [BASE_TIME]
        coordinator, repository = _coordinator(clock)
        principal = _principal("agent-one")
        await coordinator.observe_agent_event(
            _event(occurred_at=clock[0], instance_id="instance-one", status="inProgress"),
            principal,
        )
        clock[0] += timedelta(seconds=1)
        approval_thread = await coordinator.observe_approval_opened(
            CodexAgentApprovalOpened(
                approval_id=uuid4(),
                host_id=HOST_ID,
                app_server_instance_id="instance-one",
                approval_kind=CodexApprovalKind.COMMAND,
                thread_id=THREAD_ID,
                turn_id=TURN_ID,
                item_id="approval-item",
                risk_level=CodexApprovalRiskLevel.NORMAL,
                payload_digest="a" * 64,
                display_summary=CodexApprovalDisplaySummary(
                    title="命令审批",
                    reason="继续执行",
                    risk_level=CodexApprovalRiskLevel.NORMAL,
                ),
                expires_at=clock[0] + timedelta(minutes=5),
            ),
            principal,
        )

        clock[0] += timedelta(seconds=100)
        stalled = await coordinator.mark_expired_turns_stalled()

        assert approval_thread is not None
        assert stalled == ()
        assert repository.thread.turn_runtime is not None
        assert repository.thread.turn_runtime.phase is CodexTurnPhase.AWAITING_APPROVAL

    @pytest.mark.asyncio
    async def test_interrupt_is_idempotent(self) -> None:
        """同一 Agent 的重复中断事件应收敛为同一已中断终态。"""

        clock = [BASE_TIME]
        coordinator, repository = _coordinator(clock)
        principal = _principal("agent-one")
        await coordinator.observe_agent_event(
            _event(occurred_at=clock[0], instance_id="instance-one", status="inProgress"),
            principal,
        )

        clock[0] += timedelta(seconds=1)
        interrupted = _event(
            occurred_at=clock[0],
            instance_id="instance-one",
            status="interrupted",
        )
        first = await coordinator.observe_agent_event(interrupted, principal)
        second = await coordinator.observe_agent_event(interrupted, principal)

        assert first.accepted is True
        assert second.accepted is True
        assert repository.thread.turn_runtime is not None
        assert repository.thread.turn_runtime.phase is CodexTurnPhase.INTERRUPTED
        assert repository.thread.active_turn_id is None
