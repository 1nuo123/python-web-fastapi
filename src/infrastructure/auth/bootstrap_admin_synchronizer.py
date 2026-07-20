"""
引导管理员同步器基础设施模块。
"""

from __future__ import annotations

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from src.application.ports.admin_identity_port import AdminScopeKind, BusinessAdminRoleKey
from src.core.auth_contract.bootstrap_role_binding_contract import BootstrapRoleBinding
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.auth.password_hasher import PasswordHasher
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_role_scope_orm_model import (
    AuthRoleScopeOrmModel,
)
from src.infrastructure.persistence.orm_model.auth_scope_orm_model import AuthScopeOrmModel
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.auth_user_role_orm_model import (
    AuthUserRoleOrmModel,
)
from src.infrastructure.settings.application_settings import BootstrapAdminSettings

BOOTSTRAP_ADMIN_FIELDS_REQUIRED_MESSAGE = "启用初始管理员同步时必须提供主体、用户名和密码。"

BOOTSTRAP_BUSINESS_ROLE_SEED_KEYS: frozenset[str] = frozenset(
    role_key.value for role_key in BusinessAdminRoleKey
)


class BootstrapAdminSynchronizer:
    """
    引导管理员同步器类型，用于封装当前模块中的相关行为或状态。
    """

    def __init__(self, *, password_hasher: PasswordHasher) -> None:
        """
        初始化引导管理员同步器。

        :param password_hasher: 当前步骤使用的密码哈希器参数。约束：需符合 ``PasswordHasher`` 注解。
        :type password_hasher: PasswordHasher
        :returns: 无返回值。
        :rtype: None
        """

        self._password_hasher = password_hasher

    def synchronize(
        self,
        *,
        session: Session,
        bootstrap_admin: BootstrapAdminSettings,
    ) -> None:
        """
        处理同步。

        :param session: 当前数据库会话，生命周期由工作单元控制。约束：需符合 ``Session`` 注解。
        :type session: Session
        :param bootstrap_admin: 当前步骤使用的引导管理员参数。约束：需符合 ``BootstrapAdminSettings`` 注解。
        :type bootstrap_admin: BootstrapAdminSettings
        :returns: 无返回值。
        :rtype: None
        """

        subject_id = bootstrap_admin.subject_id
        username = bootstrap_admin.username
        password_secret = bootstrap_admin.password_plain
        if subject_id is None or username is None or password_secret is None:
            raise ValueError(BOOTSTRAP_ADMIN_FIELDS_REQUIRED_MESSAGE)
        user = self._get_bootstrap_user(session, username)
        password_plain = password_secret.get_secret_value()
        if user is None:
            user = AuthUserOrmModel(
                subject_id=subject_id,
                username=username,
                password_hash=self._password_hasher.hash_password(password_plain),
                is_active=True,
            )
            session.add(user)
            session.flush()
        self._synchronize_bootstrap_user(
            user=user,
            subject_id=subject_id,
            username=username,
            password_plain=password_plain,
        )
        self._synchronize_scope_catalog(
            session=session,
            role_bindings=bootstrap_admin.role_bindings,
        )
        role_models = self._synchronize_bootstrap_roles(
            session=session,
            role_bindings=bootstrap_admin.role_bindings,
        )
        self._synchronize_bootstrap_user_roles(user=user, role_models=role_models)

    def _get_bootstrap_user(
        self,
        session: Session,
        username: str,
    ) -> AuthUserOrmModel | None:
        """
        获取引导用户。

        :param session: 当前数据库会话，生命周期由工作单元控制。约束：需符合 ``Session`` 注解。
        :type session: Session
        :param username: 当前步骤使用的用户名参数。约束：需符合 ``str`` 注解。
        :type username: str
        :returns: 返回当前操作结果。
        :rtype: AuthUserOrmModel | None
        """

        statement = select(AuthUserOrmModel).where(AuthUserOrmModel.username == username)
        return session.scalars(statement).one_or_none()

    def _synchronize_scope_catalog(
        self,
        *,
        session: Session,
        role_bindings: list[BootstrapRoleBinding],
    ) -> None:
        """
        同步引导角色涉及的 scope 目录。

        :param session: 当前数据库会话，生命周期由工作单元控制。
        :type session: Session
        :param role_bindings: 角色绑定集合。
        :type role_bindings: list[BootstrapRoleBinding]
        :returns: 无返回值。
        :rtype: None
        """

        scope_codes = list(
            dict.fromkeys(
                [scope.value for scope in AuthScopeCode]
                + [
                    scope_code
                    for role_binding in role_bindings
                    for scope_code in role_binding.scope_codes
                ]
            )
        )
        existing_scopes = {
            scope.scope_code
            for scope in session.scalars(
                select(AuthScopeOrmModel).where(AuthScopeOrmModel.scope_code.in_(scope_codes))
            ).all()
        }
        for scope_code in scope_codes:
            if scope_code in existing_scopes:
                continue
            session.add(
                AuthScopeOrmModel(
                    scope_code=scope_code,
                    scope_name=scope_code,
                    description=None,
                    scope_kind=self._resolve_scope_kind(scope_code).value,
                    enabled=True,
                )
            )

    def _resolve_scope_kind(self, scope_code: str) -> AdminScopeKind:
        """
        解析 scope 类型。

        :param scope_code: scope 编码。
        :type scope_code: str
        :returns: scope 类型。
        :rtype: AdminScopeKind
        """

        if scope_code in {scope.value for scope in AuthScopeCode}:
            return AdminScopeKind.BUILTIN
        return AdminScopeKind.CUSTOM

    def _synchronize_bootstrap_user(
        self,
        *,
        user: AuthUserOrmModel,
        subject_id: str,
        username: str,
        password_plain: str,
    ) -> None:
        """
        同步引导用户。

        :param user: 当前步骤使用的用户参数。约束：需符合 ``AuthUserOrmModel`` 注解。
        :type user: AuthUserOrmModel
        :param subject_id: 初始管理员主体标识。
        :type subject_id: str
        :param username: 初始管理员用户名。
        :type username: str
        :param password_plain: 明文密码，仅在当前调用链中短暂使用。约束：需符合 ``str`` 注解。
        :type password_plain: str
        :returns: 无返回值。
        :rtype: None
        """

        user.subject_id = subject_id
        user.username = username
        if not self._password_hasher.verify_password(password_plain, user.password_hash):
            user.password_hash = self._password_hasher.hash_password(password_plain)
        elif self._password_hasher.needs_rehash(user.password_hash):
            user.password_hash = self._password_hasher.hash_password(password_plain)
        user.is_active = True

    def _build_role_statement(
        self,
        role_keys: list[str],
    ) -> Select[tuple[AuthRoleOrmModel]]:
        """
        构建角色声明。

        :param role_keys: 角色键列表。约束：需符合 ``list[str]`` 注解。
        :type role_keys: list[str]
        :returns: 返回当前操作结果。
        :rtype: Select[tuple[AuthRoleOrmModel]]
        """

        return select(AuthRoleOrmModel).where(AuthRoleOrmModel.role_key.in_(role_keys))

    def _synchronize_bootstrap_roles(
        self,
        *,
        session: Session,
        role_bindings: list[BootstrapRoleBinding],
    ) -> list[AuthRoleOrmModel]:
        """
        同步引导角色集合。

        :param session: 当前数据库会话，生命周期由工作单元控制。约束：需符合 ``Session`` 注解。
        :type session: Session
        :param role_bindings: 角色绑定集合。约束：需符合 ``list[BootstrapRoleBinding]`` 注解。
        :type role_bindings: list[BootstrapRoleBinding]
        :returns: 返回按实现构造的列表结果。
        :rtype: list[AuthRoleOrmModel]
        """

        role_keys = [role_binding.role_key for role_binding in role_bindings]
        existing_roles = {
            role.role_key: role
            for role in session.scalars(self._build_role_statement(role_keys)).all()
        }
        resolved_roles: list[AuthRoleOrmModel] = []
        for role_binding in role_bindings:
            role = existing_roles.get(role_binding.role_key)
            if role is None:
                role = AuthRoleOrmModel(
                    role_key=role_binding.role_key,
                    role_name=role_binding.role_key,
                )
                session.add(role)
                session.flush()
            role.role_name = role_binding.role_key
            self._synchronize_role_scopes(
                role=role,
                scope_codes=role_binding.scope_codes,
            )
            resolved_roles.append(role)
        return resolved_roles

    def _synchronize_role_scopes(
        self,
        *,
        role: AuthRoleOrmModel,
        scope_codes: list[str],
    ) -> None:
        """
        同步角色作用域集合。

        :param role: 角色对象。约束：需符合 ``AuthRoleOrmModel`` 注解。
        :type role: AuthRoleOrmModel
        :param scope_codes: 作用域编码列表。约束：需符合 ``list[str]`` 注解。
        :type scope_codes: list[str]
        :returns: 无返回值。
        :rtype: None
        """

        target_scope_codes = set(scope_codes)
        current_scope_codes = {role_scope.scope_code for role_scope in role.role_scopes}
        for scope_code in target_scope_codes - current_scope_codes:
            role.role_scopes.append(AuthRoleScopeOrmModel(scope_code=scope_code))
        role.role_scopes[:] = [
            role_scope
            for role_scope in role.role_scopes
            if role_scope.scope_code in target_scope_codes
        ]

    def _synchronize_bootstrap_user_roles(
        self,
        *,
        user: AuthUserOrmModel,
        role_models: list[AuthRoleOrmModel],
    ) -> None:
        """
        同步引导用户角色集合。

        :param user: 当前步骤使用的用户参数。约束：需符合 ``AuthUserOrmModel`` 注解。
        :type user: AuthUserOrmModel
        :param role_models: 角色 ORM 模型列表。约束：需符合 ``list[AuthRoleOrmModel]`` 注解。
        :type role_models: list[AuthRoleOrmModel]
        :returns: 无返回值。
        :rtype: None
        """

        assigned_role_models = [
            role for role in role_models if role.role_key not in BOOTSTRAP_BUSINESS_ROLE_SEED_KEYS
        ]
        target_role_ids = {role.role_id for role in assigned_role_models}
        current_role_ids = {user_role.role_id for user_role in user.user_roles}
        for role in assigned_role_models:
            if role.role_id in current_role_ids:
                continue
            user.user_roles.append(AuthUserRoleOrmModel(role=role))
        user.user_roles[:] = [
            user_role for user_role in user.user_roles if user_role.role.role_id in target_role_ids
        ]
