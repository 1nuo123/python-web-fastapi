"""普通用户注册用例单元测试。"""

from __future__ import annotations

from http import HTTPStatus

import pytest

from src.application.register_user_usecase import (
    RegisteredUserSnapshot,
    RegisterUserUsecase,
    UserRegistrationCommand,
    UserRegistrationPolicy,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.auth.auth_error_code import AuthErrorCode
from src.domain.auth.auth_role_key import AuthRoleKey

UNIT_USERNAME = "unit_user"
UNIT_PASSWORD = "unit-password-strong"
UNIT_SUBJECT_ID = "user-unit"


class UserRegistrationPortStub:
    """记录普通注册调用的端口替身。"""

    def __init__(self) -> None:
        self.received_role_key: str | None = None

    def create_registered_user(
        self,
        *,
        command: UserRegistrationCommand,
        role_key: str,
    ) -> RegisteredUserSnapshot:
        """记录调用并返回测试快照。"""

        self.received_role_key = role_key
        return RegisteredUserSnapshot(
            subject_id=UNIT_SUBJECT_ID,
            username=command.username,
        )


def test_register_user_when_enabled_should_use_server_role() -> None:
    """验证开启注册时只使用服务端策略角色。"""

    registration_port = UserRegistrationPortStub()
    result = RegisterUserUsecase(registration_port=registration_port).execute(
        command=UserRegistrationCommand(
            username=UNIT_USERNAME,
            password_plain=UNIT_PASSWORD,
        ),
        policy=UserRegistrationPolicy(
            enabled=True,
            default_role_key=AuthRoleKey.REGISTERED_USER.value,
        ),
    )

    assert result.subject_id == UNIT_SUBJECT_ID
    assert registration_port.received_role_key == AuthRoleKey.REGISTERED_USER.value


def test_register_user_when_disabled_should_fail_closed() -> None:
    """验证关闭注册时在任何写入前拒绝请求。"""

    registration_port = UserRegistrationPortStub()
    with pytest.raises(HttpFaultException) as fault:
        RegisterUserUsecase(registration_port=registration_port).execute(
            command=UserRegistrationCommand(
                username=UNIT_USERNAME,
                password_plain=UNIT_PASSWORD,
            ),
            policy=UserRegistrationPolicy(
                enabled=False,
                default_role_key=AuthRoleKey.REGISTERED_USER.value,
            ),
        )

    assert fault.value.status_code == HTTPStatus.FORBIDDEN
    assert fault.value.error_code == AuthErrorCode.REGISTRATION_DISABLED
    assert registration_port.received_role_key is None
