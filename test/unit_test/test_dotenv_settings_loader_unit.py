"""
dotenv 配置加载单元测试。
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
from src.infrastructure.settings.dotenv_settings_loader import DotenvSettingsLoader

DOTENV_CONTENT = """
# 本地开发变量
JWT_SECRET=dotenv-jwt-secret-minimum-32-characters
AUTH_BOOTSTRAP_ADMIN_PASSWORD=dotenv-admin-password
"""
PROCESS_JWT_SECRET = "process-jwt-secret-minimum-32-characters"
DOTENV_JWT_SECRET = "dotenv-jwt-secret-minimum-32-characters"
DOTENV_ADMIN_PASSWORD = "dotenv-admin-password"


class TestDotenvSettingsLoaderUnit:
    """
    dotenv 配置加载单元测试集合。
    """

    def test_loader_when_dotenv_exists_should_parse_simple_values(self, tmp_path: Path) -> None:
        """
        验证 dotenv 存在时应解析简单键值。
        """

        dotenv_path = tmp_path / ".env"
        dotenv_path.write_text(DOTENV_CONTENT, encoding="utf-8")
        result = DotenvSettingsLoader().load(
            dotenv_path=dotenv_path,
            environment=AppEnvironment.DEVELOPMENT.value,
            enabled=True,
        )
        assert result.variables[JWT_SECRET_ENVIRONMENT_VARIABLE] == DOTENV_JWT_SECRET
        assert (
            result.variables[AUTH_BOOTSTRAP_ADMIN_PASSWORD_ENVIRONMENT_VARIABLE]
            == DOTENV_ADMIN_PASSWORD
        )
        assert result.source_envelope.detail.existing is True

    def test_loader_when_dotenv_missing_should_return_empty_mapping(
        self,
        tmp_path: Path,
    ) -> None:
        """
        验证 dotenv 缺失时应返回空配置。
        """

        result = DotenvSettingsLoader().load(
            dotenv_path=tmp_path / ".env",
            environment=AppEnvironment.DEVELOPMENT.value,
            enabled=True,
        )
        assert result.variables == {}
        assert result.source_envelope.detail.existing is False

    def test_app_loader_when_development_secret_missing_should_use_dotenv(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证开发环境缺失进程密钥时应读取 dotenv。
        """

        config_root = self._copy_config_to_temp(tmp_path)
        (tmp_path / ".env").write_text(DOTENV_CONTENT, encoding="utf-8")
        monkeypatch.delenv(JWT_SECRET_ENVIRONMENT_VARIABLE, raising=False)
        monkeypatch.delenv(
            AUTH_BOOTSTRAP_ADMIN_PASSWORD_ENVIRONMENT_VARIABLE,
            raising=False,
        )

        settings = AppSettingsLoader(config_root=config_root).load_for_environment(
            AppEnvironment.DEVELOPMENT
        )

        assert settings.runtime.auth.jwt_secret.get_secret_value() == DOTENV_JWT_SECRET
        assert (
            settings.modules.auth.bootstrap_admin.password_plain.get_secret_value()
            == DOTENV_ADMIN_PASSWORD
        )

    def test_app_loader_when_process_secret_exists_should_override_dotenv(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证进程环境变量优先级应高于 dotenv。
        """

        config_root = self._copy_config_to_temp(tmp_path)
        (tmp_path / ".env").write_text(DOTENV_CONTENT, encoding="utf-8")
        monkeypatch.setenv(JWT_SECRET_ENVIRONMENT_VARIABLE, PROCESS_JWT_SECRET)

        settings = AppSettingsLoader(config_root=config_root).load_for_environment(
            AppEnvironment.DEVELOPMENT
        )

        assert settings.runtime.auth.jwt_secret.get_secret_value() == PROCESS_JWT_SECRET

    def test_app_loader_when_production_secret_only_in_dotenv_should_fail(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证生产环境不会从仓库 dotenv 补齐 JWT 密钥。
        """

        config_root = self._copy_config_to_temp(tmp_path)
        (tmp_path / ".env").write_text(DOTENV_CONTENT, encoding="utf-8")
        monkeypatch.delenv(JWT_SECRET_ENVIRONMENT_VARIABLE, raising=False)

        with pytest.raises(ValueError) as fault:
            AppSettingsLoader(config_root=config_root).load_for_environment(
                AppEnvironment.PRODUCTION
            )

        assert "JWT_SECRET" in str(fault.value)

    def _copy_config_to_temp(self, tmp_path: Path) -> Path:
        """
        复制配置目录到临时目录。
        """

        config_root = tmp_path / "config"
        shutil.copytree(Path("config"), config_root)
        return config_root
