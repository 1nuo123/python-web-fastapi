"""
管理员角色用例集成测试模块。
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.application.admin.identity.shared.admin_identity_command import (
    AdminRoleCreateCommand,
    AdminRoleDeleteCommand,
    AdminRoleScopeReplaceCommand,
    AdminRoleUpdateCommand,
    AdminScopeCreateCommand,
    AdminUserCreateCommand,
)
from src.application.ports.admin_identity_port import BusinessAdminRoleKey
from src.domain.auth.auth_role_key import AuthRoleKey
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_scope_orm_model import AuthScopeOrmModel
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.shared_resource_mount import SharedResourceMount

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
]

ROLE_UNIT_NAME = "角色单元测试"
ROLE_UNIT_UPDATED_NAME = "角色单元测试更新"
ROLE_UNIT_DISABLED_SCOPE_NAME = "禁用 scope"
ROLE_UNIT_PASSWORD = "role-unit-password"
ROLE_UNIT_ACTOR_SUBJECT_ID = "not-current-user"
DEFAULT_ADMIN_SUBJECT_ID = "user-admin"


class TestAdminRoleUsecaseIntegration:
    """
    管理员角色用例测试集合。
    """

    def test_role_create_update_replace_and_delete_should_success(self) -> None:
        """
        验证角色创建、更新、替换 scope、删除链路成功。
        """

        role_key = self._build_role_key("crud")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                created = resource_mount.create_admin_role(
                    AdminRoleCreateCommand(
                        role_key=role_key,
                        role_name=ROLE_UNIT_NAME,
                        scope_codes=[AuthScopeCode.AUTH_READ.value],
                        grant_confirmed=True,
                    )
                )
                updated = resource_mount.update_admin_role(
                    AdminRoleUpdateCommand(
                        role_key=role_key,
                        role_name=ROLE_UNIT_UPDATED_NAME,
                    )
                )
                replaced = resource_mount.replace_admin_role_scopes(
                    AdminRoleScopeReplaceCommand(
                        actor_subject_id=ROLE_UNIT_ACTOR_SUBJECT_ID,
                        role_key=role_key,
                        scope_codes=[AuthScopeCode.SYSTEM_READ.value],
                    )
                )
                deleted = resource_mount.delete_admin_role(
                    AdminRoleDeleteCommand(
                        actor_subject_id=ROLE_UNIT_ACTOR_SUBJECT_ID,
                        role_key=role_key,
                    )
                )
            finally:
                self._cleanup(resource_mount=resource_mount, role_keys=[role_key])

        assert created.role_key == role_key
        assert updated.role_name == ROLE_UNIT_UPDATED_NAME
        assert replaced.scope_codes == [AuthScopeCode.SYSTEM_READ.value]
        assert deleted.deleted is True

    def test_role_create_when_duplicate_should_return_conflict(self) -> None:
        """
        验证重复角色创建返回冲突。
        """

        role_key = self._build_role_key("duplicate")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                command = AdminRoleCreateCommand(
                    role_key=role_key,
                    role_name=ROLE_UNIT_NAME,
                    scope_codes=[AuthScopeCode.AUTH_READ.value],
                    grant_confirmed=True,
                )
                resource_mount.create_admin_role(command)
                with pytest.raises(Exception) as fault:
                    resource_mount.create_admin_role(command)
            finally:
                self._cleanup(resource_mount=resource_mount, role_keys=[role_key])

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def test_role_scope_replace_when_scope_missing_should_return_invalid(
        self,
    ) -> None:
        """
        验证替换不存在的 scope 返回校验失败。
        """

        role_key = self._build_role_key("missing-scope")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                resource_mount.create_admin_role(
                    AdminRoleCreateCommand(
                        role_key=role_key,
                        role_name=ROLE_UNIT_NAME,
                        scope_codes=[AuthScopeCode.AUTH_READ.value],
                        grant_confirmed=True,
                    )
                )
                with pytest.raises(Exception) as fault:
                    resource_mount.replace_admin_role_scopes(
                        AdminRoleScopeReplaceCommand(
                            actor_subject_id=ROLE_UNIT_ACTOR_SUBJECT_ID,
                            role_key=role_key,
                            scope_codes=[self._build_missing_scope_code()],
                        )
                    )
            finally:
                self._cleanup(resource_mount=resource_mount, role_keys=[role_key])

        assert getattr(fault.value, "status_code", None) == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_role_delete_when_admin_should_return_conflict(self) -> None:
        """
        验证内置 admin 角色不允许删除。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            with pytest.raises(Exception) as fault:
                resource_mount.delete_admin_role(
                    AdminRoleDeleteCommand(
                        actor_subject_id=ROLE_UNIT_ACTOR_SUBJECT_ID,
                        role_key=AuthRoleKey.ADMIN.value,
                    )
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def test_role_scope_replace_when_self_lock_should_return_conflict(self) -> None:
        """
        验证当前管理员不能移除自身 admin + auth:manage 能力。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            with pytest.raises(Exception) as fault:
                resource_mount.replace_admin_role_scopes(
                    AdminRoleScopeReplaceCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        role_key=AuthRoleKey.ADMIN.value,
                        scope_codes=[AuthScopeCode.AUTH_READ.value],
                    )
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def test_role_create_or_replace_when_scope_disabled_should_return_invalid(
        self,
    ) -> None:
        """
        验证禁用 scope 在角色创建或替换时被拒绝。
        """

        disabled_scope_code = self._build_scope_code("disabled")
        create_role_key = self._build_role_key("disabled-create")
        replace_role_key = self._build_role_key("disabled-replace")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                resource_mount.create_admin_scope(
                    AdminScopeCreateCommand(
                        scope_code=disabled_scope_code,
                        scope_name=ROLE_UNIT_DISABLED_SCOPE_NAME,
                        description=None,
                        enabled=False,
                    )
                )
                with pytest.raises(Exception) as create_fault:
                    resource_mount.create_admin_role(
                        AdminRoleCreateCommand(
                            role_key=create_role_key,
                            role_name=ROLE_UNIT_NAME,
                            scope_codes=[disabled_scope_code],
                        )
                    )
                resource_mount.create_admin_role(
                    AdminRoleCreateCommand(
                        role_key=replace_role_key,
                        role_name=ROLE_UNIT_NAME,
                        scope_codes=[AuthScopeCode.AUTH_READ.value],
                        grant_confirmed=True,
                    )
                )
                with pytest.raises(Exception) as replace_fault:
                    resource_mount.replace_admin_role_scopes(
                        AdminRoleScopeReplaceCommand(
                            actor_subject_id=ROLE_UNIT_ACTOR_SUBJECT_ID,
                            role_key=replace_role_key,
                            scope_codes=[disabled_scope_code],
                        )
                    )
            finally:
                self._cleanup(
                    resource_mount=resource_mount,
                    role_keys=[create_role_key, replace_role_key],
                    scope_codes=[disabled_scope_code],
                )

        assert getattr(create_fault.value, "status_code", None) == HTTPStatus.UNPROCESSABLE_ENTITY
        assert getattr(replace_fault.value, "status_code", None) == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_role_create_when_protected_scope_unconfirmed_should_return_invalid(
        self,
    ) -> None:
        """
        验证创建含受保护后台 scope 的角色必须完成授权确认。
        """

        role_key = self._build_role_key("protected-unconfirmed")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                with pytest.raises(Exception) as fault:
                    resource_mount.create_admin_role(
                        AdminRoleCreateCommand(
                            role_key=role_key,
                            role_name=ROLE_UNIT_NAME,
                            scope_codes=[AuthScopeCode.AUTH_READ.value],
                        )
                    )
            finally:
                self._cleanup(resource_mount=resource_mount, role_keys=[role_key])

        assert getattr(fault.value, "status_code", None) == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_role_delete_when_bound_user_should_return_conflict(self) -> None:
        """
        验证已绑定用户的角色不允许删除。
        """

        role_key = BusinessAdminRoleKey.CUSTOMER_SERVICE.value
        username = self._build_username("bound-user")
        subject_id = self._build_subject_id("bound-user")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                resource_mount.create_admin_user(
                    AdminUserCreateCommand(
                        username=username,
                        password_plain=ROLE_UNIT_PASSWORD,
                        role_keys=[role_key],
                        subject_id=subject_id,
                    )
                )
                with pytest.raises(Exception) as fault:
                    resource_mount.delete_admin_role(
                        AdminRoleDeleteCommand(
                            actor_subject_id=ROLE_UNIT_ACTOR_SUBJECT_ID,
                            role_key=role_key,
                        )
                    )
            finally:
                self._cleanup(
                    resource_mount=resource_mount,
                    role_keys=[],
                    subject_ids=[subject_id],
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def _build_role_key(self, suffix: str) -> str:
        """
        构建测试角色键。
        """

        return f"unit_role_{suffix}_{uuid4().hex}"

    def _build_scope_code(self, suffix: str) -> str:
        """
        构建测试 scope 编码。
        """

        return f"unit:role:{suffix}:{uuid4()}"

    def _build_username(self, suffix: str) -> str:
        """
        构建测试用户名。
        """

        return f"unit_role_user_{suffix}_{uuid4().hex}"

    def _build_subject_id(self, suffix: str) -> str:
        """
        构建测试主体标识。
        """

        return f"unit-role-user-{suffix}-{uuid4()}"

    def _build_missing_scope_code(self) -> str:
        """
        构建不存在的 scope 编码。
        """

        return f"missing:{uuid4()}"

    def _cleanup(
        self,
        *,
        resource_mount: SharedResourceMount,
        role_keys: list[str],
        scope_codes: list[str] | None = None,
        subject_ids: list[str] | None = None,
    ) -> None:
        """
        清理测试角色。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            if subject_ids is not None:
                users = (
                    session.query(AuthUserOrmModel)
                    .filter(AuthUserOrmModel.subject_id.in_(subject_ids))
                    .all()
                )
                for user in users:
                    session.delete(user)
            roles = (
                session.query(AuthRoleOrmModel)
                .filter(AuthRoleOrmModel.role_key.in_(role_keys))
                .all()
            )
            for role in roles:
                session.delete(role)
            if scope_codes is not None:
                scopes = (
                    session.query(AuthScopeOrmModel)
                    .filter(AuthScopeOrmModel.scope_code.in_(scope_codes))
                    .all()
                )
                for scope in scopes:
                    session.delete(scope)
            unit_of_work.commit()
        finally:
            unit_of_work.dispose()
