"""
可观测性初始化测试模块。
"""

from __future__ import annotations

from typing import cast

from fastapi.testclient import TestClient

from src.api.testing.test_app_factory import TestAppFactory
from src.infrastructure.settings.app_settings_loader import (
    AppSettingsLoader,
)
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
)
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping

METRICS_PATH = "/metrics"
RUNTIME_SECTION = "runtime"
METRICS_SECTION = "metrics"
HEADER_SECTION = "header"
ENABLED_FIELD = "enabled"


class TestObservabilityInitialization:
    """
    可观测性初始化测试集合。
    """

    def test_default_test_settings_should_disable_metrics(self) -> None:
        """
        验证测试环境默认关闭 metrics。
        """

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.TEST)

        assert settings.runtime.metrics.header.enabled is False

    def test_development_settings_should_enable_metrics_for_local_observability_stack(self) -> None:
        """
        验证 development profile 为本地 Prometheus 显式暴露指标路由。
        """

        settings = AppSettingsLoader().load_for_environment(AppEnvironment.DEVELOPMENT)

        assert settings.runtime.metrics.header.enabled is True
        assert settings.runtime.metrics.detail.metrics_path == METRICS_PATH

    def test_enabled_metrics_should_register_route(self) -> None:
        """
        验证开启 metrics 时应用会注册指标路由。
        """

        app = TestAppFactory().create(overrides=self._build_metrics_override(True))
        with TestClient(app) as client:
            response = client.get(METRICS_PATH)

        assert response.status_code == 200

    def _build_metrics_override(self, enabled: bool) -> SettingsOverrideMapping:
        """
        构建 metrics 开关覆盖配置。

        :param enabled: 是否启用 metrics。
        :type enabled: bool
        :returns: 配置覆盖映射。
        :rtype: SettingsOverrideMapping
        """

        return cast(
            SettingsOverrideMapping,
            {
                RUNTIME_SECTION: {
                    METRICS_SECTION: {
                        HEADER_SECTION: {
                            ENABLED_FIELD: enabled,
                        }
                    }
                }
            },
        )
