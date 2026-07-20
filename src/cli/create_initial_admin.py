"""
初始管理员创建命令行入口。
"""

from __future__ import annotations

import getpass
import hashlib
import hmac
import os
import sys
from enum import StrEnum
from typing import Annotated, Final, Literal, TextIO
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from src.application.admin.identity.initial_admin.create_initial_admin_usecase import (
    INITIAL_ADMIN_CONFIRMATION_INVALID_MESSAGE,
    CreateInitialAdminUsecase,
)
from src.application.admin.identity.shared.admin_identity_command import (
    InitialAdminCreateCommand,
    InitialAdminCreateReason,
    InitialAdminCreateResult,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.auth.password_hasher import PasswordHasher
from src.infrastructure.logging.app_logger_factory import AppLoggerFactory
from src.infrastructure.persistence.repository_impl.admin_identity_repository_impl import (
    AdminIdentityRepositoryImpl,
)
from src.infrastructure.persistence.sqlalchemy_engine_factory import SqlAlchemyEngineFactory
from src.infrastructure.persistence.sqlalchemy_session_factory import (
    SqlAlchemySessionFactory,
)
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    DatabaseRuntimeSettings,
)

INITIAL_ADMIN_CREATE_EXIT_SUCCESS = 0
INITIAL_ADMIN_CREATE_EXIT_FAILURE = 1
INITIAL_ADMIN_CREATE_SCHEMA_VERSION: Final = "1.0"
INITIAL_ADMIN_CREATE_RESULT_KIND: Final = "initial_admin_create_result"
INITIAL_ADMIN_CREATE_OPERATION_NAME: Final = "initial_admin_create"
INITIAL_ADMIN_USERNAME_ENV = "INITIAL_ADMIN_USERNAME"
INITIAL_ADMIN_PASSWORD_ENV = "INITIAL_ADMIN_PASSWORD"
INITIAL_ADMIN_SUBJECT_ID_ENV = "INITIAL_ADMIN_SUBJECT_ID"
INITIAL_ADMIN_CONFIRM_ENV = "INITIAL_ADMIN_CONFIRM"
INITIAL_ADMIN_ALLOW_PRODUCTION_ENV = "INITIAL_ADMIN_ALLOW_PRODUCTION"
INITIAL_ADMIN_DATABASE_FINGERPRINT_ENV = "INITIAL_ADMIN_DATABASE_FINGERPRINT"
INITIAL_ADMIN_BOOTSTRAP_SECRET_ENV = "INITIAL_ADMIN_BOOTSTRAP_SECRET"
INITIAL_ADMIN_BOOTSTRAP_SECRET_CONFIRM_ENV = "INITIAL_ADMIN_BOOTSTRAP_SECRET_CONFIRM"
INITIAL_ADMIN_ALLOW_PRODUCTION_VALUE = "true"
INITIAL_ADMIN_DATABASE_FINGERPRINT_SEPARATOR = "|"
INITIAL_ADMIN_CONFIRM_PROMPT = "请输入确认短语 create-initial-admin："
INITIAL_ADMIN_USERNAME_PROMPT = "请输入初始管理员用户名："
INITIAL_ADMIN_PASSWORD_PROMPT = "请输入初始管理员密码："
INITIAL_ADMIN_CONFIRM_REQUIRED_MESSAGE = "非交互执行必须提供 INITIAL_ADMIN_CONFIRM。"
INITIAL_ADMIN_USERNAME_REQUIRED_MESSAGE = "初始管理员用户名不能为空。"
INITIAL_ADMIN_PASSWORD_REQUIRED_MESSAGE = "初始管理员密码不能为空。"
INITIAL_ADMIN_FAILURE_MESSAGE = "初始管理员创建失败。"
INITIAL_ADMIN_PRODUCTION_BLOCKED_MESSAGE = (
    "生产环境默认禁止执行初始管理员创建；必须显式设置 INITIAL_ADMIN_ALLOW_PRODUCTION=true。"
)
INITIAL_ADMIN_DATABASE_FINGERPRINT_REQUIRED_MESSAGE = (
    "生产环境必须提供目标库指纹 INITIAL_ADMIN_DATABASE_FINGERPRINT。"
)
INITIAL_ADMIN_DATABASE_FINGERPRINT_MISMATCH_MESSAGE = (
    "生产环境目标库指纹与当前配置不一致，禁止创建初始管理员。"
)
INITIAL_ADMIN_BOOTSTRAP_SECRET_REQUIRED_MESSAGE = (
    "生产环境必须提供一次性 bootstrap secret 及确认值。"
)
INITIAL_ADMIN_BOOTSTRAP_SECRET_MISMATCH_MESSAGE = "生产环境一次性 bootstrap secret 确认失败。"


