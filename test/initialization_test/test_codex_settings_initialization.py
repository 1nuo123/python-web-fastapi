"""Codex 配置初始化测试。"""

import pytest

from src.core.codex_contract.agent_release_manifest_contract import (
    CodexAgentReleaseDistributionMode,
)
from src.core.exception_contract.http_fault_contract import HttpFaultException
from src.infrastructure.settings.app_settings_loader import AppSettingsLoader
from src.infrastructure.settings.application_settings import AppEnvironment


class TestCodexSettingsInitialization:
    def test_settings_when_test_environment_should_load_phase1_defaults(self) -> None:
        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)

        assert settings.modules.codex_control.personal_mvp_only is True
        assert settings.runtime.codex_control.agent_heartbeat_seconds == 15
        assert settings.runtime.codex_control.turn_runtime_lease_ttl_seconds == 60
        assert settings.runtime.codex_control.turn_runtime_watchdog_seconds == 15
        assert settings.runtime.codex_control.turn_runtime_stalled_after_seconds == 90
        assert not settings.runtime.codex_control.client_diagnostic_error_collection_enabled
        assert not settings.runtime.codex_control.client_diagnostic_performance_collection_enabled
        assert settings.runtime.codex_control.client_diagnostic_performance_sample_rate == 0.1
        assert settings.runtime.codex_control.client_diagnostic_cleanup_interval_seconds == 3600
        assert settings.runtime.codex_control.client_diagnostic_error_retention_days == 14
        assert settings.runtime.codex_control.client_diagnostic_performance_retention_days == 30
        assert not settings.runtime.codex_control.codex_scroll_controller_v2
        assert not settings.runtime.codex_control.codex_realtime_batch_v2
        assert not settings.runtime.codex_control.codex_authority_recovery_v2
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

    def test_experience_flags_can_be_enabled_independently(self) -> None:
        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={
                "runtime": {
                    "codex_control": {
                        "codex_scroll_controller_v2": True,
                        "codex_realtime_batch_v2": False,
                        "codex_authority_recovery_v2": True,
                    }
                }
            },
        )

        assert settings.runtime.codex_control.codex_scroll_controller_v2
        assert not settings.runtime.codex_control.codex_realtime_batch_v2
        assert settings.runtime.codex_control.codex_authority_recovery_v2

    def test_settings_when_internal_agent_release_is_versioned_should_load(self) -> None:
        settings = AppSettingsLoader().load_from_mapping(
            environment=AppEnvironment.TEST,
            overrides={
                "runtime": {
                    "codex_control": {
                        "agent_release_version": "0.1.16",
                        "agent_release_distribution_mode": "internal",
                        "agent_release_artifact_sha256": "a" * 64,
                        "agent_release_download_url": (
                            "https://github.com/acme/codex-agent/releases/download/"
                            "v0.1.16/CodexRemoteAgent.msi"
                        ),
                        "agent_release_manifest_url": (
                            "https://github.com/acme/codex-agent/releases/download/"
                            "v0.1.16/internal-release.json"
                        ),
                        "agent_release_minimum_security_version": "0.1.16",
                    }
                }
            },
        )

        release = settings.runtime.codex_control
        assert release.agent_release_distribution_mode is CodexAgentReleaseDistributionMode.INTERNAL
        assert release.agent_release_artifact_sha256 == "a" * 64

    def test_settings_when_internal_agent_release_uses_mutable_branch_should_fail(self) -> None:
        with pytest.raises(HttpFaultException) as fault:
            AppSettingsLoader().load_from_mapping(
                environment=AppEnvironment.TEST,
                overrides={
                    "runtime": {
                        "codex_control": {
                            "agent_release_version": "0.1.16",
                            "agent_release_distribution_mode": "internal",
                            "agent_release_artifact_sha256": "a" * 64,
                            "agent_release_download_url": (
                                "https://raw.githubusercontent.com/acme/codex-agent/"
                                "master/releases/0.1.16/CodexRemoteAgent.msi"
                            ),
                            "agent_release_manifest_url": (
                                "https://github.com/acme/codex-agent/releases/download/"
                                "v0.1.16/internal-release.json"
                            ),
                            "agent_release_minimum_security_version": "0.1.16",
                        }
                    }
                },
            )

        assert "可变路径" in str(fault.value.detail)

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
