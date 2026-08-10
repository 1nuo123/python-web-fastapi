"""
生产安全配置集成测试模块。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from src.core.cache_contract.cache_runtime_contract import (
    REDIS_CACHE_BACKEND_KIND,
    CacheBackend,
)
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.docker,
    pytest.mark.usefixtures("integration_database"),
]


PRODUCTION_JWT_SECRET = "production-jwt-secret-minimum-32-characters"
PRODUCTION_DATABASE_URL = (
    "postgresql+psycopg://fastapi:production-postgres-password@postgres:5432/fastapi_web_skeleton"
)
PRODUCTION_REDIS_URL = "redis://:production-redis-password@redis:6379/0"
PRODUCTION_RABBITMQ_URL = "amqp://fastapi:production-rabbitmq-password@rabbitmq:5672/%2F"
COMPOSE_PROJECT_ROOT = Path(__file__).resolve().parents[2]
POSTGRES_PUBLIC_PORT_FRAGMENT = "0.0.0.0:55432"
REDIS_PUBLIC_PORT_FRAGMENT = "0.0.0.0:56379"
RABBITMQ_PUBLIC_PORT_FRAGMENT = "0.0.0.0:15672"
RABBITMQ_GUEST_FRAGMENT = "guest:guest"
RABBITMQ_DOUBLE_SLASH_FRAGMENT = ":5672//"
RABBITMQ_ENCODED_ROOT_VHOST_FRAGMENT = ":5672/%2F"
PRODUCTION_ENV_FILE_NAME = ".env.production.example"
LOCAL_DEV_SECRET_FRAGMENT = "local-dev"
APP_SERVICE_KEY = "app"
PRODUCTION_APP_PIDS_LIMIT = 256
PRODUCTION_LOG_PATH = "/tmp/logs"
LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE = "LOGGING_ENTRY_LOG_PATH"
ALL_CAPABILITIES = "ALL"
NO_NEW_PRIVILEGES_SECURITY_OPTION = "no-new-privileges:true"
RABBITMQ_PORT_CONNECTIVITY_COMMAND = "check_port_connectivity"


class ComposeHealthcheckConfig(BaseModel):
    """Compose 健康检查强类型配置。"""

    model_config = ConfigDict(extra="ignore")

    test: list[str]


class ProductionAppComposeConfig(BaseModel):
    """生产应用 Compose 强类型配置。"""

    model_config = ConfigDict(extra="ignore")

    read_only: bool
    pids_limit: int
    cap_drop: list[str]
    security_opt: list[str]
    environment: dict[str, str]


class ProductionRabbitMqComposeConfig(BaseModel):
    """生产 RabbitMQ Compose 强类型配置。"""

    model_config = ConfigDict(extra="ignore")

    healthcheck: ComposeHealthcheckConfig


class ProductionComposeServicesConfig(BaseModel):
    """生产 Compose 服务强类型配置。"""

    model_config = ConfigDict(extra="ignore")

    app: ProductionAppComposeConfig
    rabbitmq: ProductionRabbitMqComposeConfig


class ProductionComposeConfig(BaseModel):
    """生产 Compose 渲染结果强类型配置。"""

    model_config = ConfigDict(extra="ignore")

    services: ProductionComposeServicesConfig


class TestSecurityProductionIntegration:
    """
    生产安全配置集成测试集合。
    """

    def test_production_loader_should_use_external_secret_and_redis(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证生产配置加载应使用外部密钥与 Redis 节流。
        """

        monkeypatch.setenv("DATABASE_URL", PRODUCTION_DATABASE_URL)
        monkeypatch.setenv("JWT_SECRET", PRODUCTION_JWT_SECRET)
        monkeypatch.setenv("REDIS_URL", PRODUCTION_REDIS_URL)
        monkeypatch.setenv("RABBITMQ_URL", PRODUCTION_RABBITMQ_URL)

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.PRODUCTION)

        assert settings.runtime.auth.jwt_secret.get_secret_value() == PRODUCTION_JWT_SECRET
        assert settings.runtime.cache.backend is CacheBackend.REDIS
        assert settings.runtime.cache.backend_detail.kind == REDIS_CACHE_BACKEND_KIND
        assert settings.runtime.redis_resource.detail.url == PRODUCTION_REDIS_URL

    def test_production_compose_config_should_not_publish_internal_ports(self) -> None:
        """
        验证生产 Compose 配置不发布内部服务端口到公网宿主机。
        """

        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "compose.yml",
                "-f",
                "compose.production.yml",
                "config",
            ],
            cwd=COMPOSE_PROJECT_ROOT,
            env=self._build_compose_env(),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        compose_config = result.stdout
        assert POSTGRES_PUBLIC_PORT_FRAGMENT not in compose_config
        assert REDIS_PUBLIC_PORT_FRAGMENT not in compose_config
        assert RABBITMQ_PUBLIC_PORT_FRAGMENT not in compose_config
        assert RABBITMQ_GUEST_FRAGMENT not in compose_config
        assert RABBITMQ_DOUBLE_SLASH_FRAGMENT not in compose_config
        assert RABBITMQ_ENCODED_ROOT_VHOST_FRAGMENT in compose_config

    def test_production_compose_example_env_should_render_encoded_rabbitmq_vhost(
        self,
    ) -> None:
        """
        验证生产示例 env 渲染 Compose 时使用 RabbitMQ 编码 root vhost。
        """

        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                PRODUCTION_ENV_FILE_NAME,
                "-f",
                "compose.yml",
                "-f",
                "compose.production.yml",
                "config",
            ],
            cwd=COMPOSE_PROJECT_ROOT,
            env=self._build_isolated_process_env(),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        compose_config = result.stdout
        assert RABBITMQ_DOUBLE_SLASH_FRAGMENT not in compose_config
        assert RABBITMQ_ENCODED_ROOT_VHOST_FRAGMENT in compose_config
        assert LOCAL_DEV_SECRET_FRAGMENT not in compose_config

    def test_production_app_should_keep_bounded_read_only_runtime(self) -> None:
        """验证生产应用具备只读文件系统、进程上限和可写日志边界。"""

        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "compose.yml",
                "-f",
                "compose.production.yml",
                "config",
                "--format",
                "json",
            ],
            cwd=COMPOSE_PROJECT_ROOT,
            env=self._build_compose_env(),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        app_config = ProductionComposeConfig.model_validate_json(result.stdout).services.app
        assert app_config.read_only is True
        assert app_config.pids_limit == PRODUCTION_APP_PIDS_LIMIT
        assert app_config.cap_drop == [ALL_CAPABILITIES]
        assert NO_NEW_PRIVILEGES_SECURITY_OPTION in app_config.security_opt
        assert (
            app_config.environment[LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE]
            == PRODUCTION_LOG_PATH
        )

    def test_rabbitmq_healthcheck_should_wait_for_listener_connectivity(self) -> None:
        """验证应用启动门禁等待 RabbitMQ 监听端口真实可连接。"""

        result = subprocess.run(
            [
                "docker",
                "compose",
                "-f",
                "compose.yml",
                "-f",
                "compose.production.yml",
                "config",
                "--format",
                "json",
            ],
            cwd=COMPOSE_PROJECT_ROOT,
            env=self._build_compose_env(),
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0
        compose_config = ProductionComposeConfig.model_validate_json(result.stdout)
        assert (
            RABBITMQ_PORT_CONNECTIVITY_COMMAND in compose_config.services.rabbitmq.healthcheck.test
        )

    def _build_isolated_process_env(self) -> dict[str, str]:
        """
        构建隔离宿主敏感变量的进程环境。
        """

        compose_env = dict(os.environ)
        for variable_name in (
            "POSTGRES_PASSWORD",
            "RABBITMQ_DEFAULT_PASS",
            "RABBITMQ_URL",
            "REDIS_URL",
        ):
            compose_env.pop(variable_name, None)
        return compose_env

    def _build_compose_env(self) -> dict[str, str]:
        """
        构建生产 Compose 配置校验所需环境变量。
        """

        compose_env = dict(os.environ)
        compose_env.update(
            {
                "POSTGRES_DB": "fastapi_web_skeleton",
                "POSTGRES_USER": "fastapi_prod",
                "POSTGRES_PASSWORD": "production-postgres-password",
                "REDIS_PASSWORD": "production-redis-password",
                "JWT_SECRET": PRODUCTION_JWT_SECRET,
                "RABBITMQ_DEFAULT_USER": "fastapi_prod",
                "RABBITMQ_DEFAULT_PASS": "production-rabbitmq-password",
                "RABBITMQ_DEFAULT_VHOST": "/",
                "RABBITMQ_VHOST_ENCODED": "%2F",
            }
        )
        return compose_env
