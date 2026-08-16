"""管理员用户仓储。"""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import Select, func, select, text
from sqlalchemy.orm import selectinload

from src.application.admin.identity.shared.admin_identity_command import (
    AdminUserCreateCommand,
    AdminUserDeleteCommand,
    AdminUserPasswordResetCommand,
    AdminUserRoleReplaceCommand,
    AdminUserScopeReplaceCommand,
    AdminUserUpdateCommand,
    InitialAdminCreateReason,
    InitialAdminCreateResult,
)
from src.application.ports.admin_identity_port import (
    AdminIdentityDeleteResult,
    AdminUserListQuery,
    AdminUserPage,
    AdminUserSnapshot,
)
from src.infrastructure.persistence.database_dialect import DatabaseDialect
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.auth_user_role_orm_model import (
    AuthUserRoleOrmModel,
)
from src.infrastructure.persistence.orm_model.auth_user_scope_orm_model import (
    AuthUserScopeOrmModel,
)
from src.infrastructure.persistence.repository_impl.admin_identity_repository_support import (
    ADMIN_IDENTITY_DISABLED_STATUS,
    ADMIN_IDENTITY_SUBJECT_SEPARATOR,
    ADMIN_IDENTITY_USER_SUBJECT_PREFIX,
    ADMIN_ROLE_KEY,
    ADMIN_ROLE_NAME,
    ADMIN_ROLE_SCOPE_CODES,
    AUTH_USER_TABLE_LOCK_SQL,
    INITIAL_ADMIN_DEFAULT_SUBJECT_PREFIX,
    PASSWORD_RESET_PEER_ADMIN_BLOCKED_MESSAGE,
    PASSWORD_RESET_PROTECTED_TARGET_BLOCKED_MESSAGE,
    PASSWORD_RESET_SELF_BLOCKED_MESSAGE,
    ROLE_DISABLED_OR_MISSING_MESSAGE,
    USER_ALREADY_EXISTS_MESSAGE,
    USER_NOT_FOUND_MESSAGE,
    AdminIdentityRepositorySupport,
)


