"""
鉴权运行时应用端口。
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from src.core.auth_contract.authenticated_principal_contract import AuthenticatedPrincipal
from src.core.auth_contract.token_payload_contract import (
    TokenIssuePayload,
    TokenPayload,
    TokenUse,
)
from src.core.persistence_contract.auth_identity_repository_contract import (
    AuthIdentityRepository,
)
from src.core.persistence_contract.refresh_token_repository_contract import (
    RefreshTokenRepository,
)
from src.core.persistence_contract.unit_of_work_contract import PersistenceSession, UnitOfWork


class IssuedTokenBundlePort(Protocol):
    """
    已签发令牌集合端口。
    """

    response_payload: TokenIssuePayload
    refresh_token_payload: TokenPayload


class AuthFailureThrottlePort(Protocol):
    """
    鉴权失败节流端口。
    """

    def assert_issue_access_token_allowed(self, username: str) -> None:
        """
        断言访问令牌签发允许。
        """

    def record_issue_access_token_failure(self, username: str) -> None:
        """
        记录访问令牌签发失败。
        """

    def clear_issue_access_token_failures(self, username: str) -> None:
        """
        清理访问令牌签发失败记录。
        """

    def assert_refresh_access_token_allowed(self, subject_key: str) -> None:
        """
        断言访问令牌刷新允许。
        """

    def record_refresh_access_token_failure(self, subject_key: str) -> None:
        """
        记录访问令牌刷新失败。
        """

    def clear_refresh_access_token_failures(self, subject_key: str) -> None:
        """
        清理访问令牌刷新失败记录。
        """


class PasswordHasherPort(Protocol):
    """
    密码哈希端口。
    """

    def hash_password(self, password_plain: str) -> str:
        """
        计算密码哈希。
        """

    def verify_password(self, password_plain: str, password_hash: str) -> bool:
        """
        校验密码哈希。
        """

    def needs_rehash(self, password_hash: str) -> bool:
        """
        判断密码哈希是否需要升级。
        """


class TokenServicePort(Protocol):
    """
    令牌服务端口。
    """

    def issue_token_pair(
        self,
        principal: AuthenticatedPrincipal,
        *,
        current_epoch: int | None = None,
        token_session_id: UUID | None = None,
    ) -> IssuedTokenBundlePort:
        """
        签发访问令牌与刷新令牌。
        """

    def decode_token(
        self,
        token: str,
        *,
        expected_use: TokenUse,
        current_epoch: int | None = None,
    ) -> TokenPayload:
        """
        解码并校验令牌。
        """


class AuthRuntimePort(Protocol):
    """
    鉴权运行时端口。
    """

    def get_auth_failure_throttle(self) -> AuthFailureThrottlePort:
        """
        获取鉴权失败节流器。
        """

    def create_unit_of_work(self) -> UnitOfWork:
        """
        创建工作单元。
        """

    def create_auth_identity_repository(
        self,
        session: PersistenceSession,
    ) -> AuthIdentityRepository:
        """
        创建鉴权身份仓储。
        """

    def create_refresh_token_repository(
        self,
        session: PersistenceSession,
    ) -> RefreshTokenRepository:
        """
        创建刷新令牌仓储。
        """

    def get_password_hasher(self) -> PasswordHasherPort:
        """
        获取密码哈希器。
        """

    def get_jwt_token_service(self) -> TokenServicePort:
        """
        获取令牌服务。
        """
