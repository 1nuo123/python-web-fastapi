"""访问令牌主体当前授权事实解析器。"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.auth_contract.token_payload_contract import TokenPayload
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.auth.auth_error_code import AuthErrorCode

if TYPE_CHECKING:
    from src.infrastructure.shared_resource_mount import SharedResourceMount

ACCOUNT_DISABLED_MESSAGE = "账号已停用。"
AUTH_SUBJECT_MISSING_MESSAGE = "访问主体不存在。"
TOKEN_SESSION_REVOKED_MESSAGE = "访问令牌所属会话已吊销。"
TOKEN_SESSION_MISSING_MESSAGE = "访问令牌所属会话不存在。"
TOKEN_SESSION_SUBJECT_MISMATCH_MESSAGE = "访问令牌所属会话主体不匹配。"
TOKEN_SESSION_EXPIRED_MESSAGE = "访问令牌所属会话已过期。"
TOKEN_SESSION_INCONSISTENT_MESSAGE = "访问令牌所属会话状态不一致。"


class AuthenticatedPrincipalResolver:
    """复用数据库当前授权与令牌会话状态解析主体。"""

    def __init__(self, *, resource_mount: SharedResourceMount) -> None:
        """初始化共享资源事实源。"""

        self._resource_mount = resource_mount

    def resolve(self, token_payload: TokenPayload) -> AuthenticatedPrincipal:
        """解析已验签访问令牌对应的当前有效主体。"""

        unit_of_work = self._resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            identity_repository = self._resource_mount.create_auth_identity_repository(session)
            refresh_token_repository = self._resource_mount.create_refresh_token_repository(session)
            snapshot = identity_repository.get_authorization_snapshot_by_subject_id(
                token_payload.subject_id
            )
            if snapshot is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=AUTH_SUBJECT_MISSING_MESSAGE,
                )
            if not snapshot.is_active:
                raise HttpFaultException(
                    status_code=HTTPStatus.FORBIDDEN,
                    error_code=AuthErrorCode.ACCOUNT_DISABLED,
                    message=ACCOUNT_DISABLED_MESSAGE,
                )
            session_status = refresh_token_repository.get_token_session_status(
                token_payload.token_session_id
            )
            if session_status is None:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=TOKEN_SESSION_MISSING_MESSAGE,
                )
            if session_status.subject_id != snapshot.subject_id:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=TOKEN_SESSION_SUBJECT_MISMATCH_MESSAGE,
                )
            if session_status.is_inconsistent:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_INVALID,
                    message=TOKEN_SESSION_INCONSISTENT_MESSAGE,
                )
            if session_status.is_revoked:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_REVOKED,
                    message=TOKEN_SESSION_REVOKED_MESSAGE,
                )
            if session_status.is_expired:
                raise HttpFaultException(
                    status_code=HTTPStatus.UNAUTHORIZED,
                    error_code=AuthErrorCode.TOKEN_EXPIRED,
                    message=TOKEN_SESSION_EXPIRED_MESSAGE,
                )
            return AuthenticatedPrincipal.from_authorization_snapshot(snapshot)
        finally:
            unit_of_work.dispose()
