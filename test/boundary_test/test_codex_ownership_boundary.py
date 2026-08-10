"""Codex 所有权应用边界测试。"""

from uuid import UUID, uuid4

import pytest

from src.application.codex.list_workspaces_usecase import ListCodexWorkspacesUsecase
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession, UnitOfWork
from src.domain.codex.codex_error_code import CodexErrorCode


class StubPersistenceSession(PersistenceSession):
    """所有权边界测试名义会话。"""


class StubUnitOfWork(UnitOfWork):
    def __init__(self) -> None:
        self.session = StubPersistenceSession()
        self.disposed = False

    def get_session(self) -> PersistenceSession:
        return self.session

    def commit(self) -> None:
        return None

    def flush(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def dispose(self) -> None:
        self.disposed = True


class MissingHostRepository:
    def get_by_id_and_owner(self, host_id: UUID, owner_subject_id: str) -> None:
        _ = host_id, owner_subject_id
        return None


class StubCodexControlPort:
    def __init__(self) -> None:
        self.unit_of_work = StubUnitOfWork()

    def create_unit_of_work(self) -> UnitOfWork:
        return self.unit_of_work

    def create_codex_host_repository(
        self,
        session: PersistenceSession,
    ) -> MissingHostRepository:
        _ = session
        return MissingHostRepository()


def test_list_workspaces_when_host_not_owned_should_return_not_found_and_dispose() -> None:
    control_port = StubCodexControlPort()

    with pytest.raises(HttpFaultException) as fault:
        ListCodexWorkspacesUsecase(control_port=control_port).execute(
            host_id=uuid4(),
            owner_subject_id="current-owner",
        )

    assert fault.value.status_code == 404
    assert fault.value.error_code == CodexErrorCode.RESOURCE_NOT_FOUND
    assert control_port.unit_of_work.disposed is True
