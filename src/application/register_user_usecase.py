"""普通用户注册用例。"""

from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from typing import Protocol

from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.auth.auth_error_code import AuthErrorCode


@dataclass(frozen=True, slots=True)
class UserRegistrationCommand:
    """普通用户注册命令。"""

    username: str
    password_plain: str


@dataclass(frozen=True, slots=True)
class UserRegistrationPolicy:
    """普通用户注册策略。"""

    enabled: bool
    default_role_key: str


@dataclass(frozen=True, slots=True)
class RegisteredUserSnapshot:
    """已注册用户快照。"""

    subject_id: str
    username: str


class UserRegistrationPort(Protocol):
    """普通用户注册端口。"""

    def create_registered_user(
        self,
        *,
        command: UserRegistrationCommand,
        role_key: str,
    ) -> RegisteredUserSnapshot:
        """使用服务端指定角色创建普通用户。"""


class RegisterUserUsecase:
    """普通用户注册编排用例。"""

    def __init__(self, *, registration_port: UserRegistrationPort) -> None:
        """初始化普通用户注册用例。"""

        self._registration_port = registration_port

    def execute(
        self,
        *,
        command: UserRegistrationCommand,
        policy: UserRegistrationPolicy,
    ) -> RegisteredUserSnapshot:
        """按服务端策略创建普通用户。"""

        if not policy.enabled:
            raise HttpFaultException(
                status_code=HTTPStatus.FORBIDDEN,
                error_code=AuthErrorCode.REGISTRATION_DISABLED,
                message="普通用户注册未开放。",
            )
        return self._registration_port.create_registered_user(
            command=command,
            role_key=policy.default_role_key,
        )
