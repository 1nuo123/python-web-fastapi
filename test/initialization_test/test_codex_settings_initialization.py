"""Codex 配置初始化测试。"""

import pytest

from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment


class TestCodexSettingsInitialization:
    def test_settings_when_test_environment_should_load_phase1_defaults(self) -> None:
        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)

        assert settings.modules.codex_control.personal_mvp_only is True
        assert settings.runtime.codex_control.agent_heartbeat_seconds == 10
        assert settings.runtime.codex_control.max_connected_agents == 1
        assert settings.runtime.codex_control.allowed_codex_versions == [
            "0.145.0",
        ]

    def test_settings_when_offline_boundary_not_after_heartbeat_should_fail(self) -> None:
        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "runtime": {
                        "codex_control": {
                            "agent_offline_after_seconds": 10,
                        }
                    }
                },
            )

        assert "agent_offline_after_seconds" in str(fault.value.detail)

    def test_settings_when_reconnect_max_below_min_should_fail(self) -> None:
        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "runtime": {
                        "codex_control": {
                            "agent_reconnect_min_seconds": 31,
                            "agent_reconnect_max_seconds": 30,
                        }
                    }
                },
            )

        assert "agent_reconnect_max_seconds" in str(fault.value.detail)
