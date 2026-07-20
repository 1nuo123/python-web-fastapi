"""
初始管理员 CLI 单元测试模块。
"""

from __future__ import annotations

import os
from http import HTTPStatus
from io import StringIO

import pytest
from pydantic import ValidationError

from src.application.admin.identity.initial_admin.create_initial_admin_usecase import (
    INITIAL_ADMIN_CONFIRMATION_INVALID_MESSAGE,
    INITIAL_ADMIN_CONFIRMATION_PHRASE,
    CreateInitialAdminUsecase,
)
from src.application.admin.identity.shared.admin_identity_command import (
    InitialAdminCreateCommand,
    InitialAdminCreateReason,
    InitialAdminCreateResult,
)
from src.cli.create_initial_admin import (
    INITIAL_ADMIN_ALLOW_PRODUCTION_ENV,
    INITIAL_ADMIN_ALLOW_PRODUCTION_VALUE,
    INITIAL_ADMIN_BOOTSTRAP_SECRET_CONFIRM_ENV,
    INITIAL_ADMIN_BOOTSTRAP_SECRET_ENV,
    INITIAL_ADMIN_CONFIRM_ENV,
    INITIAL_ADMIN_CREATE_EXIT_FAILURE,
    INITIAL_ADMIN_CREATE_EXIT_SUCCESS,
    INITIAL_ADMIN_DATABASE_FINGERPRINT_ENV,
    INITIAL_ADMIN_PASSWORD_ENV,
    INITIAL_ADMIN_USERNAME_ENV,
    InitialAdminCli,
    InitialAdminCliStatus,
    InitialAdminResultDetail,
    InitialAdminResultEnvelope,
    InitialAdminResultHeader,
)
from src.core.exception_contract.error_code_catalog_contract import CoreErrorCode
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.auth.password_hasher import PasswordHasher
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
    DatabaseBackend,
    DatabaseRuntimeSettings,
    PasswordHashAlgorithm,
)

INITIAL_ADMIN_UNIT_USERNAME = "initial-admin-unit"
INITIAL_ADMIN_UNIT_PASSWORD = "initial-admin-password"
INITIAL_ADMIN_UNIT_SUBJECT_ID = "initial-admin-unit-subject"
INITIAL_ADMIN_HASH_PREFIX = "$"
INITIAL_ADMIN_STDOUT_EMPTY = ""
INITIAL_ADMIN_RESULT_SCHEMA_VERSION_INVALID = "9.9"
INITIAL_ADMIN_RESULT_UNKNOWN_FIELD = "unexpected"
INITIAL_ADMIN_DATABASE_URL = (
    "postgresql+psycopg://fastapi:initial-admin-password@postgres:5432/fastapi_web_skeleton"
)
INITIAL_ADMIN_DATABASE_URL_WITH_OTHER_PASSWORD = (
    "postgresql+psycopg://fastapi:other-initial-admin-password@postgres:5432/fastapi_web_skeleton"
)
INITIAL_ADMIN_DATABASE_SCHEMA = "public"
INITIAL_ADMIN_DATABASE_FINGERPRINT_WRONG = "wrong-target-fingerprint"
INITIAL_ADMIN_BOOTSTRAP_SECRET = "initial-admin-bootstrap-secret"
INITIAL_ADMIN_BOOTSTRAP_SECRET_OTHER = "initial-admin-bootstrap-secret-other"


class InitialAdminCreatePortStub:
    """
    初始管理员创建端口测试替身。
    """

    def __init__(self, result: InitialAdminCreateResult) -> None:
        """
        初始化测试替身。
        """

        self._result = result
        self.username: str | None = None
        self.password_hash: str | None = None
        self.subject_id: str | None = None

    def create_initial_admin_user(
        self,
        *,
        username: str,
        password_hash: str,
        subject_id: str | None,
    ) -> InitialAdminCreateResult:
        """
        记录调用并返回指定结果。
        """

        self.username = username
        self.password_hash = password_hash
        self.subject_id = subject_id
        return self._result


