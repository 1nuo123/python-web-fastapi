"""
安全配置单元测试模块。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import rtoml
from pydantic import SecretStr

from src.core.auth_contract.bootstrap_role_binding_contract import (
    BOOTSTRAP_ROLE_BINDING_KIND,
    BOOTSTRAP_ROLE_BINDING_SCHEMA_VERSION,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.core.task_contract.task_registration_contract import (
    TASK_REGISTRATION_ENVELOPE_KIND,
    TASK_REGISTRATION_HEADER_KIND,
    TASK_REGISTRATION_SCHEMA_VERSION,
)
from src.core.task_contract.task_runtime_contract import (
    FUNBOOST_RABBITMQ_COMPLEX_ROUTING_BROKER_KIND,
    FUNBOOST_TASK_BACKEND_KIND,
    LOCAL_TASK_BACKEND_KIND,
)
from src.domain.auth.auth_role_key import AuthRoleKey
from src.domain.auth.auth_scope_code import AuthScopeCode
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    DATABASE_URL_ENVIRONMENT_VARIABLE,
    JWT_SECRET_ENVIRONMENT_VARIABLE,
    RABBITMQ_URL_ENVIRONMENT_VARIABLE,
    REDIS_URL_ENVIRONMENT_VARIABLE,
    AppEnvironment,
    DatabaseBackend,
    DatabaseRuntimeSettings,
)

PRODUCTION_JWT_SECRET = "production-jwt-secret-minimum-32-characters"
PRODUCTION_DATABASE_URL = (
    "postgresql+psycopg://fastapi_prod:production-postgres-password@postgres:5432/"
    "fastapi_web_skeleton"
)
PRODUCTION_REDIS_URL = "redis://:production-redis-password@redis:6379/0"
PRODUCTION_RABBITMQ_URL = "amqp://fastapi:production-rabbitmq-password@rabbitmq:5672/"
PRODUCTION_BOOTSTRAP_ADMIN_PASSWORD = "production-bootstrap-admin-password"
JWT_SECRET_MASK = "**********"
RUNTIME_SECTION_KEY = "runtime"
WEB_SECTION_KEY = "web"
CORS_SECTION_KEY = "cors"
CORS_ENABLED_FIELD = "enabled"
CORS_ALLOW_ORIGINS_FIELD = "allow_origins"
CORS_ALLOW_METHODS_FIELD = "allow_methods"
CORS_ALLOW_HEADERS_FIELD = "allow_headers"
CORS_ALLOW_CREDENTIALS_FIELD = "allow_credentials"
CORS_ALLOWED_ORIGIN = "https://admin.example.test"
CORS_ALLOWED_METHOD = "GET"
CORS_ALLOWED_HEADER = "Authorization"
CORS_WILDCARD_ORIGIN = "*"
LOCALHOST_CORS_ORIGIN = "http://localhost:3000"
CUSTOM_TRUSTED_PROXY_CIDR = "10.20.0.0/16"
PRODUCTION_TRUSTED_PROXY_CIDR = "172.30.0.0/24"
SECURITY_SECTION_KEY = "security"
DETAIL_SECTION_KEY = "detail"
PROTECTION_SECTION_KEY = "protection"
OUTBOUND_URL_SAFETY_SECTION_KEY = "outbound_url_safety"
OUTBOUND_URL_SAFETY_ENABLED_FIELD = "enabled"
OUTBOUND_URL_SAFETY_ENFORCE_ALLOWED_HOSTNAMES_FIELD = "enforce_allowed_hostnames"
OUTBOUND_URL_SAFETY_ALLOWED_HOSTNAMES_FIELD = "allowed_hostnames"
PRODUCTION_OUTBOUND_HOST_ALLOWLIST_MESSAGE = "目的域名允许清单"
TASK_MODULE_SECTION_KEY = "task_module"
DEFAULT_RETRY_LIMIT_FIELD = "default_retry_limit"
DEFAULT_JOB_KIND_FIELD = "default_job_kind"
REGISTRATIONS_FIELD = "registrations"
ENVELOPE_KIND_FIELD = "envelope_kind"
SCHEMA_VERSION_FIELD = "schema_version"
HEADER_FIELD = "header"
HEADER_KIND_FIELD = "header_kind"
TASK_NAME_FIELD = "task_name"
JOB_KIND_FIELD = "job_kind"
ENABLED_FIELD = "enabled"
BACKEND_FIELD = "backend"
DETAIL_FIELD = "detail"
KIND_FIELD = "kind"
RETRY_LIMIT_FIELD = "retry_limit"
QUEUE_NAME_FIELD = "queue_name"
EXCHANGE_NAME_FIELD = "exchange_name"
ROUTING_KEY_FIELD = "routing_key"
BROKER_KIND_FIELD = "broker_kind"
CONSUMER_WORKER_COUNT_FIELD = "consumer_worker_count"
PRODUCTION_TASK_JOB_KIND = "task_execution_probe"
PRODUCTION_TASK_NAME = "task_execution_probe"
PRODUCTION_TASK_QUEUE_NAME = "task.execution.probe"
PRODUCTION_TASK_EXCHANGE_NAME = "task.direct"
PRODUCTION_TASK_ROUTING_KEY = "task.execution.probe"
PRODUCTION_TASK_RETRY_LIMIT = 3
PRODUCTION_TASK_WORKER_COUNT = 2
LOCAL_TASK_JOB_KIND = "demo_task"
TASK_DEFAULT_DISABLED_MESSAGE = "default_job_kind 对应任务必须启用"
TASK_DEFAULT_BACKEND_MISMATCH_MESSAGE = "default_job_kind 对应任务 backend"
RABBITMQ_MESSAGE_BACKEND_KIND = "rabbitmq"
DATABASE_SCHEMA_NAME = "TenantSchema_01"
DATABASE_SCHEMA_NAME_WITH_SPACE = "tenant schema"
DATABASE_SCHEMA_NAME_WITH_SEPARATOR = "tenant;drop"
DATABASE_POOL_SIZE = 5
DATABASE_MAX_OVERFLOW = 10
DATABASE_POOL_RECYCLE_SECONDS = 1800
DATABASE_CONNECT_TIMEOUT_SECONDS = 5
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASE_RUNTIME_CONFIG_DIRECTORY = PROJECT_ROOT / "config" / "runtime" / "database_runtime"
DATABASE_RUNTIME_CONFIG_PATHS = (
    DATABASE_RUNTIME_CONFIG_DIRECTORY / "database_runtime_base.toml",
    DATABASE_RUNTIME_CONFIG_DIRECTORY / "database_runtime_development.toml",
    DATABASE_RUNTIME_CONFIG_DIRECTORY / "database_runtime_test.toml",
    DATABASE_RUNTIME_CONFIG_DIRECTORY / "database_runtime_production.toml",
)
AUTO_UPGRADE_ON_STARTUP_FIELD = "auto_upgrade_on_startup"
DATABASE_AUTO_UPGRADE_DISABLED = False


class TestSettingsSecurityUnit:
    """
    安全配置单元测试集合。
    """

    def test_loader_when_production_jwt_missing_should_fail(self, monkeypatch) -> None:
        """
        验证生产环境缺失 JWT 密钥时应启动失败。
        """

        monkeypatch.delenv(JWT_SECRET_ENVIRONMENT_VARIABLE, raising=False)

        with pytest.raises(ValueError) as fault:
            AppSettingsLoader().load_for_environment(AppEnvironment.PRODUCTION)

        assert "JWT_SECRET" in str(fault.value)

    def test_loader_when_production_jwt_weak_should_fail(self, monkeypatch) -> None:
        """
        验证生产环境使用弱 JWT 密钥时应启动失败。
        """

        monkeypatch.setenv(
            JWT_SECRET_ENVIRONMENT_VARIABLE,
            "change-me-jwt-secret-with-safe-length",
        )

        with pytest.raises(ValueError) as fault:
            AppSettingsLoader().load_for_environment(AppEnvironment.PRODUCTION)

        assert "弱密钥" in str(fault.value)

    def test_loader_when_production_database_url_missing_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产环境缺失数据库连接串时应启动失败。
        """

        monkeypatch.setenv(JWT_SECRET_ENVIRONMENT_VARIABLE, PRODUCTION_JWT_SECRET)
        monkeypatch.delenv(DATABASE_URL_ENVIRONMENT_VARIABLE, raising=False)
        monkeypatch.setenv(REDIS_URL_ENVIRONMENT_VARIABLE, PRODUCTION_REDIS_URL)
        monkeypatch.setenv(
            RABBITMQ_URL_ENVIRONMENT_VARIABLE,
            PRODUCTION_RABBITMQ_URL,
        )

        with pytest.raises(ValueError) as fault:
            AppSettingsLoader().load_for_environment(AppEnvironment.PRODUCTION)

        assert "DATABASE_URL" in str(fault.value)

    def test_loader_when_production_redis_url_missing_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产环境缺失 Redis 连接串时应启动失败。
        """

        monkeypatch.setenv(JWT_SECRET_ENVIRONMENT_VARIABLE, PRODUCTION_JWT_SECRET)
        monkeypatch.setenv(DATABASE_URL_ENVIRONMENT_VARIABLE, PRODUCTION_DATABASE_URL)
        monkeypatch.delenv(REDIS_URL_ENVIRONMENT_VARIABLE, raising=False)
        monkeypatch.setenv(
            RABBITMQ_URL_ENVIRONMENT_VARIABLE,
            PRODUCTION_RABBITMQ_URL,
        )

        with pytest.raises(ValueError) as fault:
            AppSettingsLoader().load_for_environment(AppEnvironment.PRODUCTION)

        assert "REDIS_URL" in str(fault.value)

    def test_loader_when_production_redis_url_without_password_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产 Redis 连接串缺少认证密码时应失败。
        """

        monkeypatch.setenv(JWT_SECRET_ENVIRONMENT_VARIABLE, PRODUCTION_JWT_SECRET)
        monkeypatch.setenv(DATABASE_URL_ENVIRONMENT_VARIABLE, PRODUCTION_DATABASE_URL)
        monkeypatch.setenv(REDIS_URL_ENVIRONMENT_VARIABLE, "redis://redis:6379/0")
        monkeypatch.setenv(
            RABBITMQ_URL_ENVIRONMENT_VARIABLE,
            PRODUCTION_RABBITMQ_URL,
        )

        with pytest.raises(ValueError) as fault:
            AppSettingsLoader().load_for_environment(AppEnvironment.PRODUCTION)

        assert "认证密码" in str(fault.value)

    def test_loader_when_production_rabbitmq_guest_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产 RabbitMQ 使用 guest/guest 时应失败。
        """

        monkeypatch.setenv(JWT_SECRET_ENVIRONMENT_VARIABLE, PRODUCTION_JWT_SECRET)
        monkeypatch.setenv(DATABASE_URL_ENVIRONMENT_VARIABLE, PRODUCTION_DATABASE_URL)
        monkeypatch.setenv(REDIS_URL_ENVIRONMENT_VARIABLE, PRODUCTION_REDIS_URL)
        monkeypatch.setenv(
            RABBITMQ_URL_ENVIRONMENT_VARIABLE,
            "amqp://guest:guest@rabbitmq:5672/",
        )

        with pytest.raises(ValueError) as fault:
            AppSettingsLoader().load_for_environment(AppEnvironment.PRODUCTION)

        assert "guest/guest" in str(fault.value)

    def test_loader_when_production_memory_cache_should_fail(self, monkeypatch) -> None:
        """
        验证生产环境使用内存缓存时应失败。
        """

        self._set_production_secret_env(monkeypatch)

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.PRODUCTION,
                overrides={
                    "runtime": {
                        "cache": {
                            "backend": "memory",
                            "backend_detail": {
                                "kind": "memory_cache_backend",
                                "schema_version": "1.0",
                                "max_entries": 128,
                            },
                        }
                    }
                },
            )

        assert "Redis" in str(fault.value.detail)

    def test_loader_when_production_bootstrap_admin_enabled_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产环境启用 bootstrap admin 时应失败。
        """

        self._set_production_secret_env(monkeypatch)

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.PRODUCTION,
                overrides={
                    "auth_module": {
                        "bootstrap_admin": {
                            "enabled": True,
                            "username": "admin",
                            "subject_id": "user-admin",
                            "password_plain": PRODUCTION_BOOTSTRAP_ADMIN_PASSWORD,
                            "role_bindings": [
                                {
                                    "kind": BOOTSTRAP_ROLE_BINDING_KIND,
                                    "schema_version": (BOOTSTRAP_ROLE_BINDING_SCHEMA_VERSION),
                                    "role_key": AuthRoleKey.ADMIN.value,
                                    "scope_codes": [AuthScopeCode.SYSTEM_READ.value],
                                }
                            ],
                        }
                    }
                },
            )

        assert "bootstrap admin" in str(fault.value.detail)

    def test_loader_when_production_security_runtime_valid_should_load(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产安全运行时配置满足基线时应加载成功。
        """

        self._set_production_secret_env(monkeypatch)

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.PRODUCTION)

        assert settings.app.enable_openapi is False
        assert settings.runtime.security.detail.expose_openapi is False
        assert settings.runtime.security.detail.require_external_jwt_secret is True
        assert settings.runtime.security.detail.protection.client_ip.trusted_proxy_cidr_blocks == [
            PRODUCTION_TRUSTED_PROXY_CIDR
        ]
        assert (
            settings.runtime.security.detail.protection.outbound_url_safety.enforce_allowed_hostnames
            is True
        )
        assert (
            settings.runtime.security.detail.protection.outbound_url_safety.allowed_hostnames == []
        )
        assert settings.runtime.task.backend == FUNBOOST_TASK_BACKEND_KIND
        assert settings.runtime.message.backend.value == RABBITMQ_MESSAGE_BACKEND_KIND
        assert settings.runtime.task.worker_enabled is False
        assert settings.runtime.database.auto_upgrade_on_startup is DATABASE_AUTO_UPGRADE_DISABLED

    def test_database_runtime_configs_should_keep_startup_auto_upgrade_disabled(
        self,
    ) -> None:
        """
        验证数据库运行时配置文件不会重新开启启动期自动迁移。
        """

        for config_path in DATABASE_RUNTIME_CONFIG_PATHS:
            config = rtoml.load(config_path)
            runtime_config = config[RUNTIME_SECTION_KEY]

            assert (
                runtime_config.get(
                    AUTO_UPGRADE_ON_STARTUP_FIELD,
                    DATABASE_AUTO_UPGRADE_DISABLED,
                )
                is DATABASE_AUTO_UPGRADE_DISABLED
            )

    def test_loader_should_keep_database_startup_auto_upgrade_disabled(self) -> None:
        """
        验证开发和测试环境最终配置保持关闭启动期自动迁移。
        """

        for environment in [AppEnvironment.DEVELOPMENT, AppEnvironment.TEST]:
            settings = AppSettingsLoader().load_for_environment(environment)

            assert (
                settings.runtime.database.auto_upgrade_on_startup is DATABASE_AUTO_UPGRADE_DISABLED
            )

    def test_loader_should_mount_client_ip_trusted_proxy_cidrs(self) -> None:
        """
        验证可信代理 CIDR 是安全运行时一等配置。
        """

        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={
                "runtime": {
                    "security": {
                        "detail": {
                            "protection": {
                                "client_ip": {
                                    "trusted_proxy_cidr_blocks": [CUSTOM_TRUSTED_PROXY_CIDR]
                                }
                            }
                        }
                    }
                }
            },
        )

        assert settings.runtime.security.detail.protection.client_ip.trusted_proxy_cidr_blocks == [
            CUSTOM_TRUSTED_PROXY_CIDR
        ]

    def test_loader_should_mount_outbound_allowed_hostnames(self) -> None:
        """
        验证出站目的域名允许清单是安全运行时一等配置。
        """

        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={
                RUNTIME_SECTION_KEY: {
                    SECURITY_SECTION_KEY: {
                        DETAIL_SECTION_KEY: {
                            PROTECTION_SECTION_KEY: {
                                OUTBOUND_URL_SAFETY_SECTION_KEY: {
                                    OUTBOUND_URL_SAFETY_ALLOWED_HOSTNAMES_FIELD: [
                                        CORS_ALLOWED_ORIGIN.removeprefix("https://")
                                    ],
                                    OUTBOUND_URL_SAFETY_ENFORCE_ALLOWED_HOSTNAMES_FIELD: (True),
                                }
                            }
                        }
                    }
                }
            },
        )

        assert (
            settings.runtime.security.detail.protection.outbound_url_safety.allowed_hostnames
            == [CORS_ALLOWED_ORIGIN.removeprefix("https://")]
        )
        assert (
            settings.runtime.security.detail.protection.outbound_url_safety.enforce_allowed_hostnames
            is True
        )

    def test_loader_when_production_outbound_allowlist_disabled_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产环境必须启用出站目的域名允许清单。
        """

        self._set_production_secret_env(monkeypatch)

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.PRODUCTION,
                overrides={
                    RUNTIME_SECTION_KEY: {
                        SECURITY_SECTION_KEY: {
                            DETAIL_SECTION_KEY: {
                                PROTECTION_SECTION_KEY: {
                                    OUTBOUND_URL_SAFETY_SECTION_KEY: {
                                        OUTBOUND_URL_SAFETY_ENFORCE_ALLOWED_HOSTNAMES_FIELD: (False)
                                    }
                                }
                            }
                        }
                    }
                },
            )

        assert PRODUCTION_OUTBOUND_HOST_ALLOWLIST_MESSAGE in str(fault.value.detail)

    def test_loader_when_production_outbound_safety_disabled_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产环境禁止关闭出站 URL 安全策略。
        """

        self._set_production_secret_env(monkeypatch)

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.PRODUCTION,
                overrides={
                    RUNTIME_SECTION_KEY: {
                        SECURITY_SECTION_KEY: {
                            DETAIL_SECTION_KEY: {
                                PROTECTION_SECTION_KEY: {
                                    OUTBOUND_URL_SAFETY_SECTION_KEY: {
                                        OUTBOUND_URL_SAFETY_ENABLED_FIELD: False
                                    }
                                }
                            }
                        }
                    }
                },
            )

        assert "出站 URL 安全策略" in str(fault.value.detail)

    def test_database_runtime_schema_should_accept_single_identifier(self) -> None:
        """
        验证数据库 schema 只接受单个 PostgreSQL 标识符。
        """

        settings = self._build_database_runtime_settings(DATABASE_SCHEMA_NAME)

        assert settings.schema_name == DATABASE_SCHEMA_NAME

    def test_database_runtime_schema_when_invalid_should_fail(self) -> None:
        """
        验证数据库 schema 包含空白或分隔符时应失败。
        """

        for schema_name in [
            DATABASE_SCHEMA_NAME_WITH_SPACE,
            DATABASE_SCHEMA_NAME_WITH_SEPARATOR,
        ]:
            with pytest.raises(ValueError) as fault:
                self._build_database_runtime_settings(schema_name)

            assert "PostgreSQL 标识符" in str(fault.value)

    def test_loader_when_cors_enabled_without_origin_should_fail(self) -> None:
        """
        验证启用 CORS 但允许源为空时应失败。
        """

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides=self._build_cors_override(allow_origins=[]),
            )

        assert "allow_origins" in str(fault.value.detail)

    def test_loader_when_cors_enabled_without_method_should_fail(self) -> None:
        """
        验证启用 CORS 但允许方法为空时应失败。
        """

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides=self._build_cors_override(allow_methods=[]),
            )

        assert "allow_methods" in str(fault.value.detail)

    def test_loader_when_cors_enabled_without_header_should_fail(self) -> None:
        """
        验证启用 CORS 但允许请求头为空时应失败。
        """

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides=self._build_cors_override(allow_headers=[]),
            )

        assert "allow_headers" in str(fault.value.detail)

    def test_loader_when_production_cors_wildcard_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产环境 CORS 允许源使用通配符时应失败。
        """

        self._set_production_secret_env(monkeypatch)

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.PRODUCTION,
                overrides=self._build_cors_override(
                    allow_origins=[CORS_WILDCARD_ORIGIN],
                ),
            )

        assert "CORS" in str(fault.value.detail)

    def test_loader_when_production_should_not_inherit_localhost_cors(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产 Web 运行时不会继承本地 CORS 入口。
        """

        self._set_production_secret_env(monkeypatch)

        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.PRODUCTION,
            overrides={},
        )

        assert settings.runtime.web.cors.enabled is False
        assert LOCALHOST_CORS_ORIGIN not in settings.runtime.web.cors.allow_origins

    def test_loader_when_production_default_task_disabled_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产默认任务注册项必须显式启用。
        """

        self._set_production_secret_env(monkeypatch)

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.PRODUCTION,
                overrides={
                    TASK_MODULE_SECTION_KEY: self._build_funboost_task_module_override(
                        enabled=False
                    )
                },
            )

        assert TASK_DEFAULT_DISABLED_MESSAGE in str(fault.value.detail)

    def test_loader_when_production_default_task_backend_mismatch_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产默认任务注册项后端必须与运行时后端一致。
        """

        self._set_production_secret_env(monkeypatch)

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.PRODUCTION,
                overrides={TASK_MODULE_SECTION_KEY: self._build_local_task_module_override()},
            )

        assert TASK_DEFAULT_BACKEND_MISMATCH_MESSAGE in str(fault.value.detail)

    def test_loader_when_production_external_jwt_flag_disabled_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产配置关闭外部 JWT 密钥强制项时应失败。
        """

        self._set_production_secret_env(monkeypatch)

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.PRODUCTION,
                overrides={
                    "runtime": {
                        "security": {
                            "detail": {
                                "kind": "production_security",
                                "schema_version": "1.0",
                                "expose_openapi": False,
                                "expose_system_info": False,
                                "require_external_jwt_secret": False,
                                "require_distributed_auth_throttle": True,
                                "enable_hsts": True,
                                "enable_csp": True,
                            }
                        }
                    }
                },
            )

        assert "外部 JWT 密钥" in str(fault.value.detail)

    def test_loader_when_production_distributed_throttle_flag_disabled_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产配置关闭分布式鉴权节流强制项时应失败。
        """

        self._set_production_secret_env(monkeypatch)

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.PRODUCTION,
                overrides={
                    "runtime": {
                        "security": {
                            "detail": {
                                "kind": "production_security",
                                "schema_version": "1.0",
                                "expose_openapi": False,
                                "expose_system_info": False,
                                "require_external_jwt_secret": True,
                                "require_distributed_auth_throttle": False,
                                "enable_hsts": True,
                                "enable_csp": True,
                            }
                        }
                    }
                },
            )

        assert "分布式鉴权节流" in str(fault.value.detail)

    def test_jwt_secret_should_keep_masked_in_settings_representation(self) -> None:
        """
        验证 JWT 密钥在配置对象展示中应保持脱敏。
        """

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)

        assert isinstance(settings.runtime.auth.jwt_secret, SecretStr)
        assert settings.runtime.auth.jwt_secret.get_secret_value() not in repr(
            settings.runtime.auth
        )
        assert settings.runtime.auth.model_dump(mode="json")["jwt_secret"] == (JWT_SECRET_MASK)

    def _set_production_secret_env(self, monkeypatch) -> None:
        """
        设置生产配置测试所需的外部敏感值。
        """

        monkeypatch.setenv(JWT_SECRET_ENVIRONMENT_VARIABLE, PRODUCTION_JWT_SECRET)
        monkeypatch.setenv(REDIS_URL_ENVIRONMENT_VARIABLE, PRODUCTION_REDIS_URL)
        monkeypatch.setenv(
            RABBITMQ_URL_ENVIRONMENT_VARIABLE,
            PRODUCTION_RABBITMQ_URL,
        )
        monkeypatch.setenv(
            DATABASE_URL_ENVIRONMENT_VARIABLE,
            os.getenv("DATABASE_URL", PRODUCTION_DATABASE_URL),
        )

    def _build_database_runtime_settings(
        self,
        schema_name: str,
    ) -> DatabaseRuntimeSettings:
        """
        构建数据库运行时设置。
        """

        return DatabaseRuntimeSettings(
            backend=DatabaseBackend.POSTGRESQL,
            url=PRODUCTION_DATABASE_URL,
            schema=schema_name,
            echo=False,
            pool_size=DATABASE_POOL_SIZE,
            max_overflow=DATABASE_MAX_OVERFLOW,
            pool_recycle_seconds=DATABASE_POOL_RECYCLE_SECONDS,
            connect_timeout_seconds=DATABASE_CONNECT_TIMEOUT_SECONDS,
            auto_upgrade_on_startup=False,
        )

    def _build_cors_override(
        self,
        *,
        allow_origins: list[str] | None = None,
        allow_methods: list[str] | None = None,
        allow_headers: list[str] | None = None,
    ) -> dict[str, object]:
        """
        构建 CORS 配置覆盖。
        """

        return {
            RUNTIME_SECTION_KEY: {
                WEB_SECTION_KEY: {
                    CORS_SECTION_KEY: {
                        CORS_ENABLED_FIELD: True,
                        CORS_ALLOW_ORIGINS_FIELD: (
                            [CORS_ALLOWED_ORIGIN] if allow_origins is None else allow_origins
                        ),
                        CORS_ALLOW_METHODS_FIELD: (
                            [CORS_ALLOWED_METHOD] if allow_methods is None else allow_methods
                        ),
                        CORS_ALLOW_HEADERS_FIELD: (
                            [CORS_ALLOWED_HEADER] if allow_headers is None else allow_headers
                        ),
                        CORS_ALLOW_CREDENTIALS_FIELD: True,
                    }
                }
            }
        }

    def _build_funboost_task_module_override(
        self,
        *,
        enabled: bool,
    ) -> dict[str, object]:
        """
        构建生产 Funboost 任务模块覆盖配置。
        """

        return {
            DEFAULT_RETRY_LIMIT_FIELD: PRODUCTION_TASK_RETRY_LIMIT,
            DEFAULT_JOB_KIND_FIELD: PRODUCTION_TASK_JOB_KIND,
            REGISTRATIONS_FIELD: [
                {
                    ENVELOPE_KIND_FIELD: TASK_REGISTRATION_ENVELOPE_KIND,
                    SCHEMA_VERSION_FIELD: TASK_REGISTRATION_SCHEMA_VERSION,
                    HEADER_FIELD: {
                        HEADER_KIND_FIELD: TASK_REGISTRATION_HEADER_KIND,
                        SCHEMA_VERSION_FIELD: TASK_REGISTRATION_SCHEMA_VERSION,
                        TASK_NAME_FIELD: PRODUCTION_TASK_NAME,
                        JOB_KIND_FIELD: PRODUCTION_TASK_JOB_KIND,
                        ENABLED_FIELD: enabled,
                        BACKEND_FIELD: FUNBOOST_TASK_BACKEND_KIND,
                    },
                    DETAIL_FIELD: {
                        KIND_FIELD: FUNBOOST_TASK_BACKEND_KIND,
                        SCHEMA_VERSION_FIELD: TASK_REGISTRATION_SCHEMA_VERSION,
                        QUEUE_NAME_FIELD: PRODUCTION_TASK_QUEUE_NAME,
                        EXCHANGE_NAME_FIELD: PRODUCTION_TASK_EXCHANGE_NAME,
                        ROUTING_KEY_FIELD: PRODUCTION_TASK_ROUTING_KEY,
                        BROKER_KIND_FIELD: (FUNBOOST_RABBITMQ_COMPLEX_ROUTING_BROKER_KIND),
                        RETRY_LIMIT_FIELD: PRODUCTION_TASK_RETRY_LIMIT,
                        CONSUMER_WORKER_COUNT_FIELD: PRODUCTION_TASK_WORKER_COUNT,
                    },
                }
            ],
        }

    def _build_local_task_module_override(self) -> dict[str, object]:
        """
        构建生产后端不一致的本地任务模块覆盖配置。
        """

        return {
            DEFAULT_RETRY_LIMIT_FIELD: PRODUCTION_TASK_RETRY_LIMIT,
            DEFAULT_JOB_KIND_FIELD: LOCAL_TASK_JOB_KIND,
            REGISTRATIONS_FIELD: [
                {
                    ENVELOPE_KIND_FIELD: TASK_REGISTRATION_ENVELOPE_KIND,
                    SCHEMA_VERSION_FIELD: TASK_REGISTRATION_SCHEMA_VERSION,
                    HEADER_FIELD: {
                        HEADER_KIND_FIELD: TASK_REGISTRATION_HEADER_KIND,
                        SCHEMA_VERSION_FIELD: TASK_REGISTRATION_SCHEMA_VERSION,
                        TASK_NAME_FIELD: PRODUCTION_TASK_NAME,
                        JOB_KIND_FIELD: LOCAL_TASK_JOB_KIND,
                        ENABLED_FIELD: True,
                        BACKEND_FIELD: LOCAL_TASK_BACKEND_KIND,
                    },
                    DETAIL_FIELD: {
                        KIND_FIELD: LOCAL_TASK_BACKEND_KIND,
                        SCHEMA_VERSION_FIELD: TASK_REGISTRATION_SCHEMA_VERSION,
                        RETRY_LIMIT_FIELD: PRODUCTION_TASK_RETRY_LIMIT,
                    },
                }
            ],
        }
