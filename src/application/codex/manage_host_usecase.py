"""Codex 主机重命名与撤销用例。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from http import HTTPStatus
from uuid import UUID

from src.application.ports.codex_agent_revocation_signal_port import (
    CodexAgentRevocationSignalPort,
)
from src.application.ports.codex_control_port import CodexControlPort
from src.application.ports.step_up_grant_port import StepUpGrantPort
from src.core.auth_contract.step_up_grant_contract import StepUpGrantPurpose
from src.core.codex_contract.host_contract import CodexHostSnapshot
from src.core.codex_contract.approval_contract import CodexApprovalState
from src.core.codex_contract.command_outbox_contract import CodexCommandOutboxState
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.codex.codex_error_code import CodexErrorCode


class RenameCodexHostUsecase:
    """使用版本前置条件更新主机显示名。"""

    def __init__(self, *, control_port: CodexControlPort) -> None:
        self._control_port = control_port

    async def execute(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
        display_name: str,
        expected_version: int,
    ) -> CodexHostSnapshot:
        return await asyncio.to_thread(
            self._rename,
            host_id=host_id,
            owner_subject_id=owner_subject_id,
            display_name=display_name,
            expected_version=expected_version,
        )

    def _rename(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
        display_name: str,
        expected_version: int,
    ) -> CodexHostSnapshot:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            repository = self._control_port.create_codex_host_repository(unit_of_work.get_session())
            host = repository.get_by_id_and_owner(host_id, owner_subject_id)
            if host is None:
                raise self._not_found()
            now = datetime.now(UTC)
            renamed = repository.rename_if_version(
                host_id=host_id,
                owner_subject_id=owner_subject_id,
                expected_version=expected_version,
                display_name=display_name,
                updated_at=now,
            )
            if renamed is None:
                raise self._version_conflict()
            unit_of_work.commit()
            return renamed
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _not_found(self) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.NOT_FOUND,
            error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
            message="Codex主机不存在。",
        )

    def _version_conflict(self) -> HttpFaultException:
        return HttpFaultException(
            status_code=HTTPStatus.PRECONDITION_FAILED,
            error_code=CodexErrorCode.VERSION_CONFLICT,
            message="Codex主机版本已经变化。",
        )


class RevokeCodexHostUsecase:
    """同事务撤销主机和公钥，再提升跨实例撤销代次。"""

    def __init__(
        self,
        *,
        control_port: CodexControlPort,
        step_up_port: StepUpGrantPort,
        revocation_signal: CodexAgentRevocationSignalPort,
    ) -> None:
        self._control_port = control_port
        self._step_up_port = step_up_port
        self._revocation_signal = revocation_signal

    async def execute(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
        expected_version: int,
        step_up_token: str,
    ) -> CodexHostSnapshot:
        verified = await self._step_up_port.consume(
            token=step_up_token,
            subject_id=owner_subject_id,
            purpose=StepUpGrantPurpose.CODEX_HOST_REVOKE,
        )
        if not verified:
            raise HttpFaultException(
                status_code=HTTPStatus.FORBIDDEN,
                error_code=CodexErrorCode.STATE_CONFLICT,
                message="撤销电脑需要有效的增强授权。",
            )
        revoked = await asyncio.to_thread(
            self._revoke,
            host_id=host_id,
            owner_subject_id=owner_subject_id,
            expected_version=expected_version,
        )
        await self._revocation_signal.revoke(host_id)
        return revoked

    def _revoke(
        self,
        *,
        host_id: UUID,
        owner_subject_id: str,
        expected_version: int,
    ) -> CodexHostSnapshot:
        unit_of_work = self._control_port.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            host_repository = self._control_port.create_codex_host_repository(session)
            host = host_repository.get_by_id_and_owner(host_id, owner_subject_id)
            if host is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.NOT_FOUND,
                    error_code=CodexErrorCode.RESOURCE_NOT_FOUND,
                    message="Codex主机不存在。",
                )
            now = datetime.now(UTC)
            revoked = host_repository.revoke_if_version(
                host_id=host_id,
                owner_subject_id=owner_subject_id,
                expected_version=expected_version,
                revoked_at=now,
            )
            if revoked is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.PRECONDITION_FAILED,
                    error_code=CodexErrorCode.VERSION_CONFLICT,
                    message="Codex主机版本已经变化。",
                )
            self._control_port.create_codex_device_key_repository(
                session
            ).revoke_all_by_host_and_owner(
                host_id=host_id,
                owner_subject_id=owner_subject_id,
                revoked_at=now,
            )
            approvals = self._control_port.create_codex_approval_repository(session)
            for approval in approvals.list_by_owner(owner_subject_id):
                if approval.host_id == host_id and approval.state in {
                    CodexApprovalState.PENDING,
                    CodexApprovalState.CLAIMED,
                    CodexApprovalState.DELIVERY_FAILED,
                }:
                    approvals.save(
                        approval.model_copy(
                            update={"state": CodexApprovalState.CANCELLED, "updated_at": now}
                        )
                    )
            operations = self._control_port.create_codex_operation_repository(session)
            outbox = self._control_port.create_codex_command_outbox_repository(session)
            for operation in operations.list_pending_by_host(
                host_id, ["pending", "dispatched", "acknowledged", "timed_out", "unknown"]
            ):
                operations.save(
                    operation.model_copy(
                        update={
                            "status": "cancelled",
                            "error_code": "host_revoked",
                            "completed_at": now,
                            "updated_at": now,
                        }
                    )
                )
                command = outbox.get_by_command_id(operation.command_id)
                if command is not None:
                    outbox.save(
                        command.model_copy(
                            update={
                                "state": CodexCommandOutboxState.FAILED,
                                "last_error_code": "host_revoked",
                                "completed_at": now,
                                "updated_at": now,
                                "version": command.version + 1,
                            }
                        )
                    )
            unit_of_work.commit()
            return revoked
        except BaseException:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
