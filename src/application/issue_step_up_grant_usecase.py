"""当前认证主体的密码再验证与短时 grant 签发。"""

from __future__ import annotations

import asyncio
from http import HTTPStatus

from src.application.ports.auth_runtime_port import AuthRuntimePort
from src.application.ports.step_up_grant_port import StepUpGrantIssue, StepUpGrantPort
from src.core.auth_contract.step_up_grant_contract import StepUpGrantPurpose
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.auth.auth_error_code import AuthErrorCode


class IssueStepUpGrantUsecase:
    def __init__(self, *, runtime_port: AuthRuntimePort, grant_port: StepUpGrantPort) -> None:
        self._runtime_port = runtime_port
        self._grant_port = grant_port

    async def execute(
        self,
        *,
        subject_id: str,
        password_plain: str,
        purpose: StepUpGrantPurpose,
    ) -> StepUpGrantIssue:
        await asyncio.to_thread(
            self._verify_identity,
            subject_id=subject_id,
            password_plain=password_plain,
        )
        return await self._grant_port.issue(subject_id=subject_id, purpose=purpose)

    def _verify_identity(self, *, subject_id: str, password_plain: str) -> None:
        unit_of_work = self._runtime_port.create_unit_of_work()
        try:
            identity = self._runtime_port.create_auth_identity_repository(
                unit_of_work.get_session()
            ).get_by_subject_id(subject_id)
            valid = (
                identity is not None
                and identity.is_active
                and self._runtime_port.get_password_hasher().verify_password(
                    password_plain,
                    identity.password_hash,
                )
            )
            if not valid:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.INVALID_CREDENTIALS,
                    message="增强验证失败。",
                )
        finally:
            unit_of_work.dispose()
