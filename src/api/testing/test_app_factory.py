"""
测试应用组合根工厂。
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from enum import StrEnum
from typing import cast

from fastapi import FastAPI

from src.api.fastapi_app_assembler import FastApiAppAssembler
from src.api.testing.demo_task_binding_factory import (
    DEMO_FUNBOOST_TASK_KIND,
    DEMO_TASK_KIND,
    DemoTaskBindingFactory,
)
from src.infrastructure.persistence.database_engine_factory_contract import (
    DatabaseEngineFactory,
)
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
)
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping
from src.infrastructure.settings.settings_mapping_merger import (
    SettingsMappingInput,
    SettingsMappingMerger,
)
from src.infrastructure.task.task_registration_registry import BaseModelTaskBinding
from src.infrastructure.testing.sqlite_test_engine_factory import (
    SqliteTestEngineFactory,
)

TEST_PERSISTENCE_BACKEND_SQLITE = "sqlite"
TEST_PERSISTENCE_BACKEND_CONFIGURED = "configured"


class TestPersistenceBackend(StrEnum):
    """测试应用持久化后端。"""

    SQLITE = TEST_PERSISTENCE_BACKEND_SQLITE
    CONFIGURED = TEST_PERSISTENCE_BACKEND_CONFIGURED


class TestPersistenceBackendSelector:
    """按当前测试上下文选择持久化后端。"""

    _backend: ContextVar[TestPersistenceBackend] = ContextVar(
        "test_persistence_backend",
        default=TestPersistenceBackend.SQLITE,
    )

    @classmethod
    def read(cls) -> TestPersistenceBackend:
        """读取当前测试持久化后端。"""

        return cls._backend.get()

    @classmethod
    def activate(
        cls,
        backend: TestPersistenceBackend,
    ) -> Token[TestPersistenceBackend]:
        """激活当前测试的持久化后端。"""

        return cls._backend.set(backend)

    @classmethod
    def reset(cls, token: Token[TestPersistenceBackend]) -> None:
        """恢复进入当前测试前的持久化后端。"""

        cls._backend.reset(token)


DEMO_TASK_MODULE_OVERRIDES: SettingsOverrideMapping = {
    "task_module": {
        "default_retry_limit": 1,
        "default_job_kind": DEMO_TASK_KIND,
        "registrations": [
            {
                "envelope_kind": "task_registration_envelope",
                "schema_version": "1.0",
                "header": {
                    "header_kind": "task_registration_header",
                    "schema_version": "1.0",
                    "task_name": DEMO_TASK_KIND,
                    "job_kind": DEMO_TASK_KIND,
                    "enabled": True,
                    "backend": "local",
                },
                "detail": {
                    "kind": "local",
                    "schema_version": "1.0",
                    "retry_limit": 1,
                },
            },
            {
                "envelope_kind": "task_registration_envelope",
                "schema_version": "1.0",
                "header": {
                    "header_kind": "task_registration_header",
                    "schema_version": "1.0",
                    "task_name": DEMO_FUNBOOST_TASK_KIND,
                    "job_kind": DEMO_FUNBOOST_TASK_KIND,
                    "enabled": True,
                    "backend": "funboost",
                },
                "detail": {
                    "kind": "funboost",
                    "schema_version": "1.0",
                    "queue_name": "demo_task_funboost_queue_test",
                    "exchange_name": "task.direct",
                    "routing_key": "demo.task.funboost.test",
                    "broker_kind": "RABBITMQ_COMPLEX_ROUTING",
                    "retry_limit": 1,
                    "consumer_worker_count": 1,
                },
            },
        ],
    }
}


class TestAppFactory:
    """
    测试应用测试集合，用于组织同一主题下的测试场景。
    """

    def create(
        self,
        *,
        overrides: SettingsOverrideMapping | None = None,
        task_bindings: list[BaseModelTaskBinding] | None = None,
        persistence_backend: TestPersistenceBackend | None = None,
        database_engine_factory: DatabaseEngineFactory | None = None,
    ) -> FastAPI:
        """
        处理创建。

        :param overrides: 覆盖配置映射，会在文件配置基础上递归合并。默认值：`None`。约束：需符合 ``SettingsOverrideMapping | None`` 注解。
        :type overrides: SettingsOverrideMapping | None
        :returns: 返回当前操作结果。
        :rtype: FastAPI
        """

        resolved_persistence_backend = persistence_backend or TestPersistenceBackendSelector.read()
        return FastApiAppAssembler()(
            environment=AppEnvironment.TEST,
            settings_overrides=self._merge_demo_task_overrides(overrides),
            task_bindings=(
                list(task_bindings)
                if task_bindings is not None
                else DemoTaskBindingFactory().build()
            ),
            database_engine_factory=database_engine_factory
            or (
                SqliteTestEngineFactory()
                if resolved_persistence_backend == TestPersistenceBackend.SQLITE
                else None
            ),
        )

    def _merge_demo_task_overrides(
        self,
        overrides: SettingsOverrideMapping | None,
    ) -> SettingsOverrideMapping:
        if overrides is None:
            return DEMO_TASK_MODULE_OVERRIDES
        return cast(
            SettingsOverrideMapping,
            SettingsMappingMerger().merge(
                cast(SettingsMappingInput, DEMO_TASK_MODULE_OVERRIDES),
                cast(SettingsMappingInput, overrides),
            ),
        )
