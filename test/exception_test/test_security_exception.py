"""
安全异常路径测试模块。
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    DATABASE_URL_ENVIRONMENT_VARIABLE,
    JWT_SECRET_ENVIRONMENT_VARIABLE,
    RABBITMQ_URL_ENVIRONMENT_VARIABLE,
    REDIS_URL_ENVIRONMENT_VARIABLE,
    AppEnvironment,
)

EXCEPTION_PATH = "/security-exception-test"
SENSITIVE_DETAIL = "postgresql+psycopg://user:secret-password@db:5432/app"
PRODUCTION_JWT_SECRET = "production-jwt-secret-minimum-32-characters"
PRODUCTION_DATABASE_URL = (
    "postgresql+psycopg://fastapi_prod:production-postgres-password@postgres:5432/"
    "fastapi_web_skeleton"
)
PRODUCTION_REDIS_URL = "redis://:production-redis-password@redis:6379/0"
PRODUCTION_RABBITMQ_URL = "amqp://fastapi:production-rabbitmq-password@rabbitmq:5672/"


class TestSecurityException:
    """
    安全异常路径测试集合。
    """

    def test_loader_when_security_runtime_missing_should_raise_config_fault(
        self,
        tmp_path,
        monkeypatch,
    ) -> None:
        """
        验证安全运行时配置缺失时应抛出配置错误。
        """

        config_root = tmp_path / "config"
        config_root.mkdir()
        monkeypatch.setenv(JWT_SECRET_ENVIRONMENT_VARIABLE, PRODUCTION_JWT_SECRET)
        monkeypatch.setenv(DATABASE_URL_ENVIRONMENT_VARIABLE, PRODUCTION_DATABASE_URL)
        monkeypatch.setenv(REDIS_URL_ENVIRONMENT_VARIABLE, PRODUCTION_REDIS_URL)
        monkeypatch.setenv(
            RABBITMQ_URL_ENVIRONMENT_VARIABLE,
            PRODUCTION_RABBITMQ_URL,
        )

        with pytest.raises(Exception) as fault:
            AppSettingsLoader(config_root=config_root).load_for_environment(
                AppEnvironment.PRODUCTION
            )

        assert "配置" in str(fault.value)

    def test_unexpected_exception_response_should_hide_sensitive_detail(self) -> None:
        """
        验证未预期异常响应隐藏敏感详情。
        """

        app = TestAppFactory().create()
        self._bind_exception_route(app)

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get(EXCEPTION_PATH)

        assert response.status_code == 500
        assert SENSITIVE_DETAIL not in response.text
        assert "detail" not in response.json()["data"]

    def _bind_exception_route(self, app: FastAPI) -> None:
        """
        绑定触发敏感异常的测试路由。
        """

        @app.get(EXCEPTION_PATH)
        def raise_security_exception() -> None:
            raise RuntimeError(SENSITIVE_DETAIL)
