"""普通用户注册 HTTP 契约测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.api.endpoint_auth_access.contract_auth_access import (
    AUTH_REGISTRATION_PASSWORD_MAX_LENGTH,
    AUTH_REGISTRATION_PASSWORD_MIN_LENGTH,
    AUTH_REGISTRATION_USERNAME_MAX_LENGTH,
    AUTH_REGISTRATION_USERNAME_MIN_LENGTH,
    UserRegistrationPayload,
    UserRegistrationRequest,
)


def test_registration_request_should_normalize_and_hide_password() -> None:
    """验证注册请求规范化用户名且序列化不泄漏密码。"""

    password = "contract-password"
    request = UserRegistrationRequest(username="  contract_user  ", password=password)

    assert request.username == "contract_user"
    assert password not in request.model_dump_json()


@pytest.mark.parametrize(
    ("username", "password"),
    [
        ("a" * (AUTH_REGISTRATION_USERNAME_MIN_LENGTH - 1), "p" * 12),
        ("a" * (AUTH_REGISTRATION_USERNAME_MAX_LENGTH + 1), "p" * 12),
        ("UpperCase", "p" * 12),
        ("invalid user", "p" * 12),
        ("valid_user", "p" * (AUTH_REGISTRATION_PASSWORD_MIN_LENGTH - 1)),
        ("valid_user", "p" * (AUTH_REGISTRATION_PASSWORD_MAX_LENGTH + 1)),
    ],
)
def test_registration_request_when_boundary_invalid_should_fail(
    username: str,
    password: str,
) -> None:
    """验证用户名和密码边界非法时拒绝请求。"""

    with pytest.raises(ValidationError):
        UserRegistrationRequest(username=username, password=password)


def test_registration_contract_should_reject_unknown_fields() -> None:
    """验证注册契约拒绝客户端角色和未知字段。"""

    with pytest.raises(ValidationError):
        UserRegistrationRequest.model_validate(
            {
                "username": "contract_user",
                "password": "contract-password",
                "role_key": "admin",
            }
        )


def test_registration_payload_should_keep_public_fields_only() -> None:
    """验证注册响应只包含非敏感公共字段。"""

    payload = UserRegistrationPayload(
        subject_id="user-contract",
        username="contract_user",
    )

    assert set(payload.model_dump()) == {
        "kind",
        "schema_version",
        "subject_id",
        "username",
    }
