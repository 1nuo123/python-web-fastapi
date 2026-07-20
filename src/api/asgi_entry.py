"""
ASGI 入口接口层模块。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI

from src.api.fastapi_app_assembler import FastApiAppAssembler
from src.api.task_binding_provider import ApplicationTaskBindingProvider
from src.infrastructure.persistence.database_engine_factory_contract import (
    DatabaseEngineFactory,
)
from src.infrastructure.settings.application_settings import (
    AppEnvironment,
)
from src.infrastructure.settings.raw_application_settings import SettingsOverrideMapping
from src.infrastructure.task.task_registration_registry import BaseModelTaskBinding


@dataclass(slots=True)
class AsgiApplicationFactory:
    """
    ASGI 应用工厂。
    """

    assembler: FastApiAppAssembler
    task_binding_provider: ApplicationTaskBindingProvider

    def __call__(
        self,
        *,
        environment: AppEnvironment | None = None,
        config_root: str | Path = "config",
        settings_overrides: SettingsOverrideMapping | None = None,
        task_bindings: list[BaseModelTaskBinding] | None = None,
        database_engine_factory: DatabaseEngineFactory | None = None,
    ) -> FastAPI:
        """
        构建 ASGI 应用。
        """

        return self.assembler(
            environment=environment,
            config_root=config_root,
            settings_overrides=settings_overrides,
            task_bindings=task_bindings,
            task_binding_provider=self.task_binding_provider,
            database_engine_factory=database_engine_factory,
        )


create_app = AsgiApplicationFactory(
    assembler=FastApiAppAssembler(),
    task_binding_provider=ApplicationTaskBindingProvider(),
)
