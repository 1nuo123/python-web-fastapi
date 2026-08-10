"""列出当前主体 Codex 工作区用例。"""

from http import HTTPStatus
from uuid import UUID

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.workspace_contract import CodexWorkspaceCollection
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode


class ListCodexWorkspacesUsecase:
    """先验证主机所有权，再返回该所有者的工作区。"""

    def __init__(self, control_port: CodexControlPort) -> None:
        self._control_port = control_port

    def execute(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
    ) -> CodexWorkspaceCollection:
        """列出工作区；不存在与越权统一返回 404。"""

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
            workspace_repository = self._control_port.create_codex_workspace_repository(session)
            return CodexWorkspaceCollection(
                items=workspace_repository.list_by_host_and_owner(host_id, owner_subject_id)
            )
        finally:
            unit_of_work.dispose()
