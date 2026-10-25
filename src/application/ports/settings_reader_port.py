"""
配置读取应用端口。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from src.core.http_contract.runtime_resource_contract import RuntimeResourceState


@dataclass(slots=True)
class ApplicationSettingsSnapshot:
    """
    应用配置只读快照。
    """

    application_name: str
    version: str
    environment: str
    system_overview_title: str
    ready_probe_enabled: bool
    enabled_modules: list[str]
    ready: bool
    runtime_states: list[RuntimeResourceState]


@dataclass(frozen=True, slots=True)
class HealthSettingsSnapshot:
    """生命周期发布的不可变轻量快照；读取无需I/O或资源锁。"""

    ready_probe_enabled: bool
    ready: bool
    version: str
    environment: str


class SettingsReaderPort(Protocol):
    """
    配置读取端口。
    """

    def read_health_snapshot(self) -> HealthSettingsSnapshot:
        """读取最后一次生命周期发布的健康事实。"""
        ...

    def read_application_settings_snapshot(self) -> ApplicationSettingsSnapshot:
        """
        读取应用配置只读快照。
        """
