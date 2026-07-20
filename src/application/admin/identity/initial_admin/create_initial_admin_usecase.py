"""
初始管理员创建用例。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Protocol

from src.application.admin.identity.shared.admin_identity_command import (
    InitialAdminCreateCommand,
    InitialAdminCreateResult,
)
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException

INITIAL_ADMIN_CONFIRMATION_PHRASE = "create-initial-admin"
INITIAL_ADMIN_CONFIRMATION_INVALID_MESSAGE = "初始管理员创建确认短语无效。"


class InitialAdminCreatePort(Protocol):
    """
    初始管理员创建端口。
    """

    def create_initial_admin_user(
        self,
        *,
        username: str,
        password_hash: str,
        subject_id: str | None,
    ) -> InitialAdminCreateResult:
        """
        创建首个管理员用户。
        """


class PasswordHashPort(Protocol):
    """
    密码哈希端口。
    """

    def hash_password(self, password_plain: str) -> str:
        """
        对明文密码执行哈希。
        """


class CreateInitialAdminUsecase:
    """
    初始管理员创建用例。
    """

    def __init__(
        self,
        *,
        admin_identity_port: InitialAdminCreatePort,
        password_hasher: PasswordHashPort,
    ) -> None:
        """
        初始化初始管理员创建用例。
        """

        self._admin_identity_port = admin_identity_port
        self._password_hasher = password_hasher

    def execute(
        self,
        command: InitialAdminCreateCommand,
    ) -> InitialAdminCreateResult:
        """
        执行初始管理员创建。
        """

        if command.confirmation != INITIAL_ADMIN_CONFIRMATION_PHRASE:
            raise HttpFaultException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code=CoreErrorCode.REQUEST_INVALID,
                message=INITIAL_ADMIN_CONFIRMATION_INVALID_MESSAGE,
            )
        return self._admin_identity_port.create_initial_admin_user(
            username=command.username,
            password_hash=self._password_hasher.hash_password(command.password_plain),
            subject_id=command.subject_id,
        )
