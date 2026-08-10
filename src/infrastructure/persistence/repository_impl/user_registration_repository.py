"""普通用户注册仓储。"""

from __future__ import annotations

from http import HTTPStatus
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.application.register_user_usecase import RegisteredUserSnapshot
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.auth.auth_error_code import AuthErrorCode
from src.infrastructure.persistence.orm_model.auth_role_orm_model import AuthRoleOrmModel
from src.infrastructure.persistence.orm_model.auth_user_orm_model import AuthUserOrmModel
from src.infrastructure.persistence.orm_model.auth_user_role_orm_model import (
    AuthUserRoleOrmModel,
)

REGISTERED_USER_SUBJECT_PREFIX = "user"
REGISTRATION_USERNAME_CONFLICT_MESSAGE = "该用户名不可用。"
REGISTRATION_ROLE_MISSING_MESSAGE = "普通用户注册角色未就绪。"


class UserRegistrationRepository:
    """在当前事务内写入普通用户及固定角色。"""

    def __init__(self, session: Session) -> None:
        """初始化普通用户注册仓储。"""

        self._session = session

    def create(
        self,
        *,
        username: str,
        password_hash: str,
        role_key: str,
    ) -> RegisteredUserSnapshot:
        """创建普通用户。"""

        existing_user = self._session.scalar(
            select(AuthUserOrmModel).where(AuthUserOrmModel.username == username)
        )
        if existing_user is not None:
            raise HttpFaultException(
                status_code=HTTPStatus.CONFLICT,
                error_code=AuthErrorCode.REGISTRATION_USERNAME_CONFLICT,
                message=REGISTRATION_USERNAME_CONFLICT_MESSAGE,
            )
        role = self._session.scalar(
            select(AuthRoleOrmModel).where(AuthRoleOrmModel.role_key == role_key)
        )
        if role is None:
            raise HttpFaultException(
                status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
                error_code=CoreErrorCode.CONFIG_INVALID,
                message=REGISTRATION_ROLE_MISSING_MESSAGE,
            )
        subject_id = f"{REGISTERED_USER_SUBJECT_PREFIX}-{uuid4().hex}"
        user = AuthUserOrmModel(
            subject_id=subject_id,
            username=username,
            password_hash=password_hash,
            is_active=True,
        )
        self._session.add(user)
        self._session.flush()
        self._session.add(AuthUserRoleOrmModel(user_id=user.user_id, role_id=role.role_id))
        self._session.flush()
        return RegisteredUserSnapshot(subject_id=subject_id, username=username)
