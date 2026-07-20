"""
FastAPI 应用装配器单元测试模块。
"""

from __future__ import annotations

from src.api.fastapi_app_assembler import FastApiAppAssembler
from src.api.task_binding_provider import ApplicationTaskBindingProvider
from src.api.testing.demo_task_binding_factory import (
    DEMO_TASK_KIND,
)
from src.api.testing.test_app_factory import TestAppFactory
from src.infrastructure.settings.application_settings import AppEnvironment


class TestFastApiAppAssemblerUnit:
    """
    FastAPI 应用装配器单元测试集合。
    """

    def test_assembler_without_task_bindings_should_not_inject_demo_binding(self) -> None:
        """
        验证应用装配器未传任务绑定时不再注入示例任务。
        """

        app = FastApiAppAssembler()(environment=AppEnvironment.TEST)
        registry = app.state.container.resource_mount.get_task_registration_registry()

        assert registry.list_bindings() == []

    def test_test_app_factory_should_inject_demo_binding_explicitly(self) -> None:
        """
        验证测试应用工厂显式注入示例任务绑定。
        """

        app = TestAppFactory().create()
        registry = app.state.container.resource_mount.get_task_registration_registry()
        binding_job_kinds = {binding.job_kind for binding in registry.list_bindings()}

        assert DEMO_TASK_KIND in binding_job_kinds

    def test_assembler_with_provider_should_filter_binding_not_declared_in_environment(
        self,
    ) -> None:
        """
        验证主入口只注册当前环境配置已声明的任务。
        """

        app = FastApiAppAssembler()(
            environment=AppEnvironment.TEST,
            task_binding_provider=ApplicationTaskBindingProvider(),
        )
        registry = app.state.container.resource_mount.get_task_registration_registry()

        assert registry.list_bindings() == []