class AdminUserRepository(AdminIdentityRepositorySupport):
    """管理员用户仓储实现。"""

    def list_users(self, query: AdminUserListQuery) -> AdminUserPage:
        """
        查询用户列表。
        """

        statement = self._build_user_list_statement(query)
        total = int(self._session.execute(self._build_user_count_statement(statement)).scalar_one())
        users = list(
            self._session.scalars(
                statement.order_by(
                    AuthUserOrmModel.username.asc(),
                    AuthUserOrmModel.subject_id.asc(),
                )
                .offset(max(query.offset, 0))
                .limit(self._normalize_page_size(query.page_size))
            ).all()
        )
        return AdminUserPage(
            users=[self._build_user_snapshot(user) for user in users],
            page_size=query.page_size,
            offset=query.offset,
            total=total,
        )

    def get_user(self, subject_id: str) -> AdminUserSnapshot:
        """
        读取用户详情。
        """

        user = self._get_user_row(subject_id)
        if user is None:
            self._raise_not_found(USER_NOT_FOUND_MESSAGE)
        return self._build_user_snapshot(user)

    def create_user(
        self,
        *,
        command: AdminUserCreateCommand,
        password_hash: str,
    ) -> AdminUserSnapshot:
        """
        创建用户。
        """

        subject_id = command.subject_id or self._build_subject_id()
        if (
            self._get_user_row(subject_id) is not None
            or self._get_user_row_by_username(command.username) is not None
        ):
            self._raise_conflict(USER_ALREADY_EXISTS_MESSAGE)
        role_models = self._get_required_business_role_rows(command.role_keys)
        user = AuthUserOrmModel(
            subject_id=subject_id,
            username=command.username,
            password_hash=password_hash,
            is_active=True,
        )
        self._session.add(user)
        self._session.flush()
        self._replace_user_role_rows(user=user, role_models=role_models)
        self._session.flush()
        return self.get_user(subject_id)

    def create_initial_admin_user(
        self,
        *,
        username: str,
        password_hash: str,
        subject_id: str | None,
    ) -> InitialAdminCreateResult:
        """
        仅当不存在任何 admin 用户时创建首个管理员。
        """

        self._lock_user_table_for_initial_admin()
        locked_existing_admin = self._get_any_admin_user_for_update()
        if locked_existing_admin is not None:
            existing_user = self._get_user_row_by_username(username)
            return InitialAdminCreateResult(
                created=False,
                subject_id=(existing_user.subject_id if existing_user is not None else None),
                reason=(
                    InitialAdminCreateReason.ALREADY_EXISTS
                    if existing_user is not None
                    and existing_user.subject_id == locked_existing_admin.subject_id
                    else InitialAdminCreateReason.ADMIN_EXISTS
                ),
            )
        existing_username_user = self._get_user_row_by_username(username)
        if existing_username_user is not None:
            return InitialAdminCreateResult(
                created=False,
                subject_id=existing_username_user.subject_id,
                reason=InitialAdminCreateReason.ADMIN_EXISTS,
            )
        resolved_subject_id = subject_id or self._build_initial_admin_subject_id()
        if self._get_user_row(resolved_subject_id) is not None:
            return InitialAdminCreateResult(
                created=False,
                subject_id=resolved_subject_id,
                reason=InitialAdminCreateReason.ADMIN_EXISTS,
            )
        self._ensure_admin_role_catalog()
        admin_role = self._get_role_row(ADMIN_ROLE_KEY)
        if admin_role is None:
            self._raise_invalid(ROLE_DISABLED_OR_MISSING_MESSAGE)
        user = AuthUserOrmModel(
            subject_id=resolved_subject_id,
            username=username,
            password_hash=password_hash,
            is_active=True,
        )
        self._session.add(user)
        self._session.flush()
        self._replace_user_role_rows(user=user, role_models=[admin_role])
        self._session.flush()
        return InitialAdminCreateResult(
            created=True,
            subject_id=resolved_subject_id,
            reason=InitialAdminCreateReason.CREATED,
        )

    def update_user(self, command: AdminUserUpdateCommand) -> AdminUserSnapshot:
        """
        更新用户。
        """

        user = self._get_user_row(command.subject_id)
        if user is None:
            self._raise_not_found(USER_NOT_FOUND_MESSAGE)
        if command.username is not None and command.username != user.username:
            existing = self._get_user_row_by_username(command.username)
            if existing is not None:
                self._raise_conflict(USER_ALREADY_EXISTS_MESSAGE)
            user.username = command.username
        if command.is_active is False and command.actor_subject_id == user.subject_id:
            self._raise_self_lock()
        if command.is_active is False:
            self._lock_user_table_for_admin_access_invariant()
        if command.is_active is not None:
            user.is_active = command.is_active
        self._session.flush()
        if command.is_active is False:
            self._assert_admin_access_invariant()
        return self.get_user(command.subject_id)

    def reset_user_password(
        self,
        *,
        command: AdminUserPasswordResetCommand,
        password_hash: str,
    ) -> AdminUserSnapshot:
        """
        重置用户密码。
        """

        user = self._get_user_row(command.subject_id)
        if user is None:
            self._raise_not_found(USER_NOT_FOUND_MESSAGE)
        if command.actor_subject_id == user.subject_id:
            self._raise_invalid(PASSWORD_RESET_SELF_BLOCKED_MESSAGE)
        actor = self._get_user_row(command.actor_subject_id)
        if actor is None:
            self._raise_not_found(USER_NOT_FOUND_MESSAGE)
        if self._user_has_admin_manage_capability(
            user=actor
        ) and self._user_has_admin_manage_capability(user=user):
            self._raise_invalid(PASSWORD_RESET_PEER_ADMIN_BLOCKED_MESSAGE)
        if self._user_is_protected_password_reset_target(
            user=user
        ) and not self._user_has_admin_grant_capability(user=actor):
            self._raise_invalid(PASSWORD_RESET_PROTECTED_TARGET_BLOCKED_MESSAGE)
        user.password_hash = password_hash
        self._session.flush()
        return self.get_user(command.subject_id)

    def replace_user_roles(
        self,
        command: AdminUserRoleReplaceCommand,
    ) -> AdminUserSnapshot:
        """
        替换用户角色。
        """

        user = self._get_user_row(command.subject_id)
        if user is None:
            self._raise_not_found(USER_NOT_FOUND_MESSAGE)
        role_models = self._get_required_business_role_rows(command.role_keys)
        if command.actor_subject_id == user.subject_id and not self._role_models_retain_manage(
            user=user,
            role_models=role_models,
        ):
            self._raise_self_lock()
        self._lock_user_table_for_admin_access_invariant()
        self._replace_user_role_rows(user=user, role_models=role_models)
        self._session.flush()
        self._assert_admin_access_invariant()
        return self.get_user(command.subject_id)

    def replace_user_scopes(
        self,
        command: AdminUserScopeReplaceCommand,
    ) -> AdminUserSnapshot:
        """替换用户直接 scope。"""

        user = self._get_user_row(command.subject_id)
        if user is None:
            self._raise_not_found(USER_NOT_FOUND_MESSAGE)
        scope_codes = self._normalize_unique_values(command.scope_codes)
        self._validate_scope_codes_enabled(scope_codes)
        if command.actor_subject_id == user.subject_id and not self._scope_codes_retain_manage(
            user=user,
            direct_scope_codes=scope_codes,
        ):
            self._raise_self_lock()
        self._lock_user_table_for_admin_access_invariant()
        self._replace_user_scope_rows(user=user, scope_codes=scope_codes)
        self._session.flush()
        self._assert_admin_access_invariant()
        return self.get_user(command.subject_id)

    def disable_user(self, command: AdminUserDeleteCommand) -> AdminIdentityDeleteResult:
        """
        停用用户。
        """

        user = self._get_user_row(command.subject_id)
        if user is None:
            self._raise_not_found(USER_NOT_FOUND_MESSAGE)
        if command.actor_subject_id == user.subject_id:
            self._raise_self_lock()
        self._lock_user_table_for_admin_access_invariant()
        user.is_active = False
        self._session.flush()
        self._assert_admin_access_invariant()
        return AdminIdentityDeleteResult(
            target_id=command.subject_id,
            deleted=True,
            reason=command.reason or ADMIN_IDENTITY_DISABLED_STATUS,
        )

    def _build_user_statement(self) -> Select[tuple[AuthUserOrmModel]]:
        """
        构建用户查询语句。
        """

        return select(AuthUserOrmModel).options(
            selectinload(AuthUserOrmModel.user_roles)
            .selectinload(AuthUserRoleOrmModel.role)
            .selectinload(AuthRoleOrmModel.role_scopes),
            selectinload(AuthUserOrmModel.user_scopes),
        )

    def _build_user_list_statement(
        self,
        query: AdminUserListQuery,
    ) -> Select[tuple[AuthUserOrmModel]]:
        """
        构建用户列表查询语句。
        """

        statement = self._build_user_statement()
        if query.is_active is not None:
            statement = statement.where(AuthUserOrmModel.is_active == query.is_active)
        if query.keyword is not None:
            keyword = self._build_like_keyword(query.keyword)
            statement = statement.where(
                AuthUserOrmModel.subject_id.ilike(keyword)
                | AuthUserOrmModel.username.ilike(keyword)
            )
        if query.role_key is not None:
            statement = (
                statement.join(AuthUserOrmModel.user_roles)
                .join(AuthUserRoleOrmModel.role)
                .where(AuthRoleOrmModel.role_key == query.role_key)
            )
        return statement

    def _build_role_count_statement(
        self,
        statement: Select[tuple[AuthRoleOrmModel]],
    ) -> Select[tuple[int]]:
        """
        构建角色列表统计语句。
        """

        return select(func.count()).select_from(statement.subquery())

    def _build_user_count_statement(
        self,
        statement: Select[tuple[AuthUserOrmModel]],
    ) -> Select[tuple[int]]:
        """
        构建用户列表统计语句。
        """

        return select(func.count()).select_from(statement.subquery())

    def _get_user_row(self, subject_id: str) -> AuthUserOrmModel | None:
        """
        读取用户 ORM 行。
        """

        statement = self._build_user_statement().where(AuthUserOrmModel.subject_id == subject_id)
        return self._session.scalars(statement).one_or_none()

    def _get_user_row_by_username(self, username: str) -> AuthUserOrmModel | None:
        """
        按用户名读取用户 ORM 行。
        """

        statement = self._build_user_statement().where(AuthUserOrmModel.username == username)
        return self._session.scalars(statement).one_or_none()

    def _get_any_admin_user_for_update(self) -> AuthUserOrmModel | None:
        """
        读取任意已绑定 admin 角色的用户并加锁。
        """

        statement = (
            self._build_user_statement()
            .join(AuthUserOrmModel.user_roles)
            .join(AuthUserRoleOrmModel.role)
            .where(AuthRoleOrmModel.role_key == ADMIN_ROLE_KEY)
            .order_by(AuthUserOrmModel.subject_id.asc())
            .limit(1)
            .with_for_update()
        )
        return self._session.scalars(statement).first()

    def _lock_user_table_for_initial_admin(self) -> None:
        """
        锁定用户表，保证首个管理员检查与创建在事务内串行化。
        """

        self._lock_user_table()

    def _lock_user_table_for_admin_access_invariant(self) -> None:
        """
        锁定用户表，保证管理员存活不变量检查与写入处于同一事务。
        """

        self._lock_user_table()

    def _lock_user_table(self) -> None:
        """在支持显式表锁的生产方言中锁定管理员用户表。"""

        bind = self._session.get_bind()
        if bind.dialect.name == DatabaseDialect.SQLITE:
            return
        self._session.execute(text(AUTH_USER_TABLE_LOCK_SQL))

    def _ensure_admin_role_catalog(self) -> None:
        """
        确保首个管理员依赖的内置 scope 与 admin 角色存在。
        """

        self.sync_scope_catalog(list(ADMIN_ROLE_SCOPE_CODES))
        role = self._get_role_row(ADMIN_ROLE_KEY)
        if role is None:
            role = AuthRoleOrmModel(
                role_key=ADMIN_ROLE_KEY,
                role_name=ADMIN_ROLE_NAME,
            )
            self._session.add(role)
            self._session.flush()
        else:
            role.role_name = ADMIN_ROLE_NAME
        self._replace_role_scope_rows(
            role=role,
            scope_codes=list(ADMIN_ROLE_SCOPE_CODES),
        )
        self._session.flush()

    def _build_user_snapshot(self, user: AuthUserOrmModel) -> AdminUserSnapshot:
        """
        构建用户快照。
        """

        role_keys = [
            user_role.role.role_key for user_role in user.user_roles if user_role.role is not None
        ]
        role_scope_codes = [
            role_scope.scope_code
            for user_role in user.user_roles
            if user_role.role is not None
            for role_scope in user_role.role.role_scopes
        ]
        direct_scope_codes = [user_scope.scope_code for user_scope in user.user_scopes]
        effective_scope_codes = [*role_scope_codes, *direct_scope_codes]
        return AdminUserSnapshot(
            subject_id=user.subject_id,
            username=user.username,
            is_active=user.is_active,
            role_keys=sorted(self._normalize_unique_values(role_keys)),
            direct_scope_codes=sorted(self._normalize_unique_values(direct_scope_codes)),
            effective_scope_codes=sorted(
                scope_code
                for scope_code in self._normalize_unique_values(effective_scope_codes)
                if self._is_scope_code_enabled(scope_code)
            ),
        )

    def _replace_user_role_rows(
        self,
        *,
        user: AuthUserOrmModel,
        role_models: list[AuthRoleOrmModel],
    ) -> None:
        """
        替换用户角色关联。
        """

        user.user_roles[:] = [
            AuthUserRoleOrmModel(role=role)
            for role in sorted(role_models, key=lambda role: role.role_key)
        ]

    def _replace_user_scope_rows(
        self,
        *,
        user: AuthUserOrmModel,
        scope_codes: list[str],
    ) -> None:
        """替换用户直接 scope 关联。"""

        user.user_scopes[:] = [
            AuthUserScopeOrmModel(scope_code=scope_code) for scope_code in sorted(scope_codes)
        ]

    def _matches_user_query(
        self,
        *,
        snapshot: AdminUserSnapshot,
        query: AdminUserListQuery,
    ) -> bool:
        """
        判断用户是否命中查询条件。
        """

        if query.role_key is not None and query.role_key not in snapshot.role_keys:
            return False
        if query.keyword is None:
            return True
        keyword = query.keyword.lower()
        return keyword in snapshot.subject_id.lower() or keyword in snapshot.username.lower()

    def _build_subject_id(self) -> str:
        """
        构建用户主体标识。
        """

        return f"{ADMIN_IDENTITY_USER_SUBJECT_PREFIX}{ADMIN_IDENTITY_SUBJECT_SEPARATOR}{uuid4()}"

    def _build_initial_admin_subject_id(self) -> str:
        """
        构建初始管理员主体标识。
        """

        return f"{INITIAL_ADMIN_DEFAULT_SUBJECT_PREFIX}{ADMIN_IDENTITY_SUBJECT_SEPARATOR}{uuid4()}"
