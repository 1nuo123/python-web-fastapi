"""更新 Codex 会话控制面偏好。"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.thread_contract import (
    CodexConversationPinRequest,
    CodexThreadIndexSnapshot,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode


class UpdateCodexThreadPreferenceUsecase:
    """在既有 UoW 边界内更新会话置顶偏好。

    :param control_port: Codex 控制面持久化端口。
    """

    def __init__(self, control_port: CodexControlPort) -> None:
        self._control_port = control_port

    def execute(
        self,
        *,
        host_id: UUID,
        upstream_thread_id: str,
        owner_subject_id: str,
        request: CodexConversationPinRequest,
    ) -> CodexThreadIndexSnapshot:
        """更新会话置顶偏好。

        :param host_id: 会话所属主机标识。
        :param upstream_thread_id: App Server 会话标识。
        :param owner_subject_id: 当前认证主体标识。
        :param request: 置顶偏好请求。
        :return: 更新后的会话索引。
        :raises HttpFaultException: 会话不存在或不属于当前主体时抛出。
        """

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_thread_repository(
                unit_of_work.get_session()
            )
            current = repository.get_by_upstream_id_and_owner(
                host_id,
                upstream_thread_id,
                owner_subject_id,
            )
            if current is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.NOT_FOUND,
                    error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
                    message="Codex资源不存在。",
                )
            updated = current.model_copy(
                update={
                    "is_pinned": request.is_pinned,
                    "updated_at": datetime.now(UTC),
                }
            )
            repository.save(updated)
            unit_of_work.commit()
            return updated
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
