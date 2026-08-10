"""管理员身份仓储公共支持。"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING, NoReturn

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from src.application.admin.identity.shared.admin_identity_command import (
    AdminScopeUpdateCommand,
)
from src.application.ports.admin_identity_port import (
    ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM,
    ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM,
    AdminScopeSnapshot,
    BusinessAdminRoleKey,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.persistence_contract.repository_contract import Repository
from src.domain.auth.admin_identity_error_code import AdminIdentityErrorCode
from src.domain.auth.admin_route_authorization_policy import (
    PROTECTED_ADMIN_SCOPE_CODES,
)
from src.domain.auth.auth_role_key import AuthRoleKey
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.auth_user_role_orm_model import (
    AuthUserRoleOrmModel,
)

ADMIN_IDENTITY_USER_SUBJECT_PREFIX = "user"

ADMIN_IDENTITY_SUBJECT_SEPARATOR = "-"

SCOPE_ALREADY_EXISTS_MESSAGE = "scope 编码已存在。"

SCOPE_NOT_FOUND_MESSAGE = "scope 不存在。"

BUILTIN_SCOPE_DELETE_BLOCKED_MESSAGE = "内置 scope 不允许删除。"

BUILTIN_SCOPE_DISABLE_BLOCKED_MESSAGE = "内置授权 scope 不允许禁用。"

BOUND_SCOPE_DELETE_BLOCKED_MESSAGE = "已绑定角色的 scope 不允许删除。"

SCOPE_DISABLED_OR_MISSING_MESSAGE = "scope 不存在或未启用。"

ROLE_ALREADY_EXISTS_MESSAGE = "角色键已存在。"

ROLE_NOT_FOUND_MESSAGE = "角色不存在。"

BUILTIN_ADMIN_ROLE_DELETE_BLOCKED_MESSAGE = "内置 admin 角色不允许删除。"

BOUND_ROLE_DELETE_BLOCKED_MESSAGE = "已绑定用户的角色不允许删除。"

USER_ALREADY_EXISTS_MESSAGE = "用户名或主体标识已存在。"

USER_NOT_FOUND_MESSAGE = "用户不存在。"

ROLE_DISABLED_OR_MISSING_MESSAGE = "角色不存在。"

BUSINESS_ROLE_REQUIRED_MESSAGE = "只能分配预定义业务角色。"

SELF_LOCK_BLOCKED_MESSAGE = "禁止移除自己的最后一个 admin + auth:manage 能力。"

ADMIN_ACCESS_INVARIANT_BLOCKED_MESSAGE = "系统必须保留至少一个 active admin + auth:manage 管理员。"

PASSWORD_RESET_SELF_BLOCKED_MESSAGE = "禁止管理员重置自己的密码。"

PASSWORD_RESET_PEER_ADMIN_BLOCKED_MESSAGE = "禁止管理员重置同级管理员密码。"

ROLE_CREATE_PROTECTED_SCOPE_BLOCKED_MESSAGE = (
    "创建包含受保护后台 scope 的角色必须完成高危授权确认。"
)

PASSWORD_RESET_PROTECTED_TARGET_BLOCKED_MESSAGE = "低权限管理员不允许重置高权限管理员密码。"

DELETE_ACCEPTED_REASON = "停用完成。"

ADMIN_IDENTITY_DISABLED_STATUS = "disabled"

INITIAL_ADMIN_DEFAULT_SUBJECT_PREFIX = "initial-admin"

ADMIN_ROLE_NAME = "admin"

AUTH_USER_TABLE_LOCK_SQL = "LOCK TABLE auth_user IN SHARE ROW EXCLUSIVE MODE"

BUSINESS_ADMIN_ROLE_KEYS: tuple[str, ...] = tuple(
    role_key.value for role_key in BusinessAdminRoleKey
)

ADMIN_MANAGE_SCOPE_CODE = AuthScopeCode.AUTH_MANAGE.value

ADMIN_GRANT_SCOPE_CODE = AuthScopeCode.AUTH_GRANT_ADMIN.value

ADMIN_ROLE_KEY = AuthRoleKey.ADMIN.value

REGISTERED_USER_ROLE_KEY = AuthRoleKey.REGISTERED_USER.value

REGISTERED_USER_ROLE_CHANGE_BLOCKED_MESSAGE = "普通注册用户角色不允许修改或删除。"

ADMIN_ROLE_SCOPE_CODES: tuple[str, ...] = tuple(scope.value for scope in AuthScopeCode)


class AdminIdentityRepositorySupport(Repository):
    """管理员身份仓储公共查询与不变式支持。"""

    def __init__(self, session: Session) -> None:
        """
        初始化管理员身份仓储。

        :param session: 当前数据库会话，生命周期由工作单元控制。
        :type session: Session
        :returns: 无返回值。
        :rtype: None
        """

        self._session = session

    if TYPE_CHECKING:

        def _build_role_statement(self) -> Select[tuple[AuthRoleOrmModel]]:
            """声明角色查询协作边界。"""

        def _get_scope_snapshot_or_none(
            self,
            scope_code: str,
        ) -> AdminScopeSnapshot | None:
            """声明 scope 查询协作边界。"""

        def _get_user_row(self, subject_id: str) -> AuthUserOrmModel | None:
            """声明用户查询协作边界。"""

        def _build_user_statement(self) -> Select[tuple[AuthUserOrmModel]]:
            """声明用户语句协作边界。"""

        def _get_role_row(self, role_key: str) -> AuthRoleOrmModel | None:
            """声明角色行查询协作边界。"""

        def sync_scope_catalog(self, scope_codes: list[str]) -> None:
            """声明 scope 目录同步协作边界。"""

        def _replace_role_scope_rows(
            self,
            *,
            role: AuthRoleOrmModel,
            scope_codes: list[str],
        ) -> None:
            """声明角色 scope 替换协作边界。"""

        def _build_role_count_statement(
            self,
            statement: Select[tuple[AuthRoleOrmModel]],
        ) -> Select[tuple[int]]:
            """声明角色计数协作边界。"""

        def _lock_user_table_for_admin_access_invariant(self) -> None:
            """声明管理员不变式锁协作边界。"""

    def ping(self) -> bool:
        """
        探测管理员身份仓储依赖是否可用。

        :returns: ``True`` 表示当前数据库会话可执行基础查询。
        :rtype: bool
        """

        self._session.execute(select(1))
        return True

    def _get_required_role_rows(self, role_keys: list[str]) -> list[AuthRoleOrmModel]:
        """
        读取并校验角色集合。
        """

        normalized_role_keys = self._normalize_unique_values(role_keys)
        statement = self._build_role_statement().where(
            AuthRoleOrmModel.role_key.in_(normalized_role_keys)
        )
        roles = list(self._session.scalars(statement).all())
        if len(roles) != len(normalized_role_keys):
            self._raise_invalid(ROLE_DISABLED_OR_MISSING_MESSAGE)
        return roles

    def _get_required_business_role_rows(
        self,
        role_keys: list[str],
    ) -> list[AuthRoleOrmModel]:
        """
        读取并校验预定义业务角色集合。
        """

        normalized_role_keys = self._normalize_unique_values(role_keys)
        if any(role_key not in BUSINESS_ADMIN_ROLE_KEYS for role_key in normalized_role_keys):
            self._raise_invalid(BUSINESS_ROLE_REQUIRED_MESSAGE)
        return self._get_required_role_rows(normalized_role_keys)

    def _validate_scope_codes_enabled(self, scope_codes: list[str]) -> None:
        """
        校验 scope 均存在且启用。
        """

        for scope_code in self._normalize_unique_values(scope_codes):
            snapshot = self._get_scope_snapshot_or_none(scope_code)
            if snapshot is None or not snapshot.enabled:
                self._raise_invalid(SCOPE_DISABLED_OR_MISSING_MESSAGE)

    def _validate_actor_after_role_scope_change(
        self,
        *,
        actor_subject_id: str,
        target_role_key: str,
        next_scope_codes: list[str],
    ) -> None:
        """
        校验角色 scope 变更不会让操作者自锁。
        """

        actor = self._get_user_row(actor_subject_id)
        if actor is None:
            return
        actor_role_keys = [
            user_role.role.role_key for user_role in actor.user_roles if user_role.role is not None
        ]
        if target_role_key not in actor_role_keys:
            return
        future_scope_codes = [
            role_scope.scope_code
            for user_role in actor.user_roles
            if user_role.role is not None and user_role.role.role_key != target_role_key
            for role_scope in user_role.role.role_scopes
        ]
        future_scope_codes.extend(next_scope_codes)
        if ADMIN_ROLE_KEY not in actor_role_keys:
            self._raise_self_lock()
        if ADMIN_MANAGE_SCOPE_CODE not in set(future_scope_codes):
            self._raise_self_lock()

    def _validate_actor_after_scope_change(
        self,
        *,
        command: AdminScopeUpdateCommand,
    ) -> None:
        """
        校验 scope 状态变更不会让操作者自锁。
        """

        if command.enabled is not False:
            return
        actor = self._get_user_row(command.actor_subject_id)
        if actor is None:
            return
        if not self._user_has_admin_manage_capability_excluding_scope(
            user=actor,
            excluded_scope_code=command.scope_code,
        ):
            self._raise_self_lock()

    def _user_has_admin_manage_capability_excluding_scope(
        self,
        *,
        user: AuthUserOrmModel,
        excluded_scope_code: str,
    ) -> bool:
        """
        判断用户在排除指定 scope 后是否仍有管理员管理能力。
        """

        return any(
            user_role.role is not None
            and user_role.role.role_key == ADMIN_ROLE_KEY
            and any(
                role_scope.scope_code == ADMIN_MANAGE_SCOPE_CODE
                and role_scope.scope_code != excluded_scope_code
                and self._is_scope_code_enabled(role_scope.scope_code)
                for role_scope in user_role.role.role_scopes
            )
            for user_role in user.user_roles
        )

    def _assert_admin_access_invariant(self) -> None:
        """
        断言系统内仍存在 active admin + auth:manage 管理员。
        """

        statement = (
            self._build_user_statement()
            .join(AuthUserOrmModel.user_roles)
            .join(AuthUserRoleOrmModel.role)
            .where(AuthUserOrmModel.is_active.is_(True))
            .where(AuthRoleOrmModel.role_key == ADMIN_ROLE_KEY)
        )
        users = list(self._session.scalars(statement).unique().all())
        if any(self._user_has_admin_manage_capability(user=user) for user in users):
            return
        self._raise_admin_access_invariant_blocked()

    def _user_has_admin_manage_capability(self, *, user: AuthUserOrmModel) -> bool:
        """
        判断用户是否具有当前有效的 admin + auth:manage 能力。
        """

        return any(
            user_role.role is not None
            and user_role.role.role_key == ADMIN_ROLE_KEY
            and any(
                role_scope.scope_code == ADMIN_MANAGE_SCOPE_CODE
                and self._is_scope_code_enabled(role_scope.scope_code)
                for role_scope in user_role.role.role_scopes
            )
            for user_role in user.user_roles
        )

    def _user_has_admin_grant_capability(self, *, user: AuthUserOrmModel) -> bool:
        """
        判断用户是否具有当前有效的授权变更能力。
        """

        return self._user_has_enabled_scope(
            user=user,
            scope_code=ADMIN_GRANT_SCOPE_CODE,
        )

    def _user_is_protected_password_reset_target(
        self,
        *,
        user: AuthUserOrmModel,
    ) -> bool:
        """
        判断用户是否属于密码重置高权限目标。
        """

        return self._user_has_role(user=user, role_key=ADMIN_ROLE_KEY) or (
            self._user_has_admin_grant_capability(user=user)
        )

    def _user_has_role(self, *, user: AuthUserOrmModel, role_key: str) -> bool:
        """
        判断用户是否绑定指定角色。
        """

        return any(
            user_role.role is not None and user_role.role.role_key == role_key
            for user_role in user.user_roles
        )

    def _user_has_enabled_scope(
        self,
        *,
        user: AuthUserOrmModel,
        scope_code: str,
    ) -> bool:
        """
        判断用户是否拥有当前有效的指定 scope。
        """

        return any(
            user_role.role is not None
            and any(
                role_scope.scope_code == scope_code
                and self._is_scope_code_enabled(role_scope.scope_code)
                for role_scope in user_role.role.role_scopes
            )
            for user_role in user.user_roles
        )

    def _scope_codes_contain_protected_admin_scope(
        self,
        scope_codes: list[str],
    ) -> bool:
        """
        判断 scope 集合是否包含受保护后台权限。
        """

        return any(scope_code in PROTECTED_ADMIN_SCOPE_CODES for scope_code in scope_codes)

    def _is_scope_code_enabled(self, scope_code: str) -> bool:
        """
        判断 scope 当前是否有效。
        """

        scope = self._get_scope_snapshot_or_none(scope_code)
        return scope is not None and scope.enabled

    def _role_models_grant_manage(self, role_models: list[AuthRoleOrmModel]) -> bool:
        """
        判断角色集合是否保留管理员管理能力。
        """

        role_keys = {role.role_key for role in role_models}
        scope_codes = {
            role_scope.scope_code for role in role_models for role_scope in role.role_scopes
        }
        return ADMIN_ROLE_KEY in role_keys and ADMIN_MANAGE_SCOPE_CODE in scope_codes

    def _normalize_unique_values(self, values: list[str]) -> list[str]:
        """
        归一化并去重字符串集合。
        """

        return list(dict.fromkeys(value.strip() for value in values))

    def _normalize_page_size(self, page_size: int) -> int:
        """
        归一化分页大小。
        """

        if page_size < ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM:
            return ADMIN_IDENTITY_QUERY_LIMIT_MINIMUM
        return min(page_size, ADMIN_IDENTITY_QUERY_LIMIT_MAXIMUM)

    def _build_like_keyword(self, keyword: str) -> str:
        """
        构建 SQL 模糊匹配关键字。
        """

        return f"%{keyword.strip()}%"

    def _raise_not_found(self, message: str) -> NoReturn:
        """
        抛出不存在异常。
        """

        raise HttpFaultException(
            status_code=HTTPStatus.NOT_FOUND,
            error_code=AdminIdentityErrorCode.NOT_FOUND,
            message=message,
        )

    def _raise_conflict(self, message: str) -> NoReturn:
        """
        抛出冲突异常。
        """

        raise HttpFaultException(
            status_code=HTTPStatus.CONFLICT,
            error_code=AdminIdentityErrorCode.CONFLICT,
            message=message,
        )

    def _raise_invalid(self, message: str) -> NoReturn:
        """
        抛出业务校验异常。
        """

        raise HttpFaultException(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            error_code=AdminIdentityErrorCode.INVALID,
            message=message,
        )

    def _raise_self_lock(self) -> None:
        """
        抛出自锁保护异常。
        """

        raise HttpFaultException(
            status_code=HTTPStatus.CONFLICT,
            error_code=AdminIdentityErrorCode.SELF_LOCK_BLOCKED,
            message=SELF_LOCK_BLOCKED_MESSAGE,
        )

    def _raise_admin_access_invariant_blocked(self) -> None:
        """
        抛出管理员存活不变量保护异常。
        """

        raise HttpFaultException(
            status_code=HTTPStatus.CONFLICT,
            error_code=AdminIdentityErrorCode.SELF_LOCK_BLOCKED,
            message=ADMIN_ACCESS_INVARIANT_BLOCKED_MESSAGE,
        )
