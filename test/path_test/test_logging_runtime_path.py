"""
测试日志运行时路径测试模块。
"""

from __future__ import annotations

import pytest

from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
)

LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE = "LOGGING_ENTRY_PROJECT_NAME"
LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE = "LOGGING_ENTRY_LOG_PATH"
LOGGING_TEST_PROJECT_NAME = "logging-runtime-test"
LOGGING_TEST_LOG_PATH = "logs/runtime-test"


class TestLoggingRuntimePath:
    """
    测试日志运行时路径测试集合，用于组织同一主题下的测试场景。
    """

    def test_loader_should_load_logging_runtime(self) -> None:
        """
        验证加载器应加载日志运行时配置。
        """

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)
        assert settings.runtime.logging.enabled is True
        assert settings.runtime.logging.sink.value == "database"
        assert settings.runtime.logging.entry_project_name == "fastapi_web_skeleton"
        assert settings.runtime.logging.entry_log_path == "logs"

    def test_loader_when_logging_sink_detail_invalid_should_fail(self) -> None:
        """
        验证加载器当日志扩展配置无效应失败。
        """

        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "runtime": {
                        "logging": {
                            "sink_detail": {
                                "kind": "database",
                                "schema_version": "1.0",
                                "table_name": "",
                                "flush_interval_seconds": 1,
                                "max_batch_size": 1,
                                "fallback_to_stdout": True,
                                "retention_days": 7,
                            }
                        }
                    }
                },
            )
        assert "table_name" in str(fault.value.detail)

    def test_loader_when_logging_level_changed_should_support_hot_reload(self) -> None:
        """
        验证加载器当日志级别变更应支持热更新。
        """

        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={"runtime": {"logging": {"level": "ERROR"}}},
        )
        assert settings.runtime.logging.level.value == "ERROR"

    def test_loader_when_logging_entry_env_present_should_override_runtime(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """
        验证第三方日志入口配置可由环境变量覆盖。
        """

        monkeypatch.setenv(
            LOGGING_ENTRY_PROJECT_NAME_ENVIRONMENT_VARIABLE,
            LOGGING_TEST_PROJECT_NAME,
        )
        monkeypatch.setenv(
            LOGGING_ENTRY_LOG_PATH_ENVIRONMENT_VARIABLE,
            LOGGING_TEST_LOG_PATH,
        )

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)

        assert settings.runtime.logging.entry_project_name == LOGGING_TEST_PROJECT_NAME
        assert settings.runtime.logging.entry_log_path == LOGGING_TEST_LOG_PATH
