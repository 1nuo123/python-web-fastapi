"""更新 Codex 工作区控制策略。"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.workspace_contract import (
    CodexWorkspaceSnapshot,
    CodexWorkspaceUpdateRequest,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode


class UpdateCodexWorkspaceUsecase:
    """按工作区所有权更新显示信息和可选隔离策略。"""

    def __init__(self, control_port: CodexControlPort) -> None:
        self._control_port = control_port

    def execute(
        self,
        *,
        host_id: UUID,
        workspace_id: UUID,
        owner_subject_id: str,
        request: CodexWorkspaceUpdateRequest,
    ) -> CodexWorkspaceSnapshot:
        """更新工作区；越权或不存在统一返回 404。"""

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = self._control_port.create_codex_workspace_repository(session)
            current = repository.get_by_id_and_owner(workspace_id, owner_subject_id)
            if current is None or current.host_id != host_id:
                raise HttpFaultException(
                    status_code=HTTPStatus.NOT_FOUND,
                    error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
                    message="Codex 工作区不存在。",
                )
            updated = current.model_copy(
                update={
                    "display_name": (
                        request.display_name
                        if request.display_name is not None
                        else current.display_name
                    ),
                    "enabled": (
                        request.enabled if request.enabled is not None else current.enabled
                    ),
                    "worktree_policy": (
                        request.worktree_policy.to_policy(
                            managed_root=current.worktree_policy.managed_root
                        )
                        if request.worktree_policy is not None
                        else current.worktree_policy
                    ),
                    "updated_at": datetime.now(UTC),
                    "version": current.version + 1,
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
