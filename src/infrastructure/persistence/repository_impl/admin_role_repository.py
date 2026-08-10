"""管理员角色仓储。"""

from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import selectinload

from src.application.admin.identity.shared.admin_identity_command import (
    AdminRoleCreateCommand,
    AdminRoleDeleteCommand,
    AdminRoleScopeReplaceCommand,
    AdminRoleUpdateCommand,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityDeleteResult,
    AdminRoleListQuery,
    AdminRolePage,
    AdminRoleSnapshot,
)
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_role_scope_orm_model import (
    AuthRoleScopeOrmModel,
)
from src.infrastructure.persistence.repository_impl.admin_identity_repository_support import (
    ADMIN_ROLE_KEY,
    BOUND_ROLE_DELETE_BLOCKED_MESSAGE,
    BUILTIN_ADMIN_ROLE_DELETE_BLOCKED_MESSAGE,
    BUSINESS_ADMIN_ROLE_KEYS,
    DELETE_ACCEPTED_REASON,
    REGISTERED_USER_ROLE_CHANGE_BLOCKED_MESSAGE,
    REGISTERED_USER_ROLE_KEY,
    ROLE_ALREADY_EXISTS_MESSAGE,
    ROLE_CREATE_PROTECTED_SCOPE_BLOCKED_MESSAGE,
    ROLE_NOT_FOUND_MESSAGE,
    AdminIdentityRepositorySupport,
)


