"""查询 Codex 线程索引用例。"""

from http import HTTPStatus
from uuid import UUID

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.thread_contract import (
    CodexConversationListQuery,
    CodexConversationPage,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode


class QueryCodexThreadsUsecase:
    """查询指定所有者主机下的线程索引。"""

    def __init__(self, control_port: CodexControlPort) -> None:
        self._control_port = control_port

    def execute(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
        query: CodexConversationListQuery,
    ) -> CodexConversationPage:
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
            try:
                return repository.list_page_by_host_and_owner(
                    host_id,
                    owner_subject_id,
                    query,
                )
            except ValueError as exc:
                raise HttpFaultException(
                    status_code=HTTPStatus.BAD_REQUEST,
                    error_code=CodexErrorCode.STATE_CONFLICT,
                    message="Codex会话查询条件或游标无效。",
                ) from exc
        finally:
            unit_of_work.dispose()
