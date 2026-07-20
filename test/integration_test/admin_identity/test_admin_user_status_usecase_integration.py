"""
管理员用户状态用例集成测试模块。
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.application.admin.identity.shared.admin_identity_command import (
    AdminUserCreateCommand,
    AdminUserDeleteCommand,
    AdminUserPasswordResetCommand,
    AdminUserRoleReplaceCommand,
    AdminUserUpdateCommand,
)
from src.application.ports.admin_identity_port import BusinessAdminRoleKey
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.shared_resource_mount import SharedResourceMount

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
]

AUTH_TOKEN_PATH = "/auth/token"
AUTH_REFRESH_PATH = "/auth/refresh"
DATA_FIELD = "data"
ACCESS_TOKEN_FIELD = "access_token"
REFRESH_TOKEN_FIELD = "refresh_token"
DEFAULT_ADMIN_SUBJECT_ID = "user-admin"
USER_STATUS_PASSWORD = "user-status-unit-password"
USER_STATUS_NEW_PASSWORD = "user-status-unit-new-password"
CUSTOMER_SERVICE_ROLE = BusinessAdminRoleKey.CUSTOMER_SERVICE.value
BUSINESS_OPERATOR_ROLE = BusinessAdminRoleKey.BUSINESS_OPERATOR.value


class TestAdminUserStatusUsecaseIntegration:
    """
    管理员用户状态用例测试集合。
    """

    def test_password_reset_should_revoke_refresh_session(self) -> None:
        """
        验证密码重置后撤销用户刷新令牌会话。
        """

        username = self._build_username("password")
        subject_id = self._build_subject_id("password")
        app = TestAppFactory().create()
        with TestClient(app) as client:
            try:
                self._create_user(app.state.container.resource_mount, username, subject_id)
                tokens = self._issue_token_bundle(client, username, USER_STATUS_PASSWORD)
                reset = app.state.container.resource_mount.reset_admin_user_password(
                    AdminUserPasswordResetCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=subject_id,
                        password_plain=USER_STATUS_NEW_PASSWORD,
                    )
                )
                refresh_response = client.post(
                    AUTH_REFRESH_PATH,
                    json={REFRESH_TOKEN_FIELD: tokens[REFRESH_TOKEN_FIELD]},
                )
            finally:
                self._cleanup(app=app, subject_ids=[subject_id])

        assert reset.subject_id == subject_id
        assert refresh_response.status_code == HTTPStatus.UNAUTHORIZED

    def test_role_replace_should_revoke_refresh_session(self) -> None:
        """
        验证角色替换后撤销用户刷新令牌会话。
        """

        username = self._build_username("role")
        subject_id = self._build_subject_id("role")
        app = TestAppFactory().create()
        with TestClient(app) as client:
            try:
                self._create_user(app.state.container.resource_mount, username, subject_id)
                tokens = self._issue_token_bundle(client, username, USER_STATUS_PASSWORD)
                replaced = app.state.container.resource_mount.replace_admin_user_roles(
                    AdminUserRoleReplaceCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=subject_id,
                        role_keys=[BUSINESS_OPERATOR_ROLE],
                    )
                )
                refresh_response = client.post(
                    AUTH_REFRESH_PATH,
                    json={REFRESH_TOKEN_FIELD: tokens[REFRESH_TOKEN_FIELD]},
                )
            finally:
                self._cleanup(app=app, subject_ids=[subject_id])

        assert replaced.role_keys == [BUSINESS_OPERATOR_ROLE]
        assert refresh_response.status_code == HTTPStatus.UNAUTHORIZED

    def test_disable_should_revoke_session_and_enable_should_restore_status(self) -> None:
        """
        验证停用撤销会话，启用恢复用户状态。
        """

        username = self._build_username("disable")
        subject_id = self._build_subject_id("disable")
        app = TestAppFactory().create()
        with TestClient(app) as client:
            try:
                self._create_user(app.state.container.resource_mount, username, subject_id)
                tokens = self._issue_token_bundle(client, username, USER_STATUS_PASSWORD)
                disabled = app.state.container.resource_mount.delete_admin_user(
                    AdminUserDeleteCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=subject_id,
                    )
                )
                refresh_response = client.post(
                    AUTH_REFRESH_PATH,
                    json={REFRESH_TOKEN_FIELD: tokens[REFRESH_TOKEN_FIELD]},
                )
                enabled = app.state.container.resource_mount.update_admin_user(
                    AdminUserUpdateCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=subject_id,
                        username=None,
                        is_active=True,
                    )
                )
            finally:
                self._cleanup(app=app, subject_ids=[subject_id])

        assert disabled.deleted is True
        assert refresh_response.status_code == HTTPStatus.UNAUTHORIZED
        assert enabled.is_active is True

    def _create_user(
        self,
        resource_mount: SharedResourceMount,
        username: str,
        subject_id: str,
    ) -> None:
        """
        创建测试用户。
        """

        resource_mount.create_admin_user(
            AdminUserCreateCommand(
                username=username,
                password_plain=USER_STATUS_PASSWORD,
                role_keys=[CUSTOMER_SERVICE_ROLE],
                subject_id=subject_id,
            )
        )

    def _issue_token_bundle(
        self,
        client: TestClient,
        username: str,
        password: str,
    ) -> dict[str, str]:
        """
        签发测试用户令牌。
        """

        response = client.post(
            AUTH_TOKEN_PATH,
            json={"username": username, "password": password},
        )
        data = response.json()[DATA_FIELD]
        return {
            ACCESS_TOKEN_FIELD: str(data[ACCESS_TOKEN_FIELD]),
            REFRESH_TOKEN_FIELD: str(data[REFRESH_TOKEN_FIELD]),
        }

    def _build_username(self, suffix: str) -> str:
        """
        构建测试用户名。
        """

        return f"user_status_{suffix}_{uuid4().hex}"

    def _build_subject_id(self, suffix: str) -> str:
        """
        构建测试主体标识。
        """

        return f"user-status-{suffix}-{uuid4()}"

    def _cleanup(self, *, app: FastAPI, subject_ids: list[str]) -> None:
        """
        清理测试用户。
        """

        resource_mount = app.state.container.resource_mount
        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            users = (
                session.query(AuthUserOrmModel)
                .filter(AuthUserOrmModel.subject_id.in_(subject_ids))
                .all()
            )
            for user in users:
                session.delete(user)
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
