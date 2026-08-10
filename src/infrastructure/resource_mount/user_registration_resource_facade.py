"""普通用户注册资源门面。"""

from __future__ import annotations

from http import HTTPStatus

from sqlalchemy.exc import IntegrityError

from src.application.register_user_usecase import (
    RegisteredUserSnapshot,
    UserRegistrationCommand,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.domain.auth.auth_error_code import AuthErrorCode
from src.infrastructure.persistence.repository_impl.user_registration_repository import (
    REGISTRATION_USERNAME_CONFLICT_MESSAGE,
    UserRegistrationRepository,
)
from src.infrastructure.resource_mount.shared_resource_lifecycle import SharedResourceLifecycle

AUTH_USER_USERNAME_UNIQUE_CONSTRAINT = "uq_auth_user_username"
SQLITE_AUTH_USER_USERNAME_UNIQUE_DETAIL = "UNIQUE constraint failed: auth_user.username"


class UserRegistrationResourceFacade(SharedResourceLifecycle):
    """普通用户注册的密码散列与事务边界。"""

    def create_registered_user(
        self,
        *,
        command: UserRegistrationCommand,
        role_key: str,
    ) -> RegisteredUserSnapshot:
        """在单个工作单元中创建普通用户。"""

        password_hash = self.get_password_hasher().hash_password(command.password_plain)
        unit_of_work = self.create_unit_of_work()
        try:
            repository = UserRegistrationRepository(
                self._read_sqlalchemy_session(unit_of_work.get_session())
            )
            snapshot = repository.create(
                username=command.username,
                password_hash=password_hash,
                role_key=role_key,
            )
            unit_of_work.commit()
            return snapshot
        except IntegrityError as exc:
            unit_of_work.rollback()
            integrity_detail = str(exc.orig)
            if (
                AUTH_USER_USERNAME_UNIQUE_CONSTRAINT in integrity_detail
                or SQLITE_AUTH_USER_USERNAME_UNIQUE_DETAIL in integrity_detail
            ):
                raise HttpFaultException(
                    status_code=HTTPStatus.CONFLICT,
                    error_code=AuthErrorCode.REGISTRATION_USERNAME_CONFLICT,
                    message=REGISTRATION_USERNAME_CONFLICT_MESSAGE,
                ) from exc
            raise
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()
