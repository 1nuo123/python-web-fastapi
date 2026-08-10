"""公开注册角色目录同步器。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.settings.application_settings import PublicRegistrationSettings


class PublicRegistrationRoleSynchronizer:
    """保证公开注册固定角色存在且不携带授权 scope。"""

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
        role.role_name = policy.default_role_key
        role.role_scopes.clear()
        session.flush()
