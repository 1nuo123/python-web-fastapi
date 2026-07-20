"""
管理员 scope 用例集成测试模块。
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.application.admin.identity.shared.admin_identity_command import (
    AdminRoleCreateCommand,
    AdminScopeCreateCommand,
    AdminScopeDeleteCommand,
    AdminScopeUpdateCommand,
)
from src.application.ports.admin_identity_port import AdminScopeListQuery
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_role_scope_orm_model import (
    AuthRoleScopeOrmModel,
)
from src.infrastructure.persistence.orm_model.auth_scope_orm_model import AuthScopeOrmModel
from src.infrastructure.shared_resource_mount import SharedResourceMount

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
]

SCOPE_UNIT_LIMIT = 20
SCOPE_UNIT_NAME = "单元 scope"
SCOPE_UNIT_UPDATED_NAME = "单元 scope 更新"
SCOPE_UNIT_DESCRIPTION = "单元 scope 描述"
SCOPE_UNIT_ROLE_NAME = "单元角色"
SYNCHRONIZE_SESSION_DISABLED = False
DEFAULT_ADMIN_SUBJECT_ID = "user-admin"


class TestAdminScopeUsecaseIntegration:
    """
    管理员 scope 用例测试集合。
    """

    def test_scope_list_should_include_builtin_and_custom_scope(self) -> None:
        """
        验证 scope 列表包含内置与自定义 scope。
        """

        scope_code = self._build_scope_code("list")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                resource_mount.create_admin_scope(
                    AdminScopeCreateCommand(
                        scope_code=scope_code,
                        scope_name=SCOPE_UNIT_NAME,
                        description=None,
                        enabled=True,
                    )
                )
                scopes = resource_mount.list_admin_scopes(
                    AdminScopeListQuery(
                        keyword=None,
                        enabled=None,
                        limit=SCOPE_UNIT_LIMIT,
                    )
                )
            finally:
                self._cleanup(resource_mount=resource_mount, scope_codes=[scope_code])

        assert AuthScopeCode.AUTH_READ.value in {scope.scope_code for scope in scopes}
        assert scope_code in {scope.scope_code for scope in scopes}

    def test_scope_create_when_duplicate_should_return_conflict(self) -> None:
        """
        验证重复 scope 创建返回冲突。
        """

        scope_code = self._build_scope_code("duplicate")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                command = AdminScopeCreateCommand(
                    scope_code=scope_code,
                    scope_name=SCOPE_UNIT_NAME,
                    description=None,
                    enabled=True,
                )
                resource_mount.create_admin_scope(command)
                with pytest.raises(Exception) as fault:
                    resource_mount.create_admin_scope(command)
            finally:
                self._cleanup(resource_mount=resource_mount, scope_codes=[scope_code])

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def test_scope_delete_when_builtin_should_return_conflict(self) -> None:
        """
        验证内置 scope 不允许删除。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            with pytest.raises(Exception) as fault:
                resource_mount.delete_admin_scope(
                    AdminScopeDeleteCommand(
                        scope_code=AuthScopeCode.AUTH_READ.value,
                    )
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def test_scope_update_when_protected_builtin_disabled_should_return_conflict(
        self,
    ) -> None:
        """
        验证受保护内置 scope 不允许禁用。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            with pytest.raises(Exception) as fault:
                resource_mount.update_admin_scope(
                    AdminScopeUpdateCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        scope_code=AuthScopeCode.AUTH_MANAGE.value,
                        scope_name=None,
                        description=None,
                        enabled=False,
                    )
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def test_scope_update_when_other_protected_builtin_disabled_should_return_conflict(
        self,
    ) -> None:
        """
        验证其他受保护内置 scope 也不允许禁用。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            with pytest.raises(Exception) as fault:
                resource_mount.update_admin_scope(
                    AdminScopeUpdateCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        scope_code=AuthScopeCode.SYSTEM_READ.value,
                        scope_name=None,
                        description=None,
                        enabled=False,
                    )
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def test_scope_update_when_security_manage_disabled_should_return_conflict(
        self,
    ) -> None:
        """
        验证 security:manage 受中心化后台 scope 注册表保护。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            with pytest.raises(Exception) as fault:
                resource_mount.update_admin_scope(
                    AdminScopeUpdateCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        scope_code=AuthScopeCode.SECURITY_MANAGE.value,
                        scope_name=None,
                        description=None,
                        enabled=False,
                    )
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def test_scope_update_when_custom_scope_disabled_should_success(self) -> None:
        """
        验证自定义 scope 可以禁用。
        """

        scope_code = self._build_scope_code("custom-disabled")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                resource_mount.create_admin_scope(
                    AdminScopeCreateCommand(
                        scope_code=scope_code,
                        scope_name=SCOPE_UNIT_NAME,
                        description=None,
                        enabled=True,
                    )
                )
                updated = resource_mount.update_admin_scope(
                    AdminScopeUpdateCommand(
                        actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                        scope_code=scope_code,
                        scope_name=None,
                        description=None,
                        enabled=False,
                    )
                )
            finally:
                self._cleanup(resource_mount=resource_mount, scope_codes=[scope_code])

        assert updated.scope_code == scope_code
        assert updated.enabled is False

    def test_scope_update_when_builtin_name_description_changed_should_success(
        self,
    ) -> None:
        """
        验证内置 scope 名称和描述仍允许编辑。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            updated = resource_mount.update_admin_scope(
                AdminScopeUpdateCommand(
                    actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                    scope_code=AuthScopeCode.AUTH_MANAGE.value,
                    scope_name=SCOPE_UNIT_UPDATED_NAME,
                    description=SCOPE_UNIT_DESCRIPTION,
                    enabled=True,
                )
            )

        assert updated.scope_name == SCOPE_UNIT_UPDATED_NAME
        assert updated.description == SCOPE_UNIT_DESCRIPTION
        assert updated.enabled is True

    def test_scope_update_when_actor_transmitted_should_keep_access(
        self,
    ) -> None:
        """
        验证路由层传入的 actor 主体标识会参与自锁判断。
        """

        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            updated = resource_mount.update_admin_scope(
                AdminScopeUpdateCommand(
                    actor_subject_id=DEFAULT_ADMIN_SUBJECT_ID,
                    scope_code=AuthScopeCode.AUTH_MANAGE.value,
                    scope_name=SCOPE_UNIT_UPDATED_NAME,
                    description=SCOPE_UNIT_DESCRIPTION,
                    enabled=True,
                )
            )
            scopes = resource_mount.list_admin_scopes(
                AdminScopeListQuery(
                    keyword=None,
                    enabled=None,
                    limit=SCOPE_UNIT_LIMIT,
                )
            )

        assert updated.enabled is True
        assert AuthScopeCode.AUTH_MANAGE.value in {scope.scope_code for scope in scopes}

    def test_scope_delete_when_bound_role_should_return_conflict(self) -> None:
        """
        验证已绑定角色的 scope 不允许删除。
        """

        scope_code = self._build_scope_code("bound")
        role_key = self._build_role_key("bound")
        app = TestAppFactory().create()
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            try:
                resource_mount.create_admin_scope(
                    AdminScopeCreateCommand(
                        scope_code=scope_code,
                        scope_name=SCOPE_UNIT_NAME,
                        description=None,
                        enabled=True,
                    )
                )
                resource_mount.create_admin_role(
                    AdminRoleCreateCommand(
                        role_key=role_key,
                        role_name=SCOPE_UNIT_ROLE_NAME,
                        scope_codes=[scope_code],
                        grant_confirmed=True,
                    )
                )
                with pytest.raises(Exception) as fault:
                    resource_mount.delete_admin_scope(
                        AdminScopeDeleteCommand(scope_code=scope_code)
                    )
            finally:
                self._cleanup(
                    resource_mount=resource_mount,
                    scope_codes=[scope_code],
                    role_keys=[role_key],
                )

        assert getattr(fault.value, "status_code", None) == HTTPStatus.CONFLICT

    def _build_scope_code(self, suffix: str) -> str:
        """
        构建测试 scope 编码。
        """

        return f"unit:{suffix}:{uuid4()}"

    def _build_role_key(self, suffix: str) -> str:
        """
        构建测试角色键。
        """

        return f"unit_role_{suffix}_{uuid4().hex}"

    def _cleanup(
        self,
        *,
        resource_mount: SharedResourceMount,
        scope_codes: list[str],
        role_keys: list[str] | None = None,
    ) -> None:
        """
        清理测试数据。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            if role_keys is not None:
                roles = (
                    session.query(AuthRoleOrmModel)
                    .filter(AuthRoleOrmModel.role_key.in_(role_keys))
                    .all()
                )
                role_ids = [role.role_id for role in roles]
                if role_ids:
                    (
                        session.query(AuthRoleScopeOrmModel)
                        .filter(AuthRoleScopeOrmModel.role_id.in_(role_ids))
                        .delete(synchronize_session=SYNCHRONIZE_SESSION_DISABLED)
                    )
                for role in roles:
                    session.delete(role)
            (
                session.query(AuthRoleScopeOrmModel)
                .filter(AuthRoleScopeOrmModel.scope_code.in_(scope_codes))
                .delete(synchronize_session=SYNCHRONIZE_SESSION_DISABLED)
            )
            scopes = (
                session.query(AuthScopeOrmModel)
                .filter(AuthScopeOrmModel.scope_code.in_(scope_codes))
                .all()
            )
            for scope in scopes:
                session.delete(scope)
            unit_of_work.commit()
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