class InitialAdminCliStatus(StrEnum):
    """
    初始管理员 CLI 状态枚举。
    """

    SUCCESS = "success"
    FAILED = "failed"


class InitialAdminResultDetail(BaseModel):
    """
    初始管理员创建结果扩展字段。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["initial_admin_create_result"] = INITIAL_ADMIN_CREATE_RESULT_KIND
    schema_version: Literal["1.0"] = INITIAL_ADMIN_CREATE_SCHEMA_VERSION
    status: InitialAdminCliStatus
    exit_code: int = Field(ge=INITIAL_ADMIN_CREATE_EXIT_SUCCESS)
    created: bool
    subject_id: str | None
    reason: InitialAdminCreateReason


InitialAdminResultDetailUnion = Annotated[
    InitialAdminResultDetail,
    Field(discriminator="kind"),
]


class InitialAdminResultHeader(BaseModel):
    """
    初始管理员创建结果公共头。
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["initial_admin_create_result"] = INITIAL_ADMIN_CREATE_RESULT_KIND
    schema_version: Literal["1.0"] = INITIAL_ADMIN_CREATE_SCHEMA_VERSION
    operation_name: Literal["initial_admin_create"] = INITIAL_ADMIN_CREATE_OPERATION_NAME


class InitialAdminResultEnvelope(BaseModel):
    """
    初始管理员创建结果信封。
    """

    model_config = ConfigDict(extra="forbid")

    header: InitialAdminResultHeader
    detail: InitialAdminResultDetailUnion

    @model_validator(mode="after")
    def validate_detail_contract(self) -> InitialAdminResultEnvelope:
        """
        校验初始管理员结果公共头与扩展字段一致。
        """

        if self.header.kind != self.detail.kind:
            raise ValueError("初始管理员结果 header.kind 必须与 detail.kind 一致。")
        if self.header.schema_version != self.detail.schema_version:
            raise ValueError("初始管理员结果 schema_version 必须一致。")
        return self


class InitialAdminCliInput(BaseModel):
    """
    初始管理员 CLI 输入。
    """

    model_config = ConfigDict(extra="forbid")

    username: str
    password: SecretStr
    subject_id: str | None
    confirmation: str

    @model_validator(mode="after")
    def validate_input(self) -> InitialAdminCliInput:
        """
        校验 CLI 输入字段。
        """

        if self.username.strip() == "":
            raise ValueError(INITIAL_ADMIN_USERNAME_REQUIRED_MESSAGE)
        if self.password.get_secret_value().strip() == "":
            raise ValueError(INITIAL_ADMIN_PASSWORD_REQUIRED_MESSAGE)
        if self.confirmation.strip() == "":
            raise ValueError(INITIAL_ADMIN_CONFIRM_REQUIRED_MESSAGE)
        return self


