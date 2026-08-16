"""按用户主体撤销 Codex Agent 访问单元测试。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from src.application.codex.revoke_subject_agent_access_usecase import (
    RevokeCodexSubjectAgentAccessUsecase,
)
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession, UnitOfWork

TEST_SUBJECT_ID = "subject-revoked"
EXPECTED_ACTIVE_HOST_COUNT = 2


class StubPersistenceSession(PersistenceSession):
    """撤销用例测试名义会话。"""


class TrackingUnitOfWork(UnitOfWork):
    """记录事务资源释放行为。"""

    def __init__(self) -> None:
        self.session = StubPersistenceSession()
        self.committed = False
        self.rolled_back = False
        self.disposed = False

    def get_session(self) -> PersistenceSession:
        return self.session

    def commit(self) -> None:
        self.committed = True

    def flush(self) -> None:
        return None

    def rollback(self) -> None:
        self.rolled_back = True

    def dispose(self) -> None:
        self.disposed = True


@dataclass(frozen=True, slots=True)
class StubHost:
    """撤销用例所需的最小主机快照。"""

    host_id: UUID
    revoked_at: datetime | None


class StubHostRepository:
    """返回预设主体主机集合。"""

    def __init__(self, hosts: list[StubHost], error: BaseException | None = None) -> None:
        self._hosts = hosts
        self._error = error
        self.owner_subject_ids: list[str] = []

    def list_by_owner(self, owner_subject_id: str) -> list[StubHost]:
        self.owner_subject_ids.append(owner_subject_id)
        if self._error is not None:
            raise self._error
        return list(self._hosts)


class StubCodexControlPort:
    """只实现撤销用例所需的控制面端口。"""

    def __init__(self, repository: StubHostRepository) -> None:
        self.unit_of_work = TrackingUnitOfWork()
        self.repository = repository

    def create_unit_of_work(self) -> UnitOfWork:
        return self.unit_of_work

    def create_codex_host_repository(
        self,
        session: PersistenceSession,
    ) -> StubHostRepository:
        assert session is self.unit_of_work.session
        return self.repository


class ConcurrentRevocationSignal:
    """记录并发撤销数量并阻塞到全部活动主机进入。"""

    def __init__(self, expected_count: int) -> None:
        self._expected_count = expected_count
        self._all_started = asyncio.Event()
        self._active_count = 0
        self.peak_active_count = 0
        self.host_ids: list[UUID] = []

    async def revoke(self, host_id: UUID) -> int:
        self.host_ids.append(host_id)
        self._active_count += 1
        self.peak_active_count = max(self.peak_active_count, self._active_count)
        if self._active_count == self._expected_count:
            self._all_started.set()
        await asyncio.wait_for(self._all_started.wait(), timeout=1)
        self._active_count -= 1
        return 1


class TestRevokeCodexSubjectAgentAccessUsecase:
    """验证主体撤销的成功、过滤与异常资源回收。"""

    @pytest.mark.asyncio
    async def test_execute_should_revoke_active_hosts_concurrently_and_dispose(self) -> None:
        active_host_ids = (uuid4(), uuid4())
        repository = StubHostRepository(
            [
                StubHost(host_id=active_host_ids[0], revoked_at=None),
                StubHost(host_id=uuid4(), revoked_at=datetime.max),
                StubHost(host_id=active_host_ids[1], revoked_at=None),
            ]
        )
        control_port = StubCodexControlPort(repository)
        revocation_signal = ConcurrentRevocationSignal(EXPECTED_ACTIVE_HOST_COUNT)

        result = await RevokeCodexSubjectAgentAccessUsecase(
            control_port=control_port,
            revocation_signal=revocation_signal,
        ).execute(subject_id=TEST_SUBJECT_ID)

        assert result == active_host_ids
        assert set(revocation_signal.host_ids) == set(active_host_ids)
        assert revocation_signal.peak_active_count == EXPECTED_ACTIVE_HOST_COUNT
        assert repository.owner_subject_ids == [TEST_SUBJECT_ID]
        assert control_port.unit_of_work.committed is True
        assert control_port.unit_of_work.rolled_back is False
        assert control_port.unit_of_work.disposed is True

    @pytest.mark.asyncio
    async def test_execute_when_repository_fails_should_rollback_and_dispose(self) -> None:
        repository = StubHostRepository([], error=RuntimeError("主机查询失败。"))
        control_port = StubCodexControlPort(repository)
        revocation_signal = ConcurrentRevocationSignal(EXPECTED_ACTIVE_HOST_COUNT)

        with pytest.raises(RuntimeError, match="主机查询失败"):
            await RevokeCodexSubjectAgentAccessUsecase(
                control_port=control_port,
                revocation_signal=revocation_signal,
            ).execute(subject_id=TEST_SUBJECT_ID)

        assert revocation_signal.host_ids == []
        assert control_port.unit_of_work.committed is False
        assert control_port.unit_of_work.rolled_back is True
        assert control_port.unit_of_work.disposed is True
