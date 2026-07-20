"""
鉴权身份仓储实现基础设施模块。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.orm import Session, selectinload

from src.core.auth_contract.auth_identity_authorization_snapshot_contract import (
    AuthIdentityAuthorizationSnapshot,
)
from src.core.auth_contract.auth_identity_status_contract import AuthIdentityStatusPayload
from src.core.persistence_contract.auth_identity_repository_contract import (
    AuthIdentityRepository,
    AuthIdentitySnapshot,
)
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_scope_orm_model import AuthScopeOrmModel
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.auth_user_role_orm_model import (
    AuthUserRoleOrmModel,
)


class AuthIdentityRepositoryImpl(AuthIdentityRepository):
    """
    鉴权身份仓储实现，负责提供持久化访问逻辑。
    """

    def __init__(self, session: Session) -> None:
        """
        初始化鉴权身份仓储实现。

        :param session: 当前数据库会话，生命周期由工作单元控制。约束：需符合 ``Session`` 注解。
        :type session: Session
        :returns: 无返回值。
        :rtype: None
        """

        self._session = session

    def ping(self) -> bool:
        """
        探测鉴权身份仓储依赖是否可用。

        :returns: ``True`` 表示当前数据库会话可执行基础查询。
        :rtype: bool
        """

        self._session.execute(select(1))
        return True

    def get_by_username(self, username: str) -> AuthIdentitySnapshot | None:
        """
        获取按用户名。

        :param username: 当前步骤使用的用户名参数。约束：需符合 ``str`` 注解。
        :type username: str
        :returns: 返回读取到的对象或状态快照。
        :rtype: AuthIdentitySnapshot | None
        """

        statement = self._build_user_statement().where(AuthUserOrmModel.username == username)
        user = self._session.scalars(statement).one_or_none()
        if user is None:
            return None
        return self._build_identity_snapshot(user)

    def get_by_subject_id(self, subject_id: str) -> AuthIdentitySnapshot | None:
        """
        获取按主体标识。

        :param subject_id: 认证主体标识。约束：需符合 ``str`` 注解。
        :type subject_id: str
        :returns: 返回读取到的对象或状态快照。
        :rtype: AuthIdentitySnapshot | None
        """

        statement = self._build_user_statement().where(AuthUserOrmModel.subject_id == subject_id)
        user = self._session.scalars(statement).one_or_none()
        if user is None:
            return None
        return self._build_identity_snapshot(user)

    def get_authorization_snapshot_by_subject_id(
        self,
        subject_id: str,
    ) -> AuthIdentityAuthorizationSnapshot | None:
        """
        获取授权快照按主体标识。

        :param subject_id: 认证主体标识。约束：需符合 ``str`` 注解。
        :type subject_id: str
        :returns: 返回读取到的对象或状态快照。
        :rtype: AuthIdentityAuthorizationSnapshot | None
        """

        identity_snapshot = self.get_by_subject_id(subject_id)
        if identity_snapshot is None:
            return None
        return AuthIdentityAuthorizationSnapshot(
            subject_id=identity_snapshot.subject_id,
            username=identity_snapshot.username,
            is_active=identity_snapshot.is_active,
            roles=identity_snapshot.roles,
            scopes=identity_snapshot.scopes,
        )

    def get_status_by_subject_id(
        self,
        subject_id: str,
    ) -> AuthIdentityStatusPayload | None:
        """
        获取状态按主体标识。

        :param subject_id: 认证主体标识。约束：需符合 ``str`` 注解。
        :type subject_id: str
        :returns: 返回读取到的对象或状态快照。
        :rtype: AuthIdentityStatusPayload | None
        """

        statement = select(
            AuthUserOrmModel.subject_id,
            AuthUserOrmModel.is_active,
        ).where(AuthUserOrmModel.subject_id == subject_id)
        row = self._session.execute(statement).one_or_none()
        if row is None:
            return None
        return AuthIdentityStatusPayload(
            subject_id=row.subject_id,
            is_active=row.is_active,
        )

    def update_password_hash(self, *, user_id: UUID, password_hash: str) -> None:
        """
        更新密码哈希。

        :param user_id: 用户主键标识。约束：需符合 ``UUID`` 注解。
        :type user_id: UUID
        :param password_hash: 持久化的密码哈希值。约束：需符合 ``str`` 注解。
        :type password_hash: str
        :returns: 无返回值。
        :rtype: None
        """

        user = self._session.get(AuthUserOrmModel, user_id)
        if user is None:
            return
        user.password_hash = password_hash
        self._session.flush()

    def _build_user_statement(self) -> Select[tuple[AuthUserOrmModel]]:
        """
        构建用户声明。

        :returns: 返回当前操作结果。
        :rtype: Select[tuple[AuthUserOrmModel]]
        """

        return select(AuthUserOrmModel).options(
            selectinload(AuthUserOrmModel.user_roles)
            .selectinload(AuthUserRoleOrmModel.role)
            .selectinload(AuthRoleOrmModel.role_scopes)
        )

    def _build_identity_snapshot(self, user: AuthUserOrmModel) -> AuthIdentitySnapshot:
        """
        构建身份快照。

        :param user: 当前步骤使用的用户参数。约束：需符合 ``AuthUserOrmModel`` 注解。
        :type user: AuthUserOrmModel
        :returns: 返回当前操作结果。
        :rtype: AuthIdentitySnapshot
        """

        role_keys = [user_role.role.role_key for user_role in user.user_roles]
        raw_scope_codes = [
            role_scope.scope_code
            for user_role in user.user_roles
            for role_scope in user_role.role.role_scopes
        ]
        enabled_scope_codes = self._load_enabled_scope_codes(set(raw_scope_codes))
        scope_codes = [
            scope_code for scope_code in raw_scope_codes if scope_code in enabled_scope_codes
        ]
        return AuthIdentitySnapshot(
            user_id=user.user_id,
            subject_id=user.subject_id,
            username=user.username,
            password_hash=user.password_hash,
            is_active=user.is_active,
            roles=list(dict.fromkeys(role_keys)),
            scopes=list(dict.fromkeys(scope_codes)),
        )

    def _load_enabled_scope_codes(self, scope_codes: set[str]) -> set[str]:
        """
        读取当前启用的授权作用域编码。

        :param scope_codes: 候选授权作用域编码集合。约束：缺失或禁用的 scope 均按不可授权处理。
        :type scope_codes: set[str]
        :returns: 当前可参与授权的启用 scope 编码集合。
        :rtype: set[str]
        """

        if not scope_codes:
            return set()
        return set(
            self._session.scalars(
                select(AuthScopeOrmModel.scope_code)
                .where(AuthScopeOrmModel.scope_code.in_(scope_codes))
                .where(AuthScopeOrmModel.enabled.is_(True))
            ).all()
        )