class InitialAdminCli:
    """
    初始管理员创建命令行执行器。
    """

    def __init__(
        self,
        *,
        stdin: TextIO | None = None,
        stdout: TextIO | None = None,
        interactive: bool | None = None,
    ) -> None:
        """
        初始化初始管理员创建命令行执行器。
        """

        self._stdin = stdin or sys.stdin
        self._stdout = stdout or sys.stdout
        self._interactive = interactive if interactive is not None else self._stdin.isatty()

    def execute(self) -> InitialAdminResultEnvelope:
        """
        执行初始管理员创建。
        """

        settings = AppSettingsLoader().load()
        logger = AppLoggerFactory().build(settings)
        engine_factory = SqlAlchemyEngineFactory()
        engine = engine_factory.build(settings.runtime.database)
        try:
            self._assert_production_execution_allowed(
                environment=settings.app.environment,
                database_settings=settings.runtime.database,
            )
            engine_factory.validate(engine)
            cli_input = self._read_input()
            result = self._execute_with_unit_of_work(
                session_factory=SqlAlchemySessionFactory(engine),
                password_hasher=PasswordHasher(settings.runtime.auth.password_hash_algorithm),
                command=InitialAdminCreateCommand(
                    username=cli_input.username,
                    password_plain=cli_input.password.get_secret_value(),
                    subject_id=cli_input.subject_id,
                    confirmation=cli_input.confirmation,
                ),
            )
            return self._build_success_result(result)
        except Exception as exc:
            logger.exception(INITIAL_ADMIN_FAILURE_MESSAGE)
            return self._build_failure_result(exc)
        finally:
            engine.dispose()

    def _assert_production_execution_allowed(
        self,
        *,
        environment: object,
        database_settings: DatabaseRuntimeSettings,
    ) -> None:
        """
        校验生产环境初始管理员创建开关、目标库指纹与一次性密钥。

        :param environment: 当前应用环境。
        :type environment: object
        :param database_settings: 数据库运行时配置。
        :type database_settings: DatabaseRuntimeSettings
        :returns: 无返回值。
        :rtype: None
        """

        if str(environment) != "production":
            return
        if os.getenv(INITIAL_ADMIN_ALLOW_PRODUCTION_ENV) != INITIAL_ADMIN_ALLOW_PRODUCTION_VALUE:
            raise RuntimeError(INITIAL_ADMIN_PRODUCTION_BLOCKED_MESSAGE)
        expected_fingerprint = os.getenv(INITIAL_ADMIN_DATABASE_FINGERPRINT_ENV)
        if expected_fingerprint is None or expected_fingerprint.strip() == "":
            raise RuntimeError(INITIAL_ADMIN_DATABASE_FINGERPRINT_REQUIRED_MESSAGE)
        current_fingerprint = self._build_database_fingerprint(database_settings)
        if expected_fingerprint.strip() != current_fingerprint:
            raise RuntimeError(INITIAL_ADMIN_DATABASE_FINGERPRINT_MISMATCH_MESSAGE)
        bootstrap_secret = os.getenv(INITIAL_ADMIN_BOOTSTRAP_SECRET_ENV)
        bootstrap_secret_confirm = os.getenv(INITIAL_ADMIN_BOOTSTRAP_SECRET_CONFIRM_ENV)
        if (
            bootstrap_secret is None
            or bootstrap_secret.strip() == ""
            or bootstrap_secret_confirm is None
            or bootstrap_secret_confirm.strip() == ""
        ):
            raise RuntimeError(INITIAL_ADMIN_BOOTSTRAP_SECRET_REQUIRED_MESSAGE)
        if not hmac.compare_digest(bootstrap_secret, bootstrap_secret_confirm):
            raise RuntimeError(INITIAL_ADMIN_BOOTSTRAP_SECRET_MISMATCH_MESSAGE)
        os.environ.pop(INITIAL_ADMIN_BOOTSTRAP_SECRET_ENV, None)
        os.environ.pop(INITIAL_ADMIN_BOOTSTRAP_SECRET_CONFIRM_ENV, None)

    def _build_database_fingerprint(
        self,
        database_settings: DatabaseRuntimeSettings,
    ) -> str:
        """
        构建生产初始管理员目标库指纹。

        :param database_settings: 数据库运行时配置。
        :type database_settings: DatabaseRuntimeSettings
        :returns: 当前数据库连接与 schema 的稳定摘要。
        :rtype: str
        """

        normalized_url = self._normalize_database_url(database_settings.url)
        fingerprint_source = INITIAL_ADMIN_DATABASE_FINGERPRINT_SEPARATOR.join(
            [
                normalized_url,
                database_settings.schema_name,
            ]
        )
        return hashlib.sha256(fingerprint_source.encode()).hexdigest()

    def _normalize_database_url(self, database_url: str) -> str:
        """
        规范化数据库连接串用于指纹计算。

        :param database_url: 数据库连接串。
        :type database_url: str
        :returns: 去除密码后的数据库连接串规范化文本。
        :rtype: str
        """

        parsed_url = urlsplit(database_url)
        hostname = parsed_url.hostname or ""
        username = parsed_url.username or ""
        port = parsed_url.port
        auth_prefix = f"{username}@" if username != "" else ""
        port_suffix = f":{port}" if port is not None else ""
        netloc = f"{auth_prefix}{hostname}{port_suffix}"
        return urlunsplit(
            (
                parsed_url.scheme,
                netloc,
                parsed_url.path,
                parsed_url.query,
                parsed_url.fragment,
            )
        )

    def run(self) -> int:
        """
        执行初始管理员创建并返回进程退出码。
        """

        result = self.execute()
        self._stdout.write(result.model_dump_json())
        self._stdout.write("\n")
        return result.detail.exit_code

    def _execute_with_unit_of_work(
        self,
        *,
        session_factory: SqlAlchemySessionFactory,
        password_hasher: PasswordHasher,
        command: InitialAdminCreateCommand,
    ) -> InitialAdminCreateResult:
        """
        在数据库工作单元内执行初始管理员创建。
        """

        unit_of_work = session_factory.create_unit_of_work()
        try:
            session = unit_of_work.get_session()
            usecase = CreateInitialAdminUsecase(
                admin_identity_port=AdminIdentityRepositoryImpl(session),
                password_hasher=password_hasher,
            )
            result = usecase.execute(command)
            unit_of_work.commit()
            return result
        except Exception:
            unit_of_work.rollback()
            raise
        finally:
            unit_of_work.dispose()

    def _read_input(self) -> InitialAdminCliInput:
        """
        读取 CLI 输入。
        """

        username = self._read_value(
            env_name=INITIAL_ADMIN_USERNAME_ENV,
            prompt=INITIAL_ADMIN_USERNAME_PROMPT,
        )
        password = self._read_password()
        confirmation = os.getenv(INITIAL_ADMIN_CONFIRM_ENV)
        if confirmation is None and self._interactive:
            self._stdout.write(INITIAL_ADMIN_CONFIRM_PROMPT)
            self._stdout.flush()
            confirmation = self._stdin.readline().strip()
        return InitialAdminCliInput(
            username=username or "",
            password=SecretStr(password or ""),
            subject_id=os.getenv(INITIAL_ADMIN_SUBJECT_ID_ENV),
            confirmation=confirmation or "",
        )

    def _read_value(self, *, env_name: str, prompt: str) -> str | None:
        """
        从环境变量或交互输入读取普通字段。
        """

        value = os.getenv(env_name)
        if value is not None or not self._interactive:
            return value
        self._stdout.write(prompt)
        self._stdout.flush()
        return self._stdin.readline().strip()

    def _read_password(self) -> str | None:
        """
        从环境变量或交互输入读取密码。
        """

        password = os.getenv(INITIAL_ADMIN_PASSWORD_ENV)
        if password is not None or not self._interactive:
            return password
        return getpass.getpass(INITIAL_ADMIN_PASSWORD_PROMPT)

    def _build_success_result(
        self,
        result: InitialAdminCreateResult,
    ) -> InitialAdminResultEnvelope:
        """
        构建成功结果。
        """

        return self._build_result(
            status=InitialAdminCliStatus.SUCCESS,
            exit_code=INITIAL_ADMIN_CREATE_EXIT_SUCCESS,
            created=result.created,
            subject_id=result.subject_id,
            reason=result.reason,
        )

    def _build_failure_result(self, exc: Exception) -> InitialAdminResultEnvelope:
        """
        构建失败结果。
        """

        reason = InitialAdminCreateReason.RUNTIME_ERROR
        if isinstance(exc, HttpFaultException):
            reason = self._resolve_fault_reason(exc)
        return self._build_result(
            status=InitialAdminCliStatus.FAILED,
            exit_code=INITIAL_ADMIN_CREATE_EXIT_FAILURE,
            created=False,
            subject_id=None,
            reason=reason,
        )

    def _resolve_fault_reason(self, exc: HttpFaultException) -> InitialAdminCreateReason:
        """
        解析业务异常对应的初始管理员失败原因。
        """

        if exc.message == INITIAL_ADMIN_CONFIRMATION_INVALID_MESSAGE:
            return InitialAdminCreateReason.CONFIRMATION_INVALID
        return InitialAdminCreateReason.RUNTIME_ERROR

    def _build_result(
        self,
        *,
        status: InitialAdminCliStatus,
        exit_code: int,
        created: bool,
        subject_id: str | None,
        reason: InitialAdminCreateReason,
    ) -> InitialAdminResultEnvelope:
        """
        构建 CLI 输出结果。
        """

        return InitialAdminResultEnvelope(
            header=InitialAdminResultHeader(),
            detail=InitialAdminResultDetail(
                status=status,
                exit_code=exit_code,
                created=created,
                subject_id=subject_id,
                reason=reason,
            ),
        )


if __name__ == "__main__":
    raise SystemExit(InitialAdminCli().run())
