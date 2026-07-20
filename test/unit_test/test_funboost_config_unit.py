"""
Funboost 入口配置单元测试模块。
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import funboost_config
import nb_log_config
from src.infrastructure.logging.logging_entry_environment_bridge import (
    LoggingEntryEnvironmentBridge,
)
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment

PYPROJECT_PATH = Path(__file__).resolve().parents[2] / "pyproject.toml"
PROJECT_ROOT_PATH = Path(__file__).resolve().parents[2]
PROJECT_LOG_PATH = PROJECT_ROOT_PATH / "logs"
FUNBOOST_PINNED_DEPENDENCY = '"funboost==54.8"'
LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE = "LOGGING_ENTRY_PROJECT_NAME"
LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE = "LOGGING_ENTRY_LOG_PATH"
FUNBOOST_ENV_PROJECT_NAME = "funboost-env-project"
NB_LOG_ENV_LOG_DIRECTORY = "nb-log-env"
FUNBOOST_TYPED_PROJECT_NAME = "funboost-typed-project"
NB_LOG_TYPED_LOG_DIRECTORY = "nb-log-typed"


class TestFunboostConfigUnit:
    """
    Funboost 入口配置单元测试集合。
    """

    def test_funboost_entry_settings_should_drive_project_name(self) -> None:
        """
        验证 Funboost 第三方入口使用强类型配置提供项目名。
        """

        settings = funboost_config.FunboostEntrySettings()

        assert settings.project_name == funboost_config.FUNBOOST_PROJECT_NAME
        assert (
            funboost_config.FunboostCommonConfig.PROJECT_NAME
            == funboost_config.FUNBOOST_PROJECT_NAME
        )

    def test_pyproject_should_pin_funboost_dependency(self) -> None:
        """
        验证 Funboost 依赖版本固定。
        """

        pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")

        assert FUNBOOST_PINNED_DEPENDENCY in pyproject_text

    def test_nb_log_config_should_use_project_log_path_and_disable_print_patch(
        self,
    ) -> None:
        """
        验证 nb_log 覆盖文件固定项目日志目录并关闭 print patch。
        """

        assert Path(nb_log_config.LOG_PATH) == PROJECT_LOG_PATH
        assert nb_log_config.AUTO_PATCH_PRINT is False

    def test_funboost_entry_settings_should_read_environment(
        self,
        monkeypatch,
    ) -> None:
        """
        验证 Funboost 第三方入口项目名可由环境变量驱动。
        """

        monkeypatch.setenv(
            LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE,
            FUNBOOST_ENV_PROJECT_NAME,
        )

        reloaded_module = importlib.reload(funboost_config)
        try:
            assert reloaded_module.FunboostEntrySettings().project_name == (
                FUNBOOST_ENV_PROJECT_NAME
            )
            assert reloaded_module.FunboostCommonConfig.PROJECT_NAME == (FUNBOOST_ENV_PROJECT_NAME)
        finally:
            monkeypatch.delenv(
                LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE,
                raising=False,
            )
            importlib.reload(funboost_config)

    def test_nb_log_config_should_read_environment(
        self,
        monkeypatch,
    ) -> None:
        """
        验证 nb_log 第三方入口日志路径可由环境变量驱动。
        """

        monkeypatch.setenv(
            LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE,
            NB_LOG_ENV_LOG_DIRECTORY,
        )

        reloaded_module = importlib.reload(nb_log_config)
        try:
            assert Path(reloaded_module.LOG_PATH) == (PROJECT_ROOT_PATH / NB_LOG_ENV_LOG_DIRECTORY)
        finally:
            monkeypatch.delenv(
                LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE,
                raising=False,
            )
            importlib.reload(nb_log_config)

    def test_logging_runtime_should_bridge_to_third_party_entry_modules(
        self,
        monkeypatch,
    ) -> None:
        """
        验证日志运行时强类型配置应桥接到第三方入口模块。
        """

        monkeypatch.delenv(
            LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE,
            raising=False,
        )
        monkeypatch.delenv(
            LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE,
            raising=False,
        )
        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={
                "runtime": {
                    "logging": {
                        "entry_project_name": FUNBOOST_TYPED_PROJECT_NAME,
                        "entry_log_path": NB_LOG_TYPED_LOG_DIRECTORY,
                    }
                }
            },
        )

        LoggingEntryEnvironmentBridge().apply(settings.runtime.logging)

        try:
            assert (
                os.environ[LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE]
                == FUNBOOST_TYPED_PROJECT_NAME
            )
            assert (
                os.environ[LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE]
                == NB_LOG_TYPED_LOG_DIRECTORY
            )
            assert funboost_config.FunboostCommonConfig.PROJECT_NAME == (
                FUNBOOST_TYPED_PROJECT_NAME
            )
            assert Path(nb_log_config.LOG_PATH) == (PROJECT_ROOT_PATH / NB_LOG_TYPED_LOG_DIRECTORY)
        finally:
            os.environ.pop(LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE, None)
            os.environ.pop(LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE, None)
            importlib.reload(funboost_config)
            importlib.reload(nb_log_config)
