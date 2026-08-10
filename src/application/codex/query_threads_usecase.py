"""查询 Codex 线程索引用例。"""

from http import HTTPStatus
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.thread_contract import CodexThreadIndexSnapshot
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode


class CodexThreadIndexCollection(BaseModel):
    """线程索引集合响应。"""

    model_config = ConfigDict(extra="forbid")
    items: list[CodexThreadIndexSnapshot]


class QueryCodexThreadsUsecase:
    """查询指定所有者主机下的线程索引。"""

    def __init__(self, control_port: CodexControlPort) -> None:
        self._control_port = control_port

    def execute(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
    ) -> CodexThreadIndexCollection:
        """查询线程索引；主机越权与不存在统一为 404。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            host_repository = self._control_port.create_codex_host_repository(session)
            if host_repository.get_by_id_and_owner(host_id, owner_subject_id) is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.NOT_FOUND,
                    error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
                    message="Codex 主机不存在。",
                )
            repository = self._control_port.create_codex_thread_repository(session)
            return CodexThreadIndexCollection(
                items=repository.list_by_host_and_owner(host_id, owner_subject_id)
            )
        finally:
            unit_of_work.dispose()