class TestInitialAdminCliUnit:
    """
    初始管理员 CLI 单元测试集合。
    """

    def test_usecase_when_confirmation_valid_should_hash_password(self) -> None:
        """
        验证确认短语正确时会哈希密码并调用端口。
        """

        port = InitialAdminCreatePortStub(
            InitialAdminCreateResult(
                created=True,
                subject_id=INITIAL_ADMIN_UNIT_SUBJECT_ID,
                reason=InitialAdminCreateReason.CREATED,
            )
        )
        result = CreateInitialAdminUsecase(
            admin_identity_port=port,
            password_hasher=PasswordHasher(PasswordHashAlgorithm.ARGON2),
        ).execute(
            InitialAdminCreateCommand(
                username=INITIAL_ADMIN_UNIT_USERNAME,
                password_plain=INITIAL_ADMIN_UNIT_PASSWORD,
                subject_id=INITIAL_ADMIN_UNIT_SUBJECT_ID,
                confirmation=INITIAL_ADMIN_CONFIRMATION_PHRASE,
            )
        )

        assert result.created is True
        assert port.username == INITIAL_ADMIN_UNIT_USERNAME
        assert port.subject_id == INITIAL_ADMIN_UNIT_SUBJECT_ID
        assert port.password_hash is not None
        assert port.password_hash.startswith(INITIAL_ADMIN_HASH_PREFIX)
        assert port.password_hash != INITIAL_ADMIN_UNIT_PASSWORD

    def test_usecase_when_confirmation_invalid_should_fail(self) -> None:
        """
        验证确认短语错误时拒绝执行。
        """

        port = InitialAdminCreatePortStub(
            InitialAdminCreateResult(
                created=False,
                subject_id=None,
                reason=InitialAdminCreateReason.ADMIN_EXISTS,
            )
        )

        with pytest.raises(HttpFaultException):
            CreateInitialAdminUsecase(
                admin_identity_port=port,
                password_hasher=PasswordHasher(PasswordHashAlgorithm.ARGON2),
            ).execute(
                InitialAdminCreateCommand(
                    username=INITIAL_ADMIN_UNIT_USERNAME,
                    password_plain=INITIAL_ADMIN_UNIT_PASSWORD,
                    subject_id=None,
                    confirmation="invalid-confirmation",
                )
            )

        assert port.password_hash is None

    def test_cli_result_when_already_exists_should_be_desensitized(self) -> None:
        """
        验证 CLI 输出契约不会泄露明文密码。
        """

        result = InitialAdminCli(
            stdin=StringIO(),
            stdout=StringIO(),
            interactive=False,
        )._build_success_result(  # noqa: SLF001
            InitialAdminCreateResult(
                created=False,
                subject_id=INITIAL_ADMIN_UNIT_SUBJECT_ID,
                reason=InitialAdminCreateReason.ALREADY_EXISTS,
            )
        )
        output = result.model_dump_json()

        assert result.detail.status == InitialAdminCliStatus.SUCCESS
        assert result.detail.exit_code == INITIAL_ADMIN_CREATE_EXIT_SUCCESS
        assert result.detail.created is False
        assert result.detail.reason == InitialAdminCreateReason.ALREADY_EXISTS
        assert INITIAL_ADMIN_UNIT_PASSWORD not in output
        assert INITIAL_ADMIN_PASSWORD_ENV not in output
        assert INITIAL_ADMIN_USERNAME_ENV not in output

    def test_cli_run_should_write_json_and_return_exit_code(self, monkeypatch) -> None:
        """
        验证 CLI 入口会输出 JSON 并返回结果退出码。
        """

        stdout = StringIO()
        cli = InitialAdminCli(
            stdin=StringIO(),
            stdout=stdout,
            interactive=False,
        )
        expected = cli._build_success_result(  # noqa: SLF001
            InitialAdminCreateResult(
                created=True,
                subject_id=INITIAL_ADMIN_UNIT_SUBJECT_ID,
                reason=InitialAdminCreateReason.CREATED,
            )
        )
        monkeypatch.setattr(cli, "execute", lambda: expected)

        exit_code = cli.run()
        envelope = InitialAdminResultEnvelope.model_validate_json(stdout.getvalue())

        assert exit_code == INITIAL_ADMIN_CREATE_EXIT_SUCCESS
        assert envelope.detail.status == InitialAdminCliStatus.SUCCESS
        assert envelope.detail.created is True
        assert envelope.detail.reason == InitialAdminCreateReason.CREATED

    def test_cli_failure_result_should_distinguish_confirmation_invalid(self) -> None:
        """
        验证 CLI 失败输出不会把确认短语错误伪装成 admin 已存在。
        """

        result = InitialAdminCli(
            stdin=StringIO(),
            stdout=StringIO(),
            interactive=False,
        )._build_failure_result(  # noqa: SLF001
            HttpFaultException(
                status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
                error_code=CoreErrorCode.REQUEST_INVALID,
                message=INITIAL_ADMIN_CONFIRMATION_INVALID_MESSAGE,
            )
        )

        assert result.detail.status == InitialAdminCliStatus.FAILED
        assert result.detail.exit_code == INITIAL_ADMIN_CREATE_EXIT_FAILURE
        assert result.detail.reason == InitialAdminCreateReason.CONFIRMATION_INVALID

    def test_cli_failure_result_when_runtime_error_should_return_runtime_error(
        self,
    ) -> None:
        """
        验证非确认短语错误会映射为运行时失败。
        """

        result = InitialAdminCli(
            stdin=StringIO(),
            stdout=StringIO(),
            interactive=False,
        )._build_failure_result(RuntimeError("数据库连接失败。"))  # noqa: SLF001

        assert result.detail.status == InitialAdminCliStatus.FAILED
        assert result.detail.exit_code == INITIAL_ADMIN_CREATE_EXIT_FAILURE
        assert result.detail.reason == InitialAdminCreateReason.RUNTIME_ERROR

    def test_cli_result_envelope_should_validate_header_and_detail_contract(
        self,
    ) -> None:
        """
        验证 CLI 输出信封会校验公共头与扩展字段一致。
        """

        with pytest.raises(ValidationError):
            InitialAdminResultEnvelope(
                header=InitialAdminResultHeader(),
                detail=InitialAdminResultDetail(
                    schema_version=INITIAL_ADMIN_RESULT_SCHEMA_VERSION_INVALID,
                    status=InitialAdminCliStatus.SUCCESS,
                    exit_code=INITIAL_ADMIN_CREATE_EXIT_SUCCESS,
                    created=True,
                    subject_id=INITIAL_ADMIN_UNIT_SUBJECT_ID,
                    reason=InitialAdminCreateReason.CREATED,
                ),
            )

    def test_cli_result_detail_when_unknown_field_should_fail(self) -> None:
        """
        验证 CLI 输出扩展字段拒绝未知字段。
        """

        with pytest.raises(ValidationError):
            InitialAdminResultDetail.model_validate(
                {
                    "status": InitialAdminCliStatus.SUCCESS,
                    "exit_code": INITIAL_ADMIN_CREATE_EXIT_SUCCESS,
                    "created": True,
                    "subject_id": INITIAL_ADMIN_UNIT_SUBJECT_ID,
                    "reason": InitialAdminCreateReason.CREATED,
                    INITIAL_ADMIN_RESULT_UNKNOWN_FIELD: True,
                }
            )

    def test_cli_input_when_non_interactive_missing_confirmation_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证非交互模式缺少确认变量时输入校验失败。
        """

        monkeypatch.setenv(INITIAL_ADMIN_USERNAME_ENV, INITIAL_ADMIN_UNIT_USERNAME)
        monkeypatch.setenv(INITIAL_ADMIN_PASSWORD_ENV, INITIAL_ADMIN_UNIT_PASSWORD)
        monkeypatch.delenv(INITIAL_ADMIN_CONFIRM_ENV, raising=False)

        with pytest.raises(ValueError):
            InitialAdminCli(
                stdin=StringIO(),
                stdout=StringIO(INITIAL_ADMIN_STDOUT_EMPTY),
                interactive=False,
            )._read_input()  # noqa: SLF001

    def test_cli_when_production_without_allow_flag_should_fail(self) -> None:
        """
        验证生产环境缺少显式开关时拒绝初始管理员创建。
        """

        with pytest.raises(RuntimeError):
            InitialAdminCli(
                stdin=StringIO(),
                stdout=StringIO(INITIAL_ADMIN_STDOUT_EMPTY),
                interactive=False,
            )._assert_production_execution_allowed(  # noqa: SLF001
                environment=AppEnvironment.PRODUCTION,
                database_settings=self._build_database_settings(),
            )

    def test_cli_when_production_fingerprint_mismatch_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产环境目标库指纹不一致时拒绝初始管理员创建。
        """

        self._set_production_bootstrap_env(
            monkeypatch,
            database_fingerprint=INITIAL_ADMIN_DATABASE_FINGERPRINT_WRONG,
        )

        with pytest.raises(RuntimeError):
            InitialAdminCli(
                stdin=StringIO(),
                stdout=StringIO(INITIAL_ADMIN_STDOUT_EMPTY),
                interactive=False,
            )._assert_production_execution_allowed(  # noqa: SLF001
                environment=AppEnvironment.PRODUCTION,
                database_settings=self._build_database_settings(),
            )

    def test_cli_when_production_bootstrap_secret_mismatch_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产环境一次性 bootstrap secret 不一致时拒绝执行。
        """

        cli = InitialAdminCli(
            stdin=StringIO(),
            stdout=StringIO(INITIAL_ADMIN_STDOUT_EMPTY),
            interactive=False,
        )
        database_settings = self._build_database_settings()
        self._set_production_bootstrap_env(
            monkeypatch,
            database_fingerprint=cli._build_database_fingerprint(  # noqa: SLF001
                database_settings
            ),
            bootstrap_secret_confirm=INITIAL_ADMIN_BOOTSTRAP_SECRET_OTHER,
        )

        with pytest.raises(RuntimeError):
            cli._assert_production_execution_allowed(  # noqa: SLF001
                environment=AppEnvironment.PRODUCTION,
                database_settings=database_settings,
            )

    def test_cli_when_production_fingerprint_and_secret_valid_should_pass(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产环境目标库指纹与一次性密钥齐备时允许继续执行。
        """

        cli = InitialAdminCli(
            stdin=StringIO(),
            stdout=StringIO(INITIAL_ADMIN_STDOUT_EMPTY),
            interactive=False,
        )
        database_settings = self._build_database_settings()
        self._set_production_bootstrap_env(
            monkeypatch,
            database_fingerprint=cli._build_database_fingerprint(  # noqa: SLF001
                database_settings
            ),
        )

        cli._assert_production_execution_allowed(  # noqa: SLF001
            environment=AppEnvironment.PRODUCTION,
            database_settings=database_settings,
        )

        assert os.getenv(INITIAL_ADMIN_BOOTSTRAP_SECRET_ENV) is None
        assert os.getenv(INITIAL_ADMIN_BOOTSTRAP_SECRET_CONFIRM_ENV) is None
        with pytest.raises(RuntimeError):
            cli._assert_production_execution_allowed(  # noqa: SLF001
                environment=AppEnvironment.PRODUCTION,
                database_settings=database_settings,
            )

    def test_cli_database_fingerprint_should_not_depend_on_password(self) -> None:
        """
        验证生产目标库指纹不会依赖连接串密码。
        """

        cli = InitialAdminCli(
            stdin=StringIO(),
            stdout=StringIO(INITIAL_ADMIN_STDOUT_EMPTY),
            interactive=False,
        )

        assert cli._build_database_fingerprint(  # noqa: SLF001
            self._build_database_settings()
        ) == cli._build_database_fingerprint(  # noqa: SLF001
            self._build_database_settings(
                database_url=INITIAL_ADMIN_DATABASE_URL_WITH_OTHER_PASSWORD
            )
        )

    def _set_production_bootstrap_env(
        self,
        monkeypatch,
        *,
        database_fingerprint: str,
        bootstrap_secret_confirm: str = INITIAL_ADMIN_BOOTSTRAP_SECRET,
    ) -> None:
        """
        设置生产初始管理员创建测试所需的环境变量。
        """

        monkeypatch.setenv(
            INITIAL_ADMIN_ALLOW_PRODUCTION_ENV,
            INITIAL_ADMIN_ALLOW_PRODUCTION_VALUE,
        )
        monkeypatch.setenv(
            INITIAL_ADMIN_DATABASE_FINGERPRINT_ENV,
            database_fingerprint,
        )
        monkeypatch.setenv(
            INITIAL_ADMIN_BOOTSTRAP_SECRET_ENV,
            INITIAL_ADMIN_BOOTSTRAP_SECRET,
        )
        monkeypatch.setenv(
            INITIAL_ADMIN_BOOTSTRAP_SECRET_CONFIRM_ENV,
            bootstrap_secret_confirm,
        )

    def _build_database_settings(
        self,
        *,
        database_url: str = INITIAL_ADMIN_DATABASE_URL,
    ) -> DatabaseRuntimeSettings:
        """
        构建初始管理员 CLI 测试数据库配置。
        """

        return DatabaseRuntimeSettings(
            backend=DatabaseBackend.POSTGRESQL,
            url=database_url,
            schema_name=INITIAL_ADMIN_DATABASE_SCHEMA,
            echo=False,
            pool_size=1,
            max_overflow=1,
            pool_recycle_seconds=1,
            connect_timeout_seconds=1,
            auto_upgrade_on_startup=False,
        )
