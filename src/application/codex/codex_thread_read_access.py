"""历史与正文读取共用的当前所有权校验。"""

from dataclasses import dataclass
from http import HTTPStatus
from uuid import UUID
from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.thread_contract import CodexThreadIndexSnapshot
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode


@dataclass(frozen=True, slots=True)
class OwnedCodexThreadContext:
    """已通过所有权校验的线程读取上下文。"""

    thread: CodexThreadIndexSnapshot
    workspace_key: str


def read_owned_codex_thread(
    control_port: CodexControlPort,
    host_id: UUID,
    upstream_thread_id: str,
    owner_subject_id: str,
) -> OwnedCodexThreadContext:
    unit_of_work = control_port.create_unit_of_work()
    try:
        session = unit_of_work.get_session()
        host = control_port.create_codex_host_repository(session).get_by_id_and_owner(
            host_id, owner_subject_id
        )
        if host is None or host.revoked_at is not None:
            raise HttpFaultException(
                status_code=404,
                error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
                message="Codex资源不存在。",
            )
        thread = control_port.create_codex_thread_repository(session).get_by_upstream_id_and_owner(
            host_id,
            upstream_thread_id,
            owner_subject_id,
        )
        if thread is None:
            raise HttpFaultException(
                status_code=HTTPStatus.NOT_FOUND,
                error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
                message="Codex资源不存在。",
            )
        workspace = control_port.create_codex_workspace_repository(session).get_by_id_and_owner(
            thread.workspace_id, owner_subject_id
        )
        if workspace is None or not workspace.enabled or workspace.host_id != host_id:
            raise HttpFaultException(
                status_code=HTTPStatus.NOT_FOUND,
                error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
                message="Codex资源不存在。",
            )
        return OwnedCodexThreadContext(
            thread=thread,
            workspace_key=workspace.agent_workspace_key,
        )
    finally:
        unit_of_work.dispose()
