"""更新 Codex 工作区控制策略。"""

from __future__ import annotations

from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from src.application.ports.codex_control_port import CodexControlPort
from src.core.codex_contract.host_contract import CodexHostCapabilities
from src.core.codex_contract.workspace_contract import (
    CodexWorkspaceExecutionPreferencesResult,
    CodexWorkspaceExecutionPreferencesUpdate,
    CodexWorkspaceSnapshot,
    CodexWorkspaceUpdateRequest,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.persistence_contract.unit_of_work_contract import UnitOfWork
from src.domain.codex.codex_error_code import CodexErrorCode
from src.domain.codex.workspace_execution_preference_policy import (
    revalidate_codex_workspace_execution_preferences,
)


class UpdateCodexWorkspaceUsecase:
    """按工作区所有权更新显示信息、隔离策略和执行偏好。"""

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
                    "is_pinned": (
                        request.is_pinned if request.is_pinned is not None else current.is_pinned
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

    def read_execution_preferences(
        self,
        *,
        host_id: UUID,
        workspace_id: UUID,
        owner_subject_id: str,
        subject_scopes: frozenset[str],
    ) -> CodexWorkspaceExecutionPreferencesResult:
        """读取并重校验执行偏好，不在读取路径写回持久化状态。

        主机 capability 或用户授权可能在保存后发生变化，因此读接口必须给出当前
        有效值和调整字段。此处保持查询无副作用，避免仅打开设置页就增加版本号。
        """

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            current, capabilities = self._read_owned_workspace_and_capabilities(
                unit_of_work=unit_of_work,
                host_id=host_id,
                workspace_id=workspace_id,
                owner_subject_id=owner_subject_id,
            )
            effective_preferences, adjusted_fields = (
                revalidate_codex_workspace_execution_preferences(
                    current.execution_preferences,
                    capabilities=capabilities,
                    subject_scopes=subject_scopes,
                )
            )
            return CodexWorkspaceExecutionPreferencesResult(
                workspace_id=current.workspace_id,
                effective_preferences=effective_preferences,
                adjusted_fields=adjusted_fields,
            )
        finally:
            unit_of_work.dispose()

    def update_execution_preferences(
        self,
        *,
        host_id: UUID,
        workspace_id: UUID,
        owner_subject_id: str,
        subject_scopes: frozenset[str],
        request: CodexWorkspaceExecutionPreferencesUpdate,
    ) -> CodexWorkspaceExecutionPreferencesResult:
        """按当前主机 capability 和用户 scope 收敛后持久化执行偏好。

        浏览器不能指定 capability 版本，也不能绕过当前 scope 保存更宽松的沙箱或
        审批策略。工作区更新与版本递增由同一个 UoW 原子提交。
        """

        unit_of_work = self._control_port.create_unit_of_work()
        try:
            current, capabilities = self._read_owned_workspace_and_capabilities(
                unit_of_work=unit_of_work,
                host_id=host_id,
                workspace_id=workspace_id,
                owner_subject_id=owner_subject_id,
            )
            effective_preferences, adjusted_fields = (
                revalidate_codex_workspace_execution_preferences(
                    request,
                    capabilities=capabilities,
                    subject_scopes=subject_scopes,
                )
            )
            updated = current.model_copy(
                update={
                    "execution_preferences": effective_preferences,
                    "updated_at": datetime.now(UTC),
                    "version": current.version + 1,
                }
            )
            repository = self._control_port.create_codex_workspace_repository(
                unit_of_work.get_session()
            )
            repository.save(updated)
            unit_of_work.commit()
            return CodexWorkspaceExecutionPreferencesResult(
                workspace_id=updated.workspace_id,
                effective_preferences=effective_preferences,
                adjusted_fields=adjusted_fields,
            )
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _read_owned_workspace_and_capabilities(
        self,
        *,
        unit_of_work: UnitOfWork,
        host_id: UUID,
        workspace_id: UUID,
        owner_subject_id: str,
    ) -> tuple[CodexWorkspaceSnapshot, CodexHostCapabilities]:
        """读取同一所有者下的工作区和主机能力，统一隐藏越权对象。

        此私有步骤同时检查主机与工作区，避免仅凭工作区 UUID 将别的主机的
        capability 用于重校验。返回值在下一次小范围重构时可替换为应用层 DTO。
        """

        session = unit_of_work.get_session()
        host_repository = self._control_port.create_codex_host_repository(session)
        host = host_repository.get_by_id_and_owner(host_id, owner_subject_id)
        if host is None:
            raise self._build_not_found_fault("Codex 主机不存在。")
        workspace_repository = self._control_port.create_codex_workspace_repository(session)
        current = workspace_repository.get_by_id_and_owner(workspace_id, owner_subject_id)
        if current is None or current.host_id != host_id:
            raise self._build_not_found_fault("Codex 工作区不存在。")
        return current, host.capabilities

    @staticmethod
    def _build_not_found_fault(message: str) -> HttpFaultException:
        """构造不泄露跨所有者资源存在性的统一 404 错误。"""

        return HttpFaultException(
            status_code=HTTPStatus.NOT_FOUND,
            error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
            message=message,
        )
