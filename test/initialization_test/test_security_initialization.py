"""
安全初始化测试模块。
"""

from __future__ import annotations

import pytest

from src.api.fastapi_app_assembler import FastApiAppAssembler
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.settings.application_settings import (
    DATABASE_URL_ENVIRONMENT_VARIABLE,
    JWT_SECRET_ENVIRONMENT_VARIABLE,
    RABBITMQ_URL_ENVIRONMENT_VARIABLE,
    REDIS_URL_ENVIRONMENT_VARIABLE,
    AppEnvironment,
)

PRODUCTION_JWT_SECRET = "production-jwt-secret-minimum-32-characters"
PRODUCTION_DATABASE_URL = "postgresql+psycopg://app:production-password@database:5432/app"
PRODUCTION_REDIS_URL = "redis://:production-redis-password@redis:6379/0"
PRODUCTION_RABBITMQ_URL = "amqp://fastapi:production-rabbitmq-password@rabbitmq:5672/"


class TestSecurityInitialization:
    """
    安全初始化测试集合。
    """

    def test_production_app_initialization_should_keep_security_baseline(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产应用初始化应保持安全基线。
        """

        self._set_production_env(monkeypatch)

        app = FastApiAppAssembler()(environment=AppEnvironment.PRODUCTION)
        settings = app.state.container.settings_holder.current_settings

        assert settings.app.enable_openapi is False
        assert settings.runtime.security.detail.enable_hsts is True
        assert settings.runtime.security.detail.enable_csp is True

    def test_production_app_when_bootstrap_enabled_should_fail(
        self,
        monkeypatch,
    ) -> None:
        """
        验证生产应用启用 bootstrap admin 时初始化失败。
        """

        self._set_production_env(monkeypatch)

        with pytest.raises(HttpFaultException):
            FastApiAppAssembler()(
                environment=AppEnvironment.PRODUCTION,
                settings_overrides={
                    "auth_module": {
                        "bootstrap_admin": {
                            "enabled": True,
                            "username": "admin",
                            "subject_id": "user-admin",
                            "role_bindings": [],
                        }
                    }
                },
            )

    def _set_production_env(self, monkeypatch) -> None:
        """
        设置生产初始化所需的外部敏感值。
        """

        monkeypatch.setenv(JWT_SECRET_ENVIRONMENT_VARIABLE, PRODUCTION_JWT_SECRET)
        monkeypatch.setenv(DATABASE_URL_ENVIRONMENT_VARIABLE, PRODUCTION_DATABASE_URL)
        monkeypatch.setenv(REDIS_URL_ENVIRONMENT_VARIABLE, PRODUCTION_REDIS_URL)
        monkeypatch.setenv(RABBITMQ_URL_ENVIRONMENT_VARIABLE, PRODUCTION_RABBITMQ_URL)