class AdminRoleRepository(AdminIdentityRepositorySupport):
    """管理员角色仓储实现。"""

    def list_roles(self, query: AdminRoleListQuery) -> AdminRolePage:
        """
        查询角色列表。
        """

        statement = self._build_business_role_statement(query)
        if not query.business_only:
            statement = self._build_role_list_statement(query)
        total = int(self._session.execute(self._build_role_count_statement(statement)).scalar_one())
        roles = list(
            self._session.scalars(
                statement.order_by(AuthRoleOrmModel.role_key.asc())
                .offset(max(query.offset, 0))
                .limit(self._normalize_page_size(query.page_size))
            ).all()
        )
        return AdminRolePage(
            roles=[self._build_role_snapshot(role) for role in roles],
            page_size=query.page_size,
            offset=query.offset,
            total=total,
        )

    def get_role(self, role_key: str) -> AdminRoleSnapshot:
        """
        读取角色详情。
        """

        role = self._get_role_row(role_key)
        if role is None:
            self._raise_not_found(ROLE_NOT_FOUND_MESSAGE)
        return self._build_role_snapshot(role)

    def create_role(self, command: AdminRoleCreateCommand) -> AdminRoleSnapshot:
        """
        创建角色。
        """

        if self._get_role_row(command.role_key) is not None:
            self._raise_conflict(ROLE_ALREADY_EXISTS_MESSAGE)
        scope_codes = self._normalize_unique_values(command.scope_codes)
        self._validate_scope_codes_enabled(scope_codes)
        if (
            self._scope_codes_contain_protected_admin_scope(scope_codes)
            and not command.grant_confirmed
        ):
            self._raise_invalid(ROLE_CREATE_PROTECTED_SCOPE_BLOCKED_MESSAGE)
        role = AuthRoleOrmModel(
            role_key=command.role_key,
            role_name=command.role_name,
        )
        self._session.add(role)
        self._session.flush()
        self._replace_role_scope_rows(role=role, scope_codes=scope_codes)
        self._session.flush()
        return self.get_role(command.role_key)

    def update_role(self, command: AdminRoleUpdateCommand) -> AdminRoleSnapshot:
        """
        更新角色。
        """

        role = self._get_role_row(command.role_key)
        if role is None:
            self._raise_not_found(ROLE_NOT_FOUND_MESSAGE)
        if command.role_key == REGISTERED_USER_ROLE_KEY:
            self._raise_conflict(REGISTERED_USER_ROLE_CHANGE_BLOCKED_MESSAGE)
        role.role_name = command.role_name
        self._session.flush()
        return self.get_role(command.role_key)

    def replace_role_scopes(
        self,
        command: AdminRoleScopeReplaceCommand,
    ) -> AdminRoleSnapshot:
        """
        替换角色 scope。
        """

        role = self._get_role_row(command.role_key)
        if role is None:
            self._raise_not_found(ROLE_NOT_FOUND_MESSAGE)
        if command.role_key == REGISTERED_USER_ROLE_KEY:
            self._raise_conflict(REGISTERED_USER_ROLE_CHANGE_BLOCKED_MESSAGE)
        scope_codes = self._normalize_unique_values(command.scope_codes)
        self._validate_scope_codes_enabled(scope_codes)
        self._validate_actor_after_role_scope_change(
            actor_subject_id=command.actor_subject_id,
            target_role_key=command.role_key,
            next_scope_codes=scope_codes,
        )
        self._lock_user_table_for_admin_access_invariant()
        self._replace_role_scope_rows(role=role, scope_codes=scope_codes)
        self._session.flush()
        self._assert_admin_access_invariant()
        return self.get_role(command.role_key)

    def delete_role(self, command: AdminRoleDeleteCommand) -> AdminIdentityDeleteResult:
        """
        删除角色。
        """

        role = self._get_role_row(command.role_key)
        if role is None:
            self._raise_not_found(ROLE_NOT_FOUND_MESSAGE)
        if command.role_key == ADMIN_ROLE_KEY:
            self._raise_conflict(BUILTIN_ADMIN_ROLE_DELETE_BLOCKED_MESSAGE)
        if command.role_key == REGISTERED_USER_ROLE_KEY:
            self._raise_conflict(REGISTERED_USER_ROLE_CHANGE_BLOCKED_MESSAGE)
        if len(role.user_roles) > 0:
            self._raise_conflict(BOUND_ROLE_DELETE_BLOCKED_MESSAGE)
        self._session.delete(role)
        self._session.flush()
        return AdminIdentityDeleteResult(
            target_id=command.role_key,
            deleted=True,
            reason=DELETE_ACCEPTED_REASON,
        )

    def _build_role_statement(self) -> Select[tuple[AuthRoleOrmModel]]:
        """
        构建角色查询语句。
        """

        return select(AuthRoleOrmModel).options(
            selectinload(AuthRoleOrmModel.role_scopes),
            selectinload(AuthRoleOrmModel.user_roles),
        )

    def _build_business_role_statement(
        self,
        query: AdminRoleListQuery,
    ) -> Select[tuple[AuthRoleOrmModel]]:
        """
        构建业务角色列表查询语句。
        """

        statement = self._build_role_statement().where(
            AuthRoleOrmModel.role_key.in_(BUSINESS_ADMIN_ROLE_KEYS)
        )
        if query.keyword is not None:
            keyword = self._build_like_keyword(query.keyword)
            statement = statement.where(
                AuthRoleOrmModel.role_key.ilike(keyword) | AuthRoleOrmModel.role_name.ilike(keyword)
            )
        return statement

    def _build_role_list_statement(
        self,
        query: AdminRoleListQuery,
    ) -> Select[tuple[AuthRoleOrmModel]]:
        """
        构建完整角色列表查询语句。
        """

        statement = self._build_role_statement()
        if query.keyword is not None:
            keyword = self._build_like_keyword(query.keyword)
            statement = statement.where(
                AuthRoleOrmModel.role_key.ilike(keyword) | AuthRoleOrmModel.role_name.ilike(keyword)
            )
        return statement

    def _get_role_row(self, role_key: str) -> AuthRoleOrmModel | None:
        """
        读取角色 ORM 行。
        """

        statement = self._build_role_statement().where(AuthRoleOrmModel.role_key == role_key)
        return self._session.scalars(statement).one_or_none()

    def _build_role_snapshot(self, role: AuthRoleOrmModel) -> AdminRoleSnapshot:
        """
        构建角色快照。
        """

        return AdminRoleSnapshot(
            role_key=role.role_key,
            role_name=role.role_name,
            scope_codes=sorted(
                self._normalize_unique_values(
                    [role_scope.scope_code for role_scope in role.role_scopes]
                )
            ),
            user_count=len(role.user_roles),
        )

    def _replace_role_scope_rows(
        self,
        *,
        role: AuthRoleOrmModel,
        scope_codes: list[str],
    ) -> None:
        """
        替换角色 scope 关联。
        """

        role.role_scopes[:] = [
            AuthRoleScopeOrmModel(scope_code=scope_code)
            for scope_code in self._normalize_unique_values(scope_codes)
        ]

    def _matches_role_query(
        self,
        *,
        snapshot: AdminRoleSnapshot,
        query: AdminRoleListQuery,
    ) -> bool:
        """
        判断角色是否命中查询条件。
        """

        if query.keyword is None:
            return True
        keyword = query.keyword.lower()
        return keyword in snapshot.role_key.lower() or keyword in snapshot.role_name.lower()
