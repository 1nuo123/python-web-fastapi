"""
管理员用户用例集成测试模块。
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import or_

from src.api.testing.test_app_factory import TestAppFactory
from src.application.admin.identity.shared.admin_identity_command import (
    AdminUserCreateCommand,
    AdminUserDeleteCommand,
    AdminUserPasswordResetCommand,
    AdminUserRoleReplaceCommand,
    AdminUserScopeReplaceCommand,
    AdminUserUpdateCommand,
)
from src.application.ports.admin_identity_port import BusinessAdminRoleKey
from src.domain.auth.auth_role_key import AuthRoleKey
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_role_scope_orm_model import (
    AuthRoleScopeOrmModel,
)
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.auth_user_role_orm_model import (
    AuthUserRoleOrmModel,
)
from src.infrastructure.shared_resource_mount import SharedResourceMount

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
]

USER_UNIT_PASSWORD = "user-unit-password"
USER_UNIT_NEW_PASSWORD = "user-unit-new-password"
DEFAULT_ADMIN_SUBJECT_ID = "user-admin"
CUSTOMER_SERVICE_ROLE = BusinessAdminRoleKey.CUSTOMER_SERVICE.value
BUSINESS_OPERATOR_ROLE = BusinessAdminRoleKey.BUSINESS_OPERATOR.value
PEER_ADMIN_USERNAME_SUFFIX = "peer-admin"
PROTECTED_ADMIN_USERNAME_SUFFIX = "protected-admin"
PASSWORD_RESET_SELF_EXPECTED_STATUS = HTTPStatus.UNPROCESSABLE_ENTITY
PASSWORD_RESET_PEER_EXPECTED_STATUS = HTTPStatus.UNPROCESSABLE_ENTITY
ADMIN_ROLE_SCOPE_CODES = [scope.value for scope in AuthScopeCode]
LOW_PRIVILEGE_ADMIN_SCOPE_CODES = [AuthScopeCode.AUTH_PASSWORD_RESET.value]


class TestAdminUserUsecaseIntegration:
    """
    管理员用户用例测试集合。
    """

    def test_user_create_update_reset_replace_roles_and_delete_should_success(
        self,
    ) -> None:
        """
        验证用户创建、更新、密码重置、角色替换与停用成功。
        """

        username = self._build_username("crud")
        updated_username = self._build_username("updated")
        subject_id = self._build_subject_id("crud")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                created = resource_mount.create_admin_user(
                    AdminUserCreateCommand(
                        username=username,
                        password_plain=USER_UNIT_PASSWORD,
                        role_keys=[CUSTOMER_SERVICE_ROLE],
                        subject_id=subject_id,
                    )
                )
                updated = resource_mount.update_admin_user(
                    AdminUserUpdateCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=subject_id,
                        username=updated_username,
                        is_active=True,
                    )
                )
                reset = resource_mount.reset_admin_user_password(
                    AdminUserPasswordResetCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=subject_id,
                        password_plain=USER_UNIT_NEW_PASSWORD,
                    )
                )
                replaced = resource_mount.replace_admin_user_roles(
                    AdminUserRoleReplaceCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=subject_id,
                        role_keys=[BUSINESS_OPERATOR_ROLE],
                    )
                )
                deleted = resource_mount.delete_admin_user(
                    AdminUserDeleteCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=subject_id,
                    )
                )
            finally:
                self._cleanup(
                    resource_mount=resource_mount,
                    subject_ids=[subject_id],
                    usernames=[username, updated_username],
                )

        assert created.subject_id == subject_id
        assert updated.username == updated_username
        assert reset.subject_id == subject_id
        assert BUSINESS_OPERATOR_ROLE in replaced.role_keys
        assert deleted.deleted is True

    def test_user_create_when_username_duplicate_should_return_conflict(self) -> None:
        """
        验证重复用户名返回冲突。
        """

        username = self._build_username("duplicate")
        first_subject_id = self._build_subject_id("first")
        second_subject_id = self._build_subject_id("second")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                resource_mount.create_admin_user(
                    AdminUserCreateCommand(
                        username=username,
                        password_plain=USER_UNIT_PASSWORD,
                        role_keys=[CUSTOMER_SERVICE_ROLE],
                        subject_id=first_subject_id,
                    )
                )
                with pytest.raises(Exception) as fault:
                    resource_mount.create_admin_user(
                        AdminUserCreateCommand(
                            username=username,
                            password_plain=USER_UNIT_PASSWORD,
                            role_keys=[CUSTOMER_SERVICE_ROLE],
                            subject_id=second_subject_id,
                        )
                    )
            finally:
                self._cleanup(
                    resource_mount=resource_mount,
                    subject_ids=[first_subject_id, second_subject_id],
                    usernames=[username],
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def test_user_direct_scope_replace_should_update_effective_authorization(self) -> None:
        """验证用户直接 scope 替换后成为主体授权事实。"""

        username = self._build_username("direct-scope")
        subject_id = self._build_subject_id("direct-scope")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                resource_mount.create_admin_user(
                    AdminUserCreateCommand(
                        username=username,
                        password_plain=USER_UNIT_PASSWORD,
                        role_keys=[CUSTOMER_SERVICE_ROLE],
                        subject_id=subject_id,
                    )
                )
                snapshot = resource_mount.replace_admin_user_scopes(
                    AdminUserScopeReplaceCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=subject_id,
                        scope_codes=[
                            AuthScopeCode.CODEX_READ.value,
                            AuthScopeCode.CODEX_NETWORK.value,
                            AuthScopeCode.CODEX_READ.value,
                        ],
                    )
                )
                unit_of_work = resource_mount.create_unit_of_work()
                try:
                    principal_snapshot = resource_mount.create_auth_identity_repository(
                        unit_of_work.get_session()
                    ).get_authorization_snapshot_by_subject_id(subject_id)
                finally:
                    unit_of_work.dispose()
            finally:
                self._cleanup(
                    resource_mount=resource_mount,
                    subject_ids=[subject_id],
                    usernames=[username],
                )

        assert snapshot.direct_scope_codes == [
            AuthScopeCode.CODEX_NETWORK.value,
            AuthScopeCode.CODEX_READ.value,
        ]
        assert AuthScopeCode.CODEX_READ.value in snapshot.effective_scope_codes
        assert AuthScopeCode.CODEX_NETWORK.value in snapshot.effective_scope_codes
        assert principal_snapshot is not None
        assert AuthScopeCode.CODEX_READ in principal_snapshot.scopes
        assert AuthScopeCode.CODEX_NETWORK in principal_snapshot.scopes

    def test_user_replace_roles_when_role_missing_should_return_invalid(self) -> None:
        """
        验证替换不存在的角色返回校验失败。
        """

        username = self._build_username("missing-role")
        subject_id = self._build_subject_id("missing-role")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                resource_mount.create_admin_user(
                    AdminUserCreateCommand(
                        username=username,
                        password_plain=USER_UNIT_PASSWORD,
                        role_keys=[CUSTOMER_SERVICE_ROLE],
                        subject_id=subject_id,
                    )
                )
                with pytest.raises(Exception) as fault:
                    resource_mount.replace_admin_user_roles(
                        AdminUserRoleReplaceCommand(
                            actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                            subject_id=subject_id,
                            role_keys=[self._build_missing_role_key()],
                        )
                    )
            finally:
                self._cleanup(
                    resource_mount=resource_mount,
                    subject_ids=[subject_id],
                    usernames=[username],
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_user_create_when_admin_role_assigned_should_return_invalid(self) -> None:
        """
        验证业务后台用户不能分配技术管理员角色。
        """

        username = self._build_username("admin-role")
        subject_id = self._build_subject_id("admin-role")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            with pytest.raises(Exception) as fault:
                resource_mount.create_admin_user(
                    AdminUserCreateCommand(
                        username=username,
                        password_plain=USER_UNIT_PASSWORD,
                        role_keys=[AuthRoleKey.ADMIN.value],
                        subject_id=subject_id,
                    )
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_user_role_replace_when_self_lock_should_return_conflict(self) -> None:
        """
        验证操作者移除自身管理能力时返回冲突。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            with pytest.raises(Exception) as fault:
                resource_mount.replace_admin_user_roles(
                    AdminUserRoleReplaceCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        role_keys=[],
                    )
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def test_user_update_when_self_disabled_should_return_conflict(self) -> None:
        """
        验证操作者停用自身资料时返回冲突。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            with pytest.raises(Exception) as fault:
                resource_mount.update_admin_user(
                    AdminUserUpdateCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        username=None,
                        is_active=False,
                    )
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def test_user_delete_when_self_lock_should_return_conflict(self) -> None:
        """
        验证操作者停用自身时返回冲突。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            with pytest.raises(Exception) as fault:
                resource_mount.delete_admin_user(
                    AdminUserDeleteCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                    )
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def test_user_password_reset_when_self_target_should_return_invalid(self) -> None:
        """
        验证管理员不能重置自己的密码。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount

            with pytest.raises(Exception) as fault:
                resource_mount.reset_admin_user_password(
                    AdminUserPasswordResetCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        password_plain=USER_UNIT_NEW_PASSWORD,
                    )
                )

        assert getattr(fault.value, "status_code", None) == PASSWORD_RESET_SELF_EXPECTED_STATUS

    def test_user_password_reset_when_peer_admin_target_should_return_invalid(
        self,
    ) -> None:
        """
        验证管理员不能重置同级 admin 管理员密码。
        """

        username = self._build_username(PEER_ADMIN_USERNAME_SUFFIX)
        subject_id = self._build_subject_id(PEER_ADMIN_USERNAME_SUFFIX)
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                self._create_admin_user_directly(
                    resource_mount=resource_mount,
                    username=username,
                    subject_id=subject_id,
                )

                with pytest.raises(Exception) as fault:
                    resource_mount.reset_admin_user_password(
                        AdminUserPasswordResetCommand(
                            actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                            subject_id=subject_id,
                            password_plain=USER_UNIT_NEW_PASSWORD,
                        )
                    )
            finally:
                self._cleanup(
                    resource_mount=resource_mount,
                    subject_ids=[subject_id],
                    usernames=[username],
                )

        assert getattr(fault.value, "status_code", None) == PASSWORD_RESET_PEER_EXPECTED_STATUS

    def test_user_password_reset_when_low_privilege_admin_targets_admin_should_fail(
        self,
    ) -> None:
        """
        验证低权限密码重置管理员不能重置高权限管理员密码。
        """

        username = self._build_username(PROTECTED_ADMIN_USERNAME_SUFFIX)
        subject_id = self._build_subject_id(PROTECTED_ADMIN_USERNAME_SUFFIX)
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                self._replace_admin_role_scopes(
                    resource_mount=resource_mount,
                    scope_codes=LOW_PRIVILEGE_ADMIN_SCOPE_CODES,
                )
                self._create_admin_user_directly(
                    resource_mount=resource_mount,
                    username=username,
                    subject_id=subject_id,
                )

                with pytest.raises(Exception) as fault:
                    resource_mount.reset_admin_user_password(
                        AdminUserPasswordResetCommand(
                            actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                            subject_id=subject_id,
                            password_plain=USER_UNIT_NEW_PASSWORD,
                        )
                    )
            finally:
                self._replace_admin_role_scopes(
                    resource_mount=resource_mount,
                    scope_codes=ADMIN_ROLE_SCOPE_CODES,
                )
                self._cleanup(
                    resource_mount=resource_mount,
                    subject_ids=[subject_id],
                    usernames=[username],
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.UNPROCESSABLE_ENTITY

    def _build_username(self, suffix: str) -> str:
        """
        构建测试用户名。
        """

        return f"unit_user_{suffix}_{uuid4().hex}"

    def _build_subject_id(self, suffix: str) -> str:
        """
        构建测试主体标识。
        """

        return f"unit-user-{suffix}-{uuid4()}"

    def _build_missing_role_key(self) -> str:
        """
        构建不存在的角色键。
        """

        return f"missing_role_{uuid4().hex}"

    def _create_admin_user_directly(
        self,
        *,
        resource_mount: SharedResourceMount,
        username: str,
        subject_id: str,
    ) -> None:
        """
        直接写入测试用 admin 用户。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            admin_role = (
                session.query(AuthRoleOrmModel).filter_by(role_key=AuthRoleKey.ADMIN.value).one()
            )
            user = AuthUserOrmModel(
                username=username,
                subject_id=subject_id,
                password_hash=resource_mount.get_password_hasher().hash_password(
                    USER_UNIT_PASSWORD
                ),
                is_active=True,
            )
            session.add(user)
            session.flush()
            session.add(
                AuthUserRoleOrmModel(
                    user_id=user.user_id,
                    role_id=admin_role.role_id,
                )
            )
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()

    def _replace_admin_role_scopes(
        self,
        *,
        resource_mount: SharedResourceMount,
        scope_codes: list[str],
    ) -> None:
        """
        替换内置管理员角色 scope。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            admin_role = (
                session.query(AuthRoleOrmModel).filter_by(role_key=AuthRoleKey.ADMIN.value).one()
            )
            admin_role.role_scopes.clear()
            for scope_code in scope_codes:
                admin_role.role_scopes.append(AuthRoleScopeOrmModel(scope_code=scope_code))
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()

    def _cleanup(
        self,
        *,
        resource_mount: SharedResourceMount,
        subject_ids: list[str],
        usernames: list[str],
    ) -> None:
        """
        清理测试用户。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            users = (
                session.query(AuthUserOrmModel)
                .filter(
                    or_(
                        AuthUserOrmModel.subject_id.in_(subject_ids),
                        AuthUserOrmModel.username.in_(usernames),
                    )
                )
                .all()
            )
            for user in users:
                session.delete(user)
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
