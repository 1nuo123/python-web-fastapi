"""
本地启动配置接口测试。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    AUTH_BOOTSTRAP_ADMIN_PASSWORD_ENVIRONMENT_VARIABLE,
    JWT_SECRET_ENVIRONMENT_VARIABLE,
    AppEnvironment,
)

LOCAL_STARTUP_DOTENV = """
JWT_SECRET=local-startup-jwt-secret-minimum-32-characters
AUTH_BOOTSTRAP_ADMIN_PASSWORD=local-startup-admin-password
"""


class TestLocalStartupInterface:
    """
    本地启动配置接口测试集合。
    """

    def test_local_development_startup_should_build_settings_from_dotenv(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证本地开发启动配置可由 dotenv 补齐。
        """

        config_root = tmp_path / "config"
        shutil.copytree(Path("config"), config_root)
        (tmp_path / ".env").write_text(LOCAL_STARTUP_DOTENV, encoding="utf-8")
        monkeypatch.delenv(JWT_SECRET_ENVIRONMENT_VARIABLE, raising=False)
        monkeypatch.delenv(
            AUTH_BOOTSTRAP_ADMIN_PASSWORD_ENVIRONMENT_VARIABLE,
            raising=False,
        )

        settings = AppSettingsLoader(config_root=config_root).load_for_environment(
            AppEnvironment.DEVELOPMENT
        )

        assert (
            settings.runtime.auth.jwt_secret.get_secret_value()
            == "local-startup-jwt-secret-minimum-32-characters"
        )
        assert (
            settings.modules.auth.bootstrap_admin.password_plain.get_secret_value()
            == "local-startup-admin-password"
        )
