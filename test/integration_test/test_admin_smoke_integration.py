"""
管理员服务端冒烟集成测试模块。
"""

from __future__ import annotations

from http import HTTPStatus

import pytest
from fastapi.testclient import TestClient

from src.api.fastapi_app_assembler import FastApiAppAssembler
from src.api.testing.demo_task_binding_factory import DEMO_TASK_KIND
from src.core.task_contract.task_runtime_contract import TaskBackend
from src.infrastructure.settings.application_settings import AppEnvironment

pytestmark = [
    pytest.mark.integration,
    pytest.mark.postgres,
    pytest.mark.usefixtures("integration_database"),
]


HEALTH_LIVE_PATH = "/health/live"


class TestAdminSmokeIntegration:
    """
    管理员服务端冒烟集成测试集合。
    """

    def test_default_app_should_start_and_serve_live_probe(self) -> None:
        """
        验证默认应用可完成 lifespan 并服务存活探针。
        """

        app = FastApiAppAssembler()(environment=AppEnvironment.TEST)

        with TestClient(app) as client:
            response = client.get(HEALTH_LIVE_PATH)

        assert response.status_code == HTTPStatus.OK

    def test_default_demo_task_should_stay_disabled_without_handler_binding(self) -> None:
        """
        验证默认示例任务保持禁用且未隐式注入 handler。
        """

        app = FastApiAppAssembler()(environment=AppEnvironment.TEST)
        registry = app.state.container.resource_mount.get_task_registration_registry()
        registrations = registry.list_registrations_by_backend(TaskBackend.LOCAL)
        demo_registration = next(
            registration
            for registration in registrations
            if registration.header.job_kind == DEMO_TASK_KIND
        )

        assert demo_registration.header.enabled is False
        assert registry.list_bindings() == []
