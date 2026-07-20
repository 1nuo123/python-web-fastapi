"""管理员身份资源。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from datetime import UTC, datetime

from src.application.admin.identity.shared.admin_identity_command import (
    AdminRoleCreateCommand,
    AdminRoleDeleteCommand,
    AdminRoleScopeReplaceCommand,
    AdminRoleUpdateCommand,
    AdminScopeCreateCommand,
    AdminScopeDeleteCommand,
    AdminScopeUpdateCommand,
    AdminUserCreateCommand,
    AdminUserDeleteCommand,
    AdminUserPasswordResetCommand,
    AdminUserRoleReplaceCommand,
    AdminUserUpdateCommand,
    InitialAdminCreateResult,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityDeleteResult,
    AdminRoleListQuery,
    AdminRolePage,
    AdminRoleSnapshot,
    AdminScopeListQuery,
    AdminScopeSnapshot,
    AdminUserListQuery,
    AdminUserPage,
    AdminUserSnapshot,
)
from src.infrastructure.resource_mount.shared_resource_lifecycle import SharedResourceLifecycle


class AdminIdentityResourceFacade(SharedResourceLifecycle):
    """管理员身份资源门面。"""

    def list_admin_scopes(
        self,
        query: AdminScopeListQuery,
    ) -> list[AdminScopeSnapshot]:
        """
        查询管理员 scope 列表。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            return repository.list_scopes(query)
        finally:
            unit_of_work.dispose()

    def get_admin_scope(self, scope_code: str) -> AdminScopeSnapshot:
        """
        读取管理员 scope 详情。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            return repository.get_scope(scope_code)
        finally:
            unit_of_work.dispose()

    def create_admin_scope(
        self,
        command: AdminScopeCreateCommand,
    ) -> AdminScopeSnapshot:
        """
        创建管理员 scope。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            snapshot = repository.create_scope(command)
            unit_of_work.commit()
            return snapshot
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def update_admin_scope(
        self,
        command: AdminScopeUpdateCommand,
    ) -> AdminScopeSnapshot:
        """
        更新管理员 scope。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            snapshot = repository.update_scope(command)
            unit_of_work.commit()
            return snapshot
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def delete_admin_scope(
        self,
        command: AdminScopeDeleteCommand,
    ) -> AdminIdentityDeleteResult:
        """
        删除管理员 scope。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            result = repository.delete_scope(command)
            unit_of_work.commit()
            return result
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def list_admin_roles(self, query: AdminRoleListQuery) -> AdminRolePage:
        """
        查询管理员角色列表。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            return repository.list_roles(query)
        finally:
            unit_of_work.dispose()

    def get_admin_role(self, role_key: str) -> AdminRoleSnapshot:
        """
        读取管理员角色详情。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            return repository.get_role(role_key)
        finally:
            unit_of_work.dispose()

    def create_admin_role(
        self,
        command: AdminRoleCreateCommand,
    ) -> AdminRoleSnapshot:
        """
        创建管理员角色。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            snapshot = repository.create_role(command)
            unit_of_work.commit()
            return snapshot
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def update_admin_role(
        self,
        command: AdminRoleUpdateCommand,
    ) -> AdminRoleSnapshot:
        """
        更新管理员角色。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            snapshot = repository.update_role(command)
            unit_of_work.commit()
            return snapshot
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def replace_admin_role_scopes(
        self,
        command: AdminRoleScopeReplaceCommand,
    ) -> AdminRoleSnapshot:
        """
        替换管理员角色 scope。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            snapshot = repository.replace_role_scopes(command)
            unit_of_work.commit()
            return snapshot
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def delete_admin_role(
        self,
        command: AdminRoleDeleteCommand,
    ) -> AdminIdentityDeleteResult:
        """
        删除管理员角色。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            result = repository.delete_role(command)
            unit_of_work.commit()
            return result
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def list_admin_users(self, query: AdminUserListQuery) -> AdminUserPage:
        """
        查询管理员用户列表。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            return repository.list_users(query)
        finally:
            unit_of_work.dispose()

    def get_admin_user(self, subject_id: str) -> AdminUserSnapshot:
        """
        读取管理员用户详情。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            return repository.get_user(subject_id)
        finally:
            unit_of_work.dispose()

    def create_admin_user(
        self,
        command: AdminUserCreateCommand,
    ) -> AdminUserSnapshot:
        """
        创建管理员用户。
        """

        password_hash = self.get_password_hasher().hash_password(command.password_plain)
        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            snapshot = repository.create_user(
                command=command,
                password_hash=password_hash,
            )
            unit_of_work.commit()
            return snapshot
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def update_admin_user(
        self,
        command: AdminUserUpdateCommand,
    ) -> AdminUserSnapshot:
        """
        更新管理员用户。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = self.create_admin_identity_repository(session)
            snapshot = repository.update_user(command)
            if command.is_active is False:
                self.create_refresh_token_repository(
                    session
                ).revoke_active_token_sessions_by_subject_id(
                    subject_id=command.subject_id,
                    revoked_at=datetime.now(UTC),
                )
            unit_of_work.commit()
            return snapshot
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def reset_admin_user_password(
        self,
        command: AdminUserPasswordResetCommand,
    ) -> AdminUserSnapshot:
        """
        重置管理员用户密码。
        """

        password_hash = self.get_password_hasher().hash_password(command.password_plain)
        unit_of_work = self.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = self.create_admin_identity_repository(session)
            snapshot = repository.reset_user_password(
                command=command,
                password_hash=password_hash,
            )
            self.create_refresh_token_repository(
                session
            ).revoke_active_token_sessions_by_subject_id(
                subject_id=command.subject_id,
                revoked_at=datetime.now(UTC),
            )
            unit_of_work.commit()
            return snapshot
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def replace_admin_user_roles(
        self,
        command: AdminUserRoleReplaceCommand,
    ) -> AdminUserSnapshot:
        """
        替换管理员用户角色。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = self.create_admin_identity_repository(session)
            snapshot = repository.replace_user_roles(command)
            self.create_refresh_token_repository(
                session
            ).revoke_active_token_sessions_by_subject_id(
                subject_id=command.subject_id,
                revoked_at=datetime.now(UTC),
            )
            unit_of_work.commit()
            return snapshot
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def delete_admin_user(
        self,
        command: AdminUserDeleteCommand,
    ) -> AdminIdentityDeleteResult:
        """
        停用管理员用户。
        """

        unit_of_work = self.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            repository = self.create_admin_identity_repository(session)
            result = repository.disable_user(command)
            self.create_refresh_token_repository(
                session
            ).revoke_active_token_sessions_by_subject_id(
                subject_id=command.subject_id,
                revoked_at=datetime.now(UTC),
            )
            unit_of_work.commit()
            return result
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

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

        unit_of_work = self.create_unit_of_work()
        try:
            repository = self.create_admin_identity_repository(unit_of_work.get_session())
            result = repository.create_initial_admin_user(
                username=username,
                password_hash=password_hash,
                subject_id=subject_id,
            )
            unit_of_work.commit()
            return result
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
