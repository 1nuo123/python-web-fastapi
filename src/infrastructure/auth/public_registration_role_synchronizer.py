"""公开注册角色目录同步器。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_role_scope_orm_model import (
    AuthRoleScopeOrmModel,
)
from src.infrastructure.settings.application_settings import PublicRegistrationSettings

PUBLIC_REGISTRATION_SCOPE_CODES = (
    AuthScopeCode.CODEX_READ.value,
    AuthScopeCode.CODEX_HOST_MANAGE.value,
)


class PublicRegistrationRoleSynchronizer:
    """保证公开注册固定角色存在。"""

    def synchronize(
        self,
        *,
        session: Session,
        policy: PublicRegistrationSettings,
    ) -> None:
        """同步公开注册固定角色。"""

        if not policy.enabled:
            return
        role = session.scalar(
            select(AuthRoleOrmModel).where(AuthRoleOrmModel.role_key == policy.default_role_key)
        )
        if role is None:
            role = AuthRoleOrmModel(
                role_key=policy.default_role_key,
                role_name=policy.default_role_key,
            )
            session.add(role)
            session.flush()
            role.role_scopes.extend(
                AuthRoleScopeOrmModel(scope_code=scope_code)
                for scope_code in PUBLIC_REGISTRATION_SCOPE_CODES
            )
        role.role_name = policy.default_role_key
        session.flush()
