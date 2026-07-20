"""
初始管理员 CLI 初始化测试模块。
"""

from __future__ import annotations

from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete

from src.api.testing.test_app_factory import TestAppFactory
from src.application.admin.identity.initial_admin.create_initial_admin_usecase import (
    INITIAL_ADMIN_CONFIRMATION_PHRASE,
    CreateInitialAdminUsecase,
)
from src.application.admin.identity.shared.admin_identity_command import (
    InitialAdminCreateCommand,
    InitialAdminCreateReason,
    InitialAdminCreateResult,
)
from src.application.ports.admin_identity_port import AdminUserListQuery
from src.domain.auth.auth_role_key import AuthRoleKey
from src.infrastructure.auth.password_hasher import PasswordHasher
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.auth_user_role_orm_model import (
    AuthUserRoleOrmModel,
)
from src.infrastructure.settings.application_settings import PasswordHashAlgorithm
from src.infrastructure.shared_resource_mount import SharedResourceMount

INITIAL_ADMIN_TEST_USERNAME_PREFIX = "initial_admin_cli"
INITIAL_ADMIN_TEST_PASSWORD = "initial-admin-cli-password"
INITIAL_ADMIN_OTHER_ADMIN_USERNAME_PREFIX = "initial_admin_cli_other"


class TestInitialAdminCliInitialization:
    """
    初始管理员 CLI 初始化测试集合。
    """

    def test_initial_admin_usecase_should_create_and_keep_idempotent(self) -> None:
        """
        验证关闭启动期 bootstrap 后可一次性创建首个 admin 且重复执行幂等。
        """

        username = self._build_username(INITIAL_ADMIN_TEST_USERNAME_PREFIX)
        subject_id = self._build_subject_id(INITIAL_ADMIN_TEST_USERNAME_PREFIX)
        app = TestAppFactory().create(
            overrides={
                "auth_module": {
                    "bootstrap_admin": {
                        "enabled": False,
                        "username": "",
                        "subject_id": "",
                        "role_bindings": [],
                    }
                }
            }
        )
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            admin_role_bindings = self._detach_admin_role_bindings(resource_mount=resource_mount)
            try:
                result = self._execute_initial_admin(
                    resource_mount=resource_mount,
                    username=username,
                    subject_id=subject_id,
                )
                second_result = self._execute_initial_admin(
                    resource_mount=resource_mount,
                    username=username,
                    subject_id=subject_id,
                )
                users = resource_mount.list_admin_users(self._build_user_list_query(username))
            finally:
                try:
                    self._cleanup(
                        resource_mount=resource_mount,
                        subject_ids=[subject_id],
                    )
                finally:
                    self._restore_admin_role_bindings(
                        resource_mount=resource_mount,
                        bindings=admin_role_bindings,
                    )

        assert result.created is True
        assert result.reason == InitialAdminCreateReason.CREATED
        assert second_result.created is False
        assert second_result.reason == InitialAdminCreateReason.ALREADY_EXISTS
        assert users.total == 1
        assert users.users[0].subject_id == subject_id

    def test_initial_admin_usecase_when_other_admin_exists_should_reject(self) -> None:
        """
        验证已存在其他 admin 时不会创建第二个超级管理员。
        """

        first_username = self._build_username(INITIAL_ADMIN_TEST_USERNAME_PREFIX)
        first_subject_id = self._build_subject_id(INITIAL_ADMIN_TEST_USERNAME_PREFIX)
        second_username = self._build_username(INITIAL_ADMIN_OTHER_ADMIN_USERNAME_PREFIX)
        second_subject_id = self._build_subject_id(INITIAL_ADMIN_OTHER_ADMIN_USERNAME_PREFIX)
        app = TestAppFactory().create(
            overrides={
                "auth_module": {
                    "bootstrap_admin": {
                        "enabled": False,
                        "username": "",
                        "subject_id": "",
                        "role_bindings": [],
                    }
                }
            }
        )
        with TestClient(app):
            resource_mount = app.state.container.resource_mount
            admin_role_bindings = self._detach_admin_role_bindings(resource_mount=resource_mount)
            try:
                self._execute_initial_admin(
                    resource_mount=resource_mount,
                    username=first_username,
                    subject_id=first_subject_id,
                )
                result = self._execute_initial_admin(
                    resource_mount=resource_mount,
                    username=second_username,
                    subject_id=second_subject_id,
                )
                users = resource_mount.list_admin_users(
                    self._build_user_list_query(second_username)
                )
            finally:
                try:
                    self._cleanup(
                        resource_mount=resource_mount,
                        subject_ids=[first_subject_id, second_subject_id],
                    )
                finally:
                    self._restore_admin_role_bindings(
                        resource_mount=resource_mount,
                        bindings=admin_role_bindings,
                    )

        assert result.created is False
        assert result.reason == InitialAdminCreateReason.ADMIN_EXISTS
        assert users.total == 0

    def _execute_initial_admin(
        self,
        *,
        resource_mount: SharedResourceMount,
        username: str,
        subject_id: str,
    ) -> InitialAdminCreateResult:
        """
        执行初始管理员创建用例。
        """

        return CreateInitialAdminUsecase(
            admin_identity_port=resource_mount,
            password_hasher=PasswordHasher(PasswordHashAlgorithm.ARGON2),
        ).execute(
            InitialAdminCreateCommand(
                username=username,
                password_plain=INITIAL_ADMIN_TEST_PASSWORD,
                subject_id=subject_id,
                confirmation=INITIAL_ADMIN_CONFIRMATION_PHRASE,
            )
        )

    def _build_user_list_query(self, keyword: str) -> AdminUserListQuery:
        """
        构建用户列表查询。
        """

        return AdminUserListQuery(
            keyword=keyword,
            role_key=None,
            is_active=None,
            page_size=10,
            offset=0,
        )

    def _build_username(self, prefix: str) -> str:
        """
        构建初始化测试用户名。
        """

        return f"{prefix}_{uuid4().hex}"

    def _build_subject_id(self, prefix: str) -> str:
        """
        构建初始化测试主体标识。
        """

        return f"{prefix}-{uuid4()}"

    def _cleanup(
        self,
        *,
        resource_mount: SharedResourceMount,
        subject_ids: list[str],
    ) -> None:
        """
        清理测试用户。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            users = (
                session.query(AuthUserOrmModel)
                .filter(AuthUserOrmModel.subject_id.in_(subject_ids))
                .all()
            )
            user_ids = [user.user_id for user in users]
            if user_ids:
                session.execute(
                    delete(AuthUserRoleOrmModel).where(AuthUserRoleOrmModel.user_id.in_(user_ids))
                )
            for user in users:
                session.delete(user)
            unit_of_work.commit()
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _detach_admin_role_bindings(
        self,
        *,
        resource_mount: SharedResourceMount,
    ) -> list[tuple[UUID, UUID]]:
        """
        临时移除既有 admin 绑定以隔离首个管理员场景。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            admin_role = (
                session.query(AuthRoleOrmModel)
                .filter(AuthRoleOrmModel.role_key == AuthRoleKey.ADMIN.value)
                .one_or_none()
            )
            if admin_role is None:
                unit_of_work.commit()
                return []
            bindings = (
                session.query(AuthUserRoleOrmModel)
                .filter(AuthUserRoleOrmModel.role_id == admin_role.role_id)
                .all()
            )
            binding_keys = [(binding.user_id, binding.role_id) for binding in bindings]
            for binding in bindings:
                session.delete(binding)
            unit_of_work.commit()
            return binding_keys
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _restore_admin_role_bindings(
        self,
        *,
        resource_mount: SharedResourceMount,
        bindings: list[tuple[UUID, UUID]],
    ) -> None:
        """
        恢复测试开始前存在的 admin 绑定。
        """

        unit_of_work = resource_mount.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            for user_id, role_id in bindings:
                existing = session.get(
                    AuthUserRoleOrmModel,
                    {"user_id": user_id, "role_id": role_id},
                )
                user = session.get(AuthUserOrmModel, user_id)
                role = session.get(AuthRoleOrmModel, role_id)
                if existing is not None or user is None or role is None:
                    continue
                session.add(AuthUserRoleOrmModel(user=user, role=role))
            unit_of_work.commit()
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
