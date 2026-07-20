"""
FastAPI OpenAPI 安全公开面单元测试模块。
"""

from __future__ import annotations

from src.api.fastapi_app_assembler import FastApiAppAssembler
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
OPENAPI_PATH = "/openapi.json"
DOCS_PATH = "/docs"
REDOC_PATH = "/redoc"


class TestFastApiOpenApiSurfaceUnit:
    """
    FastAPI OpenAPI 安全公开面单元测试集合。
    """

    def test_production_app_should_not_mount_openapi_routes(self, monkeypatch) -> None:
        """
        验证生产应用路由表不挂载 OpenAPI 文档入口。
        """

        monkeypatch.setenv(JWT_SECRET_ENVIRONMENT_VARIABLE, PRODUCTION_JWT_SECRET)
        monkeypatch.setenv(DATABASE_URL_ENVIRONMENT_VARIABLE, PRODUCTION_DATABASE_URL)
        monkeypatch.setenv(REDIS_URL_ENVIRONMENT_VARIABLE, PRODUCTION_REDIS_URL)
        monkeypatch.setenv(RABBITMQ_URL_ENVIRONMENT_VARIABLE, PRODUCTION_RABBITMQ_URL)
        app = FastApiAppAssembler()(environment=AppEnvironment.PRODUCTION)

        assert app.openapi_url is None
        assert app.docs_url is None
        assert app.redoc_url is None

    def test_test_app_should_keep_openapi_routes(self) -> None:
        """
        验证测试环境仍保留 OpenAPI 文档入口。
        """

        app = FastApiAppAssembler()(environment=AppEnvironment.TEST)

        assert app.openapi_url == OPENAPI_PATH
        assert app.docs_url == DOCS_PATH
        assert app.redoc_url == REDOC_PATH
